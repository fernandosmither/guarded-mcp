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
            for alias in config.google.accounts:
                try:
                    auth.get_credentials(alias)
                    logger.info("Google account '%s' loaded", alias)
                except Exception:
                    logger.warning(
                        "Google account '%s' not available",
                        alias,
                    )

            server.register_integration(GmailIntegration(auth))
            server.register_integration(
                CalendarIntegration(auth)
            )

    await server.start()
    try:
        await server.run()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
