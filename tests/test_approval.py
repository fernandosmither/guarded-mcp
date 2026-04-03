"""Tests for ApprovalEngine with mocked Telegram API."""

import asyncio

import httpx
import respx

from src.approval import ApprovalEngine
from src.models import ApprovalRequest, ApprovalStatus

BOT_TOKEN = "test-token-123"
CHAT_ID = 999
USER_ID = 42
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _make_engine(**kwargs) -> ApprovalEngine:
    """Create an ApprovalEngine. Tests must mock HTTP via respx."""
    return ApprovalEngine(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        allowed_user_ids=[USER_ID],
        timeout_seconds=kwargs.get("timeout_seconds", 300),
    )


# --- Message formatting (no HTTP needed) ---


def test_format_message_contains_tool_name():
    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="gmail__send_email",
        integration="gmail",
        arguments={"to": "a@b.com"},
    )
    text = engine._format_approval_message(req)
    assert "gmail__send_email" in text


def test_format_message_contains_hash():
    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={"x": 1}
    )
    text = engine._format_approval_message(req)
    assert req.params_hash[:16] in text


def test_format_message_escapes_html():
    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t",
        integration="i",
        arguments={"payload": "<script>alert('xss')</script>"},
    )
    text = engine._format_approval_message(req)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_format_message_long_args_uses_blockquote():
    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t",
        integration="i",
        arguments={"data": "x" * 600},
    )
    text = engine._format_approval_message(req)
    assert "<blockquote expandable>" in text


# --- Send approval message ---


@respx.mock
async def test_send_approval_message():
    respx.post(f"{BASE_URL}/sendMessage").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"message_id": 456}}
        )
    )
    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="test__tool", integration="test", arguments={"a": 1}
    )
    msg_id = await engine._send_approval_message(req)
    assert msg_id == 456


# --- Callback handling ---


@respx.mock
async def test_handle_callback_approve():
    respx.post(f"{BASE_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post(f"{BASE_URL}/editMessageText").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={"k": "v"}
    )
    event = asyncio.Event()
    engine._pending[req.nonce] = req
    engine._events[req.nonce] = event

    await engine._handle_callback({
        "id": "cb1",
        "from": {"id": USER_ID},
        "data": f"approve:{req.nonce}",
    })

    assert req.status == ApprovalStatus.APPROVED
    assert req.trust_elevated is False
    assert event.is_set()


@respx.mock
async def test_handle_callback_reject():
    respx.post(f"{BASE_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post(f"{BASE_URL}/editMessageText").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={"k": "v"}
    )
    event = asyncio.Event()
    engine._pending[req.nonce] = req
    engine._events[req.nonce] = event

    await engine._handle_callback({
        "id": "cb1",
        "from": {"id": USER_ID},
        "data": f"reject:{req.nonce}",
    })

    assert req.status == ApprovalStatus.REJECTED
    assert event.is_set()


@respx.mock
async def test_handle_callback_trust():
    respx.post(f"{BASE_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post(f"{BASE_URL}/editMessageText").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={"k": "v"}
    )
    event = asyncio.Event()
    engine._pending[req.nonce] = req
    engine._events[req.nonce] = event

    await engine._handle_callback({
        "id": "cb1",
        "from": {"id": USER_ID},
        "data": f"trust:{req.nonce}",
    })

    assert req.status == ApprovalStatus.APPROVED
    assert req.trust_elevated is True
    assert event.is_set()


@respx.mock
async def test_handle_callback_unauthorized_user():
    respx.post(f"{BASE_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={}
    )
    engine._pending[req.nonce] = req
    engine._events[req.nonce] = asyncio.Event()

    await engine._handle_callback({
        "id": "cb1",
        "from": {"id": 99999},  # not in allowed_user_ids
        "data": f"approve:{req.nonce}",
    })

    assert req.status == ApprovalStatus.PENDING  # unchanged


@respx.mock
async def test_handle_callback_unknown_nonce():
    respx.post(f"{BASE_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine()
    # Should not raise — just answers "expired or already handled"
    await engine._handle_callback({
        "id": "cb1",
        "from": {"id": USER_ID},
        "data": "approve:nonexistent_nonce",
    })


@respx.mock
async def test_handle_callback_hash_verification_failure():
    respx.post(f"{BASE_URL}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine()
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={"k": "v"}
    )
    engine._pending[req.nonce] = req
    engine._events[req.nonce] = asyncio.Event()
    # Tamper with arguments after storing
    req.arguments["k"] = "tampered"

    await engine._handle_callback({
        "id": "cb1",
        "from": {"id": USER_ID},
        "data": f"approve:{req.nonce}",
    })

    assert req.status == ApprovalStatus.PENDING  # unchanged, security check failed


@respx.mock
async def test_request_approval_timeout():
    respx.post(f"{BASE_URL}/sendMessage").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"message_id": 1}}
        )
    )
    respx.post(f"{BASE_URL}/editMessageText").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    engine = _make_engine(timeout_seconds=1)
    req = ApprovalRequest(
        tool_name="t", integration="i", arguments={}
    )
    status = await engine.request_approval(req)
    assert status == ApprovalStatus.EXPIRED


@respx.mock
async def test_start_stop_lifecycle():
    respx.get(f"{BASE_URL}/getUpdates").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": []})
    )

    engine = _make_engine()
    await engine.start()
    assert engine._polling_task is not None
    assert not engine._polling_task.done()

    await engine.stop()
    assert engine._polling_task.done()
