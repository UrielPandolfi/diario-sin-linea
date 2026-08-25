from collections.abc import Sequence
from uuid import UUID

from app.repositories import PipelineRunRepository

WRITING_STAGE = "writing"
AUDITING_STAGE = "auditing"
PUBLISHING_STAGE = "publishing"
WRITE_AUDIT_PUBLISH_STAGES: tuple[str, ...] = (WRITING_STAGE, AUDITING_STAGE, PUBLISHING_STAGE)


def is_write_audit_publish_busy(pipeline: PipelineRunRepository, event_id: UUID) -> bool:
    return any(pipeline.get_running(event_id, stage) is not None for stage in WRITE_AUDIT_PUBLISH_STAGES)
