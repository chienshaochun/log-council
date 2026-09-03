from __future__ import annotations

import re
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "token",
    "password",
    "passwd",
    "pwd",
    "client_secret",
    "cookie",
    "set_cookie",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;\"']+)"),
    re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/=-]{8,})"),
    re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd|"
        r"client[_-]?secret|cookie|set-cookie)\s*[=:]\s*[\"']?)([^\s,;\"']+)"
    ),
    re.compile(
        r"(?i)([\"'](?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd|"
        r"client[_-]?secret|cookie|set-cookie)[\"']\s*:\s*[\"'])([^\"']+)"
    ),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Return a redacted copy of nested report data without mutating source evidence."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            result[key] = REDACTED if normalized_key in SENSITIVE_KEYS else redact_value(item)
        return result
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value
