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
from app.core.text import normalize_name, token_set, content_fingerprint
from app.core.urls import canonicalize_url, url_domain
from app.domain.enums import EvidenceType
from app.models import Claim
from app.schemas.editorial_evidence import (
    Demotion,
    DocumentClass,
    PropositionRole,
    StatementEvidenceClass,
    SupportBasis,
    SupportKind,
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
_AUTHORITATIVE_PREFIXES = ("constitutive:", "youtube:", "vimeo:")
_NON_DOCUMENTARY_CITE_HOSTS = (
    "t.co",
    "bit.ly",
    "tinyurl.com",
    "ow.ly",
    "goo.gl",
    "rb.gy",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
)
_REPUBLICATION_HOST_RE = re.compile(
    r"(?:leer(?: la)? nota en|nota original en|fuente original(?: en)?|"
    r"visita(?:r)?(?: la)?(?: nota| fuente)? en)\s+"
    r"(?:https?://(?:www\.)?)?([a-z0-9.-]+\.[a-z]{2,})",
    re.I,
)
_REPUBLICATION_SUMMARY_RE = re.compile(
    r"este es un resumen(?: de la nota(?: original)?)?",
    re.I,
)
_WIRE_AGENCIES = (
    ("telam", "telam"),
    ("reuters", "reuters"),
    ("associated press", "ap"),
    ("agence france-presse", "afp"),
    (" agence france presse", "afp"),
    ("noticias argentinas", "na"),
    ("diarios y noticias", "dyn"),
)
_WIRE_SHORT = (
    (re.compile(r"\bafp\b", re.I), "afp"),
    (re.compile(r"\befe\b", re.I), "efe"),
    (re.compile(r"\bdyn\b", re.I), "dyn"),
)
_WIRE_FRAME = (
    "segun ",
    "según ",
    "informo ",
    "informó ",
    "reporto ",
    "reportó ",
    "reprodujo ",
    "agencia ",
    "de la agencia ",
)
_COMUNICADO_RE = re.compile(
    r"(?:seg[uú]n|reprodu(?:jo|cen)|difundi[oó]|inform[oó])\s+"
    r"(?:un |el |la )?(comunicado|parte oficial|gacetilla)"
    r"(?:\s+(?:de|del|de la)\s+([^.,;:]{3,50}))?",
    re.I,
)
_NAMED_SOURCE_RE = re.compile(
    r"\bseg[uú]n\s+(?:la |el |las |los )?"
    r"((?:ministerio|secretar[ií]a|indec|polic[ií]a federal|gendarmer[ií]a|"
    r"prefectura|casa rosada|jefatura de gabinete|ente regulador|enre|enargas|"
    r"bolet[ií]n oficial)[^.,;:]{0,40})",
    re.I,
)
_BODY_REPRINT_MIN_TOKENS = 40


def _canonicalize_claim_type(raw: str | None) -> str:
    from app.services.verification_policy import canonicalize_claim_type

    return canonicalize_claim_type(raw)


def _is_weak_independent_host(domain: str) -> bool:
    from app.services.verification_policy import _is_weak_independent_host as _weak

    return _weak(domain)


def _is_non_documentary_cite_host(domain: str) -> bool:
    token = (domain or "").strip().lower()
    if token.startswith("www."):
        token = token[4:]
    return any(token == host or token.endswith("." + host) for host in _NON_DOCUMENTARY_CITE_HOSTS)


def _republication_host(blobs: tuple[str | None, ...]) -> str | None:
    blob = " ".join(part for part in blobs if part)
    if not blob.strip():
        return None
    match = _REPUBLICATION_HOST_RE.search(blob)
    if match:
        host = (match.group(1) or "").strip().lower().rstrip("/")
        if host.startswith("www."):
            host = host[4:]
        return host or None
    if _REPUBLICATION_SUMMARY_RE.search(blob):
        folded = normalize_name(blob)
        for marker, host in (("infobae", "infobae.com"), ("clarin", "clarin.com"), ("lanacion", "lanacion.com.ar")):
            if marker in folded:
                return host
    return None


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
    from app.services.claim_meaning import attributed_statement
    # A publication repeating a statement does not independently observe its
    # underlying fact, even when it links to the interview or a press release.
    role = proposition_role_for(claim)
    excerpt = getattr(row, "excerpt", None) or ""
    if role != PropositionRole.UTTERANCE and attributed_statement(excerpt):
        return None
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
        if not host or _is_weak_independent_host(host) or _is_non_documentary_cite_host(host):
            continue
        return f"cited:{canonicalize_url(url)}"
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
        and not _has_attribution(getattr(row, "excerpt", None) or "")
    ):
        return f"constitutive:{key}"
    shared = _explicit_shared_origin(role, blobs)
    if shared:
        return shared
    return _reporting_origin(row)


def _explicit_shared_origin(role: PropositionRole, blobs: tuple[str | None, ...]) -> str | None:
    """Named wire, comunicado or attributed record. Distinct domains do not override this."""
    blob = " ".join(part for part in blobs if part)
    if not blob.strip():
        return None
    folded = normalize_name(blob)
    lowered = blob.casefold()
    for name, key in _WIRE_AGENCIES:
        if name in folded and _framed_as_source(folded, name):
            return f"wire:{key}"
    for pattern, key in _WIRE_SHORT:
        if pattern.search(blob) and any(frame.strip() in lowered for frame in _WIRE_FRAME):
            return f"wire:{key}"
    comunicado = _COMUNICADO_RE.search(blob)
    if comunicado:
        org = (comunicado.group(2) or "").strip()
        if org:
            return f"comunicado:{normalize_name(org)[:48]}"
    if role != PropositionRole.UTTERANCE:
        named = _NAMED_SOURCE_RE.search(blob)
        if named:
            token = normalize_name(named.group(1) or "")[:48]
            if token:
                return f"attributed:{token}"
    return None


def _framed_as_source(folded: str, name: str) -> bool:
    if f"segun {name}" in folded or f"agencia {name}" in folded:
        return True
    if f"informo {name}" in folded or f"{name} informo" in folded:
        return True
    if f"reporto {name}" in folded or f"reprodujo {name}" in folded:
        return True
    if f"de {name}" in folded and any(token in folded for token in ("segun", "informo", "agencia", "cable")):
        return True
    return False


def _reporting_origin(row) -> str | None:
    item = getattr(row, "source_item", None)
    if usable_body_source(item) != BODY_SOURCE_EXTRACTED_HTML:
        return None
    if fetch_ok_from_item(item) is False:
        return None
    host = _host(document_key(row) or "")
    src = getattr(item, "source", None) if item is not None else None
    source_domain = getattr(src, "domain", None) if src is not None else None
    if source_domain:
        host = host or _host(f"https://{source_domain}")
    if not host and src is not None:
        host = _host(getattr(src, "feed_url", None) or "") or _host(getattr(src, "homepage_url", None) or "")
    if host and _is_weak_independent_host(host):
        return None
    reprint_host = _republication_host(_blobs(row))
    if reprint_host:
        return f"reporting:{reprint_host}"
    if host:
        return f"reporting:{host}"
    source_id = getattr(src, "id", None) if src is not None else None
    if source_id:
        return f"reporting:{source_id}"
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


def _row_body_fingerprint(row) -> str | None:
    item = getattr(row, "source_item", None)
    body = (getattr(item, "clean_text", None) if item is not None else None) or ""
    if not body.strip():
        return None
    return content_fingerprint(title="", body=body)


def _body_tokens(row) -> set[str]:
    item = getattr(row, "source_item", None)
    body = (getattr(item, "clean_text", None) if item is not None else None) or ""
    return token_set(body)


def _same_material_copy(row, group: dict) -> bool:
    fp = _row_body_fingerprint(row)
    if fp and group.get("fingerprint") and fp == group["fingerprint"]:
        return True
    body_tokens = _body_tokens(row)
    other = group.get("body_tokens") or set()
    if len(body_tokens) >= _BODY_REPRINT_MIN_TOKENS and len(other) >= _BODY_REPRINT_MIN_TOKENS:
        overlap = len(body_tokens & other)
        return overlap / min(len(body_tokens), len(other)) >= _REPRINT_CONTAINMENT
    return False


@dataclass
class OriginAssessment:
    known_independent: int = 0
    unknown_groups: int = 0
    reprint_collapsed: int = 0
    documents_consulted: int = 0
    documents_supporting: int = 0
    documents_qualifying: int = 0
    documents_contradicting: int = 0
    authoritative_independent: int = 0
    reporting_independent: int = 0
    document_keys: list[str] = field(default_factory=list)
    information_origins: list[str] = field(default_factory=list)
    statement_evidence_class: StatementEvidenceClass | None = None


def assess_origins(claim: Claim, *, packet_size: int | None = None) -> OriginAssessment:
    supports = _support_rows(claim)
    result = OriginAssessment(
        documents_consulted=packet_size if packet_size is not None else len(getattr(claim, "evidence", None) or []),
        documents_supporting=len(supports),
        documents_qualifying=sum(row.evidence_type == EvidenceType.QUALIFIES for row in (claim.evidence or [])),
        documents_contradicting=sum(row.evidence_type == EvidenceType.CONTRADICTS for row in (claim.evidence or [])),
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
            reprint = _reprint_of(tokens, group["tokens"], excerpt, group["excerpt"]) or _same_material_copy(
                row, group
            )
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
                "fingerprint": _row_body_fingerprint(row),
                "body_tokens": _body_tokens(row),
            }
        )
    known_ids: set[str] = set()
    unknown = 0
    for group in groups:
        if group["origin"]:
            known_ids.add(group["origin"])
        else:
            # Recognizing a reproduction does not establish its original source.
            unknown += 1
    result.known_independent = len(known_ids)
    result.unknown_groups = unknown
    result.authoritative_independent = len(
        {item for item in known_ids if item.startswith(_AUTHORITATIVE_PREFIXES)}
    )
    result.reporting_independent = len({item for item in known_ids if item.startswith("reporting:")})
    result.information_origins = sorted(item for item in known_ids if not item.startswith("reprint:"))
    role = proposition_role_for(claim)
    mixed = is_mixed_proposition(claim.canonical_text or "", getattr(claim, "claim_type", None))
    if _canonicalize_claim_type(getattr(claim, "claim_type", None)) == "declaracion" or role == PropositionRole.UTTERANCE:
        rows = supports or list(getattr(claim, "evidence", None) or [])
        classes = [classify_statement_row(claim, row) for row in rows]
        if mixed:
            classes = [item for item in classes if item != StatementEvidenceClass.AUTHENTIC_PRIMARY]
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
    if is_mixed_proposition(getattr(claim, "canonical_text", None) or "", getattr(claim, "claim_type", None)):
        return StatementEvidenceClass.NOT_RELEVANT
    return StatementEvidenceClass.AUTHENTIC_PRIMARY


def _has_attribution(text: str) -> bool:
    folded = normalize_name(text)
    lowered = text.lower()
    return any(marker in folded or marker in lowered for marker in _ATTRIBUTION_MARKERS)


def support_kind_for(
    *,
    status: str,
    assessment: OriginAssessment,
    primary_access: str | None,
    role: PropositionRole | None = None,
) -> SupportKind:
    if status == "CONFLICTING":
        return SupportKind.CONFLICTING_EVIDENCE
    if status == "UNCERTAIN":
        return SupportKind.INSUFFICIENT
    if status == "SUPPORTED":
        if (
            assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY
            or primary_access == "found_relevant"
            or assessment.authoritative_independent >= 1
        ):
            return SupportKind.PRIMARY_SOURCE
        return SupportKind.INDEPENDENT_REPORTING
    if (
        role == PropositionRole.UTTERANCE
        and assessment.statement_evidence_class == StatementEvidenceClass.ATTRIBUTED_REPORT
    ):
        return SupportKind.ATTRIBUTED_STATEMENT
    if status == "SINGLE_SOURCE":
        return SupportKind.SINGLE_REPORT
    return SupportKind.INSUFFICIENT


def support_basis_from_assessment(
    claim: Claim,
    assessment: OriginAssessment,
    *,
    demotion: Demotion = Demotion.NONE,
    evaluated_text: str | None = None,
    primary_access: str | None = None,
    status: str | None = None,
    role: PropositionRole | None = None,
) -> SupportBasis:
    final_status = status or getattr(getattr(claim, "status", None), "value", None) or str(
        getattr(claim, "status", "") or ""
    )
    kind = support_kind_for(
        status=final_status,
        assessment=assessment,
        primary_access=primary_access,
        role=role,
    )
    return SupportBasis(
        known_independent_count=assessment.known_independent,
        unknown_group_count=assessment.unknown_groups,
        reprint_collapsed_count=assessment.reprint_collapsed,
        documents_consulted=assessment.documents_consulted,
        documents_supporting=assessment.documents_supporting,
        documents_qualifying=assessment.documents_qualifying,
        documents_contradicting=assessment.documents_contradicting,
        origin_groups_known=assessment.known_independent,
        origin_groups_unknown=assessment.unknown_groups,
        statement_evidence_class=(
            assessment.statement_evidence_class.value if assessment.statement_evidence_class else None
        ),
        primary_access=primary_access,
        kind=kind.value,
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


def final_reason_for(
    demotion: Demotion,
    assessment: OriginAssessment,
    status: str,
    *,
    role: PropositionRole | None = None,
    primary_access: str | None = None,
    support_kind: SupportKind | None = None,
    rejected_disproof: bool = False,
) -> str:
    from app.services.editorial_reason import ReasonContext, reason_code_for, render_reason

    kind = support_kind or support_kind_for(
        status=status,
        assessment=assessment,
        primary_access=primary_access,
        role=role,
    )
    code = reason_code_for(
        status=status,
        demotion=demotion,
        known_independent=assessment.known_independent,
        unknown_groups=assessment.unknown_groups,
        authoritative_independent=assessment.authoritative_independent,
        documents_supporting=assessment.documents_supporting,
        documents_qualifying=assessment.documents_qualifying,
        statement_evidence_class=assessment.statement_evidence_class,
        support_kind=kind,
        role=role,
        primary_access=primary_access,
        rejected_disproof=rejected_disproof,
    )
    return render_reason(
        code,
        ReasonContext(
            status=status,
            demotion=demotion,
            known_independent=assessment.known_independent,
            unknown_groups=assessment.unknown_groups,
            authoritative_independent=assessment.authoritative_independent,
            statement_evidence_class=assessment.statement_evidence_class,
            support_kind=kind,
            role=role,
            primary_access=primary_access,
            rejected_disproof=rejected_disproof,
        ),
    ) or "Evidencia insuficiente para corroborar de forma independiente."


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
