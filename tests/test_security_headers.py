"""Regression guard for baseline security headers and the request id.

The ``SecurityHeadersMiddleware`` / ``RequestIdMiddleware`` apply defence-in-depth
response headers on every route. These were implemented but previously unasserted,
so removing the middleware would silently weaken the app. No database is contacted.
"""

from __future__ import annotations


def test_security_headers_present_on_response(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/client/health")
    assert response.status_code == 200
    headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "camera=()" in headers["Permissions-Policy"]


def test_request_id_is_server_generated_and_not_echoed(client) -> None:  # type: ignore[no-untyped-def]
    # The server must mint its own id and never reflect a client-supplied one.
    injected = "client-supplied-should-not-be-trusted"
    response = client.get(
        "/api/client/health", headers={"X-Request-Id": injected}
    )
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    assert request_id is not None
    assert request_id != injected
