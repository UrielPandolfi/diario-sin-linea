from sqlalchemy.orm import Session

from app.core.slugs import slugify, unique_suffix
from app.models import Article, ArticleVersion
from app.repositories import ArticleRepository
from app.schemas import ArticleContentUpdate, ArticleCreate


class ArticleService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ArticleRepository(session)

    def create_draft(self, data: ArticleCreate) -> tuple[Article, bool]:
        existing = self.repo.get_by_event_id(data.event_id)
        if existing is not None:
            return existing, False

        slug = self._allocate_slug(data.slug or slugify(data.headline))
        article = Article(
            event_id=data.event_id,
            slug=slug,
            headline=data.headline,
            summary=data.summary,
            body=data.body,
            body_blocks=data.body_blocks,
            status=data.status,
            hero_image_url=data.hero_image_url,
            current_version=1,
        )
        self.repo.add(article)
        self.session.flush()
        self._add_version(article, change_reason="initial")
        self.session.flush()
        return article, True

    def update_content(self, article: Article, data: ArticleContentUpdate) -> Article:
        article.headline = data.headline
        article.summary = data.summary
        article.body = data.body
        article.body_blocks = data.body_blocks
        if data.hero_image_url is not None:
            article.hero_image_url = data.hero_image_url
        article.current_version += 1
        self._add_version(article, change_reason=data.change_reason)
        self.session.flush()
        return article

    def _add_version(self, article: Article, *, change_reason: str) -> ArticleVersion:
        version = ArticleVersion(
            article_id=article.id,
            version_number=article.current_version,
            headline=article.headline,
            summary=article.summary,
            body=article.body,
            body_blocks=article.body_blocks,
            change_reason=change_reason,
        )
        self.session.add(version)
        return version

    def _allocate_slug(self, base: str) -> str:
        candidate = base
        while self.repo.get_by_slug(candidate) is not None:
            candidate = f"{base}-{unique_suffix()}"
        return candidate
