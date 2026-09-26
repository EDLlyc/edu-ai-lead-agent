from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import app.news_infographic_local_main as local_main
import httpx
import pytest
from app.application.services.news_infographic import QUALITY_VERSION
from app.domain.news_infographic import InfographicInputError, validate_package_snapshot
from app.infrastructure.news_infographic_local import (
    LocalInfographicPackageLoader,
    read_frozen_input_bundle,
    write_frozen_input_bundle,
)
from test_news_infographic_pipeline import _copy_payload
from tests.unit.test_news_infographic import PACKAGE_ID, package_payload


@pytest.mark.asyncio
async def test_loader_uses_one_exact_get_and_rejects_response_identity() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, json=package_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        loader = LocalInfographicPackageLoader(client)
        cases = await loader.load((UUID(PACKAGE_ID),), api_base_url="http://127.0.0.1:8000")
        assert cases[0].package_id == UUID(PACKAGE_ID)
    assert calls == [("GET", f"http://127.0.0.1:8000/api/v1/material-packages/{PACKAGE_ID}")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:8000",
        "http://localhost:8000",
        "http://example.com:8000",
        "http://127.0.0.1:8000/api/v1",
        "http://127.0.0.1:8000?x=1",
    ],
)
async def test_loader_denies_unsafe_origins_without_network(origin: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request is allowed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(InfographicInputError):
            await LocalInfographicPackageLoader(client).load(
                (UUID(PACKAGE_ID),), api_base_url=origin
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 503])
async def test_loader_does_not_follow_redirect_or_retry(status: int) -> None:
    count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(status, headers={"Location": "http://example.com/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(InfographicInputError, match="exact detail"):
            await LocalInfographicPackageLoader(client).load(
                (UUID(PACKAGE_ID),), api_base_url="http://127.0.0.1:8000"
            )
    assert count == 1


@pytest.mark.asyncio
async def test_loader_rejects_wrong_package_id() -> None:
    payload = package_payload()
    payload["id"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(InfographicInputError, match="differs"):
            await LocalInfographicPackageLoader(client).load(
                (UUID(PACKAGE_ID),), api_base_url="http://127.0.0.1:8000"
            )


def test_frozen_input_round_trip_is_private_exclusive_and_symlink_safe(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())
    bundle_path = tmp_path / "input.json"
    write_frozen_input_bundle(bundle_path, (case,))
    assert bundle_path.stat().st_mode & 0o777 == 0o600
    assert read_frozen_input_bundle(bundle_path) == (case,)
    with pytest.raises(FileExistsError):
        write_frozen_input_bundle(bundle_path, (case,))
    link_path = tmp_path / "link.json"
    link_path.symlink_to(bundle_path)
    with pytest.raises(InfographicInputError, match="symlink"):
        read_frozen_input_bundle(link_path)


def test_reuse_requires_a_matching_previously_accepted_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_main, "_PROJECT_ROOT", tmp_path)
    case = validate_package_snapshot(package_payload())
    prior = tmp_path / "output" / "prior"
    prior.mkdir(parents=True)
    (prior / "private").mkdir()
    manifest = {
        "schema_version": QUALITY_VERSION,
        "case_count": 1,
        "cases": [
            {
                "copy": "accepted",
                "input_fingerprint": case.fingerprint,
                "package_id": str(case.package_id),
            }
        ],
    }
    (prior / "manifest.json").write_text(json.dumps(manifest))
    copy_record = {
        "package_id": str(case.package_id),
        "source_footer": case.source_footer,
        "copy": _copy_payload(),
    }
    (prior / "copy.json").write_text(json.dumps([copy_record]))
    frozen_request = {
        "schema_version": "daily-news-infographic-prompt-v1",
        "input_fingerprint": case.fingerprint,
        "package_id": str(case.package_id),
        "source_footer": case.source_footer,
        "copy": _copy_payload(),
    }
    (prior / "private" / "01-image-request.json").write_text(json.dumps(frozen_request))
    assert local_main._accepted_copy_from_run(prior, case).title == _copy_payload()["title"]
    tampered_copy = _copy_payload()
    tampered_copy["title"] = "孩子怎样学习科学探究"
    (prior / "copy.json").write_text(json.dumps([{**copy_record, "copy": tampered_copy}]))
    with pytest.raises(ValueError, match="does not match"):
        local_main._accepted_copy_from_run(prior, case)
    (prior / "copy.json").write_text(json.dumps([copy_record]))
    frozen_request["input_fingerprint"] = "wrong"
    (prior / "private" / "01-image-request.json").write_text(json.dumps(frozen_request))
    with pytest.raises(ValueError, match="does not match"):
        local_main._accepted_copy_from_run(prior, case)
    frozen_request["input_fingerprint"] = case.fingerprint
    (prior / "private" / "01-image-request.json").write_text(json.dumps(frozen_request))
    manifest["cases"][0]["input_fingerprint"] = "wrong"
    (prior / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="does not match"):
        local_main._accepted_copy_from_run(prior, case)
    manifest["cases"][0]["input_fingerprint"] = case.fingerprint
    (prior / "manifest.json").write_text(json.dumps(manifest))
    (prior / "private" / "01-image-request.json").unlink()
    with pytest.raises(ValueError, match="missing a bounded artifact"):
        local_main._accepted_copy_from_run(prior, case)


def test_frozen_input_rejects_deep_or_tampered_snapshot(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload())
    payload = {
        "schema_version": "news-infographic-input-v1",
        "cases": [case.model_dump(mode="json")],
    }
    payload["cases"][0]["source_url"] = "https://wrong.example/news"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InfographicInputError, match="failed validation"):
        read_frozen_input_bundle(path)
