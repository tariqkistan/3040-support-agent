"""Microsoft Foundry agent: creation, sessions, and turn execution.

Design notes:
* The agent is a *prompt agent* on the Foundry project with one tool:
  the project's Azure AI Search connection pointed at our chunk index.
  The model cannot answer from memory — grounding comes only from the index.
* Conversation state lives server-side in Foundry *conversations*
  (the v2 SDK wraps the OpenAI Responses protocol). We keep a
  session_id -> conversation_id map so POST /chat stays stateless.
* Citations: the agent is instructed to end every grounded answer with
  `Sources: <section title> — p. <page>` lines. We parse those into the
  structured `sources` field the API returns (and the evals check).
"""

import asyncio
import re

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    PromptAgentDefinition,
)
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from app.config import Settings

AGENT_NAME = "support-agent-3040"

INSTRUCTIONS = """You are a technical support agent for the product documented in the
Azure AI Search index you are connected to.

Rules:
1. Answer ONLY using information retrieved from the search index. Never use
   outside knowledge.
2. Every answer that uses retrieved content must end with source lines in
   exactly this format, one per source used:
   Sources: <section title> — p. <page number>
   (repeat the line for each source)
3. If retrieval returns nothing relevant, say you don't know and suggest the
   user contact support. Do NOT invent an answer, and do NOT list sources.
4. Keep answers concise and procedural. Quote exact values, part numbers, and
   steps from the document.
"""

SOURCES_LINE = re.compile(r"^Sources?:\s*(.+?)\s*[—–-]\s*p\.?\s*(\d+)\s*$", re.IGNORECASE)

# (caller_id, session_id) -> Foundry conversation id. This store is only used
# for local development; hosted deployments should configure Cosmos DB.
_conversations: dict[tuple[str, str], str] = {}


def _get_or_create_agent(project: AIProjectClient, settings: Settings):
    """Reuse the latest Foundry agent version, creating it only if absent."""
    try:
        existing = project.agents.get(agent_name=AGENT_NAME)
    except ResourceNotFoundError:
        existing = None
    if existing is not None:
        latest = getattr(getattr(existing, "versions", None), "latest", None)
        if latest is not None:
            return latest

    connection = project.connections.get(settings.azure_search_connection_name)
    return project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=settings.agent_model_deployment,
            instructions=INSTRUCTIONS,
            tools=[
                AzureAISearchTool(
                    azure_ai_search=AzureAISearchToolResource(
                        indexes=[
                            AISearchIndexResource(
                                project_connection_id=connection.id,
                                index_name=settings.azure_search_index,
                                query_type=AzureAISearchQueryType(
                                    settings.search_query_type
                                ),
                                top_k=10,
                            )
                        ]
                    )
                )
            ],
        ),
        description="Technical support agent grounded in the product manual.",
    )


def parse_sources(answer: str) -> tuple[str, list[dict]]:
    """Split `Sources: ...` lines off the answer into structured citations."""
    sources: list[dict] = []
    kept_lines: list[str] = []
    for line in answer.splitlines():
        m = SOURCES_LINE.match(line.strip())
        if m:
            sources.append({"section": m.group(1).strip(), "page": int(m.group(2))})
        else:
            kept_lines.append(line)
    # Drop a bare trailing "Sources:" heading with no entries
    text = "\n".join(kept_lines).strip()
    text = re.sub(r"\n*Sources?:\s*$", "", text).strip()
    return text, sources


def _run_turn_sync(
    caller_id: str, session_id: str, message: str, settings: Settings
) -> tuple[str, list[dict]]:
    credential = DefaultAzureCredential()
    with AIProjectClient(
        endpoint=settings.azure_ai_project_endpoint, credential=credential
    ) as project:
        agent = _get_or_create_agent(project, settings)
        with project.get_openai_client() as openai:
            if settings.session_store_backend == "cosmos":
                from app.session_store import get_cosmos_store

                store = get_cosmos_store(settings)
                conversation_id = store.get_conversation_id(caller_id, session_id)
            else:
                store = None
                conversation_id = _conversations.get((caller_id, session_id))

            if conversation_id is None:
                conv = openai.conversations.create(
                    items=[
                        {"type": "message", "role": "user", "content": message}
                    ]
                )
                conversation_id = conv.id
                if store is not None:
                    store.save_conversation_id(caller_id, session_id, conversation_id)
                else:
                    _conversations[(caller_id, session_id)] = conversation_id
            else:
                openai.conversations.items.create(
                    conversation_id=conversation_id,
                    items=[{"type": "message", "role": "user", "content": message}],
                )
            response = openai.responses.create(
                conversation=conversation_id,
                extra_body={
                    "agent_reference": {"name": agent.name, "type": "agent_reference"}
                },
            )
    return parse_sources(_final_message_text(response))


def _final_message_text(response) -> str:
    """Extract the last assistant message from a Responses result.

    output_text concatenates ALL text output — including commentary like
    'I'll search the docs now' — so we take the final assistant message.
    """
    texts = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
            for part in getattr(item, "content", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)
    if texts:
        return texts[-1]
    return getattr(response, "output_text", "") or ""


async def run_agent_turn(
    caller_id: str, session_id: str, message: str, settings: Settings
) -> tuple[str, list[dict]]:
    """Async wrapper; the Foundry SDK is synchronous, so run off-thread."""
    return await asyncio.to_thread(
        _run_turn_sync, caller_id, session_id, message, settings
    )


def reset_sessions() -> None:
    """Drop all session->conversation mappings (used by tests and evals)."""
    _conversations.clear()
