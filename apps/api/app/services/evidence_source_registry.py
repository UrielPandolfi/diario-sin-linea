"""Preferred official domains for directed verification. The LLM must not invent these."""

from __future__ import annotations

from app.core.text import normalize_name
from app.core.urls import url_domain

AR_PROVINCIAL_JUSTICE: dict[str, tuple[str, ...]] = {
    "mendoza": ("jus.mendoza.gov.ar", "justiciamendoza.gob.ar"),
    "santa fe": ("justiciasantafe.gov.ar",),
    "cordoba": ("justiciacordoba.gob.ar",),
    "buenos aires": ("scba.gov.ar",),
    "caba": ("jusbaires.gob.ar",),
    "ciudad autonoma de buenos aires": ("jusbaires.gob.ar",),
    "ciudad de buenos aires": ("jusbaires.gob.ar",),
    "san luis": ("justicia.sanluis.gov.ar",),
}

_FEDERAL_JUDICIAL_MARKERS = (
    "juzgado federal",
    "camara federal",
    "cámara federal",
    "justicia federal",
    "fuero federal",
    "corte suprema de justicia de la nacion",
    "corte suprema de justicia de la nación",
    "poder judicial de la nacion",
    "poder judicial de la nación",
)
_PROVINCIAL_COURT_MARKERS = (
    "suprema corte",
    "superior tribunal",
    "tribunal superior",
    "corte de justicia",
    "justicia provincial",
    "corte provincial",
    "tribunal penal colegiado",
    "juzgado penal colegiado",
)
_ELECTRICITY_TOKENS = (
    "electricidad",
    "edenor",
    "edesur",
    "enre",
    "factura de luz",
    "facturas de luz",
    "servicio eléctrico",
    "servicio electrico",
)
_GAS_TOKENS = (
    "gas natural",
    "enargas",
    "metrogas",
    "camuzzi",
    "factura de gas",
    "facturas de gas",
    "tarifas de gas",
    "tarifa de gas",
)
_WATER_TOKENS = (
    "aysa",
    "eras",
    "agua y cloaca",
    "cloaca",
    "servicio de agua",
    "agua potable",
    "saneamiento",
)

AR_TARIFF_BY_SERVICE: dict[str, tuple[str, ...]] = {
    "electricity": (
        "energia.gob.ar",
        "enre.gob.ar",
        "argentina.gob.ar",
        "boletinoficial.gob.ar",
    ),
    "gas": (
        "energia.gob.ar",
        "enargas.gob.ar",
        "argentina.gob.ar",
        "boletinoficial.gob.ar",
    ),
    "water": (
        "eras.gob.ar",
        "aysa.com.ar",
        "argentina.gob.ar",
        "boletinoficial.gob.ar",
    ),
}

_REGISTRY: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("AR", "OFFICIAL_RECORD", "GOVERNMENT_APPOINTMENT"): (
        "boletinoficial.gob.ar",
        "argentina.gob.ar",
    ),
    ("AR", "OFFICIAL_RECORD", "LAW_OR_DECREE"): (
        "boletinoficial.gob.ar",
        "argentina.gob.ar",
    ),
    ("AR", "OFFICIAL_RECORD", "GENERAL"): (
        "boletinoficial.gob.ar",
        "argentina.gob.ar",
    ),
    ("AR", "OFFICIAL_LAW", "LAW_OR_DECREE"): (
        "boletinoficial.gob.ar",
        "argentina.gob.ar",
    ),
    ("AR", "OFFICIAL_LAW", "GOVERNMENT_APPOINTMENT"): (
        "boletinoficial.gob.ar",
        "argentina.gob.ar",
    ),
    ("AR", "OFFICIAL_LAW", "GENERAL"): (
        "boletinoficial.gob.ar",
        "argentina.gob.ar",
    ),
    ("AR", "OFFICIAL_RECORD", "REGULATED_TARIFF"): (
        "energia.gob.ar",
        "enre.gob.ar",
        "enargas.gob.ar",
        "eras.gob.ar",
        "aysa.com.ar",
        "argentina.gob.ar",
        "boletinoficial.gob.ar",
    ),
    ("AR", "OFFICIAL_LAW", "REGULATED_TARIFF"): (
        "energia.gob.ar",
        "enre.gob.ar",
        "enargas.gob.ar",
        "eras.gob.ar",
        "aysa.com.ar",
        "argentina.gob.ar",
        "boletinoficial.gob.ar",
    ),
    ("AR", "OFFICIAL_STATISTICS", "STATISTICS"): ("indec.gob.ar",),
    ("AR", "OFFICIAL_STATISTICS", "GENERAL"): ("indec.gob.ar",),
    ("AR", "FINANCIAL_OFFICIAL_DATA", "FINANCIAL_OFFICIAL"): ("bcra.gob.ar",),
    ("AR", "FINANCIAL_OFFICIAL_DATA", "GENERAL"): ("bcra.gob.ar",),
    ("AR", "ELECTION_AUTHORITY", "ELECTION"): (
        "electoral.gov.ar",
        "argentina.gob.ar",
    ),
    ("AR", "JUDICIAL_RECORD", "JUDICIAL_CASE"): (
        "pjn.gov.ar",
        "cij.gov.ar",
        "csjn.gov.ar",
    ),
    ("AR", "JUDICIAL_RECORD", "GENERAL"): (
        "pjn.gov.ar",
        "cij.gov.ar",
        "csjn.gov.ar",
    ),
}


def infer_judicial_forum(text: str | None) -> str:
    folded = normalize_name(text or "")
    if any(normalize_name(marker) in folded for marker in _FEDERAL_JUDICIAL_MARKERS):
        return "FEDERAL"
    if any(normalize_name(marker) in folded for marker in _PROVINCIAL_COURT_MARKERS):
        return "PROVINCIAL"
    return "UNKNOWN"


def infer_judicial_province(text: str | None) -> str | None:
    folded = normalize_name(text or "")
    if not folded:
        return None
    matches = [name for name in AR_PROVINCIAL_JUSTICE if name in folded]
    if len(matches) == 1:
        return matches[0]
    if "mendoza" in matches:
        return "mendoza"
    return matches[0] if matches else None


def infer_tariff_service(text: str | None) -> str | None:
    token = (text or "").casefold()
    if any(marker in token for marker in _ELECTRICITY_TOKENS):
        return "electricity"
    if any(marker in token for marker in _GAS_TOKENS):
        return "gas"
    if any(marker in token for marker in _WATER_TOKENS):
        return "water"
    return None


def preferred_domains(
    jurisdiction: str | None,
    verification_target: str | None,
    subject: str | None,
    *,
    province: str | None = None,
    judicial_forum: str | None = None,
    claim_text: str | None = None,
) -> list[str]:
    country = (jurisdiction or "AR").strip().upper() or "AR"
    target = (verification_target or "GENERAL_WEB").strip().upper()
    topic = (subject or "GENERAL").strip().upper()
    domains: list[str] = []
    seen: set[str] = set()

    def _add(values: tuple[str, ...] | list[str]) -> None:
        for domain in values:
            token = domain.strip().lower()
            if not token or token in seen:
                continue
            seen.add(token)
            domains.append(token)

    national: tuple[str, ...] = ()
    for key in (
        (country, target, topic),
        (country, target, "GENERAL"),
    ):
        found = _REGISTRY.get(key)
        if found:
            national = found
            break

    if topic == "REGULATED_TARIFF":
        service = infer_tariff_service(claim_text)
        service_domains = AR_TARIFF_BY_SERVICE.get(service or "", ())
        if service_domains:
            national = service_domains

    provincial: tuple[str, ...] = ()
    forum = (judicial_forum or infer_judicial_forum(claim_text)).strip().upper() or "UNKNOWN"
    if target == "JUDICIAL_RECORD" and forum == "PROVINCIAL":
        named = infer_judicial_province(claim_text) or normalize_name(province or "")
        provincial = AR_PROVINCIAL_JUSTICE.get(named, ())

    for domain in (*provincial, *national):
        _add((domain,))
    return domains


def is_preferred_domain(url_or_domain: str, preferred: list[str]) -> bool:
    token = (url_or_domain or "").strip().lower()
    if "://" in token:
        token = url_domain(token)
    if token.startswith("www."):
        token = token[4:]
    return any(token == domain or token.endswith("." + domain) for domain in preferred)
