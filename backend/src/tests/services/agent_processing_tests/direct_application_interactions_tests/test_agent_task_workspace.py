from api.core.config.api_settings import settings
from api.services.agent_processing.tools.direct_application_interactions.shared.agent_task_workspace import (
    agent_task_workspaces_root,
    resolve_agent_task_workspace,
)


def test_resolve_agent_task_workspace_creates_directory_under_storage_root():
    workspace = resolve_agent_task_workspace("task-plain-id")
    try:
        assert workspace.is_dir(), "workspace directory should be created"
        assert workspace.parent == agent_task_workspaces_root()
        assert workspace.parent.parent == settings.STORAGE_DIR
    finally:
        workspace.rmdir()


def test_resolve_agent_task_workspace_sanitizes_unsafe_characters():
    unsafe_task_id = "../weird id/with spaces"
    workspace = resolve_agent_task_workspace(unsafe_task_id)
    try:
        assert workspace.is_dir(), "sanitized workspace directory should be created"
        # Single sanitized segment directly under the workspaces root - no path traversal.
        assert workspace.parent == agent_task_workspaces_root()
        assert ".." not in workspace.parts
        assert "/" not in workspace.name
    finally:
        workspace.rmdir()


def test_resolve_agent_task_workspace_create_false_does_not_create():
    workspace = resolve_agent_task_workspace("task-not-created", create=False)
    assert not workspace.exists(), "workspace should not be created when create=False"
