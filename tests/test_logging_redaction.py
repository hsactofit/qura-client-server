"""Sensitive-value redaction in logging."""

from __future__ import annotations

from app.core.logging import redact


def test_redacts_password() -> None:
    assert "hunter2" not in redact('{"password": "hunter2"}')


def test_redacts_authorization_header() -> None:
    assert "abc.def.ghi" not in redact("Authorization: Bearer abc.def.ghi")


def test_redacts_dsn_password() -> None:
    masked = redact("postgresql+asyncpg://user:supersecret@db:5432/qura")
    assert "supersecret" not in masked


def test_redacts_pan_and_aadhaar() -> None:
    assert "ABCDE1234F" not in redact("pan ABCDE1234F")
    assert "1234 5678 9012" not in redact("aadhaar 1234 5678 9012")


def test_keeps_non_sensitive_text() -> None:
    assert redact("just a normal log line") == "just a normal log line"
