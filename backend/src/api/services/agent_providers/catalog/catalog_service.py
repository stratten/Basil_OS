"""Bounded read-only semantic inventory for registered ACP providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunPersistenceError,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.profile_repository import (
    ProviderProfileRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.run_repository import (
    ProviderRunRepository,
)
from api.services.agent_providers.profiles.launch_validation import (
    ProviderLaunchValidationError,
    validate_profile_structure,
)

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
MAX_IDENTIFIER_BYTES = 128
MAX_DESCRIPTION_BYTES = 1_000
MAX_HINT_BYTES = 160
MAX_LABEL_BYTES = 120
MAX_CAPABILITY_DEPTH = 4
MAX_CAPABILITY_ITEMS = 32
MAX_CAPABILITY_TEXT_BYTES = 256
_TRUNCATION_SUFFIX = "[truncated]"
_REDACTED = "[redacted]"
_REDACTED_PATH = "[redacted path]"

_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|credential|authorization)\s*([:=])\s*([^\s,;]+)"
)
_SECRET_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:sk-|sk_|ghp_|github_pat_)[A-Za-z0-9_-]{6,}\b"
)
_PATH_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:file://[^\s,;]+|~/(?:[^\s,;]+)|(?<![A-Za-z0-9_/])/(?!/)[^\s,;]+|(?:\.\.?/)[^\s,;]+|[A-Za-z]:\\[^\s,;]+)"
)
_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


class ProviderCatalogNotFoundError(RuntimeError):
    """An opaque provider profile ID is not present in durable state."""


class ProviderCatalogUnavailableError(RuntimeError):
    """A real provider profile is not currently eligible for catalog use."""

    def __init__(
        self,
        *,
        reason_code: str,
        message: str,
        user_action_required: str,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.user_action_required = user_action_required


def _sanitize_text(value: object) -> str:
    text = str(value if value is not None else "")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(
        character if character in ("\n", "\t") or ord(character) >= 0x20 else " "
        for character in normalized
    )
    redacted_assignments = _SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
        cleaned,
    )
    redacted_tokens = _SECRET_TOKEN_PATTERN.sub(_REDACTED, redacted_assignments)
    return _PATH_TOKEN_PATTERN.sub(_REDACTED_PATH, redacted_tokens)


def _bounded_text(value: object, *, maximum_bytes: int) -> str:
    text = _sanitize_text(value)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum_bytes:
        return text
    suffix = _TRUNCATION_SUFFIX.encode("utf-8")
    budget = max(maximum_bytes - len(suffix), 0)
    return encoded[:budget].decode("utf-8", errors="ignore") + _TRUNCATION_SUFFIX


def _safe_identifier(value: object) -> str:
    return _bounded_text(value, maximum_bytes=MAX_IDENTIFIER_BYTES)


def _safe_optional_description(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _bounded_text(value.strip(), maximum_bytes=MAX_DESCRIPTION_BYTES)


def _safe_routing_hints(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [
        _bounded_text(item, maximum_bytes=MAX_HINT_BYTES)
        for item in list(value)[:8]
        if isinstance(item, str) and item.strip()
    ]


def _looks_like_path(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(("/", "~/", "file://", "./", "../")) or bool(
        re.match(r"^[A-Za-z]:\\", stripped)
    )


def _is_sensitive_key(value: str) -> bool:
    normalized = value.lower().replace("-", "_")
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _safe_capability_value(value: object, *, depth: int = 0) -> object:
    if depth >= MAX_CAPABILITY_DEPTH:
        return _TRUNCATION_SUFFIX
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _looks_like_path(value):
            return _REDACTED_PATH
        return _bounded_text(value, maximum_bytes=MAX_CAPABILITY_TEXT_BYTES)
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for raw_key, item in list(value.items())[:MAX_CAPABILITY_ITEMS]:
            key = _bounded_text(raw_key, maximum_bytes=MAX_IDENTIFIER_BYTES)
            if _is_sensitive_key(key):
                safe[key] = _REDACTED
            else:
                safe[key] = _safe_capability_value(item, depth=depth + 1)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _safe_capability_value(item, depth=depth + 1)
            for item in list(value)[:MAX_CAPABILITY_ITEMS]
        ]
    return "[unsupported capability value]"


def _unavailable(
    *,
    reason_code: str,
    message: str,
    user_action_required: str,
) -> ProviderCatalogUnavailableError:
    return ProviderCatalogUnavailableError(
        reason_code=reason_code,
        message=message,
        user_action_required=user_action_required,
    )


class ProviderCatalogService:
    """Read live profile/run state and return only model-safe catalog facts."""

    def __init__(
        self,
        provider_profile_repository: ProviderProfileRepository,
        provider_run_repository: ProviderRunRepository,
    ) -> None:
        self._profiles = provider_profile_repository
        self._runs = provider_run_repository

    async def list_providers(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> dict[str, object]:
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if type(limit) is not int or limit < 1 or limit > MAX_PAGE_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")

        profile_ids = await self._profiles.list_profile_ids()
        eligible: list[dict[str, object]] = []
        for profile_id in profile_ids:
            try:
                detail = await self._load_eligible_provider(profile_id)
            except (ProviderCatalogNotFoundError, ProviderCatalogUnavailableError):
                continue
            eligible.append(self._summary(detail))

        page = eligible[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "providers": page,
            "offset": offset,
            "limit": limit,
            "total_eligible": len(eligible),
            "next_offset": next_offset if next_offset < len(eligible) else None,
        }

    async def describe_provider(self, provider_profile_id: str) -> dict[str, object]:
        if not isinstance(provider_profile_id, str) or not provider_profile_id.strip():
            raise ValueError("provider_profile_id must be a nonblank string")
        return await self._load_eligible_provider(provider_profile_id.strip())

    async def _load_eligible_provider(self, provider_profile_id: str) -> dict[str, object]:
        try:
            profile = await self._profiles.get_profile(provider_profile_id)
        except ProviderRunPersistenceError as exc:
            raise _unavailable(
                reason_code="invalid_profile",
                message="The provider profile metadata is invalid.",
                user_action_required="Repair or recreate this provider profile in Settings.",
            ) from exc
        if profile is None:
            raise ProviderCatalogNotFoundError("No provider profile exists for that ID.")

        status = profile.get("status")
        if status == "removed":
            raise _unavailable(
                reason_code="removed",
                message="The provider profile has been removed.",
                user_action_required="Register a new provider profile in Settings if it is still needed.",
            )
        if status == "disabled":
            raise _unavailable(
                reason_code="disabled",
                message="The provider profile is not enabled.",
                user_action_required="Enable this provider profile in Settings before using it.",
            )
        if status != "enabled":
            raise _unavailable(
                reason_code="invalid_profile",
                message="The provider profile metadata is invalid.",
                user_action_required="Repair this provider profile in Settings before using it.",
            )

        try:
            validated = validate_profile_structure(profile, profile_id=provider_profile_id)
        except (ProviderLaunchValidationError, KeyError, TypeError) as exc:
            raise _unavailable(
                reason_code="invalid_profile",
                message="The provider profile metadata is invalid.",
                user_action_required="Repair this provider profile in Settings before using it.",
            ) from exc

        try:
            grants = await self._profiles.list_workspace_grants_for_profile(
                provider_profile_id,
                include_revoked=False,
            )
        except ProviderRunPersistenceError as exc:
            raise _unavailable(
                reason_code="invalid_workspace_grants",
                message="The provider workspace authorization metadata is invalid.",
                user_action_required="Repair or recreate this provider's workspace grants in Settings.",
            ) from exc
        active_grants = [grant for grant in grants if grant.get("status") == "active"]
        if not active_grants:
            raise _unavailable(
                reason_code="no_active_workspace_grants",
                message="The provider has no active workspace grants.",
                user_action_required="Add an authorized workspace to this provider in Settings.",
            )

        try:
            latest_run = await self._runs.get_latest_run_for_profile(provider_profile_id)
        except ProviderRunPersistenceError as exc:
            raise _unavailable(
                reason_code="invalid_observed_capabilities",
                message="The provider's observed capability record is invalid.",
                user_action_required="Run or re-register this provider after repairing its local record.",
            ) from exc
        if latest_run is not None and not isinstance(latest_run, Mapping):
            raise _unavailable(
                reason_code="invalid_observed_capabilities",
                message="The provider's observed capability record is invalid.",
                user_action_required="Run or re-register this provider after repairing its local record.",
            )
        observed_capabilities = latest_run.get("capabilities") if latest_run else None
        if observed_capabilities is not None and not isinstance(
            observed_capabilities,
            Mapping,
        ):
            raise _unavailable(
                reason_code="invalid_observed_capabilities",
                message="The provider's observed capability record is invalid.",
                user_action_required="Run or re-register this provider after repairing its local record.",
            )
        capability_state = (
            "observed" if isinstance(observed_capabilities, Mapping) else "unverified"
        )

        workspace_candidates = [
            {
                "workspace_grant_id": _safe_identifier(grant.get("id", "")),
                "workspace_label": _bounded_text(
                    grant.get("workspace_label", "Authorized workspace"),
                    maximum_bytes=MAX_LABEL_BYTES,
                ),
                "description": _safe_optional_description(grant.get("description")),
                "routing_hints": _safe_routing_hints(grant.get("routing_hints")),
            }
            for grant in active_grants
        ]
        return {
            "provider_profile_id": _safe_identifier(profile.get("id", provider_profile_id)),
            "display_name": _bounded_text(
                validated.display_name,
                maximum_bytes=MAX_LABEL_BYTES,
            ),
            "description": _safe_optional_description(profile.get("description")),
            "routing_hints": _safe_routing_hints(profile.get("routing_hints")),
            "capability_state": capability_state,
            "observed_capabilities": (
                _safe_capability_value(observed_capabilities)
                if capability_state == "observed"
                else None
            ),
            "workspace_candidates": workspace_candidates,
        }

    @staticmethod
    def _summary(detail: dict[str, object]) -> dict[str, object]:
        workspace_candidates = detail["workspace_candidates"]
        assert isinstance(workspace_candidates, list)
        return {
            "provider_profile_id": detail["provider_profile_id"],
            "display_name": detail["display_name"],
            "description": detail["description"],
            "routing_hints": detail["routing_hints"],
            "capability_state": detail["capability_state"],
            "active_workspace_grant_count": len(workspace_candidates),
            "workspace_candidates": workspace_candidates,
        }
