"""Task offer helpers for Basil setup recommendations."""

from __future__ import annotations

from typing import Dict, List


class SetupAssistantTaskOfferService:
    """Provide capability templates that Basil can adapt to user evidence."""

    def build_capability_seed_templates(self) -> List[Dict[str, str]]:
        """Return non-canned task categories for agent synthesis."""

        return [
            {
                "capability": "email_summary",
                "surface": "agent_task",
                "persona": "Paprika",
            },
            {
                "capability": "draft_reply",
                "surface": "assistant_session",
                "persona": "Dill",
            },
            {
                "capability": "file_organization",
                "surface": "agent_task",
                "persona": "Paprika",
            },
            {
                "capability": "workflow_unblock",
                "surface": "agent_task",
                "persona": "Paprika",
            },
        ]

