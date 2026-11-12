"""Exercise the real runner/QC/SQL path; replace only the paid agent call."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from cart_db import ingest, ingest_schema, pipeline
from cart_db.extraction import load_document
from cart_db.identity import compare, strong_key
from cart_db.manufacturing import dimensions
from cart_db.postprocess import normalize_record
from test_ingest import db, test_dsn, binder, evidence, write, stage, count


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extraction_runner", ROOT / "scripts/run_extraction_agent.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def mock_document_classification(monkeypatch):
    from test_document_classification import receipt
    monkeypatch.setattr(runner, "classify_document", lambda path, **kw: receipt(path))


# Build a duration measurement fixture with raw source wording.
def measurement(value, unit=None):
    # Use empty text when unit is missing or empty.
    return dict(kind="single_value", value=value, unit=unit, raw=f"合成示例：{value} {unit or ''}")


# Build a synthetic manufacturing protocol with explicit identity dimensions.
def process(name="工艺甲"):
    return dict(
        manufacturing_id="m", name=name, t_cell_source="自体", cd4_cd8_ratio=measurement(1),
        selection_steps=[dict(input="PBMC", output="T细胞", method="合成分选步骤", reagents=[])],
        activation_method="CD3/CD28，珠细胞比1:1",
        reagents=[dict(reagent_name="CD3/CD28磁珠", reagent_type="activation_reagent", amount=measurement(1, "ratio"))],
        vector_type="慢病毒", moi=measurement(5),
        transduction_transfection_conditions=dict(time_after_activation=measurement(24, "h"),
                                                   enhancer_used=False, spinoculation=False,
                                                   contact_duration=measurement(6, "h")),
        culture_system=dict(container="培养袋", culture_mode="静态", openness="closed",
                            automation="manual", culture_medium="合成培养基甲"),
        cytokine_combination=[dict(cytokine_name="IL-7", concentration=measurement(10, "ng/mL"))],
        culture_duration=measurement(7, "day"),
        formulation=dict(fill_volume=measurement(10, "mL"), cell_concentration=measurement(1000000, "cells/mL"),
                         total_dose=measurement(10000000, "cells")),
    )


# Verify that manufacturing complete new match distinct and names.
def test_manufacturing_complete_new_match_distinct_and_names(db, tmp_path):
    first = process()
    bid, _ = stage(db, write(tmp_path, [dict(table="manufacturing", data=first)]))
    assert ingest.publish(db, bid)["counts"]["published"] == 1
    second = process("工艺别名")
    bid2, _ = stage(db, write(tmp_path, [dict(table="manufacturing", data=second)], "second.jsonl"))
    assert ingest.publish(db, bid2)["counts"]["published"] == 1
    assert count(db, "manufacturing") == 1
    assert count(db, "entity_name") == 2
    second["culture_duration"] = measurement(9, "day")
    bid3, _ = stage(db, write(tmp_path, [dict(table="manufacturing", data=second)], "different.jsonl"))
    assert ingest.publish(db, bid3)["counts"]["published"] == 1
    assert count(db, "manufacturing") == 2


# Verify that manufacturing missing methods are admitted.
@pytest.mark.parametrize("field", ["selection_steps", "activation_method", "culture_duration", "culture_system"])
def test_manufacturing_missing_methods_are_admitted(db, tmp_path, field):
    data = process()
    data[field] = None
    bid, _ = stage(db, write(tmp_path, [dict(table="manufacturing", data=data)]))
    report = ingest.publish(db, bid)
    assert report["counts"] == dict(published=1, pending=0, invalid=0)
    assert report["identity_counts"]["resolved"] == 1


# Verify that optional process parameters do not control identity.
def test_optional_process_parameters_do_not_control_identity():
    data, _ = normalize_record("manufacturing", process())
    assert strong_key("manufacturing", data)
    other = deepcopy(data)
    # Process each declared item independently, preserving the order established by this collection.
    for field in ("t_cell_source", "cd4_cd8_ratio", "reagents", "moi", "transduction_transfection_conditions", "cytokine_combination", "formulation", "cryopreservation_conditions"):
        other[field] = None
    assert compare("manufacturing", data, other)["verdict"] == "same"
    other["culture_system"]["container"] = "生物反应器"
    assert compare("manufacturing", data, other)["verdict"] == "similar"


# Verify that duration raw context stays distinct from similarity.
def test_duration_raw_context_stays_distinct_from_similarity():
    data, _ = normalize_record("manufacturing", process())
    other = deepcopy(data)
    other["culture_duration"]["raw"] = "转导后7天，而非从培养开始计算"
    assert compare("manufacturing", data, other)["verdict"] == "similar"


# Provide an extraction test double that writes known artifacts instead of calling a model.
@pytest.fixture
def agent(monkeypatch):
    calls = []

    # Replace an external dependency with a deterministic fixture implementation.
    def fake(path, *, out_dir, **kwargs):
        calls.append(path)
        assert "合成" in load_document(path)
        write(out_dir, [binder(name="合成结合域"), evidence()])
        (out_dir / "reasoning.md").write_text("合成流程测试，不调用模型。", encoding="utf-8")
        # Synthetic source has no figures; record an explicit completed empty inventory.
        (out_dir / "figures.jsonl").write_text("")
        (out_dir / "img").mkdir(exist_ok=True)
        return dict(ok=True, reason="", cost=0.0, usage=runner.empty_usage(), usage_known=True, seconds=0)

    monkeypatch.setattr(runner, "_run_agent", fake)
    return calls


# Run the test's importer or pipeline operation using isolated inputs and injected dependencies.
def run(path, out_dir, **kwargs):
    return pipeline.run_document(path, extract=runner.run_one, out_dir=out_dir,
                                 timeout=30, budget=None, agent="codex", model="test-only", env={}, **kwargs)


# Create a temporary document used by extraction-resume tests.
def source(tmp_path, suffix="xml"):
    path = tmp_path / ("paper." + suffix)
    path.write_text("<article><body><p>合成数据</p></body></article>", encoding="utf-8")
    return path


# Redirect the pipeline connection factory to the isolated test database.
@pytest.fixture
def connection(db, test_dsn, monkeypatch):
    # The callback returns psycopg.connect(**test_dsn, autocommit=True).
    monkeypatch.setattr(ingest, "connect", lambda: psycopg.connect(**test_dsn, autocommit=True))
    return db


# Verify that pipeline real qc database and resume.
def test_pipeline_real_qc_database_and_resume(connection, tmp_path, agent):
    path = source(tmp_path)
    out = tmp_path / "output"
    messages = []
    result = run(path, out, on_status=messages.append)
    assert result["ok"]
    assert result["database"]["counts"] == dict(published=2, pending=0, invalid=0)
    assert result["database"]["actions"]["new_entities"] == 1
    raw = json.loads((out / "paper/original.jsonl").read_text().splitlines()[0])
    final = json.loads((out / "paper/data.jsonl").read_text().splitlines()[0])
    assert raw["data"]["binder_id"] == "b"
    assert final["data"]["binder_id"] != "b"
    manifest = json.loads((out / "paper/source_manifest.json").read_text())
    assert manifest["source_sha256"] == pipeline.checksum(path)
    assert connection.execute("SELECT count(*) FROM cart.import_context").fetchone()[0] == 4
    repeated = run(path, out)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert repeated["extraction_reused"] and len(agent) == 1
    assert not any(repeated["database"]["actions"].values())
    assert count(connection, "evidence") == 1
    # Build mapped values from messages.
    assert any("规范化" in message for message in messages)
    # Build mapped values from messages.
    assert any("数据库处理完成" in message for message in messages)


# Verify that db failure after commit resumes without model or duplicate.
def test_db_failure_after_commit_resumes_without_model_or_duplicate(connection, tmp_path, agent, monkeypatch):
    real_publish = ingest.publish

    # Simulate interruption after publication to verify safe retry without duplicate rows.
    def interrupt(conn, batch, **kwargs):
        real_publish(conn, batch, **kwargs)
        raise OSError("simulated disconnect after commit")

    monkeypatch.setattr(ingest, "publish", interrupt)
    path, out = source(tmp_path), tmp_path / "output"
    failed = run(path, out)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert not failed["ok"] and (out / "paper/data.jsonl").exists()
    monkeypatch.setattr(ingest, "publish", real_publish)
    result = run(path, out)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert result["ok"] and len(agent) == 1
    assert count(connection, "evidence") == 1


# Verify that changed source or artifact cannot silently resume.
def test_changed_source_or_artifact_cannot_silently_resume(connection, tmp_path, agent):
    path, out = source(tmp_path), tmp_path / "output"
    assert run(path, out)["ok"]
    original = path.read_text()
    path.write_text(original + "\n")
    assert not run(path, out)["ok"]
    assert len(agent) == 1
    path.write_text(original)
    (out / "paper/reasoning.md").write_text("修改后的来源依据")
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert not run(path, out)["ok"] and len(agent) == 1


# Verify that incomplete entity and dependants are published.
def test_incomplete_entity_and_dependants_are_published(connection, tmp_path, monkeypatch, agent):
    real = runner._run_agent

    # Write a QC-valid but identity-incomplete fixture to test separate admission.
    def incomplete(path, **kwargs):
        result = real(path, **kwargs)
        write(kwargs["out_dir"], [binder(sequence=None, name="只有名称"), evidence()])
        return result

    monkeypatch.setattr(runner, "_run_agent", incomplete)
    result = run(source(tmp_path), tmp_path / "output")
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert result["ok"] and result["database"]["counts"]["published"] == 2
    assert result["database"]["identity_counts"]["resolved"] == 1
    assert count(connection, "binder") == count(connection, "evidence") == 1


# Verify that runner full cli chinese and preflight.
def test_runner_full_cli_chinese_and_preflight(connection, tmp_path, monkeypatch, agent, capsys):
    monkeypatch.setattr(runner, "REPO", tmp_path)
    path = source(tmp_path)
    args = ["--file", str(path), "--out-dir", "results", "--agent", "codex", "--import-db", "--no-progress"]
    assert runner.main(args) == 0
    output = capsys.readouterr().out
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert "数据库准备完成" in output and "入库批次" in output
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert "新增实体 1 条" in output and "合计" in output
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert "Subagents:" not in output and "Workers:" not in output and "N/A" not in output
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert runner.main(args) == 0 and len(agent) == 1


# Verify that dry run never connects or calls model.
def test_dry_run_never_connects_or_calls_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "REPO", tmp_path)
    # The callback returns pytest.fail('dry-run connected').
    monkeypatch.setattr(ingest, "connect", lambda: pytest.fail("dry-run connected"))
    # The callback returns pytest.fail('dry-run called agent').
    monkeypatch.setattr(runner, "_run_agent", lambda *a, **k: pytest.fail("dry-run called agent"))
    assert runner.main(["--file", str(source(tmp_path)), "--import-db", "--dry-run"]) == 0
    assert "未调用模型" in capsys.readouterr().out


# Verify that database preflight fails before paid extraction.
def test_database_preflight_fails_before_paid_extraction(tmp_path, monkeypatch, agent, capsys):
    monkeypatch.setattr(runner, "REPO", tmp_path)

    # Simulate a failed database preflight before any paid extraction can begin.
    def unavailable():
        raise psycopg.OperationalError("test database unavailable")

    monkeypatch.setattr(ingest, "connect", unavailable)
    assert runner.main(["--file", str(source(tmp_path)), "--import-db"]) == 1
    assert not agent
    assert "尚未调用模型" in capsys.readouterr().err


# Verify that incremental migration retains v1 data and pending rows.
def test_incremental_migration_retains_v1_data_and_pending_rows(db, tmp_path):
    # Simulate a populated v1 database, including a pending normalized source claim.
    db.execute("DROP SCHEMA cart CASCADE")
    db.execute("CREATE SCHEMA cart")
    db.execute((ingest_schema.MIGRATIONS / "001_scientific_ingestion.sql").read_text())
    import hashlib
    db.execute("CREATE TABLE cart.schema_migration(version text PRIMARY KEY, checksum text NOT NULL)")
    path = ingest_schema.MIGRATIONS / "001_scientific_ingestion.sql"
    db.execute("INSERT INTO cart.schema_migration VALUES (%s,%s)", (path.name, hashlib.sha256(path.read_bytes()).hexdigest()))
    old_id = uuid4()
    db.execute("INSERT INTO cart.record(record_id,table_name) VALUES (%s,'manufacturing')", (old_id,))
    db.execute("INSERT INTO cart.manufacturing(manufacturing_id,name) VALUES (%s,'迁移前工艺')", (old_id,))
    ingest_schema.migrate(db)
    assert db.execute("SELECT name FROM cart.manufacturing WHERE manufacturing_id=%s",
                      (old_id,)).fetchone() == ("迁移前工艺",)
    # A pre-v2 normalized manufacturing claim has no newly added keys.
    bid, records = stage(db, write(tmp_path, [dict(table="manufacturing", data=dict(manufacturing_id="m"))]))
    db.execute("UPDATE cart.staged_record SET normalized=normalized-'process_step_status'-'harvest_steps'")
    ingest.decide(db, records[0]["stage_id"], "new", "测试审核人", "模拟旧批次的来源审核")
    assert ingest.publish(db, bid)["counts"]["published"] == 1
    assert count(db, "manufacturing") == 2


# Verify that pdf uses same existing extractor and importer.
def test_pdf_uses_same_existing_extractor_and_importer(connection, tmp_path, agent):
    import pymupdf
    path = tmp_path / "paper.pdf"
    # Close the PDF after extracting text from all pages.
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "合成数据", fontname="china-s")
        doc.save(path)
    result = run(path, tmp_path / "output")
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert result["ok"] and result["database"]["counts"]["published"] == 2
    assert agent == [path]


# Verify that validation failure preserves draft and never imports.
def test_validation_failure_preserves_draft_and_never_imports(connection, tmp_path, monkeypatch):
    # Return invalid extraction output to verify that it never reaches database staging.
    def invalid(path, *, out_dir, **kwargs):
        write(out_dir, [binder(), evidence(**{"binder.kd": dict(kind="single_value", value=True, unit="nM", raw="bad")})])
        (out_dir / "reasoning.md").write_text("合成无效数据")
        # Keep image artifacts valid so this test isolates scientific-value validation.
        (out_dir / "figures.jsonl").write_text("")
        (out_dir / "img").mkdir(exist_ok=True)
        return dict(ok=True, reason="", cost=0.0, usage=runner.empty_usage(), usage_known=True)
    monkeypatch.setattr(runner, "_run_agent", invalid)
    result = run(source(tmp_path), tmp_path / "output", validation_retries=0)
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert not result["ok"] and Path(result["draft_dir"]).is_dir()
    assert count(connection, "import_batch") == 0


# Verify that ingest chinese status and machine json.
def test_ingest_chinese_status_and_machine_json(connection, tmp_path, capsys):
    bid, _ = stage(connection, write(tmp_path, [binder()]))
    assert ingest.main(["publish", str(bid)]) == 0
    assert "已入库 1 条" in capsys.readouterr().out
    assert ingest.main(["--json", "status", str(bid)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"] == dict(published=1, pending=0, invalid=0)


# Verify that extraction transport exception never reports zero cost.
def test_extraction_transport_exception_never_reports_zero_cost(tmp_path):
    # Simulate a transport or connection failure rather than a successful empty result.
    def broken(*args, **kwargs):
        raise OSError("model transport disconnected")
    result = pipeline.run_document(source(tmp_path), extract=broken, out_dir=tmp_path / "output", env={})
    # Require all linked outcomes in this assertion; a partial success must still fail the test.
    assert not result["ok"] and result["cost"] is None and not result["usage_known"]
    assert "提取结果" in result["reason"]
