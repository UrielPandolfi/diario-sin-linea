from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import (
    ClaimImportance,
    ClaimStatus,
    EventSourceRelation,
    EventStatus,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.main import app
from app.models import Claim, ClaimEvidence, EventSource, PipelineRun, SourceItem
from app.providers.base import SearchHit
from app.providers.fakes import FakeSearchProvider, FakeStructuredLLM, RecordingFetcher
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.schemas.verification import (
    CheapClaimEvidenceAssessment,
    CheapEvidenceJudgement,
    EvidenceJudgementType,
    VerificationEvidence,
    VerificationPlan,
    VerificationResult,
    VerificationSubject,
    VerificationTarget,
    TemporalScope,
)
from app.services.claim_service import CLAIM_STAGE
from app.services.event_service import EventService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_policy import canonicalize_claim_type, select_claims
from app.services.verification_service import VERIFICATION_STAGE, VerificationService


def _source(session: Session, **overrides):
    payload = {
        "name": "Fuente",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": "https://www.ejemplo.test/rss.xml",
        "is_monitored": True,
        "is_enabled": True,
        "domain": "ejemplo.test",
    }
    payload.update(overrides)
    return SourceService(session).create(SourceCreate(**payload))


def _item(
    session: Session,
    source_id,
    *,
    url: str,
    title: str,
    body: str,
    content_hash: str,
    published_at: datetime | None = None,
):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
            published_at=published_at,
        )
    ).item


def _event(session: Session, item, **overrides):
    payload = {
        "title_internal": "Operativo en la plaza principal",
        "event_type": "accidente",
        "source_item_id": item.id,
        "started_at": datetime.now(timezone.utc),
        "locality": "Rosario",
        "province": "Santa Fe",
        "short_summary": "Un colectivo chocó en Rosario",
    }
    payload.update(overrides)
    return EventService(session).create(EventCreate(**payload))


def _claim(session: Session, event, *, text: str, claim_type: str, importance: ClaimImportance, status: ClaimStatus, **overrides):
    row = Claim(
        event_id=event.id,
        canonical_text=text,
        claim_type=claim_type,
        importance=importance,
        status=status,
        subject=overrides.get("subject"),
        predicate=overrides.get("predicate"),
        object_text=overrides.get("object_text"),
        normalized_value=overrides.get("normalized_value"),
        unit=overrides.get("unit"),
        occurred_at=overrides.get("occurred_at"),
    )
    session.add(row)
    session.flush()
    return row


def _evidence(session: Session, claim: Claim, item, *, excerpt: str, evidence_type: EvidenceType = EvidenceType.SUPPORTS):
    row = ClaimEvidence(
        claim_id=claim.id,
        source_item_id=item.id,
        evidence_type=evidence_type,
        excerpt=excerpt,
        source_url=item.url,
    )
    session.add(row)
    session.flush()
    return row


def _ns(**overrides):
    payload = {
        "id": uuid4(),
        "status": ClaimStatus.SINGLE_SOURCE,
        "importance": ClaimImportance.LOW,
        "claim_type": "hecho",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _sol(**overrides) -> VerificationResult:
    payload = {
        "status": ClaimStatus.SINGLE_SOURCE,
        "confidence": 0.8,
        "evidence": [],
        "reason": "ok",
        "unresolved": False,
    }
    payload.update(overrides)
    return VerificationResult(**payload)


def _service(
    session: Session,
    llm: FakeStructuredLLM,
    search: FakeSearchProvider,
    fetcher: RecordingFetcher | None = None,
    *,
    planner: FakeStructuredLLM | None = None,
    assessor: FakeStructuredLLM | None = None,
):
    return VerificationService(
        session,
        llm=llm,
        planner_llm=planner,
        assessor_llm=assessor,
        search=search,
        fetcher=fetcher or RecordingFetcher(),
    )


def test_canonicalize_claim_type_aliases() -> None:
    assert canonicalize_claim_type("cita") == "declaracion"
    assert canonicalize_claim_type("estadistica") == "cifra"
    assert canonicalize_claim_type("presupuesto") == "cifra"
    assert canonicalize_claim_type("ley") == "documento"
    assert canonicalize_claim_type("decreto") == "documento"
    assert canonicalize_claim_type("otro") == "hecho"
    assert canonicalize_claim_type("") == "hecho"
    assert canonicalize_claim_type("DECLARACION") == "declaracion"


def test_policy_skips_mundane_fire_and_supported() -> None:
    selected, skipped = select_claims(
        [
            _ns(claim_type="hecho", importance=ClaimImportance.LOW, status=ClaimStatus.SINGLE_SOURCE),
            _ns(claim_type="hecho", importance=ClaimImportance.MEDIUM, status=ClaimStatus.SINGLE_SOURCE),
            _ns(claim_type="estado", importance=ClaimImportance.LOW, status=ClaimStatus.SUPPORTED),
        ],
        flagged_ids=set(),
        limit=5,
    )
    assert selected == []
    assert {row["reason"] for row in skipped} == {"veto"}


def test_policy_selects_declaration_hard_types_and_aliases() -> None:
    cita = _ns(claim_type="cita", importance=ClaimImportance.LOW, status=ClaimStatus.UNCERTAIN)
    cifra = _ns(claim_type="estadistica", importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE)
    ley = _ns(claim_type="ley", importance=ClaimImportance.HIGH, status=ClaimStatus.CONFLICTING)
    high = _ns(claim_type="hecho", importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE)
    selected, _skipped = select_claims([cita, cifra, ley, high], flagged_ids=set(), limit=5)
    kinds = {canonicalize_claim_type(row.claim.claim_type) for row in selected}
    assert kinds == {"declaracion", "cifra", "documento", "hecho"}
    assert all(row.reasons for row in selected)


def test_policy_m5_flag_selects_unless_vetoed() -> None:
    flagged = _ns(claim_type="hecho", importance=ClaimImportance.MEDIUM, status=ClaimStatus.UNCERTAIN)
    vetoed = _ns(claim_type="hecho", importance=ClaimImportance.LOW, status=ClaimStatus.SINGLE_SOURCE)
    selected, skipped = select_claims(
        [flagged, vetoed],
        flagged_ids={flagged.id, vetoed.id},
        limit=5,
    )
    assert [row.claim.id for row in selected] == [flagged.id]
    assert "m5_flag" in selected[0].reasons
    assert any(row["claim_id"] == str(vetoed.id) and row["reason"] == "veto" for row in skipped)


def test_mundane_claim_does_not_call_sol_or_brave(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/fuego", title="Incendio", body="Hubo un incendio", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="Hubo un incendio en la esquina",
        claim_type="hecho",
        importance=ClaimImportance.LOW,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    llm = FakeStructuredLLM()
    search = FakeSearchProvider([SearchHit(title="x", url="https://otro.test/n", snippet="x")])
    result = _service(db_session, llm, search).verify(event.id, trigger="admin")
    assert result["skipped"] is False
    assert result["verified"] == 0
    assert llm.calls == []
    assert search.queries == []


def test_declaration_runs_claim_queries_not_event_research(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/base",
        title="Base",
        body="El ministro habló",
        content_hash="h1",
    )
    event = _event(db_session, item)
    item.raw_text = "<html>RAW_SOURCE_FULL_TEXT_MUST_STAY_OUT</html>"
    db_session.flush()
    claim = _claim(
        db_session,
        event,
        text="El ministro anunció que el decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    cited = "https://oficial.test/discurso"
    ignored = "https://ruido.test/otra"
    page = "<article><p>El ministro anunció que el decreto está vigente en conferencia.</p></article>"
    llm = FakeStructuredLLM(
        {
            "VerificationResult": _sol(
                evidence=[
                    VerificationEvidence(
                        source_ref=1,
                        evidence_type=EvidenceType.SUPPORTS,
                        excerpt="el decreto está vigente",
                        confidence=0.9,
                    )
                ]
            )
        }
    )
    search = FakeSearchProvider(
        [
            SearchHit(title="Discurso", url=cited, snippet="El ministro anunció que el decreto está vigente"),
            SearchHit(title="Ruido", url=ignored, snippet="otra cosa"),
        ]
    )
    fetcher = RecordingFetcher({cited: page, ignored: "<article><p>nota ajena al claim</p></article>"})
    result = _service(db_session, llm, search, fetcher).verify(event.id, trigger="admin")
    assert result["verified"] == 1
    query_text = " ".join(query.text for query in search.queries)
    assert claim.canonical_text in query_text
    assert event.title_internal not in query_text
    prompt = llm.user_prompts[0]
    assert claim.canonical_text in prompt
    assert "El ministro anunció que el decreto está vigente" in prompt
    assert "<html" not in prompt.lower()
    assert "RAW_SOURCE_FULL_TEXT_MUST_STAY_OUT" not in prompt
    urls = {
        link.source_item.url
        for link in db_session.scalars(select(EventSource).where(EventSource.event_id == event.id))
        if link.source_item is not None
    }
    assert cited in urls
    assert ignored not in urls
    extra = db_session.scalars(
        select(EventSource).where(
            EventSource.event_id == event.id,
            EventSource.source_item_id != item.id,
        )
    ).all()
    assert all(link.relation_type == EventSourceRelation.ADDITIONAL for link in extra)


def test_conflicting_unresolved_keeps_status_and_value(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Muertos", content_hash="h1")
    event = _event(db_session, item)
    two = _claim(
        db_session,
        event,
        text="Hay 2 muertos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.CONFLICTING,
        normalized_value="2",
        object_text="2 muertos",
    )
    three = _claim(
        db_session,
        event,
        text="Hay 3 muertos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.CONFLICTING,
        normalized_value="3",
        object_text="3 muertos",
    )
    llm = FakeStructuredLLM(
        {
            "VerificationResult": [
                _sol(status=ClaimStatus.CONFLICTING, unresolved=True, reason="2 vs 3"),
                _sol(status=ClaimStatus.CONFLICTING, unresolved=True, reason="2 vs 3"),
            ]
        }
    )
    search = FakeSearchProvider([])
    _service(db_session, llm, search).verify(event.id, trigger="admin")
    db_session.refresh(two)
    db_session.refresh(three)
    assert two.status == ClaimStatus.CONFLICTING
    assert three.status == ClaimStatus.CONFLICTING
    assert two.normalized_value == "2"
    assert three.normalized_value == "3"
    assert two.canonical_text == "Hay 2 muertos"


def test_secondary_consistent_evidence_can_support_without_primary_heuristic(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="medio-a.test", feed_url="https://medio-a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="medio-b.test", feed_url="https://medio-b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://medio-a.test/nota",
        title="A",
        body="El incendio dejó seis heridos según testigos.",
        content_hash="ha",
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://medio-b.test/nota",
        title="B",
        body="El incendio dejó seis heridos según testigos.",
        content_hash="hb",
    )
    event = _event(db_session, item_a)
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    claim = _claim(
        db_session,
        event,
        text="El incendio dejó seis heridos",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    _evidence(db_session, claim, item_a, excerpt="seis heridos")
    _evidence(db_session, claim, item_b, excerpt="seis heridos")
    llm = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SUPPORTED, reason="dos medios alineados")})
    search = FakeSearchProvider([])
    _service(db_session, llm, search).verify(event.id, trigger="admin")
    db_session.refresh(claim)
    assert claim.status == ClaimStatus.SUPPORTED


def test_document_without_primary_can_stay_uncertain(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Un decreto", content_hash="h1")
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Se publicó el decreto 123",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.UNCERTAIN,
    )
    llm = FakeStructuredLLM(
        {"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True, reason="falta el boletín")}
    )
    search = FakeSearchProvider(
        [SearchHit(title="Nota", url="https://diario.test/eco", snippet="mencionan un decreto")]
    )
    _service(db_session, llm, search).verify(event.id, trigger="admin")
    db_session.refresh(claim)
    assert claim.status == ClaimStatus.UNCERTAIN
    assert claim.canonical_text == "Se publicó el decreto 123"


def test_running_lock_skips_providers(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="El ministro habló",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    db_session.add(
        PipelineRun(event_id=event.id, stage=VERIFICATION_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = FakeStructuredLLM({"VerificationResult": _sol()})
    search = FakeSearchProvider([SearchHit(title="x", url="https://x.test/n", snippet="x")])
    result = _service(db_session, llm, search).verify(event.id, trigger="admin")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []
    assert search.queries == []


def test_second_run_is_idempotent(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Dijo", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="El gobernador dijo que hay acuerdo",
        claim_type="declaracion",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    url = "https://oficial.test/comunicado"
    body = "<article><p>El gobernador dijo que hay acuerdo en conferencia.</p></article>"
    evidence = [
        VerificationEvidence(
            source_ref=1,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="dijo que hay acuerdo",
            confidence=0.8,
        )
    ]
    llm = FakeStructuredLLM({"VerificationResult": _sol(evidence=evidence)})
    search = FakeSearchProvider([SearchHit(title="Comunicado", url=url, snippet="El gobernador dijo que hay acuerdo")])
    fetcher = RecordingFetcher({url: body})
    service = _service(db_session, llm, search, fetcher)
    first = service.verify(event.id, trigger="admin")
    second = service.verify(event.id, trigger="admin")
    assert first["attached"] == 1
    assert second["attached"] == 0
    assert db_session.scalar(select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id)) == 2
    assert db_session.scalar(select(func.count()).select_from(ClaimEvidence)) == 1


def test_event_status_and_prior_relations_stay_intact(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Dijo", content_hash="h1")
    event = _event(db_session, item, status=EventStatus.PUBLISHED)
    initial = db_session.scalars(select(EventSource).where(EventSource.event_id == event.id)).one()
    assert initial.relation_type == EventSourceRelation.INITIAL
    _claim(
        db_session,
        event,
        text="El ministro dio un discurso",
        claim_type="declaracion",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    llm = FakeStructuredLLM({"VerificationResult": _sol()})
    search = FakeSearchProvider([])
    _service(db_session, llm, search).verify(event.id, trigger="admin")
    db_session.refresh(event)
    db_session.refresh(initial)
    assert event.status == EventStatus.PUBLISHED
    assert initial.relation_type == EventSourceRelation.INITIAL


def test_consumes_m5_flag_from_last_success_claims_run(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Un detalle todavía incierto",
        claim_type="hecho",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.UNCERTAIN,
    )
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=CLAIM_STAGE,
            status=PipelineStatus.SUCCESS,
            metadata_json={
                "needs_external_verification": [{"claim_id": str(claim.id), "claim_ref": 1}],
            },
        )
    )
    db_session.flush()
    llm = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True)})
    search = FakeSearchProvider([])
    result = _service(db_session, llm, search).verify(event.id, trigger="admin")
    assert result["consumed_needs_external_verification"] == [{"claim_id": str(claim.id), "claim_ref": 1}]
    assert any("m5_flag" in row["reasons"] for row in result["selected"])
    assert llm.calls == ["VerificationResult"]


def test_resolve_event_claims_enqueues_verify_when_not_skipped(monkeypatch) -> None:
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
        "app.workers.tasks.ClaimService",
        lambda session: SimpleNamespace(
            resolve=lambda *_a, **_k: {"skipped": False, "event_id": "eid", "persisted": 1}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.verify_event_claims.delay", lambda *args: queued.append(args))
    from app.workers.tasks import resolve_event_claims

    resolve_event_claims.run("00000000-0000-0000-0000-000000000001", "research")
    assert queued == [("00000000-0000-0000-0000-000000000001", "research")]


def test_resolve_event_claims_does_not_enqueue_verify_when_no_claims(monkeypatch) -> None:
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
        "app.workers.tasks.ClaimService",
        lambda session: SimpleNamespace(
            resolve=lambda *_a, **_k: {
                "skipped": False,
                "event_id": "eid",
                "persisted": 0,
                "reason": "no_usable_sources",
            }
        ),
    )
    monkeypatch.setattr("app.workers.tasks.verify_event_claims.delay", lambda *args: queued.append(args))
    from app.workers.tasks import resolve_event_claims

    resolve_event_claims.run("00000000-0000-0000-0000-000000000001", "research")
    assert queued == []


def test_resolve_event_claims_does_not_enqueue_verify_when_skipped(monkeypatch) -> None:
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
        "app.workers.tasks.ClaimService",
        lambda session: SimpleNamespace(
            resolve=lambda *_a, **_k: {"skipped": True, "reason": "already_running"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.verify_event_claims.delay", lambda *args: queued.append(args))
    from app.workers.tasks import resolve_event_claims

    resolve_event_claims.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []


def test_admin_verify_accepted(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.verify_event_claims.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200
        response = client.post(f"/api/v1/admin/events/{event.id}/verify")
    assert response.status_code == 202
    assert response.json()["queued"] is True
    assert queued == [(str(event.id), "admin")]


def test_admin_verify_conflict_when_running(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.verify_event_claims.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    db_session.add(
        PipelineRun(event_id=event.id, stage=VERIFICATION_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post(f"/api/v1/admin/events/{event.id}/verify")
    assert response.status_code == 409
    assert queued == []


def test_historical_claim_search_omits_pd_even_if_event_is_today(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Designación", content_hash="h1"
    )
    event = _event(db_session, item, started_at=datetime.now(timezone.utc))
    claim = _claim(
        db_session,
        event,
        text="Natalia Laura Federman fue designada Directora Nacional de Derechos Humanos",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.UNCERTAIN,
        occurred_at=datetime(2011, 6, 9, tzinfo=timezone.utc),
    )
    llm = FakeStructuredLLM(
        {"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True, reason="faltan fuentes")}
    )
    search = FakeSearchProvider([])
    result = _service(db_session, llm, search).verify(event.id, trigger="admin")
    assert result["verified"] == 1
    assert search.queries
    assert all(query.freshness is None for query in search.queries)
    assert result["freshness"][str(claim.id)] is None
    assert result["temporal_scope"][str(claim.id)] == TemporalScope.HISTORICAL.value
    assert any("2011" in query.text for query in search.queries)


def test_official_site_query_falls_back_to_general_search(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Designación", content_hash="h1"
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Se publicó la designación en el Boletín Oficial",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.UNCERTAIN,
        occurred_at=datetime(2011, 6, 9, tzinfo=timezone.utc),
    )
    general_url = "https://diario.test/nota"
    hits_by_query: dict[str, list[SearchHit]] = {}
    search = FakeSearchProvider(hits_by_query)
    llm = FakeStructuredLLM(
        {"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True, reason="sin primaria")}
    )
    from app.services.evidence_source_registry import preferred_domains
    from app.services.verification_plan import build_verification_queries, heuristic_plan

    plan = heuristic_plan(claim)
    domains = preferred_domains(plan.jurisdiction, plan.verification_target.value, plan.subject.value)
    queries = build_verification_queries(claim, plan, domains, limit=3)
    for query in queries:
        if "site:" in query:
            hits_by_query[query] = []
        else:
            hits_by_query[query] = [SearchHit(title="Nota", url=general_url, snippet="mencionan la designación")]
    result = _service(db_session, llm, search).verify(event.id, trigger="admin")
    assert any("site:boletinoficial.gob.ar" in query.text for query in search.queries)
    assert any("site:" not in query.text for query in search.queries)
    assert result["queries"][str(claim.id)]
    assert any("site:" not in query for query in result["queries"][str(claim.id)])


def test_cheap_assessment_can_skip_sol_when_primary_supports(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/base",
        title="Base",
        body="La designación se publicó.",
        content_hash="h1",
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Se designó a la funcionaria en el Ministerio de Seguridad",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    _evidence(db_session, claim, item, excerpt="La designación se publicó")
    official = "https://www.boletinoficial.gob.ar/detalle/x"
    page = "<article><p>Dase por designada en el Ministerio de Seguridad.</p></article>"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=2,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="Dase por designada",
                        reason="el boletín nombra el cargo",
                    )
                ],
                ambiguous=False,
                reason="registro oficial",
            )
        }
    )
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SUPPORTED)})
    search = FakeSearchProvider(
        [SearchHit(title="Decreto", url=official, snippet="Dase por designada en el Ministerio de Seguridad.")]
    )
    result = _service(
        db_session, sol, search, RecordingFetcher({official: page}), assessor=assessor
    ).verify(event.id, trigger="admin")
    assert result["escalated"][str(claim.id)] is False
    assert "VerificationResult" not in sol.calls
    db_session.refresh(claim)
    assert claim.status in {ClaimStatus.SUPPORTED, ClaimStatus.SINGLE_SOURCE}


def test_official_hit_does_not_promote_without_semantic_support(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="El ministro habló", content_hash="h1"
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="El ministro anunció que el decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    official = "https://boletinoficial.gob.ar/otra"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.DOES_NOT_ESTABLISH,
                        excerpt=None,
                        reason="no sostiene el anuncio",
                    )
                ],
                ambiguous=False,
            )
        }
    )
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SUPPORTED)})
    search = FakeSearchProvider(
        [SearchHit(title="Boletín", url=official, snippet="Otra norma distinta")]
    )
    _service(db_session, sol, search, assessor=assessor).verify(event.id, trigger="admin")
    db_session.refresh(claim)
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    assert "VerificationResult" not in sol.calls


def test_primary_found_is_independent_of_semantic_support(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Designación", content_hash="h1"
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Se publicó el decreto de designación",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.UNCERTAIN,
        occurred_at=datetime(2011, 6, 9, tzinfo=timezone.utc),
    )
    official = "https://www.boletinoficial.gob.ar/detalle/otro"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.DOES_NOT_ESTABLISH,
                        excerpt=None,
                        reason="otra norma",
                    )
                ],
                ambiguous=False,
            )
        }
    )
    sol = FakeStructuredLLM(
        {"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True, reason="no sostiene")}
    )
    search = FakeSearchProvider(
        [SearchHit(title="Boletín", url=official, snippet="Otra designación distinta")]
    )
    result = _service(db_session, sol, search, assessor=assessor).verify(event.id, trigger="admin")
    cid = str(claim.id)
    assert result["primary_source_found"][cid] is True
    assert result["primary_source_supports_claim"][cid] is False


def test_sol_cannot_mark_supported_without_required_primary(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="medio-a.test", feed_url="https://medio-a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="medio-b.test", feed_url="https://medio-b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://medio-a.test/nota",
        title="A",
        body="Vital presentó una denuncia penal.",
        content_hash="ha",
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://medio-b.test/nota",
        title="B",
        body="Vital presentó una denuncia penal.",
        content_hash="hb",
    )
    event = _event(db_session, item_a)
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    claim = _claim(
        db_session,
        event,
        text="Víctor Eduardo Vital presentó una denuncia penal contra Natalia Laura Federman",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    _evidence(db_session, claim, item_a, excerpt="presentó una denuncia penal")
    _evidence(db_session, claim, item_b, excerpt="presentó una denuncia penal")
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SUPPORTED, reason="varios medios")})
    search = FakeSearchProvider([])
    _service(db_session, sol, search).verify(event.id, trigger="admin")
    db_session.refresh(claim)
    assert claim.status != ClaimStatus.SUPPORTED
