from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.article_body import annotated_article_draft
from app.domain.enums import (
    ArticleStatus,
    ClaimImportance,
    ClaimStatus,
    EventStatus,
    EventUpdateType,
    EvidenceType,
    IngestionMethod,
)
from app.main import app
from app.models import Article, ArticleVersion, Claim, ClaimEvidence, Event, EventSource, EventUpdate
from app.providers.fakes import FakeEmbeddingProvider, FakeSearchProvider, FakeStructuredLLM, RecordingFetcher
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult
from app.schemas.claims import (
    ClaimExtractionBatch,
    ClaimResolutionBatch,
    ClaimResolutionItem,
    ExtractedClaim,
    ExtractedEvidence,
)
from app.schemas.detection import EditorialTopic, EventCandidate, RelevanceLevel
from app.schemas.verification import VerificationResult
from app.services.audit_service import AuditService
from app.services.claim_service import ClaimService
from app.services.detection_service import DetectionService
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_service import VerificationService
from app.services.writing_service import WritingService, should_enqueue_write
from tests.test_claims import _attach, _event, _extracted, _item, _llm, _service, _source

WHEN = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _candidate(*, what: str) -> EventCandidate:
    return EventCandidate(
        event_type="accidente",
        what_happened=what,
        occurred_at=WHEN,
        locality="Rosario",
        province="Santa Fe",
        country_code="AR",
        short_summary=what,
        editorial_topic=EditorialTopic.GOVERNMENT,
        is_public_affairs=True,
        political_relevance=RelevanceLevel.HIGH,
        entities=[],
    )


def _source_named(session: Session, name: str, domain: str):
    return SourceService(session).create(
        SourceCreate(
            name=name,
            domain=domain,
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url=f"https://{domain}/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )


def _ingest(session: Session, source_id, *, url: str, title: str, body: str, content_hash: str):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
            published_at=WHEN,
        )
    ).item


def _extract(text: str, *, value: str | None = None, excerpt: str | None = None) -> ExtractedClaim:
    return ExtractedClaim(
        canonical_text=text,
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        subject="choque",
        predicate="heridos",
        object_text=text,
        normalized_value=value,
        evidence=[
            ExtractedEvidence(
                source_ref=1,
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt or text,
            )
        ],
    )


def _verify_llm(*statuses: ClaimStatus) -> FakeStructuredLLM:
    base = list(statuses) or [ClaimStatus.SINGLE_SOURCE]
    rows = [VerificationResult(status=status, reason="ok") for status in base]
    rows.extend(VerificationResult(status=status, reason="ok") for status in base)
    rows.extend(VerificationResult(status=ClaimStatus.SINGLE_SOURCE, reason="ok") for _ in range(6))
    return FakeStructuredLLM({"VerificationResult": rows})


def _publish_track_a(session: Session, event, claims_text: str, *, value: str = "6") -> Article:
    claims_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(claims=[_extract(claims_text, value=value)]),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE, reason="una fuente")]
            ),
        }
    )
    resolved = ClaimService(session, extractor_llm=claims_llm, resolver_llm=claims_llm).resolve(
        event.id, trigger="new_event"
    )
    assert resolved.get("error") is None
    verified = VerificationService(
        session, llm=_verify_llm(ClaimStatus.SINGLE_SOURCE), search=FakeSearchProvider([]), fetcher=RecordingFetcher()
    ).verify(event.id, trigger="claims")
    assert verified.get("error") is None
    lead = (
        claims_text
        if "según" in claims_text.casefold() or "segun" in claims_text.casefold()
        else f"Según la primera fuente, {claims_text}"
    )
    draft = annotated_article_draft(
        "Según la primera fuente, hubo seis heridos en el choque",
        "Un choque en Rosario dejó heridos, según la primera fuente.",
        [[(lead, ["C1"])]],
    )
    written = WritingService(session, llm=FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="verification"
    )
    assert written["written"] is True
    pass_audit = FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    audited = AuditService(session, llm=pass_audit, writer=pass_audit).audit(event.id, trigger="writing")
    assert audited["passed"] is True
    published = PublishService(session).publish(event.id, trigger="audit")
    assert published["published"] is True
    article = session.scalars(select(Article).where(Article.event_id == event.id)).one()
    session.refresh(article)
    session.refresh(event)
    return article


def test_incremental_claims_extracts_only_new_source(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://a.test/seis",
        title="Seis heridos",
        body="Hubo seis heridos en el choque de Rosario.",
        content_hash="ha",
        published_at=WHEN,
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://b.test/seis",
        title="Seis heridos",
        body="Otra redacción: hubo seis heridos en el choque de Rosario.",
        content_hash="hb",
        published_at=WHEN,
    )
    event = _event(db_session, item_a)
    first_llm = _llm(
        ClaimExtractionBatch(claims=[_extracted(text="Hubo seis heridos", evidence=[
            ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="Hubo seis heridos")
        ], subject="choque", predicate="heridos", normalized_value="6")]),
        ClaimResolutionBatch(items=[ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE, reason="a")]),
    )
    first = _service(db_session, first_llm).resolve(event.id, trigger="new_event")
    assert first["persisted"] == 1
    assert "Hubo seis heridos en el choque de Rosario." in first_llm.user_prompts[0]
    _attach(db_session, event, item_b)

    second_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[_extract("Hubo seis heridos", value="6", excerpt="hubo seis heridos")]
            ),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, reason="dos fuentes")]
            ),
        }
    )
    second = ClaimService(db_session, extractor_llm=second_llm, resolver_llm=second_llm).resolve(
        event.id, trigger="existing_event", source_item_id=item_b.id
    )
    assert second["changed"] is True
    assert second["new_evidence"] == 1
    assert "Otra redacción" in second_llm.user_prompts[0]
    assert "Hubo seis heridos en el choque de Rosario." not in second_llm.user_prompts[0]
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    assert len(claims) == 1
    evidence = list(db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claims[0].id)))
    assert {row.source_item_id for row in evidence} == {item_a.id, item_b.id}
    VerificationService(
        db_session, llm=_verify_llm(ClaimStatus.SUPPORTED), search=FakeSearchProvider([]), fetcher=RecordingFetcher()
    ).verify(event.id, trigger="existing_event")

    third = ClaimService(db_session, extractor_llm=second_llm, resolver_llm=second_llm).resolve(
        event.id, trigger="existing_event", source_item_id=item_b.id
    )
    assert third["reason"] == "source_already_extracted"
    assert third["changed"] is False
    assert db_session.scalar(select(func.count()).select_from(ClaimEvidence)) == 2


def test_track_b_material_keeps_v1_live_until_manual_publish(db_session: Session) -> None:
    source_a = _source_named(db_session, "A", "a.test")
    item_a = _ingest(
        db_session,
        source_a.id,
        url="https://a.test/choque",
        title="Seis heridos",
        body="Hubo seis heridos en el choque de Rosario.",
        content_hash="ha",
    )
    embedder = FakeEmbeddingProvider()
    embedder.mode = "high"
    detected = DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="Hubo seis heridos en el choque de Rosario")}),
        embeddings=embedder,
    ).detect(item_a.id)
    assert detected["created"] is True
    event = db_session.get(Event, detected["event_id"])
    assert event is not None
    event.relevance_score = 85
    article = _publish_track_a(db_session, event, "Hubo seis heridos en el choque de Rosario.")
    v1 = article.published_version
    assert v1 == 1
    assert event.status == EventStatus.PUBLISHED
    updates_after_v1 = db_session.scalar(
        select(func.count()).select_from(EventUpdate).where(
            EventUpdate.event_id == event.id,
            EventUpdate.update_type == EventUpdateType.ARTICLE_UPDATED,
        )
    )

    source_b = _source_named(db_session, "B", "b.test")
    item_b = _ingest(
        db_session,
        source_b.id,
        url="https://b.test/transito",
        title="Tránsito cortado",
        body="El tránsito permanece cortado tras el choque de Rosario.",
        content_hash="hb",
    )
    linked = DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="El tránsito permanece cortado tras el choque")}),
        embeddings=embedder,
    ).detect(item_b.id)
    assert linked["created"] is False
    assert linked["event_id"] == str(event.id)

    claims_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    ExtractedClaim(
                        canonical_text="El tránsito permanece cortado",
                        claim_type="hecho",
                        importance=ClaimImportance.HIGH,
                        subject="tránsito",
                        predicate="cortado",
                        object_text="tras el choque",
                        evidence=[
                            ExtractedEvidence(
                                source_ref=1,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="El tránsito permanece cortado",
                            )
                        ],
                    )
                ]
            ),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE, reason="nueva")]
            ),
        }
    )
    incremental = ClaimService(db_session, extractor_llm=claims_llm, resolver_llm=claims_llm).resolve(
        event.id, trigger="existing_event", source_item_id=item_b.id
    )
    assert incremental["changed"] is True
    db_session.expire(event, ["claims"])
    VerificationService(
        db_session,
        llm=_verify_llm(ClaimStatus.SINGLE_SOURCE, ClaimStatus.SINGLE_SOURCE),
        search=FakeSearchProvider([]),
        fetcher=RecordingFetcher(),
    ).verify(event.id, trigger="existing_event")
    assert should_enqueue_write(db_session, event.id) is True

    writer = FakeStructuredLLM(
        {
            "ArticleDraft": annotated_article_draft(
                "Según la segunda fuente, el tránsito sigue cortado tras el choque",
                "Hay heridos y, según esa cobertura, el tránsito permanece cortado en Rosario.",
                [[("Según la segunda fuente, el tránsito permanece cortado tras el choque de Rosario.", ["C1"])]],
            )
        }
    )
    written = WritingService(db_session, llm=writer).write(event.id, trigger="existing_event")
    assert written["written"] is True
    assert written["version"] == 2
    prompt = writer.user_prompts[-1]
    assert "current_article" in prompt
    assert "knowledge_delta" in prompt
    assert "authoritative_claims" in prompt
    assert "Según la primera fuente, hubo seis heridos en el choque" in prompt
    assert '"source_contexts": []' in prompt or '"source_contexts":[]' in prompt
    db_session.refresh(article)
    assert article.published_version == v1
    assert article.status == ArticleStatus.DRAFT
    assert article.current_version == 2

    pass_audit = FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    audited = AuditService(db_session, llm=pass_audit, writer=pass_audit).audit(event.id, trigger="writing")
    assert audited["passed"] is True
    db_session.refresh(article)
    db_session.refresh(event)
    db_session.commit()
    assert article.status == ArticleStatus.READY_FOR_REVIEW
    assert article.published_version == v1
    assert event.status == EventStatus.PUBLISHED
    assert db_session.scalar(select(func.count()).select_from(Event)) == 1
    assert db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(EventUpdate).where(
            EventUpdate.event_id == event.id, EventUpdate.update_type == EventUpdateType.ARTICLE_UPDATED
        )
    ) == updates_after_v1

    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
        feed = client.get("/api/v1/feed").json()
        live = client.get("/api/v1/live").json()
        local = client.get("/api/v1/local", params={"locality": "Rosario"}).json()
    assert payload["headline"] == "Según la primera fuente, hubo seis heridos en el choque"
    assert payload["published_version"] == v1
    from app.core.article_body import claim_ids_in_body_blocks
    from app.services.feed_ranking import compact_public_claims, live_content

    live_version = live_content(db_session, article)
    allowed = claim_ids_in_body_blocks(live_version.body_blocks)
    frozen = compact_public_claims(db_session, event, allowed_ids=allowed, freeze_to_version=v1)
    live_rows = compact_public_claims(db_session, event)
    assert payload["claims"]
    assert {row["id"] for row in payload["claims"]} == {row["id"] for row in frozen}
    assert payload["claims"][0]["status"] == frozen[0]["status"]
    assert payload["claims"][0]["presentation"] == frozen[0]["presentation"]
    assert payload["claims"][0]["editorial_labels"] == frozen[0]["editorial_labels"]
    assert {row["id"] for row in live_rows} != {row["id"] for row in payload["claims"]}
    slugs = lambda body: {item["slug"] for item in body["items"]}
    assert article.slug in slugs(feed)
    assert article.slug in slugs(live)
    assert article.slug in slugs(local)

    published = PublishService(db_session).publish(event.id, trigger="admin")
    assert published["published"] is True
    db_session.refresh(article)
    db_session.refresh(event)
    db_session.commit()
    versions = list(db_session.scalars(select(ArticleVersion).where(ArticleVersion.article_id == article.id)))
    assert {row.version_number for row in versions} == {1, 2}
    assert article.published_version == 2
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED
    assert db_session.scalar(select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id)) == 2
    assert db_session.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == event.id)) == 2
    assert db_session.scalar(
        select(func.count()).select_from(EventUpdate).where(
            EventUpdate.event_id == event.id, EventUpdate.update_type == EventUpdateType.ARTICLE_UPDATED
        )
    ) == updates_after_v1 + 1
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
        assert payload["headline"] == "Según la segunda fuente, el tránsito sigue cortado tras el choque"
    assert payload["published_version"] == 2
    from app.core.article_body import claim_ids_in_body_blocks
    from app.services.feed_ranking import compact_public_claims, live_content

    live_v2 = live_content(db_session, article)
    allowed_v2 = claim_ids_in_body_blocks(live_v2.body_blocks)
    frozen_v2 = compact_public_claims(db_session, event, allowed_ids=allowed_v2, freeze_to_version=2)
    assert payload["claims"][0]["status"] == frozen_v2[0]["status"]
    assert payload["claims"][0]["presentation"] == frozen_v2[0]["presentation"]
    assert payload["claims"][0]["editorial_labels"] == frozen_v2[0]["editorial_labels"]


def test_track_b_repetition_does_not_rewrite(db_session: Session) -> None:
    source_a = _source_named(db_session, "A", "a.test")
    item_a = _ingest(
        db_session,
        source_a.id,
        url="https://a.test/seis",
        title="Seis heridos",
        body="Hubo seis heridos.",
        content_hash="ha",
    )
    embedder = FakeEmbeddingProvider()
    embedder.mode = "high"
    detected = DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="Hubo seis heridos")}),
        embeddings=embedder,
    ).detect(item_a.id)
    event = db_session.get(Event, detected["event_id"])
    assert event is not None
    event.relevance_score = 85
    article = _publish_track_a(db_session, event, "Hubo seis heridos.", value="6")
    updates_before = db_session.scalar(
        select(func.count()).select_from(EventUpdate).where(
            EventUpdate.event_id == event.id,
            EventUpdate.update_type == EventUpdateType.ARTICLE_UPDATED,
        )
    )

    source_b = _source_named(db_session, "B", "b.test")
    item_b = _ingest(
        db_session,
        source_b.id,
        url="https://b.test/seis",
        title="Seis heridos",
        body="Hubo seis heridos.",
        content_hash="hb",
    )
    linked = DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="Hubo seis heridos")}),
        embeddings=embedder,
    ).detect(item_b.id)
    assert linked["created"] is False
    claims_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(claims=[_extract("Hubo seis heridos", value="6")]),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, reason="corroboración")]
            ),
        }
    )
    incremental = ClaimService(db_session, extractor_llm=claims_llm, resolver_llm=claims_llm).resolve(
        event.id, trigger="existing_event", source_item_id=item_b.id
    )
    assert incremental["changed"] is True
    db_session.expire(event, ["claims"])
    claim = db_session.scalars(select(Claim).where(Claim.event_id == event.id)).one()
    assert len(claim.evidence) == 2
    VerificationService(
        db_session, llm=_verify_llm(ClaimStatus.SUPPORTED), search=FakeSearchProvider([]), fetcher=RecordingFetcher()
    ).verify(event.id, trigger="existing_event")
    assert should_enqueue_write(db_session, event.id) is False
    writer = FakeStructuredLLM({"ArticleDraft": annotated_article_draft("X", "Y", [[("Z", ["C1"])]])})
    written = WritingService(db_session, llm=writer).write(event.id, trigger="existing_event")
    assert written["written"] is False
    assert written["reason"] == "no_material_change"
    assert writer.calls == []
    db_session.refresh(article)
    db_session.refresh(event)
    assert article.published_version == 1
    assert article.current_version == 1
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED
    assert db_session.scalar(select(func.count()).select_from(ArticleVersion)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(EventUpdate).where(
            EventUpdate.event_id == event.id,
            EventUpdate.update_type == EventUpdateType.ARTICLE_UPDATED,
        )
    ) == updates_before


def test_track_b_contradiction_is_material_and_freezes_public_claims(db_session: Session) -> None:
    source_a = _source_named(db_session, "A", "a.test")
    item_a = _ingest(
        db_session,
        source_a.id,
        url="https://a.test/seis",
        title="Seis heridos",
        body="Hubo seis heridos.",
        content_hash="ha",
    )
    embedder = FakeEmbeddingProvider()
    embedder.mode = "high"
    detected = DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="Hubo seis heridos")}),
        embeddings=embedder,
    ).detect(item_a.id)
    event = db_session.get(Event, detected["event_id"])
    assert event is not None
    event.relevance_score = 85
    article = _publish_track_a(db_session, event, "Hubo seis heridos.", value="6")
    live_claim = db_session.scalars(select(Claim).where(Claim.event_id == event.id)).one()
    live_status = live_claim.status

    source_b = _source_named(db_session, "B", "b.test")
    item_b = _ingest(
        db_session,
        source_b.id,
        url="https://b.test/ocho",
        title="Ocho heridos",
        body="Hubo ocho heridos.",
        content_hash="hb",
    )
    DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="Hubo ocho heridos")}),
        embeddings=embedder,
    ).detect(item_b.id)
    claims_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(claims=[_extract("Hubo ocho heridos", value="8")]),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[
                    ClaimResolutionItem(claim_ref=1, status=ClaimStatus.CONFLICTING, reason="discrepancia"),
                    ClaimResolutionItem(claim_ref=2, status=ClaimStatus.CONFLICTING, reason="discrepancia"),
                ]
            ),
        }
    )
    incremental = ClaimService(db_session, extractor_llm=claims_llm, resolver_llm=claims_llm).resolve(
        event.id, trigger="existing_event", source_item_id=item_b.id
    )
    assert incremental["changed"] is True
    db_session.expire(event, ["claims"])
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    assert len(claims) == 2
    VerificationService(
        db_session,
        llm=_verify_llm(ClaimStatus.CONFLICTING, ClaimStatus.CONFLICTING),
        search=FakeSearchProvider([]),
        fetcher=RecordingFetcher(),
    ).verify(event.id, trigger="existing_event")
    writer = FakeStructuredLLM(
        {
            "ArticleDraft": annotated_article_draft(
                "Hay cifras en conflicto sobre los heridos",
                "Las fuentes no coinciden en el número de heridos.",
                [[("Las fuentes hablan de seis u ocho heridos.", ["C1", "C2"])]],
            )
        }
    )
    written = WritingService(db_session, llm=writer).write(event.id, trigger="existing_event")
    assert written["written"] is True
    assert written["version"] == 2
    pass_audit = FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    AuditService(db_session, llm=pass_audit, writer=pass_audit).audit(event.id, trigger="writing")
    db_session.refresh(article)
    db_session.commit()
    assert article.published_version == 1
    assert article.status == ArticleStatus.READY_FOR_REVIEW
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
    assert payload["headline"] == "Según la primera fuente, hubo seis heridos en el choque"
    public_ids = {row["id"] for row in payload["claims"]}
    assert str(live_claim.id) in public_ids
    live_row = next(row for row in payload["claims"] if row["id"] == str(live_claim.id))
    assert live_row["status"] == live_status.value
    assert "DISCREPANCY" not in live_row["editorial_labels"]
    competing = [row for row in payload["claims"] if row["id"] != str(live_claim.id)]
    assert competing == []
    from app.services.feed_ranking import compact_public_claims

    live_rows = compact_public_claims(db_session, event)
    live_now = next(row for row in live_rows if row["id"] == str(live_claim.id))
    assert live_now["status"] == ClaimStatus.CONFLICTING.value
    assert live_row["presentation"]["verification_label"] != live_now["presentation"]["verification_label"]
    assert live_row["presentation"] != live_now["presentation"]
    assert "DISCREPANCY" in live_now["editorial_labels"]


def test_track_b_retry_continues_audit_without_v3(db_session: Session) -> None:
    source_a = _source_named(db_session, "A", "a.test")
    item_a = _ingest(
        db_session,
        source_a.id,
        url="https://a.test/seis",
        title="Seis heridos",
        body="Hubo seis heridos.",
        content_hash="ha",
    )
    embedder = FakeEmbeddingProvider()
    embedder.mode = "high"
    detected = DetectionService(
        db_session,
        light_llm=FakeStructuredLLM({"EventCandidate": _candidate(what="Hubo seis heridos")}),
        embeddings=embedder,
    ).detect(item_a.id)
    event = db_session.get(Event, detected["event_id"])
    assert event is not None
    article = _publish_track_a(db_session, event, "Hubo seis heridos.", value="6")
    extra = Claim(
        event_id=event.id,
        canonical_text="El tránsito permanece cortado",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="tránsito",
        predicate="cortado",
        object_text="tras el choque",
    )
    db_session.add(extra)
    db_session.flush()
    writer = FakeStructuredLLM(
        {
            "ArticleDraft": annotated_article_draft(
                "Según la segunda fuente, el tránsito sigue cortado",
                "Hay heridos y, según esa cobertura, el tránsito permanece cortado.",
                [[("Según la segunda fuente, el tránsito permanece cortado.", ["C1"])]],
            )
        }
    )
    first = WritingService(db_session, llm=writer).write(event.id, trigger="existing_event")
    assert first["written"] is True
    assert first["version"] == 2
    db_session.refresh(article)
    assert article.current_version == 2
    retry_writer = FakeStructuredLLM(
        {"ArticleDraft": annotated_article_draft("No debería", "No", [[("No", ["C1"])]])}
    )
    retry = WritingService(db_session, llm=retry_writer).write(event.id, trigger="existing_event")
    assert retry["written"] is True
    assert retry["reason"] == "unaudited_candidate"
    assert retry["version"] == 2
    assert retry_writer.calls == []
    assert db_session.scalar(select(func.count()).select_from(ArticleVersion)) == 2
    pass_audit = FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    audited = AuditService(db_session, llm=pass_audit, writer=pass_audit).audit(event.id, trigger="writing")
    assert audited["passed"] is True
    db_session.refresh(article)
    assert article.current_version == 2
    assert article.published_version == 1
    assert article.status == ArticleStatus.READY_FOR_REVIEW
