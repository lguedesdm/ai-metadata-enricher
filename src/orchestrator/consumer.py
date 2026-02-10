"""
Azure Service Bus consumer for the Orchestrator.

Connects to Service Bus using Managed Identity (DefaultAzureCredential),
receives messages in peek-lock mode with batch support, and delegates
processing to the message handler.

Message completion semantics:
- Success (SKIP or REPROCESS) → message.complete()
- Unexpected error → message.abandon()  (returns to queue for retry)
- Processing timeout → message.abandon()

Features:
- Configurable batch receive (max_message_count via BATCH_SIZE)
- Sequential processing within each batch (no parallelisation)
- Manual lock renewal via background thread per message
- Per-message processing timeout
- Structured batch-level logging (start, end, size, duration)

This consumer does NOT:
- Implement manual dead-letter logic
- Parallelize message processing
- Implement advanced retry policies
- Create concurrent workers
"""

import logging
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusReceiveMode

from .config import OrchestratorConfig
from .cosmos_state_store import CosmosStateStore
from .lock_renewal import LockRenewer
from .message_handler import handle_message

logger = logging.getLogger("orchestrator.consumer")


class ServiceBusConsumer:
    """
    Single-threaded Service Bus consumer using peek-lock mode with
    batch receive and per-message lock renewal.

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
                "batchSize": config.batch_size,
                "lockRenewIntervalSeconds": config.lock_renew_interval_seconds,
                "messageTimeoutSeconds": config.message_timeout_seconds,
            },
        )

        self._client = ServiceBusClient(
            fully_qualified_namespace=config.service_bus_namespace,
            credential=self._credential,
        )

        # -- Cosmos DB State Store (Managed Identity) -------------------
        # COSMOS_ENDPOINT is mandatory — config enforces this at startup.
        self._state_store = CosmosStateStore(config)
        logger.info(
            "Cosmos DB state store wired — auth: Managed Identity",
            extra={
                "cosmosEndpoint": config.cosmos_endpoint,
                "authMethod": "ManagedIdentity/DefaultAzureCredential",
            },
        )

    # ------------------------------------------------------------------
    # Timeout helper
    # ------------------------------------------------------------------
    @staticmethod
    def _process_with_timeout(
        body: str,
        timeout_seconds: int,
        state_store: "CosmosStateStore | None" = None,
    ) -> "tuple[object | None, bool]":
        """
        Run handle_message in a thread with a timeout.

        Returns (result, timed_out).
        - If completed in time: (MessageProcessingResult, False)
        - If timed out:         (None, True)
        """
        with ThreadPoolExecutor(max_workers=1) as executor:
            future: Future = executor.submit(
                handle_message, body, state_store,
            )
            try:
                result = future.result(timeout=timeout_seconds)
                return result, False
            except Exception:
                # TimeoutError or execution error
                return None, True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self, is_running: Callable[[], bool]) -> None:
        """
        Receive and process batches of messages until is_running()
        returns False.

        For each batch:
        1. Log batch_start with batchId and size
        2. For each message (sequentially):
           a. Start lock renewal
           b. Process message via handle_message (with timeout)
           c. Complete or abandon based on result
           d. Stop lock renewal
        3. Log batch_end with total duration

        Args:
            is_running: Callable that returns True while the consumer
                should keep processing.
        """
        logger.info(
            "Consumer starting receive loop",
            extra={
                "queue": self._config.service_bus_queue_name,
                "maxWaitTimeSeconds": self._config.max_wait_time_seconds,
                "batchSize": self._config.batch_size,
                "messageTimeoutSeconds": self._config.message_timeout_seconds,
            },
        )

        with self._client.get_queue_receiver(
            queue_name=self._config.service_bus_queue_name,
            receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
        ) as receiver:
            logger.info("Connected to Service Bus queue, waiting for messages...")

            while is_running():
                messages = receiver.receive_messages(
                    max_message_count=self._config.batch_size,
                    max_wait_time=self._config.max_wait_time_seconds,
                )

                if not messages:
                    logger.debug("No messages received, continuing...")
                    continue

                # -- Batch bookkeeping ----------------------------------
                batch_id = str(uuid.uuid4())
                batch_size = len(messages)
                batch_start = time.monotonic()

                logger.info(
                    "batch_start",
                    extra={
                        "batchId": batch_id,
                        "batchSize": batch_size,
                    },
                )

                # -- Process each message sequentially ------------------
                for index, message in enumerate(messages):
                    msg_correlation_id = str(uuid.uuid4())

                    renewer = LockRenewer(
                        receiver=receiver,
                        message=message,
                        interval_seconds=self._config.lock_renew_interval_seconds,
                        correlation_id=msg_correlation_id,
                    )
                    renewer.start()

                    try:
                        body = str(message)

                        result, timed_out = self._process_with_timeout(
                            body,
                            self._config.message_timeout_seconds,
                            state_store=self._state_store,
                        )

                        if timed_out:
                            receiver.abandon_message(message)
                            logger.warning(
                                "Message abandoned due to processing timeout",
                                extra={
                                    "correlationId": msg_correlation_id,
                                    "batchId": batch_id,
                                    "messageIndex": index,
                                    "timeoutSeconds": self._config.message_timeout_seconds,
                                },
                            )
                            continue

                        if result.success:
                            receiver.complete_message(message)
                            logger.info(
                                "Message completed",
                                extra={
                                    "correlationId": result.correlation_id,
                                    "batchId": batch_id,
                                    "messageIndex": index,
                                    "assetId": result.asset_id,
                                    "decision": result.decision,
                                },
                            )
                        else:
                            receiver.abandon_message(message)
                            logger.warning(
                                "Message abandoned due to processing error",
                                extra={
                                    "correlationId": result.correlation_id,
                                    "batchId": batch_id,
                                    "messageIndex": index,
                                    "error": result.error,
                                },
                            )

                    except Exception as exc:
                        logger.error(
                            "Unexpected error handling message: %s",
                            exc,
                            exc_info=True,
                            extra={
                                "correlationId": msg_correlation_id,
                                "batchId": batch_id,
                                "messageIndex": index,
                            },
                        )
                        try:
                            receiver.abandon_message(message)
                        except Exception as abandon_exc:
                            logger.error(
                                "Failed to abandon message: %s",
                                abandon_exc,
                                exc_info=True,
                                extra={
                                    "correlationId": msg_correlation_id,
                                    "batchId": batch_id,
                                },
                            )
                    finally:
                        renewer.stop()

                # -- Batch complete -------------------------------------
                batch_duration = time.monotonic() - batch_start
                logger.info(
                    "batch_end",
                    extra={
                        "batchId": batch_id,
                        "batchSize": batch_size,
                        "batchDurationSeconds": round(batch_duration, 3),
                    },
                )

        logger.info("Consumer stopped")

    def close(self) -> None:
        """Close the Service Bus client, state store, and credential."""
        try:
            self._client.close()
            self._state_store.close()
            self._credential.close()
            logger.info("Service Bus consumer closed")
        except Exception as exc:
            logger.warning("Error closing consumer: %s", exc)
