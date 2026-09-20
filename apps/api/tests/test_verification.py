from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from tests.origin import ADMIN_ORIGIN
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
from app.models import Claim, ClaimEvidence, Event, EventSource, PipelineRun, SourceItem
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
from app.services.feed_ranking import source_payloads
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
    vetoed = _ns(claim_type="hecho", importance=ClaimImportance.LOW, status=ClaimStatus.OUTDATED)
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
    claim = _claim(
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
    cid = str(claim.id)
    decision = result["decision_by_claim_id"][cid]
    assert decision["evaluation_state"] == "skipped"
    assert decision["llm_reason"] == "veto"
    assert claim.status == ClaimStatus.SINGLE_SOURCE


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


def test_off_topic_search_hits_stay_candidates_not_event_sources(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://prensa.rionorte.test/anuncio",
        title="Anuncio",
        body="Pérez afirmó que el costo será de 40.000 millones.",
        content_hash="h1",
    )
    event = _event(db_session, item, title_internal="Pérez anuncia baja impositiva", event_type="anuncio")
    claim = _claim(
        db_session,
        event,
        text="Pérez afirmó que el costo será de 40.000 millones",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        normalized_value="40000",
        unit="pesos",
    )
    useful = "https://hacienda.rionorte.test/proyecto"
    mexico = "https://mexico.test/subsidio-47300"
    rionegro = "https://rionegro.test/ingresos-brutos"
    useful_page = "<article><p>Pérez afirmó que el costo será de 40.000 millones anuales.</p></article>"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="Pérez afirmó que el costo será de 40.000 millones anuales.",
                        confidence=0.9,
                        reason="repite la declaración",
                    ),
                    CheapEvidenceJudgement(
                        source_ref=2,
                        relation=EvidenceJudgementType.MENTIONS,
                        excerpt="47 mil millones de pesos por subsidios",
                        confidence=0.4,
                        reason="mismo tema fiscal, otro país",
                    ),
                    CheapEvidenceJudgement(
                        source_ref=3,
                        relation=EvidenceJudgementType.DOES_NOT_ESTABLISH,
                        excerpt=None,
                        confidence=0.3,
                        reason="otra provincia y otro proyecto",
                    ),
                ],
                ambiguous=False,
            )
        }
    )
    search = FakeSearchProvider(
        [
            SearchHit(
                title="Hacienda publica el proyecto",
                url=useful,
                snippet="Pérez afirmó que el costo será de 40.000 millones anuales.",
            ),
            SearchHit(
                title="Subsidios a combustibles",
                url=mexico,
                snippet="Dejan de ingresar 47 mil millones de pesos por subsidios a combustibles",
            ),
            SearchHit(
                title="Alivio de Ingresos Brutos",
                url=rionegro,
                snippet="Proponen reducir Ingresos Brutos en Río Negro",
            ),
        ]
    )
    fetcher = RecordingFetcher(
        {
            useful: useful_page,
            mexico: "<article><p>Dejan de ingresar 47 mil millones de pesos por subsidios a combustibles</p></article>",
            rionegro: "<article><p>Proponen reducir Ingresos Brutos en Río Negro</p></article>",
        }
    )
    result = _service(
        db_session, FakeStructuredLLM(), search, fetcher, assessor=assessor
    ).verify(event.id, trigger="admin")
    packet_urls = {row["url"] for row in result["packets"][str(claim.id)]}
    assert useful in packet_urls
    assert mexico in packet_urls
    assert rionegro in packet_urls
    linked = {
        link.source_item.url
        for link in db_session.scalars(select(EventSource).where(EventSource.event_id == event.id))
        if link.source_item is not None
    }
    assert item.url in linked
    assert useful in linked
    assert mexico not in linked
    assert rionegro not in linked
    extra = db_session.scalars(
        select(EventSource).where(
            EventSource.event_id == event.id,
            EventSource.source_item_id != item.id,
        )
    ).all()
    assert len(extra) == 1
    assert extra[0].relation_type == EventSourceRelation.ADDITIONAL
    assert extra[0].source_item.url == useful
    cid = str(claim.id)
    relations = [row["relation"] for row in result["assessments"][cid]["judgements"]]
    assert "DOES_NOT_ESTABLISH" in relations
    assert "SUPPORTS" in relations
    dne_check = next(row for row in result["comparison_checks"][cid] if row["requested"] == "DOES_NOT_ESTABLISH")
    assert dne_check["admitted"] is None
    assert dne_check["reason"] == "does_not_establish"


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
    assert claim.status == ClaimStatus.SINGLE_SOURCE


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
        response = client.post(f"/api/v1/admin/events/{event.id}/verify", headers=ADMIN_ORIGIN)
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
        response = client.post(f"/api/v1/admin/events/{event.id}/verify", headers=ADMIN_ORIGIN)
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
    class DirectedFakeSearch(FakeSearchProvider):
        def search(self, query):
            self.queries.append(query)
            return [] if query.include_domains else hits_by_query.get(query.text, [])
    search = DirectedFakeSearch()
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
    assert any("boletinoficial.gob.ar" in (query.include_domains or []) for query in search.queries)
    assert any(not query.include_domains for query in search.queries)
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
    result = _service(db_session, sol, search, assessor=assessor).verify(event.id, trigger="admin")
    db_session.refresh(claim)
    cid = str(claim.id)
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    assert "VerificationResult" not in sol.calls
    assert result["assessments"][cid]["judgements"][0]["relation"] == "DOES_NOT_ESTABLISH"
    assert result["decision_by_claim_id"][cid]["evaluation_state"] == "complete"
    assert result["comparison_checks"][cid][0]["requested"] == "DOES_NOT_ESTABLISH"
    assert result["comparison_checks"][cid][0]["admitted"] is None
    linked = {
        link.source_item.url
        for link in db_session.scalars(select(EventSource).where(EventSource.event_id == event.id))
        if link.source_item is not None
    }
    assert official not in linked


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


def test_strong_verification_does_not_disprove_sibling_without_its_own_comparison(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session, source_a.id, url="https://a.test/n", title="A", body="El decreto elimina X", content_hash="ha"
    )
    item_b = _item(
        db_session, source_b.id, url="https://b.test/n", title="B", body="El decreto no elimina X", content_hash="hb"
    )
    event = _event(db_session, item_a)
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    loser = _claim(
        db_session,
        event,
        text="El decreto elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="decreto",
        predicate="elimina",
        object_text="X",
        normalized_value="si",
    )
    winner = _claim(
        db_session,
        event,
        text="El decreto no elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="decreto",
        predicate="elimina",
        object_text="no X",
        normalized_value="no",
    )
    _evidence(db_session, loser, item_a, excerpt="El decreto elimina X")
    _evidence(db_session, winner, item_b, excerpt="El decreto no elimina X")
    db_session.flush()
    payload = {
        "selected": [{"claim_id": str(winner.id), "reasons": ["policy:documento"]}],
        "skipped_search": [],
        "primary_source_supports_claim": {str(winner.id): True},
        "sol": [
            {
                "claim_id": str(winner.id),
                "status_after": "SUPPORTED",
                "unresolved": False,
            }
        ],
    }
    service = VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))
    service._reconcile_verified_competitors([loser, winner], payload)
    assert winner.status == ClaimStatus.SUPPORTED
    assert loser.status == ClaimStatus.CONFLICTING


def test_strong_verification_does_not_disprove_temporal_update(db_session: Session) -> None:
    at_15 = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    at_17 = datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc)
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/n", title="N", body="heridos", content_hash="h1")
    event = _event(db_session, item)
    earlier = _claim(
        db_session,
        event,
        text="Se registraron 4 heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="accidente",
        predicate="cantidad_heridos",
        object_text="4",
        normalized_value="4",
        unit="personas",
        occurred_at=at_15,
    )
    later = _claim(
        db_session,
        event,
        text="Se confirmaron 6 heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="accidente",
        predicate="cantidad_heridos",
        object_text="6",
        normalized_value="6",
        unit="personas",
        occurred_at=at_17,
    )
    _evidence(db_session, earlier, item, excerpt="4 heridos")
    _evidence(db_session, later, item, excerpt="6 heridos")
    payload = {
        "selected": [{"claim_id": str(later.id), "reasons": ["policy:cifra"]}],
        "skipped_search": [],
        "primary_source_supports_claim": {str(later.id): True},
        "sol": [{"claim_id": str(later.id), "status_after": "SUPPORTED", "unresolved": False}],
    }
    VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [earlier, later], payload
    )
    assert earlier.status == ClaimStatus.SUPPORTED
    assert later.status == ClaimStatus.SUPPORTED


def test_winner_without_primary_does_not_disprove_sibling(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(db_session, source_a.id, url="https://a.test/n", title="A", body="elimina", content_hash="ha")
    item_b = _item(db_session, source_b.id, url="https://b.test/n", title="B", body="no elimina", content_hash="hb")
    event = _event(db_session, item_a)
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    loser = _claim(
        db_session,
        event,
        text="El decreto elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="decreto",
        predicate="elimina",
        object_text="X",
        normalized_value="si",
    )
    winner = _claim(
        db_session,
        event,
        text="El decreto no elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="decreto",
        predicate="elimina",
        object_text="no X",
        normalized_value="no",
    )
    _evidence(db_session, loser, item_a, excerpt="elimina")
    _evidence(db_session, winner, item_b, excerpt="no elimina")
    payload = {
        "selected": [{"claim_id": str(winner.id), "reasons": ["policy:documento"]}],
        "skipped_search": [],
        "primary_source_supports_claim": {str(winner.id): False},
        "sol": [{"claim_id": str(winner.id), "status_after": "SUPPORTED", "unresolved": False}],
    }
    VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [loser, winner], payload
    )
    assert loser.status == ClaimStatus.SUPPORTED


def test_canonical_text_fallback_does_not_auto_disprove(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/n", title="N", body="texto", content_hash="h1")
    event = _event(db_session, item)
    loser = _claim(
        db_session,
        event,
        text="El decreto elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    winner = _claim(
        db_session,
        event,
        text="El decreto no elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    _evidence(db_session, loser, item, excerpt="elimina")
    _evidence(db_session, winner, item, excerpt="no elimina")
    payload = {
        "selected": [{"claim_id": str(winner.id), "reasons": ["policy:documento"]}],
        "skipped_search": [],
        "primary_source_supports_claim": {str(winner.id): True},
        "sol": [{"claim_id": str(winner.id), "status_after": "SUPPORTED", "unresolved": False}],
    }
    VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [loser, winner], payload
    )
    assert loser.status == ClaimStatus.SUPPORTED


def test_attach_upgrades_existing_mentions_to_supports(db_session: Session) -> None:
    from app.services.verification_service import _PacketSource

    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/n",
        title="N",
        body="El decreto no elimina X según el texto oficial.",
        content_hash="h1",
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="El decreto no elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    row = _evidence(
        db_session,
        claim,
        item,
        excerpt="El decreto no elimina X",
        evidence_type=EvidenceType.MENTIONS,
    )
    packet = _PacketSource(
        ref=1,
        url=item.url,
        title=item.title or "",
        snippet=item.clean_text or "",
        item=item,
    )
    judgement = CheapEvidenceJudgement(
        source_ref=1,
        relation=EvidenceJudgementType.SUPPORTS,
        excerpt="El decreto no elimina X",
        confidence=0.9,
    )
    service = VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))
    added, cited = service._attach_evidence(
        event, claim, {1: packet}, 1, EvidenceType.SUPPORTS, judgement
    )
    assert added == 0
    assert cited == 1
    db_session.flush()
    db_session.refresh(row)
    assert row.evidence_type == EvidenceType.SUPPORTS


class _BoomSearch:
    def __init__(self) -> None:
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        request = httpx.Request("POST", "https://api.exa.ai/search")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("503", request=request, response=response)


def test_search_503_does_not_block_or_invent_support(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/costo",
        title="Anuncio",
        body="Pérez afirmó que el costo será de 40.000 millones.",
        content_hash="v503",
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Juan Pérez afirmó que el costo será de 40.000 millones.",
        claim_type="cifra",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.SINGLE_SOURCE,
        normalized_value="40000",
        unit="millones de pesos",
    )
    _evidence(db_session, claim, item, excerpt="Pérez afirmó que el costo será de 40.000 millones.")
    llm = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SINGLE_SOURCE)})
    search = _BoomSearch()
    result = _service(db_session, llm, search).verify(event.id, trigger="test")
    db_session.refresh(claim)
    assert "error" not in result
    assert result.get("search_unavailable") is True
    assert search.queries
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    assert claim.status != ClaimStatus.SUPPORTED


def test_other_jurisdiction_generic_overlap_is_evidence_not_public_source(db_session: Session) -> None:
    source = _source(db_session, domain="educacion.rionorte.test", feed_url="https://educacion.rionorte.test/rss.xml")
    item = _item(
        db_session,
        source.id,
        url="https://educacion.rionorte.test/calendario",
        title="Aguilar anuncia el 2 de marzo",
        body="La ministra de Educación de Río Norte, Marta Aguilar, anunció que el ciclo lectivo comenzará el 2 de marzo.",
        content_hash="c1",
    )
    event = _event(
        db_session,
        item,
        title_internal="La ministra de Educación de Río Norte, Marta Aguilar, anunció que el ciclo lectivo comenzará el 2 de marzo",
        event_type="anuncio_oficial",
        province="Río Norte",
        locality=None,
        short_summary="Aguilar anunció el inicio del ciclo lectivo el 2 de marzo.",
    )
    claim = _claim(
        db_session,
        event,
        text="El ciclo lectivo comenzará el 2 de marzo.",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        normalized_value="2",
        unit="marzo",
    )
    related = "https://calendario.rionorte.test/oficial"
    other = "https://www.rionegro.com.ar/ciclo-lectivo-2026"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="El Ministerio de Educación de Río Norte publicó el calendario y confirmó el 2 de marzo.",
                        confidence=0.9,
                        reason="misma jurisdicción y el mismo anuncio",
                    ),
                    CheapEvidenceJudgement(
                        source_ref=2,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="Este lunes 2 de marzo comenzó el ciclo lectivo 2026 en Río Negro.",
                        confidence=0.8,
                        reason="misma fecha genérica",
                    ),
                ],
                ambiguous=False,
            )
        }
    )
    search = FakeSearchProvider(
        [
            SearchHit(
                title="Educación de Río Norte confirma el 2 de marzo",
                url=related,
                snippet="El Ministerio de Educación de Río Norte publicó el calendario y confirmó el 2 de marzo.",
            ),
            SearchHit(
                title="Río Negro puso en marcha el ciclo lectivo 2026",
                url=other,
                snippet="Este lunes 2 de marzo comenzó el ciclo lectivo 2026 en Río Negro.",
            ),
        ]
    )
    fetcher = RecordingFetcher(
        {
            related: "<article><p>El Ministerio de Educación de Río Norte publicó el calendario y confirmó el 2 de marzo.</p></article>",
            other: "<article><p>Este lunes 2 de marzo comenzó el ciclo lectivo 2026 en Río Negro.</p></article>",
        }
    )
    _service(db_session, FakeStructuredLLM(), search, fetcher, assessor=assessor).verify(
        event.id, trigger="admin"
    )
    evidence_urls = {
        row.source_url
        for row in db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id))
    }
    assert related in evidence_urls
    assert other in evidence_urls
    linked = {
        link.source_item.url
        for link in db_session.scalars(select(EventSource).where(EventSource.event_id == event.id))
        if link.source_item is not None
    }
    assert item.url in linked
    assert related in linked
    assert other not in linked
    db_session.expire_all()
    loaded = db_session.scalars(
        select(Event)
        .options(
            selectinload(Event.event_sources)
            .selectinload(EventSource.source_item)
            .selectinload(SourceItem.source)
        )
        .where(Event.id == event.id)
    ).one()
    public_urls = {row["url"] for row in source_payloads(loaded)}
    assert item.url in public_urls
    assert related in public_urls
    assert other not in public_urls


def test_selected_claim_records_complete_evaluation_state(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/anuncio",
        title="Anuncio",
        body="El ministro anunció que el decreto está vigente",
        content_hash="h-eval",
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="El ministro anunció que el decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    llm = FakeStructuredLLM({"VerificationResult": _sol()})
    result = _service(db_session, llm, FakeSearchProvider()).verify(event.id, trigger="admin")
    cid = str(claim.id)
    decision = result["decision_by_claim_id"][cid]
    assert decision["evaluation_state"] == "complete"
    assert decision["status"] == claim.status.value
    assert claim.status == ClaimStatus.SINGLE_SOURCE


def test_policy_skip_records_explicit_skipped_decision(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/mix",
        title="Mix",
        body="El ministro habló. Pasó algo en la esquina.",
        content_hash="h-skip",
    )
    event = _event(db_session, item)
    selected = _claim(
        db_session,
        event,
        text="El ministro anunció que el decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    skipped = _claim(
        db_session,
        event,
        text="Pasó algo en la esquina",
        claim_type="hecho",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.UNCERTAIN,
    )
    llm = FakeStructuredLLM({"VerificationResult": _sol()})
    result = _service(db_session, llm, FakeSearchProvider()).verify(event.id, trigger="admin")
    selected_decision = result["decision_by_claim_id"][str(selected.id)]
    skipped_decision = result["decision_by_claim_id"][str(skipped.id)]
    assert selected_decision["evaluation_state"] == "complete"
    assert skipped_decision["evaluation_state"] == "skipped"
    assert skipped_decision["llm_reason"] == "policy_skip"
    assert skipped.status == ClaimStatus.UNCERTAIN
    assert any(
        row["claim_id"] == str(skipped.id) and row["reason"] == "policy_skip"
        for row in result["skipped_policy"]
    )


def test_budget_limit_records_explicit_skipped_decision(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/budget",
        title="Presupuesto de claims",
        body="Dos declaraciones.",
        content_hash="h-budget",
    )
    event = _event(db_session, item)
    first = _claim(
        db_session,
        event,
        text="La ministra anunció que el primer decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    second = _claim(
        db_session,
        event,
        text="El secretario anunció que el segundo decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    llm = FakeStructuredLLM({"VerificationResult": _sol()})
    service = _service(db_session, llm, FakeSearchProvider())
    service.settings = service.settings.model_copy(update={"max_verification_claims_per_event": 1})
    result = service.verify(event.id, trigger="admin")
    assert get_settings().max_verification_claims_per_event == 5
    decisions = result["decision_by_claim_id"]
    assert {decisions[str(first.id)]["evaluation_state"], decisions[str(second.id)]["evaluation_state"]} == {
        "complete",
        "skipped",
    }
    skipped_id = str(first.id) if decisions[str(first.id)]["evaluation_state"] == "skipped" else str(second.id)
    assert decisions[skipped_id]["llm_reason"] == "budget"
    assert any(row["claim_id"] == skipped_id and row["reason"] == "budget" for row in result["skipped_policy"])
    assert result["verification_budget"]["limit"] == 1
    assert first.status == ClaimStatus.SINGLE_SOURCE
    assert second.status == ClaimStatus.SINGLE_SOURCE


def test_numeric_skip_records_complete_decision(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/tarifas",
        title="Tarifas",
        body="El incremento será por debajo del 2,1%. La electricidad aumentará 1,75%.",
        content_hash="h-num",
    )
    event = _event(db_session, item)
    comparison = _claim(
        db_session,
        event,
        text="El incremento de electricidad y gas será por debajo del 2,1% que informó INDEC",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    sibling = _claim(
        db_session,
        event,
        text="La electricidad aumentará 1,75%",
        claim_type="cifra",
        importance=ClaimImportance.LOW,
        status=ClaimStatus.SUPPORTED,
        normalized_value="1.75",
    )
    llm = FakeStructuredLLM()
    search = FakeSearchProvider([SearchHit(title="x", url="https://otro.test/n", snippet="x")])
    result = _service(db_session, llm, search).verify(event.id, trigger="admin")
    cid = str(comparison.id)
    assert cid in result["decision_by_claim_id"]
    decision = result["decision_by_claim_id"][cid]
    assert decision["evaluation_state"] == "complete"
    assert cid in result["skipped_search"]
    assert comparison.status == ClaimStatus.SUPPORTED
    assert sibling.status == ClaimStatus.SUPPORTED
    assert llm.calls == []
    assert search.queries == []
    sibling_decision = result["decision_by_claim_id"][str(sibling.id)]
    assert sibling_decision["evaluation_state"] == "skipped"
    assert sibling_decision["llm_reason"] == "policy_skip"


def test_outside_recheck_records_explicit_skipped_decision(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/recheck",
        title="Recheck",
        body="Dos afirmaciones.",
        content_hash="h-recheck",
    )
    event = _event(db_session, item)
    target = _claim(
        db_session,
        event,
        text="El ministro anunció que el decreto está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    other = _claim(
        db_session,
        event,
        text="El secretario anunció que la resolución está vigente",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    llm = FakeStructuredLLM({"VerificationResult": _sol()})
    result = _service(db_session, llm, FakeSearchProvider()).verify(
        event.id, trigger="admin", claim_id=target.id
    )
    assert result["decision_by_claim_id"][str(target.id)]["evaluation_state"] == "complete"
    other_decision = result["decision_by_claim_id"][str(other.id)]
    assert other_decision["evaluation_state"] == "skipped"
    assert other_decision["llm_reason"] == "outside_recheck"
    assert other.status == ClaimStatus.SINGLE_SOURCE


def test_rejected_raw_supports_does_not_activate_cheap_support(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/base",
        title="Base",
        body="Pérez habló del presupuesto.",
        content_hash="h-reject",
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Pérez afirmó que el costo será de 40.000 millones",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    hit = "https://medio.test/cifra"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="el costo será de 40.000 millones",
                        reason="el recorte menciona la cifra",
                    )
                ],
                ambiguous=False,
                reason="apoyo textual",
            )
        }
    )
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SUPPORTED)})
    search = FakeSearchProvider(
        [SearchHit(title="Cifra", url=hit, snippet="el costo será de 40.000 millones")]
    )
    result = _service(
        db_session,
        sol,
        search,
        RecordingFetcher({hit: "<article><p>el costo será de 40.000 millones</p></article>"}),
        assessor=assessor,
    ).verify(event.id, trigger="admin")
    cid = str(claim.id)
    db_session.refresh(claim)
    assert result["assessments"][cid]["judgements"][0]["relation"] == "SUPPORTS"
    assert result["comparison_checks"][cid][0]["admitted"] == "MENTIONS"
    assert result["comparison_checks"][cid][0]["reason"] == "statement_not_established"
    assert result["escalated"][cid] is False
    assert "VerificationResult" not in sol.calls
    assert assessor.calls == ["CheapClaimEvidenceAssessment"]
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    assert result["decision_by_claim_id"][cid]["evaluation_state"] == "complete"
    assert result["decision_by_claim_id"][cid]["status"] == "SINGLE_SOURCE"


def test_admitted_support_with_insufficient_origins_is_not_supported(db_session: Session) -> None:
    source = _source(db_session)
    body = "Hubo un incendio en el depósito de Rosario durante la madrugada."
    item = _item(
        db_session,
        source.id,
        url="https://medio.test/incendio",
        title="Incendio",
        body=body,
        content_hash="h-fire",
    )
    event = _event(db_session, item, title_internal="Incendio en un depósito de Rosario")
    claim = _claim(
        db_session,
        event,
        text="Hubo un incendio en el depósito de Rosario.",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    _evidence(db_session, claim, item, excerpt=body)
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt=body,
                        reason="el recorte relata el incendio",
                    )
                ],
                ambiguous=False,
            )
        }
    )
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SUPPORTED)})
    result = _service(
        db_session, sol, FakeSearchProvider([]), assessor=assessor
    ).verify(event.id, trigger="admin")
    cid = str(claim.id)
    db_session.refresh(claim)
    assert result["comparison_checks"][cid][0]["admitted"] == "SUPPORTS"
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    assert result["decision_by_claim_id"][cid]["status"] == "SINGLE_SOURCE"
    assert result["decision_by_claim_id"][cid]["evaluation_state"] == "complete"
    assert "VerificationResult" not in sol.calls


def test_uncertain_rejected_supports_escalates_on_existing_sol_path(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/base",
        title="Base",
        body="Se habló del presupuesto.",
        content_hash="h-unc",
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Pérez afirmó que el costo será de 40.000 millones",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.UNCERTAIN,
    )
    hit = "https://medio.test/cifra-u"
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="el costo será de 40.000 millones",
                    )
                ],
                ambiguous=False,
            )
        }
    )
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True)})
    result = _service(
        db_session,
        sol,
        FakeSearchProvider([SearchHit(title="Cifra", url=hit, snippet="el costo será de 40.000 millones")]),
        RecordingFetcher({hit: "<article><p>el costo será de 40.000 millones</p></article>"}),
        assessor=assessor,
    ).verify(event.id, trigger="admin")
    cid = str(claim.id)
    assert result["escalated"][cid] is True
    assert sol.calls == ["VerificationResult"]
    assert assessor.calls == ["CheapClaimEvidenceAssessment"]
    assert assessor.calls.count("CheapClaimEvidenceAssessment") == 1
    db_session.refresh(claim)
    assert result["decision_by_claim_id"][cid]["evaluation_state"] == "complete"


def test_missing_assessment_is_not_recorded_as_does_not_establish(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/base",
        title="Base",
        body="El ministro habló",
        content_hash="h-none",
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
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.SINGLE_SOURCE)})
    result = _service(db_session, sol, FakeSearchProvider([])).verify(event.id, trigger="admin")
    cid = str(claim.id)
    assert cid not in result["assessments"]
    assert result["escalated"][cid] is True
    assert "VerificationResult" in sol.calls


def test_new_cheap_evaluation_does_not_change_published_snapshot(db_session: Session) -> None:
    from app.services.feed_ranking import compact_public_claims
    from app.services.publish_service import PublishService
    from tests.test_audit import _pass_audit
    from tests.test_writing_certainty import _audit, _seed

    event, article, rows, _refs = _seed(
        db_session,
        claims=[{"text": "Hubo un incendio en el depósito de Rosario.", "status": ClaimStatus.SUPPORTED}],
        headline="Hubo un incendio en el depósito de Rosario",
        summary="Hubo un incendio en el depósito de Rosario.",
        paragraphs=[[("Hubo un incendio en el depósito de Rosario durante la madrugada.", ["C1"])]],
    )
    first, _llm = _audit(db_session, event, result=_pass_audit())
    assert first["passed"] is True
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True
    db_session.refresh(article)
    frozen_before = compact_public_claims(db_session, event, freeze_to_version=article.published_version)
    before_status = frozen_before[0]["status"]
    claim = rows[0]
    sol = FakeStructuredLLM({"VerificationResult": _sol(status=ClaimStatus.UNCERTAIN, unresolved=True)})
    _service(db_session, sol, FakeSearchProvider([])).verify(event.id, trigger="admin", claim_id=claim.id)
    db_session.refresh(claim)
    db_session.refresh(article)
    frozen_after = compact_public_claims(db_session, event, freeze_to_version=article.published_version)
    assert frozen_after[0]["status"] == before_status
    assert claim.status == ClaimStatus.UNCERTAIN
    assert article.published_version == 1

