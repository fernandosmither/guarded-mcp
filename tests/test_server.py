"""End-to-end tests for GuardedMCPServer via FastMCPTransport."""

from unittest.mock import AsyncMock

import pytest
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport

from src.integrations.dummy import DummyIntegration
from src.models import (
    ApprovalRequest,
    ApprovalStatus,
    IntegrationConfig,
    PolicyConfig,
    ServerConfig,
    TelegramConfig,
    ToolConfig,
)
from src.server import GuardedMCPServer


async def _make_client(server: GuardedMCPServer) -> Client:
    transport = FastMCPTransport(server.mcp)
    client = Client(transport)
    await client.__aenter__()
    return client


async def test_list_tools(guarded_server):
    await guarded_server.start()
    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "dummy__echo" in names
        assert "dummy__echo_gated" in names


async def test_read_only_tool_no_approval(guarded_server):
    await guarded_server.start()
    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        result = await client.call_tool("dummy__echo", {"message": "hello"})
        assert any("hello" in str(c.text) for c in result.content)


async def test_gated_tool_without_approval_engine_errors(guarded_server):
    await guarded_server.start()
    # approval is None because chat_id=0
    assert guarded_server.approval is None
    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        with pytest.raises(Exception, match="approval"):
            await client.call_tool(
                "dummy__echo_gated", {"message": "test"}
            )


async def test_gated_tool_approved(guarded_server):
    await guarded_server.start()

    mock_approval = AsyncMock()
    mock_req_store = {}

    async def fake_request_approval(req: ApprovalRequest) -> ApprovalStatus:
        req.status = ApprovalStatus.APPROVED
        mock_req_store["last"] = req
        return ApprovalStatus.APPROVED

    mock_approval.request_approval = fake_request_approval
    guarded_server.approval = mock_approval

    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        result = await client.call_tool(
            "dummy__echo_gated", {"message": "approved msg"}
        )
        assert any("approved msg" in str(c.text) for c in result.content)


async def test_gated_tool_rejected(guarded_server):
    await guarded_server.start()

    async def fake_request_approval(req: ApprovalRequest) -> ApprovalStatus:
        req.status = ApprovalStatus.REJECTED
        return ApprovalStatus.REJECTED

    mock_approval = AsyncMock()
    mock_approval.request_approval = fake_request_approval
    guarded_server.approval = mock_approval

    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        with pytest.raises(Exception, match="rejected|Rejected"):
            await client.call_tool(
                "dummy__echo_gated", {"message": "test"}
            )


async def test_gated_tool_expired(guarded_server):
    await guarded_server.start()

    async def fake_request_approval(req: ApprovalRequest) -> ApprovalStatus:
        req.status = ApprovalStatus.EXPIRED
        return ApprovalStatus.EXPIRED

    mock_approval = AsyncMock()
    mock_approval.request_approval = fake_request_approval
    guarded_server.approval = mock_approval

    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        with pytest.raises(Exception, match="timed out|timeout"):
            await client.call_tool(
                "dummy__echo_gated", {"message": "test"}
            )


async def test_trust_elevation_grants_future_bypass(guarded_server):
    await guarded_server.start()

    call_count = 0

    async def fake_request_approval(req: ApprovalRequest) -> ApprovalStatus:
        nonlocal call_count
        call_count += 1
        req.status = ApprovalStatus.APPROVED
        req.trust_elevated = True
        return ApprovalStatus.APPROVED

    mock_approval = AsyncMock()
    mock_approval.request_approval = fake_request_approval
    guarded_server.approval = mock_approval

    async with Client(FastMCPTransport(guarded_server.mcp)) as client:
        # First call: goes through approval, trust_elevated=True → grant_trust
        await client.call_tool(
            "dummy__echo_gated", {"message": "first"}
        )
        assert call_count == 1

        # Second call: policy should auto-approve (trusted), no approval needed
        result2 = await client.call_tool(
            "dummy__echo_gated", {"message": "second"}
        )
        assert call_count == 1  # approval was NOT called again
        assert any("second" in str(c.text) for c in result2.content)


async def test_domain_allowlist_bypasses_approval():
    config = ServerConfig(
        telegram=TelegramConfig(chat_id=0),
        policy=PolicyConfig(auto_approve_reads=False),
        integrations={
            "dummy": IntegrationConfig(
                tools={
                    "dummy__echo_gated": ToolConfig(
                        requires_approval=True,
                        auto_approve_domains=["allowed.com"],
                    ),
                }
            )
        },
    )
    server = GuardedMCPServer(config)
    server.register_integration(DummyIntegration())
    await server.start()

    # No approval engine — if it tries to approve, it will error.
    assert server.approval is None

    async with Client(FastMCPTransport(server.mcp)) as client:
        # Should auto-approve via domain allowlist, no approval engine needed
        result = await client.call_tool(
            "dummy__echo_gated",
            {"message": "hi", "to": "user@allowed.com"},
        )
        assert any("hi" in str(c.text) for c in result.content)
