from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from app.core.source_content import body_source_from_item
from app.core.text import excerpt_in_source, normalize_name, sha256_text, token_set
from app.core.urls import canonicalize_url
from app.domain.enums import ClaimImportance, EventSourceRelation, EvidenceType
from app.models import Claim, Event, SourceItem
from app.schemas.claims import ExtractedClaim, ExtractedEvidence
from app.schemas.editorial_evidence import (
    CONTRACT_VERSION,
    CoverageContract,
    CoverageMatch,
    CoverageSignal,
    DroppedExtracted,
    EvaluatedClaim,
    ExpectedCentral,
    GapReason,
    PropositionRole,
)
from app.services.verification_policy import canonicalize_claim_type


def _assertion_key(claim: Claim | ExtractedClaim) -> str:
    from app.services.claim_service import assertion_key_for

    return assertion_key_for(claim)

_AGE_RE = re.compile(r"\b(\d{1,2})\s*a(?:ñ|n)os\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_URL_RE = re.compile(r"https?://[^\s\]>)+]+", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[\"“”«»]([^\"“”«»]{12,})[\"“”«»]")

_UTTERANCE_MARKERS = (
    "dijo",
    "afirmó",
    "afirmo",
    "declaró",
    "declaro",
    "sostuvo",
    "señaló",
    "senalo",
    "aseguró",
    "aseguro",
    "denunció que",
    "denuncio que",
)
_EXISTENCE_MARKERS = (
    "denuncia penal",
    "presentó una denuncia",
    "presento una denuncia",
    "fue denunciado",
    "fue denunciada",
    "radicó una denuncia",
    "sobreseimiento",
    "sobreseyó",
    "sobreseyó",
    "desestimó el recurso",
)
_EFFECTIVE_MARKERS = (
    "entra en vigencia",
    "entrada en vigencia",
    "entra en vigor",
    "vigencia",
)
_SCOPE_MARKERS = (
    "delitos graves",
    "alcance del régimen",
    "alcance del regimen",
    "régimen penal",
    "regimen penal",
)
_ACCUSATION_TRUTH_MARKERS = (
    "cometió",
    "cometio",
    "es culpable",
    "traicionó",
    "traiciono",
)
_JUDICIAL_MARKERS = (
    "suspendió",
    "suspendio",
    "hizo lugar",
    "medida cautelar",
    "dictó sentencia",
    "dicto sentencia",
    "condenó a",
    "condeno a",
    "condenó al",
    "condeno al",
)
_SAID_SPLIT_RE = re.compile(
    r"\s+(?:y\s+)?(?:dijo|afirmó|afirmo|declaró|declaro|sostuvo|señaló|senalo|aseguró|aseguro)\b",
    re.IGNORECASE,
)
_FRAME_SKIP = (
    "defendió a los delincuentes",
    "defendio a los delincuentes",
    "profunda crítica",
    "profundas criticas",
    "polémica medida",
    "polemica medida",
)
_MENORES = "menor"
_DESDE = "desde"


def claims_fingerprint(claims: list[Claim]) -> str:
    rows: list[str] = []
    for claim in sorted(claims, key=lambda row: str(row.id)):
        rows.append(
            f"{claim.id}|{_assertion_key(claim)}|{normalize_name(claim.canonical_text or '')}"
        )
    return sha256_text("\n".join(rows))


def evaluated_claims_payload(claims: list[Claim]) -> list[EvaluatedClaim]:
    rows: list[EvaluatedClaim] = []
    for claim in sorted(claims, key=lambda row: str(row.id)):
        rows.append(
            EvaluatedClaim(
                claim_id=str(claim.id),
                canonical_text=claim.canonical_text,
                assertion_key=_assertion_key(claim),
                status=claim.status.value,
                role=proposition_role_for(claim).value,
            )
        )
    return rows


def source_quality_rows(event: Event) -> list[dict]:
    rows: list[dict] = []
    for link in event.event_sources:
        item = link.source_item
        if item is None:
            continue
        rows.append(
            {
                "source_item_id": str(item.id),
                "body_source": body_source_from_item(item),
                "url": item.url,
                "is_primary": bool(link.is_primary),
            }
        )
    return rows


def _lead_text(event: Event) -> str:
    links = [link for link in event.event_sources if link.source_item is not None]
    links.sort(key=lambda link: (not link.is_primary, str(link.source_item_id)))
    for link in links:
        if link.relation_type == EventSourceRelation.INITIAL or link.is_primary:
            item = link.source_item
            if item is None:
                continue
            body = (item.clean_text or "").strip()
            if not body:
                return (item.title or "").strip()
            return body.split("\n\n")[0][:800]
    if links:
        item = links[0].source_item
        if item is not None:
            return ((item.clean_text or item.title or "").split("\n\n")[0])[:800]
    return ""


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _is_frame_only(text: str) -> bool:
    folded = normalize_name(text)
    if _has_any(folded, _EXISTENCE_MARKERS) or _has_any(folded, _UTTERANCE_MARKERS):
        return False
    return _has_any(folded, _FRAME_SKIP)


def proposition_role_for(claim: Claim | ExtractedClaim | str, claim_type: str | None = None) -> PropositionRole:
    if not isinstance(claim, str):
        text = claim.canonical_text or ""
        kind = canonicalize_claim_type(getattr(claim, "claim_type", None) or claim_type)
    else:
        text = claim
        kind = canonicalize_claim_type(claim_type)
    folded = normalize_name(text)
    mixed = is_mixed_proposition(text, kind)
    if mixed:
        return PropositionRole.OTHER
    if _has_any(folded, _ACCUSATION_TRUTH_MARKERS) and not _has_any(folded, _EXISTENCE_MARKERS):
        return PropositionRole.ACCUSATION_TRUTH
    if kind == "declaracion" or _has_any(folded, _UTTERANCE_MARKERS) or _QUOTE_RE.search(text or ""):
        if _has_any(folded, _EFFECTIVE_MARKERS) or _has_any(folded, _SCOPE_MARKERS):
            return PropositionRole.OTHER
        return PropositionRole.UTTERANCE
    if _has_any(folded, _EFFECTIVE_MARKERS):
        return PropositionRole.EFFECTIVE_DATE
    if _has_any(folded, _SCOPE_MARKERS):
        return PropositionRole.NORMATIVE_SCOPE
    if _has_any(folded, _EXISTENCE_MARKERS):
        return PropositionRole.EXISTENCE
    if kind == "documento":
        return PropositionRole.OTHER
    return PropositionRole.OTHER


def is_mixed_proposition(text: str, claim_type: str | None = None) -> bool:
    folded = normalize_name(text)
    quote = bool(_QUOTE_RE.search(text or ""))
    utterance = (
        canonicalize_claim_type(claim_type) == "declaracion"
        or _has_any(folded, _UTTERANCE_MARKERS)
        or quote
    )
    extra = _has_any(folded, _EFFECTIVE_MARKERS) or _has_any(folded, _SCOPE_MARKERS)
    existence = _has_any(folded, _EXISTENCE_MARKERS)
    judicial = _has_any(normalize_name(_QUOTE_RE.sub(" ", text or "")), _JUDICIAL_MARKERS)
    if utterance and extra:
        return True
    if utterance and judicial:
        return True
    if existence and quote and _has_any(folded, _UTTERANCE_MARKERS):
        return True
    if existence and _has_any(folded, _ACCUSATION_TRUTH_MARKERS):
        return True
    return False


def split_compound_extracted(raw: ExtractedClaim) -> list[ExtractedClaim]:
    text = (raw.canonical_text or "").strip()
    if not is_mixed_proposition(text, raw.claim_type):
        return [raw]
    folded = normalize_name(text)
    parts: list[ExtractedClaim] = []

    def _copy(*, canonical: str, claim_type: str, subject: str | None, predicate: str, object_text: str) -> None:
        parts.append(
            ExtractedClaim(
                canonical_text=canonical,
                claim_type=claim_type,
                importance=raw.importance,
                subject=subject or raw.subject,
                predicate=predicate,
                object_text=object_text,
                normalized_value=raw.normalized_value,
                unit=raw.unit,
                occurred_at=raw.occurred_at,
                evidence=list(raw.evidence),
            )
        )

    if _has_any(folded, _UTTERANCE_MARKERS) or canonicalize_claim_type(raw.claim_type) == "declaracion" or _QUOTE_RE.search(text):
        said = text
        if re.search(r"\s+y\s+", text) and _has_any(folded, _EFFECTIVE_MARKERS + _SCOPE_MARKERS):
            said = re.split(r"\s+y\s+", text, maxsplit=1)[0].strip()
        said = re.split(r"(?i)\s+que entra en vigencia.*", said)[0].strip()
        said = re.split(r"(?i)\s+que el r[eé]gimen se aplica.*", said)[0].strip()
        if _has_any(normalize_name(said), _EFFECTIVE_MARKERS + _SCOPE_MARKERS):
            said = f"{raw.subject or 'La figura pública'} hizo una declaración pública"
        if _has_any(folded, _JUDICIAL_MARKERS):
            said = _utterance_span(text, raw.subject)
        _copy(
            canonical=said,
            claim_type="declaracion",
            subject=raw.subject,
            predicate="dijo",
            object_text=said,
        )
    if _has_any(folded, _JUDICIAL_MARKERS):
        ruling = _ruling_span(text)
        if ruling and _has_any(normalize_name(ruling), _JUDICIAL_MARKERS):
            _copy(
                canonical=ruling,
                claim_type="hecho",
                subject=raw.subject,
                predicate="resolucion",
                object_text=ruling,
            )
    if _has_any(folded, _EFFECTIVE_MARKERS):
        effective = "La norma entra en vigencia"
        if "mes" in folded:
            effective = "La norma entra en vigencia el mes próximo"
        _copy(
            canonical=effective,
            claim_type="documento",
            subject=raw.subject,
            predicate="vigencia",
            object_text=effective,
        )
    if _has_any(folded, _SCOPE_MARKERS):
        scope = "El régimen se aplica a delitos graves" if "delitos graves" in folded else text
        _copy(
            canonical=scope,
            claim_type="documento",
            subject=raw.subject,
            predicate="alcance",
            object_text=scope,
        )
    if _has_any(folded, _EXISTENCE_MARKERS):
        _copy(
            canonical=text,
            claim_type="hecho",
            subject=raw.subject,
            predicate="denuncia",
            object_text=text,
        )
    return parts or [raw]


def _ages(text: str) -> set[str]:
    return set(_AGE_RE.findall(normalize_name(text)))


def _negated(text: str) -> bool:
    folded = f" {normalize_name(text)} "
    return any(token in folded for token in (" no ", " nunca ", " no fue ", " no es ", " no estan ", " no están "))


def _qualifier_mismatch(left: str, right: str) -> bool:
    a = normalize_name(left)
    b = normalize_name(right)
    ages_a, ages_b = _ages(left), _ages(right)
    if ages_a and ages_b and ages_a != ages_b:
        return True
    if (_MENORES in a) != (_MENORES in b) and (ages_a or ages_b or _MENORES in a or _MENORES in b):
        if (_MENORES in a and _DESDE in b) or (_MENORES in b and _DESDE in a):
            return True
    if _negated(left) != _negated(right):
        return True
    return False


def _act_bucket(text: str) -> str:
    folded = normalize_name(text)
    if _has_any(folded, _EXISTENCE_MARKERS):
        return "existence"
    if _has_any(folded, _EFFECTIVE_MARKERS):
        return "effective_date"
    if _has_any(folded, _SCOPE_MARKERS):
        return "normative_scope"
    if _has_any(folded, _JUDICIAL_MARKERS):
        return "judicial_decision"
    if _has_any(folded, _UTTERANCE_MARKERS) or _QUOTE_RE.search(text or ""):
        return "utterance"
    if _has_any(folded, _ACCUSATION_TRUTH_MARKERS):
        return "accusation_truth"
    return "other"


def _ruling_span(text: str) -> str:
    ruling = _SAID_SPLIT_RE.split(text, maxsplit=1)[0]
    ruling = re.sub(r"(?i)\s+y$", "", ruling).strip(" ,;:")
    return ruling


def _utterance_span(text: str, subject: str | None) -> str:
    quoted = _QUOTE_RE.search(text or "")
    who = (subject or "").strip() or "La jueza"
    if quoted:
        return f"{who} dijo: {quoted.group(0)}"
    parts = _SAID_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        tail = parts[1].strip(" :")
        return f"{who} dijo {tail}".strip()
    return text


def _atomic_propositions(text: str) -> list[str]:
    cleaned = " ".join((text or "").split())
    if len(cleaned) < 12:
        return []
    spans: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
        sentence = sentence.strip()
        if len(sentence) < 12:
            continue
        if is_mixed_proposition(sentence):
            dummy = ExtractedClaim(
                canonical_text=sentence,
                claim_type="hecho",
                importance=ClaimImportance.HIGH,
                evidence=[],
            )
            spans.extend(part.canonical_text for part in split_compound_extracted(dummy) if part.canonical_text)
        else:
            spans.append(sentence)
    return spans


def propositions_equivalent(expected: str, claim_text: str, *, expected_role: PropositionRole | None = None) -> CoverageMatch:
    if _qualifier_mismatch(expected, claim_text):
        return CoverageMatch.PARTIAL
    exp_bucket = _act_bucket(expected)
    got_bucket = _act_bucket(claim_text)
    if expected_role == PropositionRole.EXISTENCE and got_bucket == "accusation_truth":
        return CoverageMatch.NONE
    if exp_bucket != "other" and got_bucket != "other" and exp_bucket != got_bucket:
        return CoverageMatch.NONE
    exp_tokens = token_set(expected)
    got_tokens = token_set(claim_text)
    if not exp_tokens or not got_tokens:
        return CoverageMatch.NONE
    overlap = len(exp_tokens & got_tokens) / max(1, min(len(exp_tokens), len(got_tokens)))
    if exp_bucket == got_bucket and overlap >= 0.35:
        return CoverageMatch.EQUIVALENT
    if overlap >= 0.6 and exp_bucket == "other":
        return CoverageMatch.EQUIVALENT
    if overlap >= 0.25:
        return CoverageMatch.PARTIAL
    return CoverageMatch.NONE


def expected_centrals_from_event(event: Event) -> list[ExpectedCentral]:
    rows: list[ExpectedCentral] = []
    seen: set[str] = set()

    def _add(text: str, signal: CoverageSignal) -> None:
        cleaned = " ".join((text or "").split())
        if len(cleaned) < 12:
            return
        if _is_frame_only(cleaned):
            return
        key = normalize_name(cleaned)
        if key in seen:
            return
        seen.add(key)
        role = proposition_role_for(cleaned)
        if role == PropositionRole.OTHER and _act_bucket(cleaned) == "other":
            return
        rows.append(
            ExpectedCentral(
                proposition=cleaned,
                role=role,
                act=_act_bucket(cleaned),
                signal=signal,
                match=CoverageMatch.NONE,
                gap_reason=GapReason.NOT_EXTRACTED.value,
            )
        )

    for span in _atomic_propositions(event.title_internal or ""):
        _add(span, CoverageSignal.TITLE)
    lead = _lead_text(event)
    if lead and normalize_name(lead) != normalize_name(event.title_internal or ""):
        for span in _atomic_propositions(lead):
            _add(span, CoverageSignal.LEAD)
    return rows


def match_expected_to_claims(
    expected: list[ExpectedCentral],
    claims: list[Claim],
) -> list[ExpectedCentral]:
    updated: list[ExpectedCentral] = []
    for row in expected:
        best: tuple[CoverageMatch, Claim] | None = None
        for claim in claims:
            match = propositions_equivalent(row.proposition, claim.canonical_text, expected_role=row.role)
            if match == CoverageMatch.NONE:
                continue
            if best is None or (match == CoverageMatch.EQUIVALENT and best[0] != CoverageMatch.EQUIVALENT):
                best = (match, claim)
            if match == CoverageMatch.EQUIVALENT:
                break
        if best is None:
            updated.append(row.model_copy(update={"match_claim_id": None, "match": CoverageMatch.NONE}))
            continue
        match, claim = best
        gap = None if match == CoverageMatch.EQUIVALENT else GapReason.QUALIFIER_MISMATCH.value
        updated.append(
            row.model_copy(
                update={
                    "match_claim_id": str(claim.id),
                    "match": match,
                    "gap_reason": gap,
                }
            )
        )
    return updated


def central_claim_ids(coverage: CoverageContract) -> set[UUID]:
    ids: set[UUID] = set()
    for row in coverage.expected_central:
        if row.match == CoverageMatch.EQUIVALENT and row.match_claim_id:
            ids.add(UUID(row.match_claim_id))
    for raw in coverage.spine_claim_ids:
        ids.add(UUID(raw))
    return ids


@dataclass
class MergeOutcome:
    pending: dict
    dropped: list[DroppedExtracted] = field(default_factory=list)
    dropped_raw: list[tuple[ExtractedClaim, str]] = field(default_factory=list)


def record_drop(
    *,
    canonical_text: str,
    reason: str,
    assertion_key: str | None = None,
    merged_into: str | None = None,
) -> DroppedExtracted:
    return DroppedExtracted(
        canonical_text=canonical_text,
        reason=reason,
        assertion_key=assertion_key,
        merged_into=merged_into,
    )


def build_coverage_contract(
    *,
    event: Event,
    claims: list[Claim],
    dropped: list[DroppedExtracted],
) -> CoverageContract:
    expected = match_expected_to_claims(expected_centrals_from_event(event), claims)
    spine = [row.match_claim_id for row in expected if row.match == CoverageMatch.EQUIVALENT and row.match_claim_id]
    roles = {str(claim.id): proposition_role_for(claim).value for claim in claims}
    gap = any(row.match != CoverageMatch.EQUIVALENT for row in expected) if expected else False
    dropped_reasons = {item.reason for item in dropped}
    for row in expected:
        if row.match == CoverageMatch.EQUIVALENT:
            continue
        if row.match == CoverageMatch.PARTIAL and row.gap_reason:
            continue
        if "invalid_excerpt" in dropped_reasons:
            row.gap_reason = GapReason.DROPPED_INVALID_EXCERPT.value
        elif "merged_into" in dropped_reasons:
            row.gap_reason = GapReason.MERGED_AWAY.value
        elif row.gap_reason is None:
            row.gap_reason = GapReason.NOT_EXTRACTED.value
    return CoverageContract(
        contract_version=CONTRACT_VERSION,
        expected_central=expected,
        spine_claim_ids=spine,
        persisted_assertion_keys=[_assertion_key(claim) for claim in claims],
        dropped=dropped,
        proposition_role=roles,
        source_quality=source_quality_rows(event),
        coverage_gap=gap,
    )


def recover_expected_from_dropped(
    expected: list[ExpectedCentral],
    dropped: list[tuple[ExtractedClaim, str]],
    sources: list[SourceItem],
    *,
    excerpt_ok,
) -> list[ExtractedClaim]:
    recovered: list[ExtractedClaim] = []
    for row in expected:
        if row.match == CoverageMatch.EQUIVALENT:
            continue
        for raw, reason in dropped:
            if reason not in {"invalid_excerpt", "empty_key"}:
                continue
            match = propositions_equivalent(row.proposition, raw.canonical_text, expected_role=row.role)
            if match != CoverageMatch.EQUIVALENT:
                continue
            if excerpt_ok(raw.evidence, sources):
                recovered.append(raw)
                break
    return recovered


def recover_from_source_body(
    expected: list[ExpectedCentral],
    sources: list[SourceItem],
) -> list[ExtractedClaim]:
    recovered: list[ExtractedClaim] = []
    for row in expected:
        if row.match == CoverageMatch.EQUIVALENT:
            continue
        needles = [token for token in (row.act, "denuncia", "vigencia", "afirmó", "dijo") if token]
        for item in sources:
            body = item.clean_text or ""
            if not body:
                continue
            sentence = _sentence_with_markers(body, row.proposition)
            if not sentence:
                continue
            if row.role not in {
                PropositionRole.EXISTENCE,
                PropositionRole.UTTERANCE,
                PropositionRole.EFFECTIVE_DATE,
                PropositionRole.NORMATIVE_SCOPE,
            } and row.act != "judicial_decision":
                continue
            match = propositions_equivalent(row.proposition, sentence, expected_role=row.role)
            if match == CoverageMatch.NONE:
                if row.role == PropositionRole.EXISTENCE and "denuncia" in normalize_name(sentence):
                    pass
                else:
                    continue
            idx = sources.index(item) + 1
            recovered.append(
                ExtractedClaim(
                    canonical_text=row.proposition,
                    claim_type="hecho"
                    if row.role == PropositionRole.EXISTENCE or row.act == "judicial_decision"
                    else "declaracion",
                    importance=ClaimImportance.HIGH,
                    subject=None,
                    predicate=row.act,
                    object_text=row.proposition,
                    evidence=[
                        ExtractedEvidence(
                            source_ref=idx,
                            evidence_type=EvidenceType.SUPPORTS,
                            excerpt=sentence[:240],
                        )
                    ],
                )
            )
            break
        _ = needles
    return recovered


def _sentence_with_markers(body: str, proposition: str) -> str | None:
    folded_needles = [token for token in token_set(proposition) if len(token) >= 5]
    act = _act_bucket(proposition)
    sentences = re.split(r"(?<=[.!?])\s+", body)
    for sentence in sentences:
        folded = normalize_name(sentence)
        sent_act = _act_bucket(sentence)
        if act != "other" and sent_act != "other" and act != sent_act:
            if not (act == "existence" and "denuncia" in folded):
                continue
        hits = sum(1 for token in folded_needles if token in folded)
        if hits >= min(3, max(1, len(folded_needles) // 4)) and len(sentence.strip()) >= 20:
            return sentence.strip()
    return None


def salvage_excerpt(canonical: str, *blobs: str | None) -> str | None:
    parts = tuple(part for part in blobs if part)
    if not canonical.strip() or not parts:
        return None
    body = "\n".join(parts)
    want = _act_bucket(canonical)
    role = proposition_role_for(canonical)
    candidates: list[str] = []
    sentence = _sentence_with_markers(body, canonical)
    if sentence:
        candidates.append(sentence)
    for match in _QUOTE_RE.finditer(body):
        quoted = match.group(0)
        if len(quoted) >= 12:
            candidates.append(quoted)
    ranked: list[tuple[int, int, str]] = []
    for raw in candidates:
        fragment = " ".join(raw.split())
        if len(fragment) < 12:
            continue
        if len(fragment) > 240:
            fragment = fragment[:240].rstrip()
        if not excerpt_in_source(fragment, *parts):
            continue
        got = _act_bucket(fragment)
        if want != "other" and got != "other" and want != got:
            continue
        match = propositions_equivalent(canonical, fragment, expected_role=role)
        if match == CoverageMatch.NONE:
            continue
        ranked.append((0 if match == CoverageMatch.EQUIVALENT else 1, len(fragment), fragment))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def cited_primary_urls(*blobs: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for blob in blobs:
        if not blob:
            continue
        for raw in _URL_RE.findall(blob):
            token = raw.rstrip(").,;\"'")
            try:
                canonical = canonicalize_url(token)
            except Exception:
                canonical = token
            if canonical in seen:
                continue
            seen.add(canonical)
            found.append(canonical)
    return found
