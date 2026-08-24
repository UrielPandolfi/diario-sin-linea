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
