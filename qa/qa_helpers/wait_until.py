"""Polling helper — the only sanctioned way to wait in QA suites (bare sleep() is banned)."""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_until[T](
    fn: Callable[[], T],
    timeout: float = 15,
    interval: float = 0.3,
    message: str | None = None,
) -> T:
    """Call `fn` every `interval` seconds until it returns a truthy value.

    Returns the first truthy result. On timeout raises TimeoutError carrying
    the repr of the last observed state so failures are diagnosable.
    """
    deadline = time.monotonic() + timeout
    while True:
        last = fn()
        if last:
            return last
        if time.monotonic() >= deadline:
            what = message or f"condition {getattr(fn, '__name__', repr(fn))} not met"
            raise TimeoutError(f"{what} within {timeout}s; last observed state: {last!r}")
        time.sleep(interval)
