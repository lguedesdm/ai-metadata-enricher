"""
Unit tests for the lock renewal manager.

Verifies that:
- Lock renewal starts and stops correctly
- The renew loop calls receiver.renew_message_lock at the expected interval
- Renewal stops cleanly when stop() is called
- Failed renewal is handled gracefully (logged, loop exits)
- renewal_count tracks successful renewals

All Service Bus interactions are mocked — no real Azure connections.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.orchestrator.lock_renewal import LockRenewer


class TestLockRenewerStartStop:
    """Tests for basic start/stop lifecycle."""

    def test_start_creates_daemon_thread(self) -> None:
        """Starting the renewer should spawn a daemon thread."""
        receiver = MagicMock()
        message = MagicMock()

        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=60,
            correlation_id="test-id",
        )
        renewer.start()

        assert renewer._thread is not None
        assert renewer._thread.daemon is True
        assert renewer._thread.is_alive()

        renewer.stop()

    def test_stop_terminates_thread(self) -> None:
        """Stopping the renewer should terminate the background thread."""
        receiver = MagicMock()
        message = MagicMock()

        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=60,
            correlation_id="test-id",
        )
        renewer.start()
        renewer.stop()

        assert renewer._thread is None

    def test_stop_without_start_is_safe(self) -> None:
        """Calling stop() without start() should not raise."""
        receiver = MagicMock()
        message = MagicMock()

        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=60,
        )
        renewer.stop()  # Should not raise


class TestLockRenewerRenewal:
    """Tests for actual lock renewal behaviour."""

    def test_renews_lock_at_interval(self) -> None:
        """Renewer should call renew_message_lock after each interval."""
        receiver = MagicMock()
        message = MagicMock()

        # Use a very short interval so the test runs fast
        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=0.05,
            correlation_id="renew-test",
        )
        renewer.start()

        # Wait long enough for at least 2 renewals
        time.sleep(0.2)
        renewer.stop()

        assert receiver.renew_message_lock.call_count >= 2
        assert renewer.renewal_count >= 2
        # Every call should have been with the same message
        for call in receiver.renew_message_lock.call_args_list:
            assert call.args[0] is message

    def test_renewal_count_starts_at_zero(self) -> None:
        """renewal_count should be 0 before any renewal occurs."""
        receiver = MagicMock()
        message = MagicMock()

        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=60,
            correlation_id="count-test",
        )

        assert renewer.renewal_count == 0


class TestLockRenewerFailure:
    """Tests for renewal failure handling."""

    def test_stops_on_renewal_failure(self) -> None:
        """If renew_message_lock raises, the loop should exit."""
        receiver = MagicMock()
        receiver.renew_message_lock.side_effect = Exception("Lock lost")
        message = MagicMock()

        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=0.05,
            correlation_id="fail-test",
        )
        renewer.start()

        # Wait for the first attempt + exit
        time.sleep(0.2)
        renewer.stop()

        # Should have attempted exactly once and then stopped
        assert receiver.renew_message_lock.call_count == 1
        assert renewer.renewal_count == 0

    def test_no_unhandled_exception_on_failure(self) -> None:
        """Renewal failure should be handled gracefully, not propagate."""
        receiver = MagicMock()
        receiver.renew_message_lock.side_effect = RuntimeError("connection reset")
        message = MagicMock()

        renewer = LockRenewer(
            receiver=receiver,
            message=message,
            interval_seconds=0.05,
            correlation_id="safe-fail-test",
        )
        renewer.start()
        time.sleep(0.15)
        renewer.stop()

        # If we get here without an exception, the test passes
        assert renewer.renewal_count == 0
