"""Basil history recall tools.

Exposes agent-task recall (recall_agent_tasks) and Conversation recall
(recall_conversations) as separate purpose-built tools. The RecallSource
contract in recall_core.py remains the extension seam for future
task-chain-shaped sources; ConversationRecallSource is conversation-keyed
rather than chain-keyed and is intentionally not registered against it.
"""

from .recall_core import RecallSource, register_recall_source, recall_source_names
from .agent_task_source import AgentTaskRecallSource
from .recall_tools import create_recall_tools
from .conversation_source import ConversationRecallSource
from .conversation_recall_tools import create_recall_conversations_tools

__all__ = [
    "RecallSource",
    "register_recall_source",
    "recall_source_names",
    "AgentTaskRecallSource",
    "create_recall_tools",
    "ConversationRecallSource",
    "create_recall_conversations_tools",
]
