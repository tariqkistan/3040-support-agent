"""Cosmos DB persistence for caller-scoped Foundry conversation mappings."""

from functools import lru_cache
from hashlib import sha256

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

from app.config import Settings


class CosmosConversationStore:
    """Persist session-to-conversation mappings with server-side expiration."""

    def __init__(self, container, ttl_seconds: int) -> None:
        self._container = container
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _item_id(caller_id: str, session_id: str) -> str:
        key = f"{caller_id}\0{session_id}".encode()
        return sha256(key).hexdigest()

    def get_conversation_id(self, caller_id: str, session_id: str) -> str | None:
        item_id = self._item_id(caller_id, session_id)
        try:
            item = self._container.read_item(item=item_id, partition_key=item_id)
        except CosmosResourceNotFoundError:
            return None
        return item["conversation_id"]

    def save_conversation_id(
        self, caller_id: str, session_id: str, conversation_id: str
    ) -> None:
        item_id = self._item_id(caller_id, session_id)
        self._container.upsert_item(
            {
                "id": item_id,
                "conversation_id": conversation_id,
                "ttl": self._ttl_seconds,
            }
        )


@lru_cache(maxsize=8)
def _get_container(endpoint: str, database_name: str, container_name: str):
    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential)
    container = client.get_database_client(database_name).get_container_client(
        container_name
    )
    properties = container.read()
    if properties.get("defaultTtl", 0) == 0:
        raise RuntimeError(
            "The Cosmos DB session container must have TTL enabled "
            "(default TTL -1 or a positive value)."
        )
    return container


def get_cosmos_store(settings: Settings) -> CosmosConversationStore:
    container = _get_container(
        settings.azure_cosmos_endpoint,
        settings.azure_cosmos_database,
        settings.azure_cosmos_container,
    )
    return CosmosConversationStore(container, settings.session_ttl_seconds)
