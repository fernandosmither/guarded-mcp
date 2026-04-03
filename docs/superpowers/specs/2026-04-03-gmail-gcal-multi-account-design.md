# Gmail & Google Calendar Multi-Account Integration

**Date:** 2026-04-03
**Status:** Approved

## Context

guarded-mcp needs real integrations beyond the dummy. Gmail and Google Calendar are the first targets. The user has 2-3 Google accounts (personal + work) and wants the AI agent to operate on any of them, with the account specified explicitly per tool call. Multi-account is a first-class citizen, not an afterthought.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth method | OAuth2 per-user credentials | Works for both personal and Workspace accounts |
| Account selection | Explicit `account` parameter on every tool | No ambiguity, agent always knows which account |
| Auth flow | CLI command (`python -m src.auth add <alias>`) | One-time browser consent per account |
| Gmail scope | `gmail.modify` + `gmail.labels` | Full access; reads auto-approved, writes gated |
| Calendar scope | `calendar.events` | Read + write events |
| Token storage | `credentials/` dir, Fernet-encrypted | Already in .gitignore, portable |
| API library | `google-api-python-client` + `asyncio.to_thread()` | Official, battle-tested |
| Architecture | Shared `GoogleAuthManager`, one integration instance per service | Simple: 2 integrations, N accounts |

## Architecture

```
GoogleAuthManager (shared singleton)
  ├─ credentials/client_secret.json    (Google Cloud OAuth client)
  ├─ credentials/work.enc             (encrypted OAuth token)
  └─ credentials/personal.enc         (encrypted OAuth token)

GmailIntegration (1 instance, uses GoogleAuthManager)
  ├─ gmail__search_emails(account, query, max_results)
  ├─ gmail__read_email(account, message_id)
  ├─ gmail__send_email(account, to, subject, body, cc, bcc, reply_to_message_id)
  ├─ gmail__reply_to_email(account, message_id, body)
  ├─ gmail__modify_email(account, message_id, add_labels, remove_labels)
  └─ gmail__list_labels(account)

CalendarIntegration (1 instance, uses GoogleAuthManager)
  ├─ calendar__list_events(account, time_min, time_max, calendar_id)
  ├─ calendar__get_event(account, event_id, calendar_id)
  ├─ calendar__create_event(account, summary, start, end, attendees, description, location)
  ├─ calendar__update_event(account, event_id, ...)
  ├─ calendar__delete_event(account, event_id, calendar_id)
  └─ calendar__list_calendars(account)
```

## Auth Layer: `src/auth.py`

### GoogleAuthManager

Manages OAuth2 credentials for N Google accounts.

**Constructor:** `GoogleAuthManager(client_secret_path, credentials_dir, secret_env)`

**Methods:**
- `add_account(alias: str) -> None` — Opens browser for OAuth consent via `InstalledAppFlow.run_local_server()`. Saves encrypted token to `credentials/{alias}.enc`.
- `remove_account(alias: str) -> None` — Deletes `credentials/{alias}.enc`.
- `list_accounts() -> list[str]` — Returns aliases from `credentials/*.enc` filenames.
- `get_credentials(alias: str) -> google.oauth2.credentials.Credentials` — Loads, decrypts, auto-refreshes if expired, re-encrypts if refreshed. Raises `ValueError` if account not found.
- `build_service(alias: str, api: str, version: str) -> Resource` — Calls `get_credentials` + `googleapiclient.discovery.build()`. Caches the service object per (alias, api, version) tuple.

**Encryption:**
- Uses `cryptography.fernet.Fernet` with key from `GUARDED_MCP_SECRET` env var.
- Token JSON is encrypted at rest, decrypted only in memory.
- If a token is refreshed (new access_token), the encrypted file is updated.

**Scopes:** `['https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/gmail.labels', 'https://www.googleapis.com/auth/calendar.events']`

All accounts get the same scopes. Requested at consent time.

### CLI: `python -m src.auth`

```
python -m src.auth add <alias>       # Link a Google account
python -m src.auth remove <alias>    # Unlink an account
python -m src.auth list              # Show linked accounts
```

The `add` command:
1. Loads `client_secret.json`
2. Runs `InstalledAppFlow.run_local_server(port=0)` (picks a random free port)
3. Encrypts the resulting credentials
4. Saves to `credentials/{alias}.enc`
5. Prints the linked email address for confirmation

## Gmail Integration: `src/integrations/gmail.py`

### Tools

**`gmail__search_emails`** (read-only, auto-approved)
- Params: `account: str`, `query: str`, `max_results: int = 10`
- Uses `users().messages().list(q=query)` then batch-fetches metadata
- Returns: list of `{id, from, to, subject, date, snippet}`

**`gmail__read_email`** (read-only, auto-approved)
- Params: `account: str`, `message_id: str`
- Uses `users().messages().get(format='full')`
- Returns: headers + body as plain text (HTML stripped), attachments listed by name/size

**`gmail__send_email`** (requires approval)
- Params: `account: str`, `to: str`, `subject: str`, `body: str`, `cc: str | None`, `bcc: str | None`
- Builds MIME message, base64url encodes
- For composing new emails only (not replies)
- Uses `users().messages().send()`

**`gmail__reply_to_email`** (requires approval)
- Params: `account: str`, `message_id: str`, `body: str`
- Fetches original message to get From, Subject, threadId, Message-ID
- Builds reply with proper headers (`In-Reply-To`, `References`, `Re:` subject prefix)
- Uses `users().messages().send()` with threadId
- Use this instead of `send_email` when replying to an existing thread

**`gmail__modify_email`** (requires approval)
- Params: `account: str`, `message_id: str`, `add_labels: list[str] = []`, `remove_labels: list[str] = []`
- Uses `users().messages().modify()`
- Common patterns: archive (remove INBOX), trash (add TRASH), mark read (remove UNREAD)

**`gmail__list_labels`** (read-only, auto-approved)
- Params: `account: str`
- Uses `users().labels().list()`
- Returns: list of `{id, name, type}`

### API wrapping pattern

All Google API calls follow:
```python
async def _call(self, account: str, fn):
    """Execute a Google API call in a thread."""
    return await asyncio.to_thread(fn.execute)
```

## Calendar Integration: `src/integrations/calendar.py`

### Tools

**`calendar__list_events`** (read-only, auto-approved)
- Params: `account: str`, `time_min: str`, `time_max: str`, `calendar_id: str = "primary"`, `max_results: int = 20`
- Dates as ISO 8601 (e.g., `2026-04-03T00:00:00Z`)
- Returns: list of `{id, summary, start, end, location, attendees, status}`

**`calendar__get_event`** (read-only, auto-approved)
- Params: `account: str`, `event_id: str`, `calendar_id: str = "primary"`
- Returns: full event details

**`calendar__create_event`** (requires approval)
- Params: `account: str`, `summary: str`, `start: str`, `end: str`, `description: str | None`, `location: str | None`, `attendees: list[str] = []`, `calendar_id: str = "primary"`
- Attendees are email strings, converted to `[{"email": x}]`
- Returns: created event with id

**`calendar__update_event`** (requires approval)
- Params: `account: str`, `event_id: str`, `calendar_id: str = "primary"`, plus optional: `summary`, `start`, `end`, `description`, `location`, `attendees`
- Only sends fields that are provided (patch semantics via `events().patch()`)

**`calendar__delete_event`** (requires approval)
- Params: `account: str`, `event_id: str`, `calendar_id: str = "primary"`
- Uses `events().delete()`

**`calendar__list_calendars`** (read-only, auto-approved)
- Params: `account: str`
- Returns: list of `{id, summary, primary, accessRole}`

## Configuration

### New `[google]` section in config.toml

```toml
[google]
client_secret_path = "credentials/client_secret.json"
credentials_dir = "credentials"
secret_env = "GUARDED_MCP_SECRET"
accounts = ["work", "personal"]
```

### New model: `GoogleConfig`

Added to `src/models.py`:
```python
class GoogleConfig(BaseModel):
    client_secret_path: str = "credentials/client_secret.json"
    credentials_dir: str = "credentials"
    secret_env: str = "GUARDED_MCP_SECRET"
    accounts: list[str] = Field(default_factory=list)
```

Added to `ServerConfig`:
```python
google: GoogleConfig = Field(default_factory=GoogleConfig)
```

### Default approval rules

Read-only tools (`search_emails`, `read_email`, `list_labels`, `list_events`, `get_event`, `list_calendars`) are auto-approved via the existing `auto_approve_reads` policy.

Write tools (`send_email`, `reply_to_email`, `modify_email`, `create_event`, `update_event`, `delete_event`) require approval by default. Per-tool overrides in config.

### Account validation at startup

On server start, for each alias in `google.accounts`:
1. Check `credentials/{alias}.enc` exists
2. Attempt to load + decrypt credentials
3. If valid, account is active
4. If missing or invalid, log warning and skip (don't crash)

## New Dependencies

```
google-api-python-client>=2.100.0
google-auth-oauthlib>=1.0.0
cryptography>=42.0.0
```

## File Layout

```
src/auth.py                         # GoogleAuthManager + __main__ CLI
src/integrations/gmail.py           # GmailIntegration
src/integrations/calendar.py        # CalendarIntegration
credentials/.gitkeep                # Ensure dir exists in repo
```

**Modified:**
- `src/models.py` — add `GoogleConfig`
- `src/server.py` — load GoogleConfig, create auth manager, register integrations
- `main.py` — register Gmail + Calendar integrations
- `config.toml.example` — add `[google]` section + tool configs
- `pyproject.toml` — new deps
- `.gitignore` — ensure `credentials/*.enc`, `credentials/client_secret*.json` excluded

## Security Considerations

- **Tokens encrypted at rest** with Fernet (AES-128-CBC + HMAC-SHA256)
- **Encryption key** stored in env var, never in config files
- **client_secret.json** in .gitignore — never committed
- **Scopes are explicit** — only requested at consent time, visible to user
- **Approval messages show raw params** including `account` — user sees exactly which account and what action
- **No phone-home** — Google API calls are on-demand only, no background sync or polling
- **Token refresh is transparent** — happens in-process, re-encrypted immediately

## Testing Strategy

- Unit tests for `GoogleAuthManager` (mock filesystem + Fernet)
- Unit tests for Gmail/Calendar integrations (mock `build_service` to return fake API objects)
- End-to-end tests via FastMCPTransport (mock auth manager, verify tool registration, approval flow)
- No real Google API calls in tests
