from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

from app.core.errors import PolicyRejectedError

Resolver = Callable[[str], Awaitable[list[str]]]

METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}

_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_NON_PUBLIC_HOST_SUFFIXES = (
    "example",
    "home.arpa",
    "internal",
    "invalid",
    "lan",
    "local",
    "localhost",
    "onion",
    "test",
)


def _decoded_path_for_policy(path: str) -> str:
    if _INVALID_PERCENT_ESCAPE.search(path):
        raise PolicyRejectedError("invalid_path", "source URL path has invalid encoding")
    decoded = path
    for _ in range(5):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        raise PolicyRejectedError("invalid_path", "source URL path is excessively encoded")
    if "\x00" in decoded or "\\" in decoded:
        raise PolicyRejectedError("invalid_path", "source URL path is invalid")
    if any(segment in {".", ".."} for segment in decoded.split("/")):
        raise PolicyRejectedError("path_traversal", "source URL path contains a dot segment")
    if decoded.count("/") != path.count("/"):
        raise PolicyRejectedError("encoded_separator", "encoded path separators are not allowed")
    return decoded


def _path_is_within_prefix(path: str, prefix: str) -> bool:
    normalized_prefix = _decoded_path_for_policy(prefix or "/")
    if not normalized_prefix.startswith("/"):
        raise PolicyRejectedError("invalid_allowlist", "approved path prefixes must be absolute")
    if normalized_prefix == "/":
        return True
    boundary = normalized_prefix.rstrip("/")
    return path == boundary or path.startswith(f"{boundary}/")


async def system_resolver(host: str) -> list[str]:
    def resolve() -> list[str]:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return sorted({str(record[4][0]) for record in records})

    return await asyncio.to_thread(resolve)


def normalize_https_url(value: str, *, allow_http_fallback: bool = False) -> str:
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme != "https" and not (allow_http_fallback and scheme == "http"):
        raise PolicyRejectedError("https_required", "only HTTPS source URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise PolicyRejectedError("userinfo_rejected", "URL user information is not allowed")
    if parts.fragment:
        raise PolicyRejectedError("fragment_rejected", "URL fragments are not allowed")
    if not parts.hostname:
        raise PolicyRejectedError("invalid_host", "source URL must include a hostname")
    try:
        port = parts.port
    except ValueError as error:
        raise PolicyRejectedError("invalid_port", "source URL contains an invalid port") from error
    default_port = 443 if scheme == "https" else 80
    if port not in (None, default_port):
        raise PolicyRejectedError("port_rejected", "only the default source port is allowed")
    host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    if host == "localhost" or "." not in host:
        raise PolicyRejectedError("ambiguous_host", "ambiguous hostnames are not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PolicyRejectedError("ip_literal_rejected", "IP-literal source URLs are not allowed")
    path = parts.path or "/"
    _decoded_path_for_policy(path)
    netloc = host
    normalized = SplitResult(scheme, netloc, path, parts.query, "")
    return urlunsplit(normalized)


def normalize_public_https_url(value: str) -> str:
    """Normalize a stored public HTTPS URL for citation/display projections.

    Acquisition performs the authoritative DNS/IP policy check before persistence. This
    synchronous projector still rejects ambiguous/local hostnames and every IP literal so
    downstream Agent and UI boundaries cannot introduce an obviously private address.
    """

    normalized = normalize_https_url(value)
    host = urlsplit(normalized).hostname
    if (
        host is None
        or len(host) > 253
        or any(
            host == suffix or host.endswith(f".{suffix}") for suffix in _NON_PUBLIC_HOST_SUFFIXES
        )
    ):
        raise PolicyRejectedError("non_public_host", "source URL host is not public")
    labels = host.split(".")
    if any(not label or len(label) > 63 for label in labels):
        raise PolicyRejectedError("invalid_host", "source URL host is invalid")
    return normalized


def is_public_https_url(value: str) -> bool:
    try:
        normalize_public_https_url(value)
    except PolicyRejectedError:
        return False
    return True


def validate_allowlist(
    value: str,
    *,
    allowed_hosts: tuple[str, ...],
    allowed_path_prefixes: tuple[str, ...],
    allow_http_fallback: bool = False,
) -> str:
    normalized = normalize_https_url(value, allow_http_fallback=allow_http_fallback)
    parts = urlsplit(normalized)
    allowed = {host.rstrip(".").encode("idna").decode("ascii").lower() for host in allowed_hosts}
    if parts.hostname not in allowed:
        raise PolicyRejectedError("host_not_allowed", "source host is not approved")
    path = _decoded_path_for_policy(parts.path or "/")
    if allowed_path_prefixes and not any(
        _path_is_within_prefix(path, prefix) for prefix in allowed_path_prefixes
    ):
        raise PolicyRejectedError("path_not_allowed", "source path is not approved")
    return normalized


async def validate_public_resolution(host: str, resolver: Resolver = system_resolver) -> list[str]:
    try:
        addresses = await resolver(host)
    except (OSError, socket.gaierror) as error:
        raise PolicyRejectedError(
            "dns_resolution_failed", "source host could not be resolved"
        ) from error
    if not addresses:
        raise PolicyRejectedError("dns_resolution_failed", "source host has no addresses")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise PolicyRejectedError(
                "invalid_dns_answer", "source DNS answer is invalid"
            ) from error
        if address in METADATA_ADDRESSES or not address.is_global:
            raise PolicyRejectedError(
                "non_public_address", "source host resolved to a non-public address"
            )
    return addresses
