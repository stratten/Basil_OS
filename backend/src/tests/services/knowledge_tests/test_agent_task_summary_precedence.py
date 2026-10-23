import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.root_summary import (
    extract_result_preview,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.summary_backfill import (
    extract_agent_task_preview,
)


@pytest.mark.parametrize(
    "extract_preview",
    [extract_result_preview, extract_agent_task_preview],
)
def test_summary_prefers_finalizer_preview_and_files_over_top_level(extract_preview):
    preview, file_count = extract_preview({
        "message": "Stale top-level status",
        "files": [{"name": "stale.txt"}],
        "finalizer_result": {
            "summary_text": "Canonical final result",
            "result_payload": {
                "message": "Canonical payload result",
                "files": [{"name": "current.txt"}, {"name": "other.txt"}],
            },
        },
    })

    assert preview == "Canonical payload result"
    assert file_count == 2


@pytest.mark.parametrize(
    "extract_preview",
    [extract_result_preview, extract_agent_task_preview],
)
def test_summary_falls_back_to_top_level_when_finalizer_omits_files(extract_preview):
    preview, file_count = extract_preview({
        "message": "Historical top-level result",
        "files": [{"name": "legacy.txt"}],
        "finalizer_result": {
            "summary_text": "Canonical final result",
            "result_payload": {"message": "Canonical payload result"},
        },
    })

    assert preview == "Canonical payload result"
    assert file_count == 1
