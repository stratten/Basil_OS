"""Working memory LangChain tools."""

import json
from typing import Any, Dict, List

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

from .models import BaseTool, MemoryReadArgs, MemorySearchArgs


# Why these slim docs:
# - The two memory tools share scope with skill_search/skill_load, so the
#   slim_doc explicitly differentiates: 'memory' is the user's durable
#   facts/context; 'skills' is reusable how-to/recipe content. The system
#   prompt does not encode this distinction, so each slim_doc carries the
#   discriminating cue.
# - DROPS the longer 'overflow markdown files' framing on memory_search
#   (the agent does not need to know about overflow internals; it just
#   needs to know search returns line-level matches across the user's
#   memory store).
_MEMORY_READ_FULL = (
    "Read one bounded Basil working-memory markdown file. Use this for durable "
    "facts and context the user has allowed Basil to remember."
)
_MEMORY_READ_SLIM = (
    "Read one bounded Basil working-memory markdown file by name; use for "
    "durable facts/context the user has stored (preferences, names, "
    "ongoing context). For reusable how-to / recipe content, use skill_load "
    "/ skill_search instead."
)
_MEMORY_SEARCH_FULL = "Search Basil working memory and user overflow markdown files."
_MEMORY_SEARCH_SLIM = (
    "Search Basil working-memory markdown files by query; returns "
    "line-level matches with file_name and line_number so you can follow "
    "up with memory_read. For reusable how-to / recipe content, use "
    "skill_search instead."
)


def create_memory_tools(profile=None) -> List[BaseTool]:
    """Create explicit LangChain tools for Basil working memory.

    Under a slim rendering profile each tool's description is swapped to
    its hand-authored slim companion above; otherwise the full description
    flows through unchanged.
    """
    from langchain_core.tools import StructuredTool

    from api.services.memory.memory_service import get_memory_service

    memory_service = get_memory_service()

    def serialize_response(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    async def memory_read(file_name: str) -> str:
        try:
            document = memory_service.read_memory_file(file_name)
            return serialize_response(
                {
                    "success": True,
                    "file_name": document.file_name,
                    "content": document.content,
                    "size_bytes": document.size_bytes,
                    "cap_bytes": document.cap_bytes,
                }
            )
        except Exception as exc:
            return serialize_response({"success": False, "error": str(exc)})

    async def memory_search(query: str, max_results: int = 20) -> str:
        try:
            results = memory_service.search_memory(query, max_results=max_results)
            return serialize_response(
                {
                    "success": True,
                    "results": [
                        {
                            "file_name": result.file_name,
                            "line_number": result.line_number,
                            "line": result.line,
                        }
                        for result in results
                    ],
                }
            )
        except Exception as exc:
            return serialize_response({"success": False, "error": str(exc)})

    return [
        StructuredTool.from_function(
            func=memory_read,
            coroutine=memory_read,
            name="memory_read",
            description=select_description_for_profile(
                profile, _MEMORY_READ_FULL, _MEMORY_READ_SLIM
            ),
            args_schema=MemoryReadArgs,
        ),
        StructuredTool.from_function(
            func=memory_search,
            coroutine=memory_search,
            name="memory_search",
            description=select_description_for_profile(
                profile, _MEMORY_SEARCH_FULL, _MEMORY_SEARCH_SLIM
            ),
            args_schema=MemorySearchArgs,
        ),
    ]
