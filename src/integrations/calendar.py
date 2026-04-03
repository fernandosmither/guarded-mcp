"""Google Calendar integration for guarded-mcp.

Provides tools to list, create, update, and delete calendar events,
as well as listing available calendars. All Google API calls are
executed in a thread pool to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.integrations.base import Integration, ToolDef


class CalendarIntegration(Integration):
    """Integration with the Google Calendar API.

    Requires a ``GoogleAuthManager`` (or compatible mock) that provides
    ``build_service(account, api, version)`` returning a Google API
    service resource.
    """

    name = "calendar"

    def __init__(self, auth: Any) -> None:
        self._auth = auth

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="list_events",
                description="List calendar events within a time range.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Google account alias.",
                        },
                        "time_min": {
                            "type": "string",
                            "description": (
                                "Start of time range (RFC 3339, e.g. "
                                "2026-04-03T00:00:00Z)."
                            ),
                        },
                        "time_max": {
                            "type": "string",
                            "description": (
                                "End of time range (RFC 3339, e.g. "
                                "2026-04-04T00:00:00Z)."
                            ),
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (default: primary).",
                            "default": "primary",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": (
                                "Maximum number of events to return "
                                "(default: 20)."
                            ),
                            "default": 20,
                        },
                    },
                    "required": ["account", "time_min", "time_max"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="get_event",
                description="Get a single calendar event by ID.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Google account alias.",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "The event ID to retrieve.",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (default: primary).",
                            "default": "primary",
                        },
                    },
                    "required": ["account", "event_id"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="create_event",
                description="Create a new calendar event.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Google account alias.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Event title.",
                        },
                        "start": {
                            "type": "string",
                            "description": (
                                "Start time (RFC 3339, e.g. "
                                "2026-04-03T12:00:00Z)."
                            ),
                        },
                        "end": {
                            "type": "string",
                            "description": (
                                "End time (RFC 3339, e.g. "
                                "2026-04-03T13:00:00Z)."
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Event location.",
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of attendee email addresses."
                            ),
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (default: primary).",
                            "default": "primary",
                        },
                    },
                    "required": ["account", "summary", "start", "end"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="update_event",
                description="Update an existing calendar event (patch semantics).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Google account alias.",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "The event ID to update.",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (default: primary).",
                            "default": "primary",
                        },
                        "summary": {
                            "type": "string",
                            "description": "New event title.",
                        },
                        "start": {
                            "type": "string",
                            "description": "New start time (RFC 3339).",
                        },
                        "end": {
                            "type": "string",
                            "description": "New end time (RFC 3339).",
                        },
                        "description": {
                            "type": "string",
                            "description": "New event description.",
                        },
                        "location": {
                            "type": "string",
                            "description": "New event location.",
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "New list of attendee email addresses."
                            ),
                        },
                    },
                    "required": ["account", "event_id"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="delete_event",
                description="Delete a calendar event.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Google account alias.",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "The event ID to delete.",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID (default: primary).",
                            "default": "primary",
                        },
                    },
                    "required": ["account", "event_id"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="list_calendars",
                description="List all calendars available to the account.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Google account alias.",
                        },
                    },
                    "required": ["account"],
                },
                read_only=True,
                requires_approval=False,
            ),
        ]

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        args = dict(arguments)
        account = args.pop("account")
        service = self._auth.build_service(account, "calendar", "v3")

        dispatch = {
            "list_events": self._list_events,
            "get_event": self._get_event,
            "create_event": self._create_event,
            "update_event": self._update_event,
            "delete_event": self._delete_event,
            "list_calendars": self._list_calendars,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        return await handler(service, args)

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    async def _list_events(
        self, service: Any, args: dict
    ) -> list[dict[str, Any]]:
        calendar_id = args.get("calendar_id", "primary")
        time_min = args["time_min"]
        time_max = args["time_max"]
        max_results = args.get("max_results", 20)

        response = await asyncio.to_thread(
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute
        )

        return [
            {
                "id": evt.get("id"),
                "summary": evt.get("summary"),
                "start": evt.get("start"),
                "end": evt.get("end"),
                "location": evt.get("location"),
                "attendees": evt.get("attendees"),
                "status": evt.get("status"),
            }
            for evt in response.get("items", [])
        ]

    async def _get_event(
        self, service: Any, args: dict
    ) -> dict[str, Any]:
        calendar_id = args.get("calendar_id", "primary")
        event_id = args["event_id"]

        return await asyncio.to_thread(
            service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute
        )

    async def _create_event(
        self, service: Any, args: dict
    ) -> dict[str, Any]:
        calendar_id = args.get("calendar_id", "primary")

        body: dict[str, Any] = {
            "summary": args["summary"],
            "start": {"dateTime": args["start"]},
            "end": {"dateTime": args["end"]},
        }

        if "description" in args:
            body["description"] = args["description"]
        if "location" in args:
            body["location"] = args["location"]
        if "attendees" in args:
            body["attendees"] = [
                {"email": email} for email in args["attendees"]
            ]

        return await asyncio.to_thread(
            service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute
        )

    async def _update_event(
        self, service: Any, args: dict
    ) -> dict[str, Any]:
        calendar_id = args.get("calendar_id", "primary")
        event_id = args["event_id"]

        body: dict[str, Any] = {}
        if "summary" in args:
            body["summary"] = args["summary"]
        if "start" in args:
            body["start"] = {"dateTime": args["start"]}
        if "end" in args:
            body["end"] = {"dateTime": args["end"]}
        if "description" in args:
            body["description"] = args["description"]
        if "location" in args:
            body["location"] = args["location"]
        if "attendees" in args:
            body["attendees"] = [
                {"email": email} for email in args["attendees"]
            ]

        return await asyncio.to_thread(
            service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=body)
            .execute
        )

    async def _delete_event(
        self, service: Any, args: dict
    ) -> dict[str, Any]:
        calendar_id = args.get("calendar_id", "primary")
        event_id = args["event_id"]

        await asyncio.to_thread(
            service.events()
            .delete(calendarId=calendar_id, eventId=event_id)
            .execute
        )

        return {"event_id": event_id, "status": "deleted"}

    async def _list_calendars(
        self, service: Any, args: dict
    ) -> list[dict[str, Any]]:
        response = await asyncio.to_thread(
            service.calendarList().list().execute
        )

        return [
            {
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "primary": cal.get("primary", False),
                "accessRole": cal.get("accessRole"),
            }
            for cal in response.get("items", [])
        ]
