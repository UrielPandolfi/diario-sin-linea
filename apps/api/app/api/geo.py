from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, require_reader
from app.models.reader import Reader
from app.services.geo_localities import search_localities

router = APIRouter(prefix="/api/v1/geo", tags=["geo"])

_NO_STORE = {"Cache-Control": "private, no-store"}


@router.get("/localities")
def search(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    q: str = Query(default="", max_length=80),
) -> JSONResponse:
    del reader
    return JSONResponse({"items": search_localities(db, q)}, headers=_NO_STORE)
