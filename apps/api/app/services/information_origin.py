from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from app.core.source_content import (
    BODY_SOURCE_EXTRACTED_HTML,
    BODY_SOURCE_SEARCH_SNIPPET,
    BODY_SOURCE_TITLE_ONLY,
    BODY_SOURCE_UNKNOWN,
    body_source_from_item,
    has_extracted_body,
)
from app.core.text import normalize_name, token_set
from app.core.urls import canonicalize_url, url_domain
from app.domain.enums import EvidenceType
from app.models import Claim
from app.schemas.editorial_evidence import (
    Demotion,
    DocumentClass,
    PropositionRole,
    StatementEvidenceClass,
    SupportBasis,
)
from app.services.claim_coverage import cited_primary_urls, is_mixed_proposition, proposition_role_for

_REPRINT_CONTAINMENT = 0.85
_REPRINT_MIN_TOKENS = 12
_GENERIC_EXCERPT = {
    "segun pudo saber",
    "según pudo saber",
    "fuentes consultadas",
    "en las ultimas horas",
    "en las últimas horas",
}
_ATTRIBUTION_MARKERS = (
    "afirmó",
    "afirmo",
    "dijo que",
    "según ",
    "segun ",
    "sostuvo que",
    "aseguró que",
    "aseguro que",
)
_PLATFORM_HOSTS = (
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "vimeo.com",
)
_CONSTITUTIVE_HOSTS = (
    "boletinoficial.gob.ar",
    "indec.gob.ar",
    "enre.gob.ar",
    "enargas.gob.ar",
    "pjn.gov.ar",
    "csjn.gov.ar",
    "cij.gov.ar",
)
_VIDEO_ID_RE = re.compile(r"(?:v=|/embed/|/shorts/|/watch/)?([A-Za-z0-9_-]{11})")
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def _canonicalize_claim_type(raw: str | None) -> str:
    from app.services.verification_policy import canonicalize_claim_type

    return canonicalize_claim_type(raw)


def _is_weak_independent_host(domain: str) -> bool:
    from app.services.verification_policy import _is_weak_independent_host as _weak

    return _weak(domain)


def document_key(row) -> str | None:
    item = getattr(row, "source_item", None)
    url = ""
    if item is not None:
        url = getattr(item, "canonical_url", None) or getattr(item, "url", "") or ""
    if not url:
        url = getattr(row, "source_url", None) or getattr(row, "url", "") or ""
    if not url:
        item_id = getattr(row, "source_item_id", None)
        return str(item_id) if item_id else None
    try:
        return canonicalize_url(url)
    except Exception:
        return url


def _host(url: str | None) -> str:
    if not url:
        return ""
    return url_domain(url)


def _support_rows(claim: Claim) -> list:
    return [
        row
        for row in (getattr(claim, "evidence", None) or [])
        if getattr(row, "evidence_type", None) == EvidenceType.SUPPORTS
    ]


def has_support_evidence(claim: Claim) -> bool:
    return bool(_support_rows(claim))


def _blobs(row) -> tuple[str | None, ...]:
    item = getattr(row, "source_item", None)
    return (
        getattr(row, "excerpt", None),
        getattr(item, "clean_text", None) if item is not None else None,
        getattr(item, "excerpt", None) if item is not None else None,
        getattr(item, "title", None) if item is not None else None,
        getattr(row, "source_url", None),
    )


def usable_body_source(item) -> str:
    source = body_source_from_item(item) if item is not None else BODY_SOURCE_UNKNOWN
    if source in {BODY_SOURCE_UNKNOWN, ""} and item is not None and has_extracted_body(item):
        return BODY_SOURCE_EXTRACTED_HTML
    return source or BODY_SOURCE_UNKNOWN


def fetch_ok_from_item(item) -> bool | None:
    if item is None:
        return None
    meta = getattr(item, "metadata_json", None) or {}
    if isinstance(meta, dict) and "fetch_ok" in meta:
        return bool(meta.get("fetch_ok"))
    if has_extracted_body(item):
        return True
    source = body_source_from_item(item)
    if source in {BODY_SOURCE_SEARCH_SNIPPET, BODY_SOURCE_TITLE_ONLY}:
        return False
    return None


def _video_origin(url: str) -> str | None:
    host = _host(url)
    if any(host == item or host.endswith("." + item) for item in _YOUTUBE_HOSTS):
        parsed = urlparse(url)
        if parsed.netloc.endswith("youtu.be"):
            vid = parsed.path.strip("/")
            return f"youtube:{vid}" if vid else None
        query = parse_qs(parsed.query)
        if query.get("v"):
            return f"youtube:{query['v'][0]}"
        match = _VIDEO_ID_RE.search(parsed.path)
        return f"youtube:{match.group(1)}" if match else None
    if "vimeo.com" in host:
        path = urlparse(url).path.strip("/")
        return f"vimeo:{path}" if path else None
    return None


def _host_matches(host: str, candidates: tuple[str, ...]) -> bool:
    return any(host == item or host.endswith("." + item) for item in candidates)


def information_origin_for_row(claim: Claim, row) -> str | None:
    key = document_key(row)
    blobs = _blobs(row)
    cited = cited_primary_urls(*blobs)
    for url in cited:
        video = _video_origin(url)
        if video:
            return video
    for url in cited:
        if key and canonicalize_url(url) == key:
            continue
        host = _host(url)
        if host and not _is_weak_independent_host(host):
            return f"cited:{canonicalize_url(url)}"
    role = proposition_role_for(claim)
    host = _host(key or "")
    item = getattr(row, "source_item", None)
    body_source = usable_body_source(item)
    if (
        role == PropositionRole.UTTERANCE
        and classify_statement_row(claim, row) == StatementEvidenceClass.AUTHENTIC_PRIMARY
        and key
    ):
        return f"constitutive:{key}"
    kind = _canonicalize_claim_type(getattr(claim, "claim_type", None))
    if (
        key
        and host
        and _host_matches(host, _CONSTITUTIVE_HOSTS)
        and kind in {"documento", "cifra"}
        and body_source == BODY_SOURCE_EXTRACTED_HTML
    ):
        return f"constitutive:{key}"
    return None


def _reprint_of(tokens_a: set[str], tokens_b: set[str], excerpt_a: str, excerpt_b: str) -> bool:
    if len(tokens_a) < _REPRINT_MIN_TOKENS or len(tokens_b) < _REPRINT_MIN_TOKENS:
        return False
    folded_a = normalize_name(excerpt_a)
    folded_b = normalize_name(excerpt_b)
    if folded_a in _GENERIC_EXCERPT or folded_b in _GENERIC_EXCERPT:
        return False
    overlap = len(tokens_a & tokens_b)
    return overlap / min(len(tokens_a), len(tokens_b)) >= _REPRINT_CONTAINMENT


@dataclass
class OriginAssessment:
    known_independent: int = 0
    unknown_groups: int = 0
    reprint_collapsed: int = 0
    documents_consulted: int = 0
    documents_supporting: int = 0
    document_keys: list[str] = field(default_factory=list)
    information_origins: list[str] = field(default_factory=list)
    statement_evidence_class: StatementEvidenceClass | None = None


def assess_origins(claim: Claim, *, packet_size: int | None = None) -> OriginAssessment:
    supports = _support_rows(claim)
    result = OriginAssessment(
        documents_consulted=packet_size if packet_size is not None else len(getattr(claim, "evidence", None) or []),
        documents_supporting=len(supports),
    )
    groups: list[dict] = []
    for row in supports:
        doc = document_key(row)
        if doc:
            result.document_keys.append(doc)
        origin = information_origin_for_row(claim, row)
        excerpt = getattr(row, "excerpt", None) or ""
        tokens = token_set(excerpt)
        host = _host(doc or "")
        if host and _is_weak_independent_host(host):
            continue
        placed = False
        for group in groups:
            same_origin = bool(origin and group["origin"] and origin == group["origin"])
            reprint = _reprint_of(tokens, group["tokens"], excerpt, group["excerpt"])
            if same_origin or reprint:
                group["members"] += 1
                if reprint and not same_origin:
                    group["reprint"] = True
                    result.reprint_collapsed += 1
                if origin and not group["origin"]:
                    group["origin"] = origin
                placed = True
                break
        if placed:
            continue
        groups.append(
            {
                "origin": origin,
                "tokens": tokens,
                "excerpt": excerpt,
                "members": 1,
                "reprint": False,
                "doc": doc,
            }
        )
    known_ids: set[str] = set()
    unknown = 0
    for index, group in enumerate(groups):
        if group["origin"]:
            known_ids.add(group["origin"])
        elif group["reprint"] or group["members"] > 1:
            known_ids.add(f"reprint:{group['doc'] or index}")
        else:
            unknown += 1
    result.known_independent = len(known_ids)
    result.unknown_groups = unknown
    result.information_origins = sorted(item for item in known_ids if not item.startswith("reprint:"))
    role = proposition_role_for(claim)
    if _canonicalize_claim_type(getattr(claim, "claim_type", None)) == "declaracion" or role == PropositionRole.UTTERANCE:
        rows = supports or list(getattr(claim, "evidence", None) or [])
        classes = [classify_statement_row(claim, row) for row in rows]
        if StatementEvidenceClass.AUTHENTIC_PRIMARY in classes:
            result.statement_evidence_class = StatementEvidenceClass.AUTHENTIC_PRIMARY
        elif StatementEvidenceClass.ATTRIBUTED_REPORT in classes:
            result.statement_evidence_class = StatementEvidenceClass.ATTRIBUTED_REPORT
        elif StatementEvidenceClass.SEARCH_HIT_ONLY in classes:
            result.statement_evidence_class = StatementEvidenceClass.SEARCH_HIT_ONLY
        elif StatementEvidenceClass.ACCESS_LIMITED in classes:
            result.statement_evidence_class = StatementEvidenceClass.ACCESS_LIMITED
        elif classes:
            result.statement_evidence_class = classes[0]
    return result


def independent_support_count(claim: Claim) -> int:
    return assess_origins(claim).known_independent


def classify_statement_row(
    claim: Claim,
    row,
    *,
    body_source: str | None = None,
    fetch_ok: bool | None = None,
) -> StatementEvidenceClass:
    item = getattr(row, "source_item", None)
    source = body_source if body_source is not None else usable_body_source(item)
    ok = fetch_ok if fetch_ok is not None else fetch_ok_from_item(item)
    if ok is False or source in {BODY_SOURCE_TITLE_ONLY, BODY_SOURCE_SEARCH_SNIPPET}:
        if source == BODY_SOURCE_SEARCH_SNIPPET:
            return StatementEvidenceClass.SEARCH_HIT_ONLY
        return StatementEvidenceClass.ACCESS_LIMITED
    evidence_type = getattr(row, "evidence_type", None)
    if evidence_type not in {EvidenceType.SUPPORTS, None} and evidence_type != EvidenceType.SUPPORTS:
        return StatementEvidenceClass.NOT_RELEVANT
    excerpt = (getattr(row, "excerpt", None) or "").strip()
    body = (getattr(item, "clean_text", None) if item is not None else "") or ""
    title = (getattr(item, "title", None) if item is not None else "") or ""
    haystack = body or excerpt
    if excerpt and normalize_name(excerpt) not in normalize_name(haystack):
        return StatementEvidenceClass.NOT_RELEVANT
    folded_body = normalize_name(body or excerpt)
    folded_title = normalize_name(title)
    subject = normalize_name(getattr(claim, "subject", None) or "")
    speaker_ok = True
    if subject:
        tokens = [token for token in subject.split() if len(token) > 3]
        speaker_ok = subject in folded_body or subject in folded_title or any(token in folded_body for token in tokens)
    if not speaker_ok:
        return StatementEvidenceClass.NOT_RELEVANT
    if source != BODY_SOURCE_EXTRACTED_HTML:
        return StatementEvidenceClass.ACCESS_LIMITED
    host = _host(document_key(row) or "")
    attributed = _has_attribution(body or excerpt)
    platform = _host_matches(host, _PLATFORM_HOSTS)
    constitutive_host = _host_matches(host, _CONSTITUTIVE_HOSTS)
    monitored = False
    if item is not None:
        src = getattr(item, "source", None)
        monitored = bool(getattr(src, "is_monitored", False)) if src is not None else False
    if platform and len((body or "").strip()) < 80:
        return StatementEvidenceClass.SEARCH_HIT_ONLY
    if monitored and attributed and not constitutive_host:
        return StatementEvidenceClass.ATTRIBUTED_REPORT
    if attributed and not constitutive_host:
        return StatementEvidenceClass.ATTRIBUTED_REPORT
    return StatementEvidenceClass.AUTHENTIC_PRIMARY


def _has_attribution(text: str) -> bool:
    folded = normalize_name(text)
    lowered = text.lower()
    return any(marker in folded or marker in lowered for marker in _ATTRIBUTION_MARKERS)


def support_basis_from_assessment(
    claim: Claim,
    assessment: OriginAssessment,
    *,
    demotion: Demotion = Demotion.NONE,
    evaluated_text: str | None = None,
    primary_access: str | None = None,
) -> SupportBasis:
    return SupportBasis(
        known_independent_count=assessment.known_independent,
        unknown_group_count=assessment.unknown_groups,
        reprint_collapsed_count=assessment.reprint_collapsed,
        documents_consulted=assessment.documents_consulted,
        documents_supporting=assessment.documents_supporting,
        origin_groups_known=assessment.known_independent,
        origin_groups_unknown=assessment.unknown_groups,
        statement_evidence_class=(
            assessment.statement_evidence_class.value if assessment.statement_evidence_class else None
        ),
        primary_access=primary_access,
        demotion=demotion.value,
        evaluated_canonical_text=evaluated_text or claim.canonical_text,
        document_keys=assessment.document_keys,
        information_origins=assessment.information_origins,
    )


def demotion_for(
    *,
    desired_status: str,
    final_status: str,
    assessment: OriginAssessment,
    primary_required: bool,
    primary_supports: bool,
    mixed: bool,
    role: PropositionRole,
) -> Demotion:
    if desired_status != "SUPPORTED" or final_status == "SUPPORTED":
        return Demotion.NONE
    if mixed:
        return Demotion.MIXED_CLAIM_NO_EXCEPTION
    if primary_required and not primary_supports:
        if role == PropositionRole.UTTERANCE:
            return Demotion.MISSING_AUTHENTIC_PRIMARY
        return Demotion.MISSING_DOCUMENTARY_PRIMARY
    if assessment.unknown_groups and assessment.known_independent < 2:
        return Demotion.UNPROVEN_INDEPENDENCE
    if assessment.known_independent < 2:
        return Demotion.INSUFFICIENT_INDEPENDENCE
    return Demotion.PARTIAL_SUPPORT


def final_reason_for(demotion: Demotion, assessment: OriginAssessment, status: str) -> str:
    if demotion == Demotion.MISSING_DOCUMENTARY_PRIMARY:
        return (
            "No hay fuente primaria documental que sostenga la proposición; "
            "el estado refleja un techo de certeza, no varias corroboraciones."
        )
    if demotion == Demotion.MISSING_AUTHENTIC_PRIMARY:
        return "No hay publicación original auténtica del dicho; un medio que atribuye no alcanza para promoverla."
    if demotion == Demotion.UNPROVEN_INDEPENDENCE:
        return (
            f"Independencia no demostrada ({assessment.unknown_groups} grupo(s) desconocido(s), "
            f"{assessment.known_independent} origen(es) conocido(s))."
        )
    if demotion == Demotion.INSUFFICIENT_INDEPENDENCE:
        return f"Un origen informativo conocido no alcanza para corroboración independiente ({status})."
    if demotion == Demotion.PARTIAL_SUPPORT:
        return "La evidencia solo sostiene parte de la proposición."
    if demotion == Demotion.MIXED_CLAIM_NO_EXCEPTION:
        return "La proposición sigue mixta; no se aplicó la excepción de declaración."
    if assessment.known_independent >= 2:
        return f"{assessment.known_independent} orígenes informativos distintos sostienen la proposición."
    if assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY:
        return "Una fuente primaria auténtica documenta el dicho, no el contenido de lo afirmado."
    if assessment.known_independent == 1:
        return "Un origen informativo conocido sostiene la proposición."
    if assessment.unknown_groups:
        return "Hay respaldo, pero la procedencia informativa no está demostrada."
    return "Evidencia insuficiente para corroborar de forma independiente."


def document_class_for(*, body_source: str, fetch_ok: bool, constitutive: bool, attributed: bool) -> DocumentClass:
    if not fetch_ok or body_source in {BODY_SOURCE_TITLE_ONLY, ""}:
        return DocumentClass.ACCESS_FAILED
    if body_source == BODY_SOURCE_SEARCH_SNIPPET:
        return DocumentClass.SEARCH_HIT_ONLY
    if constitutive:
        return DocumentClass.CONSTITUTIVE
    if attributed:
        return DocumentClass.ATTRIBUTED_REPORT
    return DocumentClass.OWN_PUBLICATION
