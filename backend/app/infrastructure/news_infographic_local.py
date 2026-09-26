"""Safe loopback GET capture and private frozen-input persistence."""

from __future__ import annotations

import json
import os
import stat
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.domain.news_infographic import (
    InfographicInputError,
    ValidatedInfographicInput,
    build_private_input_bundle,
    validate_input_bundle,
    validate_package_snapshot,
)

_MAX_BUNDLE_BYTES = 2_000_000
_MAX_PACKAGE_BYTES = 2_000_000
_MAX_NESTING = 24
_API_PREFIX = "/api/v1/material-packages/"


def _loopback_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise InfographicInputError("package API must use literal loopback HTTP")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise InfographicInputError("package API base URL has an unsafe component")
    try:
        if not ip_address(parsed.hostname).is_loopback or parsed.port is None:
            raise InfographicInputError("package API must use a literal loopback address and port")
    except ValueError as exc:
        if isinstance(exc, InfographicInputError):
            raise
        raise InfographicInputError("package API host or port is invalid") from exc
    return value.rstrip("/")


def _bounded_json(data: bytes, *, name: str) -> Any:
    if len(data) > _MAX_BUNDLE_BYTES:
        raise InfographicInputError(f"{name} exceeds size limit")
    try:
        payload = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InfographicInputError(f"{name} is not valid JSON") from exc

    def walk(value: object, depth: int) -> None:
        if depth > _MAX_NESTING:
            raise InfographicInputError(f"{name} is too deeply nested")
        if isinstance(value, dict):
            for item in value.values():
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)

    walk(payload, 0)
    return payload


class LocalInfographicPackageLoader:
    """Load only exact material-package detail GETs from a literal loopback API."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def load(
        self, package_ids: tuple[UUID, ...], *, api_base_url: str
    ) -> tuple[ValidatedInfographicInput, ...]:
        base = _loopback_base_url(api_base_url)
        if not 1 <= len(package_ids) <= 3 or len(set(package_ids)) != len(package_ids):
            raise InfographicInputError("load requires 1-3 distinct package IDs")
        if self._client is None:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                return await self._load_with_client(client, package_ids, base)
        return await self._load_with_client(self._client, package_ids, base)

    @staticmethod
    async def _load_with_client(
        client: httpx.AsyncClient, package_ids: tuple[UUID, ...], base: str
    ) -> tuple[ValidatedInfographicInput, ...]:
        cases: list[ValidatedInfographicInput] = []
        for package_id in package_ids:
            url = f"{base}{_API_PREFIX}{package_id}"
            try:
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/json"},
                    timeout=httpx.Timeout(8.0, connect=3.0),
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise InfographicInputError(
                            "package API did not return an exact detail result"
                        )
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise InfographicInputError("package API returned a non-JSON result")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > _MAX_PACKAGE_BYTES:
                            raise InfographicInputError("package API response exceeds size limit")
            except httpx.HTTPError as exc:
                raise InfographicInputError("package API GET failed") from exc
            payload = _bounded_json(bytes(data), name="package response")
            if not isinstance(payload, dict):
                raise InfographicInputError("package response is not an object")
            cases.append(validate_package_snapshot(payload, expected_package_id=package_id))
        if len({case.selected_event_version_id for case in cases}) != len(cases):
            raise InfographicInputError("selected packages repeat the same event")
        return tuple(cases)


def _reject_symlink_path(path: Path) -> None:
    if ".." in path.parts:
        raise InfographicInputError("input path must not contain parent traversal")
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise InfographicInputError("frozen input path must not contain a symlink")
        current = current.parent


def read_frozen_input_bundle(path: Path) -> tuple[ValidatedInfographicInput, ...]:
    _reject_symlink_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BUNDLE_BYTES:
            raise InfographicInputError("frozen input is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(_MAX_BUNDLE_BYTES + 1)
    finally:
        os.close(descriptor)
    return validate_input_bundle(_bounded_json(data, name="frozen input"))


def write_frozen_input_bundle(path: Path, cases: tuple[ValidatedInfographicInput, ...]) -> None:
    _reject_symlink_path(path)
    payload = build_private_input_bundle(cases)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(data) > _MAX_BUNDLE_BYTES:
        raise InfographicInputError("frozen input exceeds size limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


class LocalInfographicInputStore:
    def read(self, path: Path) -> tuple[ValidatedInfographicInput, ...]:
        return read_frozen_input_bundle(path)

    def write(self, path: Path, cases: tuple[ValidatedInfographicInput, ...]) -> None:
        write_frozen_input_bundle(path, cases)
