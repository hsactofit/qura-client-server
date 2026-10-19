"""Health and readiness endpoints."""

from __future__ import annotations


def test_health_ok(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/client/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "healthy"
    assert "timestamp" in body["data"]


def test_ready_without_database_is_ok(client) -> None:  # type: ignore[no-untyped-def]
    # No QURA_DATABASE_URL in Phase 1 test settings: ready, not configured.
    response = client.get("/api/client/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["database"] == "not_configured"
