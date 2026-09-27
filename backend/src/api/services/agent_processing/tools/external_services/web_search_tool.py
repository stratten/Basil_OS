"""
Web Search Tool for Agent

Provides the agent with explicit web search capabilities. This tool enables the agent
to search the internet for current information, research topics, find product links,
and access up-to-date knowledge beyond its training data.
"""

import logging
import json
from typing import Optional
from urllib.parse import quote_plus
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.core.models.models_registry.schema import ModelFeature, has_feature
from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
)

logger = logging.getLogger(__name__)


class WebSearchInput(BaseModel):
    """Input schema for web search tool."""
    query: str = Field(
        description=(
            "The search query to look up on the internet. Be specific and include relevant keywords.\n"
            "Examples:\n"
            "  - 'best fabric stain removers for office chairs'\n"
            "  - 'Folex Carpet Spot Remover Amazon'\n"
            "  - 'latest Salesforce API version documentation'\n"
            "  - 'current price of iPhone 15 Pro'"
        )
    )
    focus: Optional[str] = Field(
        default=None,
        description=(
            "Optional focus area for the search to get more targeted results.\n"
            "Examples: 'product reviews', 'pricing', 'how-to guides', 'technical documentation'"
        )
    )


def _browser_search_handoff(query: str, focus: Optional[str], model_label: str) -> str:
    """Return a browser-driven search handoff for models without native web search.

    Local models cannot call a provider-side web search, so instead of failing we
    hand the agent a concrete browse loop (open a results page in the user's
    browser, read links, navigate, read page content) plus a ready-to-use,
    low-friction search URL.
    """
    search_terms = f"{query} {focus}".strip() if focus else query
    search_url = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(search_terms)
    return json.dumps({
        "success": False,
        "query": query,
        "focus": focus,
        "model_used": model_label,
        "has_web_access": False,
        "web_access": "browser_required",
        "reason": (
            "The active model has no native web search. Use the browser tools to "
            "search and read results in the user's browser instead."
        ),
        "suggested_search_url": search_url,
        "next_actions": [
            f'browser_tabs(action="ensure_automation_window", url="{search_url}") to open the results page.',
            'browser_inspect(focus="links") to read the result titles and URLs.',
            'browser_interact(action="navigate", selector=<chosen result URL>) to open a result.',
            'browser_inspect(focus="content") to read the page text, then synthesize the answer.',
        ],
        "search_results": None,
    }, ensure_ascii=False, indent=2)


async def _web_search_impl(query: str, focus: Optional[str] = None) -> str:
    """Implementation of web search tool.
    
    This tool uses the LLM's native web search capabilities (enable_web_search=True)
    to find current information on the internet.
    
    Args:
        query: The search query string
        focus: Optional focus area to refine results
        
    Returns:
        JSON string containing search results and synthesized answer
    """
    try:
        from api.dependencies import get_model_service
        from api.services.model_usage_service import ModelUsageService
        from api.core.models.model_types import ModelCapability
        
        logger.info(f"🌐 Web search requested: '{query}' (focus: {focus})")

        # Resolve the model actually running this agent task (not the user's
        # preferred default), so a local run does not silently borrow a cloud
        # model. context["model_id"] is a registry id.
        active_model_id = get_current_agent_context().get("model_id")

        # Local / non-native-search models: hand off to the browser-driven path
        # without resolving (and possibly loading) any model. has_feature is the
        # authoritative, registry-driven capability check; it returns False for
        # local and unknown ids.
        if active_model_id and not has_feature(active_model_id, ModelFeature.WEB_SEARCH):
            logger.info(f"🌐 Web search handoff to browser for local model '{active_model_id}'")
            return _browser_search_handoff(query, focus, active_model_id)

        # Get a model instance capable of web search
        model_service = get_model_service()
        model_usage_service = ModelUsageService(model_service)

        # Resolve the active model (explicit_model_id=None falls back to the
        # user's preferred reasoning model, preserving prior behavior for
        # non-pinned runs).
        model = await model_usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=active_model_id,
        )

        if not model:
            raise Exception("No suitable model found for web search")

        model_name = getattr(model, 'model_name', 'unknown')

        # Covers active_model_id=None (preferred model in use): branch on the
        # resolved model's actual registry capability. Never call
        # generate_response on a model that cannot natively search.
        if not has_feature(model_name, ModelFeature.WEB_SEARCH):
            logger.info(f"🌐 Web search handoff to browser for model '{model_name}'")
            return _browser_search_handoff(query, focus, model_name)

        logger.info(f"🤖 Using model {model_name} for native web search")
        
        # Build search prompt
        focus_instruction = f"\n\nFocus your search on: {focus}" if focus else ""
        
        prompt = f"""Search the internet for information about: "{query}"{focus_instruction}

Please provide:
1. A synthesized answer based on current web information
2. Specific details, links, or product recommendations if applicable
3. Any relevant pricing, availability, or current status information

Be specific and factual. If you find product links (like Amazon URLs), include them."""
        
        # Call model with web search enabled
        # Use 6000 tokens to allow comprehensive research results without truncation
        logger.info(f"🌐 Executing web search with enable_web_search=True")
        
        response = await model.generate_response(
            prompt=prompt,
            max_tokens=6000,
            enable_web_search=True  # THIS is the key - enables web search capabilities
        )
        
        if not response:
            raise Exception("Model returned empty response for web search")
        
        logger.info(f"✅ Web search completed, response length: {len(response)}")
        
        # Return structured result
        return json.dumps({
            "success": True,
            "query": query,
            "focus": focus,
            "model_used": model_name,
            "search_results": response.strip(),
            "has_web_access": True
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.error(f"❌ Web search failed: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "query": query,
            "error": str(e),
            "search_results": None,
            "has_web_access": False
        }, ensure_ascii=False)


# Why this slim:
# - KEEPS: the discriminating question that gates web_search vs. local tools
#   vs. the model's own training data; the negative routing examples are
#   compressed into a single rule rather than an enumeration; the 'surface
#   phrasing alone is not sufficient justification' invariant survives because
#   it is the most frequent misroute (the agent reaches for web_search the
#   moment it sees 'find' or 'look up').
# - DROPS: usage examples (the focus field's description carries the
#   intent and the query field is self-explanatory); the OUTPUT block
#   (envelope shape becomes obvious from a single result); the IMPORTANT
#   tips ('be specific', 'include store name') because they are advice not
#   invariants - the agent will adapt from result quality.
SLIM_DESCRIPTION = (
    "Search the open internet for information that exists outside the user's "
    "own systems AND outside your training data (current prices, recent "
    "releases, live web pages). Do NOT use for answers that live locally "
    "(email_service, file_service, query_activities, browser_inspect) or in "
    "third-party services the user has connected (external_catalog), and do "
    "not use for facts you already know. Surface phrasing like 'find' or "
    "'look up' is not sufficient justification - apply the routing rule "
    "above to whether the answer actually lives on the open web."
)

_FULL_DESCRIPTION = """Search the internet for current information, product links, prices, and up-to-date knowledge.

**CAPABILITIES:**
- Search for current information beyond your training data
- Find product recommendations and Amazon/shopping links
- Look up pricing and availability
- Research technical documentation and guides
- Get real-time information about events, releases, or updates

**WHEN TO USE:**
Use this tool ONLY when the answer requires information that exists outside the user's
own systems (email, files, browser, activity history) AND outside your training data.

The discriminating question is: could the answer exist locally or in the model's own
knowledge? If yes, do NOT use this tool — use the appropriate local tool instead.

- USE: "What's the current price of a standing desk on Amazon?" → price changes daily, not local.
- USE: "Find the latest release notes for React 19" → recent release, may postdate training.
- DO NOT USE: "Find my last email from Sarah" → answer is in email_service, not the web.
- DO NOT USE: "Look up what I was working on yesterday" → answer is in query_activities.
- DO NOT USE: "What is the capital of France?" → model already knows this; no search needed.

Surface phrasing ("find", "look up", "search for") is not sufficient justification —
those verbs apply equally to local and web lookups. Apply the rule above to determine
whether the answer actually lives on the internet.

**USAGE EXAMPLES:**
- web_search(query="best office chair cleaning products", focus="product reviews")
- web_search(query="Folex Carpet Spot Remover Amazon")
- web_search(query="current Salesforce API version", focus="technical documentation")
- web_search(query="iPhone 15 Pro price comparison", focus="pricing")

**IMPORTANT:**
- Be specific in your queries - more detail gets better results
- If user asks for product links, include the store name (Amazon, etc.) in query
- Use the 'focus' parameter to get more targeted results
- The search results will include links and URLs when available

**OUTPUT:**
Returns JSON with:
- `search_results`: Synthesized answer with links, prices, and relevant details
- `success`: Whether the search succeeded
- `has_web_access`: Confirms web search capability is active
"""


def create_web_search_tool(profile=None) -> StructuredTool:
    """Factory for the ``web_search`` tool.

    Under a slim rendering profile the description is swapped to
    ``SLIM_DESCRIPTION`` above; otherwise ``_FULL_DESCRIPTION`` flows
    through unchanged.
    """
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )

    return StructuredTool.from_function(
        func=_web_search_impl,
        name="web_search",
        description=tool_description,
        args_schema=WebSearchInput,
        coroutine=_web_search_impl  # Mark as async
    )
