"""Safety helpers for browser automation tools."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

SENSITIVE_FIELD_PATTERN = re.compile(
    r"password|passcode|token|secret|credential|one-time|otp|2fa|mfa",
    re.IGNORECASE,
)
CAPTCHA_PATTERN = re.compile(r"captcha|recaptcha|hcaptcha|verify you are human", re.IGNORECASE)


def normalize_domain_from_url(url: Optional[str]) -> str:
    """Return a normalized hostname from a URL-like value."""
    if not url:
        return ""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname and "://" not in url:
        hostname = urlparse(f"https://{url}").hostname
    return (hostname or "").strip().lower().rstrip(".")


def can_remember_sensitive_fill_domain(domain: str) -> bool:
    """Return whether a domain is eligible for remembered sensitive-fill approval."""
    normalized = normalize_domain_from_url(domain)
    if not normalized or normalized in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        ipaddress.ip_address(normalized)
        return False
    except ValueError:
        return True


def is_sensitive_field_metadata(field_metadata: Optional[Mapping[str, Any]], selector: str = "") -> bool:
    """Classify whether DOM field metadata describes a sensitive field."""
    metadata = field_metadata or {}
    if metadata.get("sensitive") is True or metadata.get("credentialLike") is True:
        return True

    values = [
        selector,
        metadata.get("type"),
        metadata.get("name"),
        metadata.get("id"),
        metadata.get("autocomplete"),
        metadata.get("ariaLabel"),
        metadata.get("placeholder"),
        metadata.get("label"),
    ]
    searchable = " ".join(str(value) for value in values if value)
    return bool(SENSITIVE_FIELD_PATTERN.search(searchable))


def is_captcha_like_content(text: Optional[str]) -> bool:
    """Classify whether page text suggests a CAPTCHA or human-verification step."""
    return bool(text and CAPTCHA_PATTERN.search(text))


def build_redacted_value_label(value: Optional[str]) -> str:
    """Return a display-safe label for a form-fill value."""
    if not value:
        return "empty"
    return f"redacted ({len(value)} characters)"


def build_sensitive_field_label(field_metadata: Optional[Mapping[str, Any]], selector: str) -> str:
    """Return a stable, user-facing label for a sensitive browser field."""
    metadata = field_metadata or {}
    for key in ("label", "ariaLabel", "placeholder", "name", "id"):
        value = metadata.get(key)
        if value:
            return str(value)
    return selector or "Sensitive field"

