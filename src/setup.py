"""Interactive setup wizard for Guarded MCP.

Usage: python -m src.setup
"""

from __future__ import annotations

import os
from pathlib import Path


def _prompt(label: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    if default:
        raw = input(f"  {label} [{default}]: ").strip()
        return raw if raw else default
    else:
        while True:
            raw = input(f"  {label}: ").strip()
            if raw:
                return raw
            print("  (required)")


def _prompt_yn(label: str, default: bool = True) -> bool:
    """Prompt for yes/no."""
    suffix = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{suffix}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _prompt_int(label: str, default: int) -> int:
    """Prompt for integer with default."""
    raw = input(f"  {label} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  Invalid number, using default: {default}")
        return default


def setup_encryption() -> str:
    """Step 1: Encryption key."""
    print("\n1/5 Encryption key")
    existing = os.environ.get("GUARDED_MCP_SECRET", "")
    if existing:
        print(f"  GUARDED_MCP_SECRET is set ({len(existing)} chars)")
        return existing

    print("  No GUARDED_MCP_SECRET found in environment.")
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    print(f"  Generated key: {key}")
    print()
    print("  Add to your shell profile (~/.bashrc or ~/.zshrc):")
    print(f'    export GUARDED_MCP_SECRET="{key}"')
    print()
    print("  Then reload your shell or run:")
    print(f'    export GUARDED_MCP_SECRET="{key}"')
    return key


def setup_telegram() -> dict:
    """Step 2: Telegram bot configuration."""
    print("\n2/5 Telegram bot")
    print("  Create a bot via @BotFather on Telegram to get a token.")
    print("  To find your chat ID, message @userinfobot on Telegram.")
    print()

    bot_token = _prompt("Bot token (from @BotFather)")
    chat_id = _prompt_int("Chat ID", 0)

    default_users = str(chat_id) if chat_id else ""
    users_str = _prompt("Allowed user IDs (comma-separated)", default_users)
    allowed_users = [int(u.strip()) for u in users_str.split(",") if u.strip()]

    return {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "allowed_user_ids": allowed_users,
    }


def setup_policy() -> dict:
    """Step 3: Approval policy."""
    print("\n3/5 Approval policy")
    auto_reads = _prompt_yn("Auto-approve read-only tools?", True)
    trust_min = _prompt_int("Trust elevation minutes", 30)
    return {
        "auto_approve_reads": auto_reads,
        "trust_elevation_minutes": trust_min,
    }


def setup_google(secret_key: str) -> list[str]:
    """Step 4: Google accounts (optional)."""
    import webbrowser

    print("\n4/5 Google Cloud project")

    if not _prompt_yn("Set up Gmail & Google Calendar access?", False):
        print("  Skipping. You can add Google accounts later with:")
        print("    uv run python -m src.auth_cli add <alias>")
        return []

    client_secret = Path("credentials/client_secret.json")

    if not client_secret.exists():
        print()
        print("  You need a Google Cloud OAuth client. Let's set one up.")
        print()
        print("  Step A: Create a Google Cloud project (or use an existing one)")
        input("  Press Enter to open Google Cloud Console...")
        webbrowser.open(
            "https://console.cloud.google.com/projectcreate"
        )
        input("  Press Enter when your project is ready...")

        print()
        print("  Step B: Enable the Gmail and Calendar APIs")
        input("  Press Enter to open the API library...")
        webbrowser.open(
            "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
        )
        print("  Enable 'Gmail API', then come back here.")
        input("  Press Enter to continue...")
        webbrowser.open(
            "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com"
        )
        print("  Enable 'Google Calendar API', then come back here.")
        input("  Press Enter to continue...")

        print()
        print("  Step C: Configure OAuth consent screen")
        print("  Set user type to 'External', fill in app name,")
        print("  add your email as a test user.")
        input("  Press Enter to open OAuth consent screen...")
        webbrowser.open(
            "https://console.cloud.google.com/apis/credentials/consent"
        )
        input("  Press Enter when consent screen is configured...")

        print()
        print("  Step D: Create OAuth credentials")
        print("  Click '+ Create Credentials' > 'OAuth client ID'")
        print("  Application type: 'Desktop app'")
        print("  Download the JSON file.")
        input("  Press Enter to open the Credentials page...")
        webbrowser.open(
            "https://console.cloud.google.com/apis/credentials"
        )

        print()
        print("  Save the downloaded JSON as:")
        print(f"    {client_secret.resolve()}")
        print()
        input("  Press Enter when the file is in place...")

        if not client_secret.exists():
            print(
                "  client_secret.json still not found."
                " Please place it manually and re-run setup."
            )
            return []

        print("  Found client_secret.json!")

    print("\n5/5 Link Google accounts")
    print("  Now let's link your Google accounts.")
    print("  Each account opens a browser for OAuth consent.")
    print()

    from src.auth import GoogleAuthManager

    auth = GoogleAuthManager(
        client_secret_path=str(client_secret),
        credentials_dir="credentials",
        secret_key=secret_key,
    )

    accounts: list[str] = []
    while True:
        alias = _prompt(
            "Account alias (e.g., 'work', 'personal')"
        )
        try:
            print("  Opening browser for Google OAuth...")
            email = auth.add_account(alias)
            print(f"  Linked '{alias}' ({email})")
            accounts.append(alias)
        except Exception as e:
            print(f"  Error linking account: {e}")

        if not _prompt_yn("Link another account?", False):
            break

    return accounts


def write_config(
    telegram: dict,
    policy: dict,
    accounts: list[str],
) -> None:
    """Write config.toml."""
    users_list = ", ".join(str(u) for u in telegram["allowed_user_ids"])
    accounts_list = ", ".join(f'"{a}"' for a in accounts)

    auto_approve = "true" if policy["auto_approve_reads"] else "false"

    content = f"""\
[server]
host = "127.0.0.1"
port = 3100
approval_timeout_seconds = 300

[telegram]
bot_token_env = "APPROVAL_BOT_TOKEN"
chat_id = {telegram["chat_id"]}
allowed_user_ids = [{users_list}]

[policy]
auto_approve_reads = {auto_approve}
trust_elevation_minutes = {policy["trust_elevation_minutes"]}

[google]
client_secret_path = "credentials/client_secret.json"
credentials_dir = "credentials"
secret_env = "GUARDED_MCP_SECRET"
accounts = [{accounts_list}]

[integrations.gmail.tools.gmail__send_email]
requires_approval = true

[integrations.gmail.tools.gmail__reply_to_email]
requires_approval = true

[integrations.gmail.tools.gmail__modify_email]
requires_approval = true

[integrations.calendar.tools.calendar__create_event]
requires_approval = true

[integrations.calendar.tools.calendar__update_event]
requires_approval = true

[integrations.calendar.tools.calendar__delete_event]
requires_approval = true
"""

    Path("config.toml").write_text(content)


def main() -> None:
    print("Guarded MCP Setup")
    print("=" * 40)

    if Path("config.toml").exists() and not _prompt_yn(
        "config.toml already exists. Overwrite?", False
    ):
        print("Setup cancelled.")
        return

    # Step 1: Encryption key
    secret_key = setup_encryption()

    # Step 2: Telegram
    telegram = setup_telegram()

    # Save bot token reminder
    print()
    print("  Remember to set the bot token env var:")
    print(f'    export APPROVAL_BOT_TOKEN="{telegram["bot_token"]}"')

    # Step 3: Policy
    policy = setup_policy()

    # Step 4: Google accounts
    accounts = setup_google(secret_key)

    # Write config
    write_config(telegram, policy, accounts)
    print()
    print("Config written to config.toml")
    print()
    print("Run the server:")
    print("  uv run python main.py")


if __name__ == "__main__":
    main()
