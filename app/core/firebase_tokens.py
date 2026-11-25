"""Verification of Firebase ID tokens for Google / Apple / phone sign-in.

The mobile app signs the user in with Google, Apple or a mobile number (SMS
code sent by Firebase Phone Auth) through Firebase Auth and sends the
resulting Firebase ID token. This module checks that token the
same way ``firebase_admin.auth.verify_id_token`` does, using Google's published
public keys, so no private key or service account is needed:

- RS256 signature by one of Google's ``securetoken`` keys,
- ``aud`` equals our Firebase project id and ``iss`` is
  ``https://securetoken.google.com/<project id>``,
- not expired, issued and authenticated in the past, non-empty ``sub``.

The identity (email, or the mobile number for phone sign-in) is read only
from the verified token, never from the request body.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient, PyJWKClientConnectionError

from app.core.errors import ApiError

logger = logging.getLogger(__name__)

_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)
# Google rotates these keys roughly daily; cache them for an hour.
_jwks_client = PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=3600, timeout=10)

# Firebase ``sign_in_provider`` values for the providers we accept.
PROVIDERS = {"google": "google.com", "apple": "apple.com", "phone": "phone"}

_LEEWAY_SECONDS = 60


class FirebaseNotConfiguredError(Exception):
    """No Firebase project id is configured, so no token can be trusted."""


class FirebaseKeysUnavailableError(Exception):
    """Google's public keys could not be fetched (network trouble)."""


class InvalidSignInTokenError(Exception):
    """The token is malformed, forged, expired or for another project/provider."""


@dataclass(frozen=True)
class VerifiedIdentity:
    uid: str
    # Set for Google / Apple; None for phone sign-in.
    email: str | None
    email_verified: bool
    name: str | None
    provider: str
    # E.164 number proven by the SMS code; set only for phone sign-in.
    phone: str | None = None


def verify_id_token(token: str, project_id: str, provider: str) -> VerifiedIdentity:
    """Verify a Firebase ID token and return the identity it proves.

    ``provider`` is ``"google"``, ``"apple"`` or ``"phone"``; a token from any
    other sign-in method (e.g. Firebase email/password) is rejected.
    """
    project_id = (project_id or "").strip()
    if not project_id:
        raise FirebaseNotConfiguredError("Social sign-in is not configured")
    expected_provider = PROVIDERS.get(provider)
    if expected_provider is None:
        raise InvalidSignInTokenError("Unsupported provider")
    if not token or token.count(".") != 2:
        raise InvalidSignInTokenError("Malformed token")

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError as exc:
        raise FirebaseKeysUnavailableError("Could not fetch Google keys") from exc
    except jwt.PyJWTError as exc:
        raise InvalidSignInTokenError("Unknown signing key") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}",
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidSignInTokenError("Token failed verification") from exc

    now = time.time()
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 128:
        raise InvalidSignInTokenError("Token has no subject")
    auth_time = claims.get("auth_time")
    if not isinstance(auth_time, (int, float)) or auth_time > now + _LEEWAY_SECONDS:
        raise InvalidSignInTokenError("Token has an invalid auth_time")

    firebase = claims.get("firebase")
    sign_in_provider = firebase.get("sign_in_provider") if isinstance(firebase, dict) else None
    if sign_in_provider != expected_provider:
        raise InvalidSignInTokenError("Token is from a different sign-in provider")

    if provider == "phone":
        phone = claims.get("phone_number")
        if not isinstance(phone, str) or not phone.startswith("+") or not phone[1:].isdigit():
            raise InvalidSignInTokenError("Token has no phone number")
        return VerifiedIdentity(
            uid=sub, email=None, email_verified=False, name=None, provider=provider, phone=phone
        )

    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise InvalidSignInTokenError("Token has no email")
    name = claims.get("name")
    return VerifiedIdentity(
        uid=sub,
        email=email.strip().lower(),
        email_verified=claims.get("email_verified") is True,
        name=name.strip()[:200] if isinstance(name, str) and name.strip() else None,
        provider=provider,
    )


async def verify_or_raise(token: str, project_id: str, provider: str) -> VerifiedIdentity:
    """``verify_id_token`` off the event loop, with failures as API errors:
    503 when sign-in is not configured or Google's keys are unreachable,
    401 for any token that fails verification."""
    try:
        # The key fetch may hit the network; keep it off the event loop.
        return await asyncio.to_thread(verify_id_token, token, project_id, provider)
    except FirebaseNotConfiguredError as exc:
        what = (
            "Mobile number sign-in isn't"
            if provider == "phone"
            else "Google and Apple sign-in aren't"
        )
        raise ApiError(f"{what} available yet.", status_code=503) from exc
    except FirebaseKeysUnavailableError as exc:
        logger.warning("firebase sign-in: Google keys unavailable")
        raise ApiError(
            "Sign-in is unavailable right now. Please try again.", status_code=503
        ) from exc
    except InvalidSignInTokenError as exc:
        logger.info("firebase sign-in rejected: %s", exc)
        raise ApiError("Sign-in could not be verified. Please try again.", status_code=401) from exc
