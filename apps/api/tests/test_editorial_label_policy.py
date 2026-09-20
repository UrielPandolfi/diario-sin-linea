from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.domain.enums import ClaimImportance, ClaimStatus, EditorialLabel, EvidenceType, IngestionMethod, PipelineStatus
from app.models import Claim, ClaimEvidence, PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult
from app.services.article_service import ArticleService
from app.services.audit_service import AuditService
from app.services.claim_service import CLAIM_STAGE
from app.services.editorial_label_policy import labels_for_event_claims
from app.services.event_service import EventService
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_outcome import VerificationView
from app.services.verification_service import VERIFICATION_STAGE
from tests.editorial_snapshot import persist_version_snapshot


def _publish_with_snapshot_decision(session: Session, *, hash_key: str, decision: dict | None) -> tuple:
    source = SourceService(session).create(
        SourceCreate(
            name=f"Fuente {hash_key}",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url=f"https://{hash_key}.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain=f"{hash_key}.test",
        )
    )
    item = SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url=f"https://{hash_key}.test/n",
            canonical_url=f"https://{hash_key}.test/n",
            content_hash=hash_key,
            title="Hecho",
            clean_text="Ocurrió el hecho.",
        )
    ).item
    event = EventService(session).create(
        EventCreate(
            title_internal="Hecho",
            event_type="judicial",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="CABA",
            province="CABA",
            short_summary="Hecho",
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text="Vital presentó una denuncia penal",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Vital",
        predicate="presentó",
        object_text="denuncia penal",
    )
    session.add(claim)
    session.flush()
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="presentó una denuncia penal",
            source_url=item.url,
        )
    )
    cid = str(claim.id)
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Según la fuente, Vital presentó una denuncia",
            summary="Una denuncia, según la primera cobertura.",
            body="Según la fuente, Vital presentó una denuncia penal.",
            body_blocks=[
                {
                    "type": "paragraph",
                    "segments": [
                        {
                            "text": "Según la fuente, Vital presentó una denuncia penal.",
                            "claim_ids": [cid],
                        }
                    ],
                }
            ],
        )
    )
    persist_version_snapshot(session, event, article)
    AuditService(session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})).audit(
        event.id, trigger="test"
    )
    published = PublishService(session).publish(event.id, trigger="test")
    assert published.get("published") is True
    snap = _overlay_published_snapshot(session, event, article, claim, decision)
    session.refresh(article)
    session.commit()
    return event, article, claim, snap


def _overlay_published_snapshot(session: Session, event, article, claim, decision: dict | None) -> dict:
    """Simula un snapshot histórico ya publicado. C5 no despublica por metadata nueva ausente."""
    cid = str(claim.id)
    runs = list(
        session.scalars(
            select(PipelineRun)
            .where(PipelineRun.event_id == event.id)
            .order_by(PipelineRun.started_at.desc())
        )
    )
    target = int(article.published_version or article.current_version)
    last_snap: dict = {}
    for run in runs:
        meta = dict(run.metadata_json or {})
        raw = meta.get("evidence_snapshot")
        if not isinstance(raw, dict):
            continue
        bound = raw.get("version")
        version_after = meta.get("version_after")
        if bound is None and version_after is None and meta.get("version") is None:
            continue
        matches = False
        if bound is not None and int(bound) == target:
            matches = True
        if version_after is not None and int(version_after) == target:
            matches = True
        if meta.get("version") is not None and int(meta["version"]) == target:
            matches = True
        if not matches:
            continue
        snap = dict(raw)
        if decision is None:
            snap["decision_by_claim_id"] = {}
            context = snap.get("article_context") if isinstance(snap.get("article_context"), dict) else {}
            verification = context.get("verification") if isinstance(context.get("verification"), dict) else {}
            verification["decision_by_claim_id"] = {}
            context["verification"] = verification
            snap["article_context"] = context
        else:
            row = {"claim_id": cid, **decision}
            snap["decision_by_claim_id"] = {cid: row}
            context = snap.get("article_context") or {}
            for key in (
                "confirmed_claims",
                "single_source_claims",
                "conflicting_claims",
                "uncertain_claims",
                "disproven_claims",
                "outdated_claims",
            ):
                for item_row in context.get(key) or []:
                    if str(item_row.get("id")) == cid:
                        if decision.get("status"):
                            item_row["status"] = decision["status"]
                        if "support_basis" in decision:
                            item_row["support_basis"] = decision["support_basis"]
                        item_row["canonical_text"] = claim.canonical_text
            snap["article_context"] = context
        meta["evidence_snapshot"] = snap
        meta["decision_by_claim_id"] = snap.get("decision_by_claim_id") or {}
        run.metadata_json = meta
        flag_modified(run, "metadata_json")
        last_snap = snap
    session.flush()
    return last_snap


def _later_live_supported(session: Session, event, claim) -> None:
    cid = str(claim.id)
    claim.status = ClaimStatus.SUPPORTED
    session.flush()
    claim_run = session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event.id, PipelineRun.stage == CLAIM_STAGE)
        .order_by(PipelineRun.started_at.desc())
    ).first()
    fingerprint = (claim_run.metadata_json or {}).get("claims_fingerprint")
    session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "claims_fingerprint": fingerprint,
                "based_on_claim_run_id": str(claim_run.id),
                "selected": [{"claim_id": cid, "reasons": ["policy:hecho"]}],
                "skipped_search": [],
                "primary_source_supports_claim": {cid: True},
                "sol": [{"claim_id": cid, "status_after": "SUPPORTED", "unresolved": False}],
                "decision_by_claim_id": {
                    cid: {
                        "claim_id": cid,
                        "status": ClaimStatus.SUPPORTED.value,
                        "unresolved": False,
                        "evaluation_state": "complete",
                        "support_basis": {
                            "known_independent_count": 2,
                            "unknown_group_count": 0,
                            "documents_consulted": 3,
                            "documents_supporting": 2,
                            "demotion": "none",
                            "kind": "independent_reporting",
                            "primary_access": "found_relevant",
                        },
                    }
                },
            },
        )
    )
    session.flush()


def _claim(**overrides):
    payload = {
        "id": uuid4(),
        "canonical_text": "El hecho ocurrió",
        "status": ClaimStatus.SUPPORTED,
        "subject": "decreto",
        "predicate": "elimina",
        "object_text": "X",
        "normalized_value": "si",
        "unit": None,
        "occurred_at": None,
        "evidence": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _evidence(*, evidence_type: EvidenceType, excerpt: str | None, source_name: str = "Medio", url: str = "https://medio.test/n"):
    source_item_id = uuid4()
    return SimpleNamespace(
        evidence_type=evidence_type,
        excerpt=excerpt,
        source_item_id=source_item_id,
        source_url=url,
        source_item=SimpleNamespace(
            url=url,
            source=SimpleNamespace(name=source_name, domain="medio.test"),
        ),
    )


def _view_for(claim, *, primary: bool = True, skipped: bool = False, unresolved: bool = False, selected: bool = True) -> VerificationView:
    cid = str(claim.id)
    return VerificationView(
        selected_ids={cid} if selected else set(),
        skipped_search={cid} if skipped else set(),
        primary_source_supports={cid: primary},
        sol_by_id={
            cid: {
                "claim_id": cid,
                "status_after": claim.status.value,
                "unresolved": unresolved,
            }
        },
    )


def _labels(claim, mapping):
    return [label.value for label in mapping[str(claim.id)].labels]


def test_case_a_two_supports_without_verification() -> None:
    a = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="A", url="https://a.test/n")
    b = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="B", url="https://b.test/n")
    claim = _claim(evidence=[a, b])
    mapping = labels_for_event_claims([claim], VerificationView())
    assert _labels(claim, mapping) == []
    assert mapping[str(claim.id)].false_assertions == []


def test_case_b_checked_requires_real_verification() -> None:
    a = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="A")
    b = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="B")
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=[a, b])
    mapping = labels_for_event_claims([claim], _view_for(claim, primary=True))
    assert _labels(claim, mapping) == [EditorialLabel.CHECKED.value]


def test_preferred_url_without_primary_flag_is_not_checked() -> None:
    official = _evidence(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="boletin",
        source_name="Boletín",
        url="https://www.boletinoficial.gob.ar/detalle/1",
    )
    claim = _claim(evidence=[official])
    mapping = labels_for_event_claims([claim], _view_for(claim, primary=False))
    assert EditorialLabel.CHECKED.value not in _labels(claim, mapping)


def test_skipped_search_is_not_checked() -> None:
    claim = _claim(evidence=[_evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="ok")])
    mapping = labels_for_event_claims([claim], _view_for(claim, skipped=True, primary=True))
    assert _labels(claim, mapping) == []


def test_case_c_resolved_discrepancy() -> None:
    winner_ev = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="no elimina", source_name="Página/12")
    loser_ev = _evidence(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="El decreto elimina X",
        source_name="Derecha Diario",
        url="https://derecha.test/n",
    )
    winner = _claim(
        status=ClaimStatus.SUPPORTED,
        object_text="no X",
        normalized_value="no",
        canonical_text="El decreto no elimina X",
        evidence=[winner_ev],
    )
    loser = _claim(
        status=ClaimStatus.DISPROVEN,
        object_text="X",
        normalized_value="si",
        canonical_text="El decreto elimina X",
        evidence=[loser_ev],
    )
    view = _view_for(winner, primary=True)
    mapping = labels_for_event_claims([winner, loser], view)
    assert _labels(winner, mapping) == [EditorialLabel.CHECKED.value, EditorialLabel.DISCREPANCY.value]
    assert _labels(loser, mapping) == [EditorialLabel.DISCREPANCY.value, EditorialLabel.FALSE_CLAIM.value]
    assert mapping[str(winner.id)].false_assertions == [
        {
            "source_item_id": str(loser_ev.source_item_id),
            "source_name": "Derecha Diario",
            "source_url": "https://derecha.test/n",
            "excerpt": "El decreto elimina X",
        }
    ]
    assert mapping[str(loser.id)].false_assertions == []


def test_case_d_disputed_when_unresolved() -> None:
    supports = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="si")
    contradicts = _evidence(evidence_type=EvidenceType.CONTRADICTS, excerpt="no")
    claim = _claim(status=ClaimStatus.CONFLICTING, evidence=[supports, contradicts])
    view = _view_for(claim, unresolved=True, primary=False)
    mapping = labels_for_event_claims([claim], view)
    assert _labels(claim, mapping) == [EditorialLabel.DISCREPANCY.value, EditorialLabel.DISPUTED.value]


def test_contradicts_without_disproven_sibling_is_not_false_claim() -> None:
    supports = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="si")
    contradicts = _evidence(evidence_type=EvidenceType.CONTRADICTS, excerpt="no")
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=[supports, contradicts])
    mapping = labels_for_event_claims([claim], _view_for(claim, primary=True))
    assert _labels(claim, mapping) == [EditorialLabel.CHECKED.value, EditorialLabel.DISCREPANCY.value]
    assert mapping[str(claim.id)].false_assertions == []


def test_qualifies_does_not_create_discrepancy() -> None:
    supports = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="si")
    qualifies = _evidence(evidence_type=EvidenceType.QUALIFIES, excerpt="en parte")
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=[supports, qualifies])
    mapping = labels_for_event_claims([claim], VerificationView())
    assert _labels(claim, mapping) == []


def test_case_f_temporal_update_is_not_false_or_discrepancy() -> None:
    from datetime import datetime, timezone

    at_10 = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
    at_14 = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
    earlier = _claim(
        status=ClaimStatus.OUTDATED,
        normalized_value="3",
        object_text="3",
        subject="accidente",
        predicate="cantidad_heridos",
        unit="personas",
        occurred_at=at_10,
        canonical_text="Hay 3 heridos",
        evidence=[_evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="3 heridos")],
    )
    later = _claim(
        status=ClaimStatus.SINGLE_SOURCE,
        normalized_value="5",
        object_text="5",
        subject="accidente",
        predicate="cantidad_heridos",
        unit="personas",
        occurred_at=at_14,
        canonical_text="Hay 5 heridos",
        evidence=[_evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="5 heridos")],
    )
    mapping = labels_for_event_claims([earlier, later], VerificationView())
    assert _labels(earlier, mapping) == []
    assert _labels(later, mapping) == []
    assert mapping[str(later.id)].false_assertions == []


def test_compact_public_claims_includes_editorial_payload(db_session: Session) -> None:
    from app.domain.enums import ClaimImportance, IngestionMethod
    from app.models import Claim, ClaimEvidence, PipelineRun
    from app.schemas import EventCreate, SourceCreate, SourceItemCreate
    from app.services.event_service import EventService
    from app.services.feed_ranking import compact_public_claims
    from app.services.source_item_service import SourceItemService
    from app.services.source_service import SourceService
    from app.services.verification_service import VERIFICATION_STAGE
    from app.domain.enums import PipelineStatus

    source = SourceService(db_session).create(
        SourceCreate(
            name="Oficial",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://oficial.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain="oficial.test",
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://oficial.test/n",
            canonical_url="https://oficial.test/n",
            content_hash="ed1",
            title="Decreto",
            clean_text="El decreto no elimina X",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Decreto",
            event_type="anuncio_oficial",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="CABA",
            province="CABA",
            short_summary="Decreto",
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text="El decreto no elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="decreto",
        predicate="elimina",
        object_text="no X",
        normalized_value="no",
    )
    db_session.add(claim)
    db_session.flush()
    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="El decreto no elimina X",
            source_url=item.url,
        )
    )
    cid = str(claim.id)
    from app.services.claim_coverage import claims_fingerprint
    from app.services.claim_service import CLAIM_STAGE

    fingerprint = claims_fingerprint([claim])
    claim_run = PipelineRun(
        event_id=event.id,
        stage=CLAIM_STAGE,
        status=PipelineStatus.SUCCESS,
        finished_at=datetime.now(timezone.utc),
        metadata_json={"claims_fingerprint": fingerprint, "coverage": {"coverage_gap": False}},
    )
    db_session.add(claim_run)
    db_session.flush()
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "claims_fingerprint": fingerprint,
                "based_on_claim_run_id": str(claim_run.id),
                "selected": [{"claim_id": cid, "reasons": ["policy:documento"]}],
                "skipped_search": [],
                "primary_source_supports_claim": {cid: True},
                "sol": [
                    {
                        "claim_id": cid,
                        "status_after": "SUPPORTED",
                        "unresolved": False,
                        "reason": "primaria",
                        "llm_reason": "varias fuentes independientes confirman",
                    }
                ],
                "decision_by_claim_id": {
                    cid: {
                        "claim_id": cid,
                        "status": "SUPPORTED",
                        "unresolved": False,
                        "llm_reason": "varias fuentes independientes confirman",
                        "support_basis": {
                            "known_independent_count": 2,
                            "unknown_group_count": 0,
                            "documents_consulted": 1,
                            "documents_supporting": 1,
                            "demotion": "none",
                        },
                    }
                },
            },
        )
    )
    db_session.flush()
    rows = compact_public_claims(db_session, event)
    from app.services.claim_card_presentation import contains_llm_reason

    assert rows[0]["editorial_labels"] == ["CHECKED"]
    assert rows[0]["false_assertions"] == []
    assert "llm_reason" not in (rows[0].get("verification") or {})
    assert rows[0]["verification"] is None or "reason" not in (rows[0]["verification"] or {})
    assert not contains_llm_reason(rows)
    assert rows[0]["presentation"]["verification_label"] == "Confirmado"
    assert rows[0]["presentation"]["basis_known"] is True


def test_public_claims_freeze_presentation_and_labels_to_published_snapshot(db_session: Session) -> None:
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from app.domain.enums import ClaimImportance, IngestionMethod, PipelineStatus
    from app.main import app
    from app.models import Claim, ClaimEvidence, PipelineRun
    from app.providers.fakes import FakeStructuredLLM
    from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
    from app.schemas.auditing import ArticleAuditResult
    from app.schemas.editorial_evidence import Demotion, ReasonCode, SupportKind
    from app.services.article_service import ArticleService
    from app.services.audit_service import AuditService
    from app.services.claim_coverage import claims_fingerprint
    from app.services.claim_service import CLAIM_STAGE
    from app.services.event_service import EventService
    from app.services.feed_ranking import compact_public_claims
    from app.services.publish_service import PublishService
    from app.services.source_item_service import SourceItemService
    from app.services.source_service import SourceService
    from app.services.verification_service import VERIFICATION_STAGE
    from tests.editorial_snapshot import persist_version_snapshot

    source = SourceService(db_session).create(
        SourceCreate(
            name="Oficial",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://v1.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain="v1.test",
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://v1.test/n",
            canonical_url="https://v1.test/n",
            content_hash="v1c2",
            title="Denuncia",
            clean_text="Presentó una denuncia penal.",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Denuncia",
            event_type="judicial",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="CABA",
            province="CABA",
            short_summary="Denuncia",
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text="Vital presentó una denuncia penal",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Vital",
        predicate="presentó",
        object_text="denuncia penal",
    )
    db_session.add(claim)
    db_session.flush()
    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="presentó una denuncia penal",
            source_url=item.url,
        )
    )
    cid = str(claim.id)
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Según la fuente, Vital presentó una denuncia",
            summary="Una denuncia, según la primera cobertura.",
            body="Según la fuente, Vital presentó una denuncia penal.",
            body_blocks=[
                {
                    "type": "paragraph",
                    "segments": [
                        {
                            "text": "Según la fuente, Vital presentó una denuncia penal.",
                            "claim_ids": [cid],
                        }
                    ],
                }
            ],
        )
    )
    persist_version_snapshot(db_session, event, article)
    writing = db_session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event.id, PipelineRun.stage == "writing")
        .order_by(PipelineRun.started_at.desc())
    ).first()
    assert writing is not None
    snap = dict(writing.metadata_json["evidence_snapshot"])
    v1_decision = {
        "claim_id": cid,
        "status": ClaimStatus.SINGLE_SOURCE.value,
        "unresolved": False,
        "evaluation_state": "complete",
        "llm_reason": None,
        "reason_code": ReasonCode.SINGLE_KNOWN_ORIGIN.value,
        "final_reason": "Un origen informativo conocido no alcanza para corroboración independiente (SINGLE_SOURCE).",
        "verified_scope": "Vital presentó una denuncia",
        "unsupported_scope": "penal",
        "public_rendering": {
            "attribution_required": True,
            "categorical_allowed": False,
            "headline_unattributed_allowed": False,
            "independent_confirmation_language_allowed": False,
        },
        "support_basis": {
            "known_independent_count": 1,
            "unknown_group_count": 0,
            "documents_consulted": 1,
            "documents_supporting": 1,
            "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
            "kind": SupportKind.SINGLE_REPORT.value,
        },
    }
    snap["decision_by_claim_id"] = {cid: v1_decision}
    context = snap.get("article_context") or {}
    for key in (
        "confirmed_claims",
        "single_source_claims",
        "conflicting_claims",
        "uncertain_claims",
        "disproven_claims",
        "outdated_claims",
    ):
        for row in context.get(key) or []:
            if str(row.get("id")) == cid:
                row["status"] = ClaimStatus.SINGLE_SOURCE.value
                row["canonical_text"] = claim.canonical_text
                row["support_basis"] = v1_decision["support_basis"]
    writing.metadata_json = {**writing.metadata_json, "evidence_snapshot": snap, "decision_by_claim_id": snap["decision_by_claim_id"]}
    flag_modified(writing, "metadata_json")
    db_session.flush()
    AuditService(db_session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})).audit(
        event.id, trigger="test"
    )
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published.get("published") is True
    db_session.refresh(article)
    db_session.commit()

    v1_public = compact_public_claims(db_session, event, freeze_to_version=1)
    assert len(v1_public) == 1
    assert v1_public[0]["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert v1_public[0]["presentation"]["verification_label"] == "Respaldo limitado"
    assert v1_public[0]["presentation"]["known_independent_count"] == 1
    assert "CHECKED" not in v1_public[0]["editorial_labels"]
    assert v1_public[0]["reason_code"] == ReasonCode.SINGLE_KNOWN_ORIGIN.value
    assert v1_public[0]["verified_scope"] == "Vital presentó una denuncia"
    assert v1_public[0]["unsupported_scope"] == "penal"
    assert v1_public[0]["public_rendering"]["categorical_allowed"] is False
    assert v1_public[0]["public_rendering"]["headline_unattributed_allowed"] is False
    assert v1_public[0]["public_rendering"]["independent_confirmation_language_allowed"] is False

    claim.status = ClaimStatus.SUPPORTED
    db_session.flush()
    extra = Claim(
        event_id=event.id,
        canonical_text="El expediente ya tiene fecha de audiencia",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    db_session.add(extra)
    db_session.flush()
    claim_run = db_session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event.id, PipelineRun.stage == CLAIM_STAGE)
        .order_by(PipelineRun.started_at.desc())
    ).first()
    fingerprint = (claim_run.metadata_json or {}).get("claims_fingerprint") or claims_fingerprint([claim])
    later_decision = {
        "claim_id": cid,
        "status": ClaimStatus.SUPPORTED.value,
        "unresolved": False,
        "evaluation_state": "complete",
        "reason_code": ReasonCode.INDEPENDENT_CORROBORATION.value,
        "final_reason": "2 coberturas periodísticas independientes sostienen la proposición.",
        "verified_scope": claim.canonical_text,
        "unsupported_scope": None,
        "public_rendering": {
            "attribution_required": False,
            "categorical_allowed": True,
            "headline_unattributed_allowed": True,
            "independent_confirmation_language_allowed": True,
        },
        "support_basis": {
            "known_independent_count": 2,
            "unknown_group_count": 0,
            "documents_consulted": 3,
            "documents_supporting": 2,
            "demotion": Demotion.NONE.value,
            "kind": SupportKind.INDEPENDENT_REPORTING.value,
            "primary_access": "found_relevant",
        },
    }
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "claims_fingerprint": fingerprint,
                "based_on_claim_run_id": str(claim_run.id),
                "selected": [{"claim_id": cid, "reasons": ["policy:hecho"]}],
                "skipped_search": [],
                "primary_source_supports_claim": {cid: True},
                "sol": [{"claim_id": cid, "status_after": "SUPPORTED", "unresolved": False}],
                "decision_by_claim_id": {cid: later_decision},
            },
        )
    )
    db_session.flush()

    live_rows = compact_public_claims(db_session, event)
    live_main = next(row for row in live_rows if row["id"] == cid)
    assert live_main["status"] == ClaimStatus.SUPPORTED.value
    assert live_main["presentation"]["verification_label"] == "Confirmado"
    assert live_main["presentation"]["known_independent_count"] == 2
    assert "CHECKED" in live_main["editorial_labels"]
    assert live_main["reason_code"] == ReasonCode.INDEPENDENT_CORROBORATION.value
    assert live_main["verified_scope"] == claim.canonical_text
    assert live_main["unsupported_scope"] is None
    assert live_main["public_rendering"]["categorical_allowed"] is True
    assert live_main["public_rendering"]["independent_confirmation_language_allowed"] is True

    frozen = compact_public_claims(db_session, event, freeze_to_version=1)
    assert {row["id"] for row in frozen} == {cid}
    assert str(extra.id) not in {row["id"] for row in frozen}
    assert frozen[0]["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert frozen[0]["presentation"]["verification_label"] == "Respaldo limitado"
    assert frozen[0]["presentation"]["known_independent_count"] == 1
    assert frozen[0]["presentation"]["explanation"] != live_main["presentation"]["explanation"]
    assert "CHECKED" not in frozen[0]["editorial_labels"]
    assert frozen[0]["reason_code"] == ReasonCode.SINGLE_KNOWN_ORIGIN.value
    assert frozen[0]["verified_scope"] == "Vital presentó una denuncia"
    assert frozen[0]["unsupported_scope"] == "penal"
    assert frozen[0]["public_rendering"]["categorical_allowed"] is False
    assert frozen[0]["public_rendering"]["independent_confirmation_language_allowed"] is False
    db_session.commit()

    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
    assert payload["published_version"] == 1
    public_ids = {row["id"] for row in payload["claims"]}
    assert public_ids == {cid}
    public_row = payload["claims"][0]
    assert public_row["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert public_row["presentation"]["verification_label"] == "Respaldo limitado"
    assert public_row["presentation"]["known_independent_count"] == 1
    assert "CHECKED" not in public_row["editorial_labels"]
    assert public_row["reason_code"] == ReasonCode.SINGLE_KNOWN_ORIGIN.value
    assert public_row["verified_scope"] == "Vital presentó una denuncia"
    assert public_row["unsupported_scope"] == "penal"
    assert public_row["public_rendering"]["categorical_allowed"] is False
    assert public_row["public_rendering"]["independent_confirmation_language_allowed"] is False

    from app.domain.enums import ArticleStatus
    from app.models import ArticleVersion

    v2_blocks = [
        {
            "type": "paragraph",
            "segments": [{"text": "Vital presentó una denuncia penal.", "claim_ids": [cid]}],
        }
    ]
    article.status = ArticleStatus.DRAFT
    article.current_version = 2
    article.headline = "Corroborado: Vital presentó una denuncia"
    article.summary = "Dos coberturas independientes."
    article.body = "Vital presentó una denuncia penal."
    article.body_blocks = v2_blocks
    db_session.add(
        ArticleVersion(
            article_id=article.id,
            version_number=2,
            headline=article.headline,
            summary=article.summary,
            body=article.body,
            body_blocks=v2_blocks,
            change_reason="test_v2",
        )
    )
    db_session.flush()
    coverage = snap.get("coverage") or {
        "coverage_gap": False,
        "expected_central": [
            {
                "proposition": claim.canonical_text,
                "role": "other",
                "match": "equivalent",
                "match_claim_id": cid,
            }
        ],
    }
    v2_snap = {
        "contract_version": "editorial-evidence-1",
        "version": 2,
        "claims_fingerprint": fingerprint,
        "coverage_run_id": str(claim_run.id),
        "based_on_claim_run_id": str(claim_run.id),
        "verification_run_id": "v2-verify",
        "coverage": coverage,
        "verification_incomplete": False,
        "central_unverified": [],
        "stale_verification": False,
        "decision_by_claim_id": {cid: later_decision},
        "evaluated_claims": [{"claim_id": cid, "canonical_text": claim.canonical_text, "status": "SUPPORTED"}],
        "article_context": {
            "confirmed_claims": [
                {
                    "id": cid,
                    "canonical_text": claim.canonical_text,
                    "status": ClaimStatus.SUPPORTED.value,
                    "importance": "HIGH",
                    "support_basis": later_decision["support_basis"],
                    "evidence": [],
                }
            ],
            "verification": {
                "selected": [{"claim_id": cid}],
                "sol": [{"claim_id": cid, "status_after": "SUPPORTED", "unresolved": False}],
                "claims_fingerprint": fingerprint,
                "based_on_claim_run_id": str(claim_run.id),
                "verification_run_id": "v2-verify",
            },
        },
    }
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage="writing",
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={"written": True, "version": 2, "evidence_snapshot": v2_snap, **v2_snap},
        )
    )
    db_session.flush()
    still_v1 = compact_public_claims(db_session, event, freeze_to_version=1)
    assert still_v1[0]["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert still_v1[0]["presentation"]["verification_label"] == "Respaldo limitado"
    with TestClient(app) as client:
        before_v2 = client.get(f"/api/v1/articles/{article.slug}").json()
    assert before_v2["published_version"] == 1
    assert before_v2["claims"][0]["presentation"]["verification_label"] == "Respaldo limitado"
    assert before_v2["claims"][0]["reason_code"] == ReasonCode.SINGLE_KNOWN_ORIGIN.value
    assert before_v2["claims"][0]["public_rendering"]["categorical_allowed"] is False
    assert still_v1[0]["public_rendering"]["categorical_allowed"] is False

    AuditService(db_session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})).audit(
        event.id, trigger="test"
    )
    published_v2 = PublishService(db_session).publish(event.id, trigger="test")
    assert published_v2.get("published") is True
    db_session.refresh(article)
    db_session.commit()
    v2_rows = compact_public_claims(db_session, event, freeze_to_version=2)
    assert v2_rows[0]["status"] == ClaimStatus.SUPPORTED.value
    assert v2_rows[0]["presentation"]["verification_label"] == "Confirmado"
    assert v2_rows[0]["presentation"]["known_independent_count"] == 2
    assert "CHECKED" in v2_rows[0]["editorial_labels"]
    assert v2_rows[0]["reason_code"] == ReasonCode.INDEPENDENT_CORROBORATION.value
    assert v2_rows[0]["verified_scope"] == claim.canonical_text
    assert v2_rows[0]["unsupported_scope"] is None
    assert v2_rows[0]["public_rendering"]["categorical_allowed"] is True
    assert v2_rows[0]["public_rendering"]["independent_confirmation_language_allowed"] is True
    with TestClient(app) as client:
        after_v2 = client.get(f"/api/v1/articles/{article.slug}").json()
    assert after_v2["published_version"] == 2
    assert after_v2["claims"][0]["status"] == ClaimStatus.SUPPORTED.value
    assert after_v2["claims"][0]["presentation"]["verification_label"] == "Confirmado"
    assert after_v2["claims"][0]["presentation"]["known_independent_count"] == 2
    assert "CHECKED" in after_v2["claims"][0]["editorial_labels"]
    assert after_v2["claims"][0]["reason_code"] == ReasonCode.INDEPENDENT_CORROBORATION.value
    assert after_v2["claims"][0]["verified_scope"] == claim.canonical_text
    assert after_v2["claims"][0]["unsupported_scope"] is None
    assert after_v2["claims"][0]["public_rendering"]["categorical_allowed"] is True
    assert after_v2["claims"][0]["public_rendering"]["independent_confirmation_language_allowed"] is True


def test_frozen_v1_skipped_stays_unevaluated_after_later_complete(db_session: Session) -> None:
    from app.services.claim_card_presentation import NOT_EVALUATED_LABEL
    from app.services.feed_ranking import compact_public_claims
    from app.schemas.editorial_evidence import evaluation_is_complete, read_evaluation_state

    event, article, claim, snap = _publish_with_snapshot_decision(
        db_session,
        hash_key="c2skip",
        decision={
            "status": ClaimStatus.SINGLE_SOURCE.value,
            "unresolved": False,
            "evaluation_state": "skipped",
            "llm_reason": "policy_skip",
            "support_basis": {},
        },
    )
    cid = str(claim.id)
    v1 = compact_public_claims(db_session, event, freeze_to_version=1)
    assert v1[0]["presentation"]["verification_label"] == NOT_EVALUATED_LABEL
    _later_live_supported(db_session, event, claim)
    live = compact_public_claims(db_session, event)
    live_row = next(row for row in live if row["id"] == cid)
    assert live_row["presentation"]["verification_label"] == "Confirmado"
    frozen = compact_public_claims(db_session, event, freeze_to_version=1)
    assert frozen[0]["presentation"]["verification_label"] == NOT_EVALUATED_LABEL
    assert frozen[0]["presentation"]["explanation"]
    assert "no se evaluó" in frozen[0]["presentation"]["explanation"].casefold()
    assert frozen[0]["presentation"]["verification_label"] != "No confirmado"
    assert "CHECKED" not in frozen[0]["editorial_labels"]
    assert frozen[0]["reason_code"] is None
    assert frozen[0]["verified_scope"] is None
    assert frozen[0]["unsupported_scope"] is None
    stored = snap["decision_by_claim_id"][cid]
    assert frozen[0]["public_rendering"] is None
    assert read_evaluation_state(stored) is not None
    assert evaluation_is_complete(stored) is False


def test_frozen_legacy_decision_without_evaluation_state_keeps_evaluated_copy(db_session: Session) -> None:
    from app.schemas.editorial_evidence import (
        Demotion,
        decision_was_evaluated,
        evaluation_is_complete,
        read_evaluation_state,
    )
    from app.services.feed_ranking import compact_public_claims

    event, article, claim, snap = _publish_with_snapshot_decision(
        db_session,
        hash_key="c2legacy",
        decision={
            "status": ClaimStatus.SINGLE_SOURCE.value,
            "unresolved": False,
            "llm_reason": None,
            "support_basis": {
                "known_independent_count": 0,
                "unknown_group_count": 2,
                "documents_consulted": 3,
                "documents_supporting": 3,
                "demotion": Demotion.UNPROVEN_INDEPENDENCE.value,
                "kind": "single_report",
            },
        },
    )
    cid = str(claim.id)
    stored = snap["decision_by_claim_id"][cid]
    assert "evaluation_state" not in stored
    assert read_evaluation_state(stored) is None
    assert evaluation_is_complete(stored) is False
    assert decision_was_evaluated(stored) is True
    v1 = compact_public_claims(db_session, event, freeze_to_version=1)
    assert v1[0]["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert v1[0]["presentation"]["verification_label"] == "Respaldo limitado"
    _later_live_supported(db_session, event, claim)
    live = compact_public_claims(db_session, event)
    live_row = next(row for row in live if row["id"] == cid)
    assert live_row["presentation"]["verification_label"] == "Confirmado"
    frozen = compact_public_claims(db_session, event, freeze_to_version=1)
    assert frozen[0]["presentation"]["verification_label"] == "Respaldo limitado"
    assert frozen[0]["presentation"]["known_independent_count"] == 0
    assert frozen[0]["editorial_labels"] == v1[0]["editorial_labels"]
    assert frozen[0]["reason_code"] is None
    assert frozen[0]["verified_scope"] is None
    assert frozen[0]["unsupported_scope"] is None
    assert frozen[0]["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert frozen[0]["public_rendering"] is None


def test_frozen_missing_decision_is_not_filled_from_live_verify(db_session: Session) -> None:
    from app.services.claim_card_presentation import NOT_EVALUATED_LABEL
    from app.services.feed_ranking import compact_public_claims

    event, article, claim, _snap = _publish_with_snapshot_decision(
        db_session,
        hash_key="c2nodec",
        decision=None,
    )
    cid = str(claim.id)
    v1 = compact_public_claims(db_session, event, freeze_to_version=1)
    assert v1[0]["presentation"]["verification_label"] == NOT_EVALUATED_LABEL
    _later_live_supported(db_session, event, claim)
    live = compact_public_claims(db_session, event)
    live_row = next(row for row in live if row["id"] == cid)
    assert live_row["presentation"]["verification_label"] == "Confirmado"
    frozen = compact_public_claims(db_session, event, freeze_to_version=1)
    assert frozen[0]["id"] == cid
    assert frozen[0]["presentation"]["verification_label"] == NOT_EVALUATED_LABEL
    assert frozen[0]["presentation"]["explanation"]
    assert "información suficiente" in frozen[0]["presentation"]["explanation"].casefold()
    assert "CHECKED" not in frozen[0]["editorial_labels"]
    assert frozen[0]["reason_code"] is None
    assert frozen[0]["verified_scope"] is None
    assert frozen[0]["unsupported_scope"] is None
    assert frozen[0]["public_rendering"] is None
