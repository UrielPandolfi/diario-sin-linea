import logging

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

router = APIRouter()
logger = logging.getLogger(__name__)


def _postgres_ok() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("postgres health check failed")
        return False


def _redis_ok() -> bool:
    try:
        client = redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:
        logger.exception("redis health check failed")
        return False


@router.get("/health")
def health() -> JSONResponse:
    postgres = "ok" if _postgres_ok() else "error"
    redis_status = "ok" if _redis_ok() else "error"
    healthy = postgres == "ok" and redis_status == "ok"
    return JSONResponse(
        {
            "status": "ok" if healthy else "error",
            "postgres": postgres,
            "redis": redis_status,
        },
        status_code=200 if healthy else 503,
    )
