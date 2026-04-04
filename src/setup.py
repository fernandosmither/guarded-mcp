"""Interactive setup wizard for Guarded MCP.

Usage: python -m src.setup
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

DIVIDER = "\033[90m" + "-" * 50 + "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[90m"
RESET = "\033[0m"


def _load_existing_config() -> dict:
    """Load existing config.toml if present, else empty dict."""
    config_path = Path("config.toml")
    if not config_path.exists():
        return {}
    with open(config_path, "rb") as f:
        return tomllib.load(f)


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


def _save_to_dotenv(key: str, value: str) -> None:
    """Save or update a key=value pair in .env file."""
    env_path = Path(".env")
    lines: list[str] = []
    found = False

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f'{key}="{value}"')
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f'{key}="{value}"')

    env_path.write_text("\n".join(lines) + "\n")


def _load_dotenv() -> None:
    """Load .env file into os.environ (simple parser, no deps)."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if key.strip() not in os.environ:
            os.environ[key.strip()] = value


def setup_encryption(existing: dict) -> str:
    """Step 1: Encryption key."""
    _step_header(1, 5, "Encryption key")
    print("  Used to encrypt Google OAuth tokens at rest.")
    print()

    env_key = existing.get("google", {}).get(
        "secret_env", "GUARDED_MCP_SECRET"
    )
    current = os.environ.get(env_key, "")

    if current:
        _ok(f"{env_key} already set ({len(current)} chars)")
        if _prompt_yn("Keep existing key?", True):
            return current

    # Check if encrypted tokens already exist — new key would break them
    creds_dir = Path(
        existing.get("google", {}).get("credentials_dir", "credentials")
    )
    has_tokens = list(creds_dir.glob("*.enc")) if creds_dir.exists() else []

    if has_tokens:
        names = ", ".join(p.stem for p in has_tokens)
        print(
            f"  {YELLOW}Encrypted tokens found: {names}{RESET}"
        )
        print(
            f"  {YELLOW}A new key will NOT decrypt these tokens.{RESET}"
        )
        print()
        print(
            "  You need the original key. Set it in your shell:"
        )
        print(f'    export {env_key}="<your-original-key>"')
        print()
        print("  Then re-run this wizard.")
        _hint(
            "If you've lost the key, delete the .enc files in "
            f"{creds_dir}/ and re-link your accounts."
        )
        key = _prompt(
            "Paste your existing key (or 'new' to generate a fresh one)"
        )
        if key.lower() == "new":
            print(
                f"  {YELLOW}Warning: existing tokens will be "
                f"unreadable with a new key.{RESET}"
            )
            if not _prompt_yn("Generate new key anyway?", False):
                print("  Re-run setup with your original key set.")
                raise SystemExit(1)
        else:
            # Validate the key works
            from cryptography.fernet import Fernet

            try:
                Fernet(key.encode())
                _ok("Key accepted")
                return key
            except Exception:
                print(f"  {YELLOW}Invalid Fernet key.{RESET}")
                print("  Re-run setup with a valid key.")
                raise SystemExit(1) from None

    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    _save_to_dotenv("GUARDED_MCP_SECRET", key)
    _ok("Generated and saved to .env")
    _hint("Also exported for this wizard session.")
    os.environ["GUARDED_MCP_SECRET"] = key
    return key


def setup_telegram(existing: dict) -> dict | None:
    """Step 2: Telegram bot configuration."""
    _step_header(2, 5, "Telegram approval bot")
    print("  Sends approval requests when the AI agent tries")
    print("  to use gated tools (send email, create events, etc).")
    print()

    tg = existing.get("telegram", {})
    has_existing = tg.get("chat_id", 0) != 0

    if has_existing:
        _ok(f"Existing config: chat_id={tg['chat_id']}")
        if _prompt_yn("Keep existing Telegram config?", True):
            return {
                "bot_token": "",
                "chat_id": tg["chat_id"],
                "allowed_user_ids": tg.get("allowed_user_ids", []),
            }

    if not _prompt_yn("Configure Telegram bot?", True):
        _hint("Skipping. Gated tools will fail without a bot configured.")
        return None

    print()
    _hint("Create a bot via @BotFather on Telegram to get a token.")
    _hint("To find your chat/user ID, message @userinfobot.")
    print()

    prev_token = os.environ.get(
        tg.get("bot_token_env", "APPROVAL_BOT_TOKEN"), ""
    )
    if prev_token:
        bot_token = _prompt(
            "Bot token (from @BotFather)",
            prev_token[:8] + "..." + prev_token[-4:],
        )
        if "..." in bot_token:
            bot_token = prev_token
    else:
        bot_token = _prompt("Bot token (from @BotFather)")

    chat_id = _prompt_int("Chat ID", tg.get("chat_id", 0))

    prev_users = tg.get("allowed_user_ids", [])
    default_users = (
        ", ".join(str(u) for u in prev_users)
        if prev_users
        else (str(chat_id) if chat_id else "")
    )
    users_str = _prompt(
        "Allowed user IDs (comma-separated)", default_users
    )
    allowed_users = [
        int(u.strip()) for u in users_str.split(",") if u.strip()
    ]

    _save_to_dotenv("APPROVAL_BOT_TOKEN", bot_token)
    os.environ["APPROVAL_BOT_TOKEN"] = bot_token
    print()
    _ok("Telegram configured (token saved to .env)")

    return {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "allowed_user_ids": allowed_users,
    }


def setup_policy(existing: dict) -> dict:
    """Step 3: Approval policy."""
    _step_header(3, 5, "Approval policy")
    print("  Controls which tool calls need human approval.")
    print()

    pol = existing.get("policy", {})
    prev_auto = pol.get("auto_approve_reads", True)
    prev_trust = pol.get("trust_elevation_minutes", 30)

    if pol:
        auto_str = "yes" if prev_auto else "no"
        _hint(
            f"Current: auto-approve reads={auto_str}, "
            f"trust={prev_trust}min"
        )

    if not _prompt_yn("Customize policy?", False):
        result = {
            "auto_approve_reads": prev_auto,
            "trust_elevation_minutes": prev_trust,
        }
        auto_str = "yes" if result["auto_approve_reads"] else "no"
        _ok(
            f"Using: auto-approve reads={auto_str}, "
            f"trust={result['trust_elevation_minutes']}min"
        )
        return result

    print()
    auto_reads = _prompt_yn(
        "Auto-approve read-only tools?", prev_auto
    )
    trust_min = _prompt_int("Trust elevation minutes", prev_trust)
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
        print(f"  {YELLOW}client_secret.json not found.{RESET}")
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


def setup_google_accounts(
    secret_key: str, existing: dict
) -> list[str]:
    """Step 5: Link Google accounts."""
    _step_header(5, 5, "Link Google accounts")
    print("  Each account opens a browser for OAuth consent.")
    print("  You can link multiple accounts (work, personal, etc).")
    print()

    from src.auth import GoogleAuthManager

    auth = GoogleAuthManager(
        client_secret_path="credentials/client_secret.json",
        credentials_dir="credentials",
        secret_key=secret_key,
    )

    # Show existing linked accounts
    prev_accounts = existing.get("google", {}).get("accounts", [])
    on_disk = auth.list_accounts()
    if on_disk:
        _ok(f"Already linked: {', '.join(on_disk)}")
        if prev_accounts and not _prompt_yn(
            "Link additional accounts?", False
        ):
            return on_disk

    if not on_disk and not _prompt_yn(
        "Link a Google account now?", True
    ):
        _hint(
            "You can link accounts later with: "
            "uv run python -m src.auth_cli add <alias>"
        )
        return list(prev_accounts)

    accounts = list(on_disk)
    while True:
        print()
        alias = _prompt(
            "Account alias (e.g., 'work', 'personal')"
        )
        if alias in accounts:
            print(f"  {YELLOW}'{alias}' is already linked.{RESET}")
            if not _prompt_yn("Re-link it? (replaces token)", False):
                continue
        try:
            print("  Opening browser for Google OAuth...")
            email = auth.add_account(alias)
            _ok(f"Linked '{alias}' ({email})")
            if alias not in accounts:
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

    _load_dotenv()
    existing = _load_existing_config()

    if existing:
        _hint("Existing config.toml found — values will be used as defaults.")
        if not _prompt_yn("Reconfigure?", True):
            print("  Setup cancelled.")
            return

    # Step 1: Encryption key
    secret_key = setup_encryption(existing)

    # Step 2: Telegram
    telegram = setup_telegram(existing)

    # Step 3: Policy
    policy = setup_policy(existing)

    # Step 4+5: Google (split into cloud project + account linking)
    has_google = setup_google_cloud()
    accounts: list[str] = []
    if has_google:
        accounts = setup_google_accounts(secret_key, existing)
    else:
        # Preserve existing accounts even if skipping GCP setup
        accounts = list(
            existing.get("google", {}).get("accounts", [])
        )

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
    print(f"  {BOLD}Secrets saved to:{RESET} .env (auto-loaded on startup)")
    print()
    print("  Start the server:")
    print(f"    {BOLD}uv run python main.py{RESET}")
    print()


if __name__ == "__main__":
    main()
