"""Admission of contradictions. Missing coordinates are not evidence of falsity."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.core.text import excerpt_in_source, normalize_name, token_set
from app.services.claim_meaning import attributed_statement, temporal_comparison

COMPARISON_POLICY_VERSION = "proposition-comparison-1"
_APPROX = re.compile(r"cerca|cercano|alrededor|aproximad|aprox|\bunas?\b|\bunos?\b|~", re.I)
_NEGATION = re.compile(r"\bno\b|\bnunca\b|\bdesminti[oó]\b|\bfals[oa]\b", re.I)
_MONTH = re.compile(r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\d{4}-\d{2}", re.I)


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
