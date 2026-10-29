"""Shared models and LangChain compatibility exports for service tools."""

from dataclasses import dataclass, field
from typing import Dict, List

try:
    from langchain_core.tools import tool, BaseTool
    from pydantic import BaseModel, Field, create_model
    LANGCHAIN_AVAILABLE = True
except ImportError:
    # Fallback for environments where LangChain isn't available
    tool = lambda *args, **kwargs: lambda f: f
    BaseTool = object
    BaseModel = object
    Field = lambda *args, **kwargs: None
    create_model = lambda *args, **kwargs: None
    LANGCHAIN_AVAILABLE = False


if LANGCHAIN_AVAILABLE:
    class MemoryReadArgs(BaseModel):
        file_name: str = Field(
            description="Managed memory file to read: essentials.md, now.md, recent.md, user.md, or buffer.md."
        )


    class MemorySearchArgs(BaseModel):
        query: str = Field(description="Search text for working memory lookup.")
        max_results: int = Field(default=20, ge=1, le=50, description="Maximum number of line-level matches.")


    class SkillSearchArgs(BaseModel):
        query: str = Field(description="Search text describing the skill or workflow needed.")
        max_results: int = Field(default=10, ge=1, le=25, description="Maximum number of skill matches.")


    class SkillLoadArgs(BaseModel):
        slug: str = Field(description="Saved skill slug to load into task context.")
else:
    MemoryReadArgs = object
    MemorySearchArgs = object
    SkillSearchArgs = object
    SkillLoadArgs = object


@dataclass
class ToolCreationResult:
    """Result of creating tools from services."""
    tools: List[BaseTool]
    tool_map: Dict[str, BaseTool]  # service.method -> tool mapping
    errors: List[str]
    tool_error_log: List[Dict[str, str]] = field(default_factory=list)
    file_read_log: List[Dict[str, str]] = field(default_factory=list)
    # Non-fatal: optional / enhancement tools (checkpoint, web, browser, etc.) that failed to register
    optional_warnings: List[str] = field(default_factory=list)
