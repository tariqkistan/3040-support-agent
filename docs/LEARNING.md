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
