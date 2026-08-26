from __future__ import annotations

import logging

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "sin_linea:poll:"
_KEY_SUFFIX = ":new_events"
_KEY_TTL_SECONDS = 60 * 60 * 24


def allow_new_event_pipeline(poll_id: str | None) -> bool:
    """Reserve a pipeline slot for a newly created Event in this poll.

    Returns True if research (and the rest of the chain) should be enqueued.
    MAX_NEW_EVENTS_PER_POLL=0 means unlimited. Without poll_id and MAX>0,
    automatic chaining is denied (safe default); Admin research is separate.
    """
    settings = get_settings()
    max_events = int(settings.max_new_events_per_poll or 0)
    if max_events <= 0:
        return True
    if not poll_id:
        return False

    key = f"{_KEY_PREFIX}{poll_id}{_KEY_SUFFIX}"
    client = redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
    try:
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, _KEY_TTL_SECONDS)
        return count <= max_events
    except Exception:
        logger.exception("pipeline budget redis failed; denying automatic research")
        return False
    finally:
        client.close()
