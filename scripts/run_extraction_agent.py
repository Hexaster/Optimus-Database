#!/usr/bin/env python
"""把一个或一批文档逐份喂给 extract-cart-data 技能。

每份文档单独起一次 coding agent：上下文互不污染，一份跑飞不影响后面几份。
结果由技能自己写进 data/normalised/，runner 校验、规范化后才发布正式结果。

    python scripts/run_extraction_agent.py --agent claude      # Claude Code
    python scripts/run_extraction_agent.py --agent codex --model gpt-5.2-codex
    python scripts/run_extraction_agent.py --agent kimi --model kimi-code/kimi-for-coding
    python scripts/run_extraction_agent.py --agent zcode --model zai/glm-5.2
    python scripts/run_extraction_agent.py --dir data/raw/xxx   # 换目录
    python scripts/run_extraction_agent.py --file data/raw/a.pdf # 跑单个文件
    python scripts/run_extraction_agent.py --force              # 重跑已有结果的文档
    python scripts/run_extraction_agent.py --subagent true     # 启用两个子代理独立抽取
    python scripts/run_extraction_agent.py --workers 3          # 同时处理三份文档
    python scripts/run_extraction_agent.py --validation-retries 0 # 校验失败不自动修正
    python scripts/run_extraction_agent.py --dry-run            # 只列出要跑什么
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import shutil
import tempfile
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cart_db.agent_output import OutputError, prepare_output
from cart_db.config import settings      # noqa: E402  —— 唯一一份 .env 解析
SKILL = "extract-cart-data"

# 与技能 Workflow 一节支持的格式保持一致。
SUFFIXES = {".pdf", ".xml", ".nxml", ".md", ".markdown"}

PROMPT = """Read {skill_path} completely, then follow that skill to extract structured data from {path}.

Follow the skill with this run's overrides:
- Output directory: {out_dir}.
  This is a private staging workspace.
  Write final artifacts directly here; the runner publishes them in the document folder.
- Other documents may be processed concurrently. Keep all scratch files and writes
  inside this output directory; do not modify shared code, schemas, or other outputs.
- Subagent mode: {subagent_mode}
- Active YAML fields are the output contract; commented fields must not be emitted.
- IDs are document-local non-empty string labels (existing UUID labels are also accepted).
  Keep references consistent; the runner generates final UUIDs and rewrites references.
- The runner fills omitted nullable fields with null, orders fields, and normalizes units.
  Preserve source values, raw text, row order, and all list order; do not deduplicate.
Read docs/Schema/*.yaml first, then the document, then write
{out_dir}/data.jsonl, {out_dir}/reasoning.md (a concise evidence and decision summary),
and, if there are exceptions, {out_dir}/error_log.jsonl.
In reasoning.md, reference records by table, row number, and field name rather than
local IDs, because the runner replaces IDs during publication. Keep scratch material
separate from these three files; only these final artifacts will be published.

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
        "usage_known": bool(raw),
        "turns": answer.get("num_turns"),
        "session": answer.get("session_id"),
        "reason": answer.get("result", "")[:500],
    }


def parse_codex(stdout: str) -> dict:
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    usage = empty_usage()
    session = None
    summary = ""
    error = ""
    cost = None
    ok = False
    usage_known = False
    for event in events:
        if not isinstance(event, dict):
            raise TypeError("Codex event must be an object")
        if event.get("type") == "turn.started":
            ok = False
            error = ""
        if event.get("type") == "thread.started":
            session = event.get("thread_id")
        if event.get("type") == "turn.completed":
            ok = True
            error = ""
            raw = event.get("usage") or {}
            usage_known = bool(raw)
            total_input = raw.get("input_tokens", 0) or 0
            cached_input = raw.get("cached_input_tokens", 0) or 0
            usage = {
                "input": max(total_input - cached_input, 0),
                "cached_input": cached_input,
                "cache_write": 0,
                "output": raw.get("output_tokens", 0) or 0,
            }
            cost = raw.get("cost_usd", event.get("cost_usd"))
        if event.get("type") in {"error", "turn.failed"}:
            ok = False
            error = str(event.get("message") or event.get("error") or event)[:500]
        item = event.get("item") or {}
        if item.get("type") == "agent_message":
            summary = str(item.get("text", ""))[:500]
    reason = summary if ok else error or "Codex 未返回 turn.completed，输出流可能不完整"
    return {"ok": ok, "cost": cost, "usage": usage,
            "usage_known": usage_known, "session": session,
            "turns": None, "reason": reason, "error": error or None}


def parse_kimi(stdout: str) -> dict:
    """解析 Kimi Code 的 JSONL；当前格式不提供 token usage。"""
    session = None
    reason = ""
    ok = True
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("role") == "assistant":
            content = event.get("content", "")
            if isinstance(content, str):
                reason = content[:500]
            elif isinstance(content, list):
                text = "".join(part.get("text", "") for part in content
                               if part.get("type") == "text")
                reason = text[:500]
        if event.get("role") == "meta":
            session = event.get("session_id") or event.get("sessionId") or session
        if event.get("role") == "error" or event.get("type") == "error":
            ok = False
            reason = str(event.get("message") or event.get("error") or event)[:500]

    return {"ok": ok, "cost": None, "usage": empty_usage(),
            "usage_known": False, "session": session,
            "turns": None, "reason": reason}


def parse_zcode(stdout: str) -> dict:
    answer = json.loads(stdout)
    raw = answer.get("usage") or {}
    total_input = raw.get("inputTokens", 0) or 0
    cached_input = raw.get("cacheReadTokens", 0) or 0
    cache_write = raw.get("cacheWriteTokens", 0) or 0
    usage = {
        "input": max(total_input - cached_input - cache_write, 0),
        "cached_input": cached_input,
        "cache_write": cache_write,
        "output": raw.get("outputTokens", 0) or 0,
    }
    error = answer.get("error")
    return {
        "ok": not error,
        "cost": answer.get("costUsd"),
        "usage": usage,
        "usage_known": bool(raw),
        "session": answer.get("sessionId"),
        "turns": None,
        "reason": str(error or answer.get("response", ""))[:500],
    }


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


def _run_agent(path: Path, *, agent: str, out_dir: Path, timeout: int,
    budget: float | None, env: dict[str, str], model: str | None,
    effort: str, input_price: float | None, cached_input_price: float | None,
    output_price: float | None, subagent: bool = False,
    correction: str = "",
    diagnostics_dir: Path | None = None,
) -> dict:
    """跑一份文档，返回这次调用的结果摘要。"""
    prompt = PROMPT.format(
        skill=SKILL, skill_path=".claude/skills/extract-cart-data/SKILL.md",
        path=path.as_posix(), stem=path.stem,
        out_dir=out_dir.relative_to(REPO).as_posix(),
        subagent_mode=(
            "enabled. Use the skill's two-subagent independent extraction and cross-check workflow."
            if subagent else
            "disabled. Do not spawn subagents or launch additional agent processes. "
            "Extract the full document and cross-check against the source yourself."
        ),
    )
    prompt += correction
    run_env = env.copy()
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
    elif agent == "codex":
        command = ["codex", "exec", prompt, "--json", "--ephemeral",
                   "--approve-for-me", "-C", str(REPO)]
        command += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
        if settings.openai_base_url or settings.openai_api_key:
            base_url = json.dumps(
                (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
            )
            command += [
                "-c", 'model_provider="openai_compatible"',
                "-c", 'model_providers.openai_compatible.name="OpenAI compatible"',
                "-c", f"model_providers.openai_compatible.base_url={base_url}",
                "-c", 'model_providers.openai_compatible.env_key="OPENAI_API_KEY"',
                "-c", 'model_providers.openai_compatible.requires_openai_auth=false',
                "-c", 'model_providers.openai_compatible.wire_api="responses"',
            ]
        if model:
            command += ["--model", model]
    elif agent == "kimi":
        command = ["kimi"]
        if model:
            command += ["--model", model]
        command += ["--prompt", prompt, "--output-format", "stream-json"]
    else:
        command = ["zcode", "--prompt", prompt, "--json", "--mode", "yolo",
                   "--cwd", str(REPO)]
        if model:
            run_env["ZCODE_MODEL"] = model

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=REPO, env=run_env, capture_output=True, text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {"ok": False, "reason": f"找不到 {command[0]} CLI",
                "seconds": time.monotonic() - started, "cost": None,
                "usage": empty_usage(), "usage_known": False}
    except subprocess.TimeoutExpired as exc:
        if diagnostics_dir is not None:
            save_diagnostics(diagnostics_dir, env, exc.stdout, exc.stderr, None)
        return {"ok": False, "reason": f"超时（{timeout}s）",
                "seconds": time.monotonic() - started, "cost": None,
                "usage": empty_usage(), "usage_known": False}

    seconds = time.monotonic() - started
    if diagnostics_dir is not None:
        save_diagnostics(diagnostics_dir, env, completed.stdout,
                         completed.stderr, completed.returncode)
    try:
        if agent == "claude":
            result = parse_claude(completed.stdout)
        elif agent == "codex":
            result = parse_codex(completed.stdout)
        elif agent == "kimi":
            result = parse_kimi(completed.stdout)
        else:
            result = parse_zcode(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "seconds": seconds, "cost": None,
                "usage": empty_usage(), "usage_known": False,
                "reason": (completed.stderr.strip() or
                           f"返回不是 JSON：{completed.stdout[:300]}")}

    result["seconds"] = seconds
    if completed.returncode != 0:
        detail = result.get("error") or completed.stderr.strip() or (
            result["reason"] if not result["ok"] else "未提供 stderr")
        result["ok"] = False
        result["reason"] = f"CLI 退出码 {completed.returncode}：{detail}"[:500]
    if result["cost"] is None and result["usage_known"]:
        result["cost"] = estimated_cost(
            result["usage"], input_price, cached_input_price, output_price)
    return result


def save_diagnostics(directory, env, stdout, stderr, returncode):
    """Keep per-attempt output in the private draft directory, without env secrets."""
    def redact(value):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        value = value or ""
        for key, secret in env.items():
            if secret and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                value = value.replace(secret, "[REDACTED]")
        return value

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="agent-run-",
                                     suffix=".json", dir=directory, delete=False) as log:
        json.dump(dict(returncode=returncode, stdout=redact(stdout), stderr=redact(stderr)),
                  log, ensure_ascii=False)


def run_one(path: Path, *, out_dir: Path, timeout: int, budget: float | None,
            validation_retries: int = 1, **kwargs) -> dict:
    """Publish only validated output; retain failed drafts for inspection.

    Repairs share the document timeout and remaining known budget. Unknown
    spending with a budget disables automatic repair. Existing output is kept
    on validation failure; successful empty output means no extracted records.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_dir = Path(tempfile.mkdtemp(prefix=f".{path.stem}-", dir=out_dir))
    candidate = draft_dir / "data.jsonl"
    final_dir = out_dir / path.stem
    started = time.monotonic()
    usage = empty_usage()
    cost = 0.0
    known_cost = known_usage = True
    correction = ""
    result = dict(ok=False, reason="", usage=usage, cost=None, usage_known=False)
    for attempt in range(validation_retries + 1):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            result.update(ok=False, reason="单份总超时（包含校验修正）")
            break
        attempt_budget = budget - cost if budget is not None else None
        result = _run_agent(path, out_dir=draft_dir, timeout=remaining,
                            budget=attempt_budget, correction=correction,
                            diagnostics_dir=draft_dir, **kwargs)
        for key in usage:
            usage[key] += result["usage"][key]
        known_usage = known_usage and result["usage_known"]
        if result["cost"] is None:
            known_cost = False
        else:
            cost += result["cost"]
        if not result["ok"]:
            break
        try:
            output = prepare_output(candidate)
            reasoning = draft_dir / "reasoning.md"
            if not reasoning.is_file() or not reasoning.read_text(encoding="utf-8").strip():
                raise OutputError("reasoning.md: missing or empty evidence and decision summary")
        except (OutputError, ValueError) as exc:
            result.update(ok=False, reason=f"输出校验失败：{exc}")
            if attempt == validation_retries:
                break
            # Never grant a new full budget when prior spending is unknown.
            if budget is not None and (not known_cost or cost >= budget):
                result["reason"] += "；剩余预算不足或无法确定，未自动修正"
                break
            correction = (
                "\nThis is a validation repair of the existing draft, not a new extraction. "
                "Read the existing JSONL and fix the following error, then check all rows "
                "against active YAML fields. Consult the source if needed; do not guess, "
                "deduplicate, or remove valid records to pass validation.\n"
                + str(exc)
            )
            continue
        changed = []
        backups = {}
        try:
            final_dir.mkdir(parents=True, exist_ok=True)
            staged = draft_dir / "normalized.jsonl"
            staged.write_text(output, encoding="utf-8")
            for name, source in (("error_log.jsonl", draft_dir / "error_log.jsonl"),
                                 ("reasoning.md", reasoning), ("data.jsonl", staged)):
                target = final_dir / name
                if target.exists():
                    backup = draft_dir / ("previous." + name)
                    shutil.copyfile(target, backup)
                    backups[name] = backup
                if source.exists():
                    publish = source
                    if source != staged:
                        publish = draft_dir / ("staged." + name)
                        shutil.copyfile(source, publish)
                    publish.replace(target)
                else:
                    target.unlink(missing_ok=True)
                changed.append(name)
        except OSError as exc:
            result.update(ok=False, reason=f"输出发布失败（未自动调用模型修正）：{exc}")
            for name in reversed(changed):
                try:
                    if name in backups:
                        backups[name].replace(final_dir / name)
                    else:
                        (final_dir / name).unlink(missing_ok=True)
                except OSError as rollback_error:
                    result["reason"] += f"；{name} 恢复失败：{rollback_error}"
            break
        shutil.rmtree(draft_dir, ignore_errors=True)
        result["reason"] = "输出已校验并规范化"
        break
    if not result["ok"]:
        result["reason"] += f"；草稿保留于 {draft_dir}"
        result["draft_dir"] = str(draft_dir)
    result.update(seconds=time.monotonic() - started, usage=usage,
                  usage_known=known_usage, cost=cost if known_cost else None)
    return result


def usage_text(usage: dict[str, int], known: bool = True) -> str:
    if not known:
        return "tokens N/A"
    input_tokens = usage["input"] + usage["cached_input"] + usage["cache_write"]
    total = input_tokens + usage["output"]
    return (f"tokens：input {input_tokens:,}（uncached {usage['input']:,}，"
            f"cached {usage['cached_input']:,}，cache-write "
            f"{usage['cache_write']:,}），output {usage['output']:,}，"
            f"total {total:,}")


def tally(out_dir: Path, stem: str) -> str:
    """数一下技能到底写出了什么 —— 它自己报的行数不算数。"""
    rows = out_dir / "data.jsonl"
    errors = out_dir / "error_log.jsonl"
    if not rows.exists():
        return "没有 jsonl 文件"

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
    parser.add_argument("--agent", choices=("claude", "codex", "kimi", "zcode"),
                        default="claude")
    parser.add_argument("--model", help="模型名；不传则使用对应 harness 的默认配置")
    parser.add_argument("--effort", default="high", help="Claude/Codex 推理强度，默认 high")
    parser.add_argument("--out-dir", help="结果目录；默认按 agent/model 隔离")
    parser.add_argument("--force", action="store_true", help="已有结果的文档也重跑")
    parser.add_argument("--dry-run", action="store_true", help="只列出要跑什么")
    parser.add_argument("--subagent", choices=("true", "false"), default="false",
                        help="是否启用两个子代理独立抽取，默认 false")
    parser.add_argument("--timeout", type=int, default=1800, help="单份超时秒数")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="Claude 单份费用上限（美元），0 表示不限")
    parser.add_argument("--input-price", type=float,
                        help="后端不返回费用时，每百万 uncached input tokens 美元价")
    parser.add_argument("--cached-input-price", type=float,
                        help="每百万 cached input tokens 美元价")
    parser.add_argument("--output-price", type=float,
                        help="每百万 output tokens 美元价")
    parser.add_argument("--workers", type=int, default=1,
                        help="同时处理的文档数，默认 1")
    parser.add_argument("--validation-retries", type=int, default=1,
                        help="输出校验失败后的最大修正次数，默认 1，0 表示不重试")
    args = parser.parse_args(argv)
    if args.validation_retries < 0:
        parser.error("--validation-retries 不能为负数")
    if args.workers < 1:
        parser.error("--workers 必须为正整数")

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
        pending = [p for p in pending if not (out_dir / p.stem / "data.jsonl").exists()]

    if not pending:
        print(f"{input_path} 没有待处理的文档（加 --force 可重跑）")
        return 0

    if len({p.stem for p in pending}) != len(pending):
        parser.error("文档有重复文件名主干，会写入同一输出文件；请先重命名")

    budget = args.budget if args.budget > 0 else None
    env = child_env(args.agent)
    if args.agent == "claude" and settings.anthropic_api_key:
        print(f"后端：Claude API，模型 {model}，单份上限 "
              f"{'$%.2f' % budget if budget else '不限'}")
    elif args.agent == "claude":
        print(f"后端：Claude 订阅，模型 {model}（--budget 不生效）")
    elif args.agent == "codex":
        print(f"后端：Codex，模型 {model or '本机默认'}，API "
              f"{settings.openai_base_url or 'OpenAI 默认端点'}")
        if budget is not None:
            print("预算：Codex 单次调用不受 --budget 硬限额控制；该值仅限制自动校验修正")
        if args.input_price is None or args.output_price is None:
            print("费用：后端未返回 cost 时为 N/A；可传 --input-price、"
                  "--cached-input-price、--output-price 计算")
    elif args.agent == "kimi":
        print(f"后端：Kimi Code，模型 {model or 'harness 默认'}")
        print("用量：新版 Kimi Code 不在 stdout 返回 token usage，将显示 N/A")
    else:
        print(f"后端：ZCode，模型 {model or 'harness 默认'}")
        if args.input_price is None or args.output_price is None:
            print("费用：可传 --input-price、--cached-input-price、"
                  "--output-price 计算")

    print(f"输出：{out_dir.relative_to(REPO)}")
    print(f"Subagents: {args.subagent}")
    print(f"Workers: {args.workers}")
    print(f"待处理 {len(pending)} 份：")
    for path in pending:
        print(f"  {path.name} → {out_dir.relative_to(REPO) / path.stem}")
    if args.dry_run:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    failures, total_cost, unknown_cost, unknown_usage = 0, 0.0, False, False
    total_usage = empty_usage()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                run_one, path, agent=args.agent, out_dir=out_dir, timeout=args.timeout,
                budget=budget, env=env, model=model, effort=args.effort,
                input_price=args.input_price,
                cached_input_price=args.cached_input_price,
                output_price=args.output_price,
                subagent=args.subagent == "true",
                validation_retries=args.validation_retries,
            ): path for path in pending
        }
        for index, future in enumerate(as_completed(futures), 1):
            path = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = dict(ok=False, reason=f"任务异常：{type(exc).__name__}: {exc}",
                              cost=None, usage=empty_usage(), usage_known=False, seconds=0)
            print(f"\n[{index}/{len(pending)}] {path.name}", flush=True)
            if result["cost"] is None:
                unknown_cost = True
            else:
                total_cost += result["cost"]
            for key, value in result["usage"].items():
                total_usage[key] += value
            unknown_usage = unknown_usage or not result["usage_known"]

            status = "OK " if result["ok"] else "失败"
            cost_text = f"${result['cost']:.4f}" if result["cost"] is not None else "费用 N/A"
            output_text = (
                "草稿（未发布）：" + tally(Path(result['draft_dir']), path.stem)
                if result.get('draft_dir') else tally(out_dir / path.stem, path.stem)
            )
            print(f"  {status} {result['seconds']:.0f}s  {cost_text}  "
                  f"{usage_text(result['usage'], result['usage_known'])}  "
                  f"{output_text}")
            if not result["ok"]:
                failures += 1
                print(f"  ↳ {result['reason']}")

    total_cost_text = f"${total_cost:.4f}" + (" + 未知费用" if unknown_cost else "")
    print(f"\n完成 {len(pending) - failures}/{len(pending)}，合计 "
          f"{total_cost_text}，{usage_text(total_usage, not unknown_usage)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
