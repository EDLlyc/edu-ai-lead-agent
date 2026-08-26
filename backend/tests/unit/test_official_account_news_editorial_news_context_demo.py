# ruff: noqa: ASYNC240 -- bounded temporary fixture filesystem work is intentional.
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
from app import official_account_news_editorial_news_context_demo as news_v6
from PIL import Image


def _jpeg_bytes(color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _source_html() -> str:
    body_images = "".join(
        f'<img src="assets/{name}" alt="小赛场景 {index}">'
        for index, name in enumerate(news_v6.BODY_IMAGE_NAMES)
    )
    return (
        '<section style="overflow:hidden"><h1 style="margin:0">标题</h1>'
        f"{body_images}"
        '<section data-module="policy-tiles"><p>政策正文</p></section>'
        '<section data-module="parent-question-cards"><p>家长问题</p>'
        '<section data-module="semantic-generated-scene"><p>IP scene</p></section></section>'
        '<section data-module="ai-child-boundary"><p>AI边界</p>'
        '<section data-module="semantic-generated-scene"><p>IP scene</p></section></section>'
        '<section data-module="action-timeline"><p>行动</p></section></section>'
    )


def _write_v5_source(root: Path) -> tuple[bytes, bytes, bytes, bytes, bytes]:
    (root / "assets").mkdir(parents=True)
    (root / "intents").mkdir()
    bodies = tuple(
        _jpeg_bytes(((index * 37) % 255, (index * 61) % 255, (index * 83) % 255), (1536, 1024))
        for index in range(5)
    )
    for name, body in zip(news_v6.BODY_IMAGE_NAMES, bodies, strict=True):
        (root / "assets" / name).write_bytes(body)
    (root / "article-body.html").write_text(_source_html(), encoding="utf-8")
    (root / "article.md").write_text("# 标题\n\n本地文章。\n", encoding="utf-8")
    _write_json(
        root / "article-package.json",
        {
            "version": news_v6.semantic_v5.ARTICLE_SCHEMA_VERSION,
            "article": {
                "title": "标题",
                "media_slots": [
                    {"ordinal": index, "role": "body", "slot_key": f"body-{index}"}
                    for index in range(5)
                ]
                + [{"ordinal": 0, "role": "cover", "slot_key": "cover-0"}],
                "sections": [
                    {
                        "blocks": [
                            {"kind": "image", "slot_key": f"body-{index}"} for index in range(5)
                        ]
                    }
                ],
            },
        },
    )
    _write_json(
        root / "evidence.json",
        {"version": "official-account-news-editorial-evidence-v5", "sources": []},
    )
    _write_json(
        root / "reference-learning.json",
        {"version": "wechat-public-reference-patterns-v4-semantic-five-scene"},
    )
    _write_json(
        root / "semantic-selection.json",
        {
            "version": "semantic-v5",
            "status": "semantic_ready",
            "query_call_count": 2,
            "assignments": [{"ordinal": 3}, {"ordinal": 4}],
        },
    )
    _write_json(
        root / "visual-map.json",
        {
            "version": "official-account-news-editorial-visual-map-v5-five-scene",
            "visuals": [
                {
                    "ordinal": index,
                    "output_sha256": sha256(body).hexdigest(),
                    "provenance_kind": "inherited_ip_scene",
                }
                for index, body in enumerate(bodies)
            ],
        },
    )
    for name in (
        "body-3.intent.json",
        "body-3.result.json",
        "body-4.intent.json",
        "body-4.result.json",
    ):
        _write_json(root / "intents" / name, {"fixture": name})
    (root / "preview.html").write_text(_source_html(), encoding="utf-8")
    (root / "README.md").write_text("# Frozen v5 fixture\n", encoding="utf-8")
    _write_json(
        root / "run.json",
        {
            "version": news_v6.SOURCE_VERSION,
            "run_id": "ae1ba45f-d337-5ca9-bf8b-d8f3474faa4c",
            "status": "ready",
            "simulation": True,
            "local_only": True,
            "copy_ready": False,
            "published": False,
            "manual_review_status": "pending",
            "body_image_count": 5,
            "embedding_provider_calls": 2,
            "paid_generation_calls_attempted": 2,
            "paid_generation_calls_succeeded": 2,
            "comfly_calls": 0,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
        },
    )
    manifest_files = tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    _write_json(
        root / "manifest.json",
        {
            "version": news_v6.SOURCE_VERSION,
            "status": "ready",
            "simulation": True,
            "local_only": True,
            "published": False,
            "manual_review_status": "pending",
            "embedding_provider_calls": 2,
            "image_provider_calls": 2,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
            "files": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "byte_size": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
                for path in manifest_files
            ],
        },
    )
    return bodies[0], bodies[1], bodies[2], bodies[3], bodies[4]


class _FakeFetcher:
    def __init__(
        self,
        responses: dict[str, news_v6.PhotoFetchResponse],
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, url: str, *, max_bytes: int) -> news_v6.PhotoFetchResponse:
        self.calls.append((url, max_bytes))
        return self.responses[url]


def _install_test_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    tuple[news_v6.NewsContextPhoto, news_v6.NewsContextPhoto],
    tuple[bytes, bytes],
]:
    bodies = (
        _jpeg_bytes((210, 222, 234), (64, 40)),
        _jpeg_bytes((232, 218, 190), (80, 50)),
    )
    specs = tuple(
        replace(
            spec,
            width=(64, 80)[index],
            height=(40, 50)[index],
            sha256=sha256(bodies[index]).hexdigest(),
        )
        for index, spec in enumerate(news_v6.NEWS_CONTEXT_PHOTOS)
    )
    assert len(specs) == 2
    typed_specs = (specs[0], specs[1])
    monkeypatch.setattr(news_v6, "NEWS_CONTEXT_PHOTOS", typed_specs)
    monkeypatch.setattr(
        news_v6,
        "ALLOWED_IMAGE_URLS",
        frozenset(spec.image_url for spec in typed_specs),
    )
    monkeypatch.setattr(
        news_v6,
        "ALLOWED_SOURCE_PAGE_URLS",
        frozenset(spec.source_page_url for spec in typed_specs),
    )
    return typed_specs, bodies


def _fetcher_for(
    specs: tuple[news_v6.NewsContextPhoto, news_v6.NewsContextPhoto],
    bodies: tuple[bytes, bytes],
) -> _FakeFetcher:
    return _FakeFetcher(
        {
            spec.image_url: news_v6.PhotoFetchResponse(
                status_code=200,
                media_type="image/jpeg",
                final_url=spec.image_url,
                body=body,
            )
            for spec, body in zip(specs, bodies, strict=True)
        }
    )


def test_frozen_official_photo_sources_and_rights_boundary() -> None:
    first, second = news_v6.NEWS_CONTEXT_PHOTOS
    assert first.image_url.endswith("W020260723357821146376.jpg")
    assert first.sha256 == "0d2427caf395ba0d55eaf66678e2d67dd9bc581e2813d5860505e232c2e3811d"
    assert (first.width, first.height) == (575, 354)
    assert second.image_url.endswith("W020260410433219993653.jpg")
    assert second.sha256 == "ea635b7ecca51e8073ae3bd7954d8fc03234f49dda52e3a675f2591d75a7afb5"
    assert (second.width, second.height) == (800, 535)
    assert news_v6.ALLOWED_IMAGE_URLS == frozenset(
        {
            "https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2026/2026_zt09/jdt/"
            "202607/W020260723357821146376.jpg",
            "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/W020260410433219993653.jpg",
        }
    )
    assert news_v6.ALLOWED_SOURCE_PAGE_URLS == frozenset(
        {
            "https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html",
            "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html",
        }
    )
    assert news_v6.RIGHTS_STATUS == "publish_permission_unverified"


def test_news_photo_html_escapes_projection_text() -> None:
    photo = replace(
        news_v6.NEWS_CONTEXT_PHOTOS[0],
        public_ref='unsafe" onload="alert(1)',
        relation_label="<script>relation</script>",
        alt_text='unsafe" onerror="alert(2)',
        caption="<b>caption</b>",
        credit="credit & source",
    )

    html = news_v6._photo_html(photo)

    assert "<script>" not in html
    assert "<b>caption</b>" not in html
    assert 'onload="alert(1)' not in html
    assert 'onerror="alert(2)' not in html
    assert "&lt;script&gt;relation&lt;/script&gt;" in html
    assert "credit &amp; source" in html


@pytest.mark.asyncio
async def test_export_adds_two_context_photos_without_replacing_five_ip_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source-v5"
    source_bodies = _write_v5_source(source)
    specs, photo_bodies = _install_test_photos(monkeypatch)
    fetcher = _fetcher_for(specs, photo_bodies)
    output = tmp_path / "first" / "bundle-v6"

    result = await news_v6.export_news_context_bundle(source, output, fetcher=fetcher)

    assert result == output
    assert fetcher.calls == [(spec.image_url, news_v6.MAX_PHOTO_BYTES) for spec in specs]
    for name, expected in zip(news_v6.BODY_IMAGE_NAMES, source_bodies, strict=True):
        assert (output / "assets" / name).read_bytes() == expected
    assert (output / "assets" / "news-00.jpg").read_bytes() == photo_bodies[0]
    assert (output / "assets" / "news-01.jpg").read_bytes() == photo_bodies[1]
    html = (output / "article-body.html").read_text(encoding="utf-8")
    assert html.count('data-module="news-context-photo"') == 2
    assert html.count('data-module="semantic-generated-scene"') == 2
    assert html.count("<h1 ") == 1
    assert "object-fit" not in "".join(
        block.split("</section>", 1)[0]
        for block in html.split('data-module="news-context-photo"')[1:]
    )
    assert news_v6.RIGHTS_WARNING in html
    assert "<script>" not in html
    assert (output / "article-package.json").read_bytes() == (
        source / "article-package.json"
    ).read_bytes()
    assert "不替代正文事实证据" in (output / "README.md").read_text(encoding="utf-8")
    run = _read_json(output / "run.json")
    assert run["body_image_count"] == 7
    assert run["official_photo_get_calls"] == 2
    assert all(
        run[key] == 0
        for key in (
            "article_provider_calls",
            "embedding_provider_calls",
            "image_provider_calls",
            "toapis_calls",
            "comfly_calls",
            "wechat_calls",
            "wecom_calls",
            "publish_calls",
        )
    )
    assert run["rights_status"] == news_v6.RIGHTS_STATUS
    assert run["rights_warning"] == news_v6.RIGHTS_WARNING
    assert run["copy_ready"] is run["published"] is False
    provenance = _read_json(output / "news-photo-provenance.json")
    assert len(provenance["photos"]) == 2
    assert all(row["source_bytes_preserved"] for row in provenance["photos"])
    assert all(row["claim_role"] == "context_only_not_evidence" for row in provenance["photos"])
    for projection_name in ("manifest.json", "visual-map.json", "news-photo-provenance.json"):
        assert _read_json(output / projection_name)["rights_warning"] == news_v6.RIGHTS_WARNING


@pytest.mark.asyncio
async def test_exports_are_deterministic_and_archive_contains_seven_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source-v5"
    _write_v5_source(source)
    specs, bodies = _install_test_photos(monkeypatch)
    first = tmp_path / "first" / "bundle-v6"
    second = tmp_path / "second" / "bundle-v6"

    await news_v6.export_news_context_bundle(source, first, fetcher=_fetcher_for(specs, bodies))
    await news_v6.export_news_context_bundle(source, second, fetcher=_fetcher_for(specs, bodies))

    first_zip = first / "bundle-v6.zip"
    second_zip = second / "bundle-v6.zip"
    assert first_zip.read_bytes() == second_zip.read_bytes()
    with ZipFile(first_zip) as archive:
        image_names = [name for name in archive.namelist() if "/assets/" in name]
        assert len(image_names) == 7
        assert len(set(image_names)) == 7
    manifest = _read_json(first / "manifest.json")
    assert manifest["visual_count"] == 7
    for row in manifest["files"]:
        path = first / row["path"]
        assert row["byte_size"] == path.stat().st_size
        assert row["sha256"] == sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "match"),
    (
        ("checksum", "checksum"),
        ("dimensions", "dimensions"),
        ("media_type", "response contract"),
        ("final_url", "response contract"),
    ),
)
async def test_invalid_photo_response_fails_without_installing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    match: str,
) -> None:
    source = tmp_path / "source-v5"
    _write_v5_source(source)
    specs, bodies = _install_test_photos(monkeypatch)
    responses = _fetcher_for(specs, bodies).responses
    second = responses[specs[1].image_url]
    if change == "checksum":
        second = replace(second, body=_jpeg_bytes((1, 2, 3), (80, 50)))
    elif change == "dimensions":
        wrong = _jpeg_bytes((232, 218, 190), (81, 50))
        specs = (specs[0], replace(specs[1], sha256=sha256(wrong).hexdigest()))
        monkeypatch.setattr(news_v6, "NEWS_CONTEXT_PHOTOS", specs)
        second = replace(second, body=wrong)
    elif change == "media_type":
        second = replace(second, media_type="text/html")
    else:
        second = replace(second, final_url="https://www.moe.gov.cn/redirected.jpg")
    responses[specs[1].image_url] = second
    output = tmp_path / "bundle-v6"

    with pytest.raises(ValueError, match=match):
        await news_v6.export_news_context_bundle(source, output, fetcher=_FakeFetcher(responses))

    assert not output.exists()
    assert not tuple(tmp_path.glob(".bundle-v6.*"))


@pytest.mark.asyncio
async def test_source_tamper_and_existing_destination_stop_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source-v5"
    _write_v5_source(source)
    specs, bodies = _install_test_photos(monkeypatch)
    tampered_fetcher = _fetcher_for(specs, bodies)
    (source / "article-body.html").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="identity"):
        await news_v6.export_news_context_bundle(
            source, tmp_path / "tampered-output", fetcher=tampered_fetcher
        )
    assert tampered_fetcher.calls == []

    clean_source = tmp_path / "clean-v5"
    _write_v5_source(clean_source)
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    existing_fetcher = _fetcher_for(specs, bodies)
    with pytest.raises(FileExistsError):
        await news_v6.export_news_context_bundle(clean_source, existing, fetcher=existing_fetcher)
    assert existing_fetcher.calls == []
    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_unallowlisted_url_is_rejected_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, bodies = _install_test_photos(monkeypatch)
    changed = replace(specs[1], image_url="https://example.com/news.jpg")
    monkeypatch.setattr(news_v6, "NEWS_CONTEXT_PHOTOS", (specs[0], changed))
    fetcher = _fetcher_for(specs, bodies)

    with pytest.raises(ValueError, match="identity"):
        await news_v6.fetch_news_context_photos(fetcher)

    assert fetcher.calls == []


@pytest.mark.asyncio
async def test_export_with_injected_fetcher_uses_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source-v5"
    _write_v5_source(source)
    specs, bodies = _install_test_photos(monkeypatch)

    def _blocked_socket(*args: object, **kwargs: object) -> socket.socket:
        del args, kwargs
        raise AssertionError("default test path attempted a network socket")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    result = await news_v6.export_news_context_bundle(
        source,
        tmp_path / "bundle-v6",
        fetcher=_fetcher_for(specs, bodies),
    )
    assert result.is_dir()
