# ruff: noqa: RUF001 -- Chinese editorial assertions are intentional.
from __future__ import annotations

import json
import socket
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from app import official_account_news_editorial_asset_rich_demo as asset_rich
from app import official_account_news_editorial_polished_demo as polished_v3
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.domain.official_account_local import (
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    article_body_character_count,
    article_package_fingerprint,
    body_media_placeholder,
)
from app.official_account_news_editorial_demo import EditorialSourceBundle
from PIL import Image


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _jpeg_bytes(
    color: tuple[int, int, int],
    *,
    size: tuple[int, int] = (1536, 1024),
) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, color=color).save(
        stream,
        format="JPEG",
        quality=82,
        subsampling=2,
        optimize=False,
        progressive=False,
        exif=b"",
        icc_profile=None,
    )
    return stream.getvalue()


def _bundle() -> EditorialSourceBundle:
    image_bodies = (
        _jpeg_bytes((211, 231, 245)),
        _jpeg_bytes((229, 215, 188)),
        _jpeg_bytes((198, 225, 215)),
    )
    image_checksums = (
        sha256(image_bodies[0]).hexdigest(),
        sha256(image_bodies[1]).hexdigest(),
        sha256(image_bodies[2]).hexdigest(),
    )
    evidence_ids = sorted(polished_v3._EXPECTED_EVIDENCE_IDS, key=str)
    evidence_sources = (
        {
            "canonical_url": asset_rich.NEWS_URL,
            "document_sha256": "a" * 64,
            "evidence_id": str(evidence_ids[0]),
            "exact_quote": "科技教育以更加鲜明的学科融合和实践导向持续发力",
            "published_date": "2026-07-21",
            "retrieval_url": asset_rich.NEWS_URL,
            "source_name": "中华人民共和国教育部政府门户网站",
            "title": "面向未来，向新而行",
        },
        {
            "canonical_url": asset_rich.PLAN_URL,
            "document_sha256": "b" * 64,
            "evidence_id": str(evidence_ids[1]),
            "exact_quote": "鼓励开展人工智能跨学科教学",
            "published_date": "2026-04-10",
            "retrieval_url": asset_rich.PLAN_URL,
            "source_name": "中华人民共和国教育部政府门户网站",
            "title": "教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
        },
    )
    visual_rows: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] = (
        {
            "output": {"sha256": image_checksums[0]},
            "ip_visibility_assessment": "pass",
            "reference_public_ref": "fixture-reference-00",
        },
        {
            "output": {"sha256": image_checksums[1]},
            "ip_visibility_assessment": "pass",
            "reference_public_ref": "fixture-reference-01",
        },
        {
            "output": {"sha256": image_checksums[2]},
            "ip_visibility_assessment": "pass",
            "reference_public_ref": "fixture-reference-02",
        },
    )
    return EditorialSourceBundle(
        evidence_sources=evidence_sources,
        visual_rows=visual_rows,
        image_bodies=image_bodies,
        image_checksums=image_checksums,
        source_content_fingerprint="1" * 64,
        source_render_fingerprint="2" * 64,
        source_run_id="6014f5cc-1755-507a-9ecb-ab72fa41071e",
        source_manifest_sha256="3" * 64,
    )


class _FakeCatalogProvider:
    def __init__(
        self,
        manifest_path: Path,
        *,
        current: bool = True,
        drift_on_revalidate: bool = False,
        duplicate_identity: bool = False,
    ) -> None:
        self.manifest_path = manifest_path
        self.current = current
        self.drift_on_revalidate = drift_on_revalidate
        self.load_calls = 0
        self.revalidate_calls = 0
        self.read_calls = 0
        self.current_calls = 0
        self.publication_bodies = {
            asset_rich.PARENT_QUESTION_PUBLIC_REF: _jpeg_bytes((245, 211, 78), size=(614, 614)),
            asset_rich.AI_BOUNDARY_PUBLIC_REF: _jpeg_bytes((220, 230, 255), size=(1536, 1536)),
        }
        refs = [f"{index + 1:016x}" for index in range(39)] + list(asset_rich.APPROVED_PUBLIC_REFS)
        candidates: list[OfficialAccountSourceMedia] = []
        for index, public_ref in enumerate(refs):
            expected = asset_rich._EXPECTED_CATALOG_ASSETS.get(public_ref)
            body = self.publication_bodies.get(public_ref, f"publication-{index}".encode())
            publication_sha256 = sha256(body).hexdigest()
            if duplicate_identity and index == 1:
                publication_sha256 = candidates[0].sha256
            candidates.append(
                OfficialAccountSourceMedia(
                    source_image_artifact_id=None,
                    fixture_id=f"catalog:{public_ref}",
                    media_type="image/jpeg",
                    byte_size=len(body),
                    sha256=publication_sha256,
                    semantic_label=(expected.label if expected else f"fixture-{index}"),
                    candidate_id=public_ref,
                    semantic_tags=(expected.tags if expected else ("science", f"item-{index}")),
                    alt_text=f"fixture alt {index}",
                    caption_text=f"fixture caption {index}",
                    catalog_asset_id=sha256(f"asset-{index}".encode()).hexdigest(),
                    catalog_asset_ref=public_ref,
                    catalog_version="brand-visual-catalog-v1",
                    source_master_sha256=sha256(f"source-{index}".encode()).hexdigest(),
                )
            )
        self.candidates = tuple(candidates)

    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]:
        self.load_calls += 1
        return self.candidates

    async def revalidate_candidate(
        self, candidate: OfficialAccountSourceMedia
    ) -> OfficialAccountSourceMedia:
        self.revalidate_calls += 1
        if self.drift_on_revalidate:
            return replace(candidate, byte_size=candidate.byte_size + 1)
        return candidate

    async def catalog_is_current(self, candidates: tuple[OfficialAccountSourceMedia, ...]) -> bool:
        self.current_calls += 1
        assert candidates == self.candidates
        return self.current

    async def read_publication_bytes(self, **kwargs: object) -> bytes:
        self.read_calls += 1
        public_ref = str(kwargs["catalog_asset_ref"])
        candidate = next(item for item in self.candidates if item.catalog_asset_ref == public_ref)
        assert kwargs == {
            "catalog_asset_ref": public_ref,
            "catalog_version": candidate.catalog_version,
            "source_master_sha256": candidate.source_master_sha256,
            "publication_sha256": candidate.sha256,
        }
        return self.publication_bodies[public_ref]


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in the asset-rich repackage")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


def test_builds_exact_five_image_evidence_bound_v4_article() -> None:
    article = asset_rich.build_asset_rich_article(_bundle())

    assert asset_rich.REPORT_VERSION == "official-account-news-editorial-asset-rich-demo-v4"
    assert article.versions == asset_rich._versions()
    assert article.versions.model_dump() == {
        "generator_prompt_version": "official-account-news-editorial-assembler-v4-approved-catalog",
        "article_schema_version": (
            "official-account-news-editorial-schema-v4-approved-catalog-five-image"
        ),
        "auditor_prompt_version": "official-account-news-editorial-audit-v4",
        "audit_schema_version": "official-account-news-editorial-audit-schema-v4",
        "rule_version": "official-account-news-editorial-rules-v4-evidence-bound-five-image",
        "renderer_version": "wechat-news-editorial-renderer-v4-approved-catalog-five-image",
        "style_version": "wechat-news-editorial-style-v4-navy-cobalt-orange-cutaways",
        "template_version": "wechat-news-editorial-template-v4-five-image-mobile",
        "local_adapter_version": (
            "official-account-news-editorial-local-adapter-v4-approved-catalog"
        ),
        "media_plan_version": None,
        "visual_query_version": None,
        "visual_selector_version": None,
    }
    assert len(article.sections) == 6
    assert article_body_character_count(article) == 2_182
    assert article.content_fingerprint == article_package_fingerprint(article)
    assert asset_rich._module_shapes(article) == (
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleQuoteBlock, ArticleImageBlock),
        (
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleImageBlock,
            ArticleQuoteBlock,
        ),
        (ArticleParagraphBlock, ArticleParagraphBlock, ArticleBulletListBlock, ArticleImageBlock),
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleImageBlock, ArticleQuoteBlock),
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleParagraphBlock, ArticleImageBlock),
        (ArticleParagraphBlock, ArticleParagraphBlock, ArticleQuoteBlock),
    )
    assert tuple(
        (section_index, block.slot_key)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    ) == (
        (0, "body-0"),
        (1, "body-3"),
        (2, "body-1"),
        (3, "body-4"),
        (4, "body-2"),
    )
    assert tuple((slot.slot_key, slot.role, slot.ordinal) for slot in article.media_slots) == (
        ("body-0", "body", 0),
        ("body-1", "body", 1),
        ("body-2", "body", 2),
        ("body-3", "body", 3),
        ("body-4", "body", 4),
        ("cover-0", "cover", 0),
    )
    images = tuple(
        block
        for section in article.sections
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    assert all(not block.claim_refs for block in images)
    assert asset_rich._as_polished_projection(article) == polished_v3.build_polished_article(
        _bundle()
    )


def test_renderer_keeps_v3_rhythm_and_adds_two_safe_block_bound_cutaways() -> None:
    article = asset_rich.build_asset_rich_article(_bundle())
    html = asset_rich.render_asset_rich_html(article)

    assert html.count("<h1 ") == 1
    assert html.count("<img ") == 5
    assert html.count('data-module="catalog-cutaway"') == 2
    assert html.count('data-cutaway-field="warm"') == 1
    assert html.count('data-cutaway-field="blue"') == 1
    assert "object-fit:contain" in html
    assert all(
        html.count(f'data-module="{marker}"') == 1 for marker in asset_rich._V3_MODULE_MARKERS
    )
    assert html.index(body_media_placeholder(3)) < html.index(polished_v3._STYLE["boundary_note"])
    assert html.index(body_media_placeholder(4)) < html.index(polished_v3._STYLE["boundary_rule"])
    for ordinal in range(5):
        assert html.count(body_media_placeholder(ordinal)) == 1

    malicious = article.model_copy(
        update={
            "title": '<script data-title="x">标题</script>',
            "author": '<img src="https://example.invalid/tracker">',
            "content_fingerprint": "0" * 64,
        }
    )
    malicious = malicious.model_copy(
        update={"content_fingerprint": article_package_fingerprint(malicious)}
    )
    escaped = asset_rich.render_asset_rich_html(malicious)
    assert "<script" not in escaped
    assert "https://example.invalid/tracker" in escaped
    assert '<img src="https://example.invalid/tracker">' not in escaped
    assert "&lt;script data-title=&quot;x&quot;&gt;" in escaped

    question = article.sections[1]
    drifted_image = question.blocks[3].model_copy(update={"alt_text": "changed"})
    drifted_question = question.model_copy(
        update={"blocks": (*question.blocks[:3], drifted_image, question.blocks[4])}
    )
    drifted = article.model_copy(
        update={
            "sections": (article.sections[0], drifted_question, *article.sections[2:]),
            "content_fingerprint": "0" * 64,
        }
    )
    drifted = drifted.model_copy(
        update={"content_fingerprint": article_package_fingerprint(drifted)}
    )
    with pytest.raises(ValueError, match="catalog alt text changed"):
        asset_rich.render_asset_rich_html(drifted)


@pytest.mark.asyncio
async def test_real_approved_catalog_resolves_exact_two_publication_derivatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_network(monkeypatch)
    manifest = (
        Path(__file__).parents[3] / "private" / "brand-materials" / "visual-assets.manifest.json"
    )

    selection = await asset_rich.load_approved_catalog_publications(manifest)

    assert selection.catalog_version == "brand-visual-catalog-v1"
    assert len(selection.complete_catalog_fingerprint) == 64
    assert tuple(item.public_ref for item in selection.publications) == (
        "1bb84f2abb140b8f",
        "bab27fe77a8edff4",
    )
    assert tuple(item.publication_sha256 for item in selection.publications) == (
        "042366d47e654a49f3bac1f710d55becec739c27ed63d8026a6ae3fdca96ea9d",
        "266f21c5f058ef4e321fd9c1ee0e2770d86633fccd039f9df51a87e310f7db47",
    )
    assert tuple((item.width, item.height) for item in selection.publications) == (
        (614, 614),
        (1536, 1536),
    )
    assert tuple(item.slot_key for item in selection.publications) == ("body-3", "body-4")
    assert all(
        sha256(item.body).hexdigest() == item.publication_sha256 for item in selection.publications
    )


@pytest.mark.asyncio
async def test_catalog_resolution_fails_closed_on_drift_and_duplicate_identity(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "explicit-approved-manifest.json"
    drifted = _FakeCatalogProvider(manifest, drift_on_revalidate=True)
    with pytest.raises(ValueError, match="changed during revalidation"):
        await asset_rich.load_approved_catalog_publications(manifest, provider=drifted)
    assert drifted.read_calls == 0

    stale = _FakeCatalogProvider(manifest, current=False)
    with pytest.raises(ValueError, match="changed after publication reads"):
        await asset_rich.load_approved_catalog_publications(manifest, provider=stale)
    assert stale.read_calls == 2

    duplicate = _FakeCatalogProvider(manifest, duplicate_identity=True)
    with pytest.raises(ValueError, match="complete and unique"):
        await asset_rich.load_approved_catalog_publications(manifest, provider=duplicate)
    assert duplicate.revalidate_calls == 0
    assert duplicate.read_calls == 0


def test_export_is_offline_byte_exact_deterministic_safe_and_zero_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_network(monkeypatch)
    bundle = _bundle()
    manifest_path = tmp_path / "private" / "visual-assets.manifest.json"
    provider = _FakeCatalogProvider(manifest_path)
    monkeypatch.setattr(asset_rich, "load_source_bundle", lambda _source_dir: bundle)
    monkeypatch.setattr(
        asset_rich,
        "LocalOfficialAccountCatalogMediaProvider",
        lambda path: provider if path == manifest_path else pytest.fail("unexpected manifest path"),
    )
    first = tmp_path / "first" / "asset-rich-bundle"
    second = tmp_path / "second" / "asset-rich-bundle"

    assert asset_rich.export_asset_rich_bundle(tmp_path / "unused", manifest_path, first) == first
    assert asset_rich.export_asset_rich_bundle(tmp_path / "unused", manifest_path, second) == second
    expected_bodies = (*bundle.image_bodies, *provider.publication_bodies.values())
    for ordinal, expected_body in enumerate(expected_bodies):
        relative = Path("assets") / f"body-{ordinal:02d}.jpg"
        assert (first / relative).read_bytes() == expected_body
        assert (second / relative).read_bytes() == expected_body
    assert (first / "asset-rich-bundle.zip").read_bytes() == (
        second / "asset-rich-bundle.zip"
    ).read_bytes()
    assert provider.load_calls == 2
    assert provider.revalidate_calls == 4
    assert provider.read_calls == 4
    assert provider.current_calls == 2

    html = (first / "article-body.html").read_text(encoding="utf-8")
    assert html.count('src="assets/body-') == 5
    assert html.count('data-module="catalog-cutaway"') == 2
    assert "__OFFICIAL_ACCOUNT_BODY_MEDIA_" not in html
    preview = (first / "preview.html").read_text(encoding="utf-8")
    assert "default-src 'none'" in preview
    assert "img-src 'self'" in preview

    article_payload = _read_json(first / "article-package.json")
    assert article_payload["version"] == asset_rich.ARTICLE_SCHEMA_VERSION
    assert len(article_payload["article"]["media_slots"]) == 6
    run = _read_json(first / "run.json")
    manifest = _read_json(first / "manifest.json")
    for projection in (run, manifest):
        assert projection["manual_review_status"] == "pending"
        assert projection["local_only"] is True
        assert projection["copy_ready"] is False
        assert projection["published"] is False
        assert projection["inherited_historical_paid_image_calls"] == 3
        assert all(projection[field] == 0 for field in asset_rich._ZERO_CALLS)
    assert run["body_image_count"] == 5
    assert manifest["current_repackage_external_calls"] == 0

    visual = _read_json(first / "visual-map.json")
    assert len(visual["visuals"]) == 5
    assert [row["section_index"] for row in visual["visuals"]] == [0, 2, 4, 1, 3]
    assert [row["slot_key"] for row in visual["visuals"]] == [
        "body-0",
        "body-1",
        "body-2",
        "body-3",
        "body-4",
    ]
    catalog_rows = visual["visuals"][3:]
    assert all(
        row["provenance_kind"] == "approved_local_catalog_publication_derivative"
        for row in catalog_rows
    )
    serialized_catalog_rows = json.dumps(catalog_rows, ensure_ascii=False)
    assert "catalog_asset_id" not in serialized_catalog_rows
    assert "manifest_path" not in serialized_catalog_rows
    assert "filename" not in serialized_catalog_rows
    expected_catalog_keys = {
        "ordinal",
        "provenance_kind",
        "catalog_public_ref",
        "catalog_version",
        "source_master_sha256",
        "publication_sha256",
        "media_type",
        "byte_size",
        "width",
        "height",
        "semantic_tags",
        "reader_label",
        "semantic_alt",
        "caption",
        "section_index",
        "slot_key",
        "current_repackage_provider_calls",
    }
    assert all(set(row) == expected_catalog_keys for row in catalog_rows)

    manifested_paths = {row["path"] for row in manifest["files"]}
    assert "manifest.json" not in manifested_paths
    assert "asset-rich-bundle.zip" not in manifested_paths
    for row in manifest["files"]:
        body = (first / row["path"]).read_bytes()
        assert row["byte_size"] == len(body)
        assert row["sha256"] == sha256(body).hexdigest()
    with ZipFile(first / "asset-rich-bundle.zip") as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            f"asset-rich-bundle/{relative}" for relative in manifested_paths | {"manifest.json"}
        }


def test_export_refuses_overwrite_and_cleans_failed_temporary_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    manifest_path = tmp_path / "approved-manifest.json"
    provider = _FakeCatalogProvider(manifest_path)
    monkeypatch.setattr(asset_rich, "load_source_bundle", lambda _source_dir: bundle)
    monkeypatch.setattr(
        asset_rich, "LocalOfficialAccountCatalogMediaProvider", lambda _path: provider
    )
    output = tmp_path / "exports" / "asset-rich-bundle"
    output.mkdir(parents=True)
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to replace"):
        asset_rich.export_asset_rich_bundle(tmp_path / "unused", manifest_path, output)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert provider.load_calls == 0

    failed_output = tmp_path / "failed" / "asset-rich-bundle"

    def fail_write_json(_path: Path, _payload: object) -> None:
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(polished_v3, "_write_json", fail_write_json)
    with pytest.raises(RuntimeError, match="injected write failure"):
        asset_rich.export_asset_rich_bundle(tmp_path / "unused", manifest_path, failed_output)
    assert not failed_output.exists()
    assert not tuple(failed_output.parent.glob(".asset-rich-bundle.*"))
