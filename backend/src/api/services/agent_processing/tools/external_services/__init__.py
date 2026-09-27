"""
External Services Tools

Tools that interact with external APIs and services (not local macOS applications).
Includes web search, external API integrations, and cloud service interactions.
"""

from .web_search_tool import create_web_search_tool

__all__ = [
    'create_web_search_tool',
]
