import httpx

from app.services.fetching import fetch_failure_reason


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
