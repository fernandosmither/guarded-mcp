"""Tests for PolicyEngine."""

from src.models import IntegrationConfig, PolicyConfig, ToolConfig
from src.policy import PolicyEngine


def test_read_only_auto_approved(policy_engine):
    assert policy_engine.requires_approval(
        tool_name="dummy__echo",
        integration="dummy",
        arguments={},
        is_read_only=True,
    ) is False


def test_read_only_not_auto_approved_when_disabled():
    policy = PolicyConfig(auto_approve_reads=False)
    engine = PolicyEngine(policy, {})
    assert engine.requires_approval(
        tool_name="any_tool",
        integration="any",
        arguments={},
        is_read_only=True,
    ) is True


def test_trust_elevation_grants_bypass(policy_engine):
    policy_engine.grant_trust("dummy__echo_gated", "dummy")
    assert policy_engine.requires_approval(
        tool_name="dummy__echo_gated",
        integration="dummy",
        arguments={},
    ) is False


def test_trust_elevation_expires():
    policy = PolicyConfig(auto_approve_reads=True, trust_elevation_minutes=0)
    engine = PolicyEngine(policy, {})
    engine.grant_trust("tool", "integration")
    # With 0 minutes, trust expires immediately
    assert engine.requires_approval(
        tool_name="tool",
        integration="integration",
        arguments={},
    ) is True


def test_trust_elevation_scoped_to_tool(policy_engine):
    policy_engine.grant_trust("tool_a", "integration")
    # tool_b should still require approval
    assert policy_engine.requires_approval(
        tool_name="tool_b",
        integration="integration",
        arguments={},
    ) is True


def test_tool_config_no_approval():
    policy = PolicyConfig(auto_approve_reads=False)
    integrations = {
        "test": IntegrationConfig(
            tools={"my_tool": ToolConfig(requires_approval=False)}
        )
    }
    engine = PolicyEngine(policy, integrations)
    assert engine.requires_approval(
        tool_name="my_tool",
        integration="test",
        arguments={},
    ) is False


def test_domain_allowlist_matches(policy_engine):
    assert policy_engine.requires_approval(
        tool_name="dummy__echo_gated",
        integration="dummy",
        arguments={"message": "hi", "to": "user@allowed.com"},
    ) is False


def test_domain_allowlist_rejects_other_domain(policy_engine):
    assert policy_engine.requires_approval(
        tool_name="dummy__echo_gated",
        integration="dummy",
        arguments={"message": "hi", "to": "user@evil.com"},
    ) is True


def test_domain_allowlist_checks_all_recipients(policy_engine):
    # One recipient outside allowlist → needs approval
    assert policy_engine.requires_approval(
        tool_name="dummy__echo_gated",
        integration="dummy",
        arguments={"to": ["user@allowed.com", "user@evil.com"]},
    ) is True


def test_unknown_tool_requires_approval(policy_engine):
    assert policy_engine.requires_approval(
        tool_name="nonexistent_tool",
        integration="nonexistent",
        arguments={},
    ) is True


def test_domain_allowlist_email_field():
    policy = PolicyConfig(auto_approve_reads=False)
    integrations = {
        "test": IntegrationConfig(
            tools={"send": ToolConfig(
                requires_approval=True,
                auto_approve_domains=["safe.com"],
            )}
        )
    }
    engine = PolicyEngine(policy, integrations)
    assert engine.requires_approval(
        tool_name="send",
        integration="test",
        arguments={"email": "bob@safe.com"},
    ) is False
