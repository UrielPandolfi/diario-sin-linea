from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, optional_reader
from app.core.config import get_settings
from app.models.reader import Reader
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
    reader = Reader(id=uuid4(), email=payload.email, password_hash=hash_password(payload.password))
    db.add(reader)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese email ya tiene cuenta") from exc
    response = JSONResponse({"ok": True, "email": reader.email}, status_code=status.HTTP_201_CREATED, headers=_NO_STORE)
    _attach_session(response, reader)
    return response


@router.post("/login")
def login(payload: Credentials, db: DbSession) -> JSONResponse:
    reader = db.scalar(select(Reader).where(Reader.email == payload.email))
    stored = reader.password_hash if reader is not None else None
    matches = password_matches(payload.password, stored)
    if reader is None or not matches:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    response = JSONResponse({"ok": True, "email": reader.email}, headers=_NO_STORE)
    _attach_session(response, reader)
    return response


@router.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True}, headers=_NO_STORE)
    response.delete_cookie(READER_COOKIE, path="/", samesite="lax", httponly=True, secure=False)
    return response


@router.get("/session")
def session(reader: Annotated[Reader | None, Depends(optional_reader)]) -> JSONResponse:
    if reader is None:
        return JSONResponse({"authenticated": False}, headers=_NO_STORE)
    return JSONResponse({"authenticated": True, "email": reader.email}, headers=_NO_STORE)
