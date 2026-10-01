"""Data-driven per-tool-family and mixed-tool-family agent-task scenarios.

Each spec crafts a real user prompt intended to compel one or more specific
tools, submits it as a real agent task per model (via the same
process_agent_task_direct path run_agent_task already uses), and verifies
via the work ledger (agent_work_receipts) that an expected tool was actually
invoked -- not merely that the task completed without error. This also lets
cross-model tool-selection differences on identical input surface as data
(different (service, method) pairs invoked for the same prompt), which is
the point: it is a signal for future model-selection/cost/latency tuning,
not a hard-fail unless no candidate tool from the expected set fired at all.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from api.dependencies import get_sqlite_knowledge_service
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
    family_names_for_tool_name,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import ScheduledAgentTaskService

from . import scaffolding
from .ledger_evidence import (
    all_required_groups_satisfied,
    all_required_services_invoked,
    any_expected_invoked,
)
from .registry_enumeration import ModelCandidate
from .scenarios import (
    AGENT_TASK_POLL_INTERVAL_SECONDS,
    AGENT_TASK_POLL_TIMEOUT_SECONDS,
    AGENT_TASK_STATUS_CHECK_TIMEOUT_SECONDS,
    AGENT_TASK_SUBMIT_TIMEOUT_SECONDS,
    SMOKE_TAG,
    ScenarioOutcome,
)

Cleanup = Callable[["ScenarioSandbox"], Awaitable[None]]

_SERVICE_TO_FAMILY = {
    "file_service": "file",
    "email_service": "email",
    "shell_service": "shell",
    "applescript_service": "automation",
}


@dataclass
class ScenarioSandbox:
    """Per-run scratch state a spec's prompt_builder/cleanup can reference."""

    marker: str
    tmp_dir: Path
    values: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolScenarioSpec:
    scenario_id: str
    family: str
    build_prompt: Callable[[ScenarioSandbox], str]
    expected_service_methods: tuple[tuple[str, str], ...] = ()
    required_groups: tuple[tuple[tuple[str, str], ...], ...] = ()
    required_services: tuple[str, ...] = ()
    setup: Optional[Callable[[ScenarioSandbox], None]] = None
    cleanup: Optional[Cleanup] = None


def _new_sandbox() -> ScenarioSandbox:
    marker = uuid.uuid4().hex[:10]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"basil-smoke-{marker}-"))
    return ScenarioSandbox(marker=marker, tmp_dir=tmp_dir, values={})


def _families_for_service_method(service: str, method: str) -> set[str]:
    mapped = _SERVICE_TO_FAMILY.get(service)
    if mapped:
        return {mapped}
    if service == "direct_tool":
        return set(family_names_for_tool_name(method))
    return set()


def distinct_families_for_spec(spec: ToolScenarioSpec) -> set[str]:
    """Return the distinct tool families covered by a scenario spec."""
    families: set[str] = set()
    pairs: list[tuple[str, str]] = list(spec.expected_service_methods)
    for group in spec.required_groups:
        pairs.extend(group)
    for service in spec.required_services:
        families.add(_SERVICE_TO_FAMILY.get(service, service))
    for service, method in pairs:
        families.update(_families_for_service_method(service, method))
    return families


def spec_invocation_satisfied(database_path: Path, agent_task_id: str, spec: ToolScenarioSpec) -> bool:
    """Return True when ledger evidence satisfies the scenario's invocation contract."""
    if spec.required_groups and not all_required_groups_satisfied(
        database_path, agent_task_id, spec.required_groups
    ):
        return False
    if spec.required_services and not all_required_services_invoked(
        database_path, agent_task_id, spec.required_services
    ):
        return False
    if spec.expected_service_methods and not any_expected_invoked(
        database_path, agent_task_id, spec.expected_service_methods
    ):
        return False
    return bool(spec.expected_service_methods or spec.required_groups or spec.required_services)


def _setup_file_fixture(sandbox: ScenarioSandbox) -> None:
    fixture = sandbox.tmp_dir / "smoke-fixture.txt"
    fixture.write_text(f"basil-smoke-marker={sandbox.marker}", encoding="utf-8")
    sandbox.values["fixture_path"] = fixture


def _setup_browser_fixture(sandbox: ScenarioSandbox) -> None:
    html_path = sandbox.tmp_dir / "fixture.html"
    html_path.write_text(
        (
            f"<!DOCTYPE html><html><head><title>Basil Smoke {sandbox.marker}</title></head>"
            f"<body><h1>Smoke test</h1></body></html>"
        ),
        encoding="utf-8",
    )
    sandbox.values["html_path"] = html_path


def _setup_vision_fixture(sandbox: ScenarioSandbox) -> None:
    from PIL import Image

    png_path = sandbox.tmp_dir / "red-square.png"
    Image.new("RGB", (32, 32), color=(255, 0, 0)).save(png_path)
    sandbox.values["png_path"] = png_path


def _setup_number_fixture(sandbox: ScenarioSandbox) -> None:
    fixture = sandbox.tmp_dir / "number-fixture.txt"
    fixture.write_text("42", encoding="utf-8")
    sandbox.values["number_fixture"] = fixture


def _setup_mixed_email_file(sandbox: ScenarioSandbox) -> None:
    output_dir = Path.home() / "Desktop" / "BasilSmokeOutput"
    if not output_dir.is_dir():
        raise ValueError(
            f"Required output directory does not exist: {output_dir}. "
            "Create it once to approve low-impact desktop writes for mixed_email_file."
        )
    sandbox.values["output_dir"] = output_dir


async def _cleanup_scheduled_tasks(sandbox: ScenarioSandbox) -> None:
    service = ScheduledAgentTaskService()
    marker = sandbox.marker
    for task in await service.list_scheduled_agent_tasks(include_inactive=True):
        text = f"{task.get('agent_task_text') or ''} {task.get('title') or ''}"
        if marker in text:
            await service.delete_scheduled_agent_task(task["id"])


async def run_tool_scenario(candidate: ModelCandidate, spec: ToolScenarioSpec) -> ScenarioOutcome:
    sandbox = _new_sandbox()
    try:
        if spec.setup:
            try:
                spec.setup(sandbox)
            except ValueError as exc:
                return ScenarioOutcome.skip(str(exc))

        prompt = f"{SMOKE_TAG} {spec.build_prompt(sandbox)}"

        service = scaffolding.get_agent_task_submission_service()
        try:
            result = await asyncio.wait_for(
                service.process_agent_task_direct(
                    agent_task=prompt,
                    model_id=candidate.model_id,
                    approval_policy_override={"approval_mode": "always_approve"},
                ),
                timeout=AGENT_TASK_SUBMIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return ScenarioOutcome.fail(
                f"process_agent_task_direct did not return within {AGENT_TASK_SUBMIT_TIMEOUT_SECONDS:.0f}s"
            )
        except Exception as exc:
            return ScenarioOutcome.fail(f"process_agent_task_direct raised: {exc}")

        if not result.get("success", True) and result.get("status") == "failed":
            return ScenarioOutcome.fail(
                f"submission failed before routing: {result.get('error') or result.get('message')}"
            )

        agent_task_id = result.get("agent_task_id")
        if not agent_task_id:
            return ScenarioOutcome.fail(f"no agent_task_id in submission result: {result}")

        deadline = asyncio.get_event_loop().time() + AGENT_TASK_POLL_TIMEOUT_SECONDS
        last_status = None
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(AGENT_TASK_POLL_INTERVAL_SECONDS)
            try:
                last_status = await asyncio.wait_for(
                    service.agent_task_orchestrator.get_agent_task_status(agent_task_id),
                    timeout=AGENT_TASK_STATUS_CHECK_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                return ScenarioOutcome.fail(f"get_agent_task_status raised: {exc}")
            if last_status and last_status.get("status") in {"completed", "failed", "error", "canceled"}:
                break

        if not last_status:
            return ScenarioOutcome.fail(f"agent_task {agent_task_id} never appeared in the db")

        database_path = Path(get_sqlite_knowledge_service().db_path)
        invoked_expected = spec_invocation_satisfied(database_path, agent_task_id, spec)

        if last_status.get("status") == "completed":
            if invoked_expected:
                return ScenarioOutcome.ok(f"agent_task_id={agent_task_id}")
            return ScenarioOutcome.fail(
                f"agent_task {agent_task_id} completed but ledger evidence did not satisfy "
                f"{spec.scenario_id}: expected={spec.expected_service_methods} "
                f"groups={spec.required_groups} services={spec.required_services}"
            )
        if last_status.get("status") in {"failed", "error"}:
            detail = last_status.get("error") or last_status.get("message") or last_status.get("status")
            lowered = str(detail).lower()
            if "no email client" in lowered:
                return ScenarioOutcome.skip(f"no email client available: {detail}")
            return ScenarioOutcome.fail(f"agent_task {agent_task_id} ended status={last_status.get('status')}")
        return ScenarioOutcome.fail(
            f"agent_task {agent_task_id} did not reach a terminal status within "
            f"{AGENT_TASK_POLL_TIMEOUT_SECONDS:.0f}s"
        )
    finally:
        if spec.cleanup:
            try:
                await spec.cleanup(sandbox)
            except Exception:
                pass
        shutil.rmtree(sandbox.tmp_dir, ignore_errors=True)


TOOL_SCENARIO_SPECS: dict[str, ToolScenarioSpec] = {
    "tool_file": ToolScenarioSpec(
        scenario_id="tool_file",
        family="file",
        setup=_setup_file_fixture,
        build_prompt=lambda sandbox: (
            f"Find the file named 'smoke-fixture.txt' inside {sandbox.values['fixture_path'].parent} "
            f"and tell me its exact contents."
        ),
        expected_service_methods=(
            ("file_service", "find_file_for_llm"),
            ("file_service", "prepare_file_by_path"),
        ),
    ),
    "tool_email": ToolScenarioSpec(
        scenario_id="tool_email",
        family="email",
        build_prompt=lambda _sandbox: (
            "Use only the email tool's metadata lookup to check how many messages are in the Inbox "
            "from the last 24 hours. Do not read full bodies. Do not compose, send, move, delete, "
            "flag, or otherwise modify Mail."
        ),
        expected_service_methods=(("email_service", "get_email_metadata"),),
    ),
    "tool_browser": ToolScenarioSpec(
        scenario_id="tool_browser",
        family="browser",
        setup=_setup_browser_fixture,
        build_prompt=lambda sandbox: (
            f"Navigate the browser to file://{sandbox.values['html_path']} and tell me the exact page title."
        ),
        expected_service_methods=(("direct_tool", "browser_interact"),),
    ),
    "tool_vision": ToolScenarioSpec(
        scenario_id="tool_vision",
        family="vision",
        setup=_setup_vision_fixture,
        build_prompt=lambda sandbox: (
            f"Analyze the image at {sandbox.values['png_path']} and tell me the dominant color."
        ),
        expected_service_methods=(("direct_tool", "analyze_with_vision"),),
    ),
    "tool_shell": ToolScenarioSpec(
        scenario_id="tool_shell",
        family="shell",
        build_prompt=lambda sandbox: (
            f"Use the shell tool to run echo printing the exact text 'basil-smoke-{sandbox.marker}' "
            f"and tell me the output."
        ),
        expected_service_methods=(("shell_service", "execute_command"),),
    ),
    "tool_automation": ToolScenarioSpec(
        scenario_id="tool_automation",
        family="automation",
        build_prompt=lambda _sandbox: (
            "Use AppleScript to get the name of the frontmost application right now and tell me what "
            "it is. Do not change anything."
        ),
        expected_service_methods=(
            ("applescript_service", "execute_applescript"),
            ("applescript_service", "generate_and_execute_applescript"),
        ),
    ),
    "tool_external": ToolScenarioSpec(
        scenario_id="tool_external",
        family="external",
        build_prompt=lambda _sandbox: (
            "Search the web for the current official time in Tokyo, Japan, right now."
        ),
        expected_service_methods=(("direct_tool", "web_search"),),
    ),
    "tool_memory": ToolScenarioSpec(
        scenario_id="tool_memory",
        family="memory",
        build_prompt=lambda _sandbox: "Search your memory for anything you remember about my preferences.",
        expected_service_methods=(
            ("direct_tool", "memory_search"),
            ("direct_tool", "memory_read"),
        ),
    ),
    "tool_todos": ToolScenarioSpec(
        scenario_id="tool_todos",
        family="todos",
        build_prompt=lambda _sandbox: (
            "Use the To-Do list tool to list my current open Basil To-Dos and report only their titles. "
            "Do not create, update, annotate, delegate, complete, or delete any To-Do."
        ),
        expected_service_methods=(("direct_tool", "list_todos"),),
    ),
    "tool_schedule": ToolScenarioSpec(
        scenario_id="tool_schedule",
        family="schedule",
        build_prompt=lambda sandbox: (
            f"Schedule a one-time reminder agent task for January 1, 2099 that just says "
            f"hello-{sandbox.marker}. Do not run it now."
        ),
        expected_service_methods=(("direct_tool", "create_scheduled_agent_task_from_prompt"),),
        cleanup=_cleanup_scheduled_tasks,
    ),
    "tool_activity": ToolScenarioSpec(
        scenario_id="tool_activity",
        family="activity",
        build_prompt=lambda _sandbox: (
            "Tell me what app I was using most in the last hour, using your activity history tool."
        ),
        expected_service_methods=(("direct_tool", "query_activities"),),
    ),
    "tool_recall": ToolScenarioSpec(
        scenario_id="tool_recall",
        family="recall",
        build_prompt=lambda _sandbox: (
            "Before doing anything else, recall what you already know from earlier in this thread."
        ),
        expected_service_methods=(("direct_tool", "recall_agent_tasks"),),
    ),
    "tool_iterative": ToolScenarioSpec(
        scenario_id="tool_iterative",
        family="iterative",
        build_prompt=lambda sandbox: (
            "You may have an unknown, potentially large number of items to review in this task. "
            f"Use your iterative work tracker to record that you are starting review marker "
            f"{sandbox.marker} before doing anything else."
        ),
        expected_service_methods=(("direct_tool", "iterative_work"),),
    ),
    "tool_provider": ToolScenarioSpec(
        scenario_id="tool_provider",
        family="provider",
        build_prompt=lambda _sandbox: (
            "Use the provider catalog to list registered ACP providers only. Do not create a "
            "proposal, authorize a target, launch a provider, delegate work, or modify any provider state."
        ),
        expected_service_methods=(("direct_tool", "provider_catalog"),),
    ),
    "tool_delegation": ToolScenarioSpec(
        scenario_id="tool_delegation",
        family="delegation",
        build_prompt=lambda sandbox: (
            f"Delegate one independent bounded subtask to inspect the smoke marker {sandbox.marker}. "
            "The child should report only whether the marker is present; do not modify files or contact external services."
        ),
        expected_service_methods=(("direct_tool", "delegated_agent"),),
    ),
    "tool_retrieval": ToolScenarioSpec(
        scenario_id="tool_retrieval",
        family="retrieval",
        build_prompt=lambda _sandbox: (
            "Use Basil's local-history retrieval tool to search for prior work about model testing. "
            "Return only a short summary; do not modify any records."
        ),
        expected_service_methods=(("direct_tool", "retrieve_basil_history"),),
    ),
    "mixed_email_file": ToolScenarioSpec(
        scenario_id="mixed_email_file",
        family="mixed",
        setup=_setup_mixed_email_file,
        build_prompt=lambda sandbox: (
            "Use only the email tool's metadata lookup to check how many messages are in the Inbox "
            "from the last 24 hours. Do not read full bodies and do not modify Mail. Then write a "
            "plain-text summary of just the subjects and senders (no bodies) to a new file at "
            f"{sandbox.values['output_dir'] / f'summary-{sandbox.marker}.txt'} using the shell tool."
        ),
        required_groups=(
            (("email_service", "get_email_metadata"),),
            (("shell_service", "execute_command"),),
        ),
    ),
    "mixed_file_shell": ToolScenarioSpec(
        scenario_id="mixed_file_shell",
        family="mixed",
        setup=_setup_number_fixture,
        build_prompt=lambda sandbox: (
            f"Read the number in {sandbox.values['number_fixture']}, double it, and write the doubled "
            f"number to {sandbox.tmp_dir / f'doubled-{sandbox.marker}.txt'} using the shell tool."
        ),
        required_services=("file_service", "shell_service"),
    ),
    "mixed_browser_vision": ToolScenarioSpec(
        scenario_id="mixed_browser_vision",
        family="mixed",
        setup=_setup_browser_fixture,
        build_prompt=lambda sandbox: (
            f"Navigate the browser to file://{sandbox.values['html_path']}, capture or analyze a "
            f"screenshot of the page, and tell me the page title and dominant visual color."
        ),
        required_groups=(
            (("direct_tool", "browser_interact"),),
            (("direct_tool", "analyze_with_vision"),),
        ),
    ),
    "mixed_automation_activity": ToolScenarioSpec(
        scenario_id="mixed_automation_activity",
        family="mixed",
        build_prompt=lambda _sandbox: (
            "Use AppleScript to get the name of the frontmost application right now, then use your "
            "activity history tool to report what app I was using most in the last hour."
        ),
        required_groups=(
            (
                ("applescript_service", "execute_applescript"),
                ("applescript_service", "generate_and_execute_applescript"),
            ),
            (("direct_tool", "query_activities"),),
        ),
    ),
    "mixed_recall_schedule": ToolScenarioSpec(
        scenario_id="mixed_recall_schedule",
        family="mixed",
        build_prompt=lambda sandbox: (
            "Recall what you already know from earlier in this thread, then schedule a one-time "
            f"reminder agent task for January 1, 2099 that just says recall-schedule-{sandbox.marker}. "
            "Do not run it now."
        ),
        required_groups=(
            (("direct_tool", "recall_agent_tasks"),),
            (("direct_tool", "create_scheduled_agent_task_from_prompt"),),
        ),
        cleanup=_cleanup_scheduled_tasks,
    ),
    "mixed_memory_external": ToolScenarioSpec(
        scenario_id="mixed_memory_external",
        family="mixed",
        build_prompt=lambda sandbox: (
            f"Search your memory for anything you remember about my preferences, then verify or "
            f"augment that with a live web search about Tokyo time marker {sandbox.marker}."
        ),
        required_groups=(
            (("direct_tool", "memory_search"), ("direct_tool", "memory_read")),
            (("direct_tool", "web_search"),),
        ),
    ),
}

FAMILY_TO_TOOL_SCENARIO_ID = {
    spec.family: spec.scenario_id
    for spec in TOOL_SCENARIO_SPECS.values()
    if spec.family != "mixed"
}
