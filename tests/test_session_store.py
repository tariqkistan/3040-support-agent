from azure.cosmos.exceptions import CosmosResourceNotFoundError

from app.session_store import CosmosConversationStore


class FakeContainer:
    def __init__(self):
        self.items = {}

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        return self.items[item]

    def upsert_item(self, item):
        self.items[item["id"]] = item


def test_cosmos_store_persists_mapping_with_expiration_and_caller_scope():
    container = FakeContainer()
    store = CosmosConversationStore(container, ttl_seconds=3600)

    store.save_conversation_id("caller-a", "conversation-1", "foundry-conv-1")

    assert store.get_conversation_id("caller-a", "conversation-1") == "foundry-conv-1"
    assert store.get_conversation_id("caller-b", "conversation-1") is None
    assert next(iter(container.items.values()))["ttl"] == 3600
