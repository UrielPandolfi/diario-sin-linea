from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def canonicalize_url(url: str, *, base: str | None = None) -> str:
    raw = url.strip()
    if base:
        raw = urljoin(base, raw)
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))


def url_domain(url: str) -> str:
    netloc = urlparse(canonicalize_url(url)).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc
