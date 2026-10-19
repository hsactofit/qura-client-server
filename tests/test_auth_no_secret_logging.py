"""Passwords and sensitive values must never appear in logs."""

from __future__ import annotations

import logging

from app.core.passwords import hash_password


def _seed_user(store, email, password):  # type: ignore[no-untyped-def]
    from app.db.models.identity import User, UserProfile

    user = User(email=email, password_hash=hash_password(password), role="USER", status="ACTIVE")
    store.seed(user, UserProfile(user_id=user.id))
    return user


def test_signin_does_not_log_password(db_client, store, caplog) -> None:
    _seed_user(store, "log@quramail.io", "SuperSecret123")
    with caplog.at_level(logging.DEBUG):
        db_client.post(
            "/api/client/auth/signin",
            json={"email": "log@quramail.io", "password": "SuperSecret123"},
        )
    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "SuperSecret123" not in combined


def test_signup_does_not_log_password(db_client, store, caplog) -> None:
    from datetime import UTC, datetime, timedelta

    from app.core.tokens import hash_token
    from app.db.models.identity import Invite

    store.seed(
        Invite(
            email="new@quramail.io",
            token_hash=hash_token("raw-invite"),
            role="USER",
            is_used=False,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    with caplog.at_level(logging.DEBUG):
        db_client.post(
            "/api/client/auth/signup",
            json={
                "email": "new@quramail.io",
                "password": "SuperSecret123",
                "fullName": "New",
                "inviteToken": "raw-invite",
            },
        )
    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "SuperSecret123" not in combined
