# ruff: noqa: RUF001 -- Chinese fixture metadata is intentional.
from __future__ import annotations

import json
import socket
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID
from zipfile import ZipFile

import pytest
from app import official_account_news_editorial_demo as editorial
from app.domain.official_account_local import (
    ArticleImageBlock,
    article_body_character_count,
    article_package_fingerprint,
)
from PIL import Image


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (1536, 1024), color=color).save(
        stream,
        format="JPEG",
        quality=84,
        optimize=True,
        progressive=False,
    )
    return stream.getvalue()


def _refresh_manifest_row(source_dir: Path, relative_path: str) -> None:
    manifest_path = source_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    body = (source_dir / relative_path).read_bytes()
    files = manifest["files"]
    assert isinstance(files, list)
    row = next(item for item in files if item["path"] == relative_path)
    row["byte_size"] = len(body)
    row["sha256"] = sha256(body).hexdigest()
    _write_json(manifest_path, manifest)


def _source_bundle(root: Path) -> tuple[Path, tuple[bytes, bytes, bytes]]:
    source_dir = root / "source-v1"
    assets_dir = source_dir / "assets"
    assets_dir.mkdir(parents=True)
    image_bodies = (
        _jpeg_bytes((212, 231, 244)),
        _jpeg_bytes((226, 215, 190)),
        _jpeg_bytes((199, 225, 214)),
    )
    for name, body in zip(editorial.BODY_IMAGE_NAMES, image_bodies, strict=True):
        (assets_dir / name).write_bytes(body)

    run = {
        "article_provider_calls": 0,
        "comfly_calls": 0,
        "content_fingerprint": "1" * 64,
        "embedding_provider_calls": 0,
        "ip_visibility_assessment": "passed",
        "manual_review_status": "pending",
        "model": "gpt-image-2",
        "paid_generation_call_limit": 3,
        "paid_generation_calls_attempted": 3,
        "paid_generation_calls_succeeded": 3,
        "provider": "toapis",
        "publish_calls": 0,
        "published": False,
        "render_fingerprint": "2" * 64,
        "run_id": "6014f5cc-1755-507a-9ecb-ab72fa41071e",
        "simulation": True,
        "source_fetch_calls_in_run": 0,
        "status": "ready",
        "version": editorial.SOURCE_REPORT_VERSION,
        "visual_quality_status": "passed",
        "wechat_calls": 0,
        "wecom_calls": 0,
    }
    evidence = {
        "version": editorial.SOURCE_EVIDENCE_VERSION,
        "sources": [
            {
                "canonical_url": editorial.NEWS_URL,
                "document_sha256": editorial._EXPECTED_EVIDENCE_DOCUMENT_SHA256[0],
                "evidence_id": editorial._EXPECTED_EVIDENCE_IDS[0],
                "exact_quote": "科技教育以更加鲜明的学科融合和实践导向持续发力",
                "published_date": "2026-07-21",
                "retrieval_url": editorial.NEWS_FETCH_URL,
                "source_name": "中华人民共和国教育部政府门户网站",
                "title": "面向未来，向新而行",
                "unexpected_private_path": "/tmp/must-not-be-projected",
            },
            {
                "canonical_url": editorial.PLAN_URL,
                "document_sha256": editorial._EXPECTED_EVIDENCE_DOCUMENT_SHA256[1],
                "evidence_id": editorial._EXPECTED_EVIDENCE_IDS[1],
                "exact_quote": "鼓励开展人工智能跨学科教学",
                "published_date": "2026-04-10",
                "retrieval_url": editorial.PLAN_URL,
                "source_name": "中华人民共和国教育部政府门户网站",
                "title": "教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
            },
        ],
    }
    visuals: list[dict[str, object]] = []
    for ordinal, (body, public_ref, visual_contract) in enumerate(
        zip(
            image_bodies,
            editorial._EXPECTED_REFERENCE_PUBLIC_REFS,
            editorial._EXPECTED_VISUAL_CONTRACT,
            strict=True,
        )
    ):
        visuals.append(
            {
                "automatic_retry_permitted": False,
                "block_fingerprint": visual_contract["block_fingerprint"],
                "block_index": 0,
                "block_kind": "paragraph",
                "ip_prompt_contract": "mandatory_visible_protagonist",
                "ip_visibility_assessment": "pass",
                "ordinal": ordinal,
                "output": {
                    "byte_size": len(body),
                    "height": 1024,
                    "media_type": "image/jpeg",
                    "metadata_free": True,
                    "sha256": sha256(body).hexdigest(),
                    "width": 1536,
                },
                "output_profile_version": (
                    "official-account-generated-body-publication-v2-3x2-jpeg"
                ),
                "plan_version": "official-account-generated-visual-plan-v3-visible-ip",
                "prompt_version": (
                    "official-account-generated-visual-prompt-v3-visible-ip-block-scene"
                ),
                "provider_attempts": 1,
                "reference_catalog_version": "brand-visual-catalog-v1",
                "reference_input_sha256": visual_contract["reference_input_sha256"],
                "reference_input_version": ("image-reference-input-v2-png-preserve-jpeg-normalize"),
                "reference_public_ref": public_ref,
                "request_fingerprint": visual_contract["request_fingerprint"],
                "section_index": ordinal,
                "semantic_alt": visual_contract["semantic_alt"],
            }
        )
    visual_map = {"quality_status": "passed", "visuals": visuals}
    _write_json(source_dir / "run.json", run)
    _write_json(source_dir / "evidence.json", evidence)
    _write_json(source_dir / "visual-map.json", visual_map)

    manifested_paths = (
        "run.json",
        "evidence.json",
        "visual-map.json",
        *(f"assets/{name}" for name in editorial.BODY_IMAGE_NAMES),
    )
    manifest = {
        "files": [
            {
                "byte_size": len((source_dir / relative_path).read_bytes()),
                "path": relative_path,
                "sha256": sha256((source_dir / relative_path).read_bytes()).hexdigest(),
            }
            for relative_path in manifested_paths
        ],
        "published": False,
        "run_id": run["run_id"],
        "simulation": True,
        "sources": [editorial.NEWS_URL, editorial.PLAN_URL],
        "status": "ready",
        "version": editorial.SOURCE_REPORT_VERSION,
        "visual_quality_status": "passed",
    }
    _write_json(source_dir / "manifest.json", manifest)
    return source_dir, image_bodies


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in the editorial repackage")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


def test_builds_six_unit_evidence_bound_article_package(tmp_path: Path) -> None:
    source_dir, _ = _source_bundle(tmp_path)
    bundle = editorial.load_source_bundle(source_dir)
    article = editorial.build_editorial_article(bundle)

    assert all("unexpected_private_path" not in source for source in bundle.evidence_sources)
    assert len(article.sections) == 6
    assert editorial.BODY_TARGET_MIN <= article_body_character_count(article) <= 2_600
    assert article.content_fingerprint == article_package_fingerprint(article)
    assert tuple(source.source_url for source in article.sources) == (
        editorial.NEWS_URL,
        editorial.PLAN_URL,
    )
    known_evidence_ids = {source.evidence_id for source in article.sources}
    external_claims = tuple(claim for claim in article.claims if claim.kind == "external_fact")
    opinions = tuple(claim for claim in article.claims if claim.kind == "opinion")
    assert {
        evidence_id for claim in external_claims for evidence_id in claim.evidence_ids
    } == known_evidence_ids
    assert all(not claim.brand_chunk_ids for claim in external_claims)
    assert all(not claim.evidence_ids and not claim.brand_chunk_ids for claim in opinions)
    assert {
        claim_ref
        for section in article.sections
        for block in section.blocks
        for claim_ref in block.claim_refs
    } == {claim.id for claim in article.claims}
    assert tuple(
        (section_index, block.slot_key)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    ) == ((0, "body-0"), (2, "body-1"), (4, "body-2"))


def test_renderer_escapes_text_and_rejects_source_or_version_drift(tmp_path: Path) -> None:
    source_dir, _ = _source_bundle(tmp_path)
    article = editorial.build_editorial_article(editorial.load_source_bundle(source_dir))
    escaped_article = article.model_copy(
        update={
            "title": '<script data-test="x">alert(1)</script>',
            "content_fingerprint": "0" * 64,
        }
    )
    escaped_article = escaped_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(escaped_article)}
    )

    html = editorial.render_editorial_html(escaped_article)
    assert "<script" not in html
    assert "&lt;script data-test=&quot;x&quot;&gt;" in html
    assert html.count("__OFFICIAL_ACCOUNT_BODY_MEDIA_") == 3
    assert "http://" not in html
    assert "javascript:" not in html.lower()

    unsafe_source = article.sources[0].model_copy(
        update={"source_url": "https://example.invalid/not-approved"}
    )
    unsafe_article = article.model_copy(
        update={"sources": (unsafe_source, article.sources[1]), "content_fingerprint": "0" * 64}
    )
    unsafe_article = unsafe_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(unsafe_article)}
    )
    with pytest.raises(ValueError, match="source set changed"):
        editorial.render_editorial_html(unsafe_article)

    drifted_article = article.model_copy(
        update={
            "versions": article.versions.model_copy(
                update={"renderer_version": "unexpected-renderer"}
            ),
            "content_fingerprint": "0" * 64,
        }
    )
    drifted_article = drifted_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(drifted_article)}
    )
    with pytest.raises(ValueError, match="version changed"):
        editorial.render_editorial_html(drifted_article)


def test_renderer_rejects_fact_or_interpretation_binding_drift(tmp_path: Path) -> None:
    source_dir, _ = _source_bundle(tmp_path)
    article = editorial.build_editorial_article(editorial.load_source_bundle(source_dir))

    unbound_fact = article.claims[0].model_copy(update={"evidence_ids": ()})
    claims = (unbound_fact, *article.claims[1:])
    drifted_fact_article = article.model_copy(
        update={"claims": claims, "content_fingerprint": "0" * 64}
    )
    drifted_fact_article = drifted_fact_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(drifted_fact_article)}
    )
    with pytest.raises(ValueError, match="fact and interpretation bindings changed"):
        editorial.render_editorial_html(drifted_fact_article)

    bound_opinion = article.claims[3].model_copy(
        update={"evidence_ids": (article.sources[0].evidence_id,)}
    )
    claims = (*article.claims[:3], bound_opinion, *article.claims[4:])
    drifted_opinion_article = article.model_copy(
        update={"claims": claims, "content_fingerprint": "0" * 64}
    )
    drifted_opinion_article = drifted_opinion_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(drifted_opinion_article)}
    )
    with pytest.raises(ValueError, match="fact and interpretation bindings changed"):
        editorial.render_editorial_html(drifted_opinion_article)


def test_export_is_offline_exact_and_archive_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    source_dir, image_bodies = _source_bundle(tmp_path)
    first = tmp_path / "first" / "editorial-bundle"
    second = tmp_path / "second" / "editorial-bundle"

    assert editorial.export_editorial_bundle(source_dir, first) == first
    assert editorial.export_editorial_bundle(source_dir, second) == second

    for ordinal, expected_body in enumerate(image_bodies):
        relative_path = Path("assets") / f"body-{ordinal:02d}.jpg"
        assert (first / relative_path).read_bytes() == expected_body
        assert (second / relative_path).read_bytes() == expected_body
    assert (first / "editorial-bundle.zip").read_bytes() == (
        second / "editorial-bundle.zip"
    ).read_bytes()

    run = _read_json(first / "run.json")
    assert run["article_section_count"] == 6
    assert editorial.BODY_TARGET_MIN <= run["article_body_character_count"] <= 2_600
    assert run["inherited_historical_paid_image_calls"] == 3
    assert all(
        run[field] == 0
        for field in (
            "source_fetch_calls_in_repackage",
            "article_provider_calls_in_repackage",
            "embedding_provider_calls_in_repackage",
            "image_provider_calls_in_repackage",
            "comfly_calls_in_repackage",
            "toapis_calls_in_repackage",
            "wechat_calls",
            "wecom_calls",
            "publish_calls",
        )
    )
    assert run["manual_review_status"] == "pending"
    assert run["copy_ready"] is False
    assert run["published"] is False

    article_package = _read_json(first / "article-package.json")
    assert article_package["version"] == editorial.ARTICLE_SCHEMA_VERSION
    assert len(article_package["article"]["sections"]) == 6
    reference = _read_json(first / "reference-learning.json")
    assert reference["retained_source_content"] is False
    assert reference["retained_source_html"] is False
    assert reference["retained_source_images"] is False
    assert reference["copied_reference_expression"] is False

    html = (first / "article-body.html").read_text(encoding="utf-8")
    preview = (first / "preview.html").read_text(encoding="utf-8")
    assert html.count('src="assets/body-') == 3
    assert "__OFFICIAL_ACCOUNT_BODY_MEDIA_" not in html
    assert "default-src 'none'" in preview
    assert "https://mp.weixin.qq.com" not in html
    assert "未同步公众号" in html

    manifest = _read_json(first / "manifest.json")
    assert manifest["simulation"] is True
    assert manifest["local_only"] is True
    assert manifest["manual_review_status"] == "pending"
    assert manifest["copy_ready"] is False
    assert manifest["published"] is False
    assert manifest["current_repackage_external_calls"] == 0
    assert manifest["inherited_historical_paid_image_calls"] == 3
    assert manifest["source_bundle_run_id"] == run["source_bundle_run_id"]
    assert manifest["source_bundle_manifest_sha256"] == run["source_bundle_manifest_sha256"]
    manifested_paths = {row["path"] for row in manifest["files"]}
    assert "article-package.json" in manifested_paths
    assert "manifest.json" not in manifested_paths
    assert "editorial-bundle.zip" not in manifested_paths
    with ZipFile(first / "editorial-bundle.zip") as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        assert set(names) == {
            f"editorial-bundle/{relative_path}"
            for relative_path in manifested_paths | {"manifest.json"}
        }


def test_export_refuses_overwrite_and_cleans_failed_temporary_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir, _ = _source_bundle(tmp_path)
    output = tmp_path / "exports" / "editorial-bundle"
    output.mkdir(parents=True)
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to replace"):
        editorial.export_editorial_bundle(source_dir, output)
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    failed_output = tmp_path / "failed" / "editorial-bundle"

    def fail_write_json(_path: Path, _payload: object) -> None:
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(editorial, "_write_json", fail_write_json)
    with pytest.raises(RuntimeError, match="injected write failure"):
        editorial.export_editorial_bundle(source_dir, failed_output)
    assert not failed_output.exists()
    assert not tuple(failed_output.parent.glob(".editorial-bundle.*"))


def test_source_bundle_rejects_manifest_and_distribution_tampering(tmp_path: Path) -> None:
    source_dir, _ = _source_bundle(tmp_path)
    run_path = source_dir / "run.json"
    run = _read_json(run_path)
    run["wechat_calls"] = 1
    _write_json(run_path, run)
    _refresh_manifest_row(source_dir, "run.json")
    with pytest.raises(ValueError, match="distribution boundary changed"):
        editorial.load_source_bundle(source_dir)

    clean_source, _ = _source_bundle(tmp_path / "clean")
    image_path = clean_source / "assets" / editorial.BODY_IMAGE_NAMES[0]
    image_path.write_bytes(image_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="does not match the manifest"):
        editorial.load_source_bundle(clean_source)

    declared_source, _ = _source_bundle(tmp_path / "declared")
    declared_path = declared_source / "declared-note.txt"
    declared_path.write_text("manifested v1 note", encoding="utf-8")
    manifest_path = declared_source / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["files"].append(
        {
            "byte_size": declared_path.stat().st_size,
            "path": declared_path.name,
            "sha256": sha256(declared_path.read_bytes()).hexdigest(),
        }
    )
    _write_json(manifest_path, manifest)
    editorial.load_source_bundle(declared_source)
    declared_path.write_text("tampered manifested v1 note", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match the manifest"):
        editorial.load_source_bundle(declared_source)


@pytest.mark.parametrize(
    ("relative_path", "mutate", "message"),
    (
        (
            "evidence.json",
            lambda payload: payload["sources"][0].__setitem__("evidence_id", str(UUID(int=0))),
            "evidence snapshot identity changed",
        ),
        (
            "visual-map.json",
            lambda payload: payload["visuals"][1].__setitem__("request_fingerprint", "f" * 64),
            "visual contract or local IP inspection changed",
        ),
    ),
)
def test_source_bundle_rejects_evidence_or_visual_contract_drift(
    tmp_path: Path,
    relative_path: str,
    mutate: Any,
    message: str,
) -> None:
    source_dir, _ = _source_bundle(tmp_path)
    path = source_dir / relative_path
    payload = _read_json(path)
    mutate(payload)
    _write_json(path, payload)
    _refresh_manifest_row(source_dir, relative_path)

    with pytest.raises(ValueError, match=message):
        editorial.load_source_bundle(source_dir)
