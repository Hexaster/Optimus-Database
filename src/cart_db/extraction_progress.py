"""Live document status and incremental Codex / Claude Code JSONL transport."""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from threading import Event, Lock
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text


# Remove terminal control characters and collapse whitespace before displaying public progress.
def clean(text):
    # Collect items from str(text) only where c.isprintable() or c.isspace().
    return " ".join("".join(c for c in str(text) if c.isprintable() or c.isspace()).split())


def codex_status(event):
    """Only public progress messages and observed actions, never reasoning text."""
    kind = event.get("type")
    # A started turn has no observed action yet.
    if kind == "turn.started":
        return "正在处理文档，等待新的进度"
    # Report a transport/execution problem without exposing raw diagnostic content.
    if kind == "error":
        message = str(event.get("message") or event.get("error") or "").lower()
        if "429" in message or "rate limit" in message:
            return "API 限流，等待重试"
        if "401" in message or "403" in message or "unauthorized" in message:
            return "API 认证或权限失败，等待调用结束"
        if "timeout" in message or "timed out" in message:
            return "API 请求超时，等待重试"
        if "stream disconnected" in message or "reconnecting" in message:
            return "API 流连接中断，正在重连"
        if "connection" in message or "connect" in message:
            return "API 网络连接失败，等待重试"
        return "Codex 返回错误事件，具体原因将在调用结束后保存到诊断日志"
    # A failed turn is waiting for the runner to collect diagnostics.
    if kind == "turn.failed":
        return "本次调用失败，正在收集诊断信息"
    # Completion hands control back to output validation.
    if kind == "turn.completed":
        return "模型已返回，准备校验输出"
    # Use an empty mapping when event.get('item') is missing or empty.
    item = event.get("item") or {}
    # Malformed items provide no reliable public status.
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    # Only explicit public progress lines are eligible for display.
    if item_type == "agent_message":
        # Scan message lines without displaying unrelated model text.
        for line in str(item.get("text", "")).splitlines():
            # Display the declared public progress prefix, sanitized and length-limited.
            if line.startswith("进度："):
                # Represent an empty clean(line.removeprefix('进度：'))[:180] as None instead of a
                # reported value.
                return clean(line.removeprefix("进度："))[:180] or None
    # Command events describe observed tool execution, not reasoning.
    if item_type == "command_execution":
        # A started command means the tool is still running.
        if kind == "item.started":
            return "正在执行文档处理工具"
        # A completed command means its result is now being processed.
        if kind == "item.completed":
            return "工具执行结束，正在处理返回结果"
    # Distinguish pending file changes from completed changes.
    if item_type == "file_change":
        # Use '正在处理文件变更' when kind equals 'item.started'; otherwise use '文件变更已返回，继续核对输出'.
        return "正在处理文件变更" if kind == "item.started" else "文件变更已返回，继续核对输出"
    # Distinguish an active source search from returned search material.
    if item_type == "web_search":
        # Use '正在检索来源材料' when kind equals 'item.started'; otherwise use '来源检索已返回，继续核对材料'.
        return "正在检索来源材料" if kind == "item.started" else "来源检索已返回，继续核对材料"
    # Report MCP tool lifecycle without displaying private tool arguments.
    if item_type == "mcp_tool_call":
        # Use '正在调用资料工具' when kind equals 'item.started'; otherwise use '资料工具已返回，继续处理结果'.
        return "正在调用资料工具" if kind == "item.started" else "资料工具已返回，继续处理结果"
    return None


def claude_status(event):
    """Read public assistant messages and tool events, excluding thinking blocks."""
    kind = event.get("type")
    # A system initialization event marks backend startup.
    if kind == "system" and event.get("subtype") == "init":
        return "Claude Code 已启动，正在准备抽取"
    # The terminal result tells the runner whether to validate output or diagnose failure.
    if kind == "result":
        # Error and non-success result subtypes indicate failure.
        if event.get("is_error") or event.get("subtype") != "success":
            return "本次调用失败，正在收集诊断信息"
        return "模型已返回，准备校验输出"
    # A tool-progress event confirms continued execution without claiming completion.
    if kind == "tool_progress":
        return "工具仍在执行，等待返回结果"
    # Ignore other event kinds that contain no supported public progress.
    if kind not in {"assistant", "user"}:
        return None
    # Use an empty mapping when event.get('message') is missing or empty.
    message = event.get("message") or {}
    # Require a structured content-block list before inspecting message text.
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return None
    status = None
    # Inspect public blocks individually; thinking blocks are never rendered.
    for block in message["content"]:
        # Ignore malformed content blocks.
        if not isinstance(block, dict):
            continue
        # Assistant text can contain an explicit public progress line.
        if kind == "assistant" and block.get("type") == "text":
            # Search text line by line for the declared progress marker.
            for line in str(block.get("text", "")).splitlines():
                # Retain only the sanitized progress message, not the rest of the response.
                if line.startswith("进度："):
                    # Prefer clean(line.removeprefix('进度：'))[:180]; if empty or absent, fall back to
                    # status.
                    status = clean(line.removeprefix("进度："))[:180] or status
        # Map observed tool names to readable task descriptions.
        elif kind == "assistant" and block.get("type") == "tool_use":
            status = {
                "Read": "正在读取文档或字段定义",
                "Glob": "正在定位所需文件",
                "Grep": "正在检索文档内容",
                "Bash": "正在执行文档处理工具",
                "Write": "正在写入抽取文件",
                "Edit": "正在更新抽取文件",
                "WebSearch": "正在检索来源材料",
                "WebFetch": "正在读取在线来源材料",
            }.get(block.get("name"), "正在调用资料工具")
        # A returned tool result updates status while leaving errors for the extractor to handle.
        elif kind == "user" and block.get("type") == "tool_result":
            # Use '工具返回错误，等待提取程序处理' when block.get('is_error'); otherwise use '工具执行结束，正在处理返回结果'.
            status = ("工具返回错误，等待提取程序处理" if block.get("is_error")
                      else "工具执行结束，正在处理返回结果")
    return status


def stream_agent(command, *, cwd, env, timeout, on_status, cancel_event=None,
                 status_parser=codex_status):
    """Drain both pipes as they arrive; preserve output for existing validation/accounting."""
    started = time.monotonic()
    chunks = {"stdout": [], "stderr": []}
    pending = b""

    # Decode one transport event and display only sanitized, credential-redacted public status.
    def consume(line):
        # Ignore non-JSON transport lines rather than treating them as status events.
        try:
            event = json.loads(line)
        # On (ValueError, UnicodeDecodeError), finish without producing another result.
        except (ValueError, UnicodeDecodeError):
            return
        # Only object-shaped events can be interpreted by the backend parser.
        if isinstance(event, dict):
            status = status_parser(event)
            # Emit status only when the parser recognized a supported public event.
            if status:
                # Check environment values for credentials that need redaction from diagnostics.
                for key, secret in env.items():
                    # Mask credential values before displaying or persisting diagnostic text.
                    if secret and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                        status = status.replace(secret, "[REDACTED]")
                on_status(status)

    # Own the child process and its pipes for the full streaming/cancellation lifecycle.
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, start_new_session=True) as process:
        # Ensure an interrupted streaming operation kills and reaps its process group.
        try:
            # Monitor stdout and stderr together so a full pipe cannot deadlock the child process.
            with selectors.DefaultSelector() as selector:
                # Register both output pipes so stderr cannot block a child writing stdout.
                for name in chunks:
                    selector.register(getattr(process, name), selectors.EVENT_READ, name)
                # Drain both output pipes until they close and the agent process exits.
                while selector.get_map() or process.poll() is None:
                    # Stop canceled work promptly rather than launching another processing step.
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("抽取已取消")
                    remaining = timeout - (time.monotonic() - started)
                    # Enforce the shared timeout even when the subprocess produces no output.
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout,
                            output=b"".join(chunks["stdout"]), stderr=b"".join(chunks["stderr"]))
                    # Read only ready pipes, using a short wait so cancellation remains responsive.
                    for key, _ in selector.select(min(remaining, 0.2)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        # Unregister EOF pipes to avoid repeatedly selecting a closed stream.
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        chunks[key.data].append(chunk)
                        # Only stdout carries structured events; stderr is retained for diagnostics.
                        if key.data == "stdout":
                            pending += chunk
                            # Consume every complete event line, retaining a partial tail for the
                            # next read.
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                consume(line)
                # Parse the final partial line after all complete event lines are consumed.
                if pending:
                    consume(pending)
            process.wait()
        # On BaseException, attempt the operation and retain its explicit failure path.
        except BaseException:
            # Kill the process group so descendants cannot continue after timeout/cancellation.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            # The child may have exited before SIGKILL; that race needs no further signal.
            except ProcessLookupError:
                pass
            process.wait()
            raise
    return subprocess.CompletedProcess(command, process.returncode,
        b"".join(chunks["stdout"]).decode("utf-8", errors="replace"),
        b"".join(chunks["stderr"]).decode("utf-8", errors="replace"))


class ExtractionProgress:
    # Create shared document state, a cancellation signal, and optional terminal animation.
    def __init__(self, paths, *, enabled=True, console=None, title="文档提取"):
        self.title = title
        # Prefer console; if empty or absent, fall back to Console().
        self.console = console or Console()
        # Enable the live display only when requested and the terminal supports interactive
        # rendering.
        self.enabled = enabled and self.console.is_terminal and not self.console.is_dumb_terminal
        self.lock = Lock()
        self.cancel_event = Event()
        # Build mapped values from paths.
        self.rows = {p: dict(name=p.name, state="queued", status="等待执行", started=None,
                            seconds=0) for p in paths}
        self.live = None

    # Own the document thread pool and signal cancellation before waiting for interrupted workers.
    @contextmanager
    def workers(self, count):
        # Release this managed resource when the enclosed operation completes or fails.
        with ThreadPoolExecutor(max_workers=count) as pool:
            # On interruption, signal all workers before shutting down the pool.
            try:
                yield pool
            # On BaseException, store the mapped value with its provenance.
            except BaseException:
                self.cancel_event.set()
                pool.shutdown(wait=True, cancel_futures=True)
                raise

    # Update one document under a lock and print changed status in noninteractive terminals.
    def update(self, path, status):
        # Hold the progress lock while reading or changing shared worker state.
        with self.lock:
            row = self.rows[path]
            # Start the elapsed timer on the first real status update, not while queued.
            if row["started"] is None:
                row["started"] = time.monotonic()
            changed = row["status"] != clean(status)
            row.update(state="running", status=clean(status))
            # Print changed progress as ordinary lines when interactive rendering is disabled.
            if not self.enabled and changed:
                elapsed = time.monotonic() - row["started"]
                self.console.print(Text(f"[{row['name']} · {elapsed:.0f} 秒] {row['status']}"))

    # Store the final outcome and elapsed time for a document.
    def finish(self, path, ok, status, seconds):
        # Hold the progress lock while reading or changing shared worker state.
        with self.lock:
            # Use 'done' when ok is truthy; otherwise use 'failed'.
            self.rows[path].update(state="done" if ok else "failed",
                                   status=clean(status), seconds=seconds)

    # Render a stable, height-limited view of document status, rotating active work if necessary.
    def __rich_console__(self, console, options):
        # Hold the progress lock while reading or changing shared worker state.
        with self.lock:
            # Build mapped values from self.rows.values().
            rows = [r.copy() for r in self.rows.values()]
        # Build mapped values from rows.
        running = sum(r["state"] == "running" for r in rows)
        # Build mapped values from rows.
        done = sum(r["state"] == "done" for r in rows)
        # Build mapped values from rows.
        failed = sum(r["state"] == "failed" for r in rows)
        lines = [Text(f"{self.title} · 共 {len(rows)} 篇 · 运行 {running} · 完成 {done} · 失败 {failed}", style="bold cyan")]
        height = max(3, console.size.height - 2)
        # Keep document order stable; compact inactive rows before paging active work.
        compact = 1 + 2 * len(rows) > height
        # Build mapped values from rows.
        required = 1 + sum(2 if r["state"] == "running" or not compact else 1 for r in rows)
        # Rotate active documents when the terminal cannot display all running work.
        if required > height:
            # Collect items from rows only where r['state'] == 'running'.
            active = [r for r in rows if r["state"] == "running"]
            # Collect items from rows only where r['state'] != 'running'.
            inactive = [r for r in rows if r["state"] != "running"]
            capacity = max(1, (height - 2) // 2)
            offset = (int(time.monotonic() // 5) * capacity) % max(1, len(active))
            selected = (active + active)[offset:offset + min(capacity, len(active))]
            room = max(0, height - 2 - 2 * len(selected))
            rows = selected + inactive[:room]
            lines.append(Text(f"窗口较小 · 展示 {len(rows)}/{len(self.rows)} 篇 · 运行项每 5 秒轮换", style="dim"))
        now = time.monotonic()
        # Render each selected document with its state, elapsed time, and latest status.
        for row in rows:
            state = row["state"]
            # Use '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[int(now * 10) % 10] when state equals 'running'; otherwise use
            # {'queued': '○', 'done': '✓', 'failed': '✗'}[state].
            icon = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(now * 10) % 10] if state == "running" else {"queued": "○", "done": "✓", "failed": "✗"}[state]
            color = {"queued": "dim", "running": "cyan", "done": "green", "failed": "red"}[state]
            # Use now - row['started'] when state equals 'running'; otherwise use row['seconds'].
            seconds = now - row["started"] if state == "running" else row["seconds"]
            # Use f'{int(seconds) // 60:02d}:{int(seconds) % 60:02d}' when state differs from
            # 'queued'; otherwise use '排队'.
            elapsed = f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}" if state != "queued" else "排队"
            label = Text(f"{icon} {elapsed}  {clean(row['name'])}", style=color, no_wrap=True, overflow="ellipsis")
            # Compact inactive rows to leave more room for running documents.
            if compact and state != "running":
                label.append(f" · {row['status']}")
            lines.append(label)
            # Use a second status line for active rows or when the terminal has space.
            if not compact or state == "running":
                lines.append(Text("  " + row["status"], no_wrap=True, overflow="ellipsis"))
        yield Group(*lines)

    # Start live rendering only when the terminal supports it.
    def __enter__(self):
        # Start the live terminal display only when interactive rendering is supported.
        if self.enabled:
            self.live = Live(self, console=self.console, refresh_per_second=10, transient=True)
            self.live.start()
        return self

    # Stop live rendering so final reports can use the terminal normally.
    def __exit__(self, *exc):
        # Stop the live display only if it was started.
        if self.live:
            self.live.stop()
