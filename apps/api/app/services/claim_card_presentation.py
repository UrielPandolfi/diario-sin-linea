from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import Demotion, PrimaryAccess, StatementEvidenceClass, SupportBasis
from app.services.verification_outcome import VerificationView

UNKNOWN_COVERAGE = "No hay desglose de independencia para esta verificación."
AUTHENTIC_PRIMARY_LABEL = "Declaración documentada en la publicación original"
UNRELATED_PRIMARY_LIMITATION = "El documento oficial no sostiene esta proposición."

_STANCE = {
    EvidenceType.SUPPORTS.value: "respalda",
    EvidenceType.QUALIFIES.value: "matiza",
    EvidenceType.CONTRADICTS.value: "contradice",
    EvidenceType.MENTIONS.value: "menciona",
}

_UNKNOWN_LABELS = {
    ClaimStatus.SUPPORTED.value: "Sostenido",
    ClaimStatus.SINGLE_SOURCE.value: "Independencia desconocida",
    ClaimStatus.CONFLICTING.value: "En conflicto",
    ClaimStatus.UNCERTAIN.value: "Incierto",
    ClaimStatus.DISPROVEN.value: "Desmentido",
    ClaimStatus.OUTDATED.value: "Desactualizado",
}

_STATUS_LABELS = {
    ClaimStatus.SUPPORTED.value: "Sostenido",
    ClaimStatus.SINGLE_SOURCE.value: "Sin corroboración independiente",
    ClaimStatus.CONFLICTING.value: "En conflicto",
    ClaimStatus.UNCERTAIN.value: "Incierto",
    ClaimStatus.DISPROVEN.value: "Desmentido",
    ClaimStatus.OUTDATED.value: "Desactualizado",
}

_OUTLET_TYPES = frozenset(
    {
        "media",
        "media_outlet",
        "outlet",
        "newspaper",
        "news",
        "news_outlet",
        "medio",
        "prensa",
        "diario",
        "radio",
        "tv",
        "television",
        "televisión",
    }
)
_NON_OUTLET_MARKERS = (
    "boletin",
    "boletín",
    "oficial",
    "official",
    "government",
    "gazette",
    "video",
    "social",
    "blog",
    "organismo",
    "gov",
)

_POSITIVE_PLURAL = re.compile(
    r"(?i)("
    r"[2-9]\d*\s+or[ií]genes independientes"
    r"|m[uú]ltiples corroboraciones"
    r"|varias fuentes independientes"
    r"|corroboraciones independientes"
    r")"
)

_WEAK_CONFIDENCE = re.compile(r"(?i)poca confianza")


class ClaimEvidenceDetail(BaseModel):
    evidence_type: str
    stance: str
    name: str | None = None
    url: str | None = None


class ClaimCardPresentation(BaseModel):
    verification_label: str
    limitation: str | None = None
    coverage: str
    explanation: str | None = None
    evidence_detail: list[ClaimEvidenceDetail] = Field(default_factory=list)
    basis_known: bool
    demotion: str | None = None
    documents_consulted: int | None = None
    documents_reporting: int | None = None
    known_independent_count: int | None = None
    unknown_group_count: int | None = None
    reprint_collapsed_count: int | None = None
    document_noun: str = "documentos"


def presentation_for_claim(claim: Any, view: VerificationView) -> ClaimCardPresentation:
    status = _status_value(getattr(claim, "status", None))
    cid = str(getattr(claim, "id", "") or "")
    decision = _decision_for(view, cid)
    basis, basis_known = _support_basis(view, decision)
    details = unique_evidence_details(claim)
    noun_sg, noun_pl = document_nouns(claim)
    label = _verification_label(status=status, basis_known=basis_known, basis=basis)
    limitation = _limitation(basis_known=basis_known, basis=basis)
    coverage = _coverage(
        status=status,
        basis_known=basis_known,
        basis=basis,
        noun_sg=noun_sg,
        noun_pl=noun_pl,
    )
    explanation = _explanation(status=status, basis_known=basis_known, basis=basis)
    card = ClaimCardPresentation(
        verification_label=label,
        limitation=limitation,
        coverage=coverage,
        explanation=explanation,
        evidence_detail=details,
        basis_known=basis_known,
        demotion=basis.demotion if basis_known and basis is not None else None,
        documents_consulted=basis.documents_consulted if basis_known and basis is not None else None,
        documents_reporting=basis.documents_supporting if basis_known and basis is not None else None,
        known_independent_count=basis.known_independent_count if basis_known and basis is not None else None,
        unknown_group_count=basis.unknown_group_count if basis_known and basis is not None else None,
        reprint_collapsed_count=basis.reprint_collapsed_count if basis_known and basis is not None else None,
        document_noun=noun_pl,
    )
    return card


def public_presentation_payload(card: ClaimCardPresentation) -> dict[str, Any]:
    return card.model_dump()


def public_verification_payload(sol: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sol:
        return None
    if sol.get("unresolved") is True:
        return {"unresolved": True}
    return None


def contains_llm_reason(payload: Any) -> bool:
    if isinstance(payload, dict):
        if "llm_reason" in payload:
            return True
        return any(contains_llm_reason(value) for value in payload.values())
    if isinstance(payload, list):
        return any(contains_llm_reason(item) for item in payload)
    return False


def contradicts_single_source_independence(status: str, card: ClaimCardPresentation) -> bool:
    if status != ClaimStatus.SINGLE_SOURCE.value:
        return False
    if card.verification_label.casefold() == "corroborado":
        return True
    blob = " ".join(
        part for part in (card.verification_label, card.limitation, card.coverage, card.explanation) if part
    )
    return bool(_POSITIVE_PLURAL.search(blob))


def authentic_primary_sounds_weak(card: ClaimCardPresentation) -> bool:
    blob = " ".join(
        part for part in (card.verification_label, card.limitation, card.coverage, card.explanation) if part
    )
    if _WEAK_CONFIDENCE.search(blob):
        return True
    return "un solo origen" in blob.casefold()


def unique_evidence_details(claim: Any) -> list[ClaimEvidenceDetail]:
    rows: list[ClaimEvidenceDetail] = []
    seen: set[str] = set()
    for item in getattr(claim, "evidence", None) or []:
        key = str(getattr(item, "source_item_id", "") or "")
        if not key:
            url = _evidence_url(item)
            key = url or str(id(item))
        if key in seen:
            continue
        seen.add(key)
        evidence_type = _enum_value(getattr(item, "evidence_type", None)) or EvidenceType.MENTIONS.value
        rows.append(
            ClaimEvidenceDetail(
                evidence_type=evidence_type,
                stance=_STANCE.get(evidence_type, evidence_type.lower()),
                name=_evidence_name(item),
                url=_evidence_url(item),
            )
        )
    return rows


def document_nouns(claim: Any) -> tuple[str, str]:
    flags: list[bool] = []
    for item in getattr(claim, "evidence", None) or []:
        source = _source_of(item)
        raw = getattr(source, "source_type", None) if source is not None else None
        flag = _outlet_flag(raw)
        if flag is not None:
            flags.append(flag)
    if flags and all(flags):
        return "medio", "medios"
    return "documento", "documentos"


def _verification_label(*, status: str, basis_known: bool, basis: SupportBasis | None) -> str:
    if not basis_known or basis is None:
        return _UNKNOWN_LABELS.get(status, status)
    if (basis.statement_evidence_class or "") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
        return AUTHENTIC_PRIMARY_LABEL
    if status == ClaimStatus.SUPPORTED.value and basis.known_independent_count >= 2:
        return "Corroborado"
    if status == ClaimStatus.SINGLE_SOURCE.value:
        demotion = basis.demotion
        if demotion == Demotion.UNPROVEN_INDEPENDENCE.value:
            return "Sin corroboración independiente"
        if demotion == Demotion.INSUFFICIENT_INDEPENDENCE.value:
            return "Un solo origen"
        if demotion == Demotion.MISSING_DOCUMENTARY_PRIMARY.value:
            return "Sin respaldo documental suficiente"
        if demotion == Demotion.MISSING_AUTHENTIC_PRIMARY.value:
            return "Sin publicación original del dicho"
        if basis.known_independent_count == 1:
            return "Un solo origen"
        return "Sin corroboración independiente"
    return _STATUS_LABELS.get(status, status)


def _limitation(*, basis_known: bool, basis: SupportBasis | None) -> str | None:
    if not basis_known or basis is None:
        return None
    access = basis.primary_access or ""
    demotion = basis.demotion
    if access == PrimaryAccess.FOUND_UNRELATED.value or demotion == Demotion.MISSING_DOCUMENTARY_PRIMARY.value:
        return UNRELATED_PRIMARY_LIMITATION
    if demotion == Demotion.MISSING_AUTHENTIC_PRIMARY.value:
        return "No hay publicación original auténtica del dicho."
    if demotion == Demotion.PARTIAL_SUPPORT.value:
        return "La evidencia solo sostiene parte de la proposición."
    return None


def _coverage(
    *,
    status: str,
    basis_known: bool,
    basis: SupportBasis | None,
    noun_sg: str,
    noun_pl: str,
) -> str:
    if not basis_known or basis is None:
        return UNKNOWN_COVERAGE
    consulted = int(basis.documents_consulted or 0)
    reporting = int(basis.documents_supporting or 0)
    parts: list[str] = []
    if consulted <= 0:
        parts.append("No hay documentos contabilizados en esta verificación.")
    else:
        head = _consulted_phrase(consulted, noun_sg, noun_pl)
        if reporting <= 0:
            parts.append(f"{head}; ninguno respalda la afirmación.")
        else:
            parts.append(f"{head}; {_report_phrase(reporting)}.")
    if status == ClaimStatus.SUPPORTED.value and basis.known_independent_count >= 2:
        parts.append(_independent_origins_phrase(basis.known_independent_count))
    return " ".join(parts)


def _explanation(*, status: str, basis_known: bool, basis: SupportBasis | None) -> str | None:
    if not basis_known or basis is None:
        return None
    if (basis.statement_evidence_class or "") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
        return None
    demotion = basis.demotion
    if demotion == Demotion.UNPROVEN_INDEPENDENCE.value:
        return "No se pudo establecer que aporten confirmaciones independientes."
    if demotion == Demotion.INSUFFICIENT_INDEPENDENCE.value:
        return "Se basan en la misma información original."
    if demotion == Demotion.MIXED_CLAIM_NO_EXCEPTION.value:
        return "La proposición sigue mixta; no se aplicó la excepción de declaración."
    if (
        status == ClaimStatus.SINGLE_SOURCE.value
        and basis.known_independent_count == 1
        and int(basis.documents_supporting or 0) > 1
    ):
        return "Se basan en la misma información original."
    return None


def _consulted_phrase(count: int, noun_sg: str, noun_pl: str) -> str:
    if count == 1:
        return f"Se consultó 1 {noun_sg}"
    return f"Se consultaron {count} {noun_pl}"


def _report_phrase(count: int) -> str:
    if count == 1:
        return "1 reporta la afirmación"
    return f"{count} reportan la afirmación"


def _independent_origins_phrase(count: int) -> str:
    if count == 1:
        return "1 origen independiente respalda esta afirmación."
    return f"{count} orígenes independientes respaldan esta afirmación."


def _decision_for(view: VerificationView, claim_id: str) -> dict[str, Any] | None:
    if not claim_id:
        return None
    raw = view.decision_by_claim_id.get(claim_id)
    return raw if isinstance(raw, dict) else None


def _support_basis(view: VerificationView, decision: dict[str, Any] | None) -> tuple[SupportBasis | None, bool]:
    if not view.paired or decision is None:
        return None, False
    raw = decision.get("support_basis")
    if not isinstance(raw, dict):
        return None, False
    try:
        return SupportBasis.model_validate(raw), True
    except Exception:
        return None, False


def _status_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value.value) if hasattr(value, "value") else str(value)


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value.value) if hasattr(value, "value") else str(value)


def _source_of(item: Any) -> Any | None:
    source_item = getattr(item, "source_item", None)
    if source_item is None:
        return None
    return getattr(source_item, "source", None)


def _evidence_name(item: Any) -> str | None:
    source = _source_of(item)
    name = getattr(source, "name", None) if source is not None else None
    if name:
        return str(name)
    source_item = getattr(item, "source_item", None)
    title = getattr(source_item, "title", None) if source_item is not None else None
    if title:
        return str(title)
    domain = getattr(source, "domain", None) if source is not None else None
    return str(domain) if domain else None


def _evidence_url(item: Any) -> str | None:
    source_item = getattr(item, "source_item", None)
    if source_item is not None:
        url = getattr(source_item, "canonical_url", None) or getattr(source_item, "url", None)
        if url:
            return str(url)
    url = getattr(item, "source_url", None)
    return str(url) if url else None


def _outlet_flag(raw: str | None) -> bool | None:
    if not raw or not str(raw).strip():
        return None
    token = str(raw).strip().lower().replace(" ", "_")
    folded = token.replace("í", "i").replace("ó", "o")
    if token in _OUTLET_TYPES or folded in _OUTLET_TYPES:
        return True
    if any(marker in folded for marker in _NON_OUTLET_MARKERS):
        return False
    return None
