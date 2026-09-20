from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import (
    Demotion,
    EvaluationState,
    PrimaryAccess,
    PropositionRole,
    PublicRendering,
    ReasonCode,
    StatementEvidenceClass,
    SupportBasis,
    SupportKind,
    decision_looks_like_skip,
    decision_was_evaluated,
    read_evaluation_state,
    read_public_rendering,
    read_reason_code,
)
from app.services.verification_outcome import VerificationView

UNKNOWN_COVERAGE = "No hay un desglose documental utilizable para esta versión."
NOT_EVALUATED_LABEL = "Sin evaluación disponible"
NOT_EVALUATED_COVERAGE = "No hay un desglose documental utilizable para esta versión."
AUTHENTIC_PRIMARY_LABEL = "Declaración confirmada"
UNRELATED_PRIMARY_LIMITATION = "El documento oficial consultado no sostiene esta proposición."

LABEL_CONFIRMED = "Confirmado"
LABEL_CONFIRMED_UTTERANCE = AUTHENTIC_PRIMARY_LABEL
LABEL_LIMITED = "Respaldo limitado"
LABEL_NOT_CONFIRMED = "No confirmado"
LABEL_DISPUTED = "En disputa"
LABEL_DISPROVEN = "Contradicho"
LABEL_PENDING = "Verificación pendiente"
LABEL_FAILED = "Verificación no completada"

_STANCE = {
    EvidenceType.SUPPORTS.value: "respalda",
    EvidenceType.QUALIFIES.value: "matiza",
    EvidenceType.CONTRADICTS.value: "contradice",
    EvidenceType.MENTIONS.value: "menciona",
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

_TECHNICAL_TOKENS = (
    "SINGLE_SOURCE",
    "SUPPORTED",
    "UNCERTAIN",
    "CONFLICTING",
    "DISPROVEN",
    "OUTDATED",
    "UNPROVEN_INDEPENDENCE",
    "INSUFFICIENT_INDEPENDENCE",
    "MISSING_DOCUMENTARY_PRIMARY",
    "MISSING_AUTHENTIC_PRIMARY",
    "PARTIAL_SUPPORT",
    "MIXED_CLAIM_NO_EXCEPTION",
    "INDEPENDENCE_NOT_ESTABLISHED",
    "SINGLE_KNOWN_ORIGIN",
    "DOCUMENTARY_PRIMARY",
    "PRIMARY_AUTHENTIC_UTTERANCE",
    "INDEPENDENT_CORROBORATION",
    "CONFLICTING_COMPARABLE_EVIDENCE",
    "COMPARABLE_DISPROOF",
    "CONTRADICTION_NOT_COMPARABLE",
    "INSUFFICIENT_EVIDENCE",
    "llm_reason",
)


class PresentationKind(StrEnum):
    """Stable public presentation family. Not a ClaimStatus."""

    CONFIRMED = "confirmed"
    CONFIRMED_UTTERANCE = "confirmed_utterance"
    LIMITED_SUPPORT = "limited_support"
    NOT_CONFIRMED = "not_confirmed"
    DISPUTED = "disputed"
    DISPROVEN = "disproven"
    UNEVALUATED = "unevaluated"
    UNEVALUATED_SKIPPED = "unevaluated_skipped"
    UNEVALUATED_PENDING = "unevaluated_pending"
    UNEVALUATED_FAILED = "unevaluated_failed"


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
    presentation_kind: str = PresentationKind.UNEVALUATED.value
    demotion: str | None = None
    documents_consulted: int | None = None
    documents_supporting: int | None = None
    known_independent_count: int | None = None
    unknown_group_count: int | None = None
    reprint_collapsed_count: int | None = None
    document_noun: str = "documentos"

    @property
    def documents_reporting(self) -> int | None:
        """Alias kept on the model for callers that still read the old name."""
        return self.documents_supporting


def presentation_for_claim(claim: Any, view: VerificationView) -> ClaimCardPresentation:
    """Deterministic public copy from the version's structured contract.

    Precedence (not accidental if-order):
    1. Evaluation availability for this version (pending / failed / skipped /
       unpaired / missing metadata).
    2. Final gated result (DISPROVEN, CONFLICTING).
    3. Role and scope restrictions (partial, mixed, utterance).
    4. Sufficiency of admitted support for the complete proposition.
    Never derives copy from llm_reason, assessment.reason or free final_reason.
    """
    status = _status_value(getattr(claim, "status", None))
    cid = str(getattr(claim, "id", "") or "")
    decision = _decision_for(view, cid)
    details = unique_evidence_details(claim)
    noun_sg, noun_pl = document_nouns(claim)
    basis, basis_known = _usable_basis(view, decision)
    kind = resolve_presentation_kind(
        claim,
        view=view,
        decision=decision,
        status=status,
        basis=basis,
        basis_known=basis_known,
    )
    label, explanation, limitation = copy_for_kind(
        kind,
        claim=claim,
        decision=decision,
        status=status,
        basis=basis,
        basis_known=basis_known,
    )
    coverage = _coverage(
        kind=kind,
        basis_known=basis_known,
        basis=basis,
        decision=decision,
        noun_sg=noun_sg,
        noun_pl=noun_pl,
    )
    counts = _count_fields(basis) if basis_known and basis is not None else _empty_counts()
    return ClaimCardPresentation(
        verification_label=label,
        limitation=limitation,
        coverage=coverage,
        explanation=explanation,
        evidence_detail=details,
        basis_known=basis_known and kind not in _UNEVALUATED_KINDS,
        presentation_kind=kind.value,
        demotion=basis.demotion if basis_known and basis is not None else None,
        document_noun=noun_pl,
        **counts,
    )


def public_presentation_payload(card: ClaimCardPresentation, *, include_internal: bool = False) -> dict[str, Any]:
    data = card.model_dump()
    data.pop("documents_reporting", None)
    if not include_internal:
        data.pop("demotion", None)
    return data


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


def public_copy_has_technical_tokens(card: ClaimCardPresentation) -> bool:
    blob = " ".join(
        part
        for part in (card.verification_label, card.limitation, card.coverage, card.explanation)
        if part
    )
    return any(token in blob for token in _TECHNICAL_TOKENS)


def contradicts_single_source_independence(status: str, card: ClaimCardPresentation) -> bool:
    if status != ClaimStatus.SINGLE_SOURCE.value:
        return False
    if card.presentation_kind == PresentationKind.CONFIRMED.value:
        return True
    if card.verification_label == LABEL_CONFIRMED:
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


def resolve_presentation_kind(
    claim: Any,
    *,
    view: VerificationView,
    decision: dict[str, Any] | None,
    status: str,
    basis: SupportBasis | None,
    basis_known: bool,
) -> PresentationKind:
    state = read_evaluation_state(decision)
    if state is EvaluationState.PENDING:
        return PresentationKind.UNEVALUATED_PENDING
    if state is EvaluationState.FAILED:
        return PresentationKind.UNEVALUATED_FAILED
    if state is EvaluationState.SKIPPED or decision_looks_like_skip(decision):
        return PresentationKind.UNEVALUATED_SKIPPED
    if decision is None:
        return PresentationKind.UNEVALUATED
    if not view.paired:
        return PresentationKind.UNEVALUATED
    if not decision_was_evaluated(decision):
        return PresentationKind.UNEVALUATED
    if not basis_known or basis is None:
        return PresentationKind.UNEVALUATED

    if status == ClaimStatus.DISPROVEN.value:
        return PresentationKind.DISPROVEN
    if status == ClaimStatus.CONFLICTING.value:
        return PresentationKind.DISPUTED

    code = read_reason_code(decision)
    rendering = read_public_rendering(decision)
    partial = _is_partial(decision=decision, basis=basis, code=code)
    mixed = _is_mixed(basis=basis, code=code)
    utterance = _is_utterance(claim, decision, basis)
    admitted = _has_admitted_support(claim, basis)

    if partial or mixed:
        return PresentationKind.LIMITED_SUPPORT
    if utterance:
        if _utterance_accredited(status=status, basis=basis, code=code):
            return PresentationKind.CONFIRMED_UTTERANCE
        if admitted:
            return PresentationKind.LIMITED_SUPPORT
        return PresentationKind.NOT_CONFIRMED
    if _sufficient_complete_proposition(
        status=status,
        basis=basis,
        code=code,
        rendering=rendering,
        admitted=admitted,
    ):
        return PresentationKind.CONFIRMED
    if admitted:
        return PresentationKind.LIMITED_SUPPORT
    return PresentationKind.NOT_CONFIRMED


def copy_for_kind(
    kind: PresentationKind,
    *,
    claim: Any,
    decision: dict[str, Any] | None,
    status: str,
    basis: SupportBasis | None,
    basis_known: bool,
) -> tuple[str, str | None, str | None]:
    if kind is PresentationKind.UNEVALUATED_PENDING:
        return (
            LABEL_PENDING,
            "La verificación de esta afirmación aún no está disponible. No hay un plazo anunciado.",
            None,
        )
    if kind is PresentationKind.UNEVALUATED_FAILED:
        return (
            LABEL_FAILED,
            "La verificación de esta afirmación no llegó a un resultado utilizable. Eso no equivale a un juicio de «no confirmado».",
            None,
        )
    if kind is PresentationKind.UNEVALUATED_SKIPPED:
        return (
            NOT_EVALUATED_LABEL,
            "Esta afirmación no se evaluó en esta ronda. Eso no es evidencia en contra ni anula un respaldo previo ya documentado.",
            None,
        )
    if kind is PresentationKind.UNEVALUATED:
        return (
            NOT_EVALUATED_LABEL,
            "No hay información suficiente sobre la evaluación de esta afirmación en esta versión.",
            None,
        )
    if kind is PresentationKind.DISPROVEN:
        return (
            LABEL_DISPROVEN,
            "La evidencia comparable desmiente esta proposición. Eso no atribuye mentira ni intención de engañar.",
            None,
        )
    if kind is PresentationKind.DISPUTED:
        return (
            LABEL_DISPUTED,
            "Hay versiones comparables y opuestas sobre esta proposición. No se toma una como confirmada.",
            None,
        )
    if kind is PresentationKind.CONFIRMED_UTTERANCE:
        return (
            LABEL_CONFIRMED_UTTERANCE,
            _utterance_explanation(claim),
            None,
        )
    if kind is PresentationKind.CONFIRMED:
        return (
            LABEL_CONFIRMED,
            _confirmed_explanation(basis, read_reason_code(decision), read_public_rendering(decision)),
            None,
        )
    if kind is PresentationKind.LIMITED_SUPPORT:
        explanation, limitation = _limited_copy(claim, decision, basis)
        return LABEL_LIMITED, explanation, limitation
    explanation, limitation = _not_confirmed_copy(status, decision, basis, basis_known)
    return LABEL_NOT_CONFIRMED, explanation, limitation


_UNEVALUATED_KINDS = {
    PresentationKind.UNEVALUATED,
    PresentationKind.UNEVALUATED_SKIPPED,
    PresentationKind.UNEVALUATED_PENDING,
    PresentationKind.UNEVALUATED_FAILED,
}


def _usable_basis(
    view: VerificationView, decision: dict[str, Any] | None
) -> tuple[SupportBasis | None, bool]:
    if not view.paired or decision is None:
        return None, False
    if not decision_was_evaluated(decision):
        return None, False
    raw = decision.get("support_basis")
    if not isinstance(raw, dict):
        return None, False
    try:
        return SupportBasis.model_validate(raw), True
    except Exception:
        return None, False


def _has_admitted_support(claim: Any, basis: SupportBasis | None) -> bool:
    if basis is not None and int(basis.documents_supporting or 0) > 0:
        return True
    for row in getattr(claim, "evidence", None) or []:
        if _enum_value(getattr(row, "evidence_type", None)) == EvidenceType.SUPPORTS.value:
            return True
    return False


def _is_partial(*, decision: dict[str, Any] | None, basis: SupportBasis, code: ReasonCode | None) -> bool:
    if code is ReasonCode.PARTIAL_SUPPORT:
        return True
    if (basis.demotion or "") == Demotion.PARTIAL_SUPPORT.value:
        return True
    verified = str((decision or {}).get("verified_scope") or "").strip()
    unsupported = str((decision or {}).get("unsupported_scope") or "").strip()
    if unsupported:
        return True
    evaluated = (basis.evaluated_canonical_text or "").strip()
    return bool(verified and evaluated and verified != evaluated)


def _is_mixed(*, basis: SupportBasis, code: ReasonCode | None) -> bool:
    if code is ReasonCode.MIXED_CLAIM_NO_EXCEPTION:
        return True
    return (basis.demotion or "") == Demotion.MIXED_CLAIM_NO_EXCEPTION.value


def _is_utterance(claim: Any, decision: dict[str, Any] | None, basis: SupportBasis | None) -> bool:
    role = str((decision or {}).get("proposition_role") or "")
    if role == PropositionRole.UTTERANCE.value:
        return True
    if (getattr(claim, "claim_type", None) or "") == "declaracion":
        return True
    if basis is not None and (basis.statement_evidence_class or "") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
        return True
    return False


def _utterance_accredited(*, status: str, basis: SupportBasis, code: ReasonCode | None) -> bool:
    if code is ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE:
        return True
    if (basis.statement_evidence_class or "") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
        return True
    if status == ClaimStatus.SUPPORTED.value and (basis.kind or "") == SupportKind.PRIMARY_SOURCE.value:
        return True
    return False


def _sufficient_complete_proposition(
    *,
    status: str,
    basis: SupportBasis,
    code: ReasonCode | None,
    rendering: PublicRendering | None,
    admitted: bool,
) -> bool:
    if status != ClaimStatus.SUPPORTED.value or not admitted:
        return False
    if code in {
        ReasonCode.INSUFFICIENT_EVIDENCE,
        ReasonCode.SINGLE_KNOWN_ORIGIN,
        ReasonCode.INDEPENDENCE_NOT_ESTABLISHED,
        ReasonCode.MISSING_DOCUMENTARY_PRIMARY,
        ReasonCode.MISSING_AUTHENTIC_PRIMARY,
        ReasonCode.PARTIAL_SUPPORT,
        ReasonCode.MIXED_CLAIM_NO_EXCEPTION,
        ReasonCode.CONTRADICTION_NOT_COMPARABLE,
    }:
        return False
    if rendering is not None:
        if rendering.categorical_allowed is not True:
            return False
        if rendering.attribution_required is True:
            return False
    if code in {ReasonCode.INDEPENDENT_CORROBORATION, ReasonCode.DOCUMENTARY_PRIMARY}:
        return True
    kind = basis.kind or ""
    if kind == SupportKind.INDEPENDENT_REPORTING.value and int(basis.known_independent_count or 0) >= 2:
        return True
    if kind == SupportKind.PRIMARY_SOURCE.value:
        return True
    if int(basis.known_independent_count or 0) >= 2:
        return True
    return False


def _utterance_explanation(claim: Any) -> str:
    speaker = str(getattr(claim, "subject", None) or "").strip()
    text = str(getattr(claim, "canonical_text", None) or "").strip()
    if speaker and text:
        return (
            f"Se acreditó que {speaker} hizo esta declaración: «{text}». "
            "Eso no comprueba el contenido de lo dicho ni una reacción adicional."
        )
    if text:
        return (
            f"Se acreditó el acto de declaración: «{text}». "
            "Eso no comprueba el contenido de lo dicho ni una reacción adicional."
        )
    return (
        "Se acreditó el acto de declaración. "
        "Eso no comprueba el contenido de lo dicho ni una reacción adicional."
    )


def _confirmed_explanation(
    basis: SupportBasis | None,
    code: ReasonCode | None,
    rendering: PublicRendering | None,
) -> str:
    if _may_say_independent(rendering=rendering, basis=basis, code=code):
        return "La proposición completa quedó respaldada por corroboración independiente."
    if code is ReasonCode.DOCUMENTARY_PRIMARY or (
        basis is not None and (basis.kind or "") == SupportKind.PRIMARY_SOURCE.value
    ):
        return "La proposición completa quedó respaldada por una fuente primaria documental."
    return "La evaluación acreditó respaldo suficiente para la proposición completa, dentro de su alcance."


def _may_say_independent(
    *,
    rendering: PublicRendering | None,
    basis: SupportBasis | None,
    code: ReasonCode | None,
) -> bool:
    if rendering is not None and rendering.independent_confirmation_language_allowed is False:
        return False
    if rendering is not None and rendering.independent_confirmation_language_allowed is True:
        return True
    if code is ReasonCode.INDEPENDENT_CORROBORATION:
        return True
    if (
        basis is not None
        and (basis.kind or "") == SupportKind.INDEPENDENT_REPORTING.value
        and int(basis.known_independent_count or 0) >= 2
    ):
        return True
    return bool(basis is not None and int(basis.known_independent_count or 0) >= 2)


def _limited_copy(
    claim: Any, decision: dict[str, Any] | None, basis: SupportBasis
) -> tuple[str, str | None]:
    code = read_reason_code(decision)
    demotion = basis.demotion or ""
    verified = str((decision or {}).get("verified_scope") or "").strip()
    unsupported = str((decision or {}).get("unsupported_scope") or "").strip()
    if code is ReasonCode.PARTIAL_SUPPORT or demotion == Demotion.PARTIAL_SUPPORT.value:
        if verified and unsupported:
            explanation = (
                f"El respaldo alcanza solo a esta parte: «{verified}». "
                f"Quedó sin establecer, sin darlo por falso: «{unsupported}»."
            )
        elif verified:
            explanation = (
                f"El respaldo alcanza solo a esta parte: «{verified}». "
                "El resto del compuesto no está identificado y no se da por falso."
            )
        else:
            explanation = (
                "La evidencia solo sostiene parte de la proposición. "
                "No está identificado qué fragmento quedó establecido, y el resto no se da por falso."
            )
        return explanation, None
    if code is ReasonCode.MIXED_CLAIM_NO_EXCEPTION or demotion == Demotion.MIXED_CLAIM_NO_EXCEPTION.value:
        return (
            "La proposición sigue mixta: el respaldo de un acto no confirma todo el compuesto.",
            None,
        )
    limitation = _primary_limitation(basis)
    if code is ReasonCode.MISSING_DOCUMENTARY_PRIMARY or demotion == Demotion.MISSING_DOCUMENTARY_PRIMARY.value:
        return (
            "Hay mención o consulta documental, pero falta una fuente primaria que sostenga la proposición.",
            limitation or UNRELATED_PRIMARY_LIMITATION,
        )
    if code is ReasonCode.MISSING_AUTHENTIC_PRIMARY or demotion == Demotion.MISSING_AUTHENTIC_PRIMARY.value:
        return (
            "Hay atribución del dicho, pero no hay publicación original auténtica que lo acredite.",
            limitation or "No hay publicación original auténtica del dicho.",
        )
    if (
        code is ReasonCode.INDEPENDENCE_NOT_ESTABLISHED
        or demotion == Demotion.UNPROVEN_INDEPENDENCE.value
    ):
        return (
            "Hay documentos que se refieren a la proposición, pero no quedó demostrada la independencia de las procedencias.",
            limitation,
        )
    if (
        code is ReasonCode.SINGLE_KNOWN_ORIGIN
        or demotion == Demotion.INSUFFICIENT_INDEPENDENCE.value
    ):
        return (
            "Hay respaldo admitido, pero una restricción de procedencia impide presentar la proposición completa como confirmada. Varios documentos no equivalen a corroboración independiente.",
            limitation,
        )
    if _is_utterance(claim, decision, basis):
        return (
            "Hay respaldo admitido del acto de declaración, pero no alcanza para presentarlo como declaración confirmada.",
            limitation,
        )
    return (
        "Hay respaldo admitido, pero una restricción de procedencia, alcance o autoridad impide presentar la proposición completa como confirmada.",
        limitation,
    )


def _not_confirmed_copy(
    status: str,
    decision: dict[str, Any] | None,
    basis: SupportBasis | None,
    basis_known: bool,
) -> tuple[str, str | None]:
    code = read_reason_code(decision)
    limitation = _primary_limitation(basis) if basis_known and basis is not None else None
    if status == ClaimStatus.OUTDATED.value:
        return (
            "Hay una versión más reciente de esta proposición. Eso no prueba que el dato anterior fuera falso.",
            limitation,
        )
    if code is ReasonCode.CONTRADICTION_NOT_COMPARABLE:
        return (
            "La evaluación no permite confirmar esta proposición. Una contradicción citada no era comparable.",
            limitation,
        )
    return (
        "La evaluación no permite confirmar esta proposición. Eso no equivale a desmentirla.",
        limitation,
    )


def _primary_limitation(basis: SupportBasis | None) -> str | None:
    if basis is None:
        return None
    access = basis.primary_access or ""
    demotion = basis.demotion or ""
    if demotion == Demotion.MISSING_DOCUMENTARY_PRIMARY.value:
        if access == PrimaryAccess.NOT_FOUND.value:
            return "No se localizó una fuente primaria que permita comprobar la afirmación."
        if access == PrimaryAccess.ACCESS_FAILED.value:
            return "No se pudo acceder al contenido de la fuente primaria."
        return UNRELATED_PRIMARY_LIMITATION
    if access == PrimaryAccess.ACCESS_FAILED.value and demotion == Demotion.MISSING_AUTHENTIC_PRIMARY.value:
        return "No se pudo acceder al contenido de la fuente primaria."
    if access == PrimaryAccess.FOUND_UNRELATED.value:
        return UNRELATED_PRIMARY_LIMITATION
    if demotion == Demotion.MISSING_AUTHENTIC_PRIMARY.value:
        return "No hay publicación original auténtica del dicho."
    return None


def _coverage(
    *,
    kind: PresentationKind,
    basis_known: bool,
    basis: SupportBasis | None,
    decision: dict[str, Any] | None,
    noun_sg: str,
    noun_pl: str,
) -> str:
    if kind in _UNEVALUATED_KINDS or not basis_known or basis is None:
        return UNKNOWN_COVERAGE
    consulted = int(basis.documents_consulted or 0)
    supporting = int(basis.documents_supporting or 0)
    parts: list[str] = []
    if consulted <= 0:
        parts.append("No hay documentos contabilizados en esta verificación.")
    else:
        head = _consulted_phrase(consulted, noun_sg, noun_pl)
        if supporting <= 0:
            parts.append(f"{head}; ninguno respalda la proposición.")
        else:
            parts.append(f"{head}; {_support_phrase(supporting, noun_sg, noun_pl)}.")
    known = int(basis.known_independent_count or 0)
    if known >= 2 and kind is PresentationKind.CONFIRMED and _may_say_independent(
        rendering=read_public_rendering(decision),
        basis=basis,
        code=read_reason_code(decision),
    ):
        parts.append(_independent_origins_phrase(known))
    unknown = int(basis.unknown_group_count or 0)
    if unknown > 0 and kind is not PresentationKind.CONFIRMED:
        parts.append(f"{unknown} grupo(s) de procedencia siguen sin acreditarse.")
    return " ".join(parts)


def _count_fields(basis: SupportBasis) -> dict[str, int | None]:
    return {
        "documents_consulted": int(basis.documents_consulted or 0),
        "documents_supporting": int(basis.documents_supporting or 0),
        "known_independent_count": int(basis.known_independent_count or 0),
        "unknown_group_count": int(basis.unknown_group_count or 0),
        "reprint_collapsed_count": int(basis.reprint_collapsed_count or 0),
    }


def _empty_counts() -> dict[str, int | None]:
    return {
        "documents_consulted": None,
        "documents_supporting": None,
        "known_independent_count": None,
        "unknown_group_count": None,
        "reprint_collapsed_count": None,
    }


def _consulted_phrase(count: int, noun_sg: str, noun_pl: str) -> str:
    if count == 1:
        return f"Se consultó 1 {noun_sg}"
    return f"Se consultaron {count} {noun_pl}"


def _support_phrase(count: int, noun_sg: str, noun_pl: str) -> str:
    if count == 1:
        return f"1 {noun_sg} respalda la proposición"
    return f"{count} {noun_pl} respaldan la proposición"


def _independent_origins_phrase(count: int) -> str:
    if count == 1:
        return "1 procedencia independiente conocida figura en el contrato."
    return f"{count} procedencias independientes conocidas figuran en el contrato."


def _decision_for(view: VerificationView, claim_id: str) -> dict[str, Any] | None:
    if not claim_id:
        return None
    raw = view.decision_by_claim_id.get(claim_id)
    return raw if isinstance(raw, dict) else None


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
