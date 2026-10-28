"""Build the OpenAPI 2.0 document expected by Power Platform custom connectors."""

from copy import deepcopy


def build_copilot_openapi(openapi_spec: dict) -> dict:
    """Convert the chat operation's OpenAPI 3 schema into Swagger 2.0."""
    chat = openapi_spec["paths"]["/chat"]["post"]
    request_schema = chat["requestBody"]["content"]["application/json"]["schema"]
    response_schema = chat["responses"]["200"]["content"]["application/json"]["schema"]
    definitions = {
        name: deepcopy(openapi_spec["components"]["schemas"][name])
        for name in ("ChatRequest", "ChatResponse", "Source")
    }

    def convert_references(value):
        if isinstance(value, dict):
            return {
                key: convert_references(
                    item.replace("#/components/schemas/", "#/definitions/")
                    if key == "$ref" and isinstance(item, str)
                    else item
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [convert_references(item) for item in value]
        return value

    definitions = convert_references(definitions)
    request_schema = convert_references(request_schema)
    response_schema = convert_references(response_schema)
    return {
        "swagger": "2.0",
        "info": {
            "title": openapi_spec["info"]["title"],
            "description": (
                "Copilot Studio custom-connector definition for the support agent."
            ),
            "version": openapi_spec["info"]["version"],
        },
        "schemes": ["https"],
        "basePath": "/",
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": {
            "/chat": {
                "post": {
                    "summary": chat["summary"],
                    "description": chat["description"],
                    "operationId": chat["operationId"],
                    "consumes": ["application/json"],
                    "produces": ["application/json"],
                    "parameters": [
                        {
                            "name": "body",
                            "in": "body",
                            "required": True,
                            "schema": request_schema,
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Successful Response",
                            "schema": response_schema,
                        },
                        "401": {"description": "Missing or invalid API key."},
                        "422": {"description": "Invalid request."},
                    },
                    "security": [{"ApiKeyHeader": []}],
                }
            }
        },
        "securityDefinitions": {
            "ApiKeyHeader": {
                "type": "apiKey",
                "name": "X-API-Key",
                "in": "header",
            }
        },
        "definitions": definitions,
    }
