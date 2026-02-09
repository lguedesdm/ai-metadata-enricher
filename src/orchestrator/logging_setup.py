"""
Structured logging setup for the Orchestrator.

Configures:
- JSON-formatted logging to stdout (captured by Container Apps → Log Analytics)
- Application Insights integration when connection string is provided
- correlationId propagation via LogRecord extras
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional


class StructuredJsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON for structured ingestion.

    Every log line includes:
    - timestamp (ISO 8601 UTC)
    - level
    - logger
    - message
    - correlationId (if present in extra)
    - Any additional extra fields
    """

    # Fields that are part of the standard LogRecord and should not be
    # forwarded as custom properties.
    _BUILTIN_ATTRS = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Append any extra fields (correlationId, assetId, etc.)
        for key, value in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS and not key.startswith("_"):
                log_entry[key] = value

        # Append exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str, ensure_ascii=False)


def configure_logging(
    app_insights_connection_string: Optional[str] = None,
) -> None:
    """
    Configure structured logging for the orchestrator.

    Args:
        app_insights_connection_string: If provided, telemetry is also
            exported to Application Insights.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any pre-existing handlers
    root_logger.handlers.clear()

    # ---- stdout handler (JSON) ----
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(stdout_handler)

    # ---- Application Insights ----
    if app_insights_connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=app_insights_connection_string,
                enable_live_metrics=False,
            )
            logging.getLogger("orchestrator").info(
                "Application Insights configured successfully"
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("orchestrator").warning(
                "Failed to configure Application Insights: %s. "
                "Continuing with stdout logging only.",
                exc,
            )

    # Suppress noisy Azure SDK loggers
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("uamqp").setLevel(logging.WARNING)
