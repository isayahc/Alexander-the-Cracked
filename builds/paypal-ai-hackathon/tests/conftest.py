"""Shared fixtures for the PayPilot test suite."""

import pytest

from app.config import Settings


@pytest.fixture
def demo_settings() -> Settings:
    """No credentials anywhere: the app under test runs in DEMO mode."""
    return Settings(
        paypal_client_id=None,
        paypal_client_secret=None,
        paypal_api_base="https://api-m.sandbox.paypal.com",
        ai_provider="local",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
    )
