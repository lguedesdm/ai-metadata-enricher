"""
Azure Service Bus consumer for the Orchestrator.

Connects to Service Bus using Managed Identity (DefaultAzureCredential),
receives messages in peek-lock mode, and delegates processing to the
message handler.

Message completion semantics:
- Success (SKIP or REPROCESS) → message.complete()
- Unexpected error → message.abandon()  (returns to queue for retry)

This consumer does NOT:
- Implement manual dead-letter logic
- Parallelize consumption
- Implement advanced retry policies
- Implement batch processing
"""

import logging
from typing import Callable

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusReceiveMode

from .config import OrchestratorConfig
from .message_handler import handle_message

logger = logging.getLogger("orchestrator.consumer")


class ServiceBusConsumer:
    """
    Single-threaded Service Bus consumer using peek-lock mode.

    Lifecycle:
        consumer = ServiceBusConsumer(config)
        consumer.run(running_check)   # blocks until running_check() → False
        consumer.close()
    """

    def __init__(self, config: OrchestratorConfig) -> None:
        self._config = config
        self._credential = DefaultAzureCredential()

        logger.info(
            "Initializing Service Bus consumer",
            extra={
                "namespace": config.service_bus_namespace,
                "queue": config.service_bus_queue_name,
            },
        )

        self._client = ServiceBusClient(
            fully_qualified_namespace=config.service_bus_namespace,
            credential=self._credential,
        )

    def run(self, is_running: Callable[[], bool]) -> None:
        """
        Receive and process messages until is_running() returns False.

        Each message is processed sequentially:
        1. Receive one message (peek-lock)
        2. Delegate to handle_message()
        3. Complete or abandon based on result

        Args:
            is_running: Callable that returns True while the consumer
                should keep processing.
        """
        logger.info(
            "Consumer starting receive loop",
            extra={
                "queue": self._config.service_bus_queue_name,
                "maxWaitTimeSeconds": self._config.max_wait_time_seconds,
            },
        )

        with self._client.get_queue_receiver(
            queue_name=self._config.service_bus_queue_name,
            receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
        ) as receiver:
            logger.info("Connected to Service Bus queue, waiting for messages...")

            while is_running():
                messages = receiver.receive_messages(
                    max_message_count=1,
                    max_wait_time=self._config.max_wait_time_seconds,
                )

                if not messages:
                    logger.debug("No messages received, continuing...")
                    continue

                message = messages[0]

                try:
                    # Extract body
                    body = str(message)

                    # Process
                    result = handle_message(body)

                    if result.success:
                        # Both SKIP and REPROCESS → complete
                        # (no side-effects in this minimal orchestrator)
                        receiver.complete_message(message)
                        logger.info(
                            "Message completed",
                            extra={
                                "correlationId": result.correlation_id,
                                "assetId": result.asset_id,
                                "decision": result.decision,
                            },
                        )
                    else:
                        # Processing error → abandon (return to queue)
                        receiver.abandon_message(message)
                        logger.warning(
                            "Message abandoned due to processing error",
                            extra={
                                "correlationId": result.correlation_id,
                                "error": result.error,
                            },
                        )

                except Exception as exc:
                    # Unexpected error in the receive/complete flow
                    logger.error(
                        "Unexpected error handling message: %s",
                        exc,
                        exc_info=True,
                    )
                    try:
                        receiver.abandon_message(message)
                    except Exception as abandon_exc:
                        logger.error(
                            "Failed to abandon message: %s",
                            abandon_exc,
                            exc_info=True,
                        )

        logger.info("Consumer stopped")

    def close(self) -> None:
        """Close the Service Bus client and credential."""
        try:
            self._client.close()
            self._credential.close()
            logger.info("Service Bus consumer closed")
        except Exception as exc:
            logger.warning("Error closing consumer: %s", exc)
