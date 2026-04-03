# Guarded MCP

Authorization-first MCP server framework with Telegram-based human-in-the-loop approval for AI agent actions.

## Why

LLM agents can call tools. Some tools are dangerous — sending emails, modifying data, transferring money. Guarded MCP sits between the agent and the tools, requiring explicit human approval for sensitive actions via Telegram.

## Architecture

```
AI Agent (Claude, GPT, etc.)
    │
    ▼
┌─────────────────────────────────┐
│  MCP Protocol (HTTP transport)  │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│      GuardedMCPServer           │
│  ┌───────────────────────────┐  │
│  │   ApprovalMiddleware      │  │
│  │   ┌─────────────────────┐ │  │
│  │   │   PolicyEngine      │ │  │  ← auto-approve reads, trust, allowlists
│  │   └─────────────────────┘ │  │
│  │   ┌─────────────────────┐ │  │
│  │   │  ApprovalEngine     │ │  │  ← Telegram: approve / reject / trust 30min
│  │   └─────────────────────┘ │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │  Integrations (pluggable) │  │  ← Gmail, Calendar, etc.
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

## Features

- **Approval middleware** — intercepts gated tool calls, sends a Telegram message with an inline keyboard (Approve / Reject / Trust 30min)
- **Policy engine** — auto-approve read-only tools, domain allowlists, per-tool configuration
- **Trust elevation** — "Trust 30min" grants temporary auto-approval for repeated calls to the same tool
- **Hash verification** — each request's parameters are SHA-256 hashed; the hash is verified before execution to prevent tampering
- **Anti-manipulation** — approval messages show raw parameters only, never agent-supplied descriptions
- **Pluggable integrations** — simple ABC for adding new tool providers

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- A Telegram bot token (via [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID and user ID

### Setup

```bash
git clone https://github.com/fernandosmither/guarded-mcp.git
cd guarded-mcp
uv sync
```

### Configure

```bash
cp config.toml.example config.toml
# Edit config.toml with your Telegram credentials
```

Set the bot token:

```bash
export APPROVAL_BOT_TOKEN="your-bot-token-here"
```

### Run

```bash
uv run python main.py
```

The server starts on `http://127.0.0.1:3100` with stateless HTTP transport.

## Configuration

### `[server]`

| Key | Default | Description |
|-----|---------|-------------|
| `host` | `127.0.0.1` | Bind address |
| `port` | `3100` | Listen port |
| `approval_timeout_seconds` | `300` | Seconds before an unanswered approval expires |

### `[telegram]`

| Key | Default | Description |
|-----|---------|-------------|
| `bot_token_env` | `APPROVAL_BOT_TOKEN` | Environment variable containing the bot token |
| `chat_id` | `0` | Telegram chat ID to send approvals to |
| `allowed_user_ids` | `[]` | User IDs allowed to approve/reject |

### `[policy]`

| Key | Default | Description |
|-----|---------|-------------|
| `auto_approve_reads` | `true` | Read-only tools skip approval |
| `trust_elevation_minutes` | `30` | Duration of "Trust 30min" button |

### `[integrations.<name>.tools.<tool>]`

| Key | Default | Description |
|-----|---------|-------------|
| `requires_approval` | `true` | Whether this tool needs human approval |
| `auto_approve_domains` | `[]` | Email domains that bypass approval |

## Writing an Integration

```python
from src.integrations.base import Integration, ToolDef

class MyIntegration(Integration):
    name = "my_service"

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="read_data",
                description="Read some data",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"],
                },
                read_only=True,       # auto-approved if policy allows
                requires_approval=False,
            ),
            ToolDef(
                name="write_data",
                description="Write data (needs approval)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["content"],
                },
                read_only=False,
                requires_approval=True,
            ),
        ]

    async def execute(self, tool_name: str, arguments: dict):
        if tool_name == "read_data":
            return {"result": f"data for {arguments['query']}"}
        elif tool_name == "write_data":
            return {"written": arguments["content"]}
```

Register it in `main.py`:

```python
server.register_integration(MyIntegration())
```

## Development

```bash
uv sync --extra dev
uv run pytest -v
uv run ruff check src/ tests/
```

## License

MIT
