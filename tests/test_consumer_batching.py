"""
Unit tests for the Service Bus consumer with batching, lock renewal
and per-message timeout.

Verifies that:
- Batch receive uses configured batch_size and max_wait_time
- Messages within a batch are processed sequentially
- Lock renewal is started and stopped for each message
- Successful messages are completed (SKIP or REPROCESS)
- Failed messages are abandoned
- Timed-out messages are abandoned
- Batch logging includes batchId, size, and duration
- Decision semantics are preserved (SKIP → complete, REPROCESS → complete,
  error → abandon)

All Azure Service Bus interactions are mocked — no real connections.
"""

import json
import time
from unittest.mock import MagicMock, patch, call

import pytest

from src.orchestrator.config import OrchestratorConfig
from src.orchestrator.consumer import ServiceBusConsumer
from src.orchestrator.message_handler import MessageProcessingResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ASSET = json.dumps({
    "id": "synergy.student.enrollment.table",
    "sourceSystem": "synergy",
    "entityType": "table",
    "entityName": "Student Enrollment",
    "entityPath": "synergy.student.enrollment",
    "description": "Stores student enrollment records.",
    "domain": "Student Information",
    "tags": ["enrollment", "student"],
    "content": "Student Enrollment table in Synergy.",
    "lastUpdated": "2026-02-02T12:00:00Z",
    "schemaVersion": "1.0.0",
})


def _make_config(
    monkeypatch: pytest.MonkeyPatch,
    batch_size: int = 5,
    lock_renew_interval: int = 15,
    message_timeout: int = 120,
    max_wait_time: int = 5,
) -> OrchestratorConfig:
    """Create an OrchestratorConfig with test-friendly defaults."""
    monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
    monkeypatch.setenv("SERVICE_BUS_QUEUE_NAME", "test-queue")
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
    monkeypatch.setenv("BATCH_SIZE", str(batch_size))
    monkeypatch.setenv("LOCK_RENEW_INTERVAL_SECONDS", str(lock_renew_interval))
    monkeypatch.setenv("MESSAGE_TIMEOUT_SECONDS", str(message_timeout))
    monkeypatch.setenv("MAX_WAIT_TIME_SECONDS", str(max_wait_time))
    # Prevent real Cosmos DB connections in unit tests
    monkeypatch.setattr(
        "src.orchestrator.consumer.CosmosStateStore", MagicMock()
    )
    return OrchestratorConfig()


def _make_mock_message(body: str = VALID_ASSET) -> MagicMock:
    """Create a mock Service Bus message."""
    msg = MagicMock()
    msg.__str__ = MagicMock(return_value=body)
    return msg


def _run_one_batch(consumer, messages):
    """Run the consumer for exactly one batch, then stop."""
    call_count = 0
    receiver = MagicMock()
    receiver.receive_messages.side_effect = [messages, []]

    def is_running():
        nonlocal call_count
        call_count += 1
        # Allow two iterations: one to process, one to exit
        return call_count <= 2

    return consumer, receiver, is_running


# ---------------------------------------------------------------------------
# Tests: Config new env vars
# ---------------------------------------------------------------------------


class TestConfigBatchingVars:
    """Tests for new configuration env vars."""

    def test_default_batch_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.delenv("BATCH_SIZE", raising=False)
        config = OrchestratorConfig()
        assert config.batch_size == 5

    def test_custom_batch_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.setenv("BATCH_SIZE", "10")
        config = OrchestratorConfig()
        assert config.batch_size == 10

    def test_default_lock_renew_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.delenv("LOCK_RENEW_INTERVAL_SECONDS", raising=False)
        config = OrchestratorConfig()
        assert config.lock_renew_interval_seconds == 15

    def test_custom_lock_renew_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.setenv("LOCK_RENEW_INTERVAL_SECONDS", "30")
        config = OrchestratorConfig()
        assert config.lock_renew_interval_seconds == 30

    def test_default_message_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.delenv("MESSAGE_TIMEOUT_SECONDS", raising=False)
        config = OrchestratorConfig()
        assert config.message_timeout_seconds == 120

    def test_custom_message_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.setenv("MESSAGE_TIMEOUT_SECONDS", "60")
        config = OrchestratorConfig()
        assert config.message_timeout_seconds == 60


# ---------------------------------------------------------------------------
# Tests: Batching
# ---------------------------------------------------------------------------


class TestConsumerBatching:
    """Tests verifying batch receive and sequential processing."""

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_batch_receive_uses_config_batch_size(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """receive_messages should be called with configured batch_size."""
        config = _make_config(monkeypatch, batch_size=3)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [
            [_make_mock_message()],
            [],
        ]

        mock_handle_message.return_value = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )
        mock_renewer_instance = MagicMock()
        mock_lock_renewer_cls.return_value = mock_renewer_instance

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        first_call = mock_receiver.receive_messages.call_args_list[0]
        assert first_call.kwargs["max_message_count"] == 3

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_all_messages_in_batch_processed_sequentially(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All messages in a batch should be processed, one at a time."""
        config = _make_config(monkeypatch, batch_size=3)
        consumer = ServiceBusConsumer(config)

        messages = [_make_mock_message() for _ in range(3)]

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [messages, []]

        mock_handle_message.return_value = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )
        mock_renewer_instance = MagicMock()
        mock_lock_renewer_cls.return_value = mock_renewer_instance

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        # handle_message called once per message
        assert mock_handle_message.call_count == 3
        # Each message completed
        assert mock_receiver.complete_message.call_count == 3

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_empty_batch_continues_loop(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no messages are received, the loop should continue."""
        config = _make_config(monkeypatch)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.return_value = []

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 3

        consumer.run(is_running)

        mock_handle_message.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Lock Renewal Integration
# ---------------------------------------------------------------------------


class TestConsumerLockRenewal:
    """Tests verifying lock renewal lifecycle per message."""

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_lock_renewer_started_and_stopped_per_message(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each message should get its own LockRenewer, started then stopped."""
        config = _make_config(monkeypatch, batch_size=2)
        consumer = ServiceBusConsumer(config)

        messages = [_make_mock_message(), _make_mock_message()]

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [messages, []]

        mock_handle_message.return_value = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )

        renewer_instances = [MagicMock(), MagicMock()]
        mock_lock_renewer_cls.side_effect = renewer_instances

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        # Two LockRenewer instances created
        assert mock_lock_renewer_cls.call_count == 2
        # Each started and stopped
        for renewer in renewer_instances:
            renewer.start.assert_called_once()
            renewer.stop.assert_called_once()

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_lock_renewer_uses_configured_interval(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LockRenewer should be created with the configured interval."""
        config = _make_config(monkeypatch, lock_renew_interval=25)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        mock_handle_message.return_value = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        create_call = mock_lock_renewer_cls.call_args
        assert create_call.kwargs["interval_seconds"] == 25

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_lock_renewer_stopped_even_on_error(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LockRenewer.stop() must be called even if processing raises."""
        config = _make_config(monkeypatch, batch_size=1)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        # Simulate an unexpected error in _process_with_timeout
        mock_handle_message.side_effect = RuntimeError("boom")

        renewer_instance = MagicMock()
        mock_lock_renewer_cls.return_value = renewer_instance

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        # Even with error, stop() must have been called (finally block)
        renewer_instance.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Message Timeout
# ---------------------------------------------------------------------------


class TestConsumerTimeout:
    """Tests verifying per-message processing timeout."""

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.ServiceBusConsumer._process_with_timeout")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_timed_out_message_is_abandoned(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_process,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A message that times out should be abandoned, not completed."""
        config = _make_config(monkeypatch, message_timeout=1)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        # Simulate timeout
        mock_process.return_value = (None, True)
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        mock_receiver.abandon_message.assert_called_once()
        mock_receiver.complete_message.assert_not_called()

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.ServiceBusConsumer._process_with_timeout")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_non_timed_out_message_is_completed(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_process,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A message that completes in time should be completed normally."""
        config = _make_config(monkeypatch, message_timeout=120)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        result = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )
        mock_process.return_value = (result, False)
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        mock_receiver.complete_message.assert_called_once()
        mock_receiver.abandon_message.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Decision Semantics Preserved
# ---------------------------------------------------------------------------


class TestConsumerDecisionSemantics:
    """Tests verifying SKIP → complete, REPROCESS → complete, error → abandon."""

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.ServiceBusConsumer._process_with_timeout")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_skip_decision_completes_message(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_process,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SKIP decision → message should be completed."""
        config = _make_config(monkeypatch, batch_size=1)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        result = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="SKIP", success=True
        )
        mock_process.return_value = (result, False)
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        mock_receiver.complete_message.assert_called_once()
        mock_receiver.abandon_message.assert_not_called()

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.ServiceBusConsumer._process_with_timeout")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_reprocess_decision_completes_message(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_process,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """REPROCESS decision → message should be completed."""
        config = _make_config(monkeypatch, batch_size=1)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        result = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )
        mock_process.return_value = (result, False)
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        mock_receiver.complete_message.assert_called_once()
        mock_receiver.abandon_message.assert_not_called()

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.ServiceBusConsumer._process_with_timeout")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_error_result_abandons_message(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_process,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Error in processing → message should be abandoned."""
        config = _make_config(monkeypatch, batch_size=1)
        consumer = ServiceBusConsumer(config)

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [[_make_mock_message()], []]

        result = MessageProcessingResult(
            correlation_id="test",
            asset_id="unknown",
            decision=None,
            success=False,
            error="parse error",
        )
        mock_process.return_value = (result, False)
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        consumer.run(is_running)

        mock_receiver.abandon_message.assert_called_once()
        mock_receiver.complete_message.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Batch Logging
# ---------------------------------------------------------------------------


class TestConsumerBatchLogging:
    """Tests verifying batch-level structured logging."""

    @patch("src.orchestrator.consumer.LockRenewer")
    @patch("src.orchestrator.consumer.handle_message")
    @patch("src.orchestrator.consumer.DefaultAzureCredential")
    @patch("src.orchestrator.consumer.ServiceBusClient")
    def test_batch_start_and_end_logged(
        self,
        mock_sb_client_cls,
        mock_cred_cls,
        mock_handle_message,
        mock_lock_renewer_cls,
        monkeypatch: pytest.MonkeyPatch,
        caplog,
    ) -> None:
        """batch_start and batch_end should be logged for each batch."""
        config = _make_config(monkeypatch, batch_size=2)
        consumer = ServiceBusConsumer(config)

        messages = [_make_mock_message(), _make_mock_message()]

        mock_receiver = MagicMock()
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__enter__ = (
            MagicMock(return_value=mock_receiver)
        )
        mock_sb_client_cls.return_value.get_queue_receiver.return_value.__exit__ = (
            MagicMock(return_value=False)
        )
        mock_receiver.receive_messages.side_effect = [messages, []]

        mock_handle_message.return_value = MessageProcessingResult(
            correlation_id="test", asset_id="test", decision="REPROCESS", success=True
        )
        mock_lock_renewer_cls.return_value = MagicMock()

        call_count = 0

        def is_running():
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        import logging as _logging

        with caplog.at_level(_logging.INFO, logger="orchestrator.consumer"):
            consumer.run(is_running)

        log_messages = [r.message for r in caplog.records]
        assert "batch_start" in log_messages
        assert "batch_end" in log_messages


# ---------------------------------------------------------------------------
# Tests: _process_with_timeout
# ---------------------------------------------------------------------------


class TestProcessWithTimeout:
    """Tests for the static timeout helper."""

    @patch("src.orchestrator.consumer.handle_message")
    def test_returns_result_when_fast_enough(self, mock_handle) -> None:
        """Should return (result, False) when processing is fast."""
        expected = MessageProcessingResult(
            correlation_id="t", asset_id="a", decision="REPROCESS", success=True
        )
        mock_handle.return_value = expected

        result, timed_out = ServiceBusConsumer._process_with_timeout("body", 5)

        assert timed_out is False
        assert result is expected

    @patch("src.orchestrator.consumer.handle_message")
    def test_returns_timeout_when_too_slow(self, mock_handle) -> None:
        """Should return (None, True) when processing exceeds timeout."""

        def slow_handler(body):
            time.sleep(5)
            return MessageProcessingResult(
                correlation_id="t", asset_id="a", decision="REPROCESS", success=True
            )

        mock_handle.side_effect = slow_handler

        result, timed_out = ServiceBusConsumer._process_with_timeout("body", 0.1)

        assert timed_out is True
        assert result is None
