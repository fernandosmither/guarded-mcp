"""Shared fixtures for guarded-mcp tests."""

import pytest

from src.integrations.dummy import DummyIntegration
from src.models import (
    ApprovalRequest,
    IntegrationConfig,
    PolicyConfig,
    ServerConfig,
    TelegramConfig,
    ToolConfig,
)
from src.policy import PolicyEngine
from src.server import GuardedMCPServer


@pytest.fixture
def policy_config():
    return PolicyConfig(auto_approve_reads=True, trust_elevation_minutes=30)


@pytest.fixture
def integration_configs():
    return {
        "dummy": IntegrationConfig(
            enabled=True,
            tools={
                "dummy__echo": ToolConfig(requires_approval=False),
                "dummy__echo_gated": ToolConfig(
                    requires_approval=True,
                    auto_approve_domains=["allowed.com"],
                ),
            },
        )
    }


@pytest.fixture
def policy_engine(policy_config, integration_configs):
    return PolicyEngine(policy_config, integration_configs)


@pytest.fixture
def sample_request():
    return ApprovalRequest(
        tool_name="dummy__echo_gated",
        integration="dummy",
        arguments={"message": "test"},
    )


@pytest.fixture
def server_config(integration_configs):
    return ServerConfig(
        host="127.0.0.1",
        port=3100,
        approval_timeout_seconds=5,
        telegram=TelegramConfig(chat_id=0),
        policy=PolicyConfig(auto_approve_reads=True, trust_elevation_minutes=30),
        integrations=integration_configs,
    )


@pytest.fixture
def guarded_server(server_config):
    server = GuardedMCPServer(server_config)
    server.register_integration(DummyIntegration())
    return server
