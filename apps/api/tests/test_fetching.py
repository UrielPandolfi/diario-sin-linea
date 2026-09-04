import httpx

from app.services.fetching import fetch_failure_reason, is_extractable_document


def test_fetch_failure_reason_timeout() -> None:
    assert fetch_failure_reason(httpx.TimeoutException("timed out")) == "timeout"


def test_fetch_failure_reason_http_status() -> None:
    request = httpx.Request("GET", "https://ejemplo.test/n")
    forbidden = httpx.HTTPStatusError(
        "forbidden",
        request=request,
        response=httpx.Response(403, request=request),
    )
    server = httpx.HTTPStatusError(
        "error",
        request=request,
        response=httpx.Response(503, request=request),
    )
    assert fetch_failure_reason(forbidden) == "http_403"
    assert fetch_failure_reason(server) == "http_5xx"


def test_fetch_failure_reason_sanitizes_other_errors() -> None:
    assert fetch_failure_reason(RuntimeError("boom <script>")) == "RuntimeError"


def test_pdf_and_nul_bodies_are_not_extractable() -> None:
    assert is_extractable_document("https://indec.gob.ar/ipc.pdf") is False
    assert is_extractable_document("https://indec.gob.ar/ipc", "application/pdf") is False
    assert is_extractable_document("https://indec.gob.ar/ipc", "text/html", "%PDF-1.7\x00obj") is False
    assert is_extractable_document("https://boletinoficial.gob.ar/detalle/1", "text/html", "<p>Decreto</p>") is True
