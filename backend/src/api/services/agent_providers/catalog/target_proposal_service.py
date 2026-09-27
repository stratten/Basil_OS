"""Semantic validation and durable recording for provider-target proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.service import (
    AgentTaskService,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.discovery_proposal_repository import (
    ProviderDiscoveryProposalRepository,
)
from api.services.agent_processing.tools.external_services.external_catalog.auth import (
    find_external_catalog_connection,
    load_external_catalog_preferences,
)
from api.services.agent_providers.catalog.catalog_service import (
    ProviderCatalogNotFoundError,
    ProviderCatalogService,
    ProviderCatalogUnavailableError,
)

PROPOSAL_TTL_SECONDS = 900
MAX_PROVIDER_CANDIDATES = 4
MAX_SERVICE_CANDIDATES = 4
MAX_EVIDENCE_ITEMS = 12
MAX_IDENTIFIER_BYTES = 128
MAX_RATIONALE_BYTES = 1_000
MAX_EVIDENCE_SUMMARY_BYTES = 500
MAX_EVIDENCE_REFERENCE_BYTES = 500
MAX_CONSTRAINT_BYTES = 160
MAX_RESOLUTION_NOTE_BYTES = 500

PROPOSAL_STATUSES = frozenset(
    {"proposed", "ambiguous", "unavailable", "conflicts_with_user_target"}
)
GROUNDING_TIERS = frozenset(
    {
        "exact_user_target",
        "explicit_reference_or_chain_context",
        "inferred_native_context",
        "insufficient",
    }
)
CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})
EVIDENCE_SOURCES = frozenset(
    {
        "user_request",
        "reference_path",
        "task_chain",
        "screen_context",
        "native_tool_observation",
        "provider_catalog",
        "external_catalog",
    }
)


class ProviderTargetProposalError(RuntimeError):
    """Raised when the proposal has an invalid shape or task binding."""


class ProviderTargetProposalUnavailableError(ProviderTargetProposalError):
    """Raised when a proposal names unavailable current durable inventory."""

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _require_bounded_text(
    value: object,
    field_name: str,
    maximum_bytes: int,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderTargetProposalError(
            f"{field_name} must be a nonblank string"
        )
    cleaned = value.strip()
    if len(cleaned.encode("utf-8")) > maximum_bytes:
        raise ProviderTargetProposalError(
            f"{field_name} must not exceed {maximum_bytes} UTF-8 bytes"
        )
    return cleaned


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum_bytes: int,
) -> str | None:
    if value is None:
        return None
    return _require_bounded_text(value, field_name, maximum_bytes)


def _require_exact_mapping(
    value: object,
    field_name: str,
    keys: frozenset[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProviderTargetProposalError(f"{field_name} must be an object")
    actual_keys = set(value)
    if actual_keys != keys:
        raise ProviderTargetProposalError(
            f"{field_name} must contain exactly {sorted(keys)!r}"
        )
    return value


def _require_mapping_array(
    value: object,
    field_name: str,
    maximum_items: int,
) -> Sequence[Mapping[str, object]]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ProviderTargetProposalError(f"{field_name} must be an array")
    if len(value) > maximum_items:
        raise ProviderTargetProposalError(
            f"{field_name} must contain at most {maximum_items} entries"
        )
    if any(not isinstance(item, Mapping) for item in value):
        raise ProviderTargetProposalError(
            f"{field_name} entries must be objects"
        )
    return value


class ProviderTargetProposalService:
    """Validate proposal inputs without authorizing or dispatching a target."""

    def __init__(
        self,
        *,
        proposal_repository: ProviderDiscoveryProposalRepository,
        provider_catalog_service: ProviderCatalogService,
        agent_task_service: AgentTaskService,
    ) -> None:
        self._proposals = proposal_repository
        self._catalog = provider_catalog_service
        self._agent_tasks = agent_task_service

    def _normalize_provider_candidates(
        self,
        value: object,
    ) -> list[dict[str, str]]:
        raw_candidates = _require_mapping_array(
            value,
            "provider_candidates",
            MAX_PROVIDER_CANDIDATES,
        )
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for index, candidate in enumerate(raw_candidates):
            mapping = _require_exact_mapping(
                candidate,
                f"provider_candidates[{index}]",
                frozenset({"provider_profile_id", "workspace_grant_id"}),
            )
            profile_id = _require_bounded_text(
                mapping["provider_profile_id"],
                f"provider_candidates[{index}].provider_profile_id",
                MAX_IDENTIFIER_BYTES,
            )
            grant_id = _require_bounded_text(
                mapping["workspace_grant_id"],
                f"provider_candidates[{index}].workspace_grant_id",
                MAX_IDENTIFIER_BYTES,
            )
            pair = (profile_id, grant_id)
            if pair in seen:
                raise ProviderTargetProposalError(
                    "provider_candidates must not contain duplicate provider/grant pairs"
                )
            seen.add(pair)
            candidates.append(
                {
                    "provider_profile_id": profile_id,
                    "workspace_grant_id": grant_id,
                }
            )
        return candidates

    def _normalize_service_candidates(
        self,
        value: object,
    ) -> list[dict[str, str | None]]:
        raw_candidates = _require_mapping_array(
            value,
            "service_candidates",
            MAX_SERVICE_CANDIDATES,
        )
        candidates: list[dict[str, str | None]] = []
        seen: set[tuple[str, str | None]] = set()
        for index, candidate in enumerate(raw_candidates):
            mapping = _require_exact_mapping(
                candidate,
                f"service_candidates[{index}]",
                frozenset({"connection_id", "tool_name"}),
            )
            connection_id = _require_bounded_text(
                mapping["connection_id"],
                f"service_candidates[{index}].connection_id",
                MAX_IDENTIFIER_BYTES,
            )
            tool_name = _optional_bounded_text(
                mapping["tool_name"],
                f"service_candidates[{index}].tool_name",
                MAX_IDENTIFIER_BYTES,
            )
            pair = (connection_id, tool_name)
            if pair in seen:
                raise ProviderTargetProposalError(
                    "service_candidates must not contain duplicate connection/tool pairs"
                )
            seen.add(pair)
            candidates.append(
                {
                    "connection_id": connection_id,
                    "tool_name": tool_name,
                }
            )
        return candidates

    def _normalize_evidence(self, value: object) -> list[dict[str, str | None]]:
        raw_evidence = _require_mapping_array(
            value,
            "evidence",
            MAX_EVIDENCE_ITEMS,
        )
        if not raw_evidence:
            raise ProviderTargetProposalError(
                "evidence must contain at least one entry"
            )
        normalized: list[dict[str, str | None]] = []
        for index, item in enumerate(raw_evidence):
            mapping = _require_exact_mapping(
                item,
                f"evidence[{index}]",
                frozenset({"source", "summary", "reference"}),
            )
            source = _require_bounded_text(
                mapping["source"],
                f"evidence[{index}].source",
                MAX_IDENTIFIER_BYTES,
            )
            if source not in EVIDENCE_SOURCES:
                raise ProviderTargetProposalError(
                    f"evidence[{index}].source is unsupported"
                )
            normalized.append(
                {
                    "source": source,
                    "summary": _require_bounded_text(
                        mapping["summary"],
                        f"evidence[{index}].summary",
                        MAX_EVIDENCE_SUMMARY_BYTES,
                    ),
                    "reference": _optional_bounded_text(
                        mapping["reference"],
                        f"evidence[{index}].reference",
                        MAX_EVIDENCE_REFERENCE_BYTES,
                    ),
                }
            )
        return normalized

    def _normalize_exact_user_constraints(
        self,
        value: object,
    ) -> dict[str, str | None]:
        mapping = _require_exact_mapping(
            value,
            "exact_user_constraints",
            frozenset({"provider", "workspace", "service", "tool"}),
        )
        return {
            key: _optional_bounded_text(
                mapping[key],
                f"exact_user_constraints.{key}",
                MAX_CONSTRAINT_BYTES,
            )
            for key in ("provider", "workspace", "service", "tool")
        }

    @staticmethod
    def _validate_status_shape(
        *,
        status: str,
        grounding_tier: str,
        confidence: str,
        provider_candidates: Sequence[Mapping[str, str]],
        exact_user_constraints: Mapping[str, str | None],
        resolution_note: str | None,
    ) -> None:
        if status not in PROPOSAL_STATUSES:
            raise ProviderTargetProposalError("proposal_status is unsupported")
        if grounding_tier not in GROUNDING_TIERS:
            raise ProviderTargetProposalError("grounding_tier is unsupported")
        if confidence not in CONFIDENCE_VALUES:
            raise ProviderTargetProposalError("confidence is unsupported")
        candidate_count = len(provider_candidates)
        if status == "proposed" and candidate_count != 1:
            raise ProviderTargetProposalError(
                "proposed status requires exactly one provider candidate"
            )
        if status == "ambiguous" and not 1 <= candidate_count <= MAX_PROVIDER_CANDIDATES:
            raise ProviderTargetProposalError(
                "ambiguous status requires one to four provider candidates"
            )
        if status == "unavailable" and candidate_count != 0:
            raise ProviderTargetProposalError(
                "unavailable status requires zero provider candidates"
            )
        if status == "conflicts_with_user_target" and candidate_count > MAX_PROVIDER_CANDIDATES:
            raise ProviderTargetProposalError(
                "conflicts_with_user_target permits at most four provider candidates"
            )
        if status == "proposed" and resolution_note is not None:
            raise ProviderTargetProposalError(
                "proposed status must not include resolution_note"
            )
        if status != "proposed" and resolution_note is None:
            raise ProviderTargetProposalError(
                "non-proposed status requires resolution_note"
            )
        if grounding_tier == "inferred_native_context":
            if status == "proposed":
                if confidence != "high":
                    raise ProviderTargetProposalError(
                        "inferred_native_context proposed status requires high confidence"
                    )
                if any(exact_user_constraints.values()):
                    raise ProviderTargetProposalError(
                        "inferred_native_context proposed status must not carry exact user constraints"
                    )
            elif status != "ambiguous":
                raise ProviderTargetProposalError(
                    "inferred_native_context requires ambiguous or high-confidence proposed status"
                )
        if grounding_tier == "insufficient" and status != "unavailable":
            raise ProviderTargetProposalError(
                "insufficient grounding requires unavailable status"
            )
        if status == "conflicts_with_user_target" and not any(
            exact_user_constraints.values()
        ):
            raise ProviderTargetProposalError(
                "conflicts_with_user_target requires an exact user constraint"
            )

    async def _validate_provider_candidates(
        self,
        candidates: Sequence[Mapping[str, str]],
    ) -> None:
        for candidate in candidates:
            profile_id = candidate["provider_profile_id"]
            grant_id = candidate["workspace_grant_id"]
            try:
                detail = await self._catalog.describe_provider(profile_id)
            except (
                ProviderCatalogNotFoundError,
                ProviderCatalogUnavailableError,
            ) as exc:
                raise ProviderTargetProposalUnavailableError(
                    reason_code="invalid_provider_candidate",
                    message="The proposed provider is not currently eligible.",
                ) from exc
            workspaces = detail.get("workspace_candidates")
            if not isinstance(workspaces, list) or not any(
                isinstance(workspace, Mapping)
                and workspace.get("workspace_grant_id") == grant_id
                for workspace in workspaces
            ):
                raise ProviderTargetProposalUnavailableError(
                    reason_code="invalid_provider_candidate",
                    message="The proposed workspace is not currently authorized for that provider.",
                )

    @staticmethod
    def _validate_service_candidates(
        candidates: Sequence[Mapping[str, str | None]],
    ) -> None:
        preferences = load_external_catalog_preferences()
        for candidate in candidates:
            connection_id = candidate["connection_id"]
            tool_name = candidate["tool_name"]
            connection = find_external_catalog_connection(
                preferences,
                connection_id,
            )
            if connection is None or connection.enabled is not True:
                raise ProviderTargetProposalUnavailableError(
                    reason_code="invalid_service_candidate",
                    message="The proposed connected service is not enabled.",
                )
            if tool_name is not None and not any(
                cached_tool.name == tool_name
                for cached_tool in connection.cached_tools
            ):
                raise ProviderTargetProposalUnavailableError(
                    reason_code="invalid_service_candidate",
                    message="The proposed service tool is not in the stored connection inventory.",
                )

    @staticmethod
    def _reference_paths_from_task(task: Any) -> set[str]:
        artifacts = task.accumulated_artifacts
        if not isinstance(artifacts, Mapping):
            return set()
        paths = artifacts.get("reference_paths")
        if isinstance(paths, (str, bytes, bytearray)) or not isinstance(paths, Sequence):
            return set()
        return {path for path in paths if isinstance(path, str)}

    @staticmethod
    def _validate_evidence_context(
        *,
        evidence: Sequence[Mapping[str, str | None]],
        task: Any,
        chain_task_ids: set[str],
        provider_candidates: Sequence[Mapping[str, str]],
        service_candidates: Sequence[Mapping[str, str | None]],
        grounding_tier: str,
    ) -> None:
        reference_paths = ProviderTargetProposalService._reference_paths_from_task(task)
        provider_ids = {
            candidate["provider_profile_id"] for candidate in provider_candidates
        }
        service_ids = {
            candidate["connection_id"] for candidate in service_candidates
        }
        sources = {entry["source"] for entry in evidence}
        for item in evidence:
            source = item["source"]
            reference = item["reference"]
            if source == "reference_path" and reference not in reference_paths:
                raise ProviderTargetProposalError(
                    "reference_path evidence must name a current task reference path"
                )
            if source == "task_chain" and reference not in chain_task_ids:
                raise ProviderTargetProposalError(
                    "task_chain evidence must name an Agent Task in this root chain"
                )
            if source == "screen_context" and not any(
                (task.screen_text, task.app_name, task.window_title)
            ):
                raise ProviderTargetProposalError(
                    "screen_context evidence requires captured screen context"
                )
            if source == "provider_catalog" and reference not in provider_ids:
                raise ProviderTargetProposalError(
                    "provider_catalog evidence must reference a proposed provider ID"
                )
            if source == "external_catalog" and reference not in service_ids:
                raise ProviderTargetProposalError(
                    "external_catalog evidence must reference a proposed connection ID"
                )
        if provider_candidates and "provider_catalog" not in sources:
            raise ProviderTargetProposalError(
                "provider candidates require provider_catalog evidence"
            )
        if service_candidates and "external_catalog" not in sources:
            raise ProviderTargetProposalError(
                "service candidates require external_catalog evidence"
            )
        if grounding_tier == "exact_user_target" and "user_request" not in sources:
            raise ProviderTargetProposalError(
                "exact_user_target requires user_request evidence"
            )
        if (
            grounding_tier == "explicit_reference_or_chain_context"
            and not {"reference_path", "task_chain"}.intersection(sources)
        ):
            raise ProviderTargetProposalError(
                "explicit_reference_or_chain_context requires reference_path or task_chain evidence"
            )
        if (
            grounding_tier == "inferred_native_context"
            and not {"screen_context", "native_tool_observation"}.intersection(sources)
        ):
            raise ProviderTargetProposalError(
                "inferred_native_context requires screen_context or native_tool_observation evidence"
            )

    async def propose_target(
        self,
        *,
        agent_task_id: str,
        root_task_id: str,
        status: str,
        grounding_tier: str,
        confidence: str,
        provider_candidates: Sequence[Mapping[str, object]],
        service_candidates: Sequence[Mapping[str, object]],
        evidence: Sequence[Mapping[str, object]],
        exact_user_constraints: Mapping[str, object],
        rationale: str,
        resolution_note: str | None,
    ) -> dict[str, object]:
        task_id = _require_bounded_text(
            agent_task_id,
            "agent_task_id",
            MAX_IDENTIFIER_BYTES,
        )
        root_id = _require_bounded_text(
            root_task_id,
            "root_task_id",
            MAX_IDENTIFIER_BYTES,
        )
        cleaned_status = _require_bounded_text(
            status,
            "proposal_status",
            MAX_IDENTIFIER_BYTES,
        )
        cleaned_grounding_tier = _require_bounded_text(
            grounding_tier,
            "grounding_tier",
            MAX_IDENTIFIER_BYTES,
        )
        cleaned_confidence = _require_bounded_text(
            confidence,
            "confidence",
            MAX_IDENTIFIER_BYTES,
        )
        cleaned_candidates = self._normalize_provider_candidates(provider_candidates)
        cleaned_services = self._normalize_service_candidates(service_candidates)
        cleaned_evidence = self._normalize_evidence(evidence)
        cleaned_constraints = self._normalize_exact_user_constraints(
            exact_user_constraints
        )
        cleaned_rationale = _require_bounded_text(
            rationale,
            "rationale",
            MAX_RATIONALE_BYTES,
        )
        cleaned_resolution_note = _optional_bounded_text(
            resolution_note,
            "resolution_note",
            MAX_RESOLUTION_NOTE_BYTES,
        )
        self._validate_status_shape(
            status=cleaned_status,
            grounding_tier=cleaned_grounding_tier,
            confidence=cleaned_confidence,
            provider_candidates=cleaned_candidates,
            exact_user_constraints=cleaned_constraints,
            resolution_note=cleaned_resolution_note,
        )
        task = await self._agent_tasks.get_agent_task(task_id)
        if task is None:
            raise ProviderTargetProposalUnavailableError(
                reason_code="missing_agent_task",
                message="The current Agent Task is unavailable.",
            )
        actual_root_id = task.root_task_id or task.id
        if actual_root_id != root_id:
            raise ProviderTargetProposalError(
                "root_task_id does not match the captured Agent Task root"
            )
        chain = await self._agent_tasks.get_agent_task_chain(root_id)
        chain_task_ids = {chain_task.id for chain_task in chain}
        self._validate_evidence_context(
            evidence=cleaned_evidence,
            task=task,
            chain_task_ids=chain_task_ids,
            provider_candidates=cleaned_candidates,
            service_candidates=cleaned_services,
            grounding_tier=cleaned_grounding_tier,
        )
        await self._validate_provider_candidates(cleaned_candidates)
        self._validate_service_candidates(cleaned_services)
        expires_at = (
            datetime.utcnow() + timedelta(seconds=PROPOSAL_TTL_SECONDS)
        ).isoformat()
        return await self._proposals.create_or_get_proposal(
            agent_task_id=task_id,
            root_task_id=root_id,
            status=cleaned_status,
            grounding_tier=cleaned_grounding_tier,
            confidence=cleaned_confidence,
            provider_candidates=cleaned_candidates,
            service_candidates=cleaned_services,
            evidence=cleaned_evidence,
            exact_user_constraints=cleaned_constraints,
            rationale=cleaned_rationale,
            resolution_note=cleaned_resolution_note,
            expires_at=expires_at,
        )
