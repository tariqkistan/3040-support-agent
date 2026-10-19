"""Extract, chunk, embed, and upload the source PDF to Azure AI Search.

Usage:
    python -m ingest.ingest [path-to-pdf]

Auth: DefaultAzureCredential everywhere (Entra ID). You need
`az login` locally, or the workload identity in CI.

Idempotent: re-running deletes the document's existing chunks first, then
re-uploads — no duplicates.
"""

import sys
import time
from pathlib import Path

from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from app.config import get_settings
from ingest.chunking import Chunk, chunk_blocks, extract_blocks

DEFAULT_PDF = Path(__file__).resolve().parent.parent / "data" / "docs" / "source.pdf"
EMBED_BATCH = 16
UPLOAD_BATCH = 100


def build_index(settings) -> SearchIndex:
    """Index schema: keyword-searchable text + vector + semantic ranker."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=settings.embedding_dimensions,
            vector_search_profile_name="hnsw-profile",
        ),
        SimpleField(
            name="page_number", type=SearchFieldDataType.Int32, filterable=True
        ),
        SearchableField(
            name="section_title", type=SearchFieldDataType.String, filterable=True
        ),
        SimpleField(
            name="source_file", type=SearchFieldDataType.String, filterable=True
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[
            VectorSearchProfile(
                name="hnsw-profile",
                algorithm_configuration_name="hnsw",
                vectorizer_name="aoai-vectorizer",
            )
        ],
        vectorizers=[
            # Lets the Foundry agent vectorize queries at search time using the
            # account's managed identity — no keys.
            AzureOpenAIVectorizer(
                vectorizer_name="aoai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=settings.azure_openai_endpoint,
                    deployment_name=settings.embedding_model_deployment,
                    model_name=settings.embedding_model_deployment,
                ),
            )
        ],
    )
    semantic = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="section_title")],
                ),
            )
        ]
    )
    return SearchIndex(
        name=settings.azure_search_index,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic,
    )


def ensure_index(settings, credential: TokenCredential) -> None:
    client = SearchIndexClient(settings.azure_search_endpoint, credential)
    client.create_or_update_index(build_index(settings))
    print(f"Index '{settings.azure_search_index}' ready (hybrid + semantic).")


def delete_existing_chunks(settings, credential: TokenCredential, source_file: str) -> int:
    """Remove all chunks for this source file so re-runs can't duplicate."""
    search = SearchClient(
        settings.azure_search_endpoint, settings.azure_search_index, credential
    )
    stale = [
        {"id": doc["id"]}
        for doc in search.search(
            "*", filter=f"source_file eq '{source_file}'", select=["id"]
        )
    ]
    if stale:
        search.delete_documents(stale)
    return len(stale)


def embed_chunks(chunks: list[Chunk], settings, credential: TokenCredential) -> list[list[float]]:
    """Vectorize chunk content with the account's embedding deployment."""
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI

    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-10-21",
    )
    vectors: list[list[float]] = []
    with client as openai_client:
        for i in range(0, len(chunks), EMBED_BATCH):
            batch = [c.content for c in chunks[i : i + EMBED_BATCH]]
            resp = _embed_with_retry(openai_client, settings, batch)
            vectors.extend(item.embedding for item in resp.data)
    return vectors


def _embed_with_retry(openai_client, settings, batch, attempts: int = 6):
    """Retry on 429s: small deployments hit the tier's TPM cap quickly."""
    from openai import RateLimitError

    for attempt in range(attempts):
        try:
            return openai_client.embeddings.create(
                model=settings.embedding_model_deployment, input=batch
            )
        except RateLimitError:
            if attempt == attempts - 1:
                raise
            wait = 65
            print(f"  rate limited, retrying in {wait}s (batch retry {attempt + 1})")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def upload_chunks(chunks, vectors, settings, credential) -> int:
    search = SearchClient(
        settings.azure_search_endpoint, settings.azure_search_index, credential
    )
    docs = [
        {
            "id": c.id,
            "content": c.content,
            "content_vector": v,
            "page_number": c.page_number,
            "section_title": c.section_title,
            "source_file": c.source_file,
        }
        for c, v in zip(chunks, vectors, strict=True)
    ]
    uploaded = 0
    for i in range(0, len(docs), UPLOAD_BATCH):
        result = search.upload_documents(docs[i : i + UPLOAD_BATCH])
        uploaded += sum(1 for r in result if r.succeeded)
    return uploaded


def main() -> int:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}. Drop one into data/docs/.")
        return 1
    settings = get_settings()
    missing = [
        k
        for k in ("azure_openai_endpoint", "azure_search_endpoint")
        if not getattr(settings, k)
    ]
    if missing:
        print(f"Missing settings: {', '.join(missing)} — fill in .env first.")
        return 1

    t0 = time.time()
    n_pages, blocks = extract_blocks(str(pdf_path))
    chunks = chunk_blocks(blocks, source_file=pdf_path.name)
    print(f"Extracted {len(blocks)} blocks from {n_pages} pages -> {len(chunks)} chunks")

    credential = DefaultAzureCredential()
    ensure_index(settings, credential)
    removed = delete_existing_chunks(settings, credential, pdf_path.name)
    if removed:
        print(f"Removed {removed} stale chunks for {pdf_path.name}")

    print(f"Embedding {len(chunks)} chunks with '{settings.embedding_model_deployment}'...")
    vectors = embed_chunks(chunks, settings, credential)
    uploaded = upload_chunks(chunks, vectors, settings, credential)

    avg_tokens = sum(c.token_count for c in chunks) // max(len(chunks), 1)
    print("\n=== Ingest summary ===")
    print(f"Pages:            {n_pages}")
    print(f"Chunks uploaded:  {uploaded}")
    print(f"Avg chunk size:   {avg_tokens} tokens")
    print(f"Elapsed:          {time.time() - t0:.1f}s")
    print("\n=== Sample chunks ===")
    for c in chunks[:3]:
        print(f"\n--- {c.id} | p.{c.page_number} | {c.section_title or '(no section)'} ---")
        print(c.content[:400] + ("..." if len(c.content) > 400 else ""))
    return 0 if uploaded == len(chunks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
