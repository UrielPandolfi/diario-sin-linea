from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.domain.enums import PipelineStatus, SourceItemStatus
from app.services.publication_outcome import (
    CODE_ALREADY_LINKED,
    CODE_DETECTION_FAILED,
    CODE_EMBEDDING_HIGH,
    CODE_LEVEL1_URL,
    CODE_MAX_NEW_EVENTS,
    CODE_PENDING_DETECTION,
    CODE_PENDING_QUOTA,
    CODE_PROVIDER_NOT_CONFIGURED,
    CODE_SPORTS_ONLY,
    CODE_TERRA_NEW,
    CODE_UNRECORDED,
    OUTCOME_CREATED,
    OUTCOME_DISCARDED,
    OUTCOME_ERROR,
    OUTCOME_LINKED,
    OUTCOME_PENDING,
    OUTCOME_STAGE_SKIPPED,
    OUTCOME_UNRECORDED,
    current_item_outcome,
    normalize_detection_code,
    outcome_from_detection_run,
)


def _run(**overrides):
    payload = {
        "id": uuid4(),
        "stage": "event_detection",
        "status": PipelineStatus.SUCCESS,
        "attempt": 1,
        "started_at": datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 9, 8, 12, 1, tzinfo=timezone.utc),
        "error_message": None,
        "event_id": None,
        "metadata_json": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _item(status=SourceItemStatus.PENDING, **meta):
    return SimpleNamespace(
        id=uuid4(),
        processing_status=status,
        metadata_json=meta or {},
    )


def test_normalize_embedding_score_prefix() -> None:
    assert normalize_detection_code("embedding_high:0.912") == CODE_EMBEDDING_HIGH
    assert normalize_detection_code("embedding_low:0.40") == "EMBEDDING_LOW"


def test_filtered_sports_is_discarded() -> None:
    run = _run(metadata_json={"filtered": True, "filter_reason": "SPORTS_ONLY"})
    result = outcome_from_detection_run(run)
    assert result.outcome == OUTCOME_DISCARDED
    assert result.code == CODE_SPORTS_ONLY


def test_level1_url_is_linked_not_discarded() -> None:
    event_id = uuid4()
    run = _run(event_id=event_id, metadata_json={"created": False, "reason": "level1_url"})
    result = outcome_from_detection_run(run, linked_event_ids=[str(event_id)])
    assert result.outcome == OUTCOME_LINKED
    assert result.code == CODE_LEVEL1_URL
    assert str(event_id) in result.event_ids


def test_terra_new_is_created() -> None:
    run = _run(metadata_json={"created": True, "reason": "terra_new"})
    result = outcome_from_detection_run(run)
    assert result.outcome == OUTCOME_CREATED
    assert result.code == CODE_TERRA_NEW


def test_quota_skip_is_stage_skipped_for_the_run() -> None:
    run = _run(metadata_json={"reason": "max_new_events_per_poll", "pipeline_skipped": True})
    result = outcome_from_detection_run(run)
    assert result.outcome == OUTCOME_STAGE_SKIPPED
    assert result.code == CODE_MAX_NEW_EVENTS


def test_failed_provider_error() -> None:
    run = _run(
        status=PipelineStatus.FAILED,
        error_message="Falta API key para el proveedor openai",
        metadata_json={},
    )
    result = outcome_from_detection_run(run)
    assert result.outcome == OUTCOME_ERROR
    assert result.code == CODE_PROVIDER_NOT_CONFIGURED


def test_failed_generic_detection() -> None:
    run = _run(status=PipelineStatus.FAILED, error_message="boom", metadata_json={})
    result = outcome_from_detection_run(run)
    assert result.code == CODE_DETECTION_FAILED


def test_missing_metadata_is_unrecorded() -> None:
    run = _run(metadata_json={})
    result = outcome_from_detection_run(run)
    assert result.outcome == OUTCOME_UNRECORDED
    assert result.code == CODE_UNRECORDED


def test_current_pending_without_run() -> None:
    item = _item()
    result = current_item_outcome(item, latest_run=None, linked_event_ids=[])
    assert result.outcome == OUTCOME_PENDING
    assert result.code == CODE_PENDING_DETECTION


def test_research_attached_pending_is_linked() -> None:
    item = _item(SourceItemStatus.PENDING)
    event_id = str(uuid4())
    result = current_item_outcome(item, latest_run=None, linked_event_ids=[event_id])
    assert result.outcome == OUTCOME_LINKED
    assert result.code == CODE_ALREADY_LINKED
    assert result.event_ids == [event_id]


def test_current_quota_skip_stays_pending_quota() -> None:
    item = _item(SourceItemStatus.PENDING)
    run = _run(metadata_json={"reason": "max_new_events_per_poll", "pipeline_skipped": True})
    result = current_item_outcome(item, latest_run=run, linked_event_ids=[])
    assert result.outcome == OUTCOME_PENDING
    assert result.code == CODE_PENDING_QUOTA


def test_skipped_without_reason_is_unrecorded() -> None:
    item = _item(SourceItemStatus.SKIPPED)
    result = current_item_outcome(item, latest_run=None, linked_event_ids=[])
    assert result.outcome == OUTCOME_UNRECORDED
    assert result.code == CODE_UNRECORDED


def test_period_counts_each_run_not_only_latest() -> None:
    item_id = uuid4()
    first = _run(metadata_json={"filtered": True, "filter_reason": "SPORTS_ONLY"})
    second = _run(metadata_json={"created": False, "reason": "level1_url"})
    outcomes = [
        outcome_from_detection_run(first),
        outcome_from_detection_run(second),
    ]
    assert [row.outcome for row in outcomes] == [OUTCOME_DISCARDED, OUTCOME_LINKED]
    unique_items = {item_id}
    assert len(outcomes) == 2
    assert len(unique_items) == 1
