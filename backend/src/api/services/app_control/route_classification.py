"""Says, for every mutating HTTP route, how an agent inside Basil relates to it.

The contract test walks the real route table, so a new mutating route that matches no rule fails CI until someone decides. Rules are checked in order and the first match wins. A route is "mutating" when its method is POST, PUT, PATCH or DELETE.

Dispositions:
- registry: writes preference fields, which the app_settings tool governs field by field through classification.py.
- existing_tool: an agent tool already does this. The rule names the tool, and the test checks the tool exists.
- human_only: credentials, sign-ins, approvals and permission decisions. An agent never does these, whatever the tier of a future tool.
- runtime_internal: an input surface or plumbing that the app's own clients and pipeline call. It is not a control an agent needs.
- deferred: a control an agent should eventually have, not built yet. It names the roadmap domain that owns it. DEFERRED_BASELINE can only shrink.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

REGISTRY = "registry"
EXISTING_TOOL = "existing_tool"
HUMAN_ONLY = "human_only"
RUNTIME_INTERNAL = "runtime_internal"
DEFERRED = "deferred"

DISPOSITIONS = frozenset({REGISTRY, EXISTING_TOOL, HUMAN_ONLY, RUNTIME_INTERNAL, DEFERRED})

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class RouteRule:
    """One classification rule. The pattern must match the whole path. An empty methods set means any mutating method."""

    pattern: str
    disposition: str
    reason: str
    methods: FrozenSet[str] = frozenset()
    domain: Optional[str] = None
    tool: Optional[str] = None

    def matches(self, method: str, path: str) -> bool:
        if self.methods and method not in self.methods:
            return False
        return re.fullmatch(self.pattern, path) is not None


def _rule(pattern: str, disposition: str, reason: str, *, methods: Tuple[str, ...] = (), domain: Optional[str] = None, tool: Optional[str] = None) -> RouteRule:
    return RouteRule(pattern=pattern, disposition=disposition, reason=reason, methods=frozenset(methods), domain=domain, tool=tool)


ROUTE_RULES: Tuple[RouteRule, ...] = (
    # Approval and permission decisions belong to the user.
    _rule(r"/app-control/settings-change/approve", HUMAN_ONLY, "Resolves an agent's own settings-change request; the host credential keeps the agent from approving itself."),
    _rule(r"/app-control/native-command/result", RUNTIME_INTERNAL, "The Mac app reports the outcome of an allowed native command; the host credential keeps an agent from reporting its own success."),
    _rule(r"/api/v1/agent-tasks/approval/.*", HUMAN_ONLY, "Command approval decisions and the approval mode."),
    _rule(r"/api/v1/agent-tasks/whitelist(/.*)?", HUMAN_ONLY, "The remembered-approval list is the permission system."),
    _rule(r"/api/v1/agent-tasks/command-input/.*", HUMAN_ONLY, "Answers a command's request for input on the user's behalf."),
    _rule(r"/api/v1/agent-tasks/auto-approve/\{root_task_id\}", HUMAN_ONLY, "Turns on approving every command of one task without asking; only the host credential and the user's risk confirmation can change it, so an agent cannot approve itself."),
    _rule(r"/api/v1/agent-tasks/\{agent_task_id\}/execution-approvals/recover", HUMAN_ONLY, "Recovers a pending approval."),
    _rule(r"/api/v1/agent-tasks/\{agent_task_id\}/provider-interactions/.*", HUMAN_ONLY, "Answers a delegated provider's permission and input prompts."),
    _rule(r"/api/v1/agent-tasks/managed-file-history/restore", HUMAN_ONLY, "Restores earlier file contents; no approval path exists for an agent yet."),
    _rule(r"/settings/browser-automation/sensitive-value/approve", HUMAN_ONLY, "Approves release of a sensitive value to a web page."),
    _rule(r"/settings/browser-automation/sensitive-domains/\{domain\}", HUMAN_ONLY, "Edits the list of domains that need sensitive-value approval."),
    _rule(r"/settings/browser-automation/automation-browser-profile/clear", HUMAN_ONLY, "Erases the automation browser's saved sign-ins."),
    _rule(r"/personalization/contacts/mac/request-access", HUMAN_ONLY, "Triggers an operating-system permission prompt."),
    _rule(r"/memory/promotions/.*|/memory/skill-candidates/.*|/memory/reconciliation/.*", HUMAN_ONLY, "The user's decision on what enters Basil's memory and skills."),
    _rule(r"/memory/context-import/.*", HUMAN_ONLY, "The user's own decision to add personal text to Basil's memory, and to undo it."),
    _rule(r"/meetings/cloud-transcription/keys/\{provider\}", HUMAN_ONLY, "Stores or removes a cloud transcription key."),
    _rule(r"/setup-assistant/.*", HUMAN_ONLY, "The Setup Assistant is its own user-approved flow; its allowlists come from setup_assistant_policy.py."),
    # Credentials, sign-ins and the permission system.
    _rule(r"/settings/auth(/token)?", HUMAN_ONLY, "Basil's own authentication."),
    _rule(r"/settings/api_models/api_keys(/test|/\{provider\})?", HUMAN_ONLY, "API keys."),
    _rule(r"/settings/connections/(github/.*|slack/.*|start_oauth|manual_token|gmail_transport)", HUMAN_ONLY, "Sign-ins and tokens for connections."),
    _rule(r"/settings/connections/local_server(/.*)?", HUMAN_ONLY, "Adding a local server stores a command that Basil then runs on this Mac, and starting or reconfiguring its background program runs it, so only a person can approve it."),
    _rule(r"/settings/provider-profiles(/\{provider_profile_id\})?", HUMAN_ONLY, "Creating or rewriting a provider profile sets its command and credentials.", domain="connections_and_profiles"),
    _rule(r"/settings/provider-profiles/\{provider_profile_id\}/workspace-grants(/.*)?", HUMAN_ONLY, "Grants a provider access to a workspace folder."),
    _rule(r"/settings/reset", HUMAN_ONLY, "Resets every setting."),
    _rule(r"/hotkeys/bindings/\{operation\}", HUMAN_ONLY, "Keyboard bindings are human-only in the registry."),
    # Settings written through the preference registry.
    _rule(
        r"/settings/(activity-capture|agent-task|ambient-suggestions|appearance|assistant-session|behavior|browser-automation|conversation-widget|general|hotkeys|meeting-detection|memory-intelligence|models|transcription|ui|voice-listener/settings|zettel)",
        REGISTRY,
        "These routes save preference sections; the app_settings tool reaches the same fields through the schema-derived registry.",
        methods=("PUT",),
    ),
    # Existing agent tools.
    _rule(r"/api/v1/todos/items", EXISTING_TOOL, "Creates To-Dos.", methods=("POST",), tool="create_todos"),
    _rule(r"/api/v1/todos/items/\{todo_id\}", EXISTING_TOOL, "Edits a To-Do.", methods=("PATCH",), tool="update_todo"),
    _rule(r"/api/v1/todos/items/\{todo_id\}/(accept|cancel|complete|dismiss|reopen|status)", EXISTING_TOOL, "Changes a To-Do's status.", tool="set_todo_status"),
    _rule(r"/api/v1/todos/items/\{todo_id\}/notes", EXISTING_TOOL, "Appends to a To-Do's notes.", tool="append_todo_note"),
    _rule(r"/api/v1/todos/items/\{todo_id\}/references", EXISTING_TOOL, "Attaches a reference.", methods=("POST",), tool="attach_todo_reference"),
    _rule(r"/api/v1/todos/items/\{todo_id\}/workers", EXISTING_TOOL, "Delegates To-Do work.", tool="delegate_todo_work"),
    _rule(r"/api/v1/agent-tasks/\{agent_task_id\}/checklist/.*", EXISTING_TOOL, "The task checklist.", tool="checklist"),
    _rule(r"/api/v1/agent-task-schedules", EXISTING_TOOL, "Creates a scheduled agent task.", methods=("POST",), tool="create_scheduled_agent_task_from_prompt"),
    _rule(r"/api/v1/agent-task-schedules/interpret", EXISTING_TOOL, "Interprets a schedule request as part of creating one.", tool="create_scheduled_agent_task_from_prompt"),
    # Deferred domains an agent should eventually reach.
    _rule(r"/api/v1/agent-task-schedules/\{scheduled_agent_task_id\}(/run-now)?", DEFERRED, "Edit, delete and run-now for a schedule. Pausing is covered by manage_scheduled_agent_tasks; the rest needs an approval path.", domain="agent_and_schedule_audit"),
    _rule(r"/api/v1/agent-tasks/\{agent_task_id\}(/archive|/unarchive|/retry|/feedback|/save-as-skill|/clarifications)?", DEFERRED, "Archiving, deleting and retrying agent tasks.", domain="agent_and_schedule_audit"),
    _rule(r"/api/v1/agent-tasks/sessions/\{agent_task_id\}/.*", DEFERRED, "Controlling another running agent task.", domain="agent_and_schedule_audit"),
    _rule(r"/api/v1/agent-tasks/follow-ups/\{root_task_id\}", DEFERRED, "Cancels a task's follow-ups.", domain="agent_and_schedule_audit"),
    _rule(r"/api/v1/agent-tasks/\{agent_task_id\}/artifacts/.*", DEFERRED, "Local previews of an agent task's files.", domain="agent_and_schedule_audit"),
    _rule(r"/api/v1/todos/(items/\{todo_id\}|items/\{todo_id\}/references/\{reference_id\}|meeting-proposals/promote)", DEFERRED, "Deleting a To-Do or a reference, and promoting a meeting proposal.", domain="memory_todos_board"),
    _rule(r"/api/v1/basil-board/home/inquiries/\{inquiry_id\}/reroute", DEFERRED, "Rerouting a board inquiry.", domain="memory_todos_board"),
    _rule(r"/memory/(run-now|skills/\{slug\}|\{file_name\})", DEFERRED, "Memory files, skills and the memory run.", domain="memory_todos_board"),
    _rule(r"/settings/zettel/(carding|narrative)/.*", DEFERRED, "Summary and narrative runs.", domain="memory_todos_board"),
    _rule(r"/assistant-outputs/.*", DEFERRED, "Deleting, resuming and saving dictation history.", domain="memory_todos_board"),
    _rule(r"/user/.*", DEFERRED, "The user's profile, writing samples and style analysis.", domain="personalization"),
    _rule(r"/settings/connections/\{connection_id\}(/metadata|/policy|/status)?", DEFERRED, "Editing and removing connections.", domain="connections_and_profiles"),
    _rule(r"/settings/provider-profiles/\{provider_profile_id\}/(enable|disable)", DEFERRED, "Turning a provider profile on or off.", domain="connections_and_profiles"),
    _rule(r"/settings/api_models/.*", DEFERRED, "Which cloud models and transcription providers are on.", domain="models_and_downloads"),
    _rule(r"/settings/transcription/model/swap", DEFERRED, "Swapping the transcription model.", domain="models_and_downloads"),
    _rule(r"/models/.*", DEFERRED, "Downloading, adding and removing models.", domain="models_and_downloads"),
    _rule(r"/onboarding/start-starter-downloads", DEFERRED, "Starting the starter model downloads.", domain="models_and_downloads"),
    _rule(r"/onboarding/use-smaller-reasoning-model", RUNTIME_INTERNAL, "The Setup Assistant's recovery action after a local model fails to run; the user chooses it from the failure banner."),
    _rule(r"/diagnostics/problem-report", RUNTIME_INTERNAL, "The Mac app's Report a problem flow builds a redacted diagnostics bundle for the user to attach to an issue."),
    _rule(r"/settings/appearance/themes(/\{theme_id\})?", DEFERRED, "Saved themes.", domain="appearance_themes"),
    _rule(r"/meetings/prepare-retranscription-model", DEFERRED, "Preparing a retranscription model.", domain="models_and_downloads"),
    _rule(r"/meetings/.*", DEFERRED, "Starting, stopping, editing and analyzing meetings, and the meeting companion.", domain="meeting_automation"),
    _rule(r"/meeting-detection/(start|stop|toggle|calendar-event/ignore)", DEFERRED, "Starting and stopping meeting detection.", domain="capture_and_detection"),
    _rule(r"/activity-capture/.*", DEFERRED, "Starting, stopping and processing screen capture.", domain="capture_and_detection"),
    _rule(r"/ambient-suggestions/.*", DEFERRED, "Ambient suggestions runtime.", domain="capture_and_detection"),
    _rule(r"/api/v1/capture-management/.*", DEFERRED, "Clearing captured history and its retention.", domain="capture_and_detection"),
    _rule(r"/api/v1/voice-listener/(start|stop|stop-agent-task-capture)", DEFERRED, "Starting and stopping the voice listener.", domain="capture_and_detection"),
    # Input surfaces and plumbing that the app's own clients drive.
    _rule(r"/api/v1/voice-listener/wake-word-callback", RUNTIME_INTERNAL, "The wake-word detector reports a hit."),
    _rule(r"/api/v1/agent-tasks/(process|process-audio)|/api/v1/agent-tasks/\{root_task_id\}/refine-audio", RUNTIME_INTERNAL, "The ways the user hands the agent its work."),
    _rule(r"/api/v1/basil-board/(conversation|home)/(transcribe|turn)", RUNTIME_INTERNAL, "Board chat input."),
    _rule(r"/api/v1/startup/status", RUNTIME_INTERNAL, "Startup progress reports."),
    _rule(r"/assistant-sessions(/.*)?", RUNTIME_INTERNAL, "Dictation sessions driven by hotkeys and the overlay."),
    _rule(r"/conversation(/.*)?", RUNTIME_INTERNAL, "The Conversation window's own chat."),
    _rule(r"/hotkeys/(capture|conversation|transcribe|transcribe/stop)", RUNTIME_INTERNAL, "Hotkey triggers."),
    _rule(r"/capture(/.*)?|/ocr/.*|/image/.*|/similar-activities|/cleanup|/audio-activity/probe-response|/meeting-detection/calendar-probe-response", RUNTIME_INTERNAL, "Capture, OCR and analysis plumbing."),
    _rule(r"/test/.*|/settings/dev/log", RUNTIME_INTERNAL, "Developer diagnostics."),
)

# The deferred routes that exist today, as (domain, count). The contract test fails if any domain grows, so a new route cannot be deferred silently; shrink a number when a domain is built.
DEFERRED_BASELINE: Dict[str, int] = {
    "agent_and_schedule_audit": 18,
    "appearance_themes": 2,
    "capture_and_detection": 24,
    "connections_and_profiles": 6,
    "meeting_automation": 30,
    "memory_todos_board": 15,
    "models_and_downloads": 23,
    "personalization": 8,
}


def classify_route(method: str, path: str) -> Optional[RouteRule]:
    """Return the first rule matching a mutating method and path, or None."""
    for rule in ROUTE_RULES:
        if rule.matches(method.upper(), path):
            return rule
    return None
