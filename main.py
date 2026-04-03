"""Guarded MCP — Authorization-first MCP server."""

import asyncio
import logging

from src.integrations.dummy import DummyIntegration
from src.server import GuardedMCPServer, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main() -> None:
    config = load_config()
    server = GuardedMCPServer(config)

    server.register_integration(DummyIntegration())

    await server.start()
    try:
        server.run()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
