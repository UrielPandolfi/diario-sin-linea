from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, optional_reader, require_reader
from app.core.config import get_settings
from app.models.geo_locality import GeoLocality
from app.models.reader import Reader
from app.services.geo_localities import reader_locality_payload
from app.services.reader_auth import (
    READER_COOKIE,
    READER_SESSION_TTL,
    hash_password,
    issue_reader_token,
    normalize_email,
    password_matches,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_NO_STORE = {"Cache-Control": "private, no-store"}


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        email = normalize_email(value)
        if email is None:
            raise ValueError("email inválido")
        return email


def _account(db: DbSession, reader: Reader, *, include_ok: bool) -> dict:
    payload: dict = {
        "email": reader.email,
        "locality_step": reader.locality_step,
        "locality": reader_locality_payload(db, reader),
    }
    if include_ok:
        payload = {"ok": True, **payload}
    return payload


def _attach_session(response: Response, reader: Reader) -> None:
    token = issue_reader_token(reader.id, get_settings().app_secret)
    response.set_cookie(
        READER_COOKIE,
        token,
        max_age=READER_SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, db: DbSession) -> JSONResponse:
    reader = Reader(
        id=uuid4(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        locality_step="pending",
    )
    db.add(reader)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese email ya tiene cuenta") from exc
    response = JSONResponse(_account(db, reader, include_ok=True), status_code=status.HTTP_201_CREATED, headers=_NO_STORE)
    _attach_session(response, reader)
    return response


@router.post("/login")
def login(payload: Credentials, db: DbSession) -> JSONResponse:
    reader = db.scalar(select(Reader).where(Reader.email == payload.email))
    stored = reader.password_hash if reader is not None else None
    matches = password_matches(payload.password, stored)
    if reader is None or not matches:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    response = JSONResponse(_account(db, reader, include_ok=True), headers=_NO_STORE)
    _attach_session(response, reader)
    return response


@router.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True}, headers=_NO_STORE)
    response.delete_cookie(READER_COOKIE, path="/", samesite="lax", httponly=True, secure=False)
    return response


@router.get("/session")
def session(db: DbSession, reader: Annotated[Reader | None, Depends(optional_reader)]) -> JSONResponse:
    if reader is None:
        return JSONResponse({"authenticated": False}, headers=_NO_STORE)
    return JSONResponse(
        {"authenticated": True, **_account(db, reader, include_ok=False)},
        headers=_NO_STORE,
    )


class LocalityChoice(BaseModel):
    locality_id: str = Field(min_length=1, max_length=32)

    @field_validator("locality_id")
    @classmethod
    def clean_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("localidad inválida")
        return cleaned


@router.put("/locality")
def save_locality(
    payload: LocalityChoice,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    row = db.get(GeoLocality, payload.locality_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Localidad no encontrada")
    reader.interest_locality_id = row.id
    reader.locality_step = "done"
    db.flush()
    return JSONResponse(_account(db, reader, include_ok=True), headers=_NO_STORE)


@router.post("/locality/skip")
def skip_locality(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    reader.locality_step = "skipped"
    db.flush()
    return JSONResponse(_account(db, reader, include_ok=True), headers=_NO_STORE)


@router.delete("/locality")
def clear_locality(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    reader.interest_locality_id = None
    if reader.locality_step == "pending":
        reader.locality_step = "skipped"
    db.flush()
    return JSONResponse(_account(db, reader, include_ok=True), headers=_NO_STORE)
