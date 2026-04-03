"""E2e tests for Google integrations via FastMCPTransport."""

from unittest.mock import MagicMock

import pytest
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport

from src.auth import GoogleAuthManager
from src.integrations.calendar import CalendarIntegration
from src.integrations.gmail import GmailIntegration
from src.models import (
    IntegrationConfig,
    PolicyConfig,
    ServerConfig,
    TelegramConfig,
)
from src.server import GuardedMCPServer


@pytest.fixture
def mock_auth():
    auth = MagicMock(spec=GoogleAuthManager)
    mock_svc = MagicMock()
    auth.build_service.return_value = mock_svc
    # Gmail defaults
    mock_svc.users().messages().list().execute.return_value = {
        "messages": []
    }
    mock_svc.users().labels().list().execute.return_value = {
        "labels": []
    }
    # Calendar defaults
    mock_svc.events().list().execute.return_value = {"items": []}
    mock_svc.calendarList().list().execute.return_value = {
        "items": []
    }
    return auth


@pytest.fixture
def google_server(mock_auth):
    config = ServerConfig(
        telegram=TelegramConfig(chat_id=0),
        policy=PolicyConfig(auto_approve_reads=True),
        integrations={
            "gmail": IntegrationConfig(tools={}),
            "calendar": IntegrationConfig(tools={}),
        },
    )
    server = GuardedMCPServer(config)
    server.register_integration(GmailIntegration(mock_auth))
    server.register_integration(CalendarIntegration(mock_auth))
    return server


async def test_gmail_tools_registered(google_server):
    await google_server.start()
    async with Client(
        FastMCPTransport(google_server.mcp)
    ) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "gmail__search_emails" in names
        assert "gmail__send_email" in names
        assert "gmail__list_labels" in names


async def test_calendar_tools_registered(google_server):
    await google_server.start()
    async with Client(
        FastMCPTransport(google_server.mcp)
    ) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "calendar__list_events" in names
        assert "calendar__create_event" in names
        assert "calendar__list_calendars" in names


async def test_gmail_read_tool_auto_approved(google_server):
    await google_server.start()
    async with Client(
        FastMCPTransport(google_server.mcp)
    ) as client:
        result = await client.call_tool(
            "gmail__list_labels", {"account": "work"}
        )
        assert result is not None


async def test_calendar_read_tool_auto_approved(google_server):
    await google_server.start()
    async with Client(
        FastMCPTransport(google_server.mcp)
    ) as client:
        result = await client.call_tool(
            "calendar__list_events",
            {
                "account": "work",
                "time_min": "2026-04-03T00:00:00Z",
                "time_max": "2026-04-04T00:00:00Z",
            },
        )
        assert result is not None


async def test_gmail_write_tool_requires_approval(google_server):
    await google_server.start()
    assert google_server.approval is None
    async with Client(
        FastMCPTransport(google_server.mcp)
    ) as client:
        with pytest.raises(Exception, match="approval"):
            await client.call_tool("gmail__send_email", {
                "account": "work",
                "to": "test@test.com",
                "subject": "Hi",
                "body": "Hello",
            })


async def test_calendar_write_tool_requires_approval(google_server):
    await google_server.start()
    assert google_server.approval is None
    async with Client(
        FastMCPTransport(google_server.mcp)
    ) as client:
        with pytest.raises(Exception, match="approval"):
            await client.call_tool("calendar__create_event", {
                "account": "work",
                "summary": "Test",
                "start": "2026-04-03T10:00:00Z",
                "end": "2026-04-03T11:00:00Z",
            })
