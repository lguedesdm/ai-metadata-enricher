"""
Unit tests for the Orchestrator configuration.

Verifies that configuration is correctly loaded from environment variables
and that missing required variables raise appropriate errors.
"""

import os

import pytest

from src.orchestrator.config import OrchestratorConfig


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig."""

    def test_loads_required_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config should load SERVICE_BUS_NAMESPACE from env."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")

        config = OrchestratorConfig()

        assert config.service_bus_namespace == "sb-test.servicebus.windows.net"

    def test_missing_namespace_raises_key_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing SERVICE_BUS_NAMESPACE should raise KeyError."""
        monkeypatch.delenv("SERVICE_BUS_NAMESPACE", raising=False)
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")

        with pytest.raises(KeyError):
            OrchestratorConfig()

    def test_missing_cosmos_endpoint_raises_key_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing COSMOS_ENDPOINT should raise KeyError — Cosmos is mandatory."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)

        with pytest.raises(KeyError):
            OrchestratorConfig()

    def test_default_queue_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default queue name should be 'metadata-ingestion'."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.delenv("SERVICE_BUS_QUEUE_NAME", raising=False)

        config = OrchestratorConfig()

        assert config.service_bus_queue_name == "metadata-ingestion"

    def test_custom_queue_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom queue name should be read from env."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.setenv("SERVICE_BUS_QUEUE_NAME", "custom-queue")

        config = OrchestratorConfig()

        assert config.service_bus_queue_name == "custom-queue"

    def test_default_max_wait_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default max_wait_time_seconds should be 30."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.delenv("MAX_WAIT_TIME_SECONDS", raising=False)

        config = OrchestratorConfig()

        assert config.max_wait_time_seconds == 30

    def test_custom_max_wait_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom max_wait_time_seconds from env."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.setenv("MAX_WAIT_TIME_SECONDS", "60")

        config = OrchestratorConfig()

        assert config.max_wait_time_seconds == 60

    def test_default_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default environment should be 'dev'."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        config = OrchestratorConfig()

        assert config.environment == "dev"

    def test_app_insights_connection_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """App Insights connection string should be loaded from env."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")
        monkeypatch.setenv(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test"
        )

        config = OrchestratorConfig()

        assert config.applicationinsights_connection_string == "InstrumentationKey=test"

    def test_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """repr should contain key config values."""
        monkeypatch.setenv("SERVICE_BUS_NAMESPACE", "sb-test.servicebus.windows.net")
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-test.documents.azure.com:443/")

        config = OrchestratorConfig()
        config_repr = repr(config)

        assert "sb-test.servicebus.windows.net" in config_repr
        assert "metadata-ingestion" in config_repr
