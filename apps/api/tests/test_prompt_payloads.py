from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.domain.enums import (
    ClaimImportance,
    ClaimStatus,
    EventSourceRelation,
    EvidenceType,
    SourceItemStatus,
)
from app.providers.base import SearchHit
from app.schemas.detection import EventCandidate
from app.services.article_context import _sources, _to_context_claim
from app.services.claim_service import ClaimService
from app.services.detection_service import DetectionService
from app.services.research_service import ResearchService


def test_relevance_prompt_omits_max_queries() -> None:
    svc = object.__new__(ResearchService)
    event = SimpleNamespace(
        title_internal="Choque",
        event_type="accidente",
        short_summary="Un colectivo chocó",
        locality="Rosario",
        province="Santa Fe",
        started_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        detected_at=None,
    )
    prompt = ResearchService._relevance_prompt(
        svc,
        event,
        [SearchHit(title="Nota", url="https://ejemplo.test/n", snippet="choque")],
    )
    assert "Máximo 0" not in prompt
    assert "Título interno: Choque" in prompt
    assert "https://ejemplo.test/n" in prompt


def test_numbered_sources_skips_failed_and_empty() -> None:
    svc = object.__new__(ClaimService)
    good = SimpleNamespace(
        processing_status=SourceItemStatus.PENDING,
        clean_text="Texto extraído de research con suficiente cuerpo.",
        excerpt=None,
    )
    failed = SimpleNamespace(
        processing_status=SourceItemStatus.FAILED,
        clean_text="Aunque tenga texto no debe entrar.",
        excerpt=None,
    )
    empty = SimpleNamespace(
        processing_status=SourceItemStatus.PENDING,
        clean_text=None,
        excerpt=None,
        title=None,
    )
    skipped = SimpleNamespace(
        processing_status=SourceItemStatus.SKIPPED,
        clean_text="Saltado por el gate.",
        excerpt=None,
        title=None,
    )
    title_only = SimpleNamespace(
        processing_status=SourceItemStatus.PENDING,
        clean_text=None,
        excerpt=None,
        title="Un colectivo chocó contra un auto en Pellegrini y Corrientes",
    )
    event = SimpleNamespace(
        event_sources=[
            SimpleNamespace(source_item=good, is_primary=True, added_at=None, source_item_id=uuid4()),
            SimpleNamespace(source_item=failed, is_primary=False, added_at=None, source_item_id=uuid4()),
            SimpleNamespace(source_item=empty, is_primary=False, added_at=None, source_item_id=uuid4()),
            SimpleNamespace(source_item=skipped, is_primary=False, added_at=None, source_item_id=uuid4()),
            SimpleNamespace(source_item=title_only, is_primary=False, added_at=None, source_item_id=uuid4()),
        ]
    )
    assert ClaimService._numbered_sources(svc, event) == [good]


def test_terra_dump_omits_editorial_fields() -> None:
    candidate = EventCandidate(
        event_type="accidente",
        what_happened="Un colectivo chocó",
        short_summary="Choque",
        locality="Rosario",
        province="Santa Fe",
        editorial_reason="noticia",
        location_confidence=0.9,
        latitude=None,
        longitude=None,
    )
    slim = candidate.model_dump_json(
        include={
            "event_type",
            "what_happened",
            "occurred_at",
            "province",
            "locality",
            "neighborhood",
            "address_text",
            "entities",
            "short_summary",
        }
    )
    assert "editorial_scope" not in slim
    assert "location_confidence" not in slim
    assert "Rosario" in slim
    assert DetectionService._ask_terra  # callable exists


def test_context_evidence_maps_source_ref() -> None:
    item_id = uuid4()
    claim = SimpleNamespace(
        id=uuid4(),
        canonical_text="Hay 6 heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="heridos",
        predicate="cantidad",
        object_text="6",
        normalized_value="6",
        unit=None,
        occurred_at=None,
        evidence=[
            SimpleNamespace(
                source_item_id=item_id,
                source_item=None,
                source_url="https://ejemplo.test/n",
                evidence_type=EvidenceType.SUPPORTS,
                excerpt="6 heridos",
            )
        ],
    )
    mapped = _to_context_claim(
        claim,
        excerpt_chars=400,
        item_id_to_ref={item_id: 3},
        url_to_ref={},
    )
    assert mapped.evidence[0].source_ref == 3
    assert mapped.evidence[0].excerpt == "6 heridos"
    assert "source_url" not in mapped.evidence[0].model_dump()


def test_context_sources_expose_ref_and_name() -> None:
    item_id = uuid4()
    item = SimpleNamespace(
        id=item_id,
        url="https://on24.com.ar/nota",
        canonical_url=None,
        title="Choque",
        source=SimpleNamespace(name="ON24", domain="on24.com.ar", is_monitored=True),
    )
    event = SimpleNamespace(
        event_sources=[
            SimpleNamespace(
                id=uuid4(),
                is_primary=True,
                source_item=item,
                relation_type=EventSourceRelation.INITIAL,
            )
        ]
    )
    rows, item_id_to_ref, url_to_ref = _sources(event, limit=20)
    assert rows[0].ref == 1
    assert rows[0].name == "ON24"
    assert rows[0].domain == "on24.com.ar"
    assert item_id_to_ref[item_id] == 1
    assert url_to_ref["https://on24.com.ar/nota"] == 1
