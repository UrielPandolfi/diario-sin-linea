from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_READER_LIMIT = 30
_IP_LIMIT = 60
_WINDOW_SECONDS = 60 * 60


@contextmanager
def _redis_client() -> Iterator[redis.Redis]:
    client = redis.from_url(
        get_settings().redis_url,
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


def allow_comment(reader_id: str, ip: str) -> bool:
    try:
        if not _incr(f"sin_linea:comments:reader:{reader_id}", _READER_LIMIT):
            return False
        if not _incr(f"sin_linea:comments:ip:{ip}", _IP_LIMIT):
            return False
        return True
    except Exception:
        logger.exception("comment redis failed; denying")
        return False
