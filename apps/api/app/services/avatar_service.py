"""Random illustrated avatar after email verification. Failure never unverifies the reader."""

from __future__ import annotations

import hashlib
import logging
import secrets
from io import BytesIO
from uuid import UUID

from PIL import Image
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.reader import Reader
from app.models.reader_avatar import ReaderAvatar
from app.providers.replicate_image import ReplicateImageProvider
from app.services.hero_image_error import HeroImageError

logger = logging.getLogger(__name__)

_PENDING_KEY = "sl_avatar_reader_ids"
_HOOK_KEY = "sl_avatar_after_commit"
_SUBJECTS = (
    "a fox in a coat",
    "a paper bird",
    "a moon rabbit",
    "a lighthouse keeper",
    "a geometric face",
    "a cat with a scarf",
    "a botanist",
    "a sailor",
    "an owl with round glasses",
    "a desert cactus spirit",
)
_STYLES = (
    "flat editorial illustration",
    "ink and wash",
    "risograph print",
    "soft gouache",
)


def avatar_public_path(reader_id: UUID, fingerprint: str) -> str:
    return f"/api/v1/media/avatars/{reader_id}.webp?v={fingerprint[:12]}"


def reader_avatar_url(session: Session, reader_id: UUID) -> str | None:
    row = session.get(ReaderAvatar, reader_id)
    if row is None:
        return None
    return avatar_public_path(reader_id, row.fingerprint)


def enqueue_reader_avatar(reader_id: UUID) -> None:
    if get_settings().usage_environment == "test":
        return
    from app.workers.tasks import generate_reader_avatar

    generate_reader_avatar.delay(str(reader_id))


def release_avatar_enqueue(reader_id: UUID) -> None:
    session = SessionLocal()
    try:
        reader = session.get(Reader, reader_id)
        if reader is not None and session.get(ReaderAvatar, reader_id) is None:
            reader.avatar_enqueued_at = None
            session.commit()
    except Exception:
        session.rollback()
        logger.exception("reader_id=%s stage=avatar clear_flag status=error", reader_id)
    finally:
        session.close()


def request_reader_avatar(session: Session, reader: Reader) -> None:
    """Marca el pedido y lo encola después del commit. No llama a Replicate acá."""
    if not get_settings().avatar_image_enabled:
        return
    if reader.email_verified_at is None or reader.avatar_enqueued_at is not None:
        return
    if session.get(ReaderAvatar, reader.id) is not None:
        return
    reader.avatar_enqueued_at = utc_now()
    pending: set[UUID] = session.info.setdefault(_PENDING_KEY, set())
    pending.add(reader.id)
    if session.info.get(_HOOK_KEY):
        return
    session.info[_HOOK_KEY] = True

    def _run(sess: Session) -> None:
        ids = list(sess.info.pop(_PENDING_KEY, set()))
        sess.info.pop(_HOOK_KEY, None)
        for reader_id in ids:
            try:
                enqueue_reader_avatar(reader_id)
            except Exception:
                logger.exception("reader_id=%s stage=avatar enqueue status=error", reader_id)
                release_avatar_enqueue(reader_id)

    event.listen(session, "after_commit", _run, once=True)


def _prompt() -> str:
    subject = secrets.choice(_SUBJECTS)
    style = secrets.choice(_STYLES)
    return (
        f"Square avatar, illustrated portrait of {subject}, {style}, "
        "simple background, no text, not a photograph of a real person"
    )


def _to_webp(data: bytes, size: int) -> tuple[bytes, int, int]:
    with Image.open(BytesIO(data)) as image:
        converted = image.convert("RGBA")
        converted.thumbnail((size, size))
        out = BytesIO()
        converted.save(out, format="WEBP", quality=80)
        return out.getvalue(), int(converted.width), int(converted.height)


class AvatarService:
    def __init__(self, session: Session, images: ReplicateImageProvider | None = None) -> None:
        self.session = session
        self.images = images or ReplicateImageProvider()

    def generate(self, reader_id: UUID) -> None:
        settings = get_settings()
        if not settings.avatar_image_enabled:
            return
        reader = self.session.get(Reader, reader_id)
        if reader is None or reader.email_verified_at is None:
            return
        if self.session.get(ReaderAvatar, reader_id) is not None:
            return
        raw = self.images.generate_avatar(_prompt(), seed=secrets.randbelow(2**31))
        data, width, height = _to_webp(raw, int(settings.avatar_image_size))
        if not data:
            raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
        fingerprint = hashlib.sha256(data).hexdigest()
        self.session.add(
            ReaderAvatar(
                reader_id=reader_id,
                image_bytes=data,
                fingerprint=fingerprint,
                content_type="image/webp",
                width=width,
                height=height,
                updated_at=utc_now(),
            )
        )
        self.session.flush()
