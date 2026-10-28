What# Connect the support API to Copilot Studio

This project exposes a FastAPI endpoint for **Copilot Studio** through an
OpenAPI custom connector. This is different from building a GitHub Copilot
coding agent or publishing a Foundry agent directly into Microsoft 365 Copilot.

## Before connecting

- Run the API locally and confirm `GET /health`, `GET /ready`, and
  `POST /chat` work.
- For a Copilot Studio connection, host the API at an HTTPS address that the
  Power Platform environment can reach. A local `localhost` URL is not
  reachable from the cloud connector service.
- Configure `SESSION_STORE_BACKEND=cosmos`, Cosmos endpoint/database/container,
  and an identity with Cosmos data-plane access for a hosted, multi-instance
  deployment. Enable TTL on the container; this app sets a per-item TTL.
- Store `APP_API_KEY` in the connector connection, not in a topic message or
  source file. Rotate it when connector ownership or access changes.

## Create the custom connector

1. Download the API's Swagger 2.0 document from
   `https://<your-api-host>/copilot-openapi.json`. The normal FastAPI
   `/openapi.json` is OpenAPI 3.1 and is not the connector import format.
2. In Power Apps or Copilot Studio, create a custom connector by uploading the
   downloaded OpenAPI file.
3. Confirm that the connector imports the `chatWithSupportAgent` operation
   (`POST /chat`) and the `X-API-Key` header security scheme.
4. Configure the connector's API-key authentication as a header named
   `X-API-Key`; create a connection and provide the server's `APP_API_KEY`.
5. Configure the connector host/base URL to the deployed API. Save and test the
   connection before adding the action to an agent.
6. In Copilot Studio, add the custom connector action to a topic or agent.
   Map the user's question to `message`.
7. Supply the same stable, unique `session_id` for each turn in one
   conversation. Use the Copilot conversation identifier if available, or
   create and retain an opaque conversation ID in the topic. Use a different
   ID for a different conversation.
8. Display the `answer` result and, where useful, render the `sources` array
   (`section`, `page`) as citations.
9. Test follow-up turns, a new conversation, an out-of-scope question, missing
   authentication, and API failure handling in the target environment.

Microsoft's [custom connector OpenAPI guidance](https://learn.microsoft.com/en-us/connectors/custom-connectors/define-openapi-definition)
requires OpenAPI 2.0 for this import flow and states that OpenAPI 3.0 definitions
are not supported.

## Security boundary

The current `X-API-Key` is a shared service credential. It authenticates the
connector, **not an individual employee or customer**, and therefore does not
provide user-level authorization or an auditable end-user identity. This is
appropriate only for a controlled portfolio demonstration with non-sensitive
documents. Before any real organizational or regulated use, replace or front
it with the organization's approved Entra ID OAuth/API gateway pattern, enforce
authorization, and review data retention, audit, privacy, and network policies.

Do not expose a developer machine or a temporary tunnel as a production API.
Use an approved deployment, TLS, managed identity for Azure services, centrally
managed secrets, distributed rate limiting, and operational monitoring.
