"""FastAPI wiring: the chat endpoint, the static chat UI, and a health probe.

Run with the `paypilot` script (installed via pip) or `uvicorn app.web:app`.
Without PayPal credentials the app runs in DEMO mode against a scripted in-memory
gateway, clearly labeled in /health and in the UI.
"""

from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import Settings
from app.copilot import Copilot, CopilotTurn, Session
from app.paypal import DemoPayPalClient, PayPalClient
from app.planner import LLMProvider, LocalPlanner, OpenAIPlanner

STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    text: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    status: str
    message: str
    mode: str
    data: dict | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app around one copilot; settings default to the environment."""
    settings = settings or Settings.from_env()
    if settings.paypal_configured:
        gateway: PayPalClient | DemoPayPalClient = PayPalClient(
            settings.paypal_client_id or "",
            settings.paypal_client_secret or "",
            base_url=settings.paypal_api_base,
        )
        mode = "sandbox"
    else:
        gateway = DemoPayPalClient()
        mode = "demo"
    provider: LLMProvider = (
        OpenAIPlanner(
            api_key=settings.openai_api_key or "",
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )
        if settings.llm_configured
        else LocalPlanner()
    )
    copilot = Copilot(gateway=gateway, provider=provider)
    sessions: dict[str, Session] = defaultdict(Session)

    app = FastAPI(title="PayPilot", description="An AI copilot for PayPal")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": mode, "planner": provider.name}

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> ChatResponse:
        turn: CopilotTurn = await copilot.handle_turn(request.text, sessions[request.session_id])
        return ChatResponse(
            status=turn.status, message=turn.message, mode=mode, data=turn.data
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def main() -> None:
    """Console-script entry point: serve PayPilot on localhost:8000."""
    import uvicorn

    uvicorn.run("app.web:app", host="127.0.0.1", port=8000)


app = create_app()
