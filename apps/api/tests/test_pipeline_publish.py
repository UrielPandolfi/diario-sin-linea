from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
from app.models import Article, Claim, Event, EventSource, SourceItem
from app.providers.base import SearchHit
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
from app.schemas.detection import EventCandidate
from app.schemas.research import RelevanceBatch, RelevanceHit, ResearchQueries
from app.schemas.verification import VerificationResult
from app.schemas.writing import ArticleDraft
from app.services.audit_service import AuditService
from app.services.claim_service import ClaimService
from app.services.detection_service import DetectionService
from app.services.event_service import EventService
from app.services.publish_service import PublishService
from app.services.research_service import ResearchService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_service import VerificationService
from app.services.writing_service import WritingService

B_URL = "https://b.test/seis-heridos"
C_URL = "https://c.test/transito"


def test_pipeline_fake_source_to_public_apis(db_session: Session) -> None:
    source_a = SourceService(db_session).create(
        SourceCreate(
            name="Fuente A",
            domain="a.test",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://a.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item_a = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source_a.id,
            url="https://a.test/choque",
            canonical_url="https://a.test/choque",
            content_hash="ha",
            title="Choque en Pellegrini",
            clean_text="Dos colectivos chocaron en Pellegrini y Corrientes.",
        )
    ).item

    detection_llm = FakeStructuredLLM(
        {
            "EventCandidate": EventCandidate(
                event_type="accidente",
                what_happened="Dos colectivos chocaron en Pellegrini y Corrientes",
                occurred_at=datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc),
                locality="Rosario",
                province="Santa Fe",
                short_summary="Choque de colectivos en Rosario",
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
    event.relevance_score = 85
    db_session.flush()

    research_llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["choque colectivos rosario"]),
            "RelevanceBatch": RelevanceBatch(hits=[RelevanceHit(url=B_URL, relevant=True)]),
        }
    )
    search = FakeSearchProvider(
        [SearchHit(title="Seis heridos", url=B_URL, snippet="El choque dejó seis heridos. Dos colectivos chocaron.")]
    )
    fetcher = RecordingFetcher(
        {
            B_URL: (
                "<article><p>El choque dejó seis heridos. Dos colectivos chocaron.</p></article>"
            )
        }
    )
    research = ResearchService(db_session, llm=research_llm, search=search, fetcher=fetcher).research(
        event.id, trigger="new_event"
    )
    assert research["skipped"] is False
    assert research["attached"] >= 1

    source_c = SourceService(db_session).create(
        SourceCreate(
            name="Fuente C",
            domain="c.test",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://c.test/rss.xml",
            is_monitored=False,
            is_enabled=True,
        )
    )
    item_c = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source_c.id,
            url=C_URL,
            canonical_url=C_URL,
            content_hash="hc",
            title="Tránsito cortado",
            clean_text="El tránsito permanece cortado.",
        )
    ).item
    EventService(db_session).attach_source(event, item_c.id, relation_type=EventSourceRelation.ADDITIONAL)

    claims_llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    ExtractedClaim(
                        canonical_text="Dos colectivos chocaron en Pellegrini y Corrientes",
                        claim_type="hecho",
                        importance=ClaimImportance.HIGH,
                        subject="colectivos",
                        predicate="chocaron",
                        object_text="Pellegrini y Corrientes",
                        evidence=[
                            ExtractedEvidence(
                                source_ref=1,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="Dos colectivos chocaron",
                            ),
                            ExtractedEvidence(
                                source_ref=2,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="Dos colectivos chocaron",
                            ),
                        ],
                    ),
                    ExtractedClaim(
                        canonical_text="El choque dejó seis heridos",
                        claim_type="hecho",
                        importance=ClaimImportance.HIGH,
                        subject="choque",
                        predicate="heridos",
                        normalized_value="6",
                        evidence=[
                            ExtractedEvidence(
                                source_ref=2,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="seis heridos",
                            )
                        ],
                    ),
                    ExtractedClaim(
                        canonical_text="El tránsito permanece cortado",
                        claim_type="hecho",
                        importance=ClaimImportance.HIGH,
                        subject="tránsito",
                        predicate="cortado",
                        evidence=[
                            ExtractedEvidence(
                                source_ref=3,
                                evidence_type=EvidenceType.SUPPORTS,
                                excerpt="tránsito permanece cortado",
                            )
                        ],
                    ),
                ]
            ),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[
                    ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, reason="dos fuentes"),
                    ClaimResolutionItem(claim_ref=2, status=ClaimStatus.SINGLE_SOURCE, reason="una fuente"),
                    ClaimResolutionItem(claim_ref=3, status=ClaimStatus.SINGLE_SOURCE, reason="una fuente"),
                ]
            ),
        }
    )
    claims = ClaimService(db_session, extractor_llm=claims_llm, resolver_llm=claims_llm).resolve(
        event.id, trigger="research"
    )
    assert claims["persisted"] == 3

    verify_llm = FakeStructuredLLM(
        {
            "VerificationResult": [
                VerificationResult(status=ClaimStatus.SINGLE_SOURCE, reason="sin extra"),
                VerificationResult(status=ClaimStatus.SINGLE_SOURCE, reason="sin extra"),
                VerificationResult(status=ClaimStatus.SINGLE_SOURCE, reason="sin extra"),
            ]
        }
    )
    verified = VerificationService(
        db_session, llm=verify_llm, search=FakeSearchProvider([]), fetcher=RecordingFetcher()
    ).verify(event.id, trigger="claims")
    assert verified.get("skipped") is False
    assert verified.get("error") is None

    draft = ArticleDraft(
        headline="Choque de colectivos en Pellegrini y Corrientes",
        summary="Dos unidades chocaron en Rosario. Hay heridos y el tránsito sigue cortado.",
        body=(
            "Dos colectivos chocaron en Pellegrini y Corrientes.\n\n"
            "El choque dejó seis heridos.\n\n"
            "El tránsito permanece cortado."
        ),
    )
    written = WritingService(db_session, llm=FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="verification"
    )
    assert written["written"] is True
    article = db_session.scalars(select(Article).where(Article.event_id == event.id)).one()
    assert article.status == ArticleStatus.DRAFT
    db_session.commit()

    with TestClient(app) as client:
        assert client.get(f"/api/v1/articles/{article.slug}").status_code == 404
        feed_before = client.get("/api/v1/feed")
        assert article.slug not in [item["slug"] for item in feed_before.json()["items"]]

    audited = AuditService(
        db_session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    ).audit(event.id, trigger="writing")
    assert audited["passed"] is True
    db_session.refresh(article)
    assert article.status == ArticleStatus.DRAFT

    published = PublishService(db_session).publish(event.id, trigger="audit")
    assert published["published"] is True
    db_session.refresh(article)
    db_session.refresh(event)
    db_session.commit()
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED

    events = db_session.scalar(select(func.count()).select_from(Event))
    items = db_session.scalar(select(func.count()).select_from(SourceItem))
    claims_count = db_session.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == event.id))
    links = db_session.scalar(select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id))
    assert events == 1
    assert items >= 3
    assert claims_count >= 1
    assert links >= 3

    with TestClient(app) as client:
        article_json = client.get(f"/api/v1/articles/{article.slug}")
        by_id = client.get(f"/api/v1/articles/{event.public_id}")
        feed = client.get("/api/v1/feed")
        live = client.get("/api/v1/live")
        now = client.get("/api/v1/now")
        local_ok = client.get("/api/v1/local", params={"locality": "Rosario"})
        local_other = client.get("/api/v1/local", params={"locality": "Córdoba"})
    assert article_json.status_code == 200
    assert "Pellegrini" in article_json.json()["headline"]
    assert by_id.status_code == 200
    slugs = lambda payload: {item["slug"] for item in payload.json()["items"]}
    assert article.slug in slugs(feed)
    assert article.slug in slugs(live)
    assert article.slug in {item["slug"] for item in now.json()["items"]}
    assert article.slug in slugs(local_ok)
    assert article.slug not in slugs(local_other)
