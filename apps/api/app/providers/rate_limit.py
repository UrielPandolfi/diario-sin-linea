from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_QUOTA_CODES = {"insufficient_quota", "billing_not_active"}
_TRY_AGAIN_IN = re.compile(
    r"try again in\s+([\d.]+)\s*(ms|milliseconds|s|seconds)?",
    re.IGNORECASE,
)
_SECONDS_PER_RETRY_BUDGET = 60.0


def openai_error_code(exc: BaseException) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(err, dict):
            raw = err.get("code") or err.get("type")
            if raw:
                return str(raw)
    text = str(exc).lower()
    if "insufficient_quota" in text:
        return "insufficient_quota"
    if "rate_limit" in text:
        return "rate_limit_exceeded"
    return None


def is_quota_error(exc: BaseException) -> bool:
    code = (openai_error_code(exc) or "").lower()
    if code in _QUOTA_CODES:
        return True
    return "insufficient_quota" in str(exc).lower()


def is_transient_rate_limit(exc: BaseException) -> bool:
    if is_quota_error(exc):
        return False
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    name = type(exc).__name__
    if name == "RateLimitError":
        return True
    text = str(exc).lower()
    return "rate_limit_exceeded" in text or "rate limit reached" in text


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    token = value.split(",")[0].strip()
    if not token:
        return None
    try:
        seconds = float(token)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(token)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _header_retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if headers is None:
        return None
    return parse_retry_after(headers.get("retry-after"))


def _message_retry_after(exc: BaseException) -> float | None:
    match = _TRY_AGAIN_IN.search(str(exc))
    if match is None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error") if isinstance(body.get("error"), dict) else {}
            if isinstance(err, dict):
                match = _TRY_AGAIN_IN.search(str(err.get("message") or ""))
    if match is None:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    if unit.startswith("ms"):
        return amount / 1000.0
    return amount


def retry_wait_seconds(exc: BaseException, *, attempt: int) -> float:
    header = _header_retry_after(exc)
    if header is not None:
        return header
    from_message = _message_retry_after(exc)
    if from_message is not None:
        return from_message
    return float(min(2 ** max(attempt - 1, 0), 32))


def _jitter(wait: float) -> float:
    cap = min(1.0, max(0.05, wait * 0.1))
    return random.uniform(0.05, cap)


def with_rate_limit_retry(call: Callable[[], T], *, sleeper: Callable[[float], None] | None = None) -> T:
    """Reintenta solo 429 temporales. El SDK debe ir con max_retries=0."""
    settings = get_settings()
    max_retries = max(0, int(settings.job_max_retries))
    max_elapsed = max_retries * _SECONDS_PER_RETRY_BUDGET
    sleep = sleeper or time.sleep
    started = time.monotonic()
    attempt = 0
    while True:
        try:
            return call()
        except Exception as exc:
            if not is_transient_rate_limit(exc):
                raise
            attempt += 1
            wait = retry_wait_seconds(exc, attempt=attempt)
            elapsed = time.monotonic() - started
            remaining = max_elapsed - elapsed
            if attempt > max_retries or wait > remaining:
                logger.warning(
                    "openai rate_limit exhausted attempt=%s wait=%.3fs elapsed=%.3fs remaining=%.3fs code=%s",
                    attempt,
                    wait,
                    elapsed,
                    remaining,
                    openai_error_code(exc),
                )
                raise
            delay = wait + _jitter(wait)
            if delay < wait:
                delay = wait
            logger.info(
                "openai rate_limit retry attempt=%s delay=%.3fs wait=%.3fs code=%s",
                attempt,
                delay,
                wait,
                openai_error_code(exc),
            )
            sleep(delay)
