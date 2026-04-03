"""Gmail integration for guarded-mcp.

Provides tools for searching, reading, sending, replying, modifying emails,
and listing labels. All operations use a multi-account GoogleAuthManager
to obtain service objects per account.
"""

from __future__ import annotations

import asyncio
import base64
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any

from src.integrations.base import Integration, ToolDef

if TYPE_CHECKING:
    pass


class GmailIntegration(Integration):
    """Gmail API integration with multi-account support."""

    name = "gmail"

    def __init__(self, auth: Any) -> None:
        self._auth = auth

    def tools(self) -> list[ToolDef]:
        """Return the six Gmail tools."""
        account_prop = {
            "type": "string",
            "description": "Account alias to use (e.g. 'work', 'personal').",
        }

        return [
            ToolDef(
                name="search_emails",
                description="Search emails using Gmail query syntax.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": account_prop,
                        "query": {
                            "type": "string",
                            "description": "Gmail search query (e.g. 'from:alice').",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return.",
                            "default": 10,
                        },
                    },
                    "required": ["account", "query"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="read_email",
                description="Read a single email by message ID.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": account_prop,
                        "message_id": {
                            "type": "string",
                            "description": "The Gmail message ID.",
                        },
                    },
                    "required": ["account", "message_id"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="send_email",
                description="Compose and send a new email.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": account_prop,
                        "to": {
                            "type": "string",
                            "description": "Recipient email address.",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject line.",
                        },
                        "body": {
                            "type": "string",
                            "description": "Plain text email body.",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients (comma-separated).",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients (comma-separated).",
                        },
                    },
                    "required": ["account", "to", "subject", "body"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="reply_to_email",
                description="Reply to an existing email thread.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": account_prop,
                        "message_id": {
                            "type": "string",
                            "description": "The message ID to reply to.",
                        },
                        "body": {
                            "type": "string",
                            "description": "Plain text reply body.",
                        },
                    },
                    "required": ["account", "message_id", "body"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="modify_email",
                description="Add or remove labels from an email.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": account_prop,
                        "message_id": {
                            "type": "string",
                            "description": "The message ID to modify.",
                        },
                        "add_labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Label IDs to add.",
                        },
                        "remove_labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Label IDs to remove.",
                        },
                    },
                    "required": ["account", "message_id"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="list_labels",
                description="List all labels in the Gmail account.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": account_prop,
                    },
                    "required": ["account"],
                },
                read_only=True,
                requires_approval=False,
            ),
        ]

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        """Dispatch tool execution to the appropriate private method."""
        args = dict(arguments)
        account = args.pop("account")
        service = self._auth.build_service(account, "gmail", "v1")

        dispatch = {
            "search_emails": self._search_emails,
            "read_email": self._read_email,
            "send_email": self._send_email,
            "reply_to_email": self._reply_to_email,
            "modify_email": self._modify_email,
            "list_labels": self._list_labels,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        return await handler(service, **args)

    # ------------------------------------------------------------------
    # Private methods -- one per tool
    # ------------------------------------------------------------------

    async def _search_emails(
        self, service: Any, *, query: str, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Search for emails and return metadata summaries."""
        response = await asyncio.to_thread(
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute
        )

        messages = response.get("messages", [])
        results: list[dict[str, Any]] = []

        for msg_stub in messages:
            msg = await asyncio.to_thread(
                service.users()
                .messages()
                .get(userId="me", id=msg_stub["id"], format="metadata")
                .execute
            )
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            results.append(
                {
                    "id": msg["id"],
                    "thread_id": msg_stub.get("threadId"),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )

        return results

    async def _read_email(
        self, service: Any, *, message_id: str
    ) -> dict[str, Any]:
        """Read a full email including body and attachments list."""
        msg = await asyncio.to_thread(
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute
        )

        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        body = self._extract_body(msg.get("payload", {}))
        attachments = self._extract_attachments(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
            "attachments": attachments,
            "label_ids": msg.get("labelIds", []),
        }

    async def _send_email(
        self,
        service: Any,
        *,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict[str, Any]:
        """Compose and send an email."""
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        return await asyncio.to_thread(
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute
        )

    async def _reply_to_email(
        self, service: Any, *, message_id: str, body: str
    ) -> dict[str, Any]:
        """Reply to an existing email in the same thread."""
        original = await asyncio.to_thread(
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata")
            .execute
        )

        headers = {
            h["name"]: h["value"]
            for h in original.get("payload", {}).get("headers", [])
        }

        reply = MIMEText(body)
        reply["to"] = headers.get("From", "")
        reply["subject"] = f"Re: {headers.get('Subject', '')}"

        orig_message_id = headers.get("Message-ID", "")
        if orig_message_id:
            reply["In-Reply-To"] = orig_message_id
            reply["References"] = orig_message_id

        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()

        return await asyncio.to_thread(
            service.users()
            .messages()
            .send(
                userId="me",
                body={"raw": raw, "threadId": original.get("threadId")},
            )
            .execute
        )

    async def _modify_email(
        self,
        service: Any,
        *,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add or remove labels from a message."""
        body: dict[str, Any] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        return await asyncio.to_thread(
            service.users()
            .messages()
            .modify(userId="me", id=message_id, body=body)
            .execute
        )

    async def _list_labels(self, service: Any) -> list[dict[str, Any]]:
        """List all labels in the account."""
        response = await asyncio.to_thread(
            service.users().labels().list(userId="me").execute
        )
        return response.get("labels", [])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        """Extract plain text body from MIME payload, falling back to HTML."""
        # Direct body on payload
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode(errors="replace")

        # Walk MIME parts
        parts = payload.get("parts", [])
        plain = ""
        html = ""
        for part in parts:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if mime == "text/plain" and data:
                plain = base64.urlsafe_b64decode(data).decode(errors="replace")
            elif mime == "text/html" and data:
                html = base64.urlsafe_b64decode(data).decode(errors="replace")
            # Recurse into nested multipart
            if part.get("parts"):
                nested = GmailIntegration._extract_body(part)
                if nested:
                    plain = plain or nested

        return plain or html

    @staticmethod
    def _extract_attachments(payload: dict[str, Any]) -> list[dict[str, str]]:
        """Return a list of attachment metadata dicts."""
        attachments: list[dict[str, str]] = []
        for part in payload.get("parts", []):
            filename = part.get("filename")
            if filename:
                attachments.append(
                    {
                        "filename": filename,
                        "mime_type": part.get("mimeType", ""),
                        "attachment_id": part.get("body", {}).get(
                            "attachmentId", ""
                        ),
                    }
                )
            if part.get("parts"):
                attachments.extend(
                    GmailIntegration._extract_attachments(part)
                )
        return attachments
