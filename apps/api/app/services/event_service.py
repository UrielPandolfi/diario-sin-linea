from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import EventSourceRelation, EventUpdateType
from app.models import Event, EventSource, EventUpdate
from app.repositories import EventRepository
from app.schemas import EventCreate


class EventService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = EventRepository(session)

    def create(self, data: EventCreate) -> Event:
        payload = data.model_dump(exclude={"source_item_id"})
        event = Event(**payload)
        self.repo.add(event)
        self.session.flush()

        self.session.add(
            EventUpdate(
                event_id=event.id,
                update_type=EventUpdateType.EVENT_CREATED,
                headline=event.title_internal,
                summary=event.short_summary,
                is_material=True,
            )
        )

        if data.source_item_id is not None:
            self.attach_source(
                event,
                data.source_item_id,
                relation_type=EventSourceRelation.INITIAL,
                is_primary=True,
            )

        self.session.flush()
        return event

    def attach_source(
        self,
        event: Event,
        source_item_id: UUID,
        *,
        relation_type: EventSourceRelation = EventSourceRelation.ADDITIONAL,
        is_primary: bool = False,
    ) -> tuple[EventSource, bool]:
        existing = self.repo.get_link(event.id, source_item_id)
        if existing is not None:
            return existing, False

        link = EventSource(
            event_id=event.id,
            source_item_id=source_item_id,
            relation_type=relation_type,
            is_primary=is_primary,
        )
        self.repo.add_link(link)
        try:
            with self.session.begin_nested():
                self.session.flush()
        except IntegrityError:
            existing = self.repo.get_link(event.id, source_item_id)
            if existing is None:
                raise
            return existing, False
        return link, True
