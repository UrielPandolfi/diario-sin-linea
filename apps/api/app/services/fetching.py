import re
from dataclasses import dataclass

import httpx
import trafilatura

DEFAULT_HEADERS = {"User-Agent": "SinLineaBot/0.1 (+https://sinlinea.local)"}


@dataclass
class FetchResult:
    url: str
    body: str
    content_type: str = ""


def is_extractable_document(url: str, content_type: str = "", body: str = "") -> bool:
    lowered_type = (content_type or "").lower()
    if "pdf" in lowered_type or "octet-stream" in lowered_type:
        return False
    if (url or "").lower().split("?", 1)[0].endswith(".pdf"):
        return False
    sample = body.lstrip()[:8] if body else ""
    if sample.startswith("%PDF"):
        return False
    if "\x00" in (body or ""):
        return False
    return True


class HttpFetcher:
    def fetch(self, url: str, *, timeout: float = 20.0) -> FetchResult:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            final_url = str(response.url)
            if not is_extractable_document(final_url, content_type):
                return FetchResult(url=final_url, body="", content_type=content_type)
            body = response.text
            if not is_extractable_document(final_url, content_type, body):
                return FetchResult(url=final_url, body="", content_type=content_type)
            return FetchResult(url=final_url, body=body, content_type=content_type)


def extract_text(html: str, url: str) -> str | None:
    return trafilatura.extract(html, url=url)


def fetch_failure_reason(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else 0
        if 500 <= code <= 599:
            return "http_5xx"
        if code:
            return f"http_{code}"
        return "http_error"
    if isinstance(exc, httpx.ConnectError):
        return "connect"
    name = re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__)
    return (name[:40] or "error")
