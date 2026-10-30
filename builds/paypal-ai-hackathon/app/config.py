"""Environment-driven settings for PayPilot."""

import os
from dataclasses import dataclass

from app.paypal import SANDBOX_BASE_URL

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, read from the environment (see .env.example)."""

    paypal_client_id: str | None
    paypal_client_secret: str | None
    paypal_api_base: str
    ai_provider: str  # "local" (default) or "openai"
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        return cls(
            paypal_client_id=source.get("PAYPAL_CLIENT_ID") or None,
            paypal_client_secret=source.get("PAYPAL_CLIENT_SECRET") or None,
            paypal_api_base=source.get("PAYPAL_API_BASE", SANDBOX_BASE_URL),
            ai_provider=(source.get("AI_PROVIDER") or "local").strip().lower(),
            openai_api_key=source.get("OPENAI_API_KEY") or None,
            openai_base_url=source.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            openai_model=source.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        )

    @property
    def paypal_configured(self) -> bool:
        """True when real sandbox credentials are present (else the demo gateway runs)."""
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def llm_configured(self) -> bool:
        """True when an OpenAI-compatible LLM should drive planning (else the local planner)."""
        return self.ai_provider == "openai" and bool(self.openai_api_key)
