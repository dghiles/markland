"""Public OAuth-discovery routes that exist solely to satisfy MCP client probes.

Markland uses static bearer tokens (mint at /settings/tokens). Clients that
auto-probe for OAuth metadata (per RFC 9728 / MCP authorization spec
2025-03-26) hit these routes and receive JSON — not the styled HTML 404 page,
which would crash JSON.parse() in the client SDK with `Unrecognized token <`.

The protected-resource doc explicitly carries an empty `authorization_servers`
list so spec-aware clients short-circuit and use the static bearer path.
The authorization-server endpoint returns 404 with a JSON body for clients
that don't understand the empty-list signal and probe further.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def register_well_known_routes(app: FastAPI, *, base_url: str) -> None:
    """Mount the two /.well-known/* discovery routes on `app`.

    `base_url` is the public origin (e.g. `https://markland.dev`) used to build
    the canonical `resource` field. We do NOT derive this per-request: the
    metadata is meant to describe the server's identity, not the proxy hop.
    """

    resource_url = f"{base_url.rstrip('/')}/mcp"
    token_mint_url = f"{base_url.rstrip('/')}/settings/tokens"

    @app.get("/.well-known/oauth-protected-resource")
    def oauth_protected_resource() -> JSONResponse:
        return JSONResponse(
            {
                "resource": resource_url,
                "authorization_servers": [],
                "bearer_methods_supported": ["Bearer"],
                "resource_documentation": f"{base_url.rstrip('/')}/quickstart",
                # Non-RFC field — practical hint for human/agent eyeballs
                # that read the JSON when an SDK error surfaces it.
                "token_mint_url": token_mint_url,
            },
            status_code=200,
        )

    @app.get("/.well-known/oauth-authorization-server")
    def oauth_authorization_server() -> JSONResponse:
        return JSONResponse(
            {
                "error": "no_oauth_server",
                "error_description": (
                    "Markland does not run an OAuth authorization server. "
                    "Use a static bearer token minted at "
                    f"{token_mint_url}."
                ),
            },
            status_code=404,
        )

    # Explicitly register the trailing-slash variant as 404 so FastAPI's
    # default redirect_slashes behavior doesn't 307 → 200 us. We want the
    # discovery path to be exact: anything else is unknown.
    @app.get("/.well-known/oauth-protected-resource/")
    def oauth_protected_resource_trailing_slash() -> JSONResponse:
        return JSONResponse({"error": "not_found"}, status_code=404)
