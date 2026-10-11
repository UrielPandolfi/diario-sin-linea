"""Public comments on a published article. One reply level. Anonymous hides the author."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.article_comment import ArticleComment
from app.models.reader import Reader
from app.models.reader_avatar import ReaderAvatar
from app.services.avatar_service import avatar_public_path
from app.services.feed_ranking import FeedRankingService

COMMENT_MAX = 1000


class CommentError(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def clean_comment_body(value: str) -> str:
    text = value.replace("\x00", "").strip()
    if not text or len(text) > COMMENT_MAX:
        raise CommentError("comment_invalid", 422)
    return text


def _public_article(session: Session, key: str) -> Article | None:
    payload = FeedRankingService(session).get_article(key)
    if payload is None:
        return None
    return session.get(Article, UUID(str(payload["article_id"])))


def _author(reader: Reader | None, avatar: ReaderAvatar | None, *, anonymous: bool) -> dict | None:
    if anonymous or reader is None or not reader.username:
        return None
    avatar_url = avatar_public_path(reader.id, avatar.fingerprint) if avatar is not None else None
    return {"username": reader.username, "avatar_url": avatar_url}


def _public(row: ArticleComment, reader: Reader | None, avatar: ReaderAvatar | None) -> dict:
    anonymous = bool(row.anonymous)
    return {
        "id": str(row.id),
        "body": row.body,
        "created_at": row.created_at.isoformat(),
        "anonymous": anonymous,
        "author": None if anonymous else _author(reader, avatar, anonymous=False),
        "replies": [],
    }


class CommentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_public(self, key: str) -> list[dict] | None:
        article = _public_article(self.session, key)
        if article is None:
            return None
        rows = list(
            self.session.scalars(
                select(ArticleComment)
                .where(ArticleComment.article_id == article.id)
                .order_by(ArticleComment.created_at, ArticleComment.id)
            )
        )
        readers, avatars = self._identities(rows)
        by_id = {row.id: _public(row, readers.get(row.reader_id), avatars.get(row.reader_id)) for row in rows}
        roots: list[dict] = []
        for row in rows:
            item = by_id[row.id]
            if row.parent_id is None or row.parent_id not in by_id:
                roots.append(item)
                continue
            parent = by_id[row.parent_id]
            if parent.get("replies") is None:
                continue
            parent["replies"].append({key: value for key, value in item.items() if key != "replies"})
        return roots

    def create(
        self,
        *,
        key: str,
        reader: Reader,
        body: str,
        anonymous: bool,
        parent_id: UUID | None,
    ) -> dict:
        article = _public_article(self.session, key)
        if article is None:
            raise CommentError("article_not_found", 404)
        if reader.email_verified_at is None:
            raise CommentError("email_not_verified", 403)
        if not reader.username:
            raise CommentError("username_required", 403)
        text = clean_comment_body(body)
        if parent_id is not None:
            parent = self.session.get(ArticleComment, parent_id)
            if parent is None or parent.article_id != article.id:
                raise CommentError("parent_not_found", 404)
            if parent.parent_id is not None:
                raise CommentError("reply_not_root", 400)
        row = ArticleComment(
            article_id=article.id,
            reader_id=reader.id,
            parent_id=parent_id,
            body=text,
            anonymous=anonymous,
        )
        self.session.add(row)
        self.session.flush()
        avatar = None if anonymous else self.session.get(ReaderAvatar, reader.id)
        item = _public(row, reader, avatar)
        if parent_id is not None:
            item.pop("replies", None)
        return item

    def _identities(
        self, rows: list[ArticleComment]
    ) -> tuple[dict[UUID, Reader], dict[UUID, ReaderAvatar]]:
        visible = {row.reader_id for row in rows if not row.anonymous}
        if not visible:
            return {}, {}
        readers = {
            reader.id: reader
            for reader in self.session.scalars(select(Reader).where(Reader.id.in_(visible)))
        }
        avatars = {
            avatar.reader_id: avatar
            for avatar in self.session.scalars(select(ReaderAvatar).where(ReaderAvatar.reader_id.in_(visible)))
        }
        return readers, avatars
