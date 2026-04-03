"""Guarded MCP server with approval middleware.

Registers tools from integrations and intercepts calls that
require human approval before execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware

from src.approval import ApprovalEngine
from src.integrations.base import Integration, ToolDef
from src.models import (
    ApprovalRequest,
    ApprovalStatus,
    GoogleConfig,
    IntegrationConfig,
    PolicyConfig,
    ServerConfig,
    TelegramConfig,
    ToolConfig,
)
from src.policy import PolicyEngine

logger = logging.getLogger(__name__)


def load_config(path: str = "config.toml") -> ServerConfig:
    """Load server configuration from a TOML file."""
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("No config file at %s, using defaults", path)
        return ServerConfig()

    import tomllib

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    telegram = TelegramConfig(**raw.get("telegram", {}))
    policy = PolicyConfig(**raw.get("policy", {}))
    google = GoogleConfig(**raw.get("google", {}))

    integrations: dict[str, IntegrationConfig] = {}
    for name, int_raw in raw.get("integrations", {}).items():
        tools_raw = int_raw.pop("tools", {})
        tools = {k: ToolConfig(**v) for k, v in tools_raw.items()}
        integrations[name] = IntegrationConfig(tools=tools, **int_raw)

    return ServerConfig(
        host=raw.get("server", {}).get("host", "127.0.0.1"),
        port=raw.get("server", {}).get("port", 3100),
        approval_timeout_seconds=raw.get("server", {}).get(
            "approval_timeout_seconds", 300
        ),
        telegram=telegram,
        policy=policy,
        google=google,
        integrations=integrations,
    )


class GuardedMCPServer:
    """MCP server with approval-gated tools."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.mcp = FastMCP("Guarded MCP")
        self.policy = PolicyEngine(config.policy, config.integrations)
        self.approval: ApprovalEngine | None = None
        self._integrations: dict[str, Integration] = {}
        self._tool_meta: dict[str, ToolDef] = {}
        self._tool_integration: dict[str, str] = {}

    def register_integration(self, integration: Integration) -> None:
        """Register an integration and its tools with the MCP server."""
        self._integrations[integration.name] = integration

        for tool_def in integration.tools():
            full_name = f"{integration.name}__{tool_def.name}"
            self._tool_meta[full_name] = tool_def
            self._tool_integration[full_name] = integration.name

            self._register_tool(full_name, tool_def, integration)

            logger.info(
                "Registered tool: %s (approval=%s, read_only=%s)",
                full_name,
                tool_def.requires_approval,
                tool_def.read_only,
            )

    def _register_tool(
        self, full_name: str, tool_def: ToolDef, integration: Integration
    ) -> None:
        """Register a single tool with FastMCP."""
        import inspect
        from typing import Annotated

        from fastmcp.tools.function_tool import FunctionTool
        from pydantic import Field

        schema = tool_def.input_schema
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        # Build function parameters for the handler
        param_list = []
        annotations = {}

        for param_name, param_schema in props.items():
            type_str = param_schema.get("type", "string")
            param_type: type = str
            if type_str == "integer":
                param_type = int
            elif type_str == "number":
                param_type = float
            elif type_str == "boolean":
                param_type = bool
            elif type_str == "array":
                param_type = list
            elif type_str == "object":
                param_type = dict

            desc = param_schema.get("description", "")

            if param_name in required:
                ann = Annotated[param_type, Field(description=desc)]
                default = inspect.Parameter.empty
            else:
                ann = Annotated[param_type | None, Field(description=desc)]
                default = None

            annotations[param_name] = ann
            param_list.append(inspect.Parameter(
                param_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
                annotation=ann,
            ))

        int_ref = integration
        td_ref = tool_def

        async def handler(**kwargs: Any) -> Any:
            return await int_ref.execute(td_ref.name, kwargs)

        # Give the function a proper signature so FastMCP can parse it
        handler.__name__ = full_name
        handler.__qualname__ = full_name
        handler.__doc__ = tool_def.description
        handler.__annotations__ = annotations
        handler.__signature__ = inspect.Signature(param_list)

        tool_obj = FunctionTool.from_function(
            handler,
            name=full_name,
            description=tool_def.description,
        )
        self.mcp.add_tool(tool_obj)

    def _setup_middleware(self) -> None:
        """Set up the approval middleware on the MCP server."""

        server = self

        class ApprovalMiddleware(Middleware):
            async def on_call_tool(self, context, call_next):
                tool_name = context.message.name
                arguments = context.message.arguments or {}

                meta = server._tool_meta.get(tool_name)
                integration_name = server._tool_integration.get(tool_name, "unknown")

                if meta is None:
                    return await call_next(context)

                needs_approval = server.policy.requires_approval(
                    tool_name=tool_name,
                    integration=integration_name,
                    arguments=arguments,
                    is_read_only=meta.read_only,
                )

                if not needs_approval:
                    logger.info("Executing (no approval needed): %s", tool_name)
                    return await call_next(context)

                if server.approval is None:
                    logger.error(
                        "Approval required but no approval engine configured"
                    )
                    from fastmcp.exceptions import ToolError

                    raise ToolError(
                        "This action requires approval but the approval engine "
                        "is not configured. Set up Telegram credentials."
                    )

                request = ApprovalRequest(
                    tool_name=tool_name,
                    integration=integration_name,
                    arguments=arguments,
                )

                logger.info(
                    "Requesting approval: %s (hash=%s)",
                    tool_name,
                    request.params_hash[:16],
                )

                status = await server.approval.request_approval(request)

                if status == ApprovalStatus.APPROVED:
                    if request.trust_elevated:
                        server.policy.grant_trust(tool_name, integration_name)
                    logger.info("Executing (approved): %s", tool_name)
                    return await call_next(context)
                elif status == ApprovalStatus.REJECTED:
                    from fastmcp.exceptions import ToolError

                    raise ToolError(
                        f"Action rejected by user. Tool: {tool_name}"
                    )
                elif status == ApprovalStatus.EXPIRED:
                    from fastmcp.exceptions import ToolError

                    raise ToolError(
                        f"Approval timed out after "
                        f"{server.config.approval_timeout_seconds}s. "
                        f"Tool: {tool_name}. Retry if needed."
                    )
                else:
                    from fastmcp.exceptions import ToolError

                    raise ToolError(
                        f"Unexpected approval status: {status}"
                    )

        self.mcp.add_middleware(ApprovalMiddleware())

    async def start(self) -> None:
        """Initialize the approval engine and start the server."""
        telegram_cfg = self.config.telegram
        if telegram_cfg.chat_id:
            self.approval = ApprovalEngine.from_config(
                telegram_cfg.model_dump(),
                timeout=self.config.approval_timeout_seconds,
            )
            await self.approval.start()

        for integration in self._integrations.values():
            await integration.authenticate()

        self._setup_middleware()

    async def stop(self) -> None:
        """Shut down the approval engine and clean up resources."""
        if self.approval is not None:
            await self.approval.stop()
            logger.info("Approval engine stopped")

    def run(self) -> None:
        """Run the MCP server."""
        self.mcp.run(
            transport="http",
            host=self.config.host,
            port=self.config.port,
            stateless_http=True,
        )
