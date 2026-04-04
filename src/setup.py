"""Interactive setup wizard for Guarded MCP.

Usage: python -m src.setup
"""

from __future__ import annotations

import os
from pathlib import Path

DIVIDER = "\033[90m" + "-" * 50 + "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[90m"
RESET = "\033[0m"


def _prompt(label: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    if default:
        raw = input(f"  {label} {DIM}[{default}]{RESET}: ").strip()
        return raw if raw else default
    else:
        while True:
            raw = input(f"  {label}: ").strip()
            if raw:
                return raw
            print(f"  {YELLOW}(required){RESET}")


def _prompt_yn(label: str, default: bool = True) -> bool:
    """Prompt for yes/no."""
    suffix = "Y/n" if default else "y/N"
    raw = input(f"  {label} {DIM}[{suffix}]{RESET}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _prompt_int(label: str, default: int) -> int:
    """Prompt for integer with default."""
    raw = input(f"  {label} {DIM}[{default}]{RESET}: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  {YELLOW}Invalid number, using default: {default}{RESET}")
        return default


def _step_header(num: int, total: int, title: str) -> None:
    """Print a step header."""
    print(f"\n{DIVIDER}")
    print(f"{BOLD}{num}/{total} {title}{RESET}")
    print(DIVIDER)


def _ok(msg: str) -> None:
    """Print a success message."""
    print(f"  {GREEN}{msg}{RESET}")


def _hint(msg: str) -> None:
    """Print a hint."""
    print(f"  {DIM}{msg}{RESET}")


def _wait(msg: str = "Press Enter to continue...") -> None:
    """Wait for user to press Enter."""
    input(f"  {DIM}{msg}{RESET}")


def setup_encryption() -> str:
    """Step 1: Encryption key."""
    _step_header(1, 5, "Encryption key")
    print("  Used to encrypt Google OAuth tokens at rest.")
    print()

    existing = os.environ.get("GUARDED_MCP_SECRET", "")
    if existing:
        _ok(f"GUARDED_MCP_SECRET already set ({len(existing)} chars)")
        if not _prompt_yn("Keep existing key?", True):
            existing = ""

    if not existing:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        print()
        print("  Generated key:")
        print(f"    {BOLD}{key}{RESET}")
        print()
        print("  Add to your shell profile (~/.bashrc or ~/.zshrc):")
        print(f"    export GUARDED_MCP_SECRET=\"{key}\"")
        print()
        _hint(
            "You can also export it now in your current shell "
            "to continue setup."
        )
        return key

    return existing


def setup_telegram() -> dict | None:
    """Step 2: Telegram bot configuration."""
    _step_header(2, 5, "Telegram approval bot")
    print("  Sends approval requests when the AI agent tries")
    print("  to use gated tools (send email, create events, etc).")
    print()

    if not _prompt_yn("Configure Telegram bot?", True):
        _hint("Skipping. Gated tools will fail without a bot configured.")
        return None

    print()
    _hint("Create a bot via @BotFather on Telegram to get a token.")
    _hint("To find your chat/user ID, message @userinfobot.")
    print()

    bot_token = _prompt("Bot token (from @BotFather)")
    chat_id = _prompt_int("Chat ID", 0)

    default_users = str(chat_id) if chat_id else ""
    users_str = _prompt(
        "Allowed user IDs (comma-separated)", default_users
    )
    allowed_users = [
        int(u.strip()) for u in users_str.split(",") if u.strip()
    ]

    print()
    _ok("Telegram configured")
    print()
    print("  Set the bot token in your environment:")
    print(f"    export APPROVAL_BOT_TOKEN=\"{bot_token}\"")

    return {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "allowed_user_ids": allowed_users,
    }


def setup_policy() -> dict:
    """Step 3: Approval policy."""
    _step_header(3, 5, "Approval policy")
    print("  Controls which tool calls need human approval.")
    print()

    if not _prompt_yn("Customize policy? (defaults are sensible)", False):
        _ok("Using defaults: auto-approve reads, 30min trust elevation")
        return {
            "auto_approve_reads": True,
            "trust_elevation_minutes": 30,
        }

    print()
    auto_reads = _prompt_yn("Auto-approve read-only tools?", True)
    trust_min = _prompt_int("Trust elevation minutes", 30)
    _ok("Policy configured")
    return {
        "auto_approve_reads": auto_reads,
        "trust_elevation_minutes": trust_min,
    }


def setup_google_cloud() -> bool:
    """Step 4: Google Cloud project setup. Returns True if client_secret exists."""
    import webbrowser

    _step_header(4, 5, "Google Cloud project")
    print("  Required for Gmail and Google Calendar access.")
    print()

    client_secret = Path("credentials/client_secret.json")

    if client_secret.exists():
        _ok("credentials/client_secret.json found")
        if _prompt_yn("Keep existing client secret?", True):
            return True

    if not _prompt_yn("Set up Google Cloud OAuth?", True):
        _hint("Skipping. Run this wizard again to set up later,")
        _hint("or place client_secret.json manually in credentials/")
        return False

    print()
    print(f"  {BOLD}A. Create a Google Cloud project{RESET}")
    _hint("Use an existing project or create a new one.")
    _wait("Press Enter to open Cloud Console...")
    webbrowser.open(
        "https://console.cloud.google.com/projectcreate"
    )
    _wait("Press Enter when your project is ready...")

    print()
    print(f"  {BOLD}B. Enable APIs{RESET}")
    _hint("We need Gmail API and Google Calendar API.")
    _wait("Press Enter to open Gmail API page...")
    webbrowser.open(
        "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
    )
    print("  Click 'Enable' for Gmail API.")
    _wait()
    webbrowser.open(
        "https://console.cloud.google.com/apis/library/"
        "calendar-json.googleapis.com"
    )
    print("  Click 'Enable' for Google Calendar API.")
    _wait()

    print()
    print(f"  {BOLD}C. OAuth consent screen{RESET}")
    _hint("User type: External")
    _hint("Fill in app name (e.g., 'Guarded MCP')")
    _hint("Add your own email as a test user")
    _wait("Press Enter to open consent screen config...")
    webbrowser.open(
        "https://console.cloud.google.com/apis/credentials/consent"
    )
    _wait("Press Enter when consent screen is configured...")

    print()
    print(f"  {BOLD}D. Create OAuth client{RESET}")
    print("  1. Click '+ Create Credentials' > 'OAuth client ID'")
    print(f"  2. Application type: {BOLD}Desktop app{RESET}")
    print("  3. Give it a name (e.g., 'Guarded MCP')")
    print("  4. Click 'Create', then 'Download JSON'")
    _wait("Press Enter to open Credentials page...")
    webbrowser.open(
        "https://console.cloud.google.com/apis/credentials"
    )

    print()
    print("  Save the downloaded JSON as:")
    print(f"    {BOLD}{client_secret.resolve()}{RESET}")
    _wait("Press Enter when the file is in place...")

    if not client_secret.exists():
        print(
            f"  {YELLOW}client_secret.json not found.{RESET}"
        )
        if _prompt_yn("Try again? (check the file path)", True):
            _wait("Press Enter when ready...")
            if not client_secret.exists():
                _hint(
                    "Still not found. Place it manually and "
                    "run: uv run python -m src.auth_cli add <alias>"
                )
                return False

    _ok("Found client_secret.json!")
    return True


def setup_google_accounts(secret_key: str) -> list[str]:
    """Step 5: Link Google accounts."""
    _step_header(5, 5, "Link Google accounts")
    print("  Each account opens a browser for OAuth consent.")
    print("  You can link multiple accounts (work, personal, etc).")
    print()

    if not _prompt_yn("Link a Google account now?", True):
        _hint(
            "You can link accounts later with: "
            "uv run python -m src.auth_cli add <alias>"
        )
        return []

    from src.auth import GoogleAuthManager

    auth = GoogleAuthManager(
        client_secret_path="credentials/client_secret.json",
        credentials_dir="credentials",
        secret_key=secret_key,
    )

    accounts: list[str] = []
    while True:
        print()
        alias = _prompt(
            "Account alias (e.g., 'work', 'personal')"
        )
        try:
            print("  Opening browser for Google OAuth...")
            email = auth.add_account(alias)
            _ok(f"Linked '{alias}' ({email})")
            accounts.append(alias)
        except Exception as e:
            print(f"  {YELLOW}Error: {e}{RESET}")
            _hint("Check the error and try again, or skip for now.")

        if not _prompt_yn("Link another account?", False):
            break

    return accounts


def write_config(
    telegram: dict | None,
    policy: dict,
    accounts: list[str],
) -> None:
    """Write config.toml."""
    chat_id = telegram["chat_id"] if telegram else 0
    users_list = (
        ", ".join(str(u) for u in telegram["allowed_user_ids"])
        if telegram
        else ""
    )
    accounts_list = ", ".join(f'"{a}"' for a in accounts)
    auto_approve = "true" if policy["auto_approve_reads"] else "false"

    content = f"""\
[server]
host = "127.0.0.1"
port = 3100
approval_timeout_seconds = 300

[telegram]
bot_token_env = "APPROVAL_BOT_TOKEN"
chat_id = {chat_id}
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
    print()
    print(f"  {BOLD}Guarded MCP Setup{RESET}")
    print(f"  {DIM}Authorization-first MCP server{RESET}")
    print()

    if Path("config.toml").exists() and not _prompt_yn(
        "config.toml already exists. Reconfigure?", False
    ):
        print("  Setup cancelled.")
        return

    # Step 1: Encryption key
    secret_key = setup_encryption()

    # Step 2: Telegram
    telegram = setup_telegram()

    # Step 3: Policy
    policy = setup_policy()

    # Step 4+5: Google (split into cloud project + account linking)
    has_google = setup_google_cloud()
    accounts: list[str] = []
    if has_google:
        accounts = setup_google_accounts(secret_key)

    # Write config
    write_config(telegram, policy, accounts)

    print()
    print(DIVIDER)
    print(f"  {GREEN}{BOLD}Setup complete!{RESET}")
    print(DIVIDER)
    print()
    print(f"  {BOLD}Config written to:{RESET} config.toml")
    if accounts:
        print(
            f"  {BOLD}Linked accounts:{RESET} "
            + ", ".join(accounts)
        )
    print()
    print("  Make sure these env vars are set:")
    if telegram:
        print(
            f"    export APPROVAL_BOT_TOKEN="
            f"\"{telegram['bot_token']}\""
        )
    print(f'    export GUARDED_MCP_SECRET="{secret_key}"')
    print()
    print("  Then start the server:")
    print(f"    {BOLD}uv run python main.py{RESET}")
    print()


if __name__ == "__main__":
    main()
