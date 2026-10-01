"""Route-contract coverage for the read-only provider-profile inventory endpoint (Package 5C.1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.dependencies as dependencies_module
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunConflictError,
)
from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, get_backend_credential_store
from api.core.security.backend_request_guard import BackendRequestGuardMiddleware
from api.routes.provider_profiles.routes import router as provider_profiles_router


class _FakeKnowledgeService:
    def __init__(self, provider_run_repository) -> None:
        self.provider_profile_repository = provider_run_repository
        self.provider_run_repository = provider_run_repository


class _FakeProviderRunRepository:
    def __init__(
        self,
        *,
        profiles: list[dict],
        grants_by_profile: dict[str, list[dict]] | None = None,
        runs_by_profile: dict[str, dict] | None = None,
    ) -> None:
        self._profiles = profiles
        self._grants_by_profile = grants_by_profile or {}
        self._runs_by_profile = runs_by_profile or {}

    async def list_profiles(self, *, include_removed: bool = False):
        if include_removed:
            return list(self._profiles)
        return [p for p in self._profiles if p["status"] != "removed"]

    async def list_workspace_grants_for_profile(
        self, provider_profile_id: str, *, include_revoked: bool = False
    ):
        return self._grants_by_profile.get(provider_profile_id, [])

    async def get_latest_run_for_profile(self, provider_profile_id: str):
        return self._runs_by_profile.get(provider_profile_id)

    async def get_profile(self, provider_profile_id: str):
        return next(
            (profile for profile in self._profiles if profile["id"] == provider_profile_id),
            None,
        )

    async def create_profile(self, **kwargs):
        profile = _sample_profile(
            id=f"profile-{len(self._profiles) + 1}",
            display_name=kwargs["display_name"],
            launch_argv=kwargs["launch_argv"],
            environment_allowlist=kwargs["environment_allowlist"],
            authentication_method_id=kwargs["authentication_method_id"],
            description=kwargs["description"],
            routing_hints=kwargs["routing_hints"],
            revision=0,
            status=kwargs["initial_status"],
        )
        self._profiles.append(profile)
        return profile

    async def update_profile_configuration(self, **kwargs):
        profile = await self.get_profile(kwargs["provider_profile_id"])
        if profile is None or profile["status"] == "removed" or profile["revision"] != kwargs["expected_revision"]:
            raise ProviderRunConflictError("profile conflict")
        profile.update(
            display_name=kwargs["display_name"],
            launch_argv=kwargs["launch_argv"],
            environment_allowlist=kwargs["environment_allowlist"],
            authentication_method_id=kwargs["authentication_method_id"],
            description=kwargs["description"],
            routing_hints=kwargs["routing_hints"],
            revision=profile["revision"] + 1,
        )
        return profile

    async def set_profile_registry_status(self, **kwargs):
        profile = await self.get_profile(kwargs["provider_profile_id"])
        if profile is None or profile["status"] == "removed" or profile["revision"] != kwargs["expected_revision"]:
            raise ProviderRunConflictError("profile conflict")
        profile["status"] = kwargs["next_status"]
        profile["revision"] += 1
        return profile

    async def grant_workspace(self, **kwargs):
        profile_id = kwargs["provider_profile_id"]
        grants = self._grants_by_profile.setdefault(profile_id, [])
        existing = next(
            (grant for grant in grants if grant["canonical_workspace_root"] == kwargs["canonical_workspace_root"]),
            None,
        )
        if existing is not None and existing["status"] == "active" and kwargs["reject_active_duplicate"]:
            raise ProviderRunConflictError("duplicate grant")
        if existing is not None:
            existing.update(
                status="active",
                workspace_label=kwargs["workspace_label"],
                description=kwargs["description"],
                routing_hints=kwargs["routing_hints"],
                revision=existing["revision"] + 1,
            )
            return existing
        grant = {
            "id": f"grant-{len(grants) + 1}",
            "provider_profile_id": profile_id,
            "canonical_workspace_root": kwargs["canonical_workspace_root"],
            "status": "active",
            "workspace_label": kwargs["workspace_label"],
            "description": kwargs["description"],
            "routing_hints": kwargs["routing_hints"],
            "revision": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "revoked_at": None,
        }
        grants.append(grant)
        return grant

    async def update_workspace_grant_configuration(self, **kwargs):
        grant = next(
            (
                grant
                for grant in self._grants_by_profile.get(kwargs["provider_profile_id"], [])
                if grant["id"] == kwargs["workspace_grant_id"]
            ),
            None,
        )
        if grant is None or grant["revision"] != kwargs["expected_revision"]:
            raise ProviderRunConflictError("grant conflict")
        grant.update(
            workspace_label=kwargs["workspace_label"],
            description=kwargs["description"],
            routing_hints=kwargs["routing_hints"],
            revision=grant["revision"] + 1,
        )
        return grant

    async def revoke_workspace_grant_if_revision(self, **kwargs):
        grant = await self.update_workspace_grant_configuration(
            **{
                **kwargs,
                "workspace_label": "",
                "description": None,
                "routing_hints": (),
            }
        )
        grant["status"] = "revoked"
        return grant


def _sample_profile(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "profile-1",
        "display_name": "Fixture Provider",
        "transport": "acp_stdio",
        "launch_argv": ("fixture-acp", "--stdio"),
        "environment_allowlist": ("PATH",),
        "authentication_method_id": None,
        "status": "enabled",
        "capability_state": "unverified",
        "description": None,
        "routing_hints": (),
        "revision": 0,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "removed_at": None,
    }
    base.update(overrides)
    return base


def _build_client(repository: _FakeProviderRunRepository, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: _FakeKnowledgeService(repository),
    )
    app = FastAPI()
    app.add_middleware(BackendRequestGuardMiddleware)
    app.include_router(provider_profiles_router)
    return TestClient(app)


def test_list_provider_profiles_returns_an_empty_list_when_none_exist(monkeypatch) -> None:
    client = _build_client(_FakeProviderRunRepository(profiles=[]), monkeypatch)

    response = client.get("/settings/provider-profiles")

    assert response.status_code == 200
    assert response.json() == {"profiles": []}


def test_list_provider_profiles_surfaces_status_grants_and_validity(monkeypatch) -> None:
    repository = _FakeProviderRunRepository(
        profiles=[_sample_profile()],
        grants_by_profile={
            "profile-1": [
                {
                    "id": "grant-1",
                    "provider_profile_id": "profile-1",
                    "canonical_workspace_root": "/tmp/workspace",
                    "status": "active",
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                    "revoked_at": None,
                }
            ]
        },
    )
    client = _build_client(repository, monkeypatch)

    response = client.get("/settings/provider-profiles")

    assert response.status_code == 200
    body = response.json()
    assert len(body["profiles"]) == 1
    dto = body["profiles"][0]
    assert dto["id"] == "profile-1"
    assert dto["display_name"] == "Fixture Provider"
    assert dto["status"] == "enabled"
    assert dto["capability_state"] == "unverified"
    assert dto["description"] is None
    assert dto["routing_hints"] == []
    assert dto["revision"] == 0
    assert dto["has_observed_capabilities"] is False
    assert dto["is_structurally_valid"] is True
    assert dto["validation_error"] is None
    assert dto["active_workspace_grants"] == [
        {
            "id": "grant-1",
            "canonical_workspace_root": "/tmp/workspace",
            "status": "active",
            "workspace_label": "/tmp/workspace",
            "description": None,
            "routing_hints": [],
            "revision": 0,
        }
    ]


def test_list_provider_profiles_surfaces_a_sanitized_validation_error_for_an_invalid_profile(
    monkeypatch,
) -> None:
    repository = _FakeProviderRunRepository(profiles=[_sample_profile(launch_argv=())])
    client = _build_client(repository, monkeypatch)

    response = client.get("/settings/provider-profiles")

    assert response.status_code == 200
    dto = response.json()["profiles"][0]
    assert dto["is_structurally_valid"] is False
    assert "launch_argv" in dto["validation_error"]


def test_list_provider_profiles_excludes_removed_profiles(monkeypatch) -> None:
    repository = _FakeProviderRunRepository(
        profiles=[_sample_profile(status="removed", removed_at="2026-01-02T00:00:00")]
    )
    client = _build_client(repository, monkeypatch)

    response = client.get("/settings/provider-profiles")

    assert response.status_code == 200
    assert response.json() == {"profiles": []}


def test_list_provider_profiles_marks_a_profile_with_an_observed_capability_snapshot(
    monkeypatch,
) -> None:
    repository = _FakeProviderRunRepository(
        profiles=[_sample_profile()],
        runs_by_profile={"profile-1": {"capabilities": {"fs_read": True}}},
    )
    client = _build_client(repository, monkeypatch)

    response = client.get("/settings/provider-profiles")

    assert response.status_code == 200
    dto = response.json()["profiles"][0]
    assert dto["has_observed_capabilities"] is True


def test_provider_profile_mutations_create_edit_enable_and_soft_remove(monkeypatch) -> None:
    repository = _FakeProviderRunRepository(profiles=[])
    client = _build_client(repository, monkeypatch)
    create_payload = {
        "display_name": "Fixture Provider",
        "launch_argv": ["/bin/sh", "-c", "echo fixture"],
        "environment_allowlist": ["PATH"],
        "authentication_method_id": "api-key",
        "description": "Fixture-only profile",
        "routing_hints": ["fixture"],
    }

    created = client.post("/settings/provider-profiles", json=create_payload)

    assert created.status_code == 201
    assert created.json()["status"] == "disabled"
    assert created.json()["revision"] == 0
    assert created.json()["launch_argv"] == ["/bin/sh", "-c", "echo fixture"]
    assert created.json()["authentication_method_id"] == "api-key"

    profile_id = created.json()["id"]
    configuration = client.get(f"/settings/provider-profiles/{profile_id}")
    assert configuration.status_code == 200
    assert configuration.json()["authentication_method_id"] == "api-key"
    assert "authentication_method_id" not in client.get("/settings/provider-profiles").json()["profiles"][0]
    edited = client.put(
        f"/settings/provider-profiles/{profile_id}",
        json={**create_payload, "display_name": "Edited Fixture", "expected_revision": 0},
    )
    assert edited.status_code == 200
    assert edited.json()["display_name"] == "Edited Fixture"
    assert edited.json()["authentication_method_id"] == "api-key"
    assert edited.json()["revision"] == 1

    enabled = client.post(
        f"/settings/provider-profiles/{profile_id}/enable",
        json={"expected_revision": 1},
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "enabled"
    assert enabled.json()["revision"] == 2

    removed = client.delete(
        f"/settings/provider-profiles/{profile_id}?expected_revision=2"
    )
    assert removed.status_code == 204
    assert client.get("/settings/provider-profiles").json() == {"profiles": []}


def test_provider_workspace_mutations_reject_duplicate_and_stale_requests(monkeypatch) -> None:
    repository = _FakeProviderRunRepository(profiles=[_sample_profile(status="disabled")])
    client = _build_client(repository, monkeypatch)
    create_payload = {
        "canonical_workspace_root": "/tmp/workspace",
        "workspace_label": "Fixture workspace",
        "description": "Disposable root",
        "routing_hints": ["fixture"],
    }

    created = client.post(
        "/settings/provider-profiles/profile-1/workspace-grants",
        json=create_payload,
    )
    assert created.status_code == 201
    grant_id = created.json()["id"]
    assert created.json()["revision"] == 0

    duplicate = client.post(
        "/settings/provider-profiles/profile-1/workspace-grants",
        json=create_payload,
    )
    assert duplicate.status_code == 409

    stale_update = client.put(
        f"/settings/provider-profiles/profile-1/workspace-grants/{grant_id}",
        json={
            "expected_revision": 9,
            "workspace_label": "Stale",
            "description": None,
            "routing_hints": [],
        },
    )
    assert stale_update.status_code == 409

    updated = client.put(
        f"/settings/provider-profiles/profile-1/workspace-grants/{grant_id}",
        json={
            "expected_revision": 0,
            "workspace_label": "Updated fixture",
            "description": None,
            "routing_hints": ["temporary"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 1

    revoked = client.delete(
        f"/settings/provider-profiles/profile-1/workspace-grants/{grant_id}?expected_revision=1"
    )
    assert revoked.status_code == 204


def test_provider_profile_routes_reject_malformed_or_extra_request_fields(monkeypatch) -> None:
    client = _build_client(_FakeProviderRunRepository(profiles=[]), monkeypatch)

    missing_command = client.post(
        "/settings/provider-profiles",
        json={"display_name": "Incomplete Provider"},
    )
    extra_status = client.post(
        "/settings/provider-profiles",
        json={
            "display_name": "Fixture Provider",
            "launch_argv": ["/bin/sh"],
            "status": "enabled",
        },
    )
    malformed_revision = client.post(
        "/settings/provider-profiles/missing/enable",
        json={"expected_revision": -1},
    )
    malformed_authentication_method_ids = [
        client.post(
            "/settings/provider-profiles",
            json={
                "display_name": "Fixture Provider",
                "launch_argv": ["/bin/sh"],
                "authentication_method_id": authentication_method_id,
            },
        )
        for authentication_method_id in (" ", "x" * 129, 1)
    ]

    assert missing_command.status_code == 422
    assert extra_status.status_code == 422
    assert malformed_revision.status_code == 422
    assert all(response.status_code == 422 for response in malformed_authentication_method_ids)


def test_webview_credential_cannot_enable_a_provider_profile(monkeypatch) -> None:
    client = _build_client(_FakeProviderRunRepository(profiles=[]), monkeypatch)
    webview_token = get_backend_credential_store().current().webview_token

    response = client.post(
        "/settings/provider-profiles/missing/enable",
        json={"expected_revision": 0},
        headers={BACKEND_TOKEN_HEADER: webview_token},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "host_credential_required"}
