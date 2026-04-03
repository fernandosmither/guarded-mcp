"""Base class for guarded-mcp integrations.

Each integration provides a list of tool definitions and an execute method.
Tools are annotated with metadata indicating whether they require approval
and whether they are read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDef:
    """Definition of an MCP tool provided by an integration."""

    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False
    requires_approval: bool = True
    tags: list[str] = field(default_factory=list)


class Integration:
    """Base class for all integrations.

    Subclasses must implement `tools()` and `execute()`.
    """

    name: str = "base"

    def tools(self) -> list[ToolDef]:
        """Return the list of tools this integration provides."""
        raise NotImplementedError

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        """Execute a tool call and return the result."""
        raise NotImplementedError

    async def authenticate(self) -> None:
        """Called on server startup. Override for OAuth2 token setup."""

    async def refresh_auth(self) -> None:
        """Called when a 401 is received. Override for token refresh."""
