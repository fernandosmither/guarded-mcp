"""Tests for CalendarIntegration with mocked Google API."""

from unittest.mock import MagicMock

import pytest

from src.integrations.calendar import CalendarIntegration


@pytest.fixture
def mock_auth():
    return MagicMock()


@pytest.fixture
def cal(mock_auth):
    return CalendarIntegration(mock_auth)


def test_tools_returns_six_tools(cal):
    tools = cal.tools()
    assert len(tools) == 6
    names = {t.name for t in tools}
    assert names == {
        "list_events", "get_event", "create_event",
        "update_event", "delete_event", "list_calendars",
    }


def test_read_only_tools_marked_correctly(cal):
    tools = {t.name: t for t in cal.tools()}
    assert tools["list_events"].read_only is True
    assert tools["get_event"].read_only is True
    assert tools["list_calendars"].read_only is True
    assert tools["create_event"].read_only is False
    assert tools["update_event"].read_only is False
    assert tools["delete_event"].read_only is False


def test_all_tools_have_account_param(cal):
    for tool in cal.tools():
        props = tool.input_schema.get("properties", {})
        assert "account" in props, f"{tool.name} missing account"
        assert "account" in tool.input_schema.get("required", [])


async def test_list_events(cal, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.events().list().execute.return_value = {
        "items": [{
            "id": "evt1",
            "summary": "Meeting",
            "start": {"dateTime": "2026-04-03T10:00:00Z"},
            "end": {"dateTime": "2026-04-03T11:00:00Z"},
            "status": "confirmed",
        }]
    }

    result = await cal.execute("list_events", {
        "account": "work",
        "time_min": "2026-04-03T00:00:00Z",
        "time_max": "2026-04-04T00:00:00Z",
    })
    assert len(result) == 1
    assert result[0]["summary"] == "Meeting"


async def test_create_event(cal, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.events().insert().execute.return_value = {
        "id": "new_evt", "summary": "Lunch",
    }

    result = await cal.execute("create_event", {
        "account": "work",
        "summary": "Lunch",
        "start": "2026-04-03T12:00:00Z",
        "end": "2026-04-03T13:00:00Z",
    })
    assert result["id"] == "new_evt"


async def test_delete_event(cal, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.events().delete().execute.return_value = ""

    result = await cal.execute("delete_event", {
        "account": "work", "event_id": "evt1",
    })
    assert result["status"] == "deleted"


async def test_list_calendars(cal, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.calendarList().list().execute.return_value = {
        "items": [{
            "id": "primary",
            "summary": "Main",
            "primary": True,
            "accessRole": "owner",
        }]
    }

    result = await cal.execute("list_calendars", {"account": "work"})
    assert len(result) == 1
    assert result[0]["id"] == "primary"
