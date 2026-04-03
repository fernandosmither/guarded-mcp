# Gmail & GCal Multi-Account Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gmail and Google Calendar integrations with multi-account support (explicit `account` parameter on every tool), backed by OAuth2 with encrypted token storage.

**Architecture:** A shared `GoogleAuthManager` handles OAuth2 flows, encrypted credential storage, and Google API service construction. `GmailIntegration` and `CalendarIntegration` each take a reference to the auth manager and expose tools with an `account` parameter. All Google API calls use `google-api-python-client` wrapped in `asyncio.to_thread()`.

**Tech Stack:** `google-api-python-client`, `google-auth-oauthlib`, `cryptography` (Fernet), Python 3.12+, pytest, FastMCPTransport for e2e tests.

**Spec:** `docs/superpowers/specs/2026-04-03-gmail-gcal-multi-account-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/models.py` | Modify | Add `GoogleConfig` model |
| `src/auth.py` | Create | `GoogleAuthManager` — credential encryption, loading, refresh, service building |
| `src/auth_cli.py` | Create | CLI for `add`/`remove`/`list` accounts |
| `src/integrations/gmail.py` | Create | `GmailIntegration` — 6 tools |
| `src/integrations/calendar.py` | Create | `CalendarIntegration` — 6 tools |
| `src/server.py` | Modify | Load `GoogleConfig`, create auth manager, auto-register Google integrations |
| `main.py` | Modify | Register Gmail + Calendar integrations |
| `config.toml.example` | Modify | Add `[google]` section + default tool approval rules |
| `pyproject.toml` | Modify | Add google + cryptography deps |
| `.gitignore` | Verify | Already covers `credentials/` and `client_secret*.json` |
| `credentials/.gitkeep` | Create | Ensure dir exists in repo |
| `tests/test_auth.py` | Create | GoogleAuthManager unit tests |
| `tests/test_gmail.py` | Create | GmailIntegration unit tests |
| `tests/test_calendar.py` | Create | CalendarIntegration unit tests |
| `tests/test_server_google.py` | Create | E2e tests for Google integrations via FastMCPTransport |

---

## Task 1: Add Dependencies and GoogleConfig Model

**Files:**
- Modify: `pyproject.toml:8-12`
- Modify: `src/models.py:85-93`
- Modify: `src/server.py:44-62` (load_config)
- Create: `credentials/.gitkeep`

- [ ] **Step 1: Write test for GoogleConfig model**

```python
# tests/test_models.py — append to existing file

from src.models import GoogleConfig


def test_google_config_defaults():
    cfg = GoogleConfig()
    assert cfg.client_secret_path == "credentials/client_secret.json"
    assert cfg.credentials_dir == "credentials"
    assert cfg.secret_env == "GUARDED_MCP_SECRET"
    assert cfg.accounts == []


def test_server_config_includes_google():
    from src.models import ServerConfig
    cfg = ServerConfig()
    assert isinstance(cfg.google, GoogleConfig)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::test_google_config_defaults tests/test_models.py::test_server_config_includes_google -v`
Expected: FAIL — `GoogleConfig` does not exist

- [ ] **Step 3: Add GoogleConfig to models.py**

Add after `TelegramConfig` (after line 82 in `src/models.py`):

```python
class GoogleConfig(BaseModel):
    """Google OAuth2 configuration for multi-account access."""

    client_secret_path: str = "credentials/client_secret.json"
    credentials_dir: str = "credentials"
    secret_env: str = "GUARDED_MCP_SECRET"
    accounts: list[str] = Field(default_factory=list)
```

Add `google` field to `ServerConfig`:

```python
class ServerConfig(BaseModel):
    """Top-level server configuration."""

    host: str = "127.0.0.1"
    port: int = 3100
    approval_timeout_seconds: int = 300
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    integrations: dict[str, IntegrationConfig] = Field(default_factory=dict)
```

- [ ] **Step 4: Update load_config to parse [google] section**

In `src/server.py`, `load_config()`, add before the return statement:

```python
from src.models import GoogleConfig
google = GoogleConfig(**raw.get("google", {}))
```

And include `google=google` in the `ServerConfig(...)` constructor call.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: All PASS

- [ ] **Step 6: Add dependencies to pyproject.toml**

Add to `dependencies` list:

```toml
    "google-api-python-client>=2.100.0",
    "google-auth-oauthlib>=1.0.0",
    "cryptography>=42.0.0",
```

Run: `uv sync`

- [ ] **Step 7: Create credentials/.gitkeep**

```bash
touch credentials/.gitkeep
```

- [ ] **Step 8: Run full test suite and lint**

Run: `uv run pytest -v && uv run ruff check src/ tests/`
Expected: All pass, no lint errors

- [ ] **Step 9: Commit**

```bash
git add src/models.py src/server.py pyproject.toml uv.lock credentials/.gitkeep tests/test_models.py
git commit -m "feat: add GoogleConfig model and Google API dependencies"
```

---

## Task 2: GoogleAuthManager — Encryption and Credential Loading

**Files:**
- Create: `src/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write tests for GoogleAuthManager**

```python
# tests/test_auth.py
"""Tests for GoogleAuthManager credential encryption and loading."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from src.auth import GoogleAuthManager

TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture
def auth_dir(tmp_path):
    """Temp directory with a fake client_secret.json."""
    secret = tmp_path / "client_secret.json"
    secret.write_text(json.dumps({
        "installed": {
            "client_id": "test-id",
            "client_secret": "test-secret",
            "redirect_uris": ["http://localhost"],
        }
    }))
    return tmp_path


@pytest.fixture
def manager(auth_dir):
    return GoogleAuthManager(
        client_secret_path=str(auth_dir / "client_secret.json"),
        credentials_dir=str(auth_dir),
        secret_key=TEST_KEY,
    )


def test_list_accounts_empty(manager):
    assert manager.list_accounts() == []


def test_encrypt_decrypt_roundtrip(manager):
    token_data = {"token": "abc", "refresh_token": "xyz"}
    manager._save_encrypted("test_acct", json.dumps(token_data))

    loaded = json.loads(manager._load_encrypted("test_acct"))
    assert loaded["token"] == "abc"
    assert loaded["refresh_token"] == "xyz"


def test_list_accounts_after_save(manager):
    manager._save_encrypted("work", '{"token": "a"}')
    manager._save_encrypted("personal", '{"token": "b"}')
    accounts = manager.list_accounts()
    assert sorted(accounts) == ["personal", "work"]


def test_remove_account(manager):
    manager._save_encrypted("work", '{"token": "a"}')
    manager.remove_account("work")
    assert manager.list_accounts() == []


def test_remove_nonexistent_account(manager):
    with pytest.raises(ValueError, match="not found"):
        manager.remove_account("nonexistent")


def test_load_encrypted_nonexistent(manager):
    with pytest.raises(ValueError, match="not found"):
        manager._load_encrypted("nonexistent")


def test_get_credentials_loads_and_caches(manager):
    # Create a fake encrypted credential
    fake_creds_json = json.dumps({
        "token": "access_token_123",
        "refresh_token": "refresh_123",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-id",
        "client_secret": "test-secret",
        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
    })
    manager._save_encrypted("work", fake_creds_json)

    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_info"
    ) as mock_from_info:
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_from_info.return_value = mock_creds

        creds = manager.get_credentials("work")
        assert creds is mock_creds
        mock_from_info.assert_called_once()


def test_build_service_calls_discovery(manager):
    fake_creds_json = json.dumps({
        "token": "t",
        "refresh_token": "r",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "id",
        "client_secret": "s",
        "scopes": [],
    })
    manager._save_encrypted("work", fake_creds_json)

    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_info"
    ) as mock_from_info, patch(
        "googleapiclient.discovery.build"
    ) as mock_build:
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_from_info.return_value = mock_creds
        mock_build.return_value = MagicMock()

        svc = manager.build_service("work", "gmail", "v1")
        mock_build.assert_called_once_with(
            "gmail", "v1", credentials=mock_creds
        )
        assert svc is mock_build.return_value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `src.auth` does not exist

- [ ] **Step 3: Implement GoogleAuthManager**

```python
# src/auth.py
"""Google OAuth2 credential management with encrypted storage.

Manages per-account OAuth2 tokens encrypted at rest with Fernet.
Provides credential loading, refresh, and Google API service building.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleAuthManager:
    """Manages OAuth2 credentials for multiple Google accounts."""

    def __init__(
        self,
        client_secret_path: str,
        credentials_dir: str,
        secret_key: str,
    ) -> None:
        self._client_secret_path = Path(client_secret_path)
        self._credentials_dir = Path(credentials_dir)
        self._fernet = Fernet(secret_key.encode())
        self._service_cache: dict[tuple[str, str, str], object] = {}

    def list_accounts(self) -> list[str]:
        """Return aliases of all linked accounts."""
        return sorted(
            p.stem
            for p in self._credentials_dir.glob("*.enc")
        )

    def add_account(self, alias: str) -> str:
        """Run OAuth2 consent flow and save encrypted token.

        Returns the email address of the linked account.
        """
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_secret_path), SCOPES
        )
        creds = flow.run_local_server(port=0)
        self._save_encrypted(alias, creds.to_json())

        # Get email from the token info
        from google.auth.transport.requests import Request

        svc = build("oauth2", "v2", credentials=creds)
        info = svc.userinfo().get().execute()
        return info.get("email", alias)

    def remove_account(self, alias: str) -> None:
        """Delete encrypted credentials for an account."""
        path = self._credentials_dir / f"{alias}.enc"
        if not path.exists():
            raise ValueError(f"Account '{alias}' not found")
        path.unlink()
        # Clear cached services for this account
        self._service_cache = {
            k: v for k, v in self._service_cache.items()
            if k[0] != alias
        }

    def get_credentials(self, alias: str) -> Credentials:
        """Load and return credentials, refreshing if expired."""
        data = json.loads(self._load_encrypted(alias))
        creds = Credentials.from_authorized_user_info(data)

        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            self._save_encrypted(alias, creds.to_json())
            logger.info("Refreshed token for account '%s'", alias)

        return creds

    def build_service(
        self, alias: str, api: str, version: str
    ) -> object:
        """Build a Google API service, caching per (alias, api, version)."""
        key = (alias, api, version)
        if key not in self._service_cache:
            creds = self.get_credentials(alias)
            self._service_cache[key] = build(
                api, version, credentials=creds
            )
        return self._service_cache[key]

    def _save_encrypted(self, alias: str, data: str) -> None:
        """Encrypt and save data to credentials/{alias}.enc."""
        self._credentials_dir.mkdir(parents=True, exist_ok=True)
        path = self._credentials_dir / f"{alias}.enc"
        encrypted = self._fernet.encrypt(data.encode())
        path.write_bytes(encrypted)

    def _load_encrypted(self, alias: str) -> str:
        """Load and decrypt data from credentials/{alias}.enc."""
        path = self._credentials_dir / f"{alias}.enc"
        if not path.exists():
            raise ValueError(f"Account '{alias}' not found")
        encrypted = path.read_bytes()
        return self._fernet.decrypt(encrypted).decode()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: All PASS

- [ ] **Step 5: Lint check**

Run: `uv run ruff check src/auth.py tests/test_auth.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/auth.py tests/test_auth.py
git commit -m "feat: add GoogleAuthManager with encrypted token storage"
```

---

## Task 3: Auth CLI

**Files:**
- Create: `src/auth_cli.py`

- [ ] **Step 1: Implement the CLI module**

```python
# src/auth_cli.py
"""CLI for managing Google OAuth2 accounts.

Usage:
    python -m src.auth_cli add <alias>
    python -m src.auth_cli remove <alias>
    python -m src.auth_cli list
"""

from __future__ import annotations

import argparse
import os
import sys

from src.auth import GoogleAuthManager


def _get_manager() -> GoogleAuthManager:
    secret_key = os.environ.get("GUARDED_MCP_SECRET", "")
    if not secret_key:
        print("Error: GUARDED_MCP_SECRET env var is not set.")
        print("Generate one with:")
        print(
            '  python -c "from cryptography.fernet import Fernet;'
            ' print(Fernet.generate_key().decode())"'
        )
        sys.exit(1)

    return GoogleAuthManager(
        client_secret_path="credentials/client_secret.json",
        credentials_dir="credentials",
        secret_key=secret_key,
    )


def cmd_add(args: argparse.Namespace) -> None:
    manager = _get_manager()
    print(f"Opening browser for Google OAuth...")
    email = manager.add_account(args.alias)
    print(f"Account: {email}")
    print(f"Token saved for account \"{args.alias}\"")


def cmd_remove(args: argparse.Namespace) -> None:
    manager = _get_manager()
    manager.remove_account(args.alias)
    print(f"Account \"{args.alias}\" removed.")


def cmd_list(args: argparse.Namespace) -> None:
    manager = _get_manager()
    accounts = manager.list_accounts()
    if not accounts:
        print("No linked accounts.")
        return
    for alias in accounts:
        print(f"  - {alias}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Google OAuth2 accounts"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Link a Google account")
    add_p.add_argument("alias", help="Account alias (e.g., 'work')")
    add_p.set_defaults(func=cmd_add)

    rm_p = sub.add_parser("remove", help="Unlink an account")
    rm_p.add_argument("alias", help="Account alias to remove")
    rm_p.set_defaults(func=cmd_remove)

    ls_p = sub.add_parser("list", help="List linked accounts")
    ls_p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI parses correctly**

Run: `uv run python -m src.auth_cli --help`
Expected: Shows usage help with add/remove/list commands

- [ ] **Step 3: Lint check**

Run: `uv run ruff check src/auth_cli.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/auth_cli.py
git commit -m "feat: add auth CLI for account management"
```

---

## Task 4: Gmail Integration

**Files:**
- Create: `src/integrations/gmail.py`
- Create: `tests/test_gmail.py`

- [ ] **Step 1: Write tests for GmailIntegration**

```python
# tests/test_gmail.py
"""Tests for GmailIntegration with mocked Google API."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.gmail import GmailIntegration


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    return auth


@pytest.fixture
def gmail(mock_auth):
    return GmailIntegration(mock_auth)


def test_tools_returns_six_tools(gmail):
    tools = gmail.tools()
    assert len(tools) == 6
    names = {t.name for t in tools}
    assert names == {
        "search_emails",
        "read_email",
        "send_email",
        "reply_to_email",
        "modify_email",
        "list_labels",
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
    mock_svc.users().messages().list(
    ).execute.return_value = {
        "messages": [{"id": "msg1", "threadId": "t1"}]
    }
    mock_svc.users().messages().get(
    ).execute.return_value = {
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
        "search_emails",
        {"account": "work", "query": "from:alice"},
    )
    assert len(result) == 1
    assert result[0]["id"] == "msg1"
    assert result[0]["subject"] == "Hello"


async def test_send_email(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().messages().send(
    ).execute.return_value = {"id": "sent1", "threadId": "t1"}

    result = await gmail.execute("send_email", {
        "account": "work",
        "to": "bob@test.com",
        "subject": "Test",
        "body": "Hello Bob",
    })
    assert result["id"] == "sent1"

    # Verify the raw message was passed
    call_args = (
        mock_svc.users().messages().send.call_args
    )
    assert call_args is not None


async def test_list_labels(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().labels().list(
    ).execute.return_value = {
        "labels": [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "Label_1", "name": "Work", "type": "user"},
        ]
    }

    result = await gmail.execute(
        "list_labels", {"account": "work"}
    )
    assert len(result) == 2
    assert result[0]["name"] == "INBOX"


async def test_modify_email(gmail, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.users().messages().modify(
    ).execute.return_value = {"id": "msg1"}

    result = await gmail.execute("modify_email", {
        "account": "work",
        "message_id": "msg1",
        "add_labels": ["TRASH"],
        "remove_labels": ["INBOX"],
    })
    assert result["id"] == "msg1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gmail.py -v`
Expected: FAIL — `src.integrations.gmail` does not exist

- [ ] **Step 3: Implement GmailIntegration**

```python
# src/integrations/gmail.py
"""Gmail integration with multi-account support."""

from __future__ import annotations

import asyncio
import base64
import email.utils
import logging
from email.mime.text import MIMEText
from typing import Any

from src.auth import GoogleAuthManager
from src.integrations.base import Integration, ToolDef

logger = logging.getLogger(__name__)


class GmailIntegration(Integration):
    name = "gmail"

    def __init__(self, auth: GoogleAuthManager) -> None:
        self._auth = auth

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="search_emails",
                description="Search emails by Gmail query string.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "query": {
                            "type": "string",
                            "description": "Gmail search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max emails to return",
                        },
                    },
                    "required": ["account", "query"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="read_email",
                description="Read a full email by message ID.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "message_id": {
                            "type": "string",
                            "description": "Gmail message ID",
                        },
                    },
                    "required": ["account", "message_id"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="send_email",
                description="Send a new email.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "to": {
                            "type": "string",
                            "description": "Recipient email",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject",
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body (plain text)",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients",
                        },
                    },
                    "required": ["account", "to", "subject", "body"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="reply_to_email",
                description=(
                    "Reply to an existing email thread."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "message_id": {
                            "type": "string",
                            "description": "Message ID to reply to",
                        },
                        "body": {
                            "type": "string",
                            "description": "Reply body (plain text)",
                        },
                    },
                    "required": ["account", "message_id", "body"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="modify_email",
                description=(
                    "Modify email labels (archive, trash, "
                    "mark read/unread)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "message_id": {
                            "type": "string",
                            "description": "Gmail message ID",
                        },
                        "add_labels": {
                            "type": "array",
                            "description": "Label IDs to add",
                        },
                        "remove_labels": {
                            "type": "array",
                            "description": "Label IDs to remove",
                        },
                    },
                    "required": ["account", "message_id"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="list_labels",
                description="List all labels for the account.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                    },
                    "required": ["account"],
                },
                read_only=True,
                requires_approval=False,
            ),
        ]

    async def execute(
        self, tool_name: str, arguments: dict
    ) -> Any:
        account = arguments.pop("account")
        svc = self._auth.build_service(account, "gmail", "v1")

        if tool_name == "search_emails":
            return await self._search_emails(svc, **arguments)
        elif tool_name == "read_email":
            return await self._read_email(svc, **arguments)
        elif tool_name == "send_email":
            return await self._send_email(svc, **arguments)
        elif tool_name == "reply_to_email":
            return await self._reply_to_email(
                svc, account, **arguments
            )
        elif tool_name == "modify_email":
            return await self._modify_email(svc, **arguments)
        elif tool_name == "list_labels":
            return await self._list_labels(svc)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def _search_emails(
        self, svc: Any, query: str, max_results: int = 10
    ) -> list[dict]:
        resp = await asyncio.to_thread(
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute
        )
        messages = resp.get("messages", [])
        results = []
        for msg_stub in messages:
            msg = await asyncio.to_thread(
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_stub["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute
            )
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            results.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        return results

    async def _read_email(
        self, svc: Any, message_id: str
    ) -> dict:
        msg = await asyncio.to_thread(
            svc.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute
        )
        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        body = self._extract_body(msg.get("payload", {}))
        attachments = self._list_attachments(
            msg.get("payload", {})
        )
        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
            "attachments": attachments,
            "labels": msg.get("labelIds", []),
        }

    async def _send_email(
        self,
        svc: Any,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict:
        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        raw = base64.urlsafe_b64encode(
            msg.as_bytes()
        ).decode()

        return await asyncio.to_thread(
            svc.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute
        )

    async def _reply_to_email(
        self,
        svc: Any,
        account: str,
        message_id: str,
        body: str,
    ) -> dict:
        original = await asyncio.to_thread(
            svc.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=[
                    "From", "Subject", "Message-ID",
                ],
            )
            .execute
        )
        headers = {
            h["name"]: h["value"]
            for h in original.get("payload", {}).get("headers", [])
        }

        reply_to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        msg_id_header = headers.get("Message-ID", "")
        thread_id = original.get("threadId", "")

        msg = MIMEText(body)
        msg["To"] = reply_to
        msg["Subject"] = subject
        if msg_id_header:
            msg["In-Reply-To"] = msg_id_header
            msg["References"] = msg_id_header

        raw = base64.urlsafe_b64encode(
            msg.as_bytes()
        ).decode()

        return await asyncio.to_thread(
            svc.users()
            .messages()
            .send(
                userId="me",
                body={"raw": raw, "threadId": thread_id},
            )
            .execute
        )

    async def _modify_email(
        self,
        svc: Any,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict:
        body: dict[str, list[str]] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        return await asyncio.to_thread(
            svc.users()
            .messages()
            .modify(userId="me", id=message_id, body=body)
            .execute
        )

    async def _list_labels(self, svc: Any) -> list[dict]:
        resp = await asyncio.to_thread(
            svc.users().labels().list(userId="me").execute
        )
        return [
            {
                "id": lbl["id"],
                "name": lbl["name"],
                "type": lbl.get("type", ""),
            }
            for lbl in resp.get("labels", [])
        ]

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Extract plain text body from a Gmail message payload."""
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode(
                    errors="replace"
                )

        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode(
                        errors="replace"
                    )

        # Fallback: try first text/html and strip tags
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    html = base64.urlsafe_b64decode(data).decode(
                        errors="replace"
                    )
                    import re

                    return re.sub(r"<[^>]+>", "", html)

        return ""

    @staticmethod
    def _list_attachments(payload: dict) -> list[dict]:
        """List attachment names and sizes."""
        attachments = []
        for part in payload.get("parts", []):
            filename = part.get("filename", "")
            if filename:
                attachments.append({
                    "filename": filename,
                    "size": part.get("body", {}).get("size", 0),
                    "mime_type": part.get("mimeType", ""),
                })
        return attachments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gmail.py -v`
Expected: All PASS

- [ ] **Step 5: Lint check**

Run: `uv run ruff check src/integrations/gmail.py tests/test_gmail.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/integrations/gmail.py tests/test_gmail.py
git commit -m "feat: add Gmail integration with multi-account support"
```

---

## Task 5: Calendar Integration

**Files:**
- Create: `src/integrations/calendar.py`
- Create: `tests/test_calendar.py`

- [ ] **Step 1: Write tests for CalendarIntegration**

```python
# tests/test_calendar.py
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
        "list_events",
        "get_event",
        "create_event",
        "update_event",
        "delete_event",
        "list_calendars",
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
        "items": [
            {
                "id": "evt1",
                "summary": "Meeting",
                "start": {"dateTime": "2026-04-03T10:00:00Z"},
                "end": {"dateTime": "2026-04-03T11:00:00Z"},
                "status": "confirmed",
            }
        ]
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
        "id": "new_evt",
        "summary": "Lunch",
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
        "account": "work",
        "event_id": "evt1",
    })
    assert result["status"] == "deleted"


async def test_list_calendars(cal, mock_auth):
    mock_svc = MagicMock()
    mock_auth.build_service.return_value = mock_svc
    mock_svc.calendarList().list().execute.return_value = {
        "items": [
            {
                "id": "primary",
                "summary": "Main",
                "primary": True,
                "accessRole": "owner",
            }
        ]
    }

    result = await cal.execute(
        "list_calendars", {"account": "work"}
    )
    assert len(result) == 1
    assert result[0]["id"] == "primary"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_calendar.py -v`
Expected: FAIL — `src.integrations.calendar` does not exist

- [ ] **Step 3: Implement CalendarIntegration**

```python
# src/integrations/calendar.py
"""Google Calendar integration with multi-account support."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.auth import GoogleAuthManager
from src.integrations.base import Integration, ToolDef

logger = logging.getLogger(__name__)


class CalendarIntegration(Integration):
    name = "calendar"

    def __init__(self, auth: GoogleAuthManager) -> None:
        self._auth = auth

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="list_events",
                description="List calendar events in a time range.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "time_min": {
                            "type": "string",
                            "description": (
                                "Start time (ISO 8601)"
                            ),
                        },
                        "time_max": {
                            "type": "string",
                            "description": "End time (ISO 8601)",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max events to return",
                        },
                    },
                    "required": ["account", "time_min", "time_max"],
                },
                read_only=True,
                requires_approval=False,
            ),
            ToolDef(
                name="get_event",
                description="Get event details by event ID.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "Event ID",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID",
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
                            "description": "Account alias",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Event title",
                        },
                        "start": {
                            "type": "string",
                            "description": (
                                "Start time (ISO 8601)"
                            ),
                        },
                        "end": {
                            "type": "string",
                            "description": "End time (ISO 8601)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description",
                        },
                        "location": {
                            "type": "string",
                            "description": "Event location",
                        },
                        "attendees": {
                            "type": "array",
                            "description": "Attendee emails",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID",
                        },
                    },
                    "required": [
                        "account", "summary", "start", "end",
                    ],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="update_event",
                description="Update an existing calendar event.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "Event ID",
                        },
                        "summary": {
                            "type": "string",
                            "description": "New title",
                        },
                        "start": {
                            "type": "string",
                            "description": "New start time",
                        },
                        "end": {
                            "type": "string",
                            "description": "New end time",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description",
                        },
                        "location": {
                            "type": "string",
                            "description": "New location",
                        },
                        "attendees": {
                            "type": "array",
                            "description": "New attendee emails",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID",
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
                            "description": "Account alias",
                        },
                        "event_id": {
                            "type": "string",
                            "description": "Event ID",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Calendar ID",
                        },
                    },
                    "required": ["account", "event_id"],
                },
                read_only=False,
                requires_approval=True,
            ),
            ToolDef(
                name="list_calendars",
                description="List all calendars for the account.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account alias",
                        },
                    },
                    "required": ["account"],
                },
                read_only=True,
                requires_approval=False,
            ),
        ]

    async def execute(
        self, tool_name: str, arguments: dict
    ) -> Any:
        account = arguments.pop("account")
        svc = self._auth.build_service(
            account, "calendar", "v3"
        )

        if tool_name == "list_events":
            return await self._list_events(svc, **arguments)
        elif tool_name == "get_event":
            return await self._get_event(svc, **arguments)
        elif tool_name == "create_event":
            return await self._create_event(svc, **arguments)
        elif tool_name == "update_event":
            return await self._update_event(svc, **arguments)
        elif tool_name == "delete_event":
            return await self._delete_event(svc, **arguments)
        elif tool_name == "list_calendars":
            return await self._list_calendars(svc)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def _list_events(
        self,
        svc: Any,
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
        max_results: int = 20,
    ) -> list[dict]:
        resp = await asyncio.to_thread(
            svc.events()
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
                "id": evt["id"],
                "summary": evt.get("summary", ""),
                "start": evt.get("start", {}),
                "end": evt.get("end", {}),
                "location": evt.get("location", ""),
                "attendees": [
                    a.get("email", "")
                    for a in evt.get("attendees", [])
                ],
                "status": evt.get("status", ""),
            }
            for evt in resp.get("items", [])
        ]

    async def _get_event(
        self,
        svc: Any,
        event_id: str,
        calendar_id: str = "primary",
    ) -> dict:
        return await asyncio.to_thread(
            svc.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute
        )

    async def _create_event(
        self,
        svc: Any,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        calendar_id: str = "primary",
    ) -> dict:
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [
                {"email": e} for e in attendees
            ]

        return await asyncio.to_thread(
            svc.events()
            .insert(calendarId=calendar_id, body=body)
            .execute
        )

    async def _update_event(
        self,
        svc: Any,
        event_id: str,
        calendar_id: str = "primary",
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if start is not None:
            body["start"] = {"dateTime": start}
        if end is not None:
            body["end"] = {"dateTime": end}
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if attendees is not None:
            body["attendees"] = [
                {"email": e} for e in attendees
            ]

        return await asyncio.to_thread(
            svc.events()
            .patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
            )
            .execute
        )

    async def _delete_event(
        self,
        svc: Any,
        event_id: str,
        calendar_id: str = "primary",
    ) -> dict:
        await asyncio.to_thread(
            svc.events()
            .delete(calendarId=calendar_id, eventId=event_id)
            .execute
        )
        return {"event_id": event_id, "status": "deleted"}

    async def _list_calendars(self, svc: Any) -> list[dict]:
        resp = await asyncio.to_thread(
            svc.calendarList().list().execute
        )
        return [
            {
                "id": cal["id"],
                "summary": cal.get("summary", ""),
                "primary": cal.get("primary", False),
                "accessRole": cal.get("accessRole", ""),
            }
            for cal in resp.get("items", [])
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_calendar.py -v`
Expected: All PASS

- [ ] **Step 5: Lint check**

Run: `uv run ruff check src/integrations/calendar.py tests/test_calendar.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/integrations/calendar.py tests/test_calendar.py
git commit -m "feat: add Calendar integration with multi-account support"
```

---

## Task 6: Wire Up Server and Config

**Files:**
- Modify: `src/server.py:44-62`
- Modify: `main.py`
- Modify: `config.toml.example`

- [ ] **Step 1: Update config.toml.example**

Replace the entire file with:

```toml
# Guarded MCP Server Configuration
# Copy to config.toml and fill in your values.

[server]
host = "127.0.0.1"              # Bind address
port = 3100
approval_timeout_seconds = 300   # 5 minutes

[telegram]
bot_token_env = "APPROVAL_BOT_TOKEN"   # Env var name containing the bot token
chat_id = 0                             # Your Telegram chat ID
allowed_user_ids = []                   # [your_user_id]

[policy]
auto_approve_reads = true               # Read-only tools skip approval
trust_elevation_minutes = 30            # "Trust 30min" button duration

[google]
client_secret_path = "credentials/client_secret.json"
credentials_dir = "credentials"
secret_env = "GUARDED_MCP_SECRET"       # Env var with Fernet encryption key
accounts = []                           # ["work", "personal"]

# Gmail tool overrides (reads are auto-approved by policy)
[integrations.gmail.tools.gmail__send_email]
requires_approval = true

[integrations.gmail.tools.gmail__reply_to_email]
requires_approval = true

[integrations.gmail.tools.gmail__modify_email]
requires_approval = true

# Calendar tool overrides
[integrations.calendar.tools.calendar__create_event]
requires_approval = true

[integrations.calendar.tools.calendar__update_event]
requires_approval = true

[integrations.calendar.tools.calendar__delete_event]
requires_approval = true
```

- [ ] **Step 2: Update load_config in server.py**

In `load_config()`, add `GoogleConfig` to the imports at the top of `src/server.py`:

```python
from src.models import (
    ApprovalRequest,
    ApprovalStatus,
    GoogleConfig,
    IntegrationConfig,
    PolicyConfig,
    ServerConfig,
    TelegramConfig,
    ToolConfig,
)
```

In the `load_config()` body, add after the `policy` line:

```python
google = GoogleConfig(**raw.get("google", {}))
```

And include `google=google` in the `ServerConfig(...)` call.

- [ ] **Step 3: Update main.py to register Google integrations**

```python
"""Guarded MCP — Authorization-first MCP server."""

import asyncio
import logging
import os

from src.auth import GoogleAuthManager
from src.integrations.calendar import CalendarIntegration
from src.integrations.dummy import DummyIntegration
from src.integrations.gmail import GmailIntegration
from src.server import GuardedMCPServer, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    server = GuardedMCPServer(config)

    server.register_integration(DummyIntegration())

    # Register Google integrations if accounts are configured
    if config.google.accounts:
        secret_key = os.environ.get(config.google.secret_env, "")
        if not secret_key:
            logger.warning(
                "Google accounts configured but %s env var is not set. "
                "Skipping Google integrations.",
                config.google.secret_env,
            )
        else:
            auth = GoogleAuthManager(
                client_secret_path=config.google.client_secret_path,
                credentials_dir=config.google.credentials_dir,
                secret_key=secret_key,
            )
            # Validate accounts at startup
            for alias in config.google.accounts:
                try:
                    auth.get_credentials(alias)
                    logger.info("Google account '%s' loaded", alias)
                except Exception:
                    logger.warning(
                        "Google account '%s' not available", alias
                    )

            server.register_integration(GmailIntegration(auth))
            server.register_integration(
                CalendarIntegration(auth)
            )

    await server.start()
    try:
        server.run()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All existing tests still pass (Google integrations won't activate without config)

- [ ] **Step 5: Lint check**

Run: `uv run ruff check src/ tests/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/server.py main.py config.toml.example
git commit -m "feat: wire Google integrations into server and config"
```

---

## Task 7: End-to-End Server Tests for Google Integrations

**Files:**
- Create: `tests/test_server_google.py`

- [ ] **Step 1: Write e2e tests**

```python
# tests/test_server_google.py
"""E2e tests for Google integrations via FastMCPTransport."""

from unittest.mock import AsyncMock, MagicMock

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
    ToolConfig,
)
from src.server import GuardedMCPServer


@pytest.fixture
def mock_auth():
    auth = MagicMock(spec=GoogleAuthManager)
    mock_svc = MagicMock()
    auth.build_service.return_value = mock_svc
    # Gmail defaults
    mock_svc.users().messages().list(
    ).execute.return_value = {"messages": []}
    mock_svc.users().labels().list(
    ).execute.return_value = {"labels": []}
    # Calendar defaults
    mock_svc.events().list().execute.return_value = {
        "items": []
    }
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
    server.register_integration(
        CalendarIntegration(mock_auth)
    )
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
        # list_labels is read-only — should auto-approve
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


async def test_gmail_write_tool_requires_approval(
    google_server,
):
    await google_server.start()
    # No approval engine configured → should error
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


async def test_calendar_write_tool_requires_approval(
    google_server,
):
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
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_server_google.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite and lint**

Run: `uv run pytest -v && uv run ruff check src/ tests/`
Expected: All pass (existing + new), no lint errors

- [ ] **Step 4: Commit**

```bash
git add tests/test_server_google.py
git commit -m "test: add e2e tests for Google integrations"
```

---

## Task 8: Final Verification and Push

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors

- [ ] **Step 3: Verify .gitignore covers credentials**

Check that `.gitignore` already contains `credentials/` and `client_secret*.json`. It does (lines 21-22 of current `.gitignore`).

- [ ] **Step 4: Verify no secrets are staged**

Run: `git status`
Verify: no `.enc` files, no `client_secret*.json`, no `config.toml`

- [ ] **Step 5: Push to GitHub**

```bash
git push origin main
```
