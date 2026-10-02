"""Streamable HTTP for the local MCP servers: a static bearer token and a loopback bind.

The SDK's auth hooks are used as they are: `AuthSettings` plus a `TokenVerifier` make the SDK wrap
the MCP endpoint in its bearer middleware (401 with `WWW-Authenticate: Bearer` without a valid
token). `AuthSettings` requires an issuer URL because it is built for OAuth resource servers; with
`resource_server_url=None` the SDK publishes no protected-resource metadata, so that URL is never
shown to a client and no OAuth discovery is offered. The token is one operator secret compared in
constant time.

The server binds to loopback only, unless `--allow-remote` is given; for remote use, keep it on
loopback on the server and reach it through an SSH tunnel.
"""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Mapping

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

MIN_TOKEN_LENGTH = 32
DEFAULT_HTTP_PORT = 8765
MCP_HTTP_PATH = "/mcp"


class StaticTokenVerifier:
    """A TokenVerifier for one shared operator token."""

    def __init__(self, token: str, *, client_id: str) -> None:
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError("the MCP bearer token is too short")
        self._token = token.encode("utf-8")
        self._client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode("utf-8"), self._token):
            return None
        # The secret itself never travels further than this comparison.
        return AccessToken(token="static-operator-token", client_id=self._client_id, scopes=[])


def bearer_token_from_environment(environ: Mapping[str, str], name: str) -> str:
    token = environ.get(name, "").strip()
    if not token:
        raise RuntimeError(f"{name} is required for the HTTP transport")
    if len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(f"{name} must be at least {MIN_TOKEN_LENGTH} characters")
    return token


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def check_bind_host(host: str, *, allow_remote: bool) -> None:
    if not is_loopback(host) and not allow_remote:
        raise RuntimeError(
            f"refusing to listen on {host}: bind to 127.0.0.1 and use an SSH tunnel, "
            "or pass --allow-remote"
        )


def static_token_auth(
    token: str, *, host: str, port: int, client_id: str
) -> tuple[AuthSettings, StaticTokenVerifier]:
    url_host = f"[{host.strip('[]')}]" if ":" in host else host
    settings = AuthSettings(
        issuer_url=f"http://{url_host}:{port}",
        resource_server_url=None,
    )
    return settings, StaticTokenVerifier(token, client_id=client_id)
