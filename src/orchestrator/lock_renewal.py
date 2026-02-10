"""
Lock renewal manager for Service Bus messages.

Renews the lock on a Service Bus message at a fixed interval using a
background thread. This ensures that long-running message processing
does not lose the lock and cause the message to become visible to other
consumers.

This module uses a single daemon thread per message — never for
processing, only for lock renewal.
"""

import logging
import threading
from typing import Any

logger = logging.getLogger("orchestrator.lock_renewal")


class LockRenewer:
    """
    Renews the lock on a single Service Bus message periodically.

    Usage:
        renewer = LockRenewer(receiver, message, interval_seconds=15)
        renewer.start()
        try:
            process(message)
        finally:
            renewer.stop()
    """

    def __init__(
        self,
        receiver: Any,
        message: Any,
        interval_seconds: int = 15,
        correlation_id: str = "",
    ) -> None:
        self._receiver = receiver
        self._message = message
        self._interval_seconds = interval_seconds
        self._correlation_id = correlation_id
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._renewal_count = 0

    def start(self) -> None:
        """Start the lock renewal background thread."""
        self._stop_event.clear()
        self._renewal_count = 0
        self._thread = threading.Thread(
            target=self._renew_loop,
            daemon=True,
            name=f"lock-renewer-{self._correlation_id[:8]}",
        )
        self._thread.start()
        logger.debug(
            "Lock renewal started",
            extra={
                "correlationId": self._correlation_id,
                "intervalSeconds": self._interval_seconds,
            },
        )

    def stop(self) -> None:
        """Stop the lock renewal background thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.debug(
            "Lock renewal stopped",
            extra={
                "correlationId": self._correlation_id,
                "renewalCount": self._renewal_count,
            },
        )

    @property
    def renewal_count(self) -> int:
        """Number of successful lock renewals performed."""
        return self._renewal_count

    def _renew_loop(self) -> None:
        """Background loop that renews the message lock at intervals."""
        while not self._stop_event.wait(timeout=self._interval_seconds):
            try:
                self._receiver.renew_message_lock(self._message)
                self._renewal_count += 1
                logger.info(
                    "Lock renewed",
                    extra={
                        "correlationId": self._correlation_id,
                        "renewalCount": self._renewal_count,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Lock renewal failed: %s",
                    exc,
                    extra={
                        "correlationId": self._correlation_id,
                        "error": str(exc),
                    },
                )
                # Stop renewing — the message will eventually be
                # abandoned or the lock will expire naturally.
                break
