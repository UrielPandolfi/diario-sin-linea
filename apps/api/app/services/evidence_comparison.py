"""Admission of contradictions. Missing coordinates are not evidence of falsity."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.core.text import excerpt_in_source, normalize_name, token_set
from app.services.claim_meaning import attributed_statement, temporal_comparison

COMPARISON_POLICY_VERSION = "proposition-comparison-1"
_APPROX = re.compile(r"cerca|cercano|alrededor|aproximad|aprox|\bunas?\b|\bunos?\b|~", re.I)
_NEGATION = re.compile(r"\bno\b|\bnunca\b|\bdesminti[oó]\b|\bfals[oa]\b", re.I)
_MONTH = re.compile(
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|\d{4}-\d{2}",
    re.I,
)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
    re.I,
)
_NUMERIC = re.compile(r"\d+(?:[.,]\d+)?")
_BASIS_PATTERNS = (
    (re.compile(r"puntos?\s+porcentuales|\bpp\b", re.I), "pp"),
    (re.compile(r"inter\s*anual|\ba/a\b", re.I), "interanual"),
    (re.compile(r"mensual|\bm/m\b", re.I), "mensual"),
    (re.compile(r"acumulad", re.I), "acumulado"),
)
_SCOPE_STOP = {
    "que", "del", "una", "unos", "unas", "para", "con", "por", "los", "las",
    "el", "la", "de", "en", "un", "al", "es", "fue", "ser", "como", "este",
    "esta", "estos", "estas", "hay", "hubo", "son", "era", "registraron",
    "confirmaron", "se", "heridos", "muertos", "personas", "cantidad",
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
    "nueve", "diez", "once", "doce",
}


def _decimal(value: str):
    try:
        result = Decimal(value.replace(",", ".").strip().rstrip("%"))
        return result if result.is_finite() else None
    except (InvalidOperation, AttributeError):
        return None


def _key(value: str) -> str:
    text = normalize_name(value)
    # "Nacional" alone does not identify a country.
    return {"inflacion": "ipc", "indice de precios al consumidor": "ipc"}.get(text, text)


def _count_decimal(value: str):
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", value.strip()):
        value = value.replace(".", "")
    return _decimal(value)


def _grounded(measure, fragment: str, *, count: bool = False) -> bool:
    if measure is None:
        return False
    folded = normalize_name(fragment)
    if any(word in normalize_name(measure.indicator) for word in ("ipc", "inflacion", "indice de precios")):
        for category in ("nucleo", "regulados", "estacionales"):
            if category in folded and category not in normalize_name(measure.indicator):
                return False
    for field in (measure.indicator, measure.scope, measure.period):
        if not field.strip() or normalize_name(field) not in folded:
            return False
    # Units must be explicit too; do not compare monthly with annual/cumulative data.
    if not measure.unit.strip() or any(token not in folded for token in normalize_name(measure.unit).split()):
        return False
    if "%" in measure.unit and "%" not in fragment:
        return False
    if "%" in measure.unit:
        percentages = re.findall(r"(-?\d+(?:[.,]\d+)?)\s*%", fragment)
        if len(percentages) != 1 or _decimal(percentages[0]) != _decimal(measure.value):
            return False
    numbers = re.findall(r"(?<!\w)-?\d+(?:[.,]\d+)?", fragment)
    parse = _count_decimal if count else _decimal
    return parse(measure.value) is not None and parse(measure.value) in [parse(v) for v in numbers]


def valid_contradiction(claim, comparison, *, body: str, body_source: str) -> tuple[bool, str]:
    if comparison is None:
        return False, "missing_comparison"
    if comparison.basis not in {"incompatible_value", "explicit_negation"}:
        return False, "not_a_contradiction"
    text = claim.canonical_text or ""
    if not comparison.reason.strip():
        return False, "missing_reason"
    if not comparison.claim_fragment.strip() or not excerpt_in_source(comparison.claim_fragment, text):
        return False, "ungrounded_claim"
    if not comparison.evidence_fragment.strip() or not excerpt_in_source(comparison.evidence_fragment, body):
        return False, "ungrounded_evidence"
    if body_source != "extracted_html":
        return False, "original_document_unavailable"
    statement = attributed_statement(text) or claim.claim_type == "declaracion"
    if statement:
        if comparison.proposition != "statement" or comparison.basis != "explicit_negation":
            return False, "statistics_do_not_refute_attribution"
        subject = normalize_name(claim.subject or "")
        if not subject or subject not in normalize_name(comparison.evidence_fragment):
            return False, "speaker_not_established"
        if not attributed_statement(comparison.evidence_fragment):
            return False, "statement_not_addressed"
    if comparison.basis == "incompatible_value":
        if comparison.proposition != "statistic" or statement:
            return False, "wrong_proposition"
        left, right = comparison.claim_measurement, comparison.evidence_measurement
        if not _grounded(left, comparison.claim_fragment) or not _grounded(right, comparison.evidence_fragment):
            return False, "missing_measurement_coordinates"
        for field in ("indicator", "unit", "scope", "period"):
            if _key(getattr(left, field)) != _key(getattr(right, field)):
                return False, "different_" + field
        if not re.search(r"\b(?:19|20)\d{2}\b", left.period) or not _MONTH.search(left.period):
            return False, "period_not_explicit"
        a, b = _decimal(left.value), _decimal(right.value)
        if a == b:
            return False, "same_value"
        if _APPROX.search(text):
            # Rounding to the precision actually expressed can only REJECT a
            # contradiction. Being outside that rounding cell never proves one.
            precision = Decimal(1).scaleb(a.as_tuple().exponent)
            if b.quantize(precision, rounding=ROUND_HALF_UP) == a:
                return False, "compatible_rounding"
            if comparison.approximation != "incompatible" or not (comparison.approximation_reason or "").strip():
                return False, "approximation_unresolved"
        return True, "comparable_incompatible_observation"
    if temporal_comparison(text) or ("%" in text and not statement):
        return False, "measurement_comparison_required"
    if normalize_name(comparison.claim_fragment) != normalize_name(text):
        return False, "partial_proposition"
    if not _NEGATION.search(comparison.evidence_fragment):
        return False, "no_explicit_negation"
    if len(token_set(text) & token_set(comparison.evidence_fragment)) < 3:
        return False, "unrelated_negation"
    return True, "explicit_counterstatement"


def valid_count_support(claim, comparison, *, body: str, body_source: str) -> tuple[bool, str]:
    """A documentary count must identify the counted category, scope and period.

    Reporting somebody's number is handled separately; this gate admits evidence
    of the underlying count. Unknown coordinates cannot establish full support.
    """
    if comparison is None or comparison.basis != "same_value" or comparison.proposition != "statistic":
        return False, "count_comparison_missing"
    if body_source != "extracted_html":
        return False, "original_document_unavailable"
    if not excerpt_in_source(comparison.claim_fragment, claim.canonical_text):
        return False, "ungrounded_claim"
    if not excerpt_in_source(comparison.evidence_fragment, body):
        return False, "ungrounded_evidence"
    a, b = comparison.claim_measurement, comparison.evidence_measurement
    if not _grounded(a, comparison.claim_fragment, count=True) or not _grounded(b, comparison.evidence_fragment, count=True):
        return False, "missing_measurement_coordinates"
    for field in ("indicator", "unit", "scope", "period"):
        if _key(getattr(a, field)) != _key(getattr(b, field)):
            return False, "different_" + field
    # A number elsewhere in a paragraph is not a count of this unit.
    for measurement, fragment in ((a, comparison.claim_fragment), (b, comparison.evidence_fragment)):
        pairs = re.findall(r"(\d+(?:[.,]\d+)*)\s+([\wáéíóúñ]+)", fragment, re.I)
        if not any(_count_decimal(value) == _count_decimal(measurement.value)
                   and normalize_name(unit) == normalize_name(measurement.unit) for value, unit in pairs):
            return False, "count_category_mismatch"
    if _count_decimal(a.value) != _count_decimal(b.value):
        return False, "count_value_not_established"
    return True, "comparable_count_support"


def _field(claim, name: str) -> str:
    return (getattr(claim, name, None) or "").strip()


def _is_utterance(claim) -> bool:
    from app.schemas.editorial_evidence import PropositionRole
    from app.services.claim_coverage import proposition_role_for

    if _field(claim, "claim_type").lower() == "declaracion" or attributed_statement(_field(claim, "canonical_text")):
        return True
    try:
        return proposition_role_for(claim) == PropositionRole.UTTERANCE
    except Exception:
        return False


def is_quantitative_proposition(claim) -> bool:
    if _field(claim, "unit"):
        return True
    if _field(claim, "claim_type").lower() in {"cifra", "estadistica", "presupuesto"}:
        return True
    return bool(_NUMERIC.search(_field(claim, "normalized_value")))


def _period_tokens(text: str, occurred_at=None) -> set[str]:
    tokens: set[str] = set()
    if occurred_at is not None:
        moment = occurred_at.date().isoformat() if hasattr(occurred_at, "date") else str(occurred_at)
        if moment:
            tokens.add(f"at:{moment}")
    folded = normalize_name(text or "")
    tokens.update(f"y:{year}" for year in _YEAR.findall(folded))
    tokens.update(f"d:{day} {month}" for day, month in _DAY_MONTH.findall(folded))
    months = {match.group(0).casefold() for match in _MONTH.finditer(folded) if match.group(0) and not match.group(0)[:4].isdigit()}
    tokens.update(f"m:{month}" for month in months)
    return tokens


def _claim_period_tokens(claim) -> set[str]:
    return _period_tokens(
        " ".join(filter(None, [_field(claim, "canonical_text"), _field(claim, "object_text"), _field(claim, "unit")])),
        getattr(claim, "occurred_at", None),
    )


def _measurement_basis(claim) -> str:
    blob = " ".join(filter(None, [_field(claim, "unit"), _field(claim, "canonical_text"), _field(claim, "object_text")]))
    for pattern, label in _BASIS_PATTERNS:
        if pattern.search(blob):
            return label
    unit = _field(claim, "unit")
    return _key(unit) if unit else ""


def _scope_tokens(claim) -> set[str] | None:
    raw = _field(claim, "object_text")
    if not raw:
        return None
    folded = _NUMERIC.sub(" ", normalize_name(raw))
    unit = _field(claim, "unit")
    if unit:
        folded = folded.replace(normalize_name(unit), " ")
    tokens = token_set(folded) - _SCOPE_STOP
    return tokens or None


def _compare_optional(left: str, right: str, *, missing: str, different: str) -> str | None:
    if left and right:
        if _key(left) != _key(right):
            return different
        return None
    if left or right:
        return missing
    return missing


def contradiction_excerpt_incomparable(claim, excerpt: str) -> tuple[bool, str]:
    """True when CONTRADICTS is known not to address this claim's proposition."""
    excerpt = excerpt or ""
    if _is_utterance(claim):
        if not attributed_statement(excerpt):
            return True, "statistics_do_not_refute_attribution"
        subject = _field(claim, "subject")
        if subject and _key(subject) not in normalize_name(excerpt):
            return True, "speaker_not_established"
        if not attributed_statement(excerpt):
            return True, "statement_not_addressed"
        return False, "statement_addressed"
    claim_period = _period_tokens(
        " ".join(filter(None, [_field(claim, "canonical_text"), _field(claim, "object_text")])),
        getattr(claim, "occurred_at", None),
    )
    excerpt_period = _period_tokens(excerpt)
    stated_claim = {token for token in claim_period if not token.startswith("at:")}
    stated_excerpt = {token for token in excerpt_period if not token.startswith("at:")}
    if stated_claim and stated_excerpt and stated_claim != stated_excerpt:
        return True, "different_period"
    left_basis = _measurement_basis(claim)
    right_blob = excerpt
    right_basis = ""
    for pattern, label in _BASIS_PATTERNS:
        if pattern.search(right_blob):
            right_basis = label
            break
    if left_basis and right_basis and left_basis != right_basis:
        return True, "different_unit"
    return False, "not_known_incomparable"


def mixed_evidence_supports_conflict(claim) -> bool:
    from app.domain.enums import EvidenceType

    types = {row.evidence_type for row in getattr(claim, "evidence", []) or []}
    if EvidenceType.SUPPORTS not in types:
        return False
    for row in claim.evidence:
        if row.evidence_type != EvidenceType.CONTRADICTS:
            continue
        incomparable, _reason = contradiction_excerpt_incomparable(claim, getattr(row, "excerpt", None) or "")
        if not incomparable:
            return True
    return False


def conflict_comparability(left, right) -> tuple[bool, str]:
    """Whether two claims can compete as alternatives of one proposition.

    Missing coordinates do not prove equality. A known difference is incomparable.
    This is not the DISPROVEN gate: it does not require grounded Measurement.
    """
    left_u, right_u = _is_utterance(left), _is_utterance(right)
    if left_u != right_u:
        return False, "utterance_versus_content"
    if left_u and right_u:
        return False, "distinct_speech_acts"

    subject = _compare_optional(
        _field(left, "subject"),
        _field(right, "subject"),
        missing="missing_subject",
        different="different_subject",
    )
    if subject:
        return False, subject
    predicate = _compare_optional(
        _field(left, "predicate"),
        _field(right, "predicate"),
        missing="missing_predicate",
        different="different_predicate",
    )
    if predicate:
        return False, predicate

    quantitative = is_quantitative_proposition(left) or is_quantitative_proposition(right)
    left_basis, right_basis = _measurement_basis(left), _measurement_basis(right)
    if quantitative:
        if not left_basis or not right_basis:
            return False, "missing_unit"
        if left_basis != right_basis:
            return False, "different_unit"
    elif left_basis and right_basis and left_basis != right_basis:
        return False, "different_unit"

    left_at = getattr(left, "occurred_at", None)
    right_at = getattr(right, "occurred_at", None)
    left_period = {token for token in _claim_period_tokens(left) if not token.startswith("at:")}
    right_period = {token for token in _claim_period_tokens(right) if not token.startswith("at:")}
    if left_period and right_period and left_period != right_period:
        return False, "different_period"
    if left_at is not None and right_at is not None:
        if left_at != right_at:
            return False, "different_occurred_at"
    elif left_at is not None or right_at is not None:
        return False, "missing_occurred_at"
    elif quantitative and (not left_period or not right_period):
        return False, "missing_period"

    left_scope, right_scope = _scope_tokens(left), _scope_tokens(right)
    if left_scope and right_scope:
        extra_left = left_scope - right_scope
        extra_right = right_scope - left_scope
        if extra_left and extra_right:
            return False, "different_scope"
    elif left_scope or right_scope:
        return False, "missing_scope"

    return True, "comparable_proposition"
