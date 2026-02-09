"""
Entry point for the Orchestrator.

Usage:
    python -m src.orchestrator

This module:
1. Loads configuration from environment variables
2. Configures structured logging (stdout JSON + Application Insights)
3. Connects to Azure Service Bus via Managed Identity
4. Consumes messages in peek-lock mode
5. Executes domain-level decision logic (SKIP / REPROCESS)
6. Completes or abandons messages based on result
7. Shuts down gracefully on SIGTERM / SIGINT
"""

import logging
import signal
import sys

from .config import OrchestratorConfig
from .consumer import ServiceBusConsumer
from .logging_setup import configure_logging

logger = logging.getLogger("orchestrator")


def main() -> None:
    """Orchestrator entry point."""
    # -- Configuration ------------------------------------------------------
    try:
        config = OrchestratorConfig()
    except KeyError as exc:
        print(
            f"FATAL: Missing required environment variable: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Logging ------------------------------------------------------------
    configure_logging(config.applicationinsights_connection_string)
    logger.info("Orchestrator starting", extra={"config": repr(config)})

    # -- Graceful shutdown --------------------------------------------------
    running = True

    def _shutdown_handler(signum: int, _frame: object) -> None:
        nonlocal running
        running = False
        sig_name = signal.Signals(signum).name
        logger.info("Shutdown signal received: %s", sig_name)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    # -- Consumer loop ------------------------------------------------------
    consumer = ServiceBusConsumer(config)

    try:
        consumer.run(is_running=lambda: running)
    except Exception:
        logger.exception("Fatal error in orchestrator")
        sys.exit(1)
    finally:
        consumer.close()
        logger.info("Orchestrator stopped")


if __name__ == "__main__":
    main()
