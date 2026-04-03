"""Dummy integration for testing the approval flow."""

from __future__ import annotations

from typing import Any

from src.integrations.base import Integration, ToolDef


class DummyIntegration(Integration):
    name = "dummy"

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="echo",
                description="Echo back the input. Read-only, no approval needed.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message to echo",
                        }
                    },
                    "required": ["message"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="echo_gated",
                description="Echo back the input, but requires approval first.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message to echo",
                        },
                        "to": {
                            "type": "string",
                            "description": (
                                "Recipient email (for domain allowlists)"
                            ),
                        },
                    },
                    "required": ["message"],
                },
                read_only=False,
                requires_approval=True,
            ),
        ]

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        message = arguments.get("message", "")
        to = arguments.get("to", "")
        return {
            "tool": tool_name,
            "echoed": message,
            "to": to,
            "status": "executed",
        }
