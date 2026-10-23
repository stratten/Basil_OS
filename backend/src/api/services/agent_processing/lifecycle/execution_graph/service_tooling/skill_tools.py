"""Saved skill catalog LangChain tools."""

import json
from typing import Any, Dict, List

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

from .models import BaseTool, SkillLoadArgs, SkillSearchArgs


# Why these slim docs:
# - The two skill tools follow the search-then-load pattern (catalog
#   metadata first, then on-demand body load) that keeps the catalog
#   scalable without pre-injecting every SKILL.md into context. The slim
#   docs surface that pattern explicitly so the agent calls skill_search
#   first and only loads the bodies it actually needs.
# - DROPS the longer 'reusable procedures relevant to the task' framing
#   from skill_search and the 'when its catalog entry appears relevant'
#   framing from skill_load - both compressed into the search-then-load
#   pairing rule below.
_SKILL_SEARCH_FULL = (
    "Search the user's saved skill catalog for reusable procedures relevant to the task."
)
_SKILL_SEARCH_SLIM = (
    "Search the user's saved skill catalog (returns slug + title + "
    "when_to_use metadata only). Bodies are NOT included; if a result "
    "looks relevant, follow up with skill_load(slug=...) to fetch the "
    "SKILL.md body. For durable user facts/context use memory_search "
    "instead - skills are reusable how-to / recipe content."
)
_SKILL_LOAD_FULL = (
    "Load one saved SKILL.md body by slug when its catalog entry appears relevant."
)
_SKILL_LOAD_SLIM = (
    "Load one saved SKILL.md body by slug; use after skill_search has "
    "surfaced a candidate whose when_to_use matches your task. Avoid "
    "loading bodies speculatively; one-at-a-time keeps the context lean."
)


def create_skill_tools(profile=None) -> List[BaseTool]:
    """Create explicit LangChain tools for saved skill discovery and loading.

    Under a slim rendering profile each tool's description is swapped to
    its hand-authored slim companion above; otherwise the full description
    flows through unchanged.
    """
    from langchain_core.tools import StructuredTool

    from api.services.skills.skill_service import get_skill_service

    skill_service = get_skill_service()

    def serialize_response(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    async def skill_search(query: str, max_results: int = 10) -> str:
        try:
            results = skill_service.search_skills(query, max_results=max_results)
            return serialize_response(
                {
                    "success": True,
                    "results": [
                        {
                            "slug": result.slug,
                            "title": result.title,
                            "when_to_use": result.when_to_use,
                            "triggers": result.triggers,
                            "score": result.score,
                        }
                        for result in results
                    ],
                }
            )
        except Exception as exc:
            return serialize_response({"success": False, "error": str(exc)})

    async def skill_load(slug: str) -> str:
        try:
            record = skill_service.load_skill(slug)
            return serialize_response(
                {
                    "success": True,
                    "slug": record.slug,
                    "body": record.body,
                    "metadata": record.metadata,
                    "size_bytes": record.size_bytes,
                    "cap_bytes": record.cap_bytes,
                }
            )
        except Exception as exc:
            return serialize_response({"success": False, "error": str(exc)})

    return [
        StructuredTool.from_function(
            func=skill_search,
            coroutine=skill_search,
            name="skill_search",
            description=select_description_for_profile(
                profile, _SKILL_SEARCH_FULL, _SKILL_SEARCH_SLIM
            ),
            args_schema=SkillSearchArgs,
        ),
        StructuredTool.from_function(
            func=skill_load,
            coroutine=skill_load,
            name="skill_load",
            description=select_description_for_profile(
                profile, _SKILL_LOAD_FULL, _SKILL_LOAD_SLIM
            ),
            args_schema=SkillLoadArgs,
        ),
    ]
