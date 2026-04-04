"""CLI for managing Google OAuth2 accounts.

Usage:
    python -m src.auth_cli add work
    python -m src.auth_cli remove work
    python -m src.auth_cli list
"""

from __future__ import annotations

import argparse
import os
import sys

from src.auth import GoogleAuthManager, load_dotenv


def _get_manager() -> GoogleAuthManager:
    load_dotenv()
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
    print("Opening browser for Google OAuth...")
    email = manager.add_account(args.alias)
    print(f"Account: {email}")
    print(f'Token saved for account "{args.alias}"')


def cmd_remove(args: argparse.Namespace) -> None:
    manager = _get_manager()
    manager.remove_account(args.alias)
    print(f'Account "{args.alias}" removed.')


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
