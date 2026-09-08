from __future__ import annotations

import hashlib
import re
import secrets
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import CaseActionType, CaseActor, CaseOutcome, CaseReason, CaseStatus, CorrectionKind
from app.models import ArticleVersion, ReaderCase, ReaderCaseAction
from app.repositories import ArticleRepository, ReaderCaseRepository

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_PUBLIC_OUTCOMES_NEED_CORRECTION = {
    CaseOutcome.CORRECTED,
    CaseOutcome.UPDATED,
    CaseOutcome.RESPONSE_INCORPORATED,
}
_OUTCOMES_WITHOUT_CORRECTION = {CaseOutcome.NO_CHANGE, CaseOutcome.INQUIRY_ANSWERED}


class CaseServiceError(ValueError):
    def __init__(self, code: str, http_status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _hash_ip(ip: str) -> str:
    secret = get_settings().app_secret
    return hashlib.sha256(f"{ip}:{secret}".encode()).hexdigest()[:32]


def _public_code() -> str:
    return "SL-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _validate_link(url: str | None) -> str | None:
    if url is None:
        return None
    text = url.strip()
    if not text:
        return None
    if len(text) > 2048:
        raise CaseServiceError("link_too_long")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CaseServiceError("invalid_link")
    return text


def _validate_email(email: str | None) -> str | None:
    if email is None:
        return None
    text = email.strip()
    if not text:
        return None
    if len(text) > 254 or not _EMAIL.match(text):
        raise CaseServiceError("invalid_email")
    return text


class CaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.cases = ReaderCaseRepository(session)
        self.articles = ArticleRepository(session)

    def create(
        self,
        *,
        idempotency_key: UUID,
        reason: CaseReason,
        message: str,
        ip: str,
        article_id: UUID | None = None,
        article_slug: str | None = None,
        reported_version_number: int | None = None,
        link_url: str | None = None,
        email: str | None = None,
    ) -> ReaderCase:
        existing = self.cases.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        text = (message or "").strip()
        if len(text) < 20 or len(text) > 4000:
            raise CaseServiceError("invalid_message")

        article = None
        version: ArticleVersion | None = None
        if article_id is not None or (article_slug or "").strip():
            if article_id is not None:
                article = self.articles.get(article_id)
            else:
                article = self.articles.get_by_slug((article_slug or "").strip())
            if article is None:
                raise CaseServiceError("article_not_found", 404)
            if reported_version_number is None:
                raise CaseServiceError("version_required")
            version = self.articles.get_version(article.id, reported_version_number)
            if version is None or version.article_id != article.id:
                raise CaseServiceError("invalid_version")
            if version.published_at is None:
                raise CaseServiceError("version_not_published")
        elif reported_version_number is not None:
            raise CaseServiceError("article_required")

        row = ReaderCase(
            public_code=_public_code(),
            access_token=secrets.token_urlsafe(32),
            idempotency_key=idempotency_key,
            article_id=article.id if article is not None else None,
            reported_version_number=version.version_number if version is not None else None,
            reported_article_version_id=version.id if version is not None else None,
            reason=reason,
            message=text,
            link_url=_validate_link(link_url),
            email=_validate_email(email),
            status=CaseStatus.RECEIVED,
            ip_hash=_hash_ip(ip),
        )
        try:
            with self.session.begin_nested():
                self.cases.add(row)
                self.session.flush()
        except IntegrityError:
            existing = self.cases.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
            row.public_code = _public_code()
            row.access_token = secrets.token_urlsafe(32)
            self.cases.add(row)
            self.session.flush()

        self.cases.add_action(
            ReaderCaseAction(
                reader_case_id=row.id,
                action_type=CaseActionType.CREATED,
                actor=CaseActor.READER,
                to_status=CaseStatus.RECEIVED.value,
            )
        )
        self.session.flush()
        return row

    def get_by_token(self, token: str) -> ReaderCase | None:
        if not token or len(token) < 20:
            return None
        return self.cases.get_by_token(token)

    def get(self, case_id: UUID) -> ReaderCase | None:
        return self.cases.get(case_id)

    def list_filtered(self, **kwargs) -> list[ReaderCase]:
        return self.cases.list_filtered(**kwargs)

    def load_detail(self, case_id: UUID) -> ReaderCase | None:
        stmt = (
            select(ReaderCase)
            .options(
                selectinload(ReaderCase.actions),
                selectinload(ReaderCase.reported_version),
                selectinload(ReaderCase.article),
                selectinload(ReaderCase.linked_correction),
            )
            .where(ReaderCase.id == case_id)
        )
        return self.session.scalars(stmt).first()

    def mark_reviewing(self, case_id: UUID) -> ReaderCase:
        row = self._require(case_id)
        if row.status == CaseStatus.RESOLVED:
            raise CaseServiceError("already_resolved")
        if row.status == CaseStatus.REVIEWING:
            return row
        previous = row.status.value
        row.status = CaseStatus.REVIEWING
        row.reviewing_at = utc_now()
        self.cases.add_action(
            ReaderCaseAction(
                reader_case_id=row.id,
                action_type=CaseActionType.STATUS_CHANGED,
                actor=CaseActor.ADMIN,
                from_status=previous,
                to_status=CaseStatus.REVIEWING.value,
            )
        )
        self.session.flush()
        return row

    def add_note(self, case_id: UUID, note: str) -> ReaderCase:
        row = self._require(case_id)
        text = (note or "").strip()
        if not text or len(text) > 4000:
            raise CaseServiceError("invalid_note")
        self.cases.add_action(
            ReaderCaseAction(
                reader_case_id=row.id,
                action_type=CaseActionType.NOTE_ADDED,
                actor=CaseActor.ADMIN,
                internal_note=text,
            )
        )
        self.session.flush()
        return row

    def resolve(
        self,
        case_id: UUID,
        *,
        outcome: CaseOutcome,
        public_resolution: str,
        linked_correction_id: UUID | None = None,
    ) -> ReaderCase:
        row = self._require(case_id)
        if row.status == CaseStatus.RESOLVED:
            raise CaseServiceError("already_resolved")
        explanation = (public_resolution or "").strip()
        if len(explanation) < 20 or len(explanation) > 4000:
            raise CaseServiceError("invalid_resolution")

        if outcome in _OUTCOMES_WITHOUT_CORRECTION:
            if linked_correction_id is not None:
                raise CaseServiceError("correction_not_allowed")
        elif outcome in _PUBLIC_OUTCOMES_NEED_CORRECTION:
            if linked_correction_id is None:
                raise CaseServiceError("correction_required")
            if row.article_id is None:
                raise CaseServiceError("correction_not_allowed")
            correction = self.articles.get_correction(linked_correction_id)
            if correction is None or correction.article_id != row.article_id:
                raise CaseServiceError("correction_mismatch")
            expected_kind = (
                CorrectionKind.CORRECTION if outcome == CaseOutcome.CORRECTED else CorrectionKind.UPDATE
            )
            if correction.kind != expected_kind:
                raise CaseServiceError("correction_kind_mismatch")
            row.linked_correction_id = correction.id
        else:
            raise CaseServiceError("invalid_outcome")

        previous = row.status.value
        row.status = CaseStatus.RESOLVED
        row.outcome = outcome
        row.public_resolution = explanation
        row.resolved_at = utc_now()
        self.cases.add_action(
            ReaderCaseAction(
                reader_case_id=row.id,
                action_type=CaseActionType.RESOLVED,
                actor=CaseActor.ADMIN,
                from_status=previous,
                to_status=CaseStatus.RESOLVED.value,
                internal_note=None,
            )
        )
        if row.linked_correction_id is not None:
            self.cases.add_action(
                ReaderCaseAction(
                    reader_case_id=row.id,
                    action_type=CaseActionType.CORRECTION_LINKED,
                    actor=CaseActor.ADMIN,
                )
            )
        self.session.flush()
        return row

    def _require(self, case_id: UUID) -> ReaderCase:
        row = self.cases.get(case_id)
        if row is None:
            raise CaseServiceError("case_not_found", 404)
        return row


def follow_up_url(token: str) -> str:
    return f"/seguimiento/{token}"


def public_case_out(row: ReaderCase) -> dict:
    article = row.article
    return {
        "public_code": row.public_code,
        "status": row.status.value,
        "outcome": row.outcome.value if row.outcome is not None else None,
        "public_resolution": row.public_resolution,
        "reason": row.reason.value,
        "message": row.message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "reviewing_at": row.reviewing_at.isoformat() if row.reviewing_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "article": (
            {"slug": article.slug, "headline": article.headline}
            if article is not None
            else None
        ),
    }
