"""Policy engine for auto-approval decisions.

Evaluates tool calls against configured rules to determine if
a call can be auto-approved without human intervention.
"""

from __future__ import annotations

import logging
import time

from src.models import IntegrationConfig, PolicyConfig, ToolConfig

logger = logging.getLogger(__name__)


class PolicyEngine:
    """Evaluates whether a tool call requires human approval."""

    def __init__(
        self,
        policy: PolicyConfig,
        integrations: dict[str, IntegrationConfig],
    ) -> None:
        self.policy = policy
        self.integrations = integrations
        self._trust_until: dict[str, float] = {}

    def requires_approval(
        self,
        tool_name: str,
        integration: str,
        arguments: dict,
        *,
        is_read_only: bool = False,
    ) -> bool:
        """Check if a tool call requires human approval.

        Returns True if approval is needed, False if auto-approved.
        """
        if is_read_only and self.policy.auto_approve_reads:
            logger.debug("Auto-approved (read-only): %s/%s", integration, tool_name)
            return False

        if self._is_trusted(tool_name, integration):
            logger.debug("Auto-approved (trusted): %s/%s", integration, tool_name)
            return False

        tool_config = self._get_tool_config(tool_name, integration)

        if not tool_config.requires_approval:
            logger.debug("Auto-approved (config): %s/%s", integration, tool_name)
            return False

        if self._matches_domain_allowlist(tool_config, arguments):
            logger.debug(
                "Auto-approved (domain allowlist): %s/%s", integration, tool_name
            )
            return False

        return True

    def grant_trust(self, tool_name: str, integration: str) -> None:
        """Grant temporary trust for a tool (trust elevation)."""
        key = f"{integration}:{tool_name}"
        duration = self.policy.trust_elevation_minutes * 60
        self._trust_until[key] = time.time() + duration
        logger.info(
            "Trust granted for %s/%s (%d min)",
            integration,
            tool_name,
            self.policy.trust_elevation_minutes,
        )

    def _is_trusted(self, tool_name: str, integration: str) -> bool:
        key = f"{integration}:{tool_name}"
        until = self._trust_until.get(key, 0)
        if time.time() < until:
            return True
        self._trust_until.pop(key, None)
        return False

    def _get_tool_config(self, tool_name: str, integration: str) -> ToolConfig:
        int_config = self.integrations.get(integration)
        if int_config and tool_name in int_config.tools:
            return int_config.tools[tool_name]
        return ToolConfig(requires_approval=True)

    def _matches_domain_allowlist(
        self, tool_config: ToolConfig, arguments: dict
    ) -> bool:
        if not tool_config.auto_approve_domains:
            return False

        for field in ("to", "email", "recipient", "attendees"):
            value = arguments.get(field)
            if value is None:
                continue

            emails = value if isinstance(value, list) else [value]
            for email in emails:
                if not isinstance(email, str) or "@" not in email:
                    continue
                domain = email.split("@", 1)[1].lower()
                if domain not in tool_config.auto_approve_domains:
                    return False
            return True

        return False
