"""Tool description and progress metadata helpers."""

import logging
from typing import Any, Dict, List, Optional

from api.core.models.reasoning.model_runtime_profile import (
    RuntimeModelProfile,
    is_slim_rendering,
    resolve_tool_rendering_for,
)

logger = logging.getLogger(__name__)


def generate_tool_description(
    service_name: str,
    method_name: str,
    method_info: Dict[str, Any],
    execution_principles: List[str],
    profile: Optional[RuntimeModelProfile] = None,
) -> str:
    """Generate the per-tool description published to LangChain.

    Under a slim rendering profile, returns the hand-authored ``slim_doc`` from
    ``method_info`` when present. Empty/missing ``slim_doc`` falls back to the
    full composition with a warning so the agent never sees a silently
    truncated description, but the build_chars_total target won't be hit until
    every method's ``slim_doc`` is authored.
    """
    if is_slim_rendering(profile):
        slim_doc = method_info.get("slim_doc")
        if isinstance(slim_doc, str) and slim_doc.strip():
            return slim_doc.strip()
        logger.warning(
            "slim_doc missing for %s.%s under profile %s; falling back to full doc.",
            service_name,
            method_name,
            resolve_tool_rendering_for(profile),
        )

    base_desc = method_info.get("doc", f"Execute {method_name} on {service_name}")
    signature = method_info.get("signature", "")

    description = f"{base_desc}\n\nSignature: {signature}"

    if execution_principles:
        description += f"\n\nExecution Principles:\n"
        for principle in execution_principles[:6]:  # Show first 6 principles (covers critical parameter mapping + thread deduplication + key workflow rules)
            description += f"- {principle}\n"

    # Cross-tool guardrails (file deletion safety, etc.) live in
    # system_prompts.py under TOOL ETIQUETTE; tool-family-specific tips
    # (e.g., "use 'do shell script' for deferred AppleScript actions",
    # "shell pipelines use bash -lc") live in each service's
    # execution_principles or in the per-section blocks of system_prompts.py
    # (SHELL USAGE RULES, FILE OPERATION REPORTING, PATH QUALITY REQUIREMENTS).
    # Do not re-add static inline notes here without first checking that
    # they aren't already stated in those canonical locations.

    return description.strip()


def generate_progress_metadata(
    service_name: str,
    method_name: str,
    method_info: Dict[str, Any],
) -> Dict[str, str]:
    """Generate intelligent progress templates based on service/method characteristics and parameters."""
    parameters = method_info.get("parameters", {})
    doc = method_info.get("doc", "").lower()

    # Build service-method specific patterns with parameter-driven templates
    templates = {}

    # AppleScript services - prioritize task descriptions
    if "applescript" in service_name:
        if "task_description" in parameters:
            templates["progress_template"] = "{task_description}"
            templates["fallback_template"] = "Automating {context_data.file_name} with macOS" if "context_data" in parameters else "Running macOS automation"
        elif "script_content" in parameters:
            templates["progress_template"] = "Executing custom AppleScript"
            templates["fallback_template"] = "Running macOS automation script"
        else:
            templates["progress_template"] = "Running macOS automation"

    # Email services - focus on email context
    elif "email" in service_name:
        if "search" in method_name and "criteria" in parameters:
            templates["progress_template"] = "Searching emails from: {criteria.sender}"
            templates["fallback_template"] = "Searching emails"
        elif "get" in method_name and "folder" in parameters:
            templates["progress_template"] = "Retrieving emails from {folder}"
            templates["fallback_template"] = "Retrieving emails"
        elif "reply" in method_name:
            templates["progress_template"] = "Replying to email"
        elif ("create" in method_name or "draft" in method_name) and "email_request" in parameters:
            templates["progress_template"] = "Drafting email: {email_request.subject}"
            templates["fallback_template"] = "Drafting email"
        elif "organize" in method_name:
            templates["progress_template"] = "Organizing emails into {folder}" if "folder" in parameters else "Organizing emails"
        elif "process" in method_name:
            templates["progress_template"] = "Processing email request"
        else:
            templates["progress_template"] = f"Email: {method_name.replace('_', ' ')}"

    # File services - emphasize file operations
    elif "file" in service_name:
        file_params = [p for p in parameters.keys() if any(term in p.lower() for term in ["file", "path", "name"])]
        if file_params:
            file_param = file_params[0]  # Use first file-related parameter
            if "create" in method_name or "generate" in method_name:
                templates["progress_template"] = f"Creating file: {{{file_param}}}"
            elif "find" in method_name or "search" in method_name:
                templates["progress_template"] = f"Finding file: {{{file_param}}}"
            else:
                templates["progress_template"] = f"Working with file: {{{file_param}}}"
        else:
            templates["progress_template"] = f"File operation: {method_name.replace('_', ' ')}"

    # Router services - extract operation context
    elif "router" in service_name:
        if "suggestion" in method_name and "context" in parameters:
            templates["progress_template"] = "Generating suggestions for: {context}"
            templates["fallback_template"] = "Generating suggestions"
        elif "screen" in method_name:
            templates["progress_template"] = "Capturing screen content"
        elif "activity" in method_name and "query" in parameters:
            templates["progress_template"] = "Searching activity: {query}"
            templates["fallback_template"] = "Searching recent activity"
        else:
            templates["progress_template"] = f"Processing: {method_name.replace('_', ' ')}"

    # Shell service - show the command being run
    elif "shell" in service_name:
        if "command" in parameters:
            templates["progress_template"] = "Running: {command}"
            templates["fallback_template"] = "Running shell command"
        else:
            templates["progress_template"] = "Running shell command"

    # Generic fallback based on method name and parameters
    else:
        # Look for common descriptive parameters
        if "description" in parameters:
            templates["progress_template"] = "{description}"
        elif "query" in parameters:
            templates["progress_template"] = f"Searching: {{query}}"
        elif "action" in parameters:
            templates["progress_template"] = "{action}"
        else:
            # Clean up method name for display
            clean_method = method_name.replace("_", " ").title()
            templates["progress_template"] = f"{clean_method}"

    # Always provide a simple fallback
    templates["simple_description"] = f"{service_name.replace('_', ' ').title()}: {method_name.replace('_', ' ')}"

    return templates
