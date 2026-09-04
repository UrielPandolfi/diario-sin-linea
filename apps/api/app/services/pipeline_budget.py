from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "sin_linea:poll:"
_KEY_SUFFIX = ":new_events"
_FILL_SUFFIX = ":fill_enqueues"
_CLAIMED_SUFFIX = ":claimed_items"
_KEY_TTL_SECONDS = 60 * 60 * 24
# Admin "fill quota" may keep detecting duplicates/skips until this many
# extra enqueues (on top of the initial batch), so one click can find N new
# sucesos without LLM-scanning the whole feed.
_FILL_ENQUEUE_MULTIPLIER = 5


@contextmanager
def _redis_client() -> Iterator[redis.Redis]:
    settings = get_settings()
    client = redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        client.close()


def _slot_key(poll_id: str) -> str:
    return f"{_KEY_PREFIX}{poll_id}{_KEY_SUFFIX}"


def _fill_key(poll_id: str) -> str:
    return f"{_KEY_PREFIX}{poll_id}{_FILL_SUFFIX}"


def _max_events() -> int:
    return int(get_settings().max_new_events_per_poll or 0)


def allow_new_event_pipeline(poll_id: str | None) -> bool:
    """Reserve a detection+pipeline slot for one SourceItem in this poll.

    Returns True if event detection (LLM) may run and, if a new Event is
    created, research→publish should be enqueued.
    MAX_NEW_EVENTS_PER_POLL=0 means unlimited. Without poll_id and MAX>0,
    automatic detection is denied (safe default); Admin **Investigar** is separate.
    """
    max_events = _max_events()
    if max_events <= 0:
        return True
    if not poll_id:
        return False

    key = _slot_key(poll_id)
    try:
        with _redis_client() as client:
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, _KEY_TTL_SECONDS)
            if count <= max_events:
                return True
            # Do not leave a ghost reservation above the cap (retries / extra jobs).
            clamped = int(client.decr(key))
            if clamped < 0:
                client.set(key, 0)
                client.expire(key, _KEY_TTL_SECONDS)
            return False
    except Exception:
        logger.exception("pipeline budget redis failed; denying automatic detection")
        return False


def release_new_event_pipeline(poll_id: str | None) -> None:
    """Give back a slot when detection did not create a new Event."""
    max_events = _max_events()
    if max_events <= 0 or not poll_id:
        return
    key = _slot_key(poll_id)
    try:
        with _redis_client() as client:
            count = int(client.decr(key))
            if count < 0:
                client.set(key, 0)
                client.expire(key, _KEY_TTL_SECONDS)
    except Exception:
        logger.exception("pipeline budget redis release failed")


def allow_fill_enqueue(poll_id: str | None) -> bool:
    """Whether admin fill-quota may enqueue another PENDING item for this poll."""
    max_events = _max_events()
    if max_events <= 0 or not poll_id:
        return False
    limit = max_events * _FILL_ENQUEUE_MULTIPLIER
    key = _fill_key(poll_id)
    try:
        with _redis_client() as client:
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, _KEY_TTL_SECONDS)
            return count <= limit
    except Exception:
        logger.exception("pipeline budget fill enqueue redis failed; stopping fill")
        return False


def claim_detection_item(poll_id: str | None, item_id: str) -> bool:
    """Mark a SourceItem as already queued for this poll. False = skip, already claimed."""
    if not poll_id:
        return True
    key = f"{_KEY_PREFIX}{poll_id}{_CLAIMED_SUFFIX}"
    try:
        with _redis_client() as client:
            added = int(client.sadd(key, item_id))
            if added:
                client.expire(key, _KEY_TTL_SECONDS)
            return added == 1
    except Exception:
        logger.exception("pipeline budget claim redis failed; allowing enqueue")
        return True
