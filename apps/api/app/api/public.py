from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import DbSession, require_reader
from app.models import ArticleHeroImage
from app.models.reader import Reader
from app.services.feed_ranking import DEFAULT_LIMIT, FeedRankingService, clamp_limit
from app.services.geo_localities import reader_locality_payload
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


_NO_STORE = {"Cache-Control": "private, no-store"}


@router.get("/feed")
def feed(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    scope: str = "main",
    sort: str | None = None,
    locality: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    try:
        payload = FeedRankingService(db).feed(
            scope=scope,
            locality=locality,
            limit=clamp_limit(limit),
            cursor=cursor,
            sort=sort,
            reader_id=reader.id,
        )
    except ValueError as exc:
        raise _public_error(exc) from exc
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/local")
def local(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    locality: str | None = None,
    province: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    del reader
    try:
        payload = FeedRankingService(db).feed(
            scope="local",
            locality=locality,
            province=province,
            limit=clamp_limit(limit),
            cursor=cursor,
        )
    except ValueError as exc:
        raise _public_error(exc) from exc
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/nearby")
def nearby(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    locality: str | None = None,
    province: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    chosen = (locality or "").strip()
    chosen_province = (province or "").strip() or None
    if not chosen:
        saved = reader_locality_payload(db, reader)
        if saved is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="locality_required")
        chosen = str(saved["name"])
        chosen_province = str(saved["province_name"])
    try:
        payload = FeedRankingService(db).nearby(
            locality=chosen,
            province=chosen_province,
            limit=clamp_limit(limit),
        )
    except ValueError as exc:
        raise _public_error(exc) from exc
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/live")
def live(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    del reader
    try:
        payload = FeedRankingService(db).live(limit=clamp_limit(limit), cursor=cursor)
    except ValueError as exc:
        raise _public_error(exc) from exc
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/now")
def now(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    del reader
    return JSONResponse(FeedRankingService(db).now(limit=clamp_limit(limit)), headers=_NO_STORE)


@router.get("/search")
def search(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    q: str | None = None,
    locality: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    del reader
    try:
        payload = SearchService(db).search(query=q or "", locality=locality, limit=clamp_limit(limit))
    except ValueError as exc:
        raise _public_error(exc) from exc
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/localities")
def localities(db: DbSession, reader: Annotated[Reader, Depends(require_reader)]) -> JSONResponse:
    del reader
    return JSONResponse(FeedRankingService(db).localities(), headers=_NO_STORE)


@router.get("/sitemap-articles")
def sitemap_articles(db: DbSession) -> dict:
    return FeedRankingService(db).sitemap_articles()
