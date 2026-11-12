"""Resume the existing extractor, then stage/resolve/publish its validated JSONL."""
from __future__ import annotations

from pathlib import Path
import tempfile
import time

from . import ingest
from .console import count_text, json_text
from .identity import ENTITIES
from .artifacts import checksum, verify_artifacts


# Write a complete JSON file beside its destination, then replace the destination atomically.
def write_json(path, data):
    path = Path(path)
    # Write into a private temporary file and close it before subsequent publication/use.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name, delete=False) as stream:
        temporary = Path(stream.name)
        # Remove the temporary file if serialization fails before replacement.
        try:
            stream.write(json_text(data) + "\n")
        # On BaseException, remove the obsolete or incomplete file.
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    # Replace the destination only after the new JSON file is fully written.
    try:
        temporary.replace(path)
    # Always remove the obsolete or incomplete file.
    finally:
        temporary.unlink(missing_ok=True)


# Persist a diagnostic after redacting credential values supplied in the environment.
def save_error(path, exc, env):
    detail = str(exc)
    # Inspect environment values only to mask credentials in diagnostic text.
    for key, secret in env.items():
        # Redact nonempty values for credential-like environment keys.
        if secret and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            detail = detail.replace(secret, "[已隐藏]")
    write_json(path, dict(error_type=type(exc).__name__, detail=detail))


def run_document(path, *, extract, out_dir, force=False, on_status=None, **kwargs):
    """Only resume extraction when source, contract, and saved artifacts still match.

    Publication can be retried after a crash: the same JSONL checksum is the same
    database batch. Never use a disk report as proof of a database commit.
    """
    # Stop canceled work at progress boundaries and forward public status to the caller.
    def notify(message):
        cancel = kwargs.get("cancel_event")
        # Honor cancellation before entering another pipeline stage.
        if cancel is not None and cancel.is_set():
            raise InterruptedError("任务已取消")
        # Forward status only when a listener was supplied.
        if on_status:
            on_status(message)
    started = time.monotonic()
    final_dir = out_dir / path.stem
    report_path = final_dir / "database_report.json"
    final_dir.mkdir(parents=True, exist_ok=True)
    result = dict(ok=False, cost=0.0, usage=dict(input=0, cached_input=0, cache_write=0, output=0),
                  usage_known=True, seconds=0, reason="", extraction_reused=False)
    phase = "source"
    extraction_finished = False
    # Track the current phase so failures preserve useful diagnostics and honest cost accounting.
    try:
        notify("正在读取原始文档并核对校验和")
        source_hash = checksum(path)
        output = final_dir / "data.jsonl"
        # Reuse extraction only when the source, schema, and all required artifacts can be verified.
        if output.exists() and not force:
            verify_artifacts(final_dir, path, require_classification=True)
            result["extraction_reused"] = True
            notify("原文和提取结果一致，复用已有 JSONL，继续数据库处理")
        # A missing or changed extraction artifact requires a fresh extraction before import.
        else:
            phase = "extraction"
            result = extract(path, out_dir=out_dir, on_status=notify, **kwargs)
            extraction_finished = True
            result["extraction_reused"] = False
            # A failed extraction returns its retained draft status without attempting database
            # import.
            if not result["ok"]:
                return result
            # All required extraction artifacts must exist before recording a resumable manifest.
            if not all((final_dir / name).is_file() for name in ("data.jsonl", "original.jsonl", "reasoning.md")):
                raise ValueError("提取程序未保存完整的 JSONL 和来源依据文件")
            # Source changes during extraction invalidate this run's provenance.
            if checksum(path) != source_hash:
                raise ValueError("提取期间原始文档发生变化，本次结果不入库；请核对后重新提取")
            # The runner already wrote the source manifest; verify it without replacing its
            # provenance fields (including an explicitly supported historical schema hash).
            verify_artifacts(final_dir, path, require_classification=True)
        phase = "database"
        # Collect items from ('source_manifest.json', 'original.jsonl', 'reasoning.md',
        # 'error_log.jsonl', 'figures.jsonl') only where (final_dir / name).is_file().
        contexts = [final_dir / name for name in ("source_manifest.json", "original.jsonl", "reasoning.md", "error_log.jsonl", "figures.jsonl",
                                                      "document_classification.json", "patent.jsonl", "patent.original.jsonl")
                    if (final_dir / name).is_file()]
        # Stage and publish using the configured database; disk reports are not proof of a commit.
        with ingest.connect() as conn:
            batch_id = ingest.stage_file(conn, output, contexts, on_status=notify)
            # Check committed log IDs, not counters from a prior local report.
            before = {str(r["stage_id"]) for r in ingest.batch_status(conn, batch_id)["records"]
                      if r["status"] == "published"}
            report = ingest.publish(conn, batch_id, on_status=notify)
            methods = ingest.rows(conn, """SELECT l.stage_id,l.method,s.table_name FROM cart.publication_log l
                JOIN cart.staged_record s USING(stage_id) WHERE s.batch_id=%s""", (batch_id,))
            actions = dict(new_entities=0, linked_entities=0, new_records=0, linked_records=0)
            # Count only publication actions committed during this invocation.
            for item in methods:
                # Previously published staging rows must not inflate this run's action counts.
                if str(item["stage_id"]) in before:
                    continue
                entity = item["table_name"] in ENTITIES
                new = item["method"] in ("new_complete_identity", "new_source_entity", "reviewed_new", "new_source_observation_or_combination")
                # Use 'new_' when new is truthy; otherwise use 'linked_'.
                actions[("new_" if new else "linked_") + ("entities" if entity else "records")] += 1
            report["actions"] = actions
        write_json(report_path, report)
        result.update(ok=not report["counts"]["invalid"], database=report,
                      reason=count_text(report["counts"]), report_path=str(report_path))
        notify("数据库处理完成：" + count_text(report["counts"]))
    # Record the failure phase and diagnostic path; uncertain transport spending must not be
    # reported as zero.
    except Exception as exc:
        if phase == "extraction" and not extraction_finished:
            # A transport failure may happen after a paid request; zero is not known.
            result.update(cost=None, usage_known=False)
        log = final_dir / "pipeline_error.json"
        save_error(log, exc, kwargs.get("env", {}))
        message = {"source": "原文或续跑检查未通过", "extraction": "提取结果保存或来源核对失败",
                   "database": "数据库处理失败；提取结果已保留，恢复后可直接续跑"}[phase]
        # Keep a readable source-check error when it already contains an operator-facing Chinese
        # explanation.
        if phase == "source" and any("\u4e00" <= char <= "\u9fff" for char in str(exc)):
            message = str(exc)
        result.update(ok=False, reason=f"{message}；诊断记录：{log}")
    # Record total elapsed time for both successful and failed document processing.
    finally:
        result["seconds"] = time.monotonic() - started
    return result
