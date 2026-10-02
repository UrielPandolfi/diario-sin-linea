import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, optional_reader, require_reader
from app.core.config import get_settings
from app.models.geo_locality import GeoLocality
from app.models.reader import Reader
from app.services.geo_localities import reader_locality_payload
from app.core.request_ip import client_ip
from app.domain.enums import CaseReason
from app.services.case_rate_limit import allow_case_submit
from app.services.case_service import CaseService, CaseServiceError, follow_up_url
from app.services.mailer import mail_configured, send_email
from app.services.password_reset import confirm_reset, issue_reset
from app.services.password_reset_limit import allow_password_reset
from app.services.reader_auth import (
    READER_COOKIE,
    READER_SESSION_TTL,
    hash_password,
    issue_reader_token,
    normalize_email,
    password_matches,
)

logger = logging.getLogger(__name__)
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
    settings = get_settings()
    token = issue_reader_token(
        reader.id,
        settings.app_secret,
        generation=int(reader.session_generation or 0),
    )
    response.set_cookie(
        READER_COOKIE,
        token,
        max_age=READER_SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
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
    response.delete_cookie(
        READER_COOKIE,
        path="/",
        samesite="lax",
        httponly=True,
        secure=get_settings().cookie_secure,
    )
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


_RESET_OK = {
    "ok": True,
    "detail": "Si hay una cuenta con ese email, enviamos un enlace para elegir una contraseña nueva.",
}


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        email = normalize_email(value)
        if email is None:
            raise ValueError("email inválido")
        return email


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class DeletionRequest(BaseModel):
    message: str = Field(min_length=20, max_length=4000)


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest, request: Request, db: DbSession) -> JSONResponse:
    settings = get_settings()
    if not allow_password_reset(client_ip(request, settings), payload.email):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")
    if not mail_configured(settings):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="mail_not_configured")
    reader = db.scalar(select(Reader).where(Reader.email == payload.email))
    if reader is None:
        return JSONResponse(_RESET_OK, headers=_NO_STORE)
    token = issue_reset(db, reader)
    link = f"{settings.site_url.rstrip('/')}/cuenta/restablecer?token={token}"
    sent = send_email(
        settings,
        to=reader.email,
        subject="Restablecer contraseña de Sin Línea",
        body=(
            "Recibimos un pedido para elegir una contraseña nueva en Sin Línea.\n\n"
            f"{link}\n\n"
            "El enlace vence en una hora y se puede usar una sola vez. "
            "Si no pediste este cambio, ignorá este mensaje.\n"
        ),
    )
    if not sent:
        logger.error("password reset email was not sent")
        db.rollback()
    return JSONResponse(_RESET_OK, headers=_NO_STORE)


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirm, db: DbSession) -> JSONResponse:
    reader = confirm_reset(db, payload.token.strip(), payload.password)
    if reader is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_token")
    response = JSONResponse({"ok": True}, headers=_NO_STORE)
    _attach_session(response, reader)
    return response


@router.post("/password")
def change_password(
    payload: PasswordChange,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    if not password_matches(payload.current_password, reader.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña actual incorrecta")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Elegí una contraseña distinta")
    reader.password_hash = hash_password(payload.new_password)
    reader.session_generation = int(reader.session_generation or 0) + 1
    db.flush()
    response = JSONResponse({"ok": True}, headers=_NO_STORE)
    _attach_session(response, reader)
    return response


@router.post("/deletion-request", status_code=status.HTTP_201_CREATED)
def request_account_deletion(
    payload: DeletionRequest,
    request: Request,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    settings = get_settings()
    ip = client_ip(request, settings)
    if not allow_case_submit(ip, None):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")
    try:
        row = CaseService(db).create(
            idempotency_key=uuid4(),
            reason=CaseReason.ACCOUNT_DELETION,
            message=payload.message,
            ip=ip,
            email=reader.email,
        )
    except CaseServiceError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    return JSONResponse(
        {"public_code": row.public_code, "follow_up_url": follow_up_url(row.access_token)},
        status_code=status.HTTP_201_CREATED,
        headers=_NO_STORE,
    )
