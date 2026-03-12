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
import threading
import time
from datetime import datetime, timezone

from .config import OrchestratorConfig
from .consumer import ServiceBusConsumer
from .logging_setup import configure_logging

logger = logging.getLogger("orchestrator")

_HEARTBEAT_INTERVAL_SECONDS = 300  # 5 minutes


def _heartbeat_loop(stop_event: threading.Event) -> None:
    """Background thread — emits host_alive every 5 minutes to App Insights."""
    hb_logger = logging.getLogger("orchestrator.heartbeat")
    while not stop_event.wait(timeout=_HEARTBEAT_INTERVAL_SECONDS):
        hb_logger.info(
            "host_alive",
            extra={
                "event": "host_alive",
                "service": "orchestrator",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


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
    _stop_heartbeat = threading.Event()

    def _shutdown_handler(signum: int, _frame: object) -> None:
        nonlocal running
        running = False
        _stop_heartbeat.set()
        sig_name = signal.Signals(signum).name
        logger.info("Shutdown signal received: %s", sig_name)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    # -- Heartbeat thread ---------------------------------------------------
    _hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(_stop_heartbeat,),
        daemon=True,
        name="orchestrator-heartbeat",
    )
    _hb_thread.start()
    logger.info("Heartbeat thread started (interval=%ds)", _HEARTBEAT_INTERVAL_SECONDS)

    # -- Consumer loop ------------------------------------------------------
    consumer = ServiceBusConsumer(config)

    try:
        consumer.run(is_running=lambda: running)
    except Exception:
        logger.exception("Fatal error in orchestrator")
        sys.exit(1)
    finally:
        _stop_heartbeat.set()
        consumer.close()
        logger.info("Orchestrator stopped")


if __name__ == "__main__":
    main()
