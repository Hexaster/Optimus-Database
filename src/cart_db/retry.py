"""Shared retry policy for external calls."""
from __future__ import annotations

import time

MAX_RETRIES = 5


class CallFailure(ValueError):
    """A sanitized call failure with transport-specific retry information."""

    def __init__(self, message, *, retryable=True, retry_after=0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def call_with_retry(operation, *, timeout, label, on_status, attempts=None):
    """Pass remaining time to each call; retry at most five times on CallFailure."""
    attempts = attempts if attempts is not None else []
    deadline = time.monotonic() + timeout
    last_error = "时间额度耗尽"
    for attempt in range(MAX_RETRIES + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError(f"{label} 总超时，已尝试 {len(attempts)} 次；{last_error}")
        try:
            result = operation(remaining)
        except CallFailure as exc:
            last_error = str(exc)
            attempts.append({"attempt": attempt + 1, "status": "failed", "error": last_error})
            if not exc.retryable or attempt == MAX_RETRIES:
                raise ValueError(f"{label} 失败，已尝试 {attempt + 1} 次：{last_error}") from None
            delay = max(2 ** attempt, min(exc.retry_after, 60))
            if deadline - time.monotonic() <= delay:
                raise ValueError(f"{label} 剩余时间不足，已尝试 {attempt + 1} 次：{last_error}") from None
            on_status(f"{label} 失败（{last_error}），{delay}s 后进行第 {attempt + 1}/{MAX_RETRIES} 次重试")
            time.sleep(delay)
        else:
            attempts.append({"attempt": attempt + 1, "status": "success"})
            return result
