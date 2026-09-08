from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_IP_LIMIT = 5
_ARTICLE_LIMIT = 3
_WINDOW_SECONDS = 60 * 60


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


def _incr(key: str, limit: int) -> bool:
    with _redis_client() as client:
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, _WINDOW_SECONDS)
        if count <= limit:
            return True
        client.decr(key)
        return False


def allow_case_submit(ip: str, article_id: UUID | None) -> bool:
    try:
        if not _incr(f"sin_linea:cases:ip:{ip}", _IP_LIMIT):
            return False
        if article_id is not None and not _incr(f"sin_linea:cases:ip_article:{ip}:{article_id}", _ARTICLE_LIMIT):
            return False
        return True
    except Exception:
        logger.exception("case submit redis failed; denying")
        return False
