from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.article_body import annotated_article_draft
from app.domain.enums import (
    ArticleStatus,
    ClaimImportance,
    ClaimStatus,
    EventSourceRelation,
    EventStatus,
    EvidenceType,
    IngestionMethod,
)
from app.main import app
from app.models import Article, Claim, ClaimEvidence, Event
from app.providers.fakes import FakeEmbeddingProvider, FakeStructuredLLM
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
from app.services.audit_service import AuditService
from app.services.claim_service import ClaimService
from app.services.detection_service import DetectionService
from app.services.event_service import EventService
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.writing_service import WritingService


def test_ffaa_raise_pipeline_maps_claim_ref_and_exposes_uuid(db_session: Session) -> None:
    source_a = SourceService(db_session).create(
        SourceCreate(
            name="Casa Rosada",
            domain="casarosada.gob.ar",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://casarosada.gob.ar/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )
    source_b = SourceService(db_session).create(
        SourceCreate(
            name="Oposición Diario",
            domain="oposicion.test",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://oposicion.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )
    source_c = SourceService(db_session).create(
        SourceCreate(
            name="Agencia",
            domain="agencia.test",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://agencia.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item_a = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source_a.id,
            url="https://casarosada.gob.ar/aumento-ffaa",
            canonical_url="https://casarosada.gob.ar/aumento-ffaa",
            content_hash="ffaa-a",
            title="El Gobierno reconoció el esfuerzo de las FFAA",
            clean_text=(
                "El Gobierno reconoció el esfuerzo de las Fuerzas Armadas con un aumento del 12,22%."
            ),
        )
    ).item
    item_b = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source_b.id,
            url="https://oposicion.test/aumento-ffaa",
            canonical_url="https://oposicion.test/aumento-ffaa",
            content_hash="ffaa-b",
            title="El Ejecutivo anunció un aumento para las FFAA",
            clean_text="El Ejecutivo anunció un aumento del 12,22% para las Fuerzas Armadas.",
        )
    ).item
    item_c = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source_c.id,
            url="https://agencia.test/aumento-ffaa",
            canonical_url="https://agencia.test/aumento-ffaa",
            content_hash="ffaa-c",
            title="Incremento salarial para las Fuerzas Armadas",
            clean_text="Las Fuerzas Armadas recibirán un incremento salarial del 12,22%.",
        )
    ).item

    detection_llm = FakeStructuredLLM(
        {
            "EventCandidate": EventCandidate(
                event_type="anuncio_oficial",
                what_happened="El Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas",
                occurred_at=datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
                locality="Buenos Aires",
                province="Buenos Aires",
                country_code="AR",
                short_summary="Aumento salarial del 12,22% para las FFAA",
                editorial_topic=EditorialTopic.GOVERNMENT,
                is_public_affairs=True,
                political_relevance=RelevanceLevel.HIGH,
                entities=[],
            )
        }
    )
    detected = DetectionService(
        db_session, light_llm=detection_llm, embeddings=FakeEmbeddingProvider()
    ).detect(item_a.id)
    assert detected["created"] is True
    event = db_session.get(Event, detected["event_id"])
    assert event is not None
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    EventService(db_session).attach_source(event, item_c.id, relation_type=EventSourceRelation.ADDITIONAL)

    claims_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    ExtractedClaim(
                        canonical_text="El Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas",
                        claim_type="cifra",
                        importance=ClaimImportance.HIGH,
                        subject="Fuerzas Armadas",
                        predicate="aumento_salarial",
                        object_text="12,22%",
                        normalized_value="12.22",
                        unit="porcentaje",
                        evidence=[
                            ExtractedEvidence(
                                source_ref=1,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="aumento del 12,22%",
                                confidence=0.9,
                            ),
                            ExtractedEvidence(
                                source_ref=2,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="aumento del 12,22%",
                                confidence=0.9,
                            ),
                            ExtractedEvidence(
                                source_ref=3,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="incremento salarial del 12,22%",
                                confidence=0.9,
                            ),
                        ],
                    )
                ]
            ),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[
                    ClaimResolutionItem(
                        claim_ref=1,
                        status=ClaimStatus.SUPPORTED,
                        confidence=0.9,
                        reason="tres fuentes alineadas",
                    )
                ]
            ),
        }
    )
    extracted = ClaimService(db_session, extractor_llm=claims_llm, resolver_llm=claims_llm).resolve(
        event.id, trigger="detection"
    )
    assert extracted["persisted"] == 1
    claim = db_session.scalars(select(Claim).where(Claim.event_id == event.id)).one()
    evidence = list(db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)))
    assert len(evidence) == 3

    draft = annotated_article_draft(
        "El Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas",
        "El Ejecutivo anunció un incremento salarial del 12,22% para las Fuerzas Armadas.",
        paragraphs=[
            [("El anuncio se hizo durante una conferencia de prensa.", [])],
            [("El aumento dispuesto es del 12,22%.", ["C1"])],
            [("Las tres fuentes coinciden en el porcentaje informado.", [])],
        ],
    )
    writing_llm = FakeStructuredLLM({"ArticleDraft": draft})
    written = WritingService(db_session, llm=writing_llm).write(event.id, trigger="claims")
    assert written["written"] is True
    article = db_session.scalars(select(Article).where(Article.event_id == event.id)).one()
    annotated = next(
        segment
        for block in article.body_blocks
        for segment in block["segments"]
        if segment.get("claim_ids")
    )
    assert annotated["claim_ids"] == [str(claim.id)]
    assert "claim_refs" not in annotated
    assert "12,22%" in article.body
    assert "<" not in article.body

    audit_llm = FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    audited = AuditService(db_session, llm=audit_llm).audit(event.id, trigger="writing")
    assert audited["passed"] is True
    assert audited["rewrite_count"] == 0
    published = PublishService(db_session).publish(event.id, trigger="audit")
    assert published["published"] is True
    db_session.refresh(article)
    db_session.refresh(event)
    db_session.commit()
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED

    assert detection_llm.calls == ["EventCandidate"]
    assert claims_llm.calls.count("ClaimExtractionBatch") == 1
    assert writing_llm.calls == ["ArticleDraft"]
    assert audit_llm.calls == ["ArticleAuditResult"]

    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
    assert payload["body_blocks"][1]["segments"][0]["claim_ids"] == [str(claim.id)]
    assert payload["claims"][0]["id"] == str(claim.id)
    assert payload["claims"][0]["canonical_text"]
    assert payload["claims"][0]["editorial_labels"] == []
    assert payload["claims"][0]["false_assertions"] == []
    assert "C1" not in str(payload["body_blocks"])
