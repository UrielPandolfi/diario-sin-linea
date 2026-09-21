from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ArticleStatus, ClaimImportance, ClaimStatus, EvidenceType
from app.main import app
from app.models import ClaimEvidence, PipelineRun
from app.schemas import ArticleContentUpdate
from app.schemas.auditing import AuditIssueReason
from app.services.article_service import ArticleService
from app.services.audit_policy import structural_blocks_rewrite, structural_findings
from app.services.evidence_snapshot import evidence_snapshot_for_version
from app.services.publish_service import PublishService
from app.services.surface_validation import (
    classify_link,
    signals_independent_confirmation_language,
    surface_validation_findings,
)
from tests.editorial_snapshot import persist_version_snapshot
from tests.test_audit import _claim, _pass_audit
from tests.test_writing_certainty import _audit, _seed

_RESTRICTED = {
    "attribution_required": True,
    "categorical_allowed": False,
    "headline_unattributed_allowed": False,
    "independent_confirmation_language_allowed": False,
}
_OPEN = {
    "attribution_required": False,
    "categorical_allowed": True,
    "headline_unattributed_allowed": True,
    "independent_confirmation_language_allowed": True,
}
_UTTERANCE = {
    "attribution_required": True,
    "categorical_allowed": True,
    "headline_unattributed_allowed": False,
    "independent_confirmation_language_allowed": False,
}


def _article(*, headline: str, summary: str = "", body: str = "", body_blocks=None):
    return SimpleNamespace(headline=headline, summary=summary, body=body, body_blocks=body_blocks)


def _decision(cid: str, *, status: str, rendering: dict | None, state: str = "complete", role: str = "other"):
    return {
        "claim_id": cid,
        "status": status,
        "unresolved": False,
        "proposition_role": role,
        "evaluation_state": state,
        "public_rendering": rendering,
    }


def _snapshot(claims: list[dict], decisions: dict[str, dict]) -> dict:
    evaluated = []
    buckets = {
        "confirmed_claims": [],
        "single_source_claims": [],
        "conflicting_claims": [],
        "uncertain_claims": [],
        "disproven_claims": [],
        "outdated_claims": [],
    }
    for claim in claims:
        row = dict(claim)
        cid = str(row["id"])
        row["claim_id"] = cid
        evaluated.append(row)
        status = str(row.get("status") or "")
        if status == "SUPPORTED":
            buckets["confirmed_claims"].append(row)
        elif status == "SINGLE_SOURCE":
            buckets["single_source_claims"].append(row)
        elif status == "CONFLICTING":
            buckets["conflicting_claims"].append(row)
        elif status == "DISPROVEN":
            buckets["disproven_claims"].append(row)
        else:
            buckets["uncertain_claims"].append(row)
    return {
        "evaluated_claims": evaluated,
        "decision_by_claim_id": decisions,
        "article_context": buckets,
        "claims_fingerprint": "fp-c5",
        "verification_run_id": "v1",
        "based_on_claim_run_id": "c1",
        "coverage_run_id": "c1",
        "coverage": {"coverage_gap": False, "expected_central": []},
    }


def _reasons(issues) -> set[str]:
    out: set[str] = set()
    for issue in issues:
        reason = issue.reason if hasattr(issue, "reason") else issue.get("reason")
        if reason is None:
            continue
        out.add(reason.value if hasattr(reason, "value") else str(reason))
    return out


def _issue_key(issue) -> tuple:
    if hasattr(issue, "reason"):
        return (issue.reason, issue.claim_ref, issue.claim_id, issue.text)
    return (issue.get("reason"), issue.get("claim_ref"), issue.get("claim_id"), issue.get("text"))


def test_classify_link_requires_equivalence_not_shared_name() -> None:
    claim = {"id": "c1", "canonical_text": "Recalde es dueño del 1° A."}
    assert classify_link("Recalde figura en el expediente de Recoleta", claim) != "equivalent"
    assert classify_link("Recalde es dueño del 1° A", claim) == "equivalent"


def test_varios_medios_is_not_independent_confirmation_language() -> None:
    assert signals_independent_confirmation_language("Varios medios publicaron el informe.") is False
    assert signals_independent_confirmation_language("Fuentes independientes confirmaron el incendio.") is True
    assert signals_independent_confirmation_language("El ministro confirmó la cifra.") is False


def test_categorical_headline_is_structural_and_blocks_publish(db_session: Session) -> None:
    headline = "Recalde es dueño del 1° A"
    event, article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline=headline,
        summary="El dirigente aparece como propietario de la unidad.",
        paragraphs=[[("Según La Nación, Recalde figura como propietario del departamento 1° A.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    db_session.refresh(article)
    runs = list(db_session.scalars(select(PipelineRun).where(PipelineRun.event_id == event.id)))
    issues = structural_findings(evidence_snapshot_for_version(runs, article.current_version), article)
    assert structural_blocks_rewrite(issues)
    assert result["passed"] is False
    assert result["reason"] == "structural_block"
    assert result["rewrite_count"] == 0
    assert "ArticleDraft" not in llm.calls
    assert article.headline == headline
    assert article.status.value == "DRAFT"
    assert _reasons(result["issues"]) & {"surface_categorical", "surface_attribution"}
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is False
    assert published["reason"] == "audit_not_passed"


def test_attributed_body_does_not_heal_unattributed_headline(db_session: Session) -> None:
    event, article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline="Recalde es dueño del 1° A",
        summary="Según La Nación, Recalde es dueño del 1° A.",
        paragraphs=[[("Según La Nación, Recalde es dueño del 1° A.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    assert result["passed"] is False
    assert result["reason"] == "structural_block"
    assert result["rewrite_count"] == 0
    assert "ArticleDraft" not in llm.calls
    headline_issues = [issue for issue in result["issues"] if issue.get("claim_ref") == "headline"]
    assert any(issue.get("reason") in {"surface_attribution", "surface_categorical"} for issue in headline_issues)
    assert article.headline == "Recalde es dueño del 1° A"


def test_attributed_headline_is_not_blocked_by_attribution_rule(db_session: Session) -> None:
    event, _article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline="Según La Nación, Recalde es dueño del 1° A",
        summary="Según La Nación, Recalde es dueño del 1° A.",
        paragraphs=[[("Según La Nación, Recalde es dueño del 1° A.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    assert result["passed"] is True
    assert result["rewrite_count"] == 0
    assert "ArticleDraft" not in llm.calls
    assert "surface_attribution" not in _reasons(result["issues"])
    assert "surface_categorical" not in _reasons(result["issues"])
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True


def test_accredited_utterance_is_not_content_as_fact() -> None:
    claim = {
        "id": "u1",
        "canonical_text": "Pérez afirmó que el costo será de 40.000 millones.",
        "claim_type": "declaracion",
        "importance": "HIGH",
        "status": "SUPPORTED",
        "proposition_role": "utterance",
    }
    decisions = {"u1": _decision("u1", status="SUPPORTED", rendering=_UTTERANCE, role="utterance")}
    snap = _snapshot([claim], decisions)
    attributed = _article(
        headline="Pérez afirmó que el costo será de 40.000 millones",
        summary="Pérez afirmó que el costo será de 40.000 millones.",
        body="Pérez afirmó que el costo será de 40.000 millones.",
    )
    ok = surface_validation_findings(snap, attributed)
    assert AuditIssueReason.SURFACE_CATEGORICAL not in {issue.reason for issue in ok}
    segun = _article(
        headline="Según Pérez, el costo será de 40.000 millones",
        summary="Pérez afirmó que el costo será de 40.000 millones.",
        body="Pérez afirmó que el costo será de 40.000 millones.",
    )
    segun_blocked = surface_validation_findings(snap, segun)
    assert any(
        issue.reason == AuditIssueReason.SURFACE_CATEGORICAL and issue.claim_ref == "headline"
        for issue in segun_blocked
    )
    as_fact = _article(
        headline="El costo será de 40.000 millones",
        summary="Pérez afirmó que el costo será de 40.000 millones.",
        body="Pérez afirmó que el costo será de 40.000 millones.",
    )
    blocked = surface_validation_findings(snap, as_fact)
    assert any(issue.reason == AuditIssueReason.SURFACE_CATEGORICAL and issue.claim_ref == "headline" for issue in blocked)


def test_supported_fact_is_not_blocked_by_utterance_sibling() -> None:
    fact = {
        "id": "f1",
        "canonical_text": "El Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas",
        "claim_type": "cifra",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
        "proposition_role": "other",
    }
    utterance = {
        "id": "u1",
        "canonical_text": "El Gobierno reconoció el esfuerzo de las Fuerzas Armadas con un aumento del 12,22%.",
        "claim_type": "declaracion",
        "importance": "HIGH",
        "status": "SUPPORTED",
        "proposition_role": "utterance",
    }
    snap = _snapshot(
        [fact, utterance],
        {
            "f1": _decision("f1", status="SINGLE_SOURCE", rendering=_RESTRICTED, role="other"),
            "u1": _decision("u1", status="SUPPORTED", rendering=_UTTERANCE, role="utterance"),
        },
    )
    article = _article(
        headline="Según el anuncio, el Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas",
        summary="Según el anuncio, el Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas.",
        body="Según el anuncio, el Gobierno dispuso un aumento del 12,22% para las Fuerzas Armadas.",
    )
    issues = surface_validation_findings(snap, article)
    assert AuditIssueReason.SURFACE_CATEGORICAL not in {issue.reason for issue in issues}


def test_modal_formulation_is_not_consummated_fact() -> None:
    claim = {
        "id": "m1",
        "canonical_text": "El depósito de Rosario se incendiará esta noche.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot([claim], {"m1": _decision("m1", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    article = _article(
        headline="Según el parte, el depósito de Rosario podría incendiarse esta noche",
        summary="Según el parte, el depósito de Rosario podría incendiarse esta noche.",
        body="Según el parte, el depósito de Rosario podría incendiarse esta noche.",
    )
    issues = surface_validation_findings(snap, article)
    assert AuditIssueReason.SURFACE_CATEGORICAL not in {issue.reason for issue in issues}


def test_independent_confirmation_language_respects_contract() -> None:
    claim = {
        "id": "i1",
        "canonical_text": "Hubo un incendio en el depósito de Rosario.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    forbidden = _snapshot([claim], {"i1": _decision("i1", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    allowed = _snapshot(
        [{**claim, "status": "SUPPORTED"}],
        {
            "i1": _decision(
                "i1",
                status="SUPPORTED",
                rendering={**_OPEN, "independent_confirmation_language_allowed": True},
            )
        },
    )
    surface = _article(
        headline="Fuentes independientes confirmaron un incendio en el depósito de Rosario",
        summary="Hubo un incendio en el depósito de Rosario.",
        body="Hubo un incendio en el depósito de Rosario.",
    )
    blocked = surface_validation_findings(forbidden, surface)
    assert any(issue.reason == AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE for issue in blocked)
    ok = surface_validation_findings(allowed, surface)
    assert AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE not in {issue.reason for issue in ok}
    varios = _article(
        headline="Varios medios publicaron que hubo un incendio en el depósito de Rosario",
        summary="Hubo un incendio en el depósito de Rosario.",
        body="Hubo un incendio en el depósito de Rosario.",
    )
    not_independent = surface_validation_findings(forbidden, varios)
    assert AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE not in {issue.reason for issue in not_independent}


def test_dispute_and_contradiction_are_not_assertions() -> None:
    claim = {
        "id": "d1",
        "canonical_text": "Recalde es dueño del 1° A.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot([claim], {"d1": _decision("d1", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    dispute = _article(
        headline="Que Recalde es dueño del 1° A está en disputa",
        summary="Que Recalde es dueño del 1° A está en disputa.",
        body="Que Recalde es dueño del 1° A está en disputa.",
    )
    contradiction = _article(
        headline="Una evidencia contradice que Recalde es dueño del 1° A",
        summary="Una evidencia contradice que Recalde es dueño del 1° A.",
        body="Una evidencia contradice que Recalde es dueño del 1° A.",
    )
    for article in (dispute, contradiction):
        issues = surface_validation_findings(snap, article)
        assert AuditIssueReason.SURFACE_CATEGORICAL not in {issue.reason for issue in issues}


def test_headline_coverage_rejects_accessory_claim() -> None:
    claims = [
        {
            "id": "high",
            "canonical_text": "Hubo un incendio en un depósito de Rosario.",
            "importance": "HIGH",
            "status": "SUPPORTED",
        },
        {
            "id": "low",
            "canonical_text": "El edificio de San José 1111 tiene portería las 24 horas.",
            "importance": "LOW",
            "status": "SUPPORTED",
        },
    ]
    decisions = {
        "high": _decision("high", status="SUPPORTED", rendering=_OPEN),
        "low": _decision("low", status="SUPPORTED", rendering=_OPEN),
    }
    snap = _snapshot(claims, decisions)
    article = _article(
        headline="Recalde es dueño de un departamento en San José 1111",
        summary="El edificio de San José 1111 tiene portería las 24 horas.",
        body="El edificio de San José 1111 tiene portería las 24 horas.",
    )
    issues = surface_validation_findings(snap, article)
    assert any(issue.reason == AuditIssueReason.HEADLINE_UNCOVERED for issue in issues)
    covered = _article(
        headline="Hubo un incendio en un depósito de Rosario",
        summary="Hubo un incendio en un depósito de Rosario.",
        body="Hubo un incendio en un depósito de Rosario.",
    )
    ok = surface_validation_findings(snap, covered)
    assert AuditIssueReason.HEADLINE_UNCOVERED not in {issue.reason for issue in ok}


def test_ambiguous_paraphrase_is_indeterminate_not_pass_or_block() -> None:
    claim = {
        "id": "c1",
        "canonical_text": "Recalde es dueño del 1° A.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot([claim], {"c1": _decision("c1", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    article = _article(
        headline="Recalde figura en el expediente de Recoleta",
        summary="Hay un trámite administrativo en curso.",
        body="Hay un trámite administrativo en curso.",
    )
    issues = surface_validation_findings(snap, article)
    reasons = {issue.reason for issue in issues}
    assert AuditIssueReason.SURFACE_INDETERMINATE in reasons
    assert AuditIssueReason.SURFACE_CATEGORICAL not in reasons
    assert AuditIssueReason.SURFACE_ATTRIBUTION not in reasons
    blocking = [issue for issue in issues if issue.severity.value in {"HIGH", "MEDIUM"}]
    assert not any(issue.reason == AuditIssueReason.SURFACE_CATEGORICAL for issue in blocking)


def test_v2_uses_own_snapshot_and_leaves_public_v1(db_session: Session) -> None:
    event, article, _rows, _refs = _seed(
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
    v1 = article.published_version
    live_headline = article.headline
    extra = _claim(
        db_session,
        event,
        text="Recalde es dueño del 1° A.",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    db_session.refresh(event)
    item = event.event_sources[0].source_item
    db_session.add(
        ClaimEvidence(
            claim_id=extra.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Recalde es dueño del 1° A.",
            source_url=item.url,
        )
    )
    ArticleService(db_session).update_content(
        article,
        ArticleContentUpdate(
            headline="Recalde es dueño del 1° A",
            summary="Según La Nación, Recalde es dueño del 1° A.",
            body="Según La Nación, Recalde es dueño del 1° A.",
            change_reason="c5-v2",
        ),
    )
    article.status = ArticleStatus.DRAFT
    db_session.flush()
    db_session.refresh(article)
    persist_version_snapshot(db_session, event, article)
    second, llm = _audit(db_session, event, result=_pass_audit())
    assert second["passed"] is False
    assert second["reason"] == "structural_block"
    assert "ArticleDraft" not in llm.calls
    db_session.refresh(article)
    assert article.published_version == v1
    assert article.current_version != v1
    blocked = PublishService(db_session).publish(event.id, trigger="test")
    assert blocked["published"] is False
    db_session.refresh(article)
    db_session.commit()
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
    assert payload["headline"] == live_headline
    assert payload["published_version"] == v1


def test_legacy_and_incomplete_do_not_invent_or_call_live(monkeypatch) -> None:
    called: list[str] = []

    def boom(*_args, **_kwargs):
        called.append("live")
        raise AssertionError("live verification")

    monkeypatch.setattr("app.services.verification_outcome.verification_view_for_event", boom)
    claim = {
        "id": "c1",
        "canonical_text": "Recalde es dueño del 1° A.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    article = _article(
        headline="Recalde es dueño del 1° A",
        summary="Recalde es dueño del 1° A.",
        body="Recalde es dueño del 1° A.",
    )
    legacy = _snapshot([claim], {"c1": {"claim_id": "c1", "status": "SINGLE_SOURCE"}})
    incomplete = _snapshot(
        [claim],
        {"c1": _decision("c1", status="SINGLE_SOURCE", rendering=None, state="complete")},
    )
    skipped = _snapshot(
        [claim],
        {
            "c1": {
                "claim_id": "c1",
                "status": "SINGLE_SOURCE",
                "evaluation_state": "skipped",
                "public_rendering": None,
            }
        },
    )
    legacy_issues = surface_validation_findings(legacy, article)
    incomplete_issues = surface_validation_findings(incomplete, article)
    skipped_issues = surface_validation_findings(skipped, article)
    assert called == []
    assert any(issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE for issue in legacy_issues)
    assert any(issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE for issue in incomplete_issues)
    assert any(issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE for issue in skipped_issues)
    assert AuditIssueReason.SURFACE_ATTRIBUTION not in {issue.reason for issue in skipped_issues}
    assert AuditIssueReason.SURFACE_CATEGORICAL not in {issue.reason for issue in skipped_issues}


def test_c5_findings_do_not_enqueue_writing(db_session: Session) -> None:
    event, article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline="Recalde es dueño del 1° A",
        summary="El dirigente aparece como propietario.",
        paragraphs=[[("Según La Nación, Recalde es dueño del 1° A.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    assert result["rewrite_count"] == 0
    assert llm.calls == ["ArticleAuditResult"]
    assert "ArticleDraft" not in llm.calls
    db_session.refresh(article)
    assert article.headline == "Recalde es dueño del 1° A"


def test_surface_validation_is_idempotent() -> None:
    claim = {
        "id": "c1",
        "canonical_text": "Recalde es dueño del 1° A.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot([claim], {"c1": _decision("c1", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    article = _article(
        headline="Recalde es dueño del 1° A",
        summary="Recalde es dueño del 1° A.",
        body="Recalde es dueño del 1° A.",
    )
    first = surface_validation_findings(snap, article)
    second = surface_validation_findings(snap, article)
    assert [_issue_key(issue) for issue in first] == [_issue_key(issue) for issue in second]
    assert len(first) == len({_issue_key(issue) for issue in first})


def test_repeat_audit_does_not_duplicate_c5_work(db_session: Session) -> None:
    event, article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline="Recalde es dueño del 1° A",
        summary="Según La Nación, Recalde es dueño del 1° A.",
        paragraphs=[[("Según La Nación, Recalde es dueño del 1° A.", ["C1"])]],
    )
    first, llm1 = _audit(db_session, event, result=_pass_audit())
    second, llm2 = _audit(db_session, event, result=_pass_audit())
    assert first["rewrite_count"] == second["rewrite_count"] == 0
    assert "ArticleDraft" not in llm1.calls
    assert "ArticleDraft" not in llm2.calls
    assert len(first["issues"]) == len({_issue_key(issue) for issue in first["issues"]})
    assert len(second["issues"]) == len({_issue_key(issue) for issue in second["issues"]})
    db_session.refresh(article)
    assert article.current_version == 1


def test_supported_fact_keeps_normal_publish_path(db_session: Session) -> None:
    event, _article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Hubo un incendio en el depósito de Rosario.", "status": ClaimStatus.SUPPORTED}],
        headline="Hubo un incendio en el depósito de Rosario",
        summary="Hubo un incendio en el depósito de Rosario.",
        paragraphs=[[("Hubo un incendio en el depósito de Rosario durante la madrugada.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    assert result["passed"] is True
    assert result["rewrite_count"] == 0
    assert "ArticleDraft" not in llm.calls
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True


ANDIS_SUMMARY = (
    "El relevamiento, que analizó la gestión del organismo hasta agosto de 2025, "
    "también consignó pagos por $479.504 millones a prestadores de medicamentos e insumos, "
    "de acuerdo con reportes periodísticos."
)
ANDIS_PAYMENTS = (
    "La auditoría contabilizó pagos por $479.504 millones a prestadores por medicamentos "
    "e insumos entre 2024 y el 21 de agosto de 2025."
)
ANDIS_HEADLINE = (
    "Según una auditoría, la ex Andis registró un desfasaje de $158.717 millones "
    "en sus informes de deuda"
)
ANDIS_LEAD = (
    "Una auditoría detectó un desfasaje de $158.717 millones entre los informes de deuda "
    "de la ex Agencia Nacional de Discapacidad (Andis), según reportes periodísticos que "
    "citaron el relevamiento. La diferencia corresponde, de acuerdo con esas publicaciones, "
    "a obligaciones que no habrían pasado por las áreas de control establecidas."
)
PILAR_HEADLINE = (
    "Granja Tres Arroyos ofreció pagar parte de los salarios con pollos durante una conciliación obligatoria"
)
JEREZ_HEADLINE = (
    "Identificaron a Franco Ibán Jerez tras los incidentes denunciados por Gerardo Huesen en Graneros"
)
GRANJA_FACT_HEADLINE = "Granja Tres Arroyos despidió a 700 trabajadores en Capitán Sarmiento"
GRANJA_BOMBA = (
    "Granja Tres Arroyos, el despido de 700 trabajadores y un efecto en cadena en el pueblo "
    "«Es una bomba neutrónica en medio de la provincia» El drama de una comunidad tras los "
    "despidos en la principal empresa avícola en Capitán Sarmiento."
)


def test_andis_trailing_attribution_covers_that_assertion() -> None:
    claim = {
        "id": "5822cdcf",
        "canonical_text": ANDIS_PAYMENTS,
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot([claim], {"5822cdcf": _decision("5822cdcf", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    article = _article(headline=ANDIS_HEADLINE, summary=ANDIS_SUMMARY, body=ANDIS_LEAD)
    issues = surface_validation_findings(snap, article)
    assert not any(
        issue.claim_id == "5822cdcf"
        and issue.reason
        in {AuditIssueReason.SURFACE_ATTRIBUTION, AuditIssueReason.SURFACE_CATEGORICAL}
        for issue in issues
    )


def test_trailing_marker_does_not_cover_a_coordinated_proposition() -> None:
    from app.services.surface_validation import _assertion_attributed

    mixed = (
        "La auditoría contabilizó pagos por $479.504 millones a prestadores por medicamentos e insumos "
        "entre 2024 y el 21 de agosto de 2025, mientras que, según un informe, la deuda aumentó."
    )
    assert "$479.504" in mixed
    assert _assertion_attributed(ANDIS_SUMMARY, ANDIS_PAYMENTS) is True
    assert _assertion_attributed(mixed, ANDIS_PAYMENTS) is False
    claim = {
        "id": "5822cdcf",
        "canonical_text": ANDIS_PAYMENTS,
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot([claim], {"5822cdcf": _decision("5822cdcf", status="SINGLE_SOURCE", rendering=_RESTRICTED)})
    article = _article(headline=mixed, summary=mixed, body=mixed)
    issues = surface_validation_findings(snap, article)
    assert any(
        issue.claim_id == "5822cdcf"
        and issue.reason
        in {AuditIssueReason.SURFACE_ATTRIBUTION, AuditIssueReason.SURFACE_CATEGORICAL}
        for issue in issues
    )


def test_andis_real_surfaces_have_no_high_false_positives_on_payments() -> None:
    claims = [
        {
            "id": "5822cdcf",
            "canonical_text": ANDIS_PAYMENTS,
            "importance": "HIGH",
            "status": "SINGLE_SOURCE",
        },
        {
            "id": "a2efddc3",
            "canonical_text": (
                "Una auditoría detectó un desfasaje de 158.717 millones de pesos en los informes "
                "de deuda de la ex Agencia Nacional de Discapacidad (Andis)."
            ),
            "importance": "HIGH",
            "status": "SINGLE_SOURCE",
        },
        {
            "id": "8b114168",
            "canonical_text": (
                "La auditoría analizó la gestión de la Andis hasta el 21 de agosto de 2025, "
                "cuando el Gobierno desplazó a Diego Spagnuolo."
            ),
            "importance": "HIGH",
            "status": "SUPPORTED",
        },
    ]
    snap = _snapshot(
        claims,
        {
            "5822cdcf": _decision("5822cdcf", status="SINGLE_SOURCE", rendering=_RESTRICTED),
            "a2efddc3": _decision("a2efddc3", status="SINGLE_SOURCE", rendering=_RESTRICTED),
            "8b114168": {
                "claim_id": "8b114168",
                "status": "SUPPORTED",
                "evaluation_state": "skipped",
                "public_rendering": None,
            },
        },
    )
    article = _article(headline=ANDIS_HEADLINE, summary=ANDIS_SUMMARY, body=ANDIS_LEAD)
    issues = surface_validation_findings(snap, article)
    high = [issue for issue in issues if issue.severity.value in {"HIGH", "MEDIUM"}]
    assert not any(
        issue.claim_id == "5822cdcf"
        and issue.reason
        in {AuditIssueReason.SURFACE_ATTRIBUTION, AuditIssueReason.SURFACE_CATEGORICAL}
        for issue in high
    )
    assert not high


def test_pilar_duration_is_not_equivalent_and_skipped_principal_is_incomplete() -> None:
    duration = {
        "id": "9111b958",
        "canonical_text": (
            "La conciliación obligatoria es por 15 días hábiles, con posibilidad de una prórroga de cinco días."
        ),
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    principal = {
        "id": "f276190c",
        "canonical_text": "Granja Tres Arroyos ofreció a sus trabajadores pagar parte de los salarios con pollos.",
        "importance": "HIGH",
        "status": "SUPPORTED",
    }
    skipped = {
        "claim_id": "x",
        "status": "SINGLE_SOURCE",
        "evaluation_state": "skipped",
        "public_rendering": None,
    }
    snap = _snapshot(
        [duration, principal],
        {
            "9111b958": {**skipped, "claim_id": "9111b958", "status": "SINGLE_SOURCE"},
            "f276190c": {**skipped, "claim_id": "f276190c", "status": "SUPPORTED"},
        },
    )
    article = _article(
        headline=PILAR_HEADLINE,
        summary=PILAR_HEADLINE + ".",
        body=PILAR_HEADLINE + ".",
    )
    assert classify_link(PILAR_HEADLINE, duration) != "equivalent"
    issues = surface_validation_findings(snap, article)
    assert not any(
        issue.claim_id == "9111b958" and issue.reason == AuditIssueReason.SURFACE_ATTRIBUTION for issue in issues
    )
    assert any(
        issue.claim_id == "f276190c" and issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE for issue in issues
    )


def test_jerez_false_matches_drop_and_identification_stays_blocked() -> None:
    secretary = {
        "id": "6a782a00",
        "canonical_text": "Franco Ibán Jerez fue secretario de Gobierno de la Municipalidad de Graneros en 2022.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    hunger = {
        "id": "791fab61",
        "canonical_text": (
            'Franco Ibán Jerez afirmó que el Gobierno nacional los estaba haciendo "morir de hambre" '
            "durante los incidentes en Graneros."
        ),
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
        "claim_type": "declaracion",
    }
    identification = {
        "id": "7d7a8812",
        "canonical_text": (
            "Franco Ibán Jerez fue identificado como la persona que increpó al equipo del diputado "
            "Gerardo Huesen durante incidentes en Graneros, Tucumán, el 19 de septiembre."
        ),
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot(
        [secretary, hunger, identification],
        {
            "6a782a00": {
                "claim_id": "6a782a00",
                "status": "SINGLE_SOURCE",
                "evaluation_state": "skipped",
                "public_rendering": None,
            },
            "791fab61": _decision("791fab61", status="SINGLE_SOURCE", rendering=_RESTRICTED, role="utterance"),
            "7d7a8812": _decision("7d7a8812", status="SINGLE_SOURCE", rendering=_RESTRICTED),
        },
    )
    article = _article(
        headline=JEREZ_HEADLINE,
        summary=(
            "Según un reporte periodístico, Franco Ibán Jerez fue identificado como la persona que "
            "increpó al equipo del diputado Gerardo Huesen durante los incidentes del 19 de septiembre en Graneros."
        ),
        body=(
            "Según un reporte periodístico, Franco Ibán Jerez fue identificado como la persona que "
            "increpó al equipo del diputado nacional Gerardo Huesen durante los incidentes ocurridos "
            "el 19 de septiembre en Graneros, Tucumán."
        ),
    )
    assert classify_link(JEREZ_HEADLINE, secretary) != "equivalent"
    assert classify_link(JEREZ_HEADLINE, hunger) != "equivalent"
    assert classify_link(JEREZ_HEADLINE, identification) == "equivalent"
    issues = surface_validation_findings(snap, article)
    assert not any(issue.claim_id == "6a782a00" and issue.severity.value in {"HIGH", "MEDIUM"} for issue in issues)
    assert any(
        issue.claim_id == "7d7a8812"
        and issue.reason == AuditIssueReason.SURFACE_ATTRIBUTION
        and issue.claim_ref == "headline"
        for issue in issues
    )


def test_granja700_supported_fact_does_not_license_or_inherit_characterization() -> None:
    fact = {
        "id": "61351a23",
        "canonical_text": "Granja Tres Arroyos despidió a 700 trabajadores en Capitán Sarmiento.",
        "importance": "HIGH",
        "status": "SUPPORTED",
    }
    characterization = {
        "id": "8a0b98c2",
        "canonical_text": GRANJA_BOMBA,
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    telegrams = {
        "id": "529b15f0",
        "canonical_text": (
            "Granja Tres Arroyos envió alrededor de 1.200 telegramas de despido a trabajadores "
            "de sus plantas de Capitán Sarmiento, Esteban Echeverría y Pilar."
        ),
        "importance": "HIGH",
        "status": "SUPPORTED",
    }
    snap = _snapshot(
        [fact, characterization, telegrams],
        {
            "61351a23": _decision("61351a23", status="SUPPORTED", rendering=_OPEN),
            "8a0b98c2": _decision("8a0b98c2", status="SINGLE_SOURCE", rendering=_RESTRICTED),
            "529b15f0": {
                "claim_id": "529b15f0",
                "status": "SUPPORTED",
                "evaluation_state": "skipped",
                "public_rendering": None,
            },
        },
    )
    fact_only = _article(
        headline=GRANJA_FACT_HEADLINE,
        summary=GRANJA_FACT_HEADLINE + ".",
        body=GRANJA_FACT_HEADLINE + ".",
    )
    fact_only_issues = surface_validation_findings(snap, fact_only)
    assert not any(
        issue.claim_id == "8a0b98c2" and issue.severity.value in {"HIGH", "MEDIUM"} for issue in fact_only_issues
    )
    assert not any(
        issue.claim_id == "61351a23"
        and issue.reason in {AuditIssueReason.SURFACE_ATTRIBUTION, AuditIssueReason.SURFACE_CATEGORICAL}
        for issue in fact_only_issues
    )

    compound_headline = f"{GRANJA_FACT_HEADLINE} y es una bomba neutrónica"
    compound = _article(
        headline=compound_headline,
        summary=compound_headline + ".",
        body=compound_headline + ".",
    )
    compound_issues = surface_validation_findings(snap, compound)
    assert not any(
        issue.claim_id == "61351a23"
        and issue.reason in {AuditIssueReason.SURFACE_ATTRIBUTION, AuditIssueReason.SURFACE_CATEGORICAL}
        for issue in compound_issues
    )
    assert any(
        issue.claim_id == "8a0b98c2"
        and issue.reason in {AuditIssueReason.SURFACE_ATTRIBUTION, AuditIssueReason.SURFACE_CATEGORICAL}
        for issue in compound_issues
    )

    twelve_hundred = _article(
        headline=GRANJA_FACT_HEADLINE,
        summary="La empresa envió alrededor de 1.200 telegramas de despido en tres plantas bonaerenses.",
        body=GRANJA_FACT_HEADLINE + ".",
    )
    twelve_issues = surface_validation_findings(snap, twelve_hundred)
    assert any(
        issue.claim_id == "529b15f0" and issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE
        for issue in twelve_issues
    )
