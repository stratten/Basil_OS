from __future__ import annotations

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_providers.profiles.launch_validation import (
    ProviderLaunchValidationError,
    ProviderLaunchValidationService,
    validate_profile_structure,
)


async def _seed_profile_and_grant(
    service: SQLiteKnowledgeService,
    *,
    workspace_root: str,
    display_name: str = "Fixture Provider",
    launch_argv: tuple[str, ...] = ("fixture-acp", "--stdio"),
    environment_allowlist: tuple[str, ...] = ("PATH", "HOME"),
    authentication_method_id: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    profile = await service.provider_profile_repository.create_profile(
        display_name=display_name,
        launch_argv=launch_argv,
        environment_allowlist=environment_allowlist,
        authentication_method_id=authentication_method_id,
    )
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=workspace_root,
    )
    return profile, grant


class _FakeProviderRunRepository:
    """Duck-typed test double exercising structural checks the schema forbids in real rows."""

    def __init__(self, *, profile: dict | None, grant: dict | None = None) -> None:
        self._profile = profile
        self._grant = grant

    async def get_profile(self, provider_profile_id: str):
        return self._profile

    async def get_workspace_grant(self, workspace_grant_id: str):
        return self._grant


@pytest.mark.asyncio
async def test_validate_launch_request_succeeds_for_the_granted_root_itself(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    result = await validator.validate_launch_request(
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
        candidate_workspace_path=str(workspace_root),
    )

    assert result.provider_profile_id == profile["id"]
    assert result.display_name == "Fixture Provider"
    assert result.launch_argv == ("fixture-acp", "--stdio")
    assert result.environment_allowlist == ("PATH", "HOME")
    assert result.authentication_method_id is None
    assert result.workspace_grant_id == grant["id"]
    assert result.resolved_workspace_root == str(workspace_root.resolve())
    assert result.capability_state == "unverified"


@pytest.mark.asyncio
async def test_validate_launch_request_succeeds_for_a_real_subdirectory_of_the_grant(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    subdirectory = workspace_root / "nested"
    subdirectory.mkdir(parents=True)
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    result = await validator.validate_launch_request(
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
        candidate_workspace_path=str(subdirectory),
    )

    assert result.resolved_workspace_root == str(subdirectory.resolve())


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_missing_workspace_directory(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="does not exist"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(workspace_root / "missing"),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_candidate_file_instead_of_a_directory(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    candidate_file = workspace_root / "not-a-dir.txt"
    candidate_file.write_text("x")
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="is not a directory"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(candidate_file),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_an_unavailable_workspace_directory(
    tmp_path, monkeypatch
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)
    monkeypatch.setattr("os.access", lambda *args, **kwargs: False)

    with pytest.raises(ProviderLaunchValidationError, match="is not accessible"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_symlink_component_in_the_candidate_path(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    escape_target = tmp_path / "outside"
    escape_target.mkdir()
    linked = workspace_root / "linked"
    linked.symlink_to(escape_target)
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="cannot traverse a symbolic link"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(linked),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_symlinked_granted_root(tmp_path) -> None:
    real_workspace_root = tmp_path / "workspace"
    real_workspace_root.mkdir()
    symlinked_workspace_root = tmp_path / "workspace-link"
    symlinked_workspace_root.symlink_to(real_workspace_root)
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(
        service,
        workspace_root=str(symlinked_workspace_root),
    )
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="cannot traverse a symbolic link"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(real_workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_parent_traversal_outside_the_grant(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)
    traversal_path = str(workspace_root / ".." / "sibling")

    with pytest.raises(ProviderLaunchValidationError, match="is outside the granted root"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=traversal_path,
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_revoked_grant(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    await service.provider_profile_repository.revoke_workspace_grant(str(grant["id"]))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="is not active"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_disabled_profile(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    await service.provider_profile_repository.set_profile_status(str(profile["id"]), "disabled")
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="is not enabled"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_grant_belonging_to_another_profile(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile_one, grant_one = await _seed_profile_and_grant(
        service, workspace_root=str(workspace_root), display_name="Provider One"
    )
    profile_two, _grant_two = await _seed_profile_and_grant(
        service, workspace_root=str(tmp_path / "workspace-two"), display_name="Provider Two"
    )
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="does not belong to profile"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile_two["id"]),
            workspace_grant_id=str(grant_one["id"]),
            candidate_workspace_path=str(workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_a_missing_profile_or_grant(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service, workspace_root=str(workspace_root))
    validator = ProviderLaunchValidationService(service.provider_profile_repository)

    with pytest.raises(ProviderLaunchValidationError, match="provider profile 'missing' does not exist"):
        await validator.validate_launch_request(
            provider_profile_id="missing",
            workspace_grant_id=str(grant["id"]),
            candidate_workspace_path=str(workspace_root),
        )

    with pytest.raises(ProviderLaunchValidationError, match="workspace grant 'missing' does not exist"):
        await validator.validate_launch_request(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id="missing",
            candidate_workspace_path=str(workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_unsupported_transport_via_fake_repository() -> None:
    fake_profile = {
        "id": "fake-profile",
        "display_name": "Fake",
        "transport": "http",
        "launch_argv": ("acp",),
        "environment_allowlist": (),
        "status": "enabled",
        "capability_state": "unverified",
    }
    validator = ProviderLaunchValidationService(_FakeProviderRunRepository(profile=fake_profile))

    with pytest.raises(ProviderLaunchValidationError, match="unsupported transport"):
        await validator.validate_launch_request(
            provider_profile_id="fake-profile",
            workspace_grant_id="fake-grant",
            candidate_workspace_path="/tmp",
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_empty_launch_argv_via_fake_repository() -> None:
    fake_profile = {
        "id": "fake-profile",
        "display_name": "Fake",
        "transport": "acp_stdio",
        "launch_argv": (),
        "environment_allowlist": (),
        "status": "enabled",
        "capability_state": "unverified",
    }
    validator = ProviderLaunchValidationService(_FakeProviderRunRepository(profile=fake_profile))

    with pytest.raises(ProviderLaunchValidationError, match="has no launch_argv"):
        await validator.validate_launch_request(
            provider_profile_id="fake-profile",
            workspace_grant_id="fake-grant",
            candidate_workspace_path="/tmp",
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_non_string_launch_argv_segment_via_fake_repository() -> None:
    fake_profile = {
        "id": "fake-profile",
        "display_name": "Fake",
        "transport": "acp_stdio",
        "launch_argv": ("acp", 1),
        "environment_allowlist": (),
        "status": "enabled",
        "capability_state": "unverified",
    }
    validator = ProviderLaunchValidationService(_FakeProviderRunRepository(profile=fake_profile))

    with pytest.raises(
        ProviderLaunchValidationError,
        match="launch_argv must be a non-empty tuple of nonblank strings",
    ):
        await validator.validate_launch_request(
            provider_profile_id="fake-profile",
            workspace_grant_id="fake-grant",
            candidate_workspace_path="/tmp",
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_invalid_environment_allowlist_via_fake_repository(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    fake_profile = {
        "id": "fake-profile",
        "display_name": "Fake",
        "transport": "acp_stdio",
        "launch_argv": ("acp",),
        "environment_allowlist": ("PATH", 1),
        "status": "enabled",
        "capability_state": "unverified",
    }
    fake_grant = {
        "id": "fake-grant",
        "provider_profile_id": "fake-profile",
        "canonical_workspace_root": str(workspace_root),
        "status": "active",
    }
    validator = ProviderLaunchValidationService(
        _FakeProviderRunRepository(profile=fake_profile, grant=fake_grant)
    )

    with pytest.raises(
        ProviderLaunchValidationError,
        match="environment_allowlist must be a tuple of nonblank strings",
    ):
        await validator.validate_launch_request(
            provider_profile_id="fake-profile",
            workspace_grant_id="fake-grant",
            candidate_workspace_path=str(workspace_root),
        )


@pytest.mark.asyncio
async def test_validate_launch_request_rejects_secret_bearing_argv_via_fake_repository() -> None:
    fake_profile = {
        "id": "fake-profile",
        "display_name": "Fake",
        "transport": "acp_stdio",
        "launch_argv": ("acp", "--api-key=leaked"),
        "environment_allowlist": (),
        "status": "enabled",
        "capability_state": "unverified",
    }
    validator = ProviderLaunchValidationService(_FakeProviderRunRepository(profile=fake_profile))

    with pytest.raises(ProviderLaunchValidationError, match="secret-bearing flag '--api-key'"):
        await validator.validate_launch_request(
            provider_profile_id="fake-profile",
            workspace_grant_id="fake-grant",
            candidate_workspace_path="/tmp",
        )


def test_require_nonblank_rejects_blank_identifiers() -> None:
    from api.services.agent_providers.profiles.launch_validation import (
        _require_nonblank,
    )

    with pytest.raises(ProviderLaunchValidationError, match="must be a nonblank string"):
        _require_nonblank("", "provider_profile_id")
    with pytest.raises(ProviderLaunchValidationError, match="must be a nonblank string"):
        _require_nonblank("   ", "provider_profile_id")


def _well_formed_profile(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "profile-1",
        "display_name": "Fixture Provider",
        "transport": "acp_stdio",
        "launch_argv": ("fixture-acp", "--stdio"),
        "environment_allowlist": ("PATH", "HOME"),
        "status": "enabled",
        "capability_state": "unverified",
    }
    base.update(overrides)
    return base


def test_validate_profile_structure_succeeds_for_a_well_formed_profile() -> None:
    fields = validate_profile_structure(_well_formed_profile(), profile_id="profile-1")

    assert fields.display_name == "Fixture Provider"
    assert fields.launch_argv == ("fixture-acp", "--stdio")
    assert fields.environment_allowlist == ("PATH", "HOME")
    assert fields.authentication_method_id is None
    assert fields.capability_state == "unverified"


def test_validate_profile_structure_preserves_a_configured_authentication_method_id() -> None:
    fields = validate_profile_structure(
        _well_formed_profile(authentication_method_id="api-key"),
        profile_id="profile-1",
    )

    assert fields.authentication_method_id == "api-key"


def test_validate_profile_structure_rejects_an_invalid_authentication_method_id() -> None:
    with pytest.raises(
        ProviderLaunchValidationError,
        match="authentication_method_id must contain",
    ):
        validate_profile_structure(
            _well_formed_profile(authentication_method_id="api key"),
            profile_id="profile-1",
        )


def test_validate_profile_structure_rejects_an_unsupported_transport() -> None:
    profile = _well_formed_profile(transport="http")

    with pytest.raises(ProviderLaunchValidationError, match="unsupported transport"):
        validate_profile_structure(profile, profile_id="profile-1")


def test_validate_profile_structure_rejects_an_empty_launch_argv() -> None:
    profile = _well_formed_profile(launch_argv=())

    with pytest.raises(ProviderLaunchValidationError, match="has no launch_argv"):
        validate_profile_structure(profile, profile_id="profile-1")


def test_validate_profile_structure_rejects_secret_bearing_argv() -> None:
    profile = _well_formed_profile(launch_argv=("fixture-acp", "--api-key=xyz"))

    with pytest.raises(ProviderLaunchValidationError, match="secret-bearing flag"):
        validate_profile_structure(profile, profile_id="profile-1")


def test_validate_profile_structure_does_not_check_enablement() -> None:
    profile = _well_formed_profile(status="disabled")

    fields = validate_profile_structure(profile, profile_id="profile-1")

    assert fields.display_name == "Fixture Provider"
