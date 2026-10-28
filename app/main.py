"""FastAPI entrypoint for the 3040 support agent.

POST /chat talks to the Foundry agent (built in stage 3); GET /health is
a liveness probe. The OpenAPI document is shaped for import into a
Copilot Studio custom connector: explicit operationIds, a named
X-API-Key security scheme, and descriptions on every operation.
"""

import hashlib
import logging
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.auth import verify_api_key
from app.config import Settings, get_settings
from app.copilot_openapi import build_copilot_openapi

logger = logging.getLogger("app.request")


def rate_limit_key(request: Request) -> str:
    """Share the demo limit across callers using the same connector key."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return hashlib.sha256(api_key.encode()).hexdigest()
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)

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


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        },
    )
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded."})


class ChatRequest(BaseModel):
    """A single user turn."""

    session_id: str = Field(
        ..., min_length=1, max_length=128,
        description="Opaque, unique conversation id supplied by the Copilot client.",
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
    session_id: str = Field(description="Conversation id to reuse for follow-up turns.")
    answer: str = Field(description="The agent's answer, grounded in the index.")
    sources: list[Source] = Field(default_factory=list)


@app.get(
    "/health",
    operation_id="healthCheck",
    summary="Liveness check",
    description="Returns 200 when the process is responding.",
)
async def health() -> dict:
    return {"status": "ok"}


@app.get("/copilot-openapi.json", include_in_schema=False)
async def copilot_openapi() -> dict:
    """Return Swagger 2.0 for Power Platform custom connector import."""
    return build_copilot_openapi(app.openapi())


@app.get(
    "/ready",
    operation_id="readinessCheck",
    summary="Configuration readiness check",
    description="Reports missing API configuration. Does not verify Azure connectivity.",
)
async def readiness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    missing = settings.missing_for_api()
    ready = not missing
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if ready else "not_ready", "missing_settings": missing},
    )


@app.post(
    "/chat",
    operation_id="chatWithSupportAgent",
    summary="Ask the support agent",
    description="Sends a message to the Foundry agent grounded in the "
                "indexed technical document. Replies cite section and page; "
                "out-of-scope questions are declined.",
    response_model=ChatResponse,
)
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    caller_id: Annotated[str, Depends(verify_api_key)],
) -> ChatResponse:
    if len(body.message) > settings.max_message_length:
        raise HTTPException(status_code=422, detail="Message exceeds maximum length.")
    from app.agent import run_agent_turn

    answer, sources = await run_agent_turn(
        caller_id, body.session_id, body.message, settings
    )
    return ChatResponse(
        session_id=body.session_id,
        answer=answer,
        sources=[Source(**s) for s in sources],
    )
