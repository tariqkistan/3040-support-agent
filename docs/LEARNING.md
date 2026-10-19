# Learning notes

Short "why this design" notes, one per build stage.

## Stage 1 — Scaffold, config, and auth

**Why env-based config (pydantic-settings)?** Every deployment knob lives in
one `Settings` class validated at startup. A typo'd env var fails fast at boot
instead of mid-request, and `.env` keeps local dev secrets out of the repo.

**Why two kinds of auth?** There are two trust boundaries. (1) *Your API*: a
shared `X-API-Key` header, compared with `hmac.compare_digest` so an attacker
can't measure how many characters they got right from response timing. It fails
closed — if the server key is unset, requests are rejected. (2) *Your code →
Azure*: `DefaultAzureCredential`, i.e. Entra ID identity, so no Azure keys are
ever written to disk, committed, or leaked in logs.

**Why an eval gate at all?** (Preview of stage 4–5) LLM answers aren't
deterministic, so "does it still work" can't be checked by unit tests. A scored
dataset + thresholds in CI turns "the prompt tweak broke groundedness" into a
failing check instead of a silent regression.

## Stage 2 — Inspect, chunk, ingest

**Why inspect the PDF first?** `inspect_pdf.py` decides whether the doc needs
Document Intelligence OCR or plain text extraction (PyMuPDF). Running it once
avoids paying for DI on a text-native doc — and keeps the ingest path honest if
someone drops in a scanned manual instead.

**Why structure-aware chunking?** Fixed-size splitting slices tables in half and
separates a procedure step from its steps. The chunker uses font analysis
(larger/bold text → `section_title`), `page.find_tables()` bboxes, and numbered
line detection so tables and procedures are never split mid-item. `section_title`
and `page_number` are stored as index fields — that's what makes `Sources:
<section> — p. <N>` citations possible at answer time.

**Why an index-side vectorizer?** The Foundry Azure AI Search tool sends *text*
queries and expects the index to vectorize them itself. The index therefore
carries an `AzureOpenAIVectorizer` pointing at the embedding deployment — and
that's also why `vector_simple_hybrid` works on the free tier (no semantic
ranker needed).

**Why idempotent ingest?** `source_file`-filtered delete + deterministic chunk
IDs (sha256 of file|ordinal|content) mean re-running ingest after a doc update
replaces exactly its chunks — no duplicates, no stale rows. That's what makes
"refresh the index in CI" safe.

## Stage 3 — Agent + API

**Why a Foundry prompt agent instead of hand-rolled RAG?** The agent service
owns the search→synthesize loop (tool calls, retries, grounding). The app keeps
the two things that are actually product logic: the instructions (answer only
from the index, cite `Sources: <section> — p. <N>`, refuse otherwise) and the
session mapping (`session_id` → Foundry conversation).

**Why conversations, not threads?** azure-ai-projects 2.x uses the Responses
API: a `conversation` holds items (messages) and each turn is a
`responses.create` bound to the agent. Holding the conversation server-side
means multi-turn context works without shipping history on every request —
which is exactly what a Copilot Studio custom connector needs.

**Why parse citations instead of trusting structured output?** The model emits
`Sources:` lines because that's robust across small models; `parse_sources`
turns them into a typed array so the API contract stays clean even when the
model's formatting wobbles.

## Stage 4 — Evals + baseline

**Why four metrics?** Groundedness and relevance need an LLM judge (they're
semantic); citation accuracy and refusal rate are deterministic checks against
the dataset — cheap, fast, and they catch the failures judges miss (wrong page,
answered-when-it-should-refuse).

**Why a non-reasoning judge?** `azure-ai-evaluation` calls chat completions with
`max_tokens`; reasoning models (gpt-5-mini) reject that parameter. The judge is
a separate `gpt-4.1-mini` deployment — never reuse a reasoning deployment here.

**Why page tolerance ±2?** The printed page numbers in the document body are
offset from PDF page indices. The agent cites either faithfully; the gate
measures "did it point at the right place", not "did it do our arithmetic".

## Stage 5 — CI

**Why OIDC and not a client secret?** `azure/login@v2` with a federated
credential means CI authenticates as an Entra identity with exactly the roles
it needs — there is literally nothing to leak, rotate, or store in repo
secrets except the non-sensitive IDs.

**Why fetch the PDF from blob in CI?** The source document is copyrighted, so
it's gitignored — but evals need the real doc. A private blob + `Storage Blob
Data Reader` on the OIDC identity keeps the repo clean *and* the gate real.

## Stage 6 — What this demo shows

An honest scope statement matters: this is a single-document support agent,
not a production product. The interesting engineering is the *shape* —
grounded retrieval, pinned SDK calls, auth that's safe by default, and a CI
gate that treats answer quality like a test suite.
