#!/usr/bin/env python3
"""端到端冒烟测试 —— Day3 完成标准「冒烟测试全绿」。

检查四条链路：
  1. 数据库连通、七库表齐全
  2. 写入-读取-回滚闭环（批次 + 来源登记）
  3. Raw Data 目录规范与校验和
  4. LLM 计费打点（API key 未配置时标为「待配置」，不算失败）
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cart_db import storage  # noqa: E402
from cart_db.config import cost_cny, settings  # noqa: E402
from cart_db.db import batch, connect  # noqa: E402

EXPECTED_TABLES = [
    ("binder", "binder"), ("car", "module"), ("car", "construct"),
    ("process", "process"), ("lit", "article"), ("patent", "patent"),
    ("db1", "combo"), ("db2", "record"),
    ("core", "source_registry"), ("core", "batch_run"),
    ("core", "llm_usage"), ("core", "evidence"), ("core", "merge_log"),
    ("qc", "finding"),
]

results: list[tuple[str, str, str]] = []


# Run one legacy smoke check and collect its result without preventing subsequent checks.
def check(name: str, fn) -> None:
    # Attempt this operation while preserving the explicit recovery/cleanup paths below.
    try:
        # Use empty text when fn() is missing or empty.
        results.append((name, "通过", fn() or ""))
    # Retain each failing check and its exception so later smoke checks can still run.
    except Exception as exc:
        results.append((name, "失败", f"{type(exc).__name__}: {exc}"))


# Confirm a connection to the configured legacy database and report its PostgreSQL version.
def t_connect() -> str:
    # Close the database connection when this operation finishes or raises.
    with connect() as conn:
        ver = conn.execute("SELECT version()").fetchone()[0]
    return ver.split(",")[0]


# Compare the legacy expected table list with the server catalog.
def t_tables() -> str:
    # Close the database connection when this operation finishes or raises.
    with connect() as conn:
        rows = conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN "
            "('core','binder','car','process','lit','patent','db1','db2','qc')"
        ).fetchall()
    # Collect distinct values from rows.
    found = {(s, t) for s, t in rows}
    # Collect items from EXPECTED_TABLES only where (s, t) not in found.
    missing = [f"{s}.{t}" for s, t in EXPECTED_TABLES if (s, t) not in found]
    # Stop rather than continue with invalid or incomplete input.
    if missing:
        raise AssertionError("缺表：" + ", ".join(missing))
    return f"{len(found)} 张表齐全"


def t_roundtrip() -> str:
    """批次 + 来源登记的写入闭环，跑完清理掉。"""
    tmp = settings.data_root / "raw" / "_smoke" / "20260101"
    tmp.mkdir(parents=True, exist_ok=True)
    f = tmp / "sample.txt"
    f.write_text("smoke", encoding="utf-8")
    # Release this managed resource when the enclosed operation completes or fails.
    with batch("smoke", "core", notes="冒烟测试") as bid:
        rid = storage.register(source_name="_smoke", local_path=f,
                               used_for="测试", owner="共同", record_count=1)
    # Close the database connection when this operation finishes or raises.
    with connect() as conn:
        digest = conn.execute(
            "SELECT sha256 FROM core.source_registry WHERE id=%s", (rid,)
        ).fetchone()[0]
        conn.execute("DELETE FROM core.source_registry WHERE id=%s", (rid,))
        conn.execute("DELETE FROM core.batch_run WHERE batch_id=%s", (bid,))
    f.unlink()
    return f"批次+登记闭环 OK，校验和 {digest[:12]}…"


# Check the legacy raw-data directory convention using an empty test directory.
def t_storage() -> str:
    d = storage.raw_dir("SAbDab", "20260101")
    rel = d.relative_to(settings.data_root)
    d.rmdir()
    return f"目录规范 data/{rel}"


def t_costing() -> str:
    """按方案预算口径核对折算：180M 输入 + 20M 输出 ≈ ¥5,660。"""
    total = cost_cny(180_000_000, 20_000_000)
    assert 5000 < total < 6500, f"折算异常：{total}"
    return f"180M入+20M出 = ¥{total:,.0f}（方案预算 ¥5,660）"


# Make a small real model request when credentials exist; otherwise report a skipped check.
def t_llm() -> str:
    # Stop with a diagnostic: SKIP.
    if not settings.llm_ready:
        raise RuntimeError("SKIP")
    from cart_db.llm import _client
    client = _client()
    resp = client.messages.create(
        model=settings.llm_model, max_tokens=16,
        messages=[{"role": "user", "content": "回复两个字：就绪"}],
    )
    return f"{settings.llm_model} 调用成功，输出 {resp.usage.output_tokens} token"


# Run and summarize legacy database/storage/cost checks, including the optional paid model call.
def main() -> int:
    check("1. 数据库连通", t_connect)
    check("2. 七库表结构", t_tables)
    check("3. 写入闭环", t_roundtrip)
    check("4. 存储目录规范", t_storage)
    check("5. 成本折算口径", t_costing)
    check("6. LLM 调用", t_llm)

    print("\n冒烟测试结果")
    print("─" * 68)
    failed = 0
    # Process each (name, status, detail) from results independently.
    for name, status, detail in results:
        # When detail equals 'RuntimeError: SKIP', report this outcome to the command-line operator.
        if detail == "RuntimeError: SKIP":
            print(f"  ○ {name:16s} 待配置   API key 未填，本地建库不需要")
            continue
        # Count failed checks and print their diagnostic for the final exit status.
        if status == "失败":
            failed += 1
            print(f"  ✗ {name:16s} 失败     {detail}")
        # Otherwise, report this outcome to the command-line operator.
        else:
            print(f"  ✓ {name:16s} 通过     {detail}")
    print("─" * 68)
    # Use '全绿 —— Day3「冒烟测试全绿」达成' when failed is empty or false; otherwise use f'{failed}
    # 项失败，先修再往下走'.
    print("全绿 —— Day3「冒烟测试全绿」达成" if not failed else f"{failed} 项失败，先修再往下走")
    # Use 1 when failed is truthy; otherwise use 0.
    return 1 if failed else 0


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == "__main__":
    raise SystemExit(main())
