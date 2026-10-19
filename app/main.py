"""FastAPI entrypoint for the 3040 support agent.

POST /chat talks to the Foundry agent (built in stage 3); GET /health is
a liveness probe. The OpenAPI document is shaped for import into a
Copilot Studio custom connector: explicit operationIds, a named
X-API-Key security scheme, and descriptions on every operation.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.auth import verify_api_key
from app.config import Settings, get_settings

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="3040 Support Agent",
    description=(
        "Technical support agent grounded in a single technical document "
        "via Azure AI Search and a Microsoft Foundry agent. Answers only "
        "from the indexed document and cites section and page."
    ),
    version="0.1.0",
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded."})


class ChatRequest(BaseModel):
    """A single user turn."""

    session_id: str = Field(
        ..., min_length=1, max_length=128,
        description="Caller-chosen conversation id; state is kept per session.",
    )
    message: str = Field(
        ..., min_length=1,
        description="The user's question.",
    )


class Source(BaseModel):
    """A citation back into the source document."""

    section: str = Field(description="Section/heading the answer came from.")
    page: int = Field(description="1-based page number in the source PDF.")


class ChatResponse(BaseModel):
    answer: str = Field(description="The agent's answer, grounded in the index.")
    sources: list[Source] = Field(default_factory=list)


@app.get(
    "/health",
    operation_id="healthCheck",
    summary="Liveness check",
    description="Returns 200 when the service is up. Reports which required "
                "settings are still empty (does not validate credentials).",
)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    missing = settings.missing_for_api()
    return {"status": "ok" if not missing else "degraded", "missing_settings": missing}


@app.post(
    "/chat",
    operation_id="chatWithSupportAgent",
    summary="Ask the support agent",
    description="Sends a message to the Foundry agent grounded in the "
                "indexed technical document. Replies cite section and page; "
                "out-of-scope questions are declined.",
    response_model=ChatResponse,
    dependencies=[Depends(verify_api_key)],
)
async def chat(
    body: ChatRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatResponse:
    if len(body.message) > settings.max_message_length:
        raise HTTPException(status_code=422, detail="Message exceeds maximum length.")
    from app.agent import run_agent_turn

    answer, sources = await run_agent_turn(body.session_id, body.message, settings)
    return ChatResponse(answer=answer, sources=[Source(**s) for s in sources])
