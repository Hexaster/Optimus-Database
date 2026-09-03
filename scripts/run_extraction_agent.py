#!/usr/bin/env python
"""把一个或一批文档逐份喂给 extract-cart-data 技能。

每份文档单独起一次 Claude Code 或 Codex：上下文互不污染，一份跑飞不影响后面几份。
结果由技能自己写进 data/normalised/，这里只负责调度、计时、算钱、报结果。

    python scripts/run_extraction_agent.py --agent claude      # Claude Code
    python scripts/run_extraction_agent.py --agent codex --model gpt-5.2-codex
    python scripts/run_extraction_agent.py --dir data/raw/xxx   # 换目录
    python scripts/run_extraction_agent.py --file data/raw/a.pdf # 跑单个文件
    python scripts/run_extraction_agent.py --force              # 重跑已有结果的文档
    python scripts/run_extraction_agent.py --dry-run            # 只列出要跑什么
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cart_db.config import settings      # noqa: E402  —— 唯一一份 .env 解析
SKILL = "extract-cart-data"

# 与技能 Workflow 一节支持的格式保持一致。
SUFFIXES = {".pdf", ".xml", ".nxml", ".md", ".markdown"}

PROMPT = """Read {skill_path} completely, then follow that skill to extract structured data from {path}.

Follow the skill exactly except that this run's output directory is {out_dir}.
Read docs/Schema/*.yaml first, then the document, then write
{out_dir}/{stem}.jsonl and, if there are exceptions,
{out_dir}/{stem}.errors.jsonl.

Report at the end how many rows you wrote, broken down by table."""


def documents(directory: Path) -> list[Path]:
    """目录下所有支持的文档，按文件名排序 —— 每次跑的顺序一致，便于比对。"""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in SUFFIXES)


def child_env(agent: str) -> dict[str, str]:
    """给 agent 子进程传递 .env 中的认证配置。"""
    env = os.environ.copy()
    if agent == "claude" and settings.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if agent == "codex":
        if settings.openai_api_key:
            env["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.openai_base_url:
            env["OPENAI_BASE_URL"] = settings.openai_base_url
    return env


def empty_usage() -> dict[str, int]:
    return {"input": 0, "cached_input": 0, "cache_write": 0, "output": 0}


def parse_claude(stdout: str) -> dict:
    answer = json.loads(stdout)
    raw = answer.get("usage") or {}
    usage = {
        "input": raw.get("input_tokens", 0) or 0,
        "cached_input": raw.get("cache_read_input_tokens", 0) or 0,
        "cache_write": raw.get("cache_creation_input_tokens", 0) or 0,
        "output": raw.get("output_tokens", 0) or 0,
    }
    return {
        "ok": not answer.get("is_error", False),
        "cost": answer.get("total_cost_usd"),
        "usage": usage,
        "turns": answer.get("num_turns"),
        "session": answer.get("session_id"),
        "reason": answer.get("result", "")[:500],
    }


def parse_codex(stdout: str) -> dict:
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    usage = empty_usage()
    session = None
    reason = ""
    cost = None
    ok = True
    for event in events:
        if event.get("type") == "thread.started":
            session = event.get("thread_id")
        if event.get("type") == "turn.completed":
            raw = event.get("usage") or {}
            total_input = raw.get("input_tokens", 0) or 0
            cached_input = raw.get("cached_input_tokens", 0) or 0
            usage = {
                "input": max(total_input - cached_input, 0),
                "cached_input": cached_input,
                "cache_write": 0,
                "output": raw.get("output_tokens", 0) or 0,
            }
            cost = raw.get("cost_usd") or event.get("cost_usd")
        if event.get("type") in {"error", "turn.failed"}:
            ok = False
            reason = str(event.get("message") or event.get("error") or event)[:500]
        item = event.get("item") or {}
        if item.get("type") == "agent_message":
            reason = str(item.get("text", ""))[:500]
    return {"ok": ok, "cost": cost, "usage": usage, "session": session,
            "turns": None, "reason": reason}


def estimated_cost(usage: dict[str, int], input_price: float | None,
                   cached_input_price: float | None,
                   output_price: float | None) -> float | None:
    if input_price is None or output_price is None:
        return None
    if usage["cached_input"] and cached_input_price is None:
        return None
    cached_price = cached_input_price or 0.0
    return (usage["input"] * input_price
            + usage["cached_input"] * cached_price
            + usage["output"] * output_price) / 1_000_000


def run_one(path: Path, *, agent: str, out_dir: Path, timeout: int,
    budget: float | None, env: dict[str, str], model: str | None,
    effort: str, input_price: float | None, cached_input_price: float | None,
    output_price: float | None,
) -> dict:
    """跑一份文档，返回这次调用的结果摘要。"""
    prompt = PROMPT.format(
        skill=SKILL, skill_path=".claude/skills/extract-cart-data/SKILL.md",
        path=path.as_posix(), stem=path.stem,
        out_dir=out_dir.relative_to(REPO).as_posix(),
    )
    if agent == "claude":
        command = [
            "claude", "-p", prompt, "--output-format", "json",
            "--allowedTools", "Read", "Write", "Edit", "Bash", "Glob", "Grep",
            "--permission-mode", "acceptEdits", "--effort", effort,
        ]
        if model:
            command += ["--model", model]
        if budget is not None:
            command += ["--max-budget-usd", str(budget)]
    else:
        command = ["codex", "exec", prompt, "--json", "--ephemeral",
                   "--approve-for-me", "-C", str(REPO)]
        if settings.openai_base_url:
            base_url = json.dumps(settings.openai_base_url.rstrip("/"))
            command += [
                "-c", 'model_provider="openai_compatible"',
                "-c", 'model_providers.openai_compatible.name="OpenAI compatible"',
                "-c", f"model_providers.openai_compatible.base_url={base_url}",
                "-c", 'model_providers.openai_compatible.env_key="OPENAI_API_KEY"',
                "-c", 'model_providers.openai_compatible.wire_api="responses"',
            ]
        if model:
            command += ["--model", model]

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"超时（{timeout}s）",
                "seconds": time.monotonic() - started, "cost": None,
                "usage": empty_usage()}

    seconds = time.monotonic() - started
    try:
        result = parse_claude(completed.stdout) if agent == "claude" else parse_codex(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "seconds": seconds, "cost": None,
                "usage": empty_usage(),
                "reason": (completed.stderr.strip() or
                           f"返回不是 JSON：{completed.stdout[:300]}")}

    result["seconds"] = seconds
    if completed.returncode != 0:
        result["ok"] = False
        result["reason"] = (result["reason"] or completed.stderr.strip())[:500]
    if result["cost"] is None:
        result["cost"] = estimated_cost(
            result["usage"], input_price, cached_input_price, output_price)
    return result


def usage_text(usage: dict[str, int]) -> str:
    input_tokens = usage["input"] + usage["cached_input"] + usage["cache_write"]
    total = input_tokens + usage["output"]
    return (f"tokens：input {input_tokens:,}（uncached {usage['input']:,}，"
            f"cached {usage['cached_input']:,}，cache-write "
            f"{usage['cache_write']:,}），output {usage['output']:,}，"
            f"total {total:,}")


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
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dir", help="文档目录，默认 data/sample")
    source.add_argument("--file", help="单个文档")
    parser.add_argument("--agent", choices=("claude", "codex"), default="claude")
    parser.add_argument("--model", help="模型名；Claude 默认 opus，Codex 默认使用本机配置")
    parser.add_argument("--effort", default="high", help="Claude effort，默认 high")
    parser.add_argument("--out-dir", help="结果目录；默认按 agent/model 隔离")
    parser.add_argument("--force", action="store_true", help="已有结果的文档也重跑")
    parser.add_argument("--dry-run", action="store_true", help="只列出要跑什么")
    parser.add_argument("--timeout", type=int, default=1800, help="单份超时秒数")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="Claude 单份费用上限（美元），0 表示不限")
    parser.add_argument("--input-price", type=float,
                        help="后端不返回费用时，每百万 uncached input tokens 美元价")
    parser.add_argument("--cached-input-price", type=float,
                        help="每百万 cached input tokens 美元价")
    parser.add_argument("--output-price", type=float,
                        help="每百万 output tokens 美元价")
    args = parser.parse_args(argv)

    input_path = (REPO / (args.file or args.dir or "data/sample")).resolve()
    model = args.model or ("opus" if args.agent == "claude" else None)
    model_dir = (model or "default").replace("/", "_")
    out_arg = args.out_dir or f"data/normalised/{args.agent}/{model_dir}"
    out_dir = (REPO / out_arg).resolve()
    if not out_dir.is_relative_to(REPO):
        parser.error("--out-dir 必须位于项目目录内")
    if args.file and not input_path.is_file():
        print(f"文件不存在：{input_path}", file=sys.stderr)
        return 1
    if not args.file and not input_path.is_dir():
        print(f"目录不存在：{input_path}", file=sys.stderr)
        return 1
    if args.file and input_path.suffix.lower() not in SUFFIXES:
        print(f"不支持的文件格式：{input_path.suffix}", file=sys.stderr)
        return 1

    pending = [input_path] if args.file else documents(input_path)
    if not args.force:
        pending = [p for p in pending if not (out_dir / f"{p.stem}.jsonl").exists()]

    if not pending:
        print(f"{input_path} 没有待处理的文档（加 --force 可重跑）")
        return 0

    budget = args.budget if args.budget > 0 else None
    env = child_env(args.agent)
    if args.agent == "claude" and settings.anthropic_api_key:
        print(f"后端：Claude API，模型 {model}，单份上限 "
              f"{'$%.2f' % budget if budget else '不限'}")
    elif args.agent == "claude":
        print(f"后端：Claude 订阅，模型 {model}（--budget 不生效）")
    else:
        print(f"后端：Codex，模型 {model or '本机默认'}，API "
              f"{settings.openai_base_url or 'OpenAI 默认端点'}")
        if args.input_price is None or args.output_price is None:
            print("费用：后端未返回 cost 时为 N/A；可传 --input-price、"
                  "--cached-input-price、--output-price 计算")

    print(f"输出：{out_dir.relative_to(REPO)}")
    print(f"待处理 {len(pending)} 份：")
    for path in pending:
        print(f"  {path.name}")
    if args.dry_run:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    failures, total_cost, unknown_cost = 0, 0.0, False
    total_usage = empty_usage()

    for index, path in enumerate(pending, 1):
        print(f"\n[{index}/{len(pending)}] {path.name}", flush=True)
        result = run_one(
            path, agent=args.agent, out_dir=out_dir, timeout=args.timeout,
            budget=budget, env=env, model=model, effort=args.effort,
            input_price=args.input_price,
            cached_input_price=args.cached_input_price,
            output_price=args.output_price,
        )
        if result["cost"] is None:
            unknown_cost = True
        else:
            total_cost += result["cost"]
        for key, value in result["usage"].items():
            total_usage[key] += value

        status = "OK " if result["ok"] else "失败"
        cost_text = f"${result['cost']:.4f}" if result["cost"] is not None else "费用 N/A"
        print(f"  {status} {result['seconds']:.0f}s  {cost_text}  "
              f"{usage_text(result['usage'])}  {tally(out_dir, path.stem)}")
        if not result["ok"]:
            failures += 1
            print(f"  ↳ {result['reason']}")

    total_cost_text = f"${total_cost:.4f}" + (" + 未知费用" if unknown_cost else "")
    print(f"\n完成 {len(pending) - failures}/{len(pending)}，合计 "
          f"{total_cost_text}，{usage_text(total_usage)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
