# ruff: noqa: RUF001 -- Chinese editorial assertions are intentional.
from __future__ import annotations

import json
import socket
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from app import official_account_news_editorial_polished_demo as polished
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


def _bundle() -> EditorialSourceBundle:
    image_bodies = (
        _jpeg_bytes((211, 231, 245)),
        _jpeg_bytes((229, 215, 188)),
        _jpeg_bytes((198, 225, 215)),
    )
    image_checksums: tuple[str, str, str] = (
        sha256(image_bodies[0]).hexdigest(),
        sha256(image_bodies[1]).hexdigest(),
        sha256(image_bodies[2]).hexdigest(),
    )
    evidence_sources = (
        {
            "canonical_url": polished.NEWS_URL,
            "document_sha256": "a" * 64,
            "evidence_id": str(sorted(polished._EXPECTED_EVIDENCE_IDS, key=str)[0]),
            "exact_quote": "科技教育以更加鲜明的学科融合和实践导向持续发力",
            "published_date": "2026-07-21",
            "retrieval_url": polished.NEWS_URL,
            "source_name": "中华人民共和国教育部政府门户网站",
            "title": "面向未来，向新而行",
        },
        {
            "canonical_url": polished.PLAN_URL,
            "document_sha256": "b" * 64,
            "evidence_id": str(sorted(polished._EXPECTED_EVIDENCE_IDS, key=str)[1]),
            "exact_quote": "鼓励开展人工智能跨学科教学",
            "published_date": "2026-04-10",
            "retrieval_url": polished.PLAN_URL,
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


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in the polished editorial repackage")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


def test_builds_distinct_six_module_evidence_bound_v3_article() -> None:
    article = polished.build_polished_article(_bundle())

    assert polished.load_source_bundle is polished.editorial_v2.load_source_bundle
    assert article.versions == polished._versions()
    assert polished.REPORT_VERSION == "official-account-news-editorial-polished-demo-v3"
    assert article.versions.model_dump() == {
        "generator_prompt_version": "official-account-news-editorial-assembler-v3",
        "article_schema_version": "official-account-news-editorial-schema-v3-science-magazine",
        "auditor_prompt_version": "official-account-news-editorial-audit-v3",
        "audit_schema_version": "official-account-news-editorial-audit-schema-v3",
        "rule_version": (
            "official-account-news-editorial-rules-v3-evidence-bound-science-magazine"
        ),
        "renderer_version": "wechat-news-editorial-renderer-v3-science-magazine",
        "style_version": "wechat-news-editorial-style-v3-navy-cobalt-orange",
        "template_version": "wechat-news-editorial-template-v3-high-rhythm-mobile",
        "local_adapter_version": "official-account-news-editorial-local-adapter-v3",
        "media_plan_version": None,
        "visual_query_version": None,
        "visual_selector_version": None,
    }
    assert article.versions != polished.editorial_v2._editorial_versions()
    assert len(article.sections) == 6
    assert article_body_character_count(article) == 2_182
    assert (
        polished.BODY_TARGET_MIN
        <= article_body_character_count(article)
        <= polished.BODY_TARGET_MAX
    )
    assert article.content_fingerprint == article_package_fingerprint(article)
    assert article.content_fingerprint == (
        "566a77fda420b925faf7191c0ccb27ccba69aad04ced0fb374f253d835216e72"
    )
    assert tuple(source.source_url for source in article.sources) == (
        polished.NEWS_URL,
        polished.PLAN_URL,
    )
    source_evidence_ids = {source.evidence_id for source in article.sources}
    external_claims = tuple(claim for claim in article.claims if claim.kind == "external_fact")
    opinions = tuple(claim for claim in article.claims if claim.kind == "opinion")
    assert {
        evidence_id for claim in external_claims for evidence_id in claim.evidence_ids
    } == source_evidence_ids
    assert all(not claim.brand_chunk_ids for claim in external_claims)
    assert all(not claim.evidence_ids and not claim.brand_chunk_ids for claim in opinions)
    assert polished._module_shapes(article) == (
        (
            ArticleParagraphBlock,
            ArticleBulletListBlock,
            ArticleQuoteBlock,
            ArticleImageBlock,
        ),
        (
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleQuoteBlock,
        ),
        (
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleBulletListBlock,
            ArticleImageBlock,
        ),
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleQuoteBlock),
        (
            ArticleParagraphBlock,
            ArticleBulletListBlock,
            ArticleParagraphBlock,
            ArticleImageBlock,
        ),
        (ArticleParagraphBlock, ArticleParagraphBlock, ArticleQuoteBlock),
    )
    boundary_items = article.sections[3].blocks[1]
    assert isinstance(boundary_items, ArticleBulletListBlock)
    assert boundary_items.items == (*polished._AI_ASSIST_ITEMS, *polished._CHILD_OWNS_ITEMS)
    assert boundary_items.claim_refs == ("ai-boundary", "learning-loop")
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

    boundary = article.sections[3]
    shape_drift = boundary.model_copy(
        update={
            "blocks": (
                boundary.blocks[0],
                boundary.blocks[0],
                boundary.blocks[2],
            )
        }
    )
    shape_drift_article = article.model_copy(
        update={
            "sections": (*article.sections[:3], shape_drift, *article.sections[4:]),
            "content_fingerprint": "0" * 64,
        }
    )
    shape_drift_article = shape_drift_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(shape_drift_article)}
    )
    with pytest.raises(ValueError, match="module shape changed"):
        polished.render_polished_html(shape_drift_article)

    opinion_with_evidence = article.claims[3].model_copy(
        update={"evidence_ids": (article.sources[0].evidence_id,)}
    )
    claim_drift_article = article.model_copy(
        update={
            "claims": (*article.claims[:3], opinion_with_evidence, *article.claims[4:]),
            "content_fingerprint": "0" * 64,
        }
    )
    claim_drift_article = claim_drift_article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(claim_drift_article)}
    )
    with pytest.raises(ValueError, match="fact and interpretation bindings changed"):
        polished.render_polished_html(claim_drift_article)


def test_renderer_has_high_rhythm_modules_one_h1_and_exact_images() -> None:
    article = polished.build_polished_article(_bundle())
    html = polished.render_polished_html(article)

    assert html.count("<h1 ") == 1
    assert all(f'data-module="{marker}"' in html for marker in polished._MODULE_MARKERS)
    assert len(polished._MODULE_MARKERS) >= 6
    assert "READING MAP" not in html
    assert "FIELD NOTE" not in html
    assert html.index('data-module="opening-visual"') < html.index('data-module="policy-tiles"')
    assert html.count("__OFFICIAL_ACCOUNT_BODY_MEDIA_") == 3
    for ordinal in range(3):
        assert html.count(body_media_placeholder(ordinal)) == 1
    assert html.count("<img ") == 3
    assert "20 MINUTES" in html
    assert "STEP 01" in html
    assert "STEP 05" in html
    assert "2026.08" not in html
    assert "SCIENCE · EDUCATION · 2026" not in html
    assert "小赛科学现场" not in html
    assert html.count("AI 可以协助") == 1
    assert html.count("孩子必须完成") == 1
    assert html.count("<li ") == 6


def test_renderer_escapes_all_dynamic_text_and_only_emphasizes_allowlisted_phrases() -> None:
    article = polished.build_polished_article(_bundle())
    section = article.sections[0]
    malicious_paragraph = section.blocks[0].model_copy(
        update={
            "text": (
                "创新能力和综合素养<script>alert(1)</script>"
                "<em onclick=alert(2)>不是允许的强调</em>。"
            )
        }
    )
    assert isinstance(malicious_paragraph, ArticleParagraphBlock)
    malicious_image = section.blocks[3].model_copy(
        update={"alt_text": '"><svg/onload=alert(3)>小赛'}
    )
    changed_section = section.model_copy(
        update={
            "blocks": (
                malicious_paragraph,
                section.blocks[1],
                section.blocks[2],
                malicious_image,
            )
        }
    )
    boundary = article.sections[3]
    boundary_list = boundary.blocks[1]
    assert isinstance(boundary_list, ArticleBulletListBlock)
    malicious_boundary_list = boundary_list.model_copy(
        update={
            "items": (
                '<a href="https://example.invalid">恶意链接</a>',
                *boundary_list.items[1:],
            )
        }
    )
    changed_boundary = boundary.model_copy(
        update={
            "blocks": (
                boundary.blocks[0],
                malicious_boundary_list,
                boundary.blocks[2],
            )
        }
    )
    changed = article.model_copy(
        update={
            "title": '<script data-title="x">标题</script>',
            "author": '<img src="https://example.invalid/tracker">',
            "sections": (
                changed_section,
                *article.sections[1:3],
                changed_boundary,
                *article.sections[4:],
            ),
            "content_fingerprint": "0" * 64,
        }
    )
    changed = changed.model_copy(
        update={"content_fingerprint": article_package_fingerprint(changed)}
    )

    html = polished.render_polished_html(changed)
    assert "<script" not in html
    assert "<em" not in html
    assert "<svg" not in html
    assert "<a href" not in html
    assert "&lt;img src=&quot;https://example.invalid/tracker&quot;&gt;" in html
    assert "&lt;script data-title=&quot;x&quot;&gt;" in html
    assert "&lt;em onclick=alert(2)&gt;" in html
    assert "&lt;a href=&quot;https://example.invalid&quot;&gt;" in html
    assert "&quot;&gt;&lt;svg/onload=alert(3)&gt;" in html
    standalone = polished._emphasized_html("创新能力和综合素养；<em>未授权短语</em>；观察并判断")
    assert standalone.count("<strong ") == 1
    assert "&lt;em&gt;未授权短语&lt;/em&gt;" in standalone

    unsafe_source = article.sources[0].model_copy(
        update={"source_url": "https://example.invalid/not-approved"}
    )
    unsafe = article.model_copy(
        update={
            "sources": (unsafe_source, article.sources[1]),
            "content_fingerprint": "0" * 64,
        }
    )
    unsafe = unsafe.model_copy(update={"content_fingerprint": article_package_fingerprint(unsafe)})
    with pytest.raises(ValueError, match="source set changed"):
        polished.render_polished_html(unsafe)


def test_export_is_offline_byte_exact_deterministic_and_zero_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_network(monkeypatch)
    bundle = _bundle()
    monkeypatch.setattr(polished, "load_source_bundle", lambda _source_dir: bundle)
    first = tmp_path / "first" / "polished-bundle"
    second = tmp_path / "second" / "polished-bundle"

    assert polished.export_polished_bundle(tmp_path / "unused-source", first) == first
    assert polished.export_polished_bundle(tmp_path / "unused-source", second) == second
    for ordinal, expected_body in enumerate(bundle.image_bodies):
        relative_path = Path("assets") / f"body-{ordinal:02d}.jpg"
        assert (first / relative_path).read_bytes() == expected_body
        assert (second / relative_path).read_bytes() == expected_body
    assert (first / "polished-bundle.zip").read_bytes() == (
        second / "polished-bundle.zip"
    ).read_bytes()

    html = (first / "article-body.html").read_text(encoding="utf-8")
    assert html.count('src="assets/body-') == 3
    assert "__OFFICIAL_ACCOUNT_BODY_MEDIA_" not in html
    assert "READING MAP" not in html
    assert "FIELD NOTE" not in html
    assert "https://mp.weixin.qq.com" not in html
    assert "未同步公众号" in html
    preview = (first / "preview.html").read_text(encoding="utf-8")
    assert "default-src 'none'" in preview

    run = _read_json(first / "run.json")
    assert run["version"] == polished.REPORT_VERSION
    assert run["manual_review_status"] == "pending"
    assert run["local_only"] is True
    assert run["copy_ready"] is False
    assert run["published"] is False
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
    reference = _read_json(first / "reference-learning.json")
    assert reference["retained_source_content"] is False
    assert reference["retained_source_html"] is False
    assert reference["retained_source_images"] is False
    assert reference["copied_reference_expression"] is False

    manifest = _read_json(first / "manifest.json")
    assert manifest["current_repackage_external_calls"] == 0
    assert manifest["inherited_historical_paid_image_calls"] == 3
    assert manifest["manual_review_status"] == "pending"
    assert manifest["local_only"] is True
    assert manifest["copy_ready"] is False
    assert manifest["published"] is False
    assert all(
        manifest[field] == 0
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
    manifested_paths = {row["path"] for row in manifest["files"]}
    assert "article-package.json" in manifested_paths
    assert "manifest.json" not in manifested_paths
    assert "polished-bundle.zip" not in manifested_paths
    for row in manifest["files"]:
        path = first / row["path"]
        body = path.read_bytes()
        assert row["byte_size"] == len(body)
        assert row["sha256"] == sha256(body).hexdigest()
    with ZipFile(first / "polished-bundle.zip") as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        assert set(names) == {
            f"polished-bundle/{relative_path}"
            for relative_path in manifested_paths | {"manifest.json"}
        }
        for relative_path in manifested_paths | {"manifest.json"}:
            assert (
                archive.read(f"polished-bundle/{relative_path}")
                == (first / relative_path).read_bytes()
            )


def test_export_refuses_overwrite_and_cleans_failed_temporary_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle()
    monkeypatch.setattr(polished, "load_source_bundle", lambda _source_dir: bundle)
    output = tmp_path / "exports" / "polished-bundle"
    output.mkdir(parents=True)
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to replace"):
        polished.export_polished_bundle(tmp_path / "unused-source", output)
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    failed_output = tmp_path / "failed" / "polished-bundle"

    def fail_write_json(_path: Path, _payload: object) -> None:
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(polished, "_write_json", fail_write_json)
    with pytest.raises(RuntimeError, match="injected write failure"):
        polished.export_polished_bundle(tmp_path / "unused-source", failed_output)
    assert not failed_output.exists()
    assert not tuple(failed_output.parent.glob(".polished-bundle.*"))
