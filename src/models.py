"""Pydantic models for the approval engine and configuration."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    """A pending approval request for a gated tool call."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    tool_name: str
    integration: str
    arguments: dict
    params_hash: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    resolved_at: float | None = None
    telegram_message_id: int | None = None
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    trust_elevated: bool = False

    def model_post_init(self, __context: object) -> None:
        if not self.params_hash:
            self.params_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        canonical = json.dumps(
            {"tool": self.tool_name, "args": self.arguments},
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def verify_hash(self) -> bool:
        return self.params_hash == self._compute_hash()

    def is_expired(self, timeout_seconds: float) -> bool:
        return time.time() - self.created_at > timeout_seconds


class ToolConfig(BaseModel):
    """Per-tool configuration from config.toml."""

    requires_approval: bool = True
    auto_approve_domains: list[str] = Field(default_factory=list)


class IntegrationConfig(BaseModel):
    """Per-integration configuration."""

    enabled: bool = True
    credentials_env_prefix: str = ""
    tools: dict[str, ToolConfig] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    """Global policy configuration."""

    auto_approve_reads: bool = True
    trust_elevation_minutes: int = 30


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    bot_token_env: str = "APPROVAL_BOT_TOKEN"
    chat_id: int = 0
    allowed_user_ids: list[int] = Field(default_factory=list)


class GoogleConfig(BaseModel):
    """Google OAuth2 configuration for multi-account access."""

    client_secret_path: str = "credentials/client_secret.json"
    credentials_dir: str = "credentials"
    secret_env: str = "GUARDED_MCP_SECRET"
    accounts: list[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    """Top-level server configuration."""

    host: str = "127.0.0.1"
    port: int = 3100
    approval_timeout_seconds: int = 300
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    integrations: dict[str, IntegrationConfig] = Field(default_factory=dict)
