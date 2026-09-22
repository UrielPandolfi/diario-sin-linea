"""Regresiones de la prueba real post-fixes (prueba-real-post-fixes.json).

IDs y textos copiados del export. No llaman providers pagos ni tocan sin_linea.
"""

from types import SimpleNamespace

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.auditing import (
    ArticleAuditResult,
    AuditIssue,
    AuditIssueAction,
    AuditIssueReason,
    AuditIssueSeverity,
    AuditIssueType,
)
from app.core.text import normalize_name
from app.schemas.editorial_evidence import (
    CoverageContract,
    CoverageMatch,
    CoverageSignal,
    ExpectedCentral,
    GapReason,
    PropositionRole,
)
from app.schemas.verification import VerificationEvidence
from app.services.audit_policy import merge_audit_result
from app.services.article_context import compact_verification
from app.services.claim_coverage import (
    expected_centrals_from_event,
    match_expected_to_claims,
    propositions_equivalent,
)
from app.services.surface_validation import classify_link, surface_validation_findings
from app.services.verification_service import VerificationService
from tests.test_surface_validation import _article, _decision, _OPEN, _RESTRICTED, _snapshot

# La Tablada — artículo fa0fa66a / suceso 58759b17 / claim 37f7556a
TABLADA_CLAIM_ID = "37f7556a-5db8-4b63-897b-28ecd73ce273"
TABLADA_CLAIM = "Alan Gabriel Chazarreta recibió un único disparo durante el tiroteo."
TABLADA_INFOBAE = (
    "Alan Gabriel Chazarreta recibió un único disparo y fue trasladado al hospital."
)
TABLADA_HEADLINE = "Detuvieron a un hombre herido de bala tras el operativo en La Tablada"

# Esteche — artículo b8343be8 / suceso bb76b7a6
ESTECHE_HEADLINE = (
    "La publicación señala una conspiración para desviar la investigación del atentado "
    "contra la AMIA, según una resolución judicial"
)
ESTECHE_EMBARGO = (
    "El juez federal Daniel Rafecas dispuso un embargo de US$500 millones a cada uno "
    "de los procesados por el atentado a la AMIA"
)

# Milei — artículo f2b4ac65 / suceso 2b3557aa
MILEI_ARRIVAL_ID = "0b0ae24f-05ef-4fb9-9c5d-1c875c6b4636"
MILEI_RETURN_ID = "4703a87e-3e96-4fc3-b013-039d012abb1d"
MILEI_HEADLINE = "Milei llegará a Nueva York el martes"
MILEI_ARRIVAL = (
    "Milei tiene previsto aterrizar en el Aeropuerto Internacional John F. Kennedy "
    "el martes a las 9:30, hora argentina."
)
MILEI_RETURN = "Milei partirá de regreso hacia Buenos Aires el jueves a las 21:00."

# Formosa V2 — artículo ab70f815 / claim skipped fe1b7c92
FORMOSA_LEAD = (
    "Las diputadas radicales cuestionaron que se asocien los beneficios escolares "
    "con el gobernador Gildo Insfrán."
)
FORMOSA_QA = "¿Cómo se llama el gobernador? Gildo Insfrán"
FORMOSA_SUMMARY = (
    "Tras la denuncia, el Ministerio de Capital Humano pidió, según reportes periodísticos, "
    "que la provincia investigue lo ocurrido."
)
FORMOSA_PEDIDO = "El Ministerio de Capital Humano pidió que la provincia investigue lo ocurrido."

# AMIA V3 — artículo a3dc7124 / claims 2419315e y 4a2ba9d1
AMIA_HEADLINE = (
    "Rafecas procesó a ocho acusados por el atentado a la AMIA y les impuso "
    "embargos de US$500 millones"
)
AMIA_CLAIM_OPEN = (
    "El juez federal Daniel Rafecas dispuso un embargo de US$500 millones a cada uno "
    "de los procesados por el atentado a la AMIA"
)
AMIA_CLAIM_RESTRICTED = (
    "El juez federal Daniel Rafecas impuso un embargo de US$500 millones a cada uno "
    "de los ocho procesados por el atentado a la AMIA"
)
AMIA_LEAD = (
    "La resolución del juez federal Daniel Rafecas alcanzó a ocho acusados por el "
    "atentado contra la AMIA: Alí Fallahijan, Alí Velayati, Mohsen Rezai, Ahmad Vahidi, "
    "Hadi Soleimanpour, Mohsen Rabbani, Ahmad Asghari y Salman Raouf Salman."
)
AMIA_ROLES = (
    "Alí Fallahijan, Alí Velayati, Mohsen Rezai y Ahmad Vahidi fueron autores mediatos "
    "del atentado contra la AMIA"
)


def test_tablada_excerpt_without_shooting_link_is_not_full_support() -> None:
    service = object.__new__(VerificationService)
    service._comparison_checks = []
    claim = SimpleNamespace(canonical_text=TABLADA_CLAIM, claim_type="hecho")
    row = VerificationEvidence(
        source_ref=1,
        evidence_type=EvidenceType.SUPPORTS,
        excerpt=TABLADA_INFOBAE,
    )
    admitted, _ = service._admit_relation(claim, None, row, EvidenceType.SUPPORTS)
    assert admitted == EvidenceType.QUALIFIES
    assert service._comparison_checks[0]["reason"] == "excerpt_partial_scope"
    assert propositions_equivalent(TABLADA_CLAIM, TABLADA_INFOBAE) is CoverageMatch.PARTIAL


def test_tablada_full_excerpt_with_circumstance_stays_support() -> None:
    service = object.__new__(VerificationService)
    service._comparison_checks = []
    claim = SimpleNamespace(canonical_text=TABLADA_CLAIM, claim_type="hecho")
    row = VerificationEvidence(
        source_ref=1,
        evidence_type=EvidenceType.SUPPORTS,
        excerpt=TABLADA_CLAIM,
    )
    admitted, _ = service._admit_relation(claim, None, row, EvidenceType.SUPPORTS)
    assert admitted == EvidenceType.SUPPORTS


def test_esteche_headline_without_central_claim_is_uncovered() -> None:
    event = SimpleNamespace(title_internal=ESTECHE_HEADLINE, event_sources=[])
    expected = expected_centrals_from_event(event)
    assert expected
    embargo = SimpleNamespace(id="embargo", canonical_text=ESTECHE_EMBARGO, claim_type="hecho")
    matched = match_expected_to_claims(expected, [embargo])
    assert any(row.match is not CoverageMatch.EQUIVALENT for row in matched)
    claims = [
        {
            "id": "embargo",
            "canonical_text": ESTECHE_EMBARGO,
            "importance": "HIGH",
            "status": "SUPPORTED",
        }
    ]
    snap = _snapshot(
        claims,
        {"embargo": _decision("embargo", status="SUPPORTED", rendering=_OPEN)},
    )
    snap["coverage"] = {
        "coverage_gap": True,
        "expected_central": [
            {
                "proposition": row.proposition,
                "role": row.role.value if hasattr(row.role, "value") else row.role,
                "match": row.match.value if hasattr(row.match, "value") else row.match,
            }
            for row in matched
        ],
    }
    article = _article(
        headline=ESTECHE_HEADLINE,
        summary=ESTECHE_HEADLINE,
        body=ESTECHE_HEADLINE,
    )
    from app.services.audit_policy import structural_findings

    issues = structural_findings(snap, article)
    assert any(issue.reason == AuditIssueReason.CENTRAL_UNCOVERED for issue in issues)


def test_esteche_title_enters_expected_central() -> None:
    event = SimpleNamespace(title_internal=ESTECHE_HEADLINE, event_sources=[])
    rows = expected_centrals_from_event(event)
    assert any(row.signal is CoverageSignal.TITLE for row in rows)
    assert any("conspiracion" in normalize_name(row.proposition) for row in rows)


def test_milei_audit_does_not_link_arrival_headline_to_return_claim() -> None:
    claims = [
        {
            "id": MILEI_ARRIVAL_ID,
            "canonical_text": MILEI_ARRIVAL,
            "importance": "HIGH",
            "status": "SUPPORTED",
        },
        {
            "id": MILEI_RETURN_ID,
            "canonical_text": MILEI_RETURN,
            "importance": "HIGH",
            "status": "SINGLE_SOURCE",
        },
    ]
    snap = _snapshot(
        claims,
        {
            MILEI_ARRIVAL_ID: _decision(MILEI_ARRIVAL_ID, status="SUPPORTED", rendering=_OPEN),
            MILEI_RETURN_ID: _decision(MILEI_RETURN_ID, status="SINGLE_SOURCE", rendering=_RESTRICTED),
        },
    )
    article = _article(headline=MILEI_HEADLINE, summary=MILEI_HEADLINE, body=MILEI_HEADLINE)
    llm = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.UNSUPPORTED_CLAIM,
                severity=AuditIssueSeverity.HIGH,
                text=MILEI_HEADLINE,
                explanation="Usa la palabra regreso para bloquear la llegada.",
                reason=AuditIssueReason.SINGLE_AS_CORROBORATED,
                claim_id=MILEI_RETURN_ID,
                action=AuditIssueAction.REVIEW,
            )
        ],
    )
    merged = merge_audit_result(llm, structural=[], article=article, snapshot=snap)
    assert not any(issue.claim_id == MILEI_RETURN_ID for issue in merged.issues)
    assert classify_link(MILEI_HEADLINE, claims[1]) != "equivalent"


def test_formosa_question_claim_is_not_equivalent_to_lead() -> None:
    claim = {"id": "fe1b7c92-9895-4a58-975b-d28b7bd51db9", "canonical_text": FORMOSA_QA}
    assert classify_link(FORMOSA_LEAD, claim) != "equivalent"
    assert propositions_equivalent(FORMOSA_LEAD, FORMOSA_QA) is CoverageMatch.NONE
    snap = _snapshot(
        [
            {
                "id": claim["id"],
                "canonical_text": FORMOSA_QA,
                "importance": "LOW",
                "status": "SINGLE_SOURCE",
            }
        ],
        {claim["id"]: _decision(claim["id"], status="SINGLE_SOURCE", rendering=None, state="skipped")},
    )
    article = _article(headline=FORMOSA_LEAD, summary=FORMOSA_LEAD, body=FORMOSA_LEAD)
    issues = surface_validation_findings(snap, article)
    assert AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE not in {issue.reason for issue in issues}


def test_formosa_attribution_in_same_clause_is_recognized() -> None:
    claim = {
        "id": "pedido",
        "canonical_text": FORMOSA_PEDIDO,
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot(
        [claim],
        {"pedido": _decision("pedido", status="SINGLE_SOURCE", rendering=_RESTRICTED)},
    )
    article = _article(headline=FORMOSA_SUMMARY, summary=FORMOSA_SUMMARY, body=FORMOSA_SUMMARY)
    issues = surface_validation_findings(snap, article)
    assert AuditIssueReason.SURFACE_ATTRIBUTION not in {issue.reason for issue in issues}


def test_amia_incompatible_embargo_contracts_are_not_resolved_by_picking_one() -> None:
    claims = [
        {
            "id": "2419315e-8f58-49ba-9eac-39ee6a7ed630",
            "canonical_text": AMIA_CLAIM_OPEN,
            "importance": "HIGH",
            "status": "SUPPORTED",
        },
        {
            "id": "4a2ba9d1-fa4a-4442-8cbc-a13c653cf490",
            "canonical_text": AMIA_CLAIM_RESTRICTED,
            "importance": "HIGH",
            "status": "SINGLE_SOURCE",
        },
    ]
    snap = _snapshot(
        claims,
        {
            claims[0]["id"]: _decision(claims[0]["id"], status="SUPPORTED", rendering=_OPEN),
            claims[1]["id"]: _decision(claims[1]["id"], status="SINGLE_SOURCE", rendering=_RESTRICTED),
        },
    )
    article = _article(headline=AMIA_HEADLINE, summary=AMIA_HEADLINE, body=AMIA_HEADLINE)
    issues = surface_validation_findings(snap, article)
    assert any(issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE for issue in issues)
    assert AuditIssueReason.SURFACE_ATTRIBUTION not in {issue.reason for issue in issues}


def test_amia_name_list_is_not_equivalent_to_specific_roles() -> None:
    claim = {"id": "roles", "canonical_text": AMIA_ROLES}
    assert classify_link(AMIA_LEAD, claim) != "equivalent"
    assert propositions_equivalent(AMIA_LEAD, AMIA_ROLES) is CoverageMatch.PARTIAL


def test_unattributed_single_source_still_blocks() -> None:
    """Caso negativo: el bloqueo categórico de SINGLE_SOURCE se conserva."""
    claim = {
        "id": "ss",
        "canonical_text": "El costo será de 40.000 millones.",
        "importance": "HIGH",
        "status": "SINGLE_SOURCE",
    }
    snap = _snapshot(
        [claim],
        {"ss": _decision("ss", status="SINGLE_SOURCE", rendering=_RESTRICTED)},
    )
    article = _article(
        headline="El costo será de 40.000 millones.",
        summary="El costo será de 40.000 millones.",
        body="El costo será de 40.000 millones.",
    )
    issues = surface_validation_findings(snap, article)
    assert any(issue.reason == AuditIssueReason.SURFACE_CATEGORICAL for issue in issues)
    llm = ArticleAuditResult(passed=True, issues=[])
    merged = merge_audit_result(llm, structural=issues, article=article, snapshot=snap)
    assert merged.passed is False


def test_tablada_readmit_demotes_persisted_partial_supports() -> None:
    service = object.__new__(VerificationService)
    service._comparison_checks = []
    ev = SimpleNamespace(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt=TABLADA_INFOBAE,
        source_item_id="infobae",
    )
    claim = SimpleNamespace(
        id=TABLADA_CLAIM_ID,
        canonical_text=TABLADA_CLAIM,
        claim_type="hecho",
        status=ClaimStatus.SUPPORTED,
        evidence=[ev],
        importance="HIGH",
    )
    changes = service._readmit_persisted_evidence(claim)
    assert ev.evidence_type == EvidenceType.QUALIFIES
    assert changes
    assert changes[0]["reason"] == "excerpt_partial_scope"
    assert claim.status != ClaimStatus.SUPPORTED


def test_esteche_live_coverage_overlay_keeps_gap() -> None:
    live = CoverageContract(
        expected_central=[
            ExpectedCentral(
                proposition=ESTECHE_HEADLINE,
                role=PropositionRole.OTHER,
                act="other",
                signal=CoverageSignal.TITLE,
                match=CoverageMatch.NONE,
                gap_reason=GapReason.NOT_EXTRACTED.value,
            )
        ],
        coverage_gap=True,
    )
    compact = compact_verification(None, coverage_gap=False, live_coverage=live)
    assert compact.coverage_gap is True
    assert compact.expected_central
    assert compact.expected_central[0].match in {CoverageMatch.NONE.value, "none", CoverageMatch.NONE}
