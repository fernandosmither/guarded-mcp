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

        svc = build("oauth2", "v2", credentials=creds)
        info = svc.userinfo().get().execute()
        return info.get("email", alias)

    def remove_account(self, alias: str) -> None:
        """Delete encrypted credentials for an account."""
        path = self._credentials_dir / f"{alias}.enc"
        if not path.exists():
            raise ValueError(f"Account '{alias}' not found")
        path.unlink()
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
