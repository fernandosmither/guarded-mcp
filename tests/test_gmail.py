"""Tests for GmailIntegration with mocked Google API."""

from unittest.mock import MagicMock

import pytest

from src.integrations.gmail import GmailIntegration


@pytest.fixture
def mock_auth():
    return MagicMock()


@pytest.fixture
def gmail(mock_auth):
    return GmailIntegration(mock_auth)


def test_tools_returns_six_tools(gmail):
    tools = gmail.tools()
    assert len(tools) == 6
    names = {t.name for t in tools}
    assert names == {
        "search_emails", "read_email", "send_email",
        "reply_to_email", "modify_email", "list_labels",
    }


def test_read_only_tools_marked_correctly(gmail):
    tools = {t.name: t for t in gmail.tools()}
    assert tools["search_emails"].read_only is True
    assert tools["read_email"].read_only is True
    assert tools["list_labels"].read_only is True
    assert tools["send_email"].read_only is False
    assert tools["reply_to_email"].read_only is False
    assert tools["modify_email"].read_only is False


def test_all_tools_have_account_param(gmail):
    for tool in gmail.tools():
        props = tool.input_schema.get("properties", {})
        assert "account" in props, f"{tool.name} missing account param"
        assert "account" in tool.input_schema.get("required", [])


async def test_search_emails(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1", "threadId": "t1"}]
    }
    mock_svc.users().messages().get().execute.return_value = {
        "id": "msg1",
        "payload": {
            "headers": [
                {"name": "From", "value": "alice@test.com"},
                {"name": "To", "value": "me@test.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Date", "value": "2026-04-03"},
            ]
        },
        "snippet": "Hi there",
    }

    result = await gmail.execute(
        "search_emails", {"account": "work", "query": "from:alice"},
    )
    assert len(result) == 1
    assert result[0]["id"] == "msg1"
    assert result[0]["subject"] == "Hello"


async def test_send_email(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().messages().send().execute.return_value = {
        "id": "sent1", "threadId": "t1",
    }

    result = await gmail.execute("send_email", {
        "account": "work",
        "to": "bob@test.com",
        "subject": "Test",
        "body": "Hello Bob",
    })
    assert result["id"] == "sent1"


async def test_list_labels(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().labels().list().execute.return_value = {
        "labels": [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "Label_1", "name": "Work", "type": "user"},
        ]
    }

    result = await gmail.execute("list_labels", {"account": "work"})
    assert len(result) == 2
    assert result[0]["name"] == "INBOX"


async def test_modify_email(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().messages().modify().execute.return_value = {"id": "msg1"}

    result = await gmail.execute("modify_email", {
        "account": "work",
        "message_id": "msg1",
        "add_labels": ["TRASH"],
        "remove_labels": ["INBOX"],
    })
    assert result["id"] == "msg1"
