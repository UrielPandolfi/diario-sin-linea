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
        "argentina.gob.ar",
        "energia.gob.ar",
        "enre.gob.ar",
        "enargas.gob.ar",
        "eras.gob.ar",
        "aysa.com.ar",
        "boletinoficial.gob.ar",
    ),
    ("AR", "OFFICIAL_LAW", "REGULATED_TARIFF"): (
        "argentina.gob.ar",
        "energia.gob.ar",
        "enre.gob.ar",
        "enargas.gob.ar",
        "eras.gob.ar",
        "aysa.com.ar",
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
        "csjn.gov.ar",
        "pjn.gov.ar",
        "cij.gov.ar",
    ),
    ("AR", "JUDICIAL_RECORD", "GENERAL"): (
        "csjn.gov.ar",
        "pjn.gov.ar",
        "cij.gov.ar",
    ),
}


def preferred_domains(
    jurisdiction: str | None,
    verification_target: str | None,
    subject: str | None,
    *,
    province: str | None = None,
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

    provincial: tuple[str, ...] = ()
    if target == "JUDICIAL_RECORD":
        provincial = AR_PROVINCIAL_JUSTICE.get(normalize_name(province or ""), ())

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
