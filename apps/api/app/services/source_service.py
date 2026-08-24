from sqlalchemy.orm import Session

from app.models import Source
from app.repositories import SourceRepository
from app.schemas import SourceCreate, SourceUpdate


class SourceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = SourceRepository(session)

    def create(self, data: SourceCreate) -> Source:
        source = Source(**data.model_dump())
        self.repo.add(source)
        self.session.flush()
        return source

    def update(self, source: Source, data: SourceUpdate) -> Source:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(source, field, value)
        self.session.flush()
        return source

    def get(self, source_id) -> Source | None:
        return self.repo.get(source_id)

    def list_all(self) -> list[Source]:
        return self.repo.list_all()

    def list_pollable(self) -> list[Source]:
        return self.repo.list_pollable()
