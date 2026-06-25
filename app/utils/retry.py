"""
PDF Studio - 带重试的任务执行辅助
"""
from __future__ import annotations

from typing import Callable, Optional, TypeVar

T = TypeVar("T")


def run_with_retry(
    func: Callable[[], T],
    *,
    max_attempts: int = 1,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> T:
    """
    执行 func，失败时按 max_attempts 重试。

    Args:
        func: 无参 callable
        max_attempts: 最大尝试次数（至少 1）
        on_retry: 重试前回调 (attempt_index, exception)，attempt_index 从 1 起
    """
    attempts = max(1, max_attempts)
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            if on_retry:
                on_retry(attempt, exc)

    assert last_error is not None
    raise last_error
