from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from app.api.deps import DbSession
from app.models import ArticleHeroImage
from app.services.feed_ranking import DEFAULT_LIMIT, FeedRankingService, clamp_limit
from app.services.search_service import SearchService

router = APIRouter(prefix="/api/v1", tags=["public"])


def _public_error(exc: ValueError) -> HTTPException:
    detail = str(exc) or "invalid_request"
    code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def _hero_file(article_id: UUID, db: DbSession, v: str | None) -> Response:
    del v
    row = db.get(ArticleHeroImage, article_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada")
    return Response(
        content=bytes(row.png_bytes),
        media_type=row.content_type or "image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/media/heroes/{article_id}.png")
def get_hero_image_png(article_id: UUID, db: DbSession, v: str | None = None) -> Response:
    return _hero_file(article_id, db, v)


@router.get("/media/heroes/{article_id}.webp")
def get_hero_image_webp(article_id: UUID, db: DbSession, v: str | None = None) -> Response:
    return _hero_file(article_id, db, v)


@router.get("/articles/{key}")
def get_article(key: str, db: DbSession) -> dict:
    payload = FeedRankingService(db).get_article(key)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    return payload


@router.get("/feed")
def feed(
    db: DbSession,
    scope: str = "main",
    locality: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> dict:
    try:
        return FeedRankingService(db).feed(scope=scope, locality=locality, limit=clamp_limit(limit), cursor=cursor)
    except ValueError as exc:
        raise _public_error(exc) from exc


@router.get("/local")
def local(
    db: DbSession,
    locality: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> dict:
    try:
        return FeedRankingService(db).feed(
            scope="local", locality=locality, limit=clamp_limit(limit), cursor=cursor
        )
    except ValueError as exc:
        raise _public_error(exc) from exc


@router.get("/nearby")
def nearby(
    db: DbSession,
    locality: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> dict:
    try:
        return FeedRankingService(db).nearby(locality=locality or "", limit=clamp_limit(limit))
    except ValueError as exc:
        raise _public_error(exc) from exc


@router.get("/live")
def live(
    db: DbSession,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> dict:
    try:
        return FeedRankingService(db).live(limit=clamp_limit(limit), cursor=cursor)
    except ValueError as exc:
        raise _public_error(exc) from exc


@router.get("/now")
def now(db: DbSession, limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50)) -> dict:
    return FeedRankingService(db).now(limit=clamp_limit(limit))


@router.get("/search")
def search(
    db: DbSession,
    q: str | None = None,
    locality: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> dict:
    try:
        return SearchService(db).search(query=q or "", locality=locality, limit=clamp_limit(limit))
    except ValueError as exc:
        raise _public_error(exc) from exc


@router.get("/localities")
def localities(db: DbSession) -> dict:
    return FeedRankingService(db).localities()


@router.get("/sitemap-articles")
def sitemap_articles(db: DbSession) -> dict:
    return FeedRankingService(db).sitemap_articles()
