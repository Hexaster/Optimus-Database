#!/usr/bin/env python
"""把一个目录下的文档逐份喂给 extract-cart-data 技能。

每份文档单独起一次 `claude -p`：上下文互不污染，一份跑飞不影响后面几份。
结果由技能自己写进 data/normalised/，这里只负责调度、计时、算钱、报结果。

    python scripts/run_extraction_agent.py                      # 跑 data/sample/
    python scripts/run_extraction_agent.py --dir data/raw/xxx   # 换目录
    python scripts/run_extraction_agent.py --force              # 重跑已有结果的文档
    python scripts/run_extraction_agent.py --dry-run            # 只列出要跑什么
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = "extract-cart-data"

# 与技能 Workflow 一节支持的格式保持一致。
SUFFIXES = {".pdf", ".xml", ".nxml", ".md", ".markdown"}

PROMPT = """Use the {skill} skill to extract structured data from {path}.

Follow the skill exactly: read docs/Schema/*.yaml first, then the document,
then write data/normalised/{stem}.jsonl and, if there are exceptions,
data/normalised/{stem}.errors.jsonl.

Report at the end how many rows you wrote, broken down by table."""


def documents(directory: Path) -> list[Path]:
    """目录下所有支持的文档，按文件名排序 —— 每次跑的顺序一致，便于比对。"""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in SUFFIXES)


def run_one(path: Path, *, timeout: int, budget: float | None) -> dict:
    """跑一份文档，返回这次调用的结果摘要。"""
    command = [
        "claude", "-p",
        PROMPT.format(skill=SKILL, path=path.as_posix(), stem=path.stem),
        "--output-format", "json",
        # 技能要读 schema、写 jsonl，还要 shell 出去取 uuid 和 PDF 文字层，
        # 这几样都得放行 —— -p 模式下弹权限框就等于这一份直接失败。
        "--allowedTools", "Read", "Write", "Edit", "Bash", "Glob", "Grep",
        "--permission-mode", "acceptEdits",
    ]
    if budget is not None:
        command += ["--max-budget-usd", str(budget)]

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=REPO, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"超时（{timeout}s）",
                "seconds": time.monotonic() - started, "cost": 0.0}

    seconds = time.monotonic() - started
    if completed.returncode != 0:
        return {"ok": False, "seconds": seconds, "cost": 0.0,
                "reason": (completed.stderr or completed.stdout).strip()[:500]}

    try:
        answer = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "seconds": seconds, "cost": 0.0,
                "reason": f"返回不是 JSON：{completed.stdout[:300]}"}

    return {
        "ok": not answer.get("is_error", False),
        "seconds": seconds,
        "cost": answer.get("total_cost_usd", 0.0),
        "turns": answer.get("num_turns"),
        "session": answer.get("session_id"),
        "reason": answer.get("result", "")[:500],
    }


def tally(out_dir: Path, stem: str) -> str:
    """数一下技能到底写出了什么 —— 它自己报的行数不算数。"""
    rows = out_dir / f"{stem}.jsonl"
    errors = out_dir / f"{stem}.errors.jsonl"
    if not rows.exists():
        return "没有写出 jsonl"

    tables: dict[str, int] = {}
    bad = 0
    for line in rows.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            table = json.loads(line)["table"]
        except (json.JSONDecodeError, KeyError):
            bad += 1
            continue
        tables[table] = tables.get(table, 0) + 1

    parts = [f"{table} {count}" for table, count in sorted(tables.items())]
    if bad:
        parts.append(f"坏行 {bad}")
    if errors.exists():
        parts.append(f"异常 {len(errors.read_text(encoding='utf-8').splitlines())}")
    return "，".join(parts) or "0 行"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default="data/sample", help="文档目录，默认 data/sample")
    parser.add_argument("--out-dir", default="data/normalised", help="结果目录")
    parser.add_argument("--force", action="store_true", help="已有结果的文档也重跑")
    parser.add_argument("--dry-run", action="store_true", help="只列出要跑什么")
    parser.add_argument("--timeout", type=int, default=1800, help="单份超时秒数")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="单份费用上限（美元），0 表示不限")
    args = parser.parse_args(argv)

    directory = (REPO / args.dir).resolve()
    out_dir = (REPO / args.out_dir).resolve()
    if not directory.is_dir():
        print(f"目录不存在：{directory}", file=sys.stderr)
        return 1

    pending = documents(directory)
    if not args.force:
        pending = [p for p in pending if not (out_dir / f"{p.stem}.jsonl").exists()]

    if not pending:
        print(f"{directory} 下没有待处理的文档（加 --force 可重跑）")
        return 0

    print(f"待处理 {len(pending)} 份：")
    for path in pending:
        print(f"  {path.name}")
    if args.dry_run:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    budget = args.budget if args.budget > 0 else None
    failures, total_cost = 0, 0.0

    for index, path in enumerate(pending, 1):
        print(f"\n[{index}/{len(pending)}] {path.name}", flush=True)
        result = run_one(path, timeout=args.timeout, budget=budget)
        total_cost += result["cost"]

        status = "OK " if result["ok"] else "失败"
        print(f"  {status} {result['seconds']:.0f}s  ${result['cost']:.2f}"
              f"  {tally(out_dir, path.stem)}")
        if not result["ok"]:
            failures += 1
            print(f"  ↳ {result['reason']}")

    print(f"\n完成 {len(pending) - failures}/{len(pending)}，合计 ${total_cost:.2f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
