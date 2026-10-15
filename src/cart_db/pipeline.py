"""Resume the existing extractor, then stage/resolve/publish its validated JSONL."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time

from . import ingest
from .console import count_text, json_text
from .identity import ENTITIES
from .ingest_schema import contract_hash


def checksum(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json_text(data) + "\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_error(path, exc, env):
    detail = str(exc)
    for key, secret in env.items():
        if secret and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            detail = detail.replace(secret, "[已隐藏]")
    write_json(path, dict(error_type=type(exc).__name__, detail=detail))


def run_document(path, *, extract, out_dir, force=False, on_status=None, **kwargs):
    """Only resume extraction when source, contract, and saved artifacts still match.

    Publication can be retried after a crash: the same JSONL checksum is the same
    database batch. Never use a disk report as proof of a database commit.
    """
    def notify(message):
        cancel = kwargs.get("cancel_event")
        if cancel is not None and cancel.is_set():
            raise InterruptedError("任务已取消")
        if on_status:
            on_status(message)
    started = time.monotonic()
    final_dir = out_dir / path.stem
    manifest_path = final_dir / "source_manifest.json"
    report_path = final_dir / "database_report.json"
    final_dir.mkdir(parents=True, exist_ok=True)
    result = dict(ok=False, cost=0.0, usage=dict(input=0, cached_input=0, cache_write=0, output=0),
                  usage_known=True, seconds=0, reason="", extraction_reused=False)
    phase = "source"
    extraction_finished = False
    try:
        notify("正在读取原始文档并核对校验和")
        source_hash = checksum(path)
        output = final_dir / "data.jsonl"
        if output.exists() and not force:
            if not manifest_path.exists():
                raise ValueError("已有 JSONL 缺少原文校验记录，不能自动认定来源；请用 --force 重新提取")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("source_sha256") != source_hash or manifest.get("schema_hash") not in (contract_hash(),
                    "fb64398a5ef997932fcf2a6b795040a050054f717bc0479de176cdc799656d9a"):
                raise ValueError("原文或字段定义已经变化；请用 --force 重新提取")
            artifacts = manifest.get("artifacts", {})
            if (not {"data.jsonl", "original.jsonl", "reasoning.md"} <= artifacts.keys()
                    or not artifacts.keys() <= {"data.jsonl", "original.jsonl", "reasoning.md", "error_log.jsonl"}
                    or any(not (final_dir / name).is_file() or checksum(final_dir / name) != expected
                           for name, expected in artifacts.items())):
                raise ValueError("提取产物不完整或被修改；请恢复原文件，或用 --force 重新提取")
            result["extraction_reused"] = True
            notify("原文和提取结果一致，复用已有 JSONL，继续数据库处理")
        else:
            phase = "extraction"
            result = extract(path, out_dir=out_dir, on_status=notify, **kwargs)
            extraction_finished = True
            result["extraction_reused"] = False
            if not result["ok"]:
                return result
            if not all((final_dir / name).is_file() for name in ("data.jsonl", "original.jsonl", "reasoning.md")):
                raise ValueError("提取程序未保存完整的 JSONL 和来源依据文件")
            if checksum(path) != source_hash:
                raise ValueError("提取期间原始文档发生变化，本次结果不入库；请核对后重新提取")
            manifest = dict(source_path=str(path.resolve()), source_sha256=source_hash,
                            schema_hash=contract_hash(),
                            agent=kwargs.get("agent"), model=kwargs.get("model"),
                            artifacts={name: checksum(final_dir / name)
                                       for name in ("data.jsonl", "original.jsonl", "reasoning.md", "error_log.jsonl")
                                       if (final_dir / name).is_file()})
            write_json(manifest_path, manifest)
        phase = "database"
        contexts = [final_dir / name for name in ("source_manifest.json", "original.jsonl", "reasoning.md", "error_log.jsonl")
                    if (final_dir / name).is_file()]
        with ingest.connect() as conn:
            batch_id = ingest.stage_file(conn, output, contexts, on_status=notify)
            # Check committed log IDs, not counters from a prior local report.
            before = {str(r["stage_id"]) for r in ingest.batch_status(conn, batch_id)["records"]
                      if r["status"] == "published"}
            report = ingest.publish(conn, batch_id, on_status=notify)
            methods = ingest.rows(conn, """SELECT l.stage_id,l.method,s.table_name FROM cart.publication_log l
                JOIN cart.staged_record s USING(stage_id) WHERE s.batch_id=%s""", (batch_id,))
            actions = dict(new_entities=0, linked_entities=0, new_records=0, linked_records=0)
            for item in methods:
                if str(item["stage_id"]) in before:
                    continue
                entity = item["table_name"] in ENTITIES
                new = item["method"] in ("new_complete_identity", "new_source_entity", "reviewed_new", "new_source_observation_or_combination")
                actions[("new_" if new else "linked_") + ("entities" if entity else "records")] += 1
            report["actions"] = actions
        write_json(report_path, report)
        result.update(ok=not report["counts"]["invalid"], database=report,
                      reason=count_text(report["counts"]), report_path=str(report_path))
        notify("数据库处理完成：" + count_text(report["counts"]))
    except Exception as exc:
        if phase == "extraction" and not extraction_finished:
            # A transport failure may happen after a paid request; zero is not known.
            result.update(cost=None, usage_known=False)
        log = final_dir / "pipeline_error.json"
        save_error(log, exc, kwargs.get("env", {}))
        message = {"source": "原文或续跑检查未通过", "extraction": "提取结果保存或来源核对失败",
                   "database": "数据库处理失败；提取结果已保留，恢复后可直接续跑"}[phase]
        if phase == "source" and any("\u4e00" <= char <= "\u9fff" for char in str(exc)):
            message = str(exc)
        result.update(ok=False, reason=f"{message}；诊断记录：{log}")
    finally:
        result["seconds"] = time.monotonic() - started
    return result
