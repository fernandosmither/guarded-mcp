"""Telegram-based approval engine for gated tool calls.

Sends approval requests as Telegram messages with inline keyboards.
Polls for callback query responses. Validates user_id and nonce.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time

import httpx

from src.models import ApprovalRequest, ApprovalStatus

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, max_len: int = 800) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


class ApprovalEngine:
    """Manages approval requests via Telegram inline keyboards."""

    def __init__(
        self,
        bot_token: str,
        chat_id: int,
        allowed_user_ids: list[int],
        timeout_seconds: int = 300,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.allowed_user_ids = allowed_user_ids
        self.timeout_seconds = timeout_seconds
        self._pending: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._client = http_client or httpx.AsyncClient(timeout=30)
        self._owns_client = http_client is None
        self._polling_task: asyncio.Task | None = None
        self._last_update_id = 0

    @classmethod
    def from_config(cls, telegram_config: dict, timeout: int = 300) -> ApprovalEngine:
        token_env = telegram_config.get("bot_token_env", "APPROVAL_BOT_TOKEN")
        token = os.environ.get(token_env, "")
        if not token:
            raise ValueError(f"Missing env var: {token_env}")
        return cls(
            bot_token=token,
            chat_id=telegram_config["chat_id"],
            allowed_user_ids=telegram_config.get("allowed_user_ids", []),
            timeout_seconds=timeout,
        )

    async def start(self) -> None:
        """Start the callback polling loop."""
        if self._polling_task is None or self._polling_task.done():
            self._polling_task = asyncio.create_task(self._poll_callbacks())
            logger.info("Approval engine started (polling for callbacks)")

    async def stop(self) -> None:
        """Stop the callback polling loop."""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._polling_task
        if self._owns_client:
            await self._client.aclose()

    async def request_approval(self, request: ApprovalRequest) -> ApprovalStatus:
        """Send an approval request to Telegram and wait for response.

        Blocks until the user approves, rejects, or the request times out.
        Returns the final status.
        """
        event = asyncio.Event()
        self._pending[request.nonce] = request
        self._events[request.nonce] = event

        try:
            msg_id = await self._send_approval_message(request)
            request.telegram_message_id = msg_id

            try:
                await asyncio.wait_for(event.wait(), timeout=self.timeout_seconds)
            except TimeoutError:
                request.status = ApprovalStatus.EXPIRED
                request.resolved_at = time.time()
                await self._update_message_expired(request)
                logger.info(
                    "Approval expired: %s/%s", request.integration, request.tool_name
                )

            return request.status
        finally:
            self._pending.pop(request.nonce, None)
            self._events.pop(request.nonce, None)

    def _format_approval_message(self, req: ApprovalRequest) -> str:
        """Format the approval message using raw parameters only.

        Never includes agent-supplied descriptions or summaries.
        """
        args_display = json.dumps(req.arguments, indent=2, ensure_ascii=False)
        args_escaped = _escape_html(args_display)

        lines = [
            "\U0001f512 <b>APPROVAL REQUEST</b>",
            "",
            f"<b>Action:</b> <code>{_escape_html(req.tool_name)}</code>",
            f"<b>Integration:</b> {_escape_html(req.integration)}",
            "",
            "\u2501" * 20,
            "",
        ]

        if len(args_escaped) > 500:
            lines.append(
                f"<blockquote expandable>{args_escaped}</blockquote>"
            )
        else:
            lines.append(f"<pre>{args_escaped}</pre>")

        lines.extend([
            "",
            "\u2501" * 20,
            f"<i>Expires in {self.timeout_seconds // 60}"
            f":{self.timeout_seconds % 60:02d}</i>",
            f"<i>Hash: {req.params_hash[:16]}...</i>",
        ])

        return "\n".join(lines)

    async def _send_approval_message(self, req: ApprovalRequest) -> int:
        """Send the approval message to Telegram with inline keyboard."""
        text = self._format_approval_message(req)

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "\u2713 Approve",
                        "callback_data": f"approve:{req.nonce}",
                    },
                    {
                        "text": "\u2717 Reject",
                        "callback_data": f"reject:{req.nonce}",
                    },
                ],
                [
                    {
                        "text": "\U0001f513 Trust 30min",
                        "callback_data": f"trust:{req.nonce}",
                    },
                ],
            ]
        }

        url = TELEGRAM_API.format(token=self.bot_token) + "/sendMessage"
        resp = await self._client.post(url, json={
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        })
        data = resp.json()
        if not data.get("ok"):
            logger.error("Failed to send approval message: %s", data)
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

        msg_id = data["result"]["message_id"]
        logger.info(
            "Approval request sent: %s/%s (msg_id=%d, nonce=%s)",
            req.integration,
            req.tool_name,
            msg_id,
            req.nonce[:8],
        )
        return msg_id

    async def _poll_callbacks(self) -> None:
        """Long-poll Telegram for callback query updates."""
        url = TELEGRAM_API.format(token=self.bot_token) + "/getUpdates"

        while True:
            try:
                resp = await self._client.get(url, params={
                    "offset": self._last_update_id + 1,
                    "timeout": 30,
                    "allowed_updates": json.dumps(["callback_query"]),
                })
                data = resp.json()

                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    callback = update.get("callback_query")
                    if callback:
                        await self._handle_callback(callback)

            except httpx.TimeoutException:
                continue
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Error polling Telegram callbacks")
                await asyncio.sleep(5)

    async def _handle_callback(self, callback: dict) -> None:
        """Process a callback query from Telegram."""
        callback_id = callback["id"]
        user_id = callback["from"]["id"]
        data = callback.get("data", "")

        if user_id not in self.allowed_user_ids:
            logger.warning("Callback from unauthorized user: %d", user_id)
            await self._answer_callback(callback_id, "Unauthorized", show_alert=True)
            return

        parts = data.split(":", 1)
        if len(parts) != 2:
            await self._answer_callback(callback_id, "Invalid callback")
            return

        action, nonce = parts

        request = self._pending.get(nonce)
        if request is None:
            await self._answer_callback(
                callback_id, "Request expired or already handled", show_alert=True
            )
            return

        if not request.verify_hash():
            logger.error("Hash verification failed for nonce %s", nonce[:8])
            await self._answer_callback(
                callback_id, "Security check failed", show_alert=True
            )
            return

        event = self._events.get(nonce)

        log_ctx = (request.integration, request.tool_name, user_id)

        if action == "approve":
            request.status = ApprovalStatus.APPROVED
            request.resolved_at = time.time()
            await self._answer_callback(callback_id, "Approved")
            await self._update_message_resolved(
                request, "APPROVED \u2713"
            )
            logger.info("Approved: %s/%s by user %d", *log_ctx)
        elif action == "reject":
            request.status = ApprovalStatus.REJECTED
            request.resolved_at = time.time()
            await self._answer_callback(callback_id, "Rejected")
            await self._update_message_resolved(
                request, "REJECTED \u2717"
            )
            logger.info("Rejected: %s/%s by user %d", *log_ctx)
        elif action == "trust":
            request.status = ApprovalStatus.APPROVED
            request.trust_elevated = True
            request.resolved_at = time.time()
            await self._answer_callback(
                callback_id, "Approved + trusted for 30min"
            )
            await self._update_message_resolved(
                request, "APPROVED + TRUSTED 30min \U0001f513"
            )
            logger.info(
                "Trust-approved: %s/%s by user %d", *log_ctx
            )
        else:
            await self._answer_callback(callback_id, "Unknown action")
            return

        if event:
            event.set()

    async def _answer_callback(
        self, callback_id: str, text: str, show_alert: bool = False
    ) -> None:
        url = TELEGRAM_API.format(token=self.bot_token) + "/answerCallbackQuery"
        await self._client.post(url, json={
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": show_alert,
        })

    async def _update_message_resolved(
        self, req: ApprovalRequest, status_text: str
    ) -> None:
        """Edit the approval message to show the decision and remove buttons."""
        if req.telegram_message_id is None:
            return

        elapsed = (req.resolved_at or time.time()) - req.created_at
        text = (
            f"\U0001f512 <b>{status_text}</b>\n\n"
            f"<b>Action:</b> <code>{_escape_html(req.tool_name)}</code>\n"
            f"<b>Integration:</b> {_escape_html(req.integration)}\n"
            f"<i>Resolved in {elapsed:.0f}s</i>"
        )

        url = TELEGRAM_API.format(token=self.bot_token) + "/editMessageText"
        await self._client.post(url, json={
            "chat_id": self.chat_id,
            "message_id": req.telegram_message_id,
            "text": text,
            "parse_mode": "HTML",
        })

    async def _update_message_expired(self, req: ApprovalRequest) -> None:
        """Edit the approval message to show expiry and remove buttons."""
        await self._update_message_resolved(req, "EXPIRED \u23f0")
