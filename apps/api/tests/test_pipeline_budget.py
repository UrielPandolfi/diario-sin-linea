from types import SimpleNamespace
from uuid import uuid4

from app.core.config import get_settings
from app.services.pipeline_budget import (
    allow_fill_enqueue,
    allow_new_event_pipeline,
    claim_detection_item,
    release_new_event_pipeline,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    def set(self, key: str, value: object) -> None:
        self.store[key] = int(value)

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def sadd(self, key: str, *values: str) -> int:
        bucket = self.sets.setdefault(key, set())
        added = 0
        for value in values:
            if value not in bucket:
                bucket.add(value)
                added += 1
        return added

    def close(self) -> None:
        return None


def test_allow_unlimited_when_max_zero(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 0)
    assert allow_new_event_pipeline(None) is True
    assert allow_new_event_pipeline("poll-1") is True


def test_deny_without_poll_id_when_max_positive(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 3)
    assert allow_new_event_pipeline(None) is False
    assert allow_new_event_pipeline("") is False


def test_allow_up_to_max_then_deny(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 2)
    fake = _FakeRedis()
    monkeypatch.setattr("app.services.pipeline_budget.redis.from_url", lambda *_a, **_k: fake)
    poll_id = str(uuid4())
    assert allow_new_event_pipeline(poll_id) is True
    assert allow_new_event_pipeline(poll_id) is True
    assert allow_new_event_pipeline(poll_id) is False
    assert list(fake.ttls.values()) == [60 * 60 * 24]
    assert all(value == 2 for value in fake.store.values())


def test_release_slot_allows_another(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 1)
    fake = _FakeRedis()
    monkeypatch.setattr("app.services.pipeline_budget.redis.from_url", lambda *_a, **_k: fake)
    poll_id = str(uuid4())
    assert allow_new_event_pipeline(poll_id) is True
    assert allow_new_event_pipeline(poll_id) is False
    release_new_event_pipeline(poll_id)
    assert allow_new_event_pipeline(poll_id) is True


def test_allow_fill_enqueue_caps(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 1)
    fake = _FakeRedis()
    monkeypatch.setattr("app.services.pipeline_budget.redis.from_url", lambda *_a, **_k: fake)
    poll_id = str(uuid4())
    allowed = [allow_fill_enqueue(poll_id) for _ in range(6)]
    assert allowed == [True, True, True, True, True, False]


def test_claim_detection_item_once(monkeypatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr("app.services.pipeline_budget.redis.from_url", lambda *_a, **_k: fake)
    poll_id = str(uuid4())
    assert claim_detection_item(poll_id, "item-a") is True
    assert claim_detection_item(poll_id, "item-a") is False
    assert claim_detection_item(poll_id, "item-b") is True


def test_redis_failure_denies(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 3)

    class Boom:
        def incr(self, key: str) -> int:
            raise RuntimeError("down")

        def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.pipeline_budget.redis.from_url", lambda *_a, **_k: Boom())
    assert allow_new_event_pipeline("poll-x") is False


def test_detect_event_respects_budget(monkeypatch) -> None:
    queued: list[tuple] = []
    detect_calls: list[str] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.workers.tasks.DetectionService",
        lambda session: detect_calls.append("init")
        or SimpleNamespace(
            detect=lambda *_a, **_k: detect_calls.append("detect") or {"created": True, "event_id": "eid"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: False)
    from app.workers.tasks import detect_event

    result = detect_event.run("00000000-0000-0000-0000-000000000001", "poll-1")
    assert detect_calls == []
    assert queued == []
    assert result["detection_skipped"] is True
    assert result["pipeline_skipped"] is True
    assert result["reason"] == "max_new_events_per_poll"
    assert result["created"] is False


def test_detect_event_enqueues_when_budget_allows(monkeypatch) -> None:
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.workers.tasks.DetectionService",
        lambda session: SimpleNamespace(detect=lambda *_a, **_k: {"created": True, "event_id": "eid"}),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: True)
    from app.workers.tasks import detect_event

    result = detect_event.run("00000000-0000-0000-0000-000000000001", "poll-1")
    assert queued == [("eid", "new_event")]
    assert result.get("pipeline_skipped") is not True


def test_detect_event_fill_quota_replaces_non_created(monkeypatch) -> None:
    item_id = "00000000-0000-0000-0000-000000000001"
    released: list[str | None] = []
    filled: list[tuple[str | None, str]] = []
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.workers.tasks.DetectionService",
        lambda session: SimpleNamespace(
            detect=lambda *_a, **_k: {"created": False, "event_id": "eid", "reason": "level1_url"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: True)
    monkeypatch.setattr(
        "app.workers.tasks.release_new_event_pipeline",
        lambda poll_id: released.append(poll_id),
    )
    monkeypatch.setattr(
        "app.workers.tasks._enqueue_next_for_quota",
        lambda poll_id, exclude: filled.append((poll_id, exclude)),
    )
    from app.workers.tasks import detect_event

    detect_event.run(item_id, "poll-fill", True)
    assert queued == []
    assert released == ["poll-fill"]
    assert filled == [("poll-fill", item_id)]


def test_detect_event_does_not_fill_quota_on_poll(monkeypatch) -> None:
    filled: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.workers.tasks.DetectionService",
        lambda session: SimpleNamespace(detect=lambda *_a, **_k: {"created": False, "event_id": "eid"}),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *_a: None)
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: True)
    monkeypatch.setattr(
        "app.workers.tasks._enqueue_next_for_quota",
        lambda poll_id, exclude: filled.append((poll_id, exclude)),
    )
    from app.workers.tasks import detect_event

    detect_event.run("00000000-0000-0000-0000-000000000001", "poll-1")
    assert filled == []


def test_enqueue_next_for_quota_skips_current_item(monkeypatch) -> None:
    first = uuid4()
    second = uuid4()
    queued: list[tuple] = []

    class Sess:
        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.repositories.SourceItemRepository",
        lambda session: SimpleNamespace(
            list_retryable=lambda limit: [
                SimpleNamespace(id=first),
                SimpleNamespace(id=second),
            ]
        ),
    )
    monkeypatch.setattr("app.workers.tasks.allow_fill_enqueue", lambda poll_id: True)
    monkeypatch.setattr("app.workers.tasks.claim_detection_item", lambda poll_id, item_id: True)
    monkeypatch.setattr(
        "app.workers.tasks._enqueue_detection",
        lambda item_id, poll_id, fill_quota=False: queued.append((item_id, poll_id, fill_quota)),
    )
    from app.workers.tasks import _enqueue_next_for_quota

    _enqueue_next_for_quota("poll-fill", str(first))
    assert queued == [(second, "poll-fill", True)]
