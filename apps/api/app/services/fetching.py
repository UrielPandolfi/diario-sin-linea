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
            return FetchResult(url=str(response.url), body=response.text, content_type=content_type)


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
