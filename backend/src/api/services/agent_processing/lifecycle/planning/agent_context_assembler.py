"""Shared agent prompt context assembly for retries and follow-ups.

The database often stores far more detail than the agent should receive
verbatim.  This module turns durable agent-task history into compact, redacted,
priority-ordered prompt sections that can be shared by follow-ups, retries,
and reference-material workflows.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

# Tool-enhanced workflow envelopes record a generic
# "Enhanced workflow processed: <original prompt>" boilerplate in
# data.message. That string is just the prompt echoed back and contains
# no narrative content, so chain follow-ups that surface it look as if
# the prior task produced nothing. The richer narrative the previous
# agent actually produced lives in
# data.workflow_details.results[*].agent_output. We treat the boilerplate
# as empty whenever a richer candidate is available.
_BOILERPLATE_WORKFLOW_PROMPT_ECHO_RE = re.compile(
    r"^\s*Enhanced workflow processed:\s*",
)

# Tool-enhanced workflow `agent_output` values interleave internal telemetry
# lines ahead of the agent's actual prose, e.g.:
#   STEP_START: Using recall_agent_tasks tool
#   STEP_COMPLETE: recall_agent_tasks completed successfully
#   <actual answer...>
# STEP_START always has this exact "Using <tool> tool" shape (safe to always
# strip); STEP_COMPLETE's suffix varies ("X completed successfully", "X
# executed", "Successfully created file ...") so it is only stripped when it
# directly follows a STEP_START line -- a lone STEP_COMPLETE-prefixed line
# that is itself real prose (seen in existing test fixtures) is left alone.
_STEP_START_LINE_RE = re.compile(r"^STEP_START: Using .+ tool$")
_STEP_COMPLETE_PREFIX_RE = re.compile(r"^STEP_COMPLETE:")

logger = logging.getLogger(__name__)

CONVERSATION_THREAD_SEEDED_KEY = "conversation_thread_seeded"


SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "cookie",
    "keychain",
    "password",
    "refresh_token",
    "secret",
    "token",
)


@dataclass
class ContextSection:
    """One rendered context section with a priority for budget trimming."""

    name: str
    body: str
    priority: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def marker(self) -> str:
        return self.name.upper().replace(" ", "_")

    def render(self) -> str:
        return f"===== {self.marker} =====\n{self.body.strip()}\n===== END {self.marker} ====="


@dataclass
class AssembledAgentContext:
    """Rendered user input plus structured metadata for logs/tests."""

    user_input: str
    sections: List[ContextSection]
    omitted_sections: List[str]
    budget_chars: int


class AgentContextAssembler:
    """Build compact, redacted context blocks for agent execution."""

    DEFAULT_INPUT_BUDGET_CHARS = 48_000
    MAX_INPUT_BUDGET_CHARS = 160_000
    OUTPUT_RESERVE_TOKENS = 8_000
    CHARS_PER_TOKEN_ESTIMATE = 4
    # Longest real follow-up chain observed in the live DB is 7 turns; this
    # cap gives generous headroom while keeping a hard bound for pathological
    # chains. Turns beyond the cap are pointed at recall_agent_tasks(scope=
    # 'detail') instead of silently vanishing.
    MAX_INLINE_CHAIN_TURNS = 12
    MAX_CHAIN_TURN_SUMMARY_CHARS = 900
    MAX_TODO_WORKER_SOURCE_TASKS = 10
    MAX_TODO_WORKER_EXCERPT_CHARS = 500

    def assemble(
        self,
        *,
        current_request: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AssembledAgentContext:
        context = context or {}
        sections = self._build_sections(context)
        budget_chars = self._derive_budget_chars(context)

        selected: List[ContextSection] = []
        omitted: List[str] = []
        base_request = f"Current request: {current_request}"
        used_chars = len(base_request)

        for section in sorted(sections, key=lambda item: item.priority):
            rendered = section.render()
            if used_chars + len(rendered) + 2 <= budget_chars:
                selected.append(section)
                used_chars += len(rendered) + 2
                continue

            compact = self._compact_section_to_fit(
                section,
                available_chars=max(0, budget_chars - used_chars - 2),
            )
            if compact:
                selected.append(compact)
                used_chars += len(compact.render()) + 2
            else:
                omitted.append(section.name)

        rendered_sections = "\n\n".join(section.render() for section in selected)
        user_input = f"{rendered_sections}\n\n{base_request}" if rendered_sections else current_request

        logger.info(
            "🧩 CONTEXT ASSEMBLED budget_chars=%s sections=%s omitted=%s",
            budget_chars,
            [f"{section.name}({len(section.render())} chars)" for section in selected],
            omitted or "none",
        )

        return AssembledAgentContext(
            user_input=user_input,
            sections=selected,
            omitted_sections=omitted,
            budget_chars=budget_chars,
        )

    def _build_sections(self, context: Dict[str, Any]) -> List[ContextSection]:
        sections: List[ContextSection] = []

        reference_paths = context.get("reference_paths") or []
        if reference_paths:
            body = (
                "The user provided these files/folders as explicit reference material.\n"
                "Resolve phrases like 'these files', 'this folder', 'these documents', 'those files', "
                "'move them', or 'organize that folder' to these paths.\n"
                "For file operations, these explicit paths are authoritative and outrank the frontmost "
                "window, current Terminal tab, IDE project, or screen title.\n"
                "Do not use current-document detection for these paths unless the user explicitly asks "
                "for the file currently open/frontmost on screen:\n"
                + "\n".join(f"- {path}" for path in reference_paths)
            )
            sections.append(ContextSection("REFERENCE MATERIALS", body, priority=10))

        retry_context = context.get("retry_context")
        if isinstance(retry_context, dict) and retry_context:
            sections.append(ContextSection(
                "RETRY CONTEXT",
                self._format_retry_context(retry_context),
                priority=15,
            ))

        todo_worker_context = context.get("todo_worker_context")
        if (
            isinstance(todo_worker_context, dict)
            and self._todo_worker_source_ids(self._redact_value(todo_worker_context))
        ):
            sections.append(ContextSection(
                "TODO WORKER HANDOFF",
                self._format_todo_worker_handoff(todo_worker_context),
                priority=8,
            ))

        chain_context = context.get("chain_context")
        if isinstance(chain_context, dict) and chain_context:
            if not context.get(CONVERSATION_THREAD_SEEDED_KEY):
                sections.append(ContextSection(
                    "FOLLOW UP CONTEXT",
                    self._format_chain_context(chain_context),
                    priority=30,
                ))
            pinned_body = self._format_pinned_context(chain_context)
            if pinned_body:
                sections.append(ContextSection(
                    "PINNED CONTEXT",
                    pinned_body,
                    priority=5,
                ))

        work_ledger_handoff = context.get("work_ledger_handoff")
        if isinstance(work_ledger_handoff, str) and work_ledger_handoff.strip():
            sections.append(ContextSection(
                "WORK LEDGER",
                work_ledger_handoff.strip(),
                priority=25,
            ))

        screen_text = context.get("screen_text")
        if isinstance(screen_text, str) and screen_text.strip():
            app = context.get("active_app") or "Unknown app"
            screen_summary = self._truncate(screen_text.strip(), 2_400)
            sections.append(ContextSection(
                "SCREEN CONTEXT",
                f"Active app: {app}\nVisible screen text preview:\n{screen_summary}",
                priority=70,
            ))

        return sections

    def _format_retry_context(self, retry_context: Dict[str, Any]) -> str:
        safe_context = self._redact_value(retry_context)
        lines = [
            "This is a retry of a previous attempt. Use these facts to avoid repeating the same failed assumption.",
        ]

        for key in ("previous_status", "failure_summary", "partial_result", "self_assessment"):
            value = safe_context.get(key)
            if value:
                lines.append(f"{self._title_label(key)}: {self._truncate(str(value), 1_200)}")

        blockers = safe_context.get("blockers")
        if isinstance(blockers, list) and blockers:
            lines.append("Known blockers:")
            for blocker in blockers[:5]:
                lines.append(f"- {self._truncate(self._stringify(blocker), 900)}")

        tool_attempts = safe_context.get("tool_attempts")
        if isinstance(tool_attempts, list) and tool_attempts:
            lines.append("Previous tool attempts:")
            for attempt in tool_attempts[:8]:
                lines.append(f"- {self._truncate(self._stringify(attempt), 900)}")

        files = safe_context.get("files")
        if isinstance(files, list) and files:
            lines.append("Files/artifacts from the previous attempt:")
            for file_info in files[:10]:
                lines.append(f"- {self._truncate(self._stringify(file_info), 500)}")

        return "\n".join(lines)

    def _format_todo_worker_handoff(self, todo_worker_context: Dict[str, Any]) -> str:
        """Render bounded source handoff for a standalone To-Do worker."""
        safe_context = self._redact_value(todo_worker_context)
        source_ids = self._todo_worker_source_ids(safe_context)
        excerpts = safe_context.get("source_excerpts")
        lines = [
            "This is a standalone To-Do worker task, not a follow-up chain.",
            "The source Agent Tasks below are provenance for this To-Do. You may call "
            "recall_agent_tasks(scope='detail', task_id='<source id>') directly to retrieve "
            "the complete durable record for any listed source task.",
        ]

        if source_ids:
            lines.append("Source Agent Task ids:")
            for index, source_id in enumerate(source_ids):
                lines.append(f"- {source_id}")
                excerpt = self._todo_worker_excerpt(excerpts, source_id, index)
                if excerpt:
                    lines.append(
                        f"  Excerpt: {self._truncate(excerpt, self.MAX_TODO_WORKER_EXCERPT_CHARS)}"
                    )
        return "\n".join(lines)

    def _todo_worker_source_ids(self, context: Dict[str, Any]) -> List[str]:
        source_ids = context.get("source_agent_task_ids")
        if not isinstance(source_ids, list):
            source_ids = context.get("source_task_ids")
        if not isinstance(source_ids, list):
            source_tasks = context.get("source_agent_tasks")
            if isinstance(source_tasks, list):
                source_ids = [
                    item.get("id") or item.get("agent_task_id")
                    for item in source_tasks
                    if isinstance(item, dict)
                ]
        if not isinstance(source_ids, list):
            return []

        unique_ids: List[str] = []
        for source_id in source_ids:
            rendered = source_id.strip() if isinstance(source_id, str) else ""
            if rendered and rendered not in unique_ids:
                unique_ids.append(rendered)
            if len(unique_ids) >= self.MAX_TODO_WORKER_SOURCE_TASKS:
                break
        return unique_ids

    def _todo_worker_excerpt(self, excerpts: Any, source_id: str, index: int) -> Optional[str]:
        if isinstance(excerpts, dict):
            excerpt = excerpts.get(source_id)
        elif isinstance(excerpts, list) and index < len(excerpts):
            excerpt = excerpts[index]
        else:
            excerpt = None
        if not excerpt:
            return None
        return self._stringify(excerpt) if isinstance(excerpt, (dict, list)) else str(excerpt)

    def _format_chain_context(self, chain_context: Dict[str, Any]) -> str:
        """Render prior chain turns as an actual back-and-forth conversation.

        The previous rendering used a structured mini-report per turn
        ("AgentTask #N: '...' / Status: ... / Result summary: ..."), which
        reads to the model like a third-party account of someone else's work.
        Framing turns as "User: .../You: ..." lets the model treat its own
        past answers as memory instead of hearsay -- the framing change most
        directly aimed at follow-ups feeling like a different agent each turn.
        """
        chain_agentTasks = chain_context.get("chain_agentTasks") or []
        if not chain_agentTasks:
            return "No prior agent-task details were available."

        total_turns = len(chain_agentTasks)
        visible = chain_agentTasks[-self.MAX_INLINE_CHAIN_TURNS:]
        omitted_count = total_turns - len(visible)

        lines = [
            "This is a continuing conversation. The turns below are the actual "
            "exchange so far -- \"You:\" lines are things you already said, not "
            "a report about someone else's work. Resolve references like "
            "'that', 'it', 'the same one', and 'the previous output' from this "
            "history first.",
        ]
        if omitted_count > 0:
            lines.append(
                f"({omitted_count} earlier turn{'s' if omitted_count != 1 else ''} "
                "not shown here -- use recall_agent_tasks(scope='detail') for "
                "the full chain if needed.)"
            )

        for agent_task_record in visible:
            safe_agent_task = self._redact_value(agent_task_record)
            text = str(safe_agent_task.get("text") or "").strip()
            status = safe_agent_task.get("status", "unknown")
            result = safe_agent_task.get("result")

            lines.append(f"\nUser: {self._truncate(text, 600)}")

            if status == "awaiting_user_input":
                checkpoint_data = result.get("checkpoint_data") if isinstance(result, dict) else None
                checkpoint_prompt = checkpoint_data.get("prompt") if isinstance(checkpoint_data, dict) else None
                lines.append(
                    f"You asked: {self._truncate(str(checkpoint_prompt), 600)}"
                    if checkpoint_prompt
                    else "You: (paused, waiting on the user's reply)"
                )
            else:
                summary = self._extract_result_summary(result)
                if summary:
                    lines.append(f"You: {self._truncate(summary, self.MAX_CHAIN_TURN_SUMMARY_CHARS)}")
                elif status == "failed":
                    reason = self._extract_failure_reason(result)
                    lines.append(
                        f"(This attempt failed{': ' + reason if reason else ''}. "
                        "No response was produced for this turn.)"
                    )
                else:
                    lines.append(f"(This attempt did not produce a response; last known status: {status}.)")

            files = self._extract_files(result)
            if files:
                lines.append("Files/artifacts from that turn:")
                for file_info in files[:8]:
                    lines.append(f"- {self._truncate(self._stringify(file_info), 500)}")

            browser_targets = self._extract_browser_automation_targets(result)
            if browser_targets:
                lines.append("Browser automation targets:")
                lines.append(
                    "Attempt to reuse a listed Basil browser target if it is "
                    "still present; otherwise create a new dedicated automation window."
                )
                for target in browser_targets[:3]:
                    lines.append(f"- {self._truncate(self._stringify(target), 700)}")

            blockers = self._extract_blockers(result)
            if blockers:
                lines.append("Relevant blockers:")
                for blocker in blockers[:4]:
                    lines.append(f"- {self._truncate(self._stringify(blocker), 700)}")

            operation = safe_agent_task.get("operation")
            if operation:
                lines.append(f"Operation: {self._truncate(self._stringify(operation), 700)}")

        return "\n".join(lines)

    def _format_pinned_context(self, chain_context: Dict[str, Any]) -> Optional[str]:
        """Compact, never-trimmed summary of the immediately-prior turn.

        FOLLOW UP CONTEXT is a normal trimmable section (see
        trimmable_sections in prompt_context_trimming.py), so a reactive
        token-limit trim mid-loop can remove it entirely, dropping the
        prior turn's resolved file identity. This section is deliberately
        NOT listed there, so the previous turn's files/paths survive even
        when the loop later has to shed context to fit a token limit.
        Kept intentionally tiny so it can never itself be the cause of the
        overflow it exists to protect against.
        """
        chain_agentTasks = chain_context.get("chain_agentTasks") or []
        if not chain_agentTasks:
            return None

        last_agent_task = self._redact_value(chain_agentTasks[-1])
        result = last_agent_task.get("result")
        files = self._extract_files(result)
        summary = self._extract_result_summary(result)

        if not files and not summary:
            return None

        lines = [
            "Files/paths and outcome from the immediately preceding turn. This "
            "section is never removed for length -- treat it as the authoritative "
            "source for 'that file'/'it'/'the same one' references even if "
            "FOLLOW UP CONTEXT above was shortened.",
        ]
        if summary:
            lines.append(f"Previous result: {self._truncate(summary, 300)}")
        if files:
            lines.append("Previous files/artifacts:")
            for file_info in files[:8]:
                lines.append(f"- {self._truncate(self._stringify(file_info), 300)}")

        return "\n".join(lines)

    def _derive_budget_chars(self, context: Dict[str, Any]) -> int:
        model_metadata = context.get("model_metadata") or {}
        context_window = (
            context.get("context_window")
            or context.get("max_context_length")
            or model_metadata.get("context_window")
            or model_metadata.get("max_context_length")
        )
        try:
            if context_window:
                output_reserve = int(context.get("output_reserve_tokens") or self.OUTPUT_RESERVE_TOKENS)
                input_tokens = max(4_000, int(context_window) - output_reserve)
                derived = input_tokens * self.CHARS_PER_TOKEN_ESTIMATE
                return max(self.DEFAULT_INPUT_BUDGET_CHARS, min(self.MAX_INPUT_BUDGET_CHARS, derived))
        except Exception:
            logger.debug("Could not derive model context budget from %r", context_window)
        return self.DEFAULT_INPUT_BUDGET_CHARS

    def _compact_section_to_fit(self, section: ContextSection, available_chars: int) -> Optional[ContextSection]:
        if available_chars < 500:
            return None
        header_overhead = len(f"===== {section.marker} =====\n\n===== END {section.marker} =====")
        body_budget = max(200, available_chars - header_overhead)
        compact_body = self._truncate(section.body, body_budget)
        return ContextSection(
            name=section.name,
            body=compact_body,
            priority=section.priority,
            metadata={**section.metadata, "compacted": True},
        )

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: Dict[str, Any] = {}
            for key, item in value.items():
                key_str = str(key)
                if self._is_sensitive_key(key_str):
                    redacted[key_str] = "[redacted]"
                else:
                    redacted[key_str] = self._redact_value(item)
            return redacted
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        return value

    def _is_sensitive_key(self, key: str) -> bool:
        key_lower = key.lower()
        return any(part in key_lower for part in SENSITIVE_KEY_PARTS)

    def _extract_result_summary(self, result: Any) -> Optional[str]:
        if not isinstance(result, dict):
            return self._truncate(str(result), 1_000) if result else None

        data = result.get("data")
        data = data if isinstance(data, dict) else None
        finalizer = result.get("finalizer_result")
        finalizer = finalizer if isinstance(finalizer, dict) else None
        final_envelope = data.get("final_envelope") if data else None
        final_envelope = final_envelope if isinstance(final_envelope, dict) else None

        # finalizer_result/final_envelope.summary_text is the model's
        # deliberately-synthesized, user-facing final answer (async_finalizer.py)
        # -- prefer it over every other candidate. Without this, a real payload
        # observed in production (agent task BE770EA9) returned the raw
        # STEP_START/STEP_COMPLETE-prefixed agent_output ahead of this clean
        # field, purely because it was checked first and wasn't the (narrower)
        # "Enhanced workflow processed:" boilerplate.
        candidates = [
            finalizer.get("summary_text") if finalizer else None,
            final_envelope.get("summary_text") if final_envelope else None,
            result.get("summary_text"),
            result.get("message"),
            data.get("message") if data else None,
            data.get("summary_text") if data else None,
            self._strip_step_log_lines(self._extract_workflow_agent_output(data)),
            result.get("workflow_result"),
            data.get("workflow_result") if data else None,
            result.get("error"),
        ]

        first_boilerplate: Optional[str] = None
        for candidate in candidates:
            if not candidate:
                continue
            text = str(candidate)
            if _BOILERPLATE_WORKFLOW_PROMPT_ECHO_RE.match(text):
                if first_boilerplate is None:
                    first_boilerplate = text
                continue
            return text
        return first_boilerplate

    def _extract_workflow_agent_output(self, data: Any) -> Optional[str]:
        """Return the first non-empty agent_output from a tool-enhanced
        workflow envelope's ``data.workflow_details.results`` list, if any.

        The lifecycle's tool-enhanced workflow stores the user-visible
        narrative each step produced under
        ``data.workflow_details.results[*].agent_output``. Surfacing it
        here lets chain follow-ups quote the actual prior result instead
        of the boilerplate "Enhanced workflow processed: <prompt>" string.
        """
        if not isinstance(data, dict):
            return None
        details = data.get("workflow_details")
        if not isinstance(details, dict):
            return None
        results = details.get("results")
        if not isinstance(results, list):
            return None
        for entry in results:
            if not isinstance(entry, dict):
                continue
            agent_output = entry.get("agent_output")
            if isinstance(agent_output, str) and agent_output.strip():
                return agent_output
        return None

    def _extract_files(self, result: Any) -> List[Any]:
        files: List[Any] = []
        if not isinstance(result, dict):
            return files

        for key in ("files", "structuredFiles", "reference_paths"):
            value = result.get(key)
            if isinstance(value, list):
                files.extend(value)

        data = result.get("data")
        if isinstance(data, dict):
            files.extend(self._extract_files(data))

        finalizer = result.get("finalizer_result")
        if isinstance(finalizer, dict):
            payload = finalizer.get("result_payload")
            if isinstance(payload, dict):
                payload_files = payload.get("files")
                if isinstance(payload_files, list):
                    files.extend(payload_files)

        return files

    def _extract_browser_automation_targets(self, result: Any) -> List[Any]:
        targets: List[Any] = []
        for item in self._walk_values(result):
            if not isinstance(item, dict):
                continue
            direct_target = item.get("browser_automation_target")
            if isinstance(direct_target, dict) and direct_target not in targets:
                targets.append(direct_target)
            nested_targets = item.get("browser_automation_targets")
            if isinstance(nested_targets, list):
                for target in nested_targets:
                    if isinstance(target, dict) and target not in targets:
                        targets.append(target)
        return targets

    def _extract_blockers(self, result: Any) -> List[Any]:
        blockers: List[Any] = []
        for item in self._walk_values(result):
            if not isinstance(item, dict):
                continue
            error = item.get("error")
            if isinstance(error, dict):
                kind = str(error.get("kind") or "")
                if kind.startswith("auth") or kind in {"permission_denied", "blocked", "timeout"}:
                    blockers.append(error)
            if item.get("approval_timed_out") or item.get("user_action_required"):
                blockers.append(item)
        return blockers

    def _walk_values(self, value: Any) -> Iterable[Any]:
        yield value
        if isinstance(value, dict):
            for item in value.values():
                yield from self._walk_values(item)
        elif isinstance(value, list):
            for item in value:
                yield from self._walk_values(item)

    def _extract_failure_reason(self, result: Any) -> Optional[str]:
        if not isinstance(result, dict):
            return None
        failure_info = result.get("failure_info")
        if isinstance(failure_info, dict):
            reason = failure_info.get("error") or failure_info.get("previous_status")
            if reason:
                return self._truncate(str(reason), 300)
        error = result.get("error")
        if error:
            return self._truncate(str(error), 300)
        return None

    def _strip_step_log_lines(self, text: Optional[str]) -> Optional[str]:
        """Drop STEP_START/STEP_COMPLETE tool-telemetry line pairs.

        See the module-level regex comments for why only paired lines are
        stripped, not every line beginning with these tokens.
        """
        if not text:
            return text
        kept: List[str] = []
        skip_next_if_step_complete = False
        for line in text.split("\n"):
            if skip_next_if_step_complete and _STEP_COMPLETE_PREFIX_RE.match(line):
                skip_next_if_step_complete = False
                continue
            skip_next_if_step_complete = False
            if _STEP_START_LINE_RE.match(line):
                skip_next_if_step_complete = True
                continue
            kept.append(line)
        stripped = "\n".join(kept).strip()
        return stripped or None

    def _title_label(self, key: str) -> str:
        return key.replace("_", " ").capitalize()

    def _stringify(self, value: Any) -> str:
        try:
            return json.dumps(self._redact_value(value), ensure_ascii=False)
        except Exception:
            return str(value)

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 40)].rstrip() + "\n[...truncated for context budget...]"


def render_chain_turns_as_conversation(chain_agent_tasks: List[Dict[str, Any]]) -> str:
    """Render prior chain turns the same way `AgentContextAssembler` does for
    the tool-workflow follow-up path, so the discussion follow-up path
    (`agent_task_submission_service.handle_discussion_followup`) does not
    maintain a second, divergent context-rendering implementation."""
    return AgentContextAssembler()._format_chain_context({"chain_agentTasks": chain_agent_tasks})
