"""The fixed prompt set for the routing accuracy check.

Each case is one short prompt plus a ``RoutingExpectation`` built from the steers in the agent system prompt and the tool family catalog.
Cases marked ``live`` touch the owner's real accounts, local Basil data, or the visible desktop, so they only run when the caller passes ``--allow-live-read-only``.
Every prompt is read-only or answerable without side effects, and the runner stops each task at its first approval card and denies it, so a wrong route cannot run a command or script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .route_tokens import RoutingExpectation

FIXTURE_DIR_TOKEN = "{dir}"


def alt(*patterns: str) -> frozenset[str]:
    """One alternative: every pattern must match some token in the routing window."""
    return frozenset(patterns)


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    category: str
    prompt: str
    expectation: RoutingExpectation
    steer: str = ""
    live: bool = False
    live_reason: str = ""
    needs_fixture: bool = False
    attach_fixture: bool = False

    def render_prompt(self, fixture_dir: Optional[str]) -> str:
        return self.prompt.replace(FIXTURE_DIR_TOKEN, fixture_dir or "")


_FILE_PREFERRED = (alt("load:file"), alt("svc:file_service.*"))
_FILE_ACCEPTABLE = (alt("svc:shell_service.execute_command"),)
_NO_GUI_SCRIPT = ("svc:applescript_service.*",)


def build_cases(gmail_basil_connection_id: Optional[str] = None) -> tuple[RoutingCase, ...]:
    """Every routing case. A Gmail connection id, when given, makes the Gmail case require that exact connection."""
    gmail_preferred = (alt(f"ext:call_tool@{gmail_basil_connection_id}"),) if gmail_basil_connection_id else (alt("ext:call_tool"),)
    return (
        RoutingCase(
            "file_list_folder", "file",
            f"List the files in {FIXTURE_DIR_TOKEN} and tell me which file is the largest.",
            RoutingExpectation(preferred=_FILE_PREFERRED, acceptable=_FILE_ACCEPTABLE, forbidden=_NO_GUI_SCRIPT),
            steer="For file operations, prefer file_service tools", needs_fixture=True,
        ),
        RoutingCase(
            "file_read_text", "file",
            f"Read {FIXTURE_DIR_TOKEN}/notes.txt and tell me the project's launch codeword.",
            RoutingExpectation(preferred=_FILE_PREFERRED, acceptable=_FILE_ACCEPTABLE, forbidden=_NO_GUI_SCRIPT),
            steer="For file operations, prefer file_service tools", needs_fixture=True,
        ),
        RoutingCase(
            "file_write_text", "file",
            f"Create a file named summary.txt in {FIXTURE_DIR_TOKEN} that contains the single word hello.",
            RoutingExpectation(preferred=_FILE_PREFERRED, acceptable=_FILE_ACCEPTABLE, forbidden=_NO_GUI_SCRIPT),
            steer="Known plain-text creation prefers file_service_write_text_file", needs_fixture=True,
        ),
        RoutingCase(
            "file_attached_folder", "file",
            "What is in the attached folder? Name each file.",
            RoutingExpectation(preferred=_FILE_PREFERRED, acceptable=_FILE_ACCEPTABLE, forbidden=_NO_GUI_SCRIPT),
            steer="Attached folders are file work", needs_fixture=True, attach_fixture=True,
        ),
        RoutingCase(
            "shell_cli_command", "shell",
            f"Using the command line, count the lines in {FIXTURE_DIR_TOKEN}/notes.txt with wc.",
            RoutingExpectation(preferred=(alt("svc:shell_service.execute_command"),), forbidden=("load:shell", *_NO_GUI_SCRIPT)),
            steer="CLI tasks prefer shell_service; do not reload an available family", needs_fixture=True,
        ),
        RoutingCase(
            "shell_no_reload", "shell",
            "Run sw_vers and tell me the macOS version it reports.",
            RoutingExpectation(preferred=(alt("svc:shell_service.execute_command"),), forbidden=("load:shell", "load:automation")),
            steer="Do not call load_tool_family for an already-available family",
        ),
        RoutingCase(
            "automation_frontmost_app", "automation",
            "Which application is frontmost on my Mac right now? Use AppleScript to find out.",
            RoutingExpectation(preferred=(alt("svc:applescript_service.*"),), forbidden=("load:automation", "svc:shell_service.*")),
            steer="GUI interactions use AppleScript, never shell",
        ),
        RoutingCase(
            "external_open_web", "external",
            "What is the latest stable release of Python? Check the web rather than answering from memory.",
            RoutingExpectation(preferred=(alt("load:external"), alt("tool:web_search")), acceptable=(alt("load:browser"),), forbidden=_NO_GUI_SCRIPT),
            steer="Current open-web facts are the external family (web_search)",
        ),
        RoutingCase(
            "provider_delegation", "provider",
            f"Use a registered coding-agent provider to add a README file to the project folder {FIXTURE_DIR_TOKEN}. Only pick a provider and propose a target; do not start any work yet.",
            RoutingExpectation(
                preferred=(alt("load:provider"), alt("tool:provider_catalog")),
                forbidden=("svc:file_service.write*", "svc:file_service.edit*", "tool:delegated_agent", *_NO_GUI_SCRIPT),
            ),
            steer="Coding-agent delegation loads the provider family", needs_fixture=True,
        ),
        RoutingCase(
            "none_arithmetic", "none",
            "What is 17 times 23? Answer with just the number.",
            RoutingExpectation(expect_no_tools=True),
            steer="Questions the model can answer directly use no tools",
        ),
        RoutingCase(
            "none_explain", "none",
            "In two sentences, explain the difference between a Python list and a tuple.",
            RoutingExpectation(expect_no_tools=True),
            steer="Questions the model can answer directly use no tools",
        ),
        RoutingCase(
            "multi_family_one_load", "multi",
            f"Read {FIXTURE_DIR_TOKEN}/notes.txt, then check the web for the latest stable Python release, and tell me the codeword and the version.",
            RoutingExpectation(
                preferred=(alt("load:file", "load:external"),),
                acceptable=(alt("svc:shell_service.execute_command", "load:external"), alt("svc:file_service.*", "load:external")),
                forbidden=_NO_GUI_SCRIPT,
            ),
            steer="Load every family likely needed in one call", needs_fixture=True,
        ),
        RoutingCase(
            "external_list_connections", "external",
            "Which external services do I have connected to Basil? Just list them; do not call any of them.",
            RoutingExpectation(
                preferred=(alt("ext:list_servers"),), forbidden=("svc:email_service.*", "load:browser", *_NO_GUI_SCRIPT), answerable_from_context=True,
            ),
            steer="The connected-service inventory is already in the tool family catalog, so listing from it or calling list_servers are both correct",
            live=True, live_reason="reads the owner's connected-service inventory (names only)",
        ),
        RoutingCase(
            "external_gmail_inbox", "email",
            "What is the subject line of the most recent email in my Basil inbox? This is a read-only check: do not send, draft, label, archive, or change anything.",
            RoutingExpectation(preferred=gmail_preferred, forbidden=("svc:email_service.*", "load:email", *_NO_GUI_SCRIPT)),
            steer="A connected Gmail mailbox is used through the connector first",
            live=True, live_reason="reads the owner's connected Gmail account (read-only search)",
        ),
        RoutingCase(
            "email_apple_mail", "email",
            "Using the Mail app on this Mac, how many messages are in my inbox? This is a read-only check.",
            RoutingExpectation(
                preferred=(alt("load:email"), alt("svc:email_service.*")),
                acceptable=(alt("svc:applescript_service.*"),),
                forbidden=("ext:call_tool", "ext:call_tool@*"),
            ),
            steer="An explicitly named desktop mail client uses email_service, not a connector",
            live=True, live_reason="reads the owner's Mail app mailbox through the local email service",
        ),
        RoutingCase(
            "history_yesterday", "history",
            "What did I work on yesterday, according to Basil's history?",
            RoutingExpectation(
                preferred=(alt("load:retrieval"), alt("tool:retrieve_basil_history")),
                acceptable=(alt("tool:query_unified_history"),),
                forbidden=("tool:query_activities",),
            ),
            steer="Historical facts use retrieve_basil_history",
            live=True, live_reason="reads the owner's local Basil history (and sends results to a cloud model when one is selected)",
        ),
        RoutingCase(
            "history_foreground_app", "history",
            "Which app was in the foreground at 9:00 this morning, according to Basil's screen capture history?",
            RoutingExpectation(
                preferred=(alt("load:activity"), alt("tool:query_activities")),
                acceptable=(alt("load:retrieval"), alt("tool:retrieve_basil_history")),
            ),
            steer="query_activities is for raw screen and app evidence",
            live=True, live_reason="reads the owner's local screen-capture history",
        ),
        RoutingCase(
            "calendar_not_history", "history",
            "What meetings do I have on my calendar today?",
            RoutingExpectation(
                preferred=(alt("svc:applescript_service.*"), alt("load:external")),
                acceptable=(alt("ext:*"),),
                forbidden=("tool:query_activities", "tool:retrieve_basil_history", "load:activity", "load:retrieval"),
            ),
            steer="Calendar events belong to their services, not query_activities",
            live=True, live_reason="reads the owner's calendar",
        ),
        RoutingCase(
            "todos_list", "todos",
            "What is on my Basil to-do list right now? Just read it.",
            RoutingExpectation(preferred=(alt("load:todos"), alt("tool:list_todos")), forbidden=_NO_GUI_SCRIPT),
            steer="Basil To-Dos use the todos family",
            live=True, live_reason="reads the owner's Basil to-do list",
        ),
        RoutingCase(
            "schedule_review", "schedule",
            "Show me the scheduled agent tasks Basil has set up. Do not change any of them.",
            RoutingExpectation(preferred=(alt("load:schedule"), alt("tool:manage_scheduled_agent_tasks")), forbidden=_NO_GUI_SCRIPT),
            steer="Reviewing Basil schedules uses the schedule family",
            live=True, live_reason="reads the owner's scheduled agent tasks",
        ),
        RoutingCase(
            "app_settings_read", "settings",
            "What text size is Basil using right now? Just read the setting; do not change it.",
            RoutingExpectation(preferred=(alt("load:app_settings"), alt("tool:app_settings")), forbidden=_NO_GUI_SCRIPT),
            steer="Basil's own settings use the app_settings family",
            live=True, live_reason="reads Basil's own settings",
        ),
        RoutingCase(
            "memory_read", "memory",
            "What does Basil's working memory say about me? Just read it.",
            RoutingExpectation(preferred=(alt("load:memory"), alt("tool:memory_*"), alt("svc:memory*")), forbidden=_NO_GUI_SCRIPT),
            steer="Working memory uses the memory family",
            live=True, live_reason="reads the owner's Basil working memory",
        ),
        RoutingCase(
            "browser_page", "browser",
            "Open example.com in the browser and tell me the main heading on the page.",
            RoutingExpectation(
                preferred=(alt("load:browser"),),
                acceptable=(alt("svc:shell_service.execute_command"), alt("load:external")),
                forbidden=_NO_GUI_SCRIPT,
            ),
            steer="Website and tab work loads the browser family",
            live=True, live_reason="opens a browser automation window on the visible desktop",
        ),
    )
