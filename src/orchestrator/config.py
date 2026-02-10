"""
Configuration for the Orchestrator.

All configuration is sourced from environment variables.
No secrets are stored in code — authentication uses Managed Identity.
"""

import os


class OrchestratorConfig:
    """Immutable configuration sourced from environment variables."""

    def __init__(self) -> None:
        # -----------------------------------------------------------------
        # Azure Service Bus
        # -----------------------------------------------------------------
        # Fully qualified namespace, e.g. "sb-ai-metadata-dev.servicebus.windows.net"
        self.service_bus_namespace: str = os.environ["SERVICE_BUS_NAMESPACE"]

        # Queue name to consume from
        self.service_bus_queue_name: str = os.environ.get(
            "SERVICE_BUS_QUEUE_NAME", "metadata-ingestion"
        )

        # Maximum time (seconds) to wait for a message before looping
        self.max_wait_time_seconds: int = int(
            os.environ.get("MAX_WAIT_TIME_SECONDS", "30")
        )

        # -----------------------------------------------------------------
        # Batching & Lock Management
        # -----------------------------------------------------------------
        # Maximum number of messages to receive per batch
        self.batch_size: int = int(
            os.environ.get("BATCH_SIZE", "5")
        )

        # Interval (seconds) between lock renewal attempts
        self.lock_renew_interval_seconds: int = int(
            os.environ.get("LOCK_RENEW_INTERVAL_SECONDS", "15")
        )

        # Maximum time (seconds) allowed for processing a single message
        self.message_timeout_seconds: int = int(
            os.environ.get("MESSAGE_TIMEOUT_SECONDS", "120")
        )

        # -----------------------------------------------------------------
        # Application Insights
        # -----------------------------------------------------------------
        self.applicationinsights_connection_string: str = os.environ.get(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
        )

        # -----------------------------------------------------------------
        # Runtime
        # -----------------------------------------------------------------
        self.environment: str = os.environ.get("ENVIRONMENT", "dev")

    def __repr__(self) -> str:
        return (
            f"OrchestratorConfig("
            f"namespace={self.service_bus_namespace!r}, "
            f"queue={self.service_bus_queue_name!r}, "
            f"env={self.environment!r})"
        )
