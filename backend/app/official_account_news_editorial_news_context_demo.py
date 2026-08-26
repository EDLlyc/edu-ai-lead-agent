"""Add two pinned official news-context photos to the frozen local v5 bundle."""

# ruff: noqa: ASYNC240, RUF001 -- bounded operator FS work and Chinese copy are intentional.
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from app import official_account_news_editorial_polished_demo as polished_v3
from app import official_account_news_editorial_semantic_generated_demo as semantic_v5

REPORT_VERSION = "official-account-news-editorial-news-context-demo-v6"
NEWS_PHOTO_PROVENANCE_VERSION = "official-account-news-context-photo-provenance-v1"
VISUAL_MAP_VERSION = "official-account-news-editorial-visual-map-v6-seven-visual"
RENDERER_VERSION = "wechat-news-editorial-renderer-v6-five-ip-two-official-photo"
STYLE_VERSION = "wechat-news-editorial-style-v6-navy-cobalt-orange-news-photo"
TEMPLATE_VERSION = "wechat-news-editorial-template-v6-seven-visual-mobile"
RIGHTS_STATUS = "publish_permission_unverified"
RIGHTS_WARNING = "图片转载授权尚未核验，公开发布前需确认图片转载授权。"
SOURCE_VERSION = semantic_v5.REPORT_VERSION
MAX_SOURCE_FILE_BYTES = 25 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PHOTO_BYTES = 15 * 1024 * 1024
DEFAULT_SOURCE_DIR = semantic_v5.DEFAULT_OUTPUT_DIR
DEFAULT_OUTPUT_DIR = Path("output/official-account-news-ip-editorial-news-context-20260825-v6")
BODY_IMAGE_NAMES = tuple(f"body-{ordinal:02d}.jpg" for ordinal in range(5))
BODY_SLOT_KEYS = tuple(f"body-{ordinal}" for ordinal in range(5))
V5_MANIFEST_PATHS = frozenset(
    {
        "README.md",
        "article-body.html",
        "article-package.json",
        "article.md",
        "evidence.json",
        "intents/body-3.intent.json",
        "intents/body-3.result.json",
        "intents/body-4.intent.json",
        "intents/body-4.result.json",
        "preview.html",
        "reference-learning.json",
        "run.json",
        "semantic-selection.json",
        "visual-map.json",
        *(f"assets/{name}" for name in BODY_IMAGE_NAMES),
    }
)


@dataclass(frozen=True, slots=True)
class NewsContextPhoto:
    public_ref: str
    asset_name: str
    relation_label: str
    source_page_url: str
    image_url: str
    alt_text: str
    caption: str
    credit: str
    media_type: str
    width: int
    height: int
    sha256: str
    placement_anchor: str
    rights_status: str


NEWS_CONTEXT_PHOTOS = (
    NewsContextPhoto(
        public_ref="moe-basic-education-conference-20260722",
        asset_name="news-00.jpg",
        relation_label="关联新闻现场｜全国基础教育工作会议",
        source_page_url=(
            "https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html"
        ),
        image_url=(
            "https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2026/2026_zt09/jdt/"
            "202607/W020260723357821146376.jpg"
        ),
        alt_text="全国基础教育工作会议现场，与基础教育改革新闻背景相呼应",
        caption=(
            "7月22日，全国基础教育工作会议在北京召开。中共中央政治局常委、"
            "国务院副总理丁薛祥出席会议并讲话。"
        ),
        credit="新华社记者 高洁 摄",
        media_type="image/jpeg",
        width=575,
        height=354,
        sha256="0d2427caf395ba0d55eaf66678e2d67dd9bc581e2813d5860505e232c2e3811d",
        placement_anchor='<section data-module="parent-question-cards"',
        rights_status=RIGHTS_STATUS,
    ),
    NewsContextPhoto(
        public_ref="moe-ai-education-press-conference-20260410",
        asset_name="news-01.jpg",
        relation_label="关联新闻现场｜“人工智能+教育”行动计划发布会",
        source_page_url=(
            "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html"
        ),
        image_url=(
            "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/W020260410433219993653.jpg"
        ),
        alt_text="教育部介绍人工智能加教育行动计划的新闻发布会现场",
        caption="教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。",
        credit="中国教育报记者 张劲松/摄",
        media_type="image/jpeg",
        width=800,
        height=535,
        sha256="ea635b7ecca51e8073ae3bd7954d8fc03234f49dda52e3a675f2591d75a7afb5",
        placement_anchor='<section data-module="action-timeline"',
        rights_status=RIGHTS_STATUS,
    ),
)
ALLOWED_IMAGE_URLS = frozenset(photo.image_url for photo in NEWS_CONTEXT_PHOTOS)
ALLOWED_SOURCE_PAGE_URLS = frozenset(photo.source_page_url for photo in NEWS_CONTEXT_PHOTOS)


@dataclass(frozen=True, slots=True)
class PhotoFetchResponse:
    status_code: int
    media_type: str
    final_url: str
    body: bytes


@dataclass(frozen=True, slots=True)
class PhotoAcquisitionLedger:
    mode: Literal["network", "validated_local_cache"]
    successful_get_calls: int
    cache_reads: int
    failed_get_attempts_before_export: int = 0

    def validate(self) -> None:
        if (
            self.successful_get_calls < 0
            or self.cache_reads < 0
            or not 0 <= self.failed_get_attempts_before_export <= 2
            or self.successful_get_calls + self.cache_reads != 2
            or (self.mode == "network" and (self.successful_get_calls, self.cache_reads) != (2, 0))
            or (
                self.mode == "validated_local_cache"
                and (self.successful_get_calls, self.cache_reads) != (0, 2)
            )
        ):
            raise ValueError("official photo acquisition ledger is invalid")


NETWORK_ACQUISITION = PhotoAcquisitionLedger(mode="network", successful_get_calls=2, cache_reads=0)


class OfficialPhotoFetcher(Protocol):
    async def fetch(self, url: str, *, max_bytes: int) -> PhotoFetchResponse: ...


@dataclass(frozen=True, slots=True)
class ValidatedNewsPhoto:
    spec: NewsContextPhoto
    body: bytes


@dataclass(frozen=True, slots=True)
class ValidatedV5Bundle:
    source_dir: Path
    source_manifest_sha256: str
    article_body_html: str
    article_markdown: str
    article_package: Mapping[str, Any]
    evidence: Mapping[str, Any]
    reference_learning: Mapping[str, Any]
    semantic_selection: Mapping[str, Any]
    source_run: Mapping[str, Any]
    source_visual_map: Mapping[str, Any]
    body_images: tuple[bytes, bytes, bytes, bytes, bytes]


class HttpxOfficialPhotoFetcher:
    """Fetch one exact official JPEG without redirects or automatic retries."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, url: str, *, max_bytes: int) -> PhotoFetchResponse:
        _validate_image_url(url)
        source_page = next(
            (photo.source_page_url for photo in NEWS_CONTEXT_PHOTOS if photo.image_url == url),
            None,
        )
        if source_page is None:
            raise ValueError("official photo source page is unavailable")
        _validate_source_page_url(source_page)
        body = bytearray()
        async with self._client.stream(
            "GET",
            url,
            headers={
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": source_page,
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
                ),
            },
        ) as response:
            final_url = str(response.url)
            media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if response.status_code != 200:
                raise ValueError("official photo response status is not successful")
            if final_url != url:
                raise ValueError("official photo response URL changed")
            content_length = response.headers.get("content-length")
            if content_length is not None and int(content_length) > max_bytes:
                raise ValueError("official photo response is too large")
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError("official photo response is too large")
        return PhotoFetchResponse(
            status_code=200,
            media_type=media_type,
            final_url=final_url,
            body=bytes(body),
        )


class LocalCachedOfficialPhotoFetcher:
    """Read already-acquired exact official bytes without another network request."""

    def __init__(self, paths: Mapping[str, Path]) -> None:
        if frozenset(paths) != ALLOWED_IMAGE_URLS:
            raise ValueError("cached official photo set is incomplete")
        self._paths = dict(paths)

    async def fetch(self, url: str, *, max_bytes: int) -> PhotoFetchResponse:
        _validate_image_url(url)
        path = self._paths[url]
        if path.is_symlink() or not path.is_file():
            raise ValueError("cached official photo is unavailable")
        if path.stat().st_size > max_bytes:
            raise ValueError("cached official photo is too large")
        body = path.read_bytes()
        if len(body) > max_bytes:
            raise ValueError("cached official photo is too large")
        spec = next(photo for photo in NEWS_CONTEXT_PHOTOS if photo.image_url == url)
        return PhotoFetchResponse(
            status_code=200,
            media_type=spec.media_type,
            final_url=url,
            body=body,
        )


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("required source JSON is not a regular file")
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("required source JSON is invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("required source JSON must be an object")
    return payload


def _safe_manifest_path(raw_path: object) -> PurePosixPath:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("source manifest path is invalid")
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or path.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("source manifest path is unsafe")
    return path


def _validate_jpeg(
    body: bytes,
    *,
    expected_size: tuple[int, int],
    expected_sha256: str | None = None,
    metadata_free: bool = False,
) -> None:
    if not body or len(body) > MAX_PHOTO_BYTES:
        raise ValueError("JPEG bytes are outside the allowed size")
    if not body.startswith(b"\xff\xd8\xff") or not body.endswith(b"\xff\xd9"):
        raise ValueError("JPEG signature is invalid")
    if expected_sha256 is not None and sha256(body).hexdigest() != expected_sha256:
        raise ValueError("JPEG checksum changed")
    try:
        with Image.open(BytesIO(body)) as image:
            image.load()
            if (
                image.format != "JPEG"
                or image.size != expected_size
                or bool(getattr(image, "is_animated", False))
                or bool(image.info.get("progressive") or image.info.get("progression"))
            ):
                raise ValueError("JPEG format or dimensions changed")
            if metadata_free and (image.getexif() or image.info.get("icc_profile")):
                raise ValueError("inherited publication JPEG metadata changed")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("JPEG cannot be decoded") from error


def load_v5_bundle(source_dir: Path) -> ValidatedV5Bundle:
    """Fail closed on the complete frozen v5 manifest before any photo GET."""

    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("v5 source directory is unavailable")
    manifest_path = source_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("required source manifest is not a regular file")
    manifest_size = manifest_path.stat().st_size
    if manifest_size > MAX_SOURCE_FILE_BYTES:
        raise ValueError("required source manifest is too large")
    manifest_body = manifest_path.read_bytes()
    manifest = _read_json_object(manifest_path)
    if any(
        manifest.get(key) != value
        for key, value in {
            "version": SOURCE_VERSION,
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
        }.items()
    ):
        raise ValueError("v5 source manifest boundary changed")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("v5 source manifest file set is invalid")
    declared: dict[str, bytes] = {}
    total_size = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("v5 source manifest row is invalid")
        relative = _safe_manifest_path(row.get("path"))
        relative_key = relative.as_posix()
        if relative_key in declared:
            raise ValueError("v5 source manifest path is duplicated")
        path = source_dir.joinpath(*relative.parts)
        relative_parent = source_dir
        for part in relative.parts[:-1]:
            relative_parent /= part
            if relative_parent.is_symlink() or not relative_parent.is_dir():
                raise ValueError("v5 source path parent is unsafe")
        if path.is_symlink() or not path.is_file():
            raise ValueError("v5 source file is unavailable")
        size = path.stat().st_size
        if size > MAX_SOURCE_FILE_BYTES or total_size + size > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError("v5 source file set is too large")
        body = path.read_bytes()
        total_size += len(body)
        if (
            len(body) != size
            or row.get("byte_size") != len(body)
            or row.get("sha256") != sha256(body).hexdigest()
        ):
            raise ValueError("v5 source file identity changed")
        declared[relative_key] = body
    if frozenset(declared) != V5_MANIFEST_PATHS:
        raise ValueError("v5 source manifest is incomplete")

    def declared_json(relative_path: str) -> dict[str, Any]:
        try:
            payload = json.loads(declared[relative_path])
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("required source JSON is invalid") from error
        if not isinstance(payload, dict):
            raise ValueError("required source JSON must be an object")
        return payload

    run = declared_json("run.json")
    if any(
        run.get(key) != value
        for key, value in {
            "version": SOURCE_VERSION,
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
        }.items()
    ):
        raise ValueError("v5 source run boundary changed")
    article_package = declared_json("article-package.json")
    if article_package.get("version") != semantic_v5.ARTICLE_SCHEMA_VERSION:
        raise ValueError("v5 Article Package identity changed")
    article = article_package.get("article")
    if not isinstance(article, dict):
        raise ValueError("v5 Article Package payload changed")
    media_slots = article.get("media_slots")
    expected_slots = [
        {"ordinal": ordinal, "role": "body", "slot_key": slot_key}
        for ordinal, slot_key in enumerate(BODY_SLOT_KEYS)
    ] + [{"ordinal": 0, "role": "cover", "slot_key": "cover-0"}]
    if media_slots != expected_slots:
        raise ValueError("v5 Article Package five-slot boundary changed")
    sections = article.get("sections")
    if not isinstance(sections, list):
        raise ValueError("v5 Article Package section set changed")
    image_slot_keys: list[str] = []
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
            raise ValueError("v5 Article Package section set changed")
        for block in section["blocks"]:
            if isinstance(block, dict) and block.get("kind") == "image":
                slot_key = block.get("slot_key")
                if not isinstance(slot_key, str):
                    raise ValueError("v5 Article Package image slot changed")
                image_slot_keys.append(slot_key)
    if sorted(image_slot_keys) != sorted(BODY_SLOT_KEYS):
        raise ValueError("v5 Article Package image-slot bindings changed")
    article_html = declared["article-body.html"].decode("utf-8")
    if (
        article_html.count('data-module="semantic-generated-scene"') != 2
        or article_html.count("<h1 ") != 1
        or any(article_html.count(f"assets/{name}") != 1 for name in BODY_IMAGE_NAMES)
        or any(article_html.count(photo.placement_anchor) != 1 for photo in NEWS_CONTEXT_PHOTOS)
        or 'data-module="news-context-photo"' in article_html
    ):
        raise ValueError("v5 source HTML shape changed")
    body_images = tuple(declared[f"assets/{name}"] for name in BODY_IMAGE_NAMES)
    for body in body_images:
        _validate_jpeg(body, expected_size=(1536, 1024), metadata_free=True)
    if len({sha256(body).hexdigest() for body in body_images}) != 5:
        raise ValueError("v5 source body images are not distinct")
    source_visual_map = declared_json("visual-map.json")
    source_visuals = source_visual_map.get("visuals")
    if (
        source_visual_map.get("version")
        != "official-account-news-editorial-visual-map-v5-five-scene"
        or not isinstance(source_visuals, list)
        or len(source_visuals) != 5
    ):
        raise ValueError("v5 source visual map is invalid")
    for ordinal, (row, body) in enumerate(zip(source_visuals, body_images, strict=True)):
        if not isinstance(row, dict) or row.get("ordinal") != ordinal:
            raise ValueError("v5 source visual ordinal changed")
        output = row.get("output")
        declared_checksum = (
            output.get("sha256") if isinstance(output, dict) else row.get("output_sha256")
        )
        if declared_checksum != sha256(body).hexdigest():
            raise ValueError("v5 source visual checksum changed")
    semantic_selection = declared_json("semantic-selection.json")
    assignments = semantic_selection.get("assignments")
    if (
        semantic_selection.get("status") != "semantic_ready"
        or semantic_selection.get("query_call_count") != 2
        or not isinstance(assignments, list)
        or [row.get("ordinal") for row in assignments if isinstance(row, dict)] != [3, 4]
    ):
        raise ValueError("v5 semantic selection boundary changed")
    evidence = declared_json("evidence.json")
    reference_learning = declared_json("reference-learning.json")
    if evidence.get("version") != "official-account-news-editorial-evidence-v5":
        raise ValueError("v5 evidence projection changed")
    if (
        reference_learning.get("version")
        != "wechat-public-reference-patterns-v4-semantic-five-scene"
    ):
        raise ValueError("v5 reference-learning projection changed")
    return ValidatedV5Bundle(
        source_dir=source_dir,
        source_manifest_sha256=sha256(manifest_body).hexdigest(),
        article_body_html=article_html,
        article_markdown=declared["article.md"].decode("utf-8"),
        article_package=article_package,
        evidence=evidence,
        reference_learning=reference_learning,
        semantic_selection=semantic_selection,
        source_run=run,
        source_visual_map=source_visual_map,
        body_images=(
            body_images[0],
            body_images[1],
            body_images[2],
            body_images[3],
            body_images[4],
        ),
    )


def _validate_image_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        url not in ALLOWED_IMAGE_URLS
        or parsed.scheme != "https"
        or parsed.hostname != "www.moe.gov.cn"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("official photo URL is not allowlisted")


def _validate_source_page_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        url not in ALLOWED_SOURCE_PAGE_URLS
        or parsed.scheme != "https"
        or parsed.hostname != "www.moe.gov.cn"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("official photo source page is not allowlisted")


def _validate_news_context_photo_set() -> None:
    if (
        len(NEWS_CONTEXT_PHOTOS) != 2
        or len(ALLOWED_IMAGE_URLS) != 2
        or len(ALLOWED_SOURCE_PAGE_URLS) != 2
        or len({photo.public_ref for photo in NEWS_CONTEXT_PHOTOS}) != 2
        or {photo.asset_name for photo in NEWS_CONTEXT_PHOTOS} != {"news-00.jpg", "news-01.jpg"}
        or {photo.image_url for photo in NEWS_CONTEXT_PHOTOS} != set(ALLOWED_IMAGE_URLS)
        or {photo.source_page_url for photo in NEWS_CONTEXT_PHOTOS} != set(ALLOWED_SOURCE_PAGE_URLS)
        or any(photo.rights_status != RIGHTS_STATUS for photo in NEWS_CONTEXT_PHOTOS)
    ):
        raise ValueError("official photo set identity changed")
    for photo in NEWS_CONTEXT_PHOTOS:
        _validate_image_url(photo.image_url)
        _validate_source_page_url(photo.source_page_url)


async def fetch_news_context_photos(
    fetcher: OfficialPhotoFetcher,
) -> tuple[ValidatedNewsPhoto, ValidatedNewsPhoto]:
    _validate_news_context_photo_set()
    validated: list[ValidatedNewsPhoto] = []
    for spec in NEWS_CONTEXT_PHOTOS:
        response = await fetcher.fetch(spec.image_url, max_bytes=MAX_PHOTO_BYTES)
        if (
            response.status_code != 200
            or response.media_type.lower() != spec.media_type
            or response.final_url != spec.image_url
            or len(response.body) > MAX_PHOTO_BYTES
        ):
            raise ValueError("official photo response contract changed")
        _validate_jpeg(
            response.body,
            expected_size=(spec.width, spec.height),
            expected_sha256=spec.sha256,
        )
        validated.append(ValidatedNewsPhoto(spec=spec, body=response.body))
    if len(validated) != 2 or validated[0].body == validated[1].body:
        raise ValueError("official photo set is incomplete or duplicated")
    return validated[0], validated[1]


def _photo_html(photo: NewsContextPhoto) -> str:
    source_url = escape(photo.source_page_url, quote=True)
    _validate_source_page_url(photo.source_page_url)
    return (
        '<section data-module="news-context-photo" '
        f'data-photo-ref="{escape(photo.public_ref, quote=True)}" '
        'style="margin:31px 19px 7px;padding:10px;background:#fffdf7;'
        'border:1px solid #071b33;box-shadow:7px 7px 0 #f5d34e;">'
        '<p style="margin:1px 3px 10px;color:#f2663a;font-size:10px;line-height:1.5;'
        'font-weight:900;letter-spacing:1.7px;">关联新闻现场 · OFFICIAL SOURCE</p>'
        f'<img src="assets/{escape(photo.asset_name, quote=True)}" '
        f'alt="{escape(photo.alt_text, quote=True)}" '
        'style="display:block;width:100%;height:auto;border:0;background:#eef3f7;">'
        f'<p style="margin:11px 3px 4px;color:#071b33;font-size:13px;line-height:1.7;'
        f'font-weight:800;">{escape(photo.relation_label)}</p>'
        f'<p style="margin:0 3px 4px;color:#536176;font-size:11px;line-height:1.7;">'
        f"{escape(photo.caption)} {escape(photo.credit)}</p>"
        f'<p style="margin:0 3px 4px;color:#776a5f;font-size:10px;line-height:1.65;">'
        f'<a rel="noopener noreferrer" referrerpolicy="no-referrer" href="{source_url}" '
        'style="color:#1e5bff;text-decoration:underline;">查看教育部官方来源</a>'
        "　·　关联背景图，不替代正文事实证据。</p>"
        f'<p style="margin:7px 3px 2px;padding-top:7px;border-top:1px solid #e1d8ca;'
        f'color:#9b4b2f;font-size:10px;line-height:1.65;">{escape(RIGHTS_WARNING)}</p>'
        "</section>"
    )


def render_news_context_html(bundle: ValidatedV5Bundle) -> str:
    html = bundle.article_body_html
    for photo in NEWS_CONTEXT_PHOTOS:
        anchor = photo.placement_anchor
        if html.count(anchor) != 1:
            raise ValueError("news-context placement anchor changed")
        html = html.replace(anchor, f"{_photo_html(photo)}{anchor}", 1)
    warning_anchor = "</section>"
    warning = (
        '<section data-module="news-photo-rights-warning" style="margin:0;padding:14px 19px;'
        "background:#fff2dc;color:#7a3d29;font-size:11px;line-height:1.7;"
        'border-top:1px solid #e6c8a2;">'
        f"本地审阅提示：{escape(RIGHTS_WARNING)} 当前不可发布。</section>"
    )
    if html.count(warning_anchor) < 1:
        raise ValueError("news-context HTML root changed")
    html = html.rsplit(warning_anchor, 1)[0] + warning + warning_anchor
    if (
        html.count('data-module="news-context-photo"') != 2
        or html.count('data-module="news-photo-rights-warning"') != 1
        or html.count("<h1 ") != 1
        or any(html.count(f"assets/{photo.asset_name}") != 1 for photo in NEWS_CONTEXT_PHOTOS)
    ):
        raise ValueError("news-context HTML projection is invalid")
    return html


def _write_json(path: Path, payload: object) -> None:
    polished_v3._write_json(path, payload)


def _write_bytes(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _photo_projection(photo: ValidatedNewsPhoto, *, ordinal: int) -> dict[str, object]:
    spec = photo.spec
    return {
        "ordinal": ordinal,
        "public_ref": spec.public_ref,
        "provenance_kind": "official_source_context_photo",
        "relation_label": spec.relation_label,
        "source_page_url": spec.source_page_url,
        "image_url": spec.image_url,
        "local_path": f"assets/{spec.asset_name}",
        "alt_text": spec.alt_text,
        "caption": spec.caption,
        "credit": spec.credit,
        "media_type": spec.media_type,
        "width": spec.width,
        "height": spec.height,
        "byte_size": len(photo.body),
        "sha256": sha256(photo.body).hexdigest(),
        "source_bytes_preserved": True,
        "watermark_preserved": True,
        "claim_role": "context_only_not_evidence",
        "rights_status": spec.rights_status,
        "rights_warning": RIGHTS_WARNING,
    }


async def export_news_context_bundle(
    source_dir: Path,
    output_dir: Path,
    *,
    fetcher: OfficialPhotoFetcher,
    acquisition: PhotoAcquisitionLedger = NETWORK_ACQUISITION,
) -> Path:
    """Create one fresh local-only v6 bundle after exactly two validated fetches."""

    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("refusing to replace an existing v6 output directory")
    acquisition.validate()
    bundle = load_v5_bundle(source_dir)
    photos = await fetch_news_context_photos(fetcher)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    installed = False
    try:
        (temporary / "assets").mkdir()
        for name, body in zip(BODY_IMAGE_NAMES, bundle.body_images, strict=True):
            _write_bytes(temporary / "assets" / name, body)
        for photo in photos:
            _write_bytes(temporary / "assets" / photo.spec.asset_name, photo.body)

        article_html = render_news_context_html(bundle)
        (temporary / "article-body.html").write_text(article_html, encoding="utf-8")
        (temporary / "preview.html").write_text(
            polished_v3._preview_document(article_html), encoding="utf-8"
        )
        markdown = bundle.article_markdown.rstrip() + (
            "\n\n## 关联新闻现场图\n\n"
            "以下图片仅作关联新闻背景，不替代正文事实证据。\n\n"
            f"![{NEWS_CONTEXT_PHOTOS[0].alt_text}](assets/news-00.jpg)\n\n"
            f"{NEWS_CONTEXT_PHOTOS[0].caption} {NEWS_CONTEXT_PHOTOS[0].credit}  "
            f"[教育部官方来源]({NEWS_CONTEXT_PHOTOS[0].source_page_url})\n\n"
            f"![{NEWS_CONTEXT_PHOTOS[1].alt_text}](assets/news-01.jpg)\n\n"
            f"{NEWS_CONTEXT_PHOTOS[1].caption} {NEWS_CONTEXT_PHOTOS[1].credit}  "
            f"[教育部官方来源]({NEWS_CONTEXT_PHOTOS[1].source_page_url})\n\n"
            f"> 本地审阅提示：{RIGHTS_WARNING} 当前不可发布。\n"
        )
        (temporary / "article.md").write_text(markdown, encoding="utf-8")
        for filename, document in (
            ("article-package.json", bundle.article_package),
            ("evidence.json", bundle.evidence),
            ("reference-learning.json", bundle.reference_learning),
            ("semantic-selection.json", bundle.semantic_selection),
        ):
            _write_json(temporary / filename, document)

        news_rows = [
            {
                **_photo_projection(photo, ordinal=5 + index),
                "acquisition_mode": acquisition.mode,
            }
            for index, photo in enumerate(photos)
        ]
        source_visuals = bundle.source_visual_map.get("visuals")
        if not isinstance(source_visuals, list) or len(source_visuals) != 5:
            raise ValueError("v5 source visual map is invalid")
        _write_json(
            temporary / "visual-map.json",
            {
                "version": VISUAL_MAP_VERSION,
                "quality_status": "local_review_required",
                "rights_warning": RIGHTS_WARNING,
                "visual_count": 7,
                "company_ip_visual_count": 5,
                "official_context_photo_count": 2,
                "visuals": [*source_visuals, *news_rows],
            },
        )
        _write_json(
            temporary / "news-photo-provenance.json",
            {
                "version": NEWS_PHOTO_PROVENANCE_VERSION,
                "purpose": "context_only_not_evidence",
                "rights_status": RIGHTS_STATUS,
                "rights_warning": RIGHTS_WARNING,
                "source_pixels_preserved": True,
                "photos": news_rows,
            },
        )
        source_run_id = str(bundle.source_run.get("run_id", ""))
        run_id = sha256(
            f"{REPORT_VERSION}:{source_run_id}:{bundle.source_manifest_sha256}:"
            f"{':'.join(photo.spec.sha256 for photo in photos)}".encode()
        ).hexdigest()
        render_fingerprint = sha256(
            f"{RENDERER_VERSION}:{STYLE_VERSION}:{TEMPLATE_VERSION}:".encode()
            + article_html.encode()
        ).hexdigest()
        run = {
            "version": REPORT_VERSION,
            "run_id": run_id,
            "source_run_id": source_run_id,
            "source_version": SOURCE_VERSION,
            "source_manifest_sha256": bundle.source_manifest_sha256,
            "status": "ready",
            "simulation": True,
            "local_only": True,
            "local_review_only": True,
            "manual_review_status": "pending",
            "rights_status": RIGHTS_STATUS,
            "rights_warning": RIGHTS_WARNING,
            "copy_ready": False,
            "published": False,
            "body_image_count": 7,
            "company_ip_visual_count": 5,
            "official_context_photo_count": 2,
            "render_fingerprint": render_fingerprint,
            "official_photo_acquisition_mode": acquisition.mode,
            "official_photo_get_calls": acquisition.successful_get_calls,
            "official_photo_cache_reads": acquisition.cache_reads,
            "failed_official_photo_get_attempts_before_export": (
                acquisition.failed_get_attempts_before_export
            ),
            "source_page_get_calls": 0,
            "article_provider_calls": 0,
            "embedding_provider_calls": 0,
            "image_provider_calls": 0,
            "toapis_calls": 0,
            "comfly_calls": 0,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
            "inherited_v5_embedding_calls": 2,
            "inherited_v5_image_provider_calls": 2,
            "inherited_pre_v5_image_provider_calls": 3,
            "automatic_retry_permitted": False,
        }
        _write_json(temporary / "run.json", run)
        (temporary / "README.md").write_text(
            "# 教育部新闻 × 小赛 IP｜官方新闻现场图 v6\n\n"
            "在 v5 五张小赛／赛先生 3:2 场景图之外，增加两张与正文相邻的教育部官方新闻现场图。"
            "五张 IP 图逐字节继承；两张新闻图保留官方原始像素、水印、图注和摄影署名。\n\n"
            "两张新闻图仅作关联新闻背景，不替代正文事实证据。\n\n"
            "- 本地状态：local-review-only / pending / unpublished\n"
            f"- 本轮图片获取：{acquisition.mode}；成功 GET "
            f"{acquisition.successful_get_calls} 次，本地缓存读取 {acquisition.cache_reads} 次\n"
            f"- 导出前已知失败 GET：{acquisition.failed_get_attempts_before_export} 次；无重试\n"
            "- 本轮模型与社交：LLM、Embedding、生图、微信、企微、发布调用均为 0\n"
            f"- 授权边界：{RIGHTS_WARNING}\n\n"
            "打开 `preview.html` 查看 320--430 px 本地预览。\n",
            encoding="utf-8",
        )
        manifest_files = tuple(
            sorted(
                (path for path in temporary.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(temporary).as_posix(),
            )
        )
        _write_json(
            temporary / "manifest.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "local_review_only": True,
                "manual_review_status": "pending",
                "rights_status": RIGHTS_STATUS,
                "rights_warning": RIGHTS_WARNING,
                "copy_ready": False,
                "published": False,
                "visual_count": 7,
                "official_photo_acquisition_mode": acquisition.mode,
                "official_photo_get_calls": acquisition.successful_get_calls,
                "official_photo_cache_reads": acquisition.cache_reads,
                "failed_official_photo_get_attempts_before_export": (
                    acquisition.failed_get_attempts_before_export
                ),
                "article_provider_calls": 0,
                "embedding_provider_calls": 0,
                "image_provider_calls": 0,
                "wechat_calls": 0,
                "wecom_calls": 0,
                "publish_calls": 0,
                "files": [
                    {
                        "path": path.relative_to(temporary).as_posix(),
                        "byte_size": path.stat().st_size,
                        "sha256": sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in manifest_files
                ],
            },
        )
        polished_v3._zip_bundle(temporary, archive_root_name=output_dir.name)
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError("refusing to replace an existing v6 output directory")
        temporary.rename(output_dir)
        installed = True
        return output_dir
    finally:
        if not installed and temporary.exists():
            shutil.rmtree(temporary)


async def run_official_news_context_bundle(*, source_dir: Path, output_dir: Path) -> Path:
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        return await export_news_context_bundle(
            source_dir,
            output_dir,
            fetcher=HttpxOfficialPhotoFetcher(client),
        )


async def run_cached_news_context_bundle(
    *,
    source_dir: Path,
    output_dir: Path,
    news_00_path: Path,
    news_01_path: Path,
    failed_get_attempts_before_export: int = 0,
) -> Path:
    paths = {
        NEWS_CONTEXT_PHOTOS[0].image_url: news_00_path,
        NEWS_CONTEXT_PHOTOS[1].image_url: news_01_path,
    }
    return await export_news_context_bundle(
        source_dir,
        output_dir,
        fetcher=LocalCachedOfficialPhotoFetcher(paths),
        acquisition=PhotoAcquisitionLedger(
            mode="validated_local_cache",
            successful_get_calls=0,
            cache_reads=2,
            failed_get_attempts_before_export=failed_get_attempts_before_export,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cached-news-00", type=Path)
    parser.add_argument("--cached-news-01", type=Path)
    parser.add_argument("--failed-get-attempts-before-export", type=int, default=0)
    args = parser.parse_args()
    cached_paths = (args.cached_news_00, args.cached_news_01)
    if any(path is not None for path in cached_paths):
        if not all(path is not None for path in cached_paths):
            parser.error("both cached news-photo paths are required")
        assert args.cached_news_00 is not None
        assert args.cached_news_01 is not None
        result = asyncio.run(
            run_cached_news_context_bundle(
                source_dir=args.source_dir,
                output_dir=args.output_dir,
                news_00_path=args.cached_news_00,
                news_01_path=args.cached_news_01,
                failed_get_attempts_before_export=args.failed_get_attempts_before_export,
            )
        )
    else:
        if args.failed_get_attempts_before_export:
            parser.error("failed GET count is valid only for cached export")
        result = asyncio.run(
            run_official_news_context_bundle(
                source_dir=args.source_dir,
                output_dir=args.output_dir,
            )
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
