"""Tests for GoogleAuthManager credential encryption and loading."""

import json
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
        "src.auth.build"
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
