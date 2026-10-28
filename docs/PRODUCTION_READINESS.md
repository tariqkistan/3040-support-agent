# Portfolio-grade production-readiness checklist

This is a bank-style engineering exercise, not a claim that the service is
approved for Nedbank or any regulated production environment. An actual bank
deployment requires the organization's security, privacy, architecture, risk,
and operations approval.

## Implemented in this project

- [x] Grounded support answers through Azure AI Search with structured citations.
- [x] API-key check that fails closed, input bounds, and a request-rate limit.
- [x] Foundry agent version lookup before creation, avoiding a new agent version
  on every chat request.
- [x] Durable caller-scoped session-to-conversation mappings using Cosmos DB
  when configured, with item TTL and Entra-based Azure credential acquisition.
- [x] Separate process liveness from configuration readiness.
- [x] Add request IDs and privacy-conscious request metadata logging; the API
  key value and message text are not logged.
- [x] Evaluation judge errors propagate; missing required scores fail a full
  evaluation. Judge-skipped runs are marked partial and do not pass the gate.
- [x] Copilot Studio custom-connector instructions and explicit boundary notes.

## Still required before any enterprise pilot

- [ ] Replace the shared API key with the organization's approved OAuth/Entra ID
  user or service identity; authorize access and retain auditable caller identity.
- [ ] Use a private or approved network path, TLS termination, WAF/API gateway,
  and distributed rate limiting; the built-in limiter is process-local.
- [ ] Provision Cosmos DB through reviewed infrastructure-as-code; enable
  customer-managed security controls as required, private networking, backups,
  TTL, least-privilege data-plane RBAC, and monitoring.
- [ ] Review the Foundry project, Search service, model deployment, data
  residency, prompt-injection protections, document provenance, and ingestion
  approval with security and data owners.
- [ ] Add centralized, privacy-reviewed audit and operational telemetry,
  alerts, dashboards, and an incident response procedure.
- [ ] Define retention/deletion policies for Foundry conversation data and
  Cosmos mappings; current Cosmos TTL only expires the mapping.
- [ ] Add availability/capacity tests, dependency timeouts/retries, disaster
  recovery, deployment rollback, and environment separation.
- [ ] Improve evaluation evidence: representative approved data, human review,
  adversarial cases, regression history, and validation that retrieved evidence
  (not just reference answers) supports each response.
- [ ] Complete threat modeling, privacy impact assessment, penetration testing,
  accessibility review, and formal risk acceptance.

## Current operational caveats

- `SESSION_STORE_BACKEND=memory` is for local development only and loses
  mappings on process restart. Configure `cosmos` for a hosted service.
- The Cosmos container must already exist, use `/id` as its partition key, and
  have TTL enabled. The service uses `DefaultAzureCredential`; assign its
  runtime identity the least-privilege Cosmos data-plane role.
- A Cosmos mapping is only the link from caller/session ID to Foundry
  conversation ID. The conversation transcript remains in Foundry, so Cosmos
  TTL does not delete the transcript.
- One shared connector key currently scopes the stored session identifiers.
  It does not distinguish end users. Do not treat caller-scoped keys as user
  authorization.
- The evaluation `groundedness` judge currently uses the dataset reference
  answer as context because the API does not expose retrieved chunks. It is a
  reference-answer consistency proxy, not proof that the actual retrieved
  passages supported the response.
- `GET /ready` checks configuration values only; it does not test Azure
  connectivity or dependencies.
