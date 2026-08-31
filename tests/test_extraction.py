"""文档读取与拆平逻辑的测试。不联网、不调模型。"""
import pytest

from cart_db.extraction import load_document, strip_xml_boilerplate

JATS = """<article>
  <front><article-title>Anti-CDH17 CAR-T</article-title></front>
  <body><p>SPR 测得 Kd = 2.4 nM。</p></body>
  <back>
    <ack><p>感谢基金支持。</p></ack>
    <ref-list><ref><mixed-citation>Smith 2020</mixed-citation></ref></ref-list>
  </back>
</article>"""


def test_strip_removes_back_matter():
    out = strip_xml_boilerplate(JATS)
    assert "Smith 2020" not in out
    assert "感谢基金支持" not in out


def test_strip_keeps_body_intact():
    out = strip_xml_boilerplate(JATS)
    assert "Kd = 2.4 nM" in out
    assert "Anti-CDH17 CAR-T" in out


def test_strip_removes_standalone_ref_list():
    xml = "<article><body><p>正文</p></body><ref-list><ref>X</ref></ref-list></article>"
    out = strip_xml_boilerplate(xml)
    assert "正文" in out
    assert "<ref>" not in out


def test_load_xml_file(tmp_path):
    path = tmp_path / "PMC1.xml"
    path.write_text(JATS, encoding="utf-8")
    text = load_document(path)
    assert "Kd = 2.4 nM" in text
    assert "Smith 2020" not in text


def test_load_nxml_extension(tmp_path):
    path = tmp_path / "PMC1.nxml"
    path.write_text(JATS, encoding="utf-8")
    assert "Kd = 2.4 nM" in load_document(path)


def test_load_markdown_verbatim(tmp_path):
    """Markdown 已经是纯文本，原样送进去，不做任何剥离。"""
    path = tmp_path / "note.md"
    path.write_text("# 实验记录\n\nKd = 2.4 nM\n\n<ref-list>保留</ref-list>\n", encoding="utf-8")
    text = load_document(path)
    assert "# 实验记录" in text
    assert "Kd = 2.4 nM" in text
    assert "<ref-list>保留</ref-list>" in text


def test_load_markdown_alias_extension(tmp_path):
    path = tmp_path / "note.markdown"
    path.write_text("Kd = 2.4 nM\n", encoding="utf-8")
    assert "Kd = 2.4 nM" in load_document(path)


def test_unknown_extension_raises(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件格式"):
        load_document(path)


from cart_db.extraction import flatten
from cart_db.schema_models import load_schema

SCHEMA = load_schema()
Extraction = SCHEMA.extraction
Combination = Extraction.model_fields["combinations"].annotation.__args__[0]


def _entity(kind):
    return next(e for e in SCHEMA.entities if e.kind == kind)


def _ev(kind, **kw):
    """一条能通过校验的最小证据。"""
    model = _entity(kind).evidence_model
    return model(source_type="literature", source_id="PMC1",
                 evidence_level="同行評議", **kw)


def _shared_ev(**kw):
    """组合实验用的证据（只有共享字段）。"""
    model = Combination.model_fields["experiments"].annotation.__args__[0]
    return model(source_type="literature", source_id="PMC1",
                 evidence_level="同行評議", **kw)


def _rows_of(rows, table):
    return [r for r in rows if r.table == table]


def test_evidence_points_at_its_own_binder():
    Binder = _entity("binder").model
    ex = Extraction(binders=[
        Binder(name="ARB-202", target_antigen="CDH17",
               evidence=[_ev("binder", kd=2.4, measurement_method="SPR")]),
        Binder(name="5F9", evidence=[_ev("binder", kd=40.0)]),
    ])
    rows = flatten(ex)
    binders = _rows_of(rows, "binder")
    by_kd = {e.data["binder.kd"]: e for e in _rows_of(rows, "evidence")}

    assert len(binders) == 2
    assert by_kd[2.4].data["binder.binder_id"] == binders[0].data["binder_id"]
    assert by_kd[40.0].data["binder.binder_id"] == binders[1].data["binder_id"]
    assert binders[0].data["binder_id"] != binders[1].data["binder_id"]


def test_evidence_carries_all_three_fk_columns():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["binder.binder_id"] is not None
    assert data["car.car_id"] is None
    assert data["manufacturing.manufacturing_id"] is None


def test_shared_fields_are_not_prefixed():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    data = _rows_of(flatten(ex), "evidence")[0].data
    assert data["source_id"] == "PMC1"
    assert "binder.source_id" not in data


def test_car_and_manufacturing_memory_phenotype_stay_apart():
    """同名字段必须写成两个不同的列，绝不能互相覆盖。"""
    Car = _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        cars=[Car(name="BBz", evidence=[_ev("car", memory_phenotype="Tcm 偏多")])],
        manufacturings=[Manufacturing(
            name="LV", evidence=[_ev("manufacturing", memory_phenotype="Tscm 偏多")])],
    )
    rows = _rows_of(flatten(ex), "evidence")
    values = {}
    for row in rows:
        values.update({k: v for k, v in row.data.items() if k.endswith("memory_phenotype")})
    assert values["car.memory_phenotype"] == "Tcm 偏多"
    assert values["manufacturing.memory_phenotype"] == "Tscm 偏多"


def test_json_fields_without_item_schema_stay_plain_strings():
    """没有 item_schema 的 json 字段现在是自由文本，flatten() 原样透传。"""
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(
        name="A",
        fr_cdr_regions="CDR-H3: ARDYW",
        evidence=[_ev("binder", measurement_conditions="温度: 25°C；缓冲液: PBS")],
    )])
    rows = flatten(ex)
    assert _rows_of(rows, "binder")[0].data["fr_cdr_regions"] == "CDR-H3: ARDYW"
    assert _rows_of(rows, "evidence")[0].data["binder.measurement_conditions"] == (
        "温度: 25°C；缓冲液: PBS")


def test_modules_stay_a_list():
    Car = _entity("car").model
    ex = Extraction(cars=[Car(name="BBz", modules=[
        {"module_type": "hinge", "source_molecule": "CD8a", "length": 45},
        {"module_type": "CD3zeta"},
    ])])
    modules = _rows_of(flatten(ex), "car")[0].data["modules"]
    assert isinstance(modules, list) and len(modules) == 2
    assert modules[0]["module_type"] == "hinge"


def test_entities_come_before_evidence():
    Binder = _entity("binder").model
    ex = Extraction(binders=[Binder(name="A", evidence=[_ev("binder")])])
    tables = [r.table for r in flatten(ex)]
    assert tables.index("binder") < tables.index("evidence")


def test_combination_resolves_indices_and_emits_one_evidence_row():
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A"), Binder(name="B")],
        cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV-MOI5")],
        combinations=[Combination(
            binder_index=1, car_index=0, manufacturing_index=0,
            completed_experiment_phase="in_vitro",
            experiments=[_shared_ev(outcomes="killing_rate: 85%")],
        )],
    )
    rows = flatten(ex)
    combo = _rows_of(rows, "abc_combination_db1")[0]
    evidence = _rows_of(rows, "evidence")[0]

    assert combo.data["binder_id"] == _rows_of(rows, "binder")[1].data["binder_id"]
    assert combo.data["completed_experiment_phase"] == "in_vitro"
    assert evidence.data["binder.binder_id"] == combo.data["binder_id"]
    assert evidence.data["car.car_id"] == combo.data["car_id"]
    assert evidence.data["manufacturing.manufacturing_id"] == combo.data["manufacturing_id"]
    assert evidence.data["outcomes"] == "killing_rate: 85%"


def test_out_of_range_combination_is_dropped(caplog):
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=7, car_index=0, manufacturing_index=0)],
    )
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "abc_combination_db1") == []
    assert "序号越界" in caplog.text


def test_negative_index_is_dropped():
    Binder, Car = _entity("binder").model, _entity("car").model
    Manufacturing = _entity("manufacturing").model
    ex = Extraction(
        binders=[Binder(name="A")], cars=[Car(name="BBz")],
        manufacturings=[Manufacturing(name="LV")],
        combinations=[Combination(binder_index=-1, car_index=0, manufacturing_index=0)],
    )
    assert _rows_of(flatten(ex), "abc_combination_db1") == []


def test_evidence_without_source_id_is_dropped(caplog):
    """source_id 字段现在是非 Optional 的 str，靠不传（吃默认值 None）表达缺失，
    而不是显式传 None —— 显式传 None 会被当成类型错误拒绝。"""
    Binder = _entity("binder").model
    model = _entity("binder").evidence_model
    ex = Extraction(binders=[Binder(name="A", evidence=[
        model(source_type="literature",
              evidence_level="同行評議", kd=2.4)])])
    with caplog.at_level("WARNING"):
        rows = flatten(ex)
    assert _rows_of(rows, "evidence") == []
    assert _rows_of(rows, "binder") != []       # 实体本身保留
    assert "出处" in caplog.text


def test_evidence_with_blank_evidence_level_is_dropped():
    Binder = _entity("binder").model
    model = _entity("binder").evidence_model
    ex = Extraction(binders=[Binder(name="A", evidence=[
        model(source_type="literature", source_id="PMC1", evidence_level="   ")])])
    assert _rows_of(flatten(ex), "evidence") == []


import json

from cart_db import extraction


def test_system_prompt_contains_rules_schema_and_output_guide():
    prompt = extraction.build_system_prompt()
    assert "biomedical data extraction agent" in prompt      # article_extraction_prompt.txt
    assert "target_antigen" in prompt                        # Schema_A.yaml
    assert "abc_combination_db1" in prompt                   # Schema_DB1.yaml
    assert "binder.kd" in prompt                             # Evidence.yaml
    assert "binder_index" in prompt                          # 输出格式说明


def test_system_prompt_is_stable_across_calls():
    """跨文档完全一致才能命中提示词缓存。"""
    assert extraction.build_system_prompt() == extraction.build_system_prompt()


def _fake_request(schema, **overrides):
    """按 schema（schema.requests 里的某个单字段模型）拼一个最小可用答案。

    每个请求模型只有一个字段，字段名即 `next(iter(schema.model_fields))`；
    没有指定覆盖值的字段一律给空列表。
    """
    field_name = next(iter(schema.model_fields))
    return schema(**{field_name: overrides.get(field_name, [])})


def test_extract_document_writes_jsonl(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder = _entity("binder").model
    calls = []

    def fake_extract(*, schema, document, system_prompt, purpose, **kw):
        calls.append(dict(document=document, purpose=purpose, schema=schema))
        return _fake_request(
            schema,
            binders=[Binder(name="ARB-202", evidence=[_ev("binder", kd=2.4)])],
        )

    monkeypatch.setattr(extraction.llm, "extract", fake_extract)
    out_dir = tmp_path / "out"
    rows = extraction.extract_document(doc, out_dir=out_dir)

    binder_call = calls[0]
    assert "Kd = 2.4 nM" in binder_call["document"]      # 正文送进去了
    assert "Smith 2020" not in binder_call["document"]   # 参考文献没送
    assert binder_call["purpose"] == "article_extraction:binders"
    assert binder_call["schema"] is SCHEMA.requests[0][1]

    written = (out_dir / "PMC1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(written) == len(rows) == 2
    assert json.loads(written[0])["data"]["name"] == "ARB-202"


def test_extract_document_makes_one_call_per_request_and_hints_indices(tmp_path, monkeypatch):
    """四次调用，顺序固定；combinations 那次的文档里带着前三次结果的编号清单。"""
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder, Car = _entity("binder").model, _entity("car").model
    calls = []

    def fake_extract(*, schema, document, system_prompt, purpose, **kw):
        field_name = next(iter(schema.model_fields))
        calls.append((field_name, document))
        if field_name == "binders":
            return _fake_request(schema, binders=[Binder(name="ARB-202"), Binder(name="5F9")])
        if field_name == "cars":
            return _fake_request(schema, cars=[Car(name="CD8a-BBz")])
        return _fake_request(schema)

    monkeypatch.setattr(extraction.llm, "extract", fake_extract)
    extraction.extract_document(doc, out_dir=tmp_path / "out")

    assert [name for name, _ in calls] == ["binders", "cars", "manufacturings", "combinations"]
    combo_document = calls[-1][1]
    assert "binders: 0=ARB-202, 1=5F9" in combo_document
    assert "cars: 0=CD8a-BBz" in combo_document
    assert "manufacturings: (none)" in combo_document


def test_extract_document_writes_readable_utf8(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    Binder = _entity("binder").model
    monkeypatch.setattr(
        extraction.llm, "extract",
        lambda *, schema, **kw: _fake_request(schema, binders=[Binder(name="抗体")]))

    extraction.extract_document(doc, out_dir=tmp_path / "out")
    raw = (tmp_path / "out" / "PMC1.jsonl").read_text(encoding="utf-8")
    assert "抗体" in raw


def test_dry_run_estimates_without_calling_extract(tmp_path, monkeypatch):
    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")

    def boom(**kw):
        raise AssertionError("dry_run 不该真的调用模型")

    monkeypatch.setattr(extraction.llm, "extract", boom)
    monkeypatch.setattr(extraction.llm, "count_tokens", lambda **kw: 42_000)

    rows = extraction.extract_document(doc, out_dir=tmp_path / "out", dry_run=True)
    assert rows == []
    assert not (tmp_path / "out" / "PMC1.jsonl").exists()


import subprocess
import sys
from pathlib import Path as _Path

REPO = _Path(__file__).resolve().parents[1]


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "extract.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout


def test_cli_main_passes_arguments(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "scripts"))
    import extract as cli

    doc = tmp_path / "PMC1.xml"
    doc.write_text(JATS, encoding="utf-8")
    seen = {}

    def fake(path, *, out_dir=None, dry_run=False):
        seen.update(path=str(path), out_dir=str(out_dir), dry_run=dry_run)
        return []

    monkeypatch.setattr(cli, "extract_document", fake)
    assert cli.main([str(doc), "--out-dir", str(tmp_path / "out"), "--dry-run"]) == 0
    assert seen["dry_run"] is True
    assert seen["path"] == str(doc)


def test_cli_reports_missing_file(tmp_path, capsys):
    sys.path.insert(0, str(REPO / "scripts"))
    import extract as cli

    assert cli.main([str(tmp_path / "nope.xml")]) == 1
    assert "不存在" in capsys.readouterr().err
