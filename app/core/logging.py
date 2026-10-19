"""Structured logging with sensitive-value redaction.

A logging filter scrubs known-sensitive tokens (authorization headers, cookies,
passwords, session/CSRF values, PAN/Aadhaar) from every log record's message and
arguments before they are emitted. This is defence in depth: code should not log
secrets in the first place, but the filter ensures a stray one is masked.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pythonjsonlogger import json as jsonlogger

_REDACTION = "***redacted***"

# Patterns matched case-insensitively against rendered log text. Each captures a
# key/label and replaces the trailing value with the redaction marker.
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    # Header-style values run to the end of the line (e.g. "Bearer <token>",
    # "name=value; name2=value2"), so consume the remainder after the separator.
    re.compile(r"(authorization)\s*[:=][^\r\n]+", re.IGNORECASE),
    re.compile(r"(set-cookie|cookie)\s*[:=][^\r\n]+", re.IGNORECASE),
    re.compile(r"(password\"?)\s*[:=]\s*\"?[^\s,\"}]+", re.IGNORECASE),
    re.compile(r"(session_secret\"?)\s*[:=]\s*\"?[^\s,\"}]+", re.IGNORECASE),
    re.compile(r"(csrf[_-]?token\"?)\s*[:=]\s*\"?[^\s,\"}]+", re.IGNORECASE),
    # Postgres DSN password: scheme://user:PASSWORD@host
    re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)", re.IGNORECASE),
    # Indian PAN (ABCDE1234F) and 12-digit Aadhaar.
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
]


def _redact_text(text: str) -> str:
    result = text
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.groups == 2:
            result = pattern.sub(rf"\1{_REDACTION}\2", result)
        elif pattern.groups == 1:
            result = pattern.sub(rf"\1={_REDACTION}", result)
        else:
            result = pattern.sub(_REDACTION, result)
    return result


class RedactionFilter(logging.Filter):
    """Masks sensitive values in the formatted message and string args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _redact_text(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: _redact_text(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        _redact_text(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        except Exception:  # never let logging break the request
            return True
        return True


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure root logging once at application startup."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Replace handlers so re-configuration (e.g. in tests) is idempotent.
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler()
    handler.addFilter(RedactionFilter())

    formatter: logging.Formatter
    if json_output:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    handler.setFormatter(formatter)
    root.addHandler(handler)


def redact(value: Any) -> str:
    """Expose single-value redaction for callers that must log user-adjacent text."""
    return _redact_text(str(value))
