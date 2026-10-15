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


def clean(text):
    return " ".join("".join(c for c in str(text) if c.isprintable() or c.isspace()).split())


def codex_status(event):
    """Only public progress messages and observed actions, never reasoning text."""
    kind = event.get("type")
    if kind == "turn.started":
        return "正在处理文档，等待新的进度"
    if kind == "error":
        return "连接或执行遇到问题，等待后续事件"
    if kind == "turn.failed":
        return "本次调用失败，正在收集诊断信息"
    if kind == "turn.completed":
        return "模型已返回，准备校验输出"
    item = event.get("item") or {}
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if item_type == "agent_message":
        for line in str(item.get("text", "")).splitlines():
            if line.startswith("进度："):
                return clean(line.removeprefix("进度："))[:180] or None
    if item_type == "command_execution":
        if kind == "item.started":
            return "正在执行文档处理工具"
        if kind == "item.completed":
            return "工具执行结束，正在处理返回结果"
    if item_type == "file_change":
        return "正在处理文件变更" if kind == "item.started" else "文件变更已返回，继续核对输出"
    if item_type == "web_search":
        return "正在检索来源材料" if kind == "item.started" else "来源检索已返回，继续核对材料"
    if item_type == "mcp_tool_call":
        return "正在调用资料工具" if kind == "item.started" else "资料工具已返回，继续处理结果"
    return None


def claude_status(event):
    """Read public assistant messages and tool events, excluding thinking blocks."""
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return "Claude Code 已启动，正在准备抽取"
    if kind == "result":
        if event.get("is_error") or event.get("subtype") != "success":
            return "本次调用失败，正在收集诊断信息"
        return "模型已返回，准备校验输出"
    if kind == "tool_progress":
        return "工具仍在执行，等待返回结果"
    if kind not in {"assistant", "user"}:
        return None
    message = event.get("message") or {}
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return None
    status = None
    for block in message["content"]:
        if not isinstance(block, dict):
            continue
        if kind == "assistant" and block.get("type") == "text":
            for line in str(block.get("text", "")).splitlines():
                if line.startswith("进度："):
                    status = clean(line.removeprefix("进度："))[:180] or status
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
        elif kind == "user" and block.get("type") == "tool_result":
            status = ("工具返回错误，等待提取程序处理" if block.get("is_error")
                      else "工具执行结束，正在处理返回结果")
    return status


def stream_agent(command, *, cwd, env, timeout, on_status, cancel_event=None,
                 status_parser=codex_status):
    """Drain both pipes as they arrive; preserve output for existing validation/accounting."""
    started = time.monotonic()
    chunks = {"stdout": [], "stderr": []}
    pending = b""

    def consume(line):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(event, dict):
            status = status_parser(event)
            if status:
                for key, secret in env.items():
                    if secret and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                        status = status.replace(secret, "[REDACTED]")
                on_status(status)

    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, start_new_session=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                for name in chunks:
                    selector.register(getattr(process, name), selectors.EVENT_READ, name)
                while selector.get_map() or process.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("抽取已取消")
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout,
                            output=b"".join(chunks["stdout"]), stderr=b"".join(chunks["stderr"]))
                    for key, _ in selector.select(min(remaining, 0.2)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        chunks[key.data].append(chunk)
                        if key.data == "stdout":
                            pending += chunk
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                consume(line)
                if pending:
                    consume(pending)
            process.wait()
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
    return subprocess.CompletedProcess(command, process.returncode,
        b"".join(chunks["stdout"]).decode("utf-8", errors="replace"),
        b"".join(chunks["stderr"]).decode("utf-8", errors="replace"))


class ExtractionProgress:
    def __init__(self, paths, *, enabled=True, console=None, title="文档提取"):
        self.title = title
        self.console = console or Console()
        self.enabled = enabled and self.console.is_terminal and not self.console.is_dumb_terminal
        self.lock = Lock()
        self.cancel_event = Event()
        self.rows = {p: dict(name=p.name, state="queued", status="等待执行", started=None,
                            seconds=0) for p in paths}
        self.live = None

    @contextmanager
    def workers(self, count):
        with ThreadPoolExecutor(max_workers=count) as pool:
            try:
                yield pool
            except BaseException:
                self.cancel_event.set()
                pool.shutdown(wait=True, cancel_futures=True)
                raise

    def update(self, path, status):
        with self.lock:
            row = self.rows[path]
            if row["started"] is None:
                row["started"] = time.monotonic()
            changed = row["status"] != clean(status)
            row.update(state="running", status=clean(status))
            if not self.enabled and changed:
                elapsed = time.monotonic() - row["started"]
                self.console.print(Text(f"[{row['name']} · {elapsed:.0f} 秒] {row['status']}"))

    def finish(self, path, ok, status, seconds):
        with self.lock:
            self.rows[path].update(state="done" if ok else "failed",
                                   status=clean(status), seconds=seconds)

    def __rich_console__(self, console, options):
        with self.lock:
            rows = [r.copy() for r in self.rows.values()]
        running = sum(r["state"] == "running" for r in rows)
        done = sum(r["state"] == "done" for r in rows)
        failed = sum(r["state"] == "failed" for r in rows)
        lines = [Text(f"{self.title} · 共 {len(rows)} 篇 · 运行 {running} · 完成 {done} · 失败 {failed}", style="bold cyan")]
        height = max(3, console.size.height - 2)
        # Keep document order stable; compact inactive rows before paging active work.
        compact = 1 + 2 * len(rows) > height
        required = 1 + sum(2 if r["state"] == "running" or not compact else 1 for r in rows)
        if required > height:
            active = [r for r in rows if r["state"] == "running"]
            inactive = [r for r in rows if r["state"] != "running"]
            capacity = max(1, (height - 2) // 2)
            offset = (int(time.monotonic() // 5) * capacity) % max(1, len(active))
            selected = (active + active)[offset:offset + min(capacity, len(active))]
            room = max(0, height - 2 - 2 * len(selected))
            rows = selected + inactive[:room]
            lines.append(Text(f"窗口较小 · 展示 {len(rows)}/{len(self.rows)} 篇 · 运行项每 5 秒轮换", style="dim"))
        now = time.monotonic()
        for row in rows:
            state = row["state"]
            icon = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(now * 10) % 10] if state == "running" else {"queued": "○", "done": "✓", "failed": "✗"}[state]
            color = {"queued": "dim", "running": "cyan", "done": "green", "failed": "red"}[state]
            seconds = now - row["started"] if state == "running" else row["seconds"]
            elapsed = f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}" if state != "queued" else "排队"
            label = Text(f"{icon} {elapsed}  {clean(row['name'])}", style=color, no_wrap=True, overflow="ellipsis")
            if compact and state != "running":
                label.append(f" · {row['status']}")
            lines.append(label)
            if not compact or state == "running":
                lines.append(Text("  " + row["status"], no_wrap=True, overflow="ellipsis"))
        yield Group(*lines)

    def __enter__(self):
        if self.enabled:
            self.live = Live(self, console=self.console, refresh_per_second=10, transient=True)
            self.live.start()
        return self

    def __exit__(self, *exc):
        if self.live:
            self.live.stop()
