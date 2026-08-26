from types import SimpleNamespace
from uuid import uuid4

from app.core.config import get_settings
from app.services.pipeline_budget import allow_new_event_pipeline


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

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
            detect=lambda *_a, **_k: {"created": True, "event_id": "eid"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: False)
    from app.workers.tasks import detect_event

    result = detect_event.run("00000000-0000-0000-0000-000000000001", "poll-1")
    assert queued == []
    assert result["pipeline_skipped"] is True
    assert result["reason"] == "max_new_events_per_poll"


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
        lambda session: SimpleNamespace(
            detect=lambda *_a, **_k: {"created": True, "event_id": "eid"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: True)
    from app.workers.tasks import detect_event

    result = detect_event.run("00000000-0000-0000-0000-000000000001", "poll-1")
    assert queued == [("eid", "new_event")]
    assert result.get("pipeline_skipped") is not True
