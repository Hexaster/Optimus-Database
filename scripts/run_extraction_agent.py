#!/usr/bin/env python
"""把一个或一批文档逐份喂给 extract-cart-data 技能。

每份文档单独启动一次提取程序：上下文互不污染，一份跑飞不影响后面几份。
结果由技能自己写进 data/normalised/，运行程序校验、规范化后才发布正式结果。

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
    python scripts/run_extraction_agent.py --import-db --file data/raw/a.pdf # 提取并入库
    python scripts/run_extraction_agent.py --dry-run            # 只列出要跑什么
"""
from __future__ import annotations

import argparse
from concurrent.futures import as_completed
import json
import os
import subprocess
import shutil
import tempfile
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cart_db.document_classification import classify_document
from cart_db.retry import CallFailure, call_with_retry
from cart_db.agent_output import OutputError, prepare_output
from cart_db.figures import validate_figures
from cart_db.artifacts import artifact_manifest, verify_artifacts
from cart_db.pipeline import checksum, write_json
from cart_db.extraction_progress import ExtractionProgress, stream_agent, codex_status, claude_status
from cart_db.console import ChineseArgumentParser, TABLE_NAMES, report_text
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
- Data cross-check subagent mode: {subagent_mode}
- Independently of that setting, delegate figure extraction to exactly one additional
  image subagent. Give it the source path, this output directory, and
  docs/figure_extraction.md. It owns only figures.jsonl and img/. Wait for it,
  inspect its outputs, and resolve omissions from the source before finishing.
  It must not delegate further. If delegation is unavailable, report failure;
  do not silently omit images or claim a subagent ran.
- Follow docs/figure_extraction.md for the figure artifact contract. These
  instructions override the older skill restrictions on subagents/final files.
- Active YAML fields are the output contract; commented fields must not be emitted.
- IDs are document-local non-empty string labels (existing UUID labels are also accepted).
  Keep references consistent; the runner generates final UUIDs and rewrites references.
- The runner fills omitted nullable fields with null, orders fields, and normalizes units.
  Preserve source values, raw text, row order, and all list order; do not deduplicate.
- Write reasoning.md headings and explanatory prose in Simplified Chinese.
  In error_log.jsonl, retain the skill's keys and machine-readable category codes,
  and add a message field to every exception with a Simplified Chinese explanation
  of the specific problem and the action taken. Keep source quotes, raw_value,
  identifiers, schema field names, and scientific sequences unchanged.
Document classification by Jev: {document_type}.
For BOTH literature and patent, extract ALL applicable existing binder, car,
manufacturing, abc_combination_db1 and evidence records using the normal workflow.
Classification only enables ADDITIONAL patent extraction; it never replaces or
narrows the scientific extraction.
If patent: additionally use docs/Schema/Schema_Patent.yaml and append patent rows
AFTER all scientific rows in data.jsonl. At least one patent metadata row is required,
even if claims or sequence listings are unavailable; record those gaps faithfully.
Entity links use IDs of scientific rows in this same draft. Do not generate
claim_scope_assessments; leave it null. The runner rewrites linked IDs and publishes
patent rows separately as patent.jsonl (and patent.original.jsonl for the raw rows).
For patent evidence in reasoning.md, use patent.jsonl row numbers counted from 1.
If literature: do not extract patent rows, even when the paper cites patents.
Do not write or modify document_classification.json; it is owned by the runner.
Read the applicable YAML schemas first, then the document, then write
{out_dir}/data.jsonl, {out_dir}/reasoning.md (a concise evidence and decision summary),
and, if there are exceptions, {out_dir}/error_log.jsonl.
In reasoning.md, reference records by table, row number, and field name rather than
local IDs, because the runner replaces IDs during publication. Keep scratch material
separate from final artifacts. figures.jsonl and img/ are also published.
In reasoning.md link relevant evidence to img/ paths and figure/panel labels;
use table, one-based JSONL line, and field rather than temporary record IDs.

Report at the end how many rows you wrote, broken down by table."""


def documents(directory: Path) -> list[Path]:
    """目录下所有支持的文档，按文件名排序 —— 每次跑的顺序一致，便于比对。"""
    # Collect items from directory.iterdir() only where p.is_file() and p.suffix.lower() in
    # SUFFIXES.
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in SUFFIXES)


def child_env(agent: str) -> dict[str, str]:
    """给 agent 子进程传递 .env 中的认证配置。"""
    env = os.environ.copy()
    # Pass configured Anthropic credentials only to the Claude backend.
    if agent == "claude" and settings.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    # Pass OpenAI-compatible settings only to the Codex backend.
    if agent == "codex":
        # Use the configured API key when one is present.
        if urlparse(settings.openai_base_url or "").hostname == "openrouter.ai":
            # Every OpenRouter request shares one credential, including Codex and Jev.
            if not settings.openrouter_api_key:
                raise ValueError("OpenRouter 调用必须配置 OPENROUTER_API_KEY")
            env["OPENAI_API_KEY"] = settings.openrouter_api_key
        elif settings.openai_api_key:
            env["OPENAI_API_KEY"] = settings.openai_api_key
        # Forward the configured provider endpoint alongside its credentials.
        if settings.openai_base_url:
            env["OPENAI_BASE_URL"] = settings.openai_base_url
    return env


# Create independent token counters for a run; usage_known distinguishes zero from missing usage.
def empty_usage() -> dict[str, int]:
    return {"input": 0, "cached_input": 0, "cache_write": 0, "output": 0}


# Translate Claude's final JSON result into the runner's common outcome and cost fields.
def parse_claude(stdout: str) -> dict:
    answer = json.loads(stdout)
    # Use an empty mapping when answer.get('usage') is missing or empty.
    raw = answer.get("usage") or {}
    # Missing/null token counters become zero here; usage_known separately records whether usage was
    # reported.
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


def parse_claude_stream(stdout: str) -> dict:
    """Only the terminal result owns run-wide usage and cost."""
    result = None
    # Read every transport line; only a terminal result owns the run-wide accounting.
    for line in stdout.splitlines():
        # Ignore blank transport/input lines without creating an empty record.
        if not line.strip():
            continue
        event = json.loads(line)
        # Malformed event shapes cannot be interpreted as successful runs.
        if not isinstance(event, dict):
            raise TypeError("Claude event must be an object")
        # Retain the terminal result event rather than adding usage from intermediate messages.
        if event.get("type") == "result":
            result = event
    # A truncated stream with no result is a failure with unknown usage.
    if result is None:
        result = {"is_error": True, "result": "Claude 未返回 result，输出流可能不完整"}
    # Treat a non-success result subtype as a failed extraction even without is_error.
    elif result.get("subtype") != "success":
        result["is_error"] = True
        # Build mapped values from result.get('errors', []).
        result["result"] = result.get("result") or "；".join(
            str(error) for error in result.get("errors", [])
        ) or f"Claude 调用失败：{result.get('subtype', '未知状态')}"
    return parse_claude(json.dumps(result))


# Read Codex lifecycle events, keeping final-turn status and separating cached input tokens.
def parse_codex(stdout: str) -> dict:
    # Collect items from stdout.splitlines() only where line.strip().
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    usage = empty_usage()
    session = None
    summary = ""
    error = ""
    cost = None
    ok = False
    usage_known = False
    # Apply Codex lifecycle events in arrival order.
    for event in events:
        # Stop with a diagnostic: Codex event must be an object.
        if not isinstance(event, dict):
            raise TypeError("Codex event must be an object")
        # A new turn invalidates the prior turn's success state.
        if event.get("type") == "turn.started":
            ok = False
            error = ""
        # Retain the thread identifier for diagnostics.
        if event.get("type") == "thread.started":
            session = event.get("thread_id")
        # A completed turn provides its final usage and clears stale errors.
        if event.get("type") == "turn.completed":
            ok = True
            error = ""
            # Use an empty mapping when event.get('usage') is missing or empty.
            raw = event.get("usage") or {}
            usage_known = bool(raw)
            # Default an absent/empty raw.get('input_tokens', 0) to zero for this counter or
            # estimate.
            total_input = raw.get("input_tokens", 0) or 0
            # Default an absent/empty raw.get('cached_input_tokens', 0) to zero for this counter or
            # estimate.
            cached_input = raw.get("cached_input_tokens", 0) or 0
            # Default an absent/empty raw.get('output_tokens', 0) to zero for this counter or
            # estimate.
            usage = {
                "input": max(total_input - cached_input, 0),
                "cached_input": cached_input,
                "cache_write": 0,
                "output": raw.get("output_tokens", 0) or 0,
            }
            cost = raw.get("cost_usd", event.get("cost_usd"))
        # Explicit errors override the current success state.
        if event.get("type") in {"error", "turn.failed"}:
            ok = False
            # Prefer a message, then an error payload, then the entire event for diagnostic text.
            error = str(event.get("message") or event.get("error") or event)[:500]
        # Use an empty mapping when event.get('item') is missing or empty.
        item = event.get("item") or {}
        # Keep the latest public agent message as the outcome summary.
        if item.get("type") == "agent_message":
            summary = str(item.get("text", ""))[:500]
    # Use summary when ok is truthy; otherwise use error or 'Codex 未返回 turn.completed，输出流可能不完整'.
    reason = summary if ok else error or "Codex 未返回 turn.completed，输出流可能不完整"
    # Represent an empty error as None instead of a reported value.
    return {"ok": ok, "cost": cost, "usage": usage,
            "usage_known": usage_known, "session": session,
            "turns": None, "reason": reason, "error": error or None}


def parse_kimi(stdout: str) -> dict:
    """解析 Kimi Code 的 JSONL；当前格式不提供 token usage。"""
    session = None
    reason = ""
    ok = True
    # Process each line separately so record/event boundaries and diagnostics stay attributable.
    for line in stdout.splitlines():
        # Ignore blank transport/input lines without creating an empty record.
        if not line.strip():
            continue
        event = json.loads(line)
        # Assistant messages supply the public result summary.
        if event.get("role") == "assistant":
            content = event.get("content", "")
            # A plain-text message can be summarized directly.
            if isinstance(content, str):
                reason = content[:500]
            # For content blocks, include only public text blocks.
            elif isinstance(content, list):
                # Collect items from content only where part.get('type') == 'text'.
                text = "".join(part.get("text", "") for part in content
                               if part.get("type") == "text")
                reason = text[:500]
        # Accept either session-ID spelling reported by Kimi.
        if event.get("role") == "meta":
            # Accept either session-ID spelling, retaining the last observed ID when neither is
            # present.
            session = event.get("session_id") or event.get("sessionId") or session
        # An explicit transport error marks the result unsuccessful.
        if event.get("role") == "error" or event.get("type") == "error":
            ok = False
            # Prefer a message, then an error payload, then the entire event for diagnostic text.
            reason = str(event.get("message") or event.get("error") or event)[:500]

    return {"ok": ok, "cost": None, "usage": empty_usage(),
            "usage_known": False, "session": session,
            "turns": None, "reason": reason}


# Translate ZCode usage fields while excluding cache reads/writes from ordinary input tokens.
def parse_zcode(stdout: str) -> dict:
    answer = json.loads(stdout)
    # Use an empty mapping when answer.get('usage') is missing or empty.
    raw = answer.get("usage") or {}
    # Default an absent/empty raw.get('inputTokens', 0) to zero for this counter or estimate.
    total_input = raw.get("inputTokens", 0) or 0
    # Default an absent/empty raw.get('cacheReadTokens', 0) to zero for this counter or estimate.
    cached_input = raw.get("cacheReadTokens", 0) or 0
    # Default an absent/empty raw.get('cacheWriteTokens', 0) to zero for this counter or estimate.
    cache_write = raw.get("cacheWriteTokens", 0) or 0
    # Default an absent/empty raw.get('outputTokens', 0) to zero for this counter or estimate.
    usage = {
        "input": max(total_input - cached_input - cache_write, 0),
        "cached_input": cached_input,
        "cache_write": cache_write,
        "output": raw.get("outputTokens", 0) or 0,
    }
    error = answer.get("error")
    # Prefer error; if empty or absent, fall back to answer.get('response', '').
    return {
        "ok": not error,
        "cost": answer.get("costUsd"),
        "usage": usage,
        "usage_known": bool(raw),
        "session": answer.get("sessionId"),
        "turns": None,
        "reason": str(error or answer.get("response", ""))[:500],
    }


# Estimate USD cost only when all prices required by the observed usage are available.
def estimated_cost(usage: dict[str, int], input_price: float | None,
                   cached_input_price: float | None,
                   output_price: float | None) -> float | None:
    # Missing required token prices means cost is unknown, not zero.
    if input_price is None or output_price is None:
        return None
    # Cached tokens require a cached-input price before a cost estimate is valid.
    if usage["cached_input"] and cached_input_price is None:
        return None
    # An unspecified cached-input price contributes zero to this configured estimate.
    cached_price = cached_input_price or 0.0
    return (usage["input"] * input_price
            + usage["cached_input"] * cached_price
            + usage["output"] * output_price) / 1_000_000


def _run_agent(path: Path, *, agent: str, out_dir: Path, timeout: int,
    budget: float | None, env: dict[str, str], model: str | None,
    effort: str, input_price: float | None, cached_input_price: float | None,
    output_price: float | None, subagent: bool = False,
    correction: str = "",
    document_type: str = "unclassified",
    figures_only: bool = False,
    diagnostics_dir: Path | None = None,
    on_status=None,
    cancel_event=None,
) -> dict:
    """跑一份文档，返回这次调用的结果摘要。"""
    # Choose the result according to subagent is truthy; preserve the alternate path for the other
    # case.
    prompt = PROMPT.format(
        document_type=document_type,
        skill=SKILL, skill_path=".claude/skills/extract-cart-data/SKILL.md",
        path=path.as_posix(), stem=path.stem,
        out_dir=out_dir.relative_to(REPO).as_posix(),
        subagent_mode=(
            "enabled. Use the skill's two-subagent independent extraction and cross-check workflow."
            if subagent else
            "disabled for structured data. Only the dedicated image subagent is authorized. "
            "Extract the full document and cross-check against the source yourself."
        ),
    )
    # A backfill delegates only image work, preserving previously validated structured data.
    if figures_only:
        prompt = (
            f"Delegate image extraction from {path.as_posix()} to exactly one image subagent. "
            f"Output workspace: {out_dir.as_posix()}. Read docs/figure_extraction.md and give "
            "the subagent those instructions. It owns only figures.jsonl and img/ and must "
            "not delegate further. Wait for completion and inspect the crops and inventory. "
            "Do not edit data.jsonl, original.jsonl, reasoning.md, error_log.jsonl, or schemas. "
            "If delegation is unavailable, report failure. Do not claim an unperformed review."
        )
    prompt += correction
    # Request public progress lines only for backends with supported event parsers.
    if agent in {"codex", "claude"}:
        prompt += (
            "\nAt meaningful workflow transitions, emit a short public progress message "
            "in Simplified Chinese on a single line beginning exactly with 进度：. "
            "Describe the current observable task (reading, extracting, source checking, "
            "or writing), not private reasoning. Report actual work only; do not invent "
            "progress, percentages, or completion. Continue working after each update.\n"
        )
    run_env = env.copy()
    # Use the selected backend's transport, authentication, and result conventions.
    if agent == "claude":
        # Use 'stream-json' when on status is supplied; otherwise use 'json'.
        command = [
            "claude", "-p", prompt, "--output-format", "stream-json" if on_status is not None else "json",
            "--allowedTools", "Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "Task",
            "--permission-mode", "acceptEdits", "--effort", effort,
        ]
        # Claude streaming output requires verbose event reporting.
        if on_status is not None:
            command += ["--verbose"]
        # An explicit model overrides the backend default.
        if model:
            command += ["--model", model]
        # Pass the document budget only through Claude's supported CLI option.
        if budget is not None:
            command += ["--max-budget-usd", str(budget)]
    # Use the selected backend's transport, authentication, and result conventions.
    elif agent == "codex":
        command = ["codex", "exec", prompt, "--json", "--ephemeral",
                   "--approve-for-me", "-C", str(REPO)]
        command += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
        # Configure both endpoint and credential lookup when using an OpenAI-compatible provider.
        if settings.openai_base_url or settings.openai_api_key:
            # Prefer settings.openai_base_url; if empty or absent, fall back to
            # 'https://api.openai.com/v1'.
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
        # Preserve an explicit Codex model selection.
        if model:
            command += ["--model", model]
    # Use the selected backend's transport, authentication, and result conventions.
    elif agent == "kimi":
        command = ["kimi"]
        # Preserve an explicit Kimi model selection.
        if model:
            command += ["--model", model]
        command += ["--prompt", prompt, "--output-format", "stream-json"]
    # Otherwise, build the selected backend's command using its own CLI options.
    else:
        command = ["zcode", "--prompt", prompt, "--json", "--mode", "yolo",
                   "--cwd", str(REPO)]
        # ZCode receives its model override through the child environment.
        if model:
            run_env["ZCODE_MODEL"] = model

    started = time.monotonic()
    # Capture launch/timeout failures without reporting fabricated usage or cost.
    try:
        # Use streaming only when this backend supports it and a status listener exists.
        if agent in {"codex", "claude"} and on_status is not None:
            # Use claude_status when agent equals 'claude'; otherwise use codex_status.
            completed = stream_agent(command, cwd=REPO, env=run_env,
                                     timeout=timeout, on_status=on_status,
                                     cancel_event=cancel_event,
                                     status_parser=claude_status if agent == "claude" else codex_status)
        # Backends without streamed status use a captured subprocess with the same environment and
        # timeout.
        else:
            completed = subprocess.run(
                command, cwd=REPO, env=run_env, capture_output=True, text=True,
                timeout=timeout,
            )
    # On FileNotFoundError, return the result for this representation.
    except FileNotFoundError:
        return {"ok": False, "reason": f"找不到 {command[0]} CLI",
                "seconds": time.monotonic() - started, "cost": None,
                "usage": empty_usage(), "usage_known": False}
    # Preserve any partial timeout output and report unknown usage rather than assuming no paid
    # request ran.
    except subprocess.TimeoutExpired as exc:
        # Save available timeout output when a private diagnostics directory was supplied.
        if diagnostics_dir is not None:
            save_diagnostics(diagnostics_dir, env, exc.stdout, exc.stderr, None)
        return {"ok": False, "reason": f"超时（{timeout}s）",
                "seconds": time.monotonic() - started, "cost": None,
                "usage": empty_usage(), "usage_known": False}

    seconds = time.monotonic() - started
    # Retain the completed process output for later validation/accounting diagnosis.
    if diagnostics_dir is not None:
        save_diagnostics(diagnostics_dir, env, completed.stdout,
                         completed.stderr, completed.returncode)
    # Parse backend-specific output into the shared result format.
    try:
        # Use the selected backend's transport, authentication, and result conventions.
        if agent == "claude":
            # Use parse_claude_stream(completed.stdout) when on status is supplied; otherwise use
            # parse_claude(completed.stdout).
            result = (parse_claude_stream(completed.stdout) if on_status is not None
                      else parse_claude(completed.stdout))
        # Use the selected backend's transport, authentication, and result conventions.
        elif agent == "codex":
            result = parse_codex(completed.stdout)
        # Use the selected backend's transport, authentication, and result conventions.
        elif agent == "kimi":
            result = parse_kimi(completed.stdout)
        # Otherwise, run the selected operation and retain its result.
        else:
            result = parse_zcode(completed.stdout)
    # On (json.JSONDecodeError, TypeError), return the result for this representation.
    except (json.JSONDecodeError, TypeError):
        # Prefer captured stderr for a malformed result; otherwise show a bounded stdout excerpt.
        return {"ok": False, "seconds": seconds, "cost": None,
                "usage": empty_usage(), "usage_known": False,
                "reason": (completed.stderr.strip() or
                           f"返回不是 JSON：{completed.stdout[:300]}")}

    result["seconds"] = seconds
    # A nonzero process exit overrides a success-looking JSON result.
    if completed.returncode != 0:
        # Use result['reason'] when result ok is empty or false; otherwise use '未提供 stderr'.
        detail = result.get("error") or completed.stderr.strip() or (
            result["reason"] if not result["ok"] else "未提供 stderr")
        result["ok"] = False
        result["reason"] = f"CLI 退出码 {completed.returncode}：{detail}"[:500]
    # Estimate missing cost only when token usage was actually reported.
    if result["cost"] is None and result["usage_known"]:
        result["cost"] = estimated_cost(
            result["usage"], input_price, cached_input_price, output_price)
    return result


def save_diagnostics(directory, env, stdout, stderr, returncode):
    """Keep per-attempt output in the private draft directory, without env secrets."""
    # Decode captured output and mask environment credential values before saving diagnostics.
    def redact(value):
        # Timeout capture may be bytes; decode before redacting credential values.
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        # Use empty text when value is missing or empty.
        value = value or ""
        # Check environment values for credentials that need redaction from diagnostics.
        for key, secret in env.items():
            # Mask credential values before displaying or persisting diagnostic text.
            if secret and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                value = value.replace(secret, "[REDACTED]")
        return value

    # Write into a private temporary file and close it before subsequent publication/use.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="agent-run-",
                                     suffix=".json", dir=directory, delete=False) as log:
        json.dump(dict(returncode=returncode, stdout=redact(stdout), stderr=redact(stderr)),
                  log, ensure_ascii=False)


def publish_artifacts(draft, destination, names):
    """Replace files and the complete image directory; roll back on publication errors."""
    destination.mkdir(parents=True, exist_ok=True)
    backup = draft / ".publication-backup"
    backup.mkdir()
    changed = []
    try:
        for name in names:
            target, source = destination / name, draft / name
            # Move old files/directories aside on the same filesystem for reversible replacement.
            if target.exists():
                target.replace(backup / name)
            changed.append(name)
            # Missing optional artifacts intentionally remove the previous run's artifact.
            if source.exists():
                source.replace(target)
    except OSError:
        for name in reversed(changed):
            target = destination / name
            # Return new artifacts to the retained draft before restoring the previous output.
            if target.exists():
                target.replace(draft / name)
            if (backup / name).exists():
                (backup / name).replace(target)
        raise


def run_one(path: Path, *, out_dir: Path, timeout: int, budget: float | None,
            validation_retries: int = 1, on_status=None, figures_only: bool = False, **kwargs) -> dict:
    """Publish only validated output; retain failed drafts for inspection.

    Repairs share the document timeout and remaining known budget. Unknown
    spending with a budget disables automatic repair. Existing output is kept
    on validation failure; successful empty output means no extracted records.
    """
    # Use a no-op callback when no progress listener was supplied.
    notify = on_status or (lambda message: None)
    notify("正在启动提取程序")
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_dir = Path(tempfile.mkdtemp(prefix=f".{path.stem}-", dir=out_dir))
    candidate = draft_dir / "data.jsonl"
    final_dir = out_dir / path.stem
    source_hash = checksum(path)
    preserved = {}
    protected_names = ("data.jsonl", "original.jsonl", "reasoning.md", "error_log.jsonl",
                       "document_classification.json", "patent.jsonl", "patent.original.jsonl")
    # Backfills require verified provenance before any model work and keep scientific rows intact.
    if figures_only:
        previous = verify_artifacts(final_dir, path, require_figures=False)
        for name in protected_names:
            # Optional exception logs are copied only when present in the existing result.
            if (final_dir / name).is_file():
                shutil.copyfile(final_dir / name, draft_dir / name)
                preserved[name] = checksum(draft_dir / name)
    started = time.monotonic()
    usage = empty_usage()
    cost = 0.0
    known_cost = known_usage = True
    correction = ""
    result = dict(ok=False, reason="", usage=usage, cost=None, usage_known=False)
    classification = None
    document_type = "unclassified"
    if not figures_only:
        notify("正在通过 OpenRouter 调用 Jev 判断文献或专利")
        try:
            classification = classify_document(path, timeout=timeout)
            write_json(draft_dir / "document_classification.json", classification)
            document_type = classification["document_type"]
            jev_usage = classification["response"]["usage"]
            usage["input"] += jev_usage["input_tokens"]
            usage["output"] += jev_usage["output_tokens"]
            known_cost = classification["cost_usd"] is not None
            cost = classification["cost_usd"] or 0.0
            if classification["source_sha256"] != source_hash:
                raise ValueError("Jev 分类期间源文件发生变化")
            if document_type not in ("literature", "patent"):
                raise ValueError("Jev 无法确定文件类型；请核对文档后重试")
            notify("Jev：专利；常规抽取并额外提取专利信息" if document_type == "patent"
                   else "Jev：文献；执行常规抽取")
        except (ValueError, OSError) as exc:
            # No extraction may start without an actual typed routing decision.
            result.update(reason=str(exc), draft_dir=str(draft_dir),
                          user_reason=f"文档分类未通过：{exc}；诊断保留于 {draft_dir}",
                          seconds=time.monotonic() - started, usage=usage,
                          usage_known=classification is not None,
                          cost=cost if classification is not None and known_cost else None)
            save_diagnostics(draft_dir, kwargs.get("env", {}), str(exc), "", None)
            return result
    # Run the initial attempt and bounded repairs within the same document time/budget allowance.
    for attempt in range(validation_retries + 1):
        remaining = timeout - (time.monotonic() - started)
        # All repair attempts share one elapsed-time limit.
        if remaining <= 0:
            result.update(ok=False, reason="单份总超时（包含校验修正）")
            break
        if budget is not None and (not known_cost or cost >= budget):
            result.update(ok=False, reason="剩余预算不足或 Jev 费用未知，未启动提取")
            break
        # Each backend adapts its outcome to the same external-call retry policy.
        def invoke(remaining):
            nonlocal result, known_usage, known_cost, cost
            if budget is not None and (not known_cost or cost >= budget):
                raise CallFailure("剩余预算不足或调用费用未知", retryable=False)
            attempt_budget = budget - cost if budget is not None else None
            result = _run_agent(path, out_dir=draft_dir, timeout=remaining,
                                budget=attempt_budget, correction=correction, figures_only=figures_only,
                                document_type=document_type,
                                diagnostics_dir=draft_dir, on_status=on_status, **kwargs)
            for key in usage:
                usage[key] += result["usage"][key]
            known_usage = known_usage and result["usage_known"]
            if result["cost"] is None:
                known_cost = False
            else:
                cost += result["cost"]
            if not result["ok"]:
                can_retry = budget is None or (known_cost and cost < budget)
                reason = result["reason"]
                if not can_retry:
                    reason += "；剩余预算不足或调用费用未知"
                raise CallFailure(reason, retryable=can_retry)
            return result

        try:
            result = call_with_retry(invoke, timeout=remaining, label="抽取调用", on_status=notify)
        except ValueError as exc:
            result.update(ok=False, reason=str(exc))
            break
        # Validate the draft and its evidence summary before publishing any output files.
        try:
            notify("正在校验字段、记录引用和计量单位")
            # Images must be complete and source-bounded before any artifacts become public.
            validate_figures(draft_dir, source=path)
            if checksum(path) != source_hash:
                raise OutputError("Source changed during extraction")
            # Backfills must not regenerate UUIDs or change any scientific extraction artifact.
            if figures_only:
                for name in protected_names:
                    # Adding an exception log is also an unauthorized structured-output change.
                    if name not in preserved:
                        if (draft_dir / name).exists():
                            raise OutputError(f"Figure backfill added {name}")
                        continue
                    expected = preserved[name]
                    if checksum(draft_dir / name) != expected:
                        raise OutputError(f"Figure backfill modified {name}")
                output = candidate.read_text(encoding="utf-8")
            else:
                saved = json.loads((draft_dir / "document_classification.json").read_text())
                if saved != classification:
                    raise OutputError("Agent modified runner-owned document classification")
                output = prepare_output(candidate, document_type=document_type)
            reasoning = draft_dir / "reasoning.md"
            # A valid JSONL without a nonempty evidence summary is incomplete extraction output.
            if not reasoning.is_file() or not reasoning.read_text(encoding="utf-8").strip():
                raise OutputError("reasoning.md: missing or empty evidence and decision summary")
        # Keep the invalid draft and prepare a bounded repair only when retries and budget allow it.
        except (OutputError, ValueError, OSError) as exc:
            result.update(ok=False, reason=f"输出校验失败：{exc}")
            # Stop once the configured number of repair attempts has been exhausted.
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
            # Figure-only repairs cannot use the normal instruction to edit scientific JSONL.
            if figures_only:
                correction = (
                    "\nRepair only figures.jsonl and img/ in this existing workspace. "
                    "Recheck against the source and docs/figure_extraction.md. "
                    "Do not edit scientific artifacts. Validation error: " + str(exc)
                )
            notify(f"输出校验未通过，正在启动第 {attempt + 1} 次修正")
            continue
        # Prepare the entire artifact set and checksummed manifest before replacing public files.
        try:
            notify("校验通过，正在保存正式结果")
            if not figures_only:
                # Validate combined rows first, so patent links use final scientific UUIDs.
                raw = candidate.read_text(encoding="utf-8")
                for text, scientific_name, patent_name in (
                    (raw, "original.jsonl", "patent.original.jsonl"),
                    (output, "data.jsonl", "patent.jsonl"),
                ):
                    scientific, patents = [], []
                    for line in text.splitlines():
                        if line.strip():
                            (patents if json.loads(line)["table"] == "patent" else scientific).append(line)
                    (draft_dir / scientific_name).write_text(
                        "".join(line + "\n" for line in scientific), encoding="utf-8")
                    if document_type == "patent":
                        (draft_dir / patent_name).write_text(
                            "".join(line + "\n" for line in patents), encoding="utf-8")
                    else:
                        (draft_dir / patent_name).unlink(missing_ok=True)
            manifest = artifact_manifest(draft_dir, path, agent=kwargs.get("agent"),
                                         model=kwargs.get("model"))
            # Hash again at the publication boundary, including extraction-only runs.
            if manifest["source_sha256"] != source_hash:
                raise ValueError("Source changed before publication")
            # Preserve the original data contract and producer when adding images to older output.
            if figures_only:
                current = verify_artifacts(final_dir, path, require_figures=False)
                if current != previous:
                    raise ValueError("Existing extraction changed during figure backfill")
                for name, expected in preserved.items():
                    # Only image artifacts will be replaced, so live scientific files must match.
                    if checksum(final_dir / name) != expected:
                        raise ValueError(f"Existing {name} changed during figure backfill")
                for key in ("schema_hash", "agent", "model"):
                    manifest[key] = previous.get(key)
                manifest["figure_agent"] = kwargs.get("agent")
                manifest["figure_model"] = kwargs.get("model")
            write_json(draft_dir / "source_manifest.json", manifest)
            names = ["figures.jsonl", "img", "source_manifest.json"]
            # Full extraction also refreshes data and removes any obsolete exception log.
            if not figures_only:
                names = ["original.jsonl", "error_log.jsonl", "reasoning.md", "figures.jsonl",
                         "img", "data.jsonl", "document_classification.json",
                         "patent.jsonl", "patent.original.jsonl", "source_manifest.json"]
            publish_artifacts(draft_dir, final_dir, names)
        except (OSError, ValueError) as exc:
            result.update(ok=False, reason=f"输出发布失败：{exc}")
            break
        shutil.rmtree(draft_dir, ignore_errors=True)
        result["reason"] = "输出已校验并规范化"
        break
    # Failed drafts remain available and their location is included in the operator report.
    if not result["ok"]:
        save_diagnostics(draft_dir, kwargs.get("env", {}), result["reason"], "", None)
        result["user_reason"] = f"提取或校验未通过；草稿和诊断记录保留于 {draft_dir}"
        result["reason"] += f"；草稿保留于 {draft_dir}"
        result["draft_dir"] = str(draft_dir)
    # Use cost when known cost is truthy; otherwise use None.
    result.update(seconds=time.monotonic() - started, usage=usage,
                  usage_known=known_usage, cost=cost if known_cost else None)
    return result


# Render token totals while explicitly distinguishing unknown usage from an observed zero.
def usage_text(usage: dict[str, int], known: bool = True) -> str:
    # Unknown token usage must not look like an observed zero-token run.
    if not known:
        return "词元用量未提供"
    input_tokens = usage["input"] + usage["cached_input"] + usage["cache_write"]
    total = input_tokens + usage["output"]
    return (f"词元：输入 {input_tokens:,}（未缓存 {usage['input']:,}，"
            f"缓存读取 {usage['cached_input']:,}，缓存写入 "
            f"{usage['cache_write']:,}），输出 {usage['output']:,}，"
            f"合计 {total:,}")


def tally(out_dir: Path, stem: str) -> str:
    """数一下技能到底写出了什么 —— 它自己报的行数不算数。"""
    rows = out_dir / "data.jsonl"
    errors = out_dir / "error_log.jsonl"
    # A missing output file cannot be counted as a successful empty extraction.
    if not rows.exists():
        return "没有 jsonl 文件"

    tables: dict[str, int] = {}
    bad = 0
    # Count actual output rows rather than trusting the agent's reported totals.
    for line in (rows.read_text(encoding="utf-8") +
                 ((out_dir / "patent.jsonl").read_text(encoding="utf-8")
                  if (out_dir / "patent.jsonl").is_file() else "")).splitlines():
        # Ignore blank transport/input lines without creating an empty record.
        if not line.strip():
            continue
        # Count malformed JSONL separately from valid table rows.
        try:
            table = json.loads(line)["table"]
        # Count malformed or table-less lines as bad output and continue summarizing the other
        # lines.
        except (json.JSONDecodeError, KeyError):
            bad += 1
            continue
        tables[table] = tables.get(table, 0) + 1

    # Build mapped values from sorted(tables.items()).
    parts = [f"{TABLE_NAMES.get(table, table)} {count}" for table, count in sorted(tables.items())]
    # Include malformed-line counts in the output summary.
    if bad:
        parts.append(f"坏行 {bad}")
    # Report exception-log row counts only when that artifact exists.
    if errors.exists():
        parts.append(f"异常 {len(errors.read_text(encoding='utf-8').splitlines())}")
    # Prefer '，'.join(parts); if empty or absent, fall back to '0 行'.
    return "，".join(parts) or "0 行"


# Validate inputs, optionally preflight PostgreSQL, and schedule independent document extraction
# jobs.
def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dir", help="文档目录，默认 data/sample")
    source.add_argument("--file", help="单个文档")
    parser.add_argument("--agent", choices=("claude", "codex", "kimi", "zcode"),
                        default="claude")
    parser.add_argument("--model", help="模型名；不传则使用对应提取后端的默认配置")
    parser.add_argument("--effort", default="high", help="Claude/Codex 推理强度，默认 high")
    parser.add_argument("--out-dir", help="结果目录；默认按 agent/model 隔离")
    parser.add_argument("--import-db", action="store_true", help="连接 PostgreSQL，提取后自动暂存、比对并入库；重复运行可续跑")
    parser.add_argument("--figures-only", action="store_true",
                        help="仅补充图像；保留已校验的数据，需要现有 source_manifest.json")
    parser.add_argument("--force", action="store_true", help="已有结果的文档也重跑")
    parser.add_argument("--dry-run", action="store_true", help="只列出要跑什么")
    parser.add_argument("--no-progress", action="store_true", help="关闭终端动态状态面板")
    parser.add_argument("--subagent", choices=("true", "false"), default="false",
                        help="是否启用两个子代理独立抽取，默认 false")
    parser.add_argument("--timeout", type=int, default=1800, help="单份超时秒数")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="Claude 单份费用上限（美元），0 表示不限")
    parser.add_argument("--input-price", type=float,
                        help="后端不返回费用时，每百万未缓存输入词元的美元价")
    parser.add_argument("--cached-input-price", type=float,
                        help="每百万缓存输入词元的美元价")
    parser.add_argument("--output-price", type=float,
                        help="每百万输出词元的美元价")
    parser.add_argument("--workers", type=int, default=1,
                        help="同时处理的文档数，默认 1")
    parser.add_argument("--validation-retries", type=int, default=1,
                        help="输出校验失败后的最大修正次数，默认 1，0 表示不重试")
    args = parser.parse_args(argv)
    # Reject the input: --validation-retries 不能为负数.
    if args.validation_retries < 0:
        parser.error("--validation-retries 不能为负数")
    # Reject the input: --workers 必须为正整数.
    if args.workers < 1:
        parser.error("--workers 必须为正整数")

    # Choose a single file, then a directory, then the default sample directory.
    input_path = (REPO / (args.file or args.dir or "data/sample")).resolve()
    # Use 'opus' when args.agent equals 'claude'; otherwise use None.
    model = args.model or ("opus" if args.agent == "claude" else None)
    # Prefer model; if empty or absent, fall back to 'default'.
    model_dir = (model or "default").replace("/", "_")
    # Honor --out-dir or derive a directory from the agent and model.
    out_arg = args.out_dir or f"data/normalised/{args.agent}/{model_dir}"
    out_dir = (REPO / out_arg).resolve()
    # Reject the input: --out-dir 必须位于项目目录内.
    if not out_dir.is_relative_to(REPO):
        parser.error("--out-dir 必须位于项目目录内")
    # When args.file and (not input_path.is_file()), report this outcome to the command-line
    # operator.
    if args.file and not input_path.is_file():
        print(f"文件不存在：{input_path}", file=sys.stderr)
        return 1
    # When not args.file and (not input_path.is_dir()), report this outcome to the command-line
    # operator.
    if not args.file and not input_path.is_dir():
        print(f"目录不存在：{input_path}", file=sys.stderr)
        return 1
    # When args.file and input_path.suffix.lower() not in SUFFIXES, report this outcome to the
    # command-line operator.
    if args.file and input_path.suffix.lower() not in SUFFIXES:
        print(f"不支持的文件格式：{input_path.suffix}", file=sys.stderr)
        return 1

    # Use [input_path] when args.file; otherwise use documents(input_path).
    pending = [input_path] if args.file else documents(input_path)
    # Extraction-only mode skips existing outputs; database mode performs stronger manifest checks
    # later.
    if not args.force and not args.import_db and not args.figures_only:
        # Collect items from pending only where not (out_dir / p.stem / 'data.jsonl').exists().
        remaining = []
        for path in pending:
            # Existing outputs must pass provenance/image checks; never silently skip old results.
            if (out_dir / path.stem / "data.jsonl").exists():
                try:
                    verify_artifacts(out_dir / path.stem, path, require_classification=True)
                except ValueError as exc:
                    parser.error(str(exc))
            else:
                remaining.append(path)
        pending = remaining

    # Return without calling an agent when every selected document is already handled.
    if not pending:
        print(f"{input_path} 没有待处理的文档（加 --force 可重跑）")
        return 0

    # Reject the input: 文档有重复文件名主干，会写入同一输出文件；请先重命名.
    if len({p.stem for p in pending}) != len(pending):
        parser.error("文档有重复文件名主干，会写入同一输出文件；请先重命名")

    # Use args.budget when args.budget exceeds 0; otherwise use None.
    budget = args.budget if args.budget > 0 else None
    env = child_env(args.agent)
    # Use the selected backend's transport, authentication, and result conventions.
    if args.agent == "claude" and settings.anthropic_api_key:
        # Use '$%.2f' % budget when budget is truthy; otherwise use '不限'.
        print(f"后端：Claude API，模型 {model}，单份上限 "
              f"{'$%.2f' % budget if budget else '不限'}")
    # Use the selected backend's transport, authentication, and result conventions.
    elif args.agent == "claude":
        print(f"后端：Claude 订阅，模型 {model}（--budget 不生效）")
    # Use the selected backend's transport, authentication, and result conventions.
    elif args.agent == "codex":
        # Apply the explicit fallbacks to missing/empty values while retaining any reported nonempty
        # values.
        print(f"后端：Codex，模型 {model or '本机默认'}，API "
              f"{settings.openai_base_url or 'OpenAI 默认端点'}")
    # Use the selected backend's transport, authentication, and result conventions.
    elif args.agent == "kimi":
        # Prefer model; if empty or absent, fall back to '本机默认'.
        print(f"后端：Kimi Code，模型 {model or '本机默认'}")
        print("用量：Kimi Code 未返回词元统计时显示未知")
    # Otherwise, report this outcome to the command-line operator.
    else:
        # Prefer model; if empty or absent, fall back to '本机默认'.
        print(f"后端：ZCode，模型 {model or '本机默认'}")
        # Explain missing cost prices without inventing a backend charge.
        if args.input_price is None or args.output_price is None:
            print("费用：可传 --input-price、--cached-input-price、"
                  "--output-price 计算")

    print(f"输出：{out_dir.relative_to(REPO)}")
    # Use '启用' when args.subagent equals 'true'; otherwise use '关闭'.
    print(f"数据独立交叉核对：{'启用' if args.subagent == 'true' else '关闭'}")
    print(f"并发文档数：{args.workers}")
    print(f"待处理 {len(pending)} 份：")
    # Preview each document's destination before starting work.
    for path in pending:
        print(f"  {path.name} → {out_dir.relative_to(REPO) / path.stem}")
    print("图像提取：独立图像子代理；" + ("仅补图" if args.figures_only else "随数据提取"))
    # Show the configured target database when import is requested.
    if args.import_db:
        print(f"目标数据库：{settings.pg_database}；流程：提取 → 规范化与质检 → 暂存 → 实体比对 → 入库")
    # Preview the planned operation and return before the subsequent execution stage.
    if args.dry_run:
        print("预览结束：未调用模型，未连接或修改数据库")
        return 0

    if not args.figures_only and not settings.openrouter_api_key:
        parser.error("请配置 OPENROUTER_API_KEY；Jev 与其他 OpenRouter 调用共用此 key")

    # Backfill is an artifact operation; database import can be run separately after it succeeds.
    if args.figures_only and args.import_db:
        parser.error("--figures-only 请勿与 --import-db 同用；补图完成后单独入库")
    runner = run_one
    runner_options = {}
    # Verify connectivity and migrations before any potentially paid extraction.
    if args.import_db:
        from cart_db import ingest
        from cart_db.pipeline import run_document, save_error
        print("正在检查数据库连接和字段版本……", flush=True)
        # Capture preflight errors before scheduling document jobs.
        try:
            # Close the database connection when this operation finishes or raises.
            with ingest.connect() as conn:
                ingest.migrate(conn)
        # Save a redacted database-preflight diagnostic and exit before launching any model.
        except Exception as exc:
            out_dir.mkdir(parents=True, exist_ok=True)
            log = out_dir / "database_preflight_error.json"
            save_error(log, exc, env)
            print(f"数据库准备失败，尚未调用模型；请检查数据库配置、权限及迁移。诊断记录：{log}", file=sys.stderr)
            return 1
        runner = run_document
        runner_options = dict(extract=run_one, force=args.force)
        print("数据库准备完成", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    failures, total_cost, unknown_cost, unknown_usage = 0, 0.0, False, False
    total_usage = empty_usage()

    reports = []
    # Own the progress display and worker pool until all document jobs complete or are canceled.
    with ExtractionProgress(pending, enabled=not args.no_progress,
                            title="提取与入库" if args.import_db else "文档提取") as progress, \
            progress.workers(args.workers) as pool:
        # Build mapped values from pending.
        futures = {
            pool.submit(
                runner, path, **runner_options, agent=args.agent, out_dir=out_dir, timeout=args.timeout,
                budget=budget, env=env, model=model, effort=args.effort,
                input_price=args.input_price,
                cached_input_price=args.cached_input_price,
                output_price=args.output_price,
                subagent=args.subagent == "true",
                figures_only=args.figures_only,
                validation_retries=args.validation_retries,
                on_status=(lambda message, p=path: progress.update(p, message)),
                cancel_event=progress.cancel_event,
            ): path for path in pending
        }
        # Collect document results as workers finish; preserve each result's source path.
        for index, future in enumerate(as_completed(futures), 1):
            path = futures[future]
            # Collect a failed worker as a document result so other completed work can still be
            # reported.
            try:
                result = future.result()
            # Convert an unexpected worker failure into a per-document result so other completed
            # jobs remain reportable.
            except Exception as exc:
                from cart_db.pipeline import save_error
                log = out_dir / (path.stem + ".runner_error.json")
                # Failure to save diagnostics must itself be reported clearly.
                try:
                    save_error(log, exc, env)
                    reason = f"任务异常，未完成处理；诊断记录：{log}"
                # If diagnostics cannot be written, report the output-directory failure directly.
                except OSError:
                    reason = "任务异常且无法保存诊断记录；请检查输出目录权限与剩余空间"
                result = dict(ok=False, reason=reason,
                              cost=None, usage=empty_usage(), usage_known=False, seconds=0)
            report = [f"\n[{index}/{len(pending)}] {path.name}"]
            # Retain an unknown-cost flag alongside the sum of known charges.
            if result["cost"] is None:
                unknown_cost = True
            # Add known document costs to the run total; unknown costs remain separately flagged.
            else:
                total_cost += result["cost"]
            # Aggregate the reported token categories across documents.
            for key, value in result["usage"].items():
                total_usage[key] += value
            # Keep the unknown-usage flag once any document lacks usage metadata.
            unknown_usage = unknown_usage or not result["usage_known"]

            # Use '成功' when result['ok']; otherwise use '失败'.
            status = "成功" if result["ok"] else "失败"
            # Use f"${result['cost']:.4f}" when result cost is supplied; otherwise use '费用未知'.
            cost_text = f"${result['cost']:.4f}" if result["cost"] is not None else "费用未知"
            # Use '草稿（未发布）：' + tally(Path(result['draft_dir']), path.stem) when
            # result.get('draft_dir'); otherwise use tally(out_dir / path.stem, path.stem).
            output_text = (
                "草稿（未发布）：" + tally(Path(result['draft_dir']), path.stem)
                if result.get('draft_dir') else tally(out_dir / path.stem, path.stem)
            )
            report.append(f"  {status} {result['seconds']:.0f} 秒  {cost_text}  "
                  f"{usage_text(result['usage'], result['usage_known'])}  "
                  f"{output_text}")
            # Attach a database report only when the pipeline returned one.
            if result.get("database"):
                report.append(report_text(result["database"]))
                report.append(f"  入库报告：{result['report_path']}")
            # Count failed documents and report their retained diagnostics or draft path.
            if not result["ok"]:
                failures += 1
                report.append(f"  ↳ {result.get('user_reason', result['reason'])}")
            # Use result['reason'] if args.import_db else f'已完成 · {output_text} · 校验通过' when
            # result['ok']; otherwise use result.get('user_reason', result['reason']).
            progress.finish(path, result["ok"],
                            (result["reason"] if args.import_db else f"已完成 · {output_text} · 校验通过")
                            if result["ok"] else result.get("user_reason", result["reason"]),
                            result["seconds"])
            # Buffer final reports while the live panel owns the terminal.
            if progress.enabled:
                reports.extend(report)
            # Otherwise, report this outcome to the command-line operator.
            else:
                print("\n".join(report), flush=True)

    # Print buffered reports after the interactive display has closed.
    if reports:
        print("\n".join(reports))

    # Use ' + 未知费用' when unknown cost is truthy; otherwise use ''.
    total_cost_text = f"${total_cost:.4f}" + (" + 未知费用" if unknown_cost else "")
    print(f"\n完成 {len(pending) - failures}/{len(pending)}，合计 "
          f"{total_cost_text}，{usage_text(total_usage, not unknown_usage)}")
    # Use 1 when failures is truthy; otherwise use 0.
    return 1 if failures else 0


# Run the command only when invoked as a script, not when imported by tests or other modules.
if __name__ == "__main__":
    raise SystemExit(main())
