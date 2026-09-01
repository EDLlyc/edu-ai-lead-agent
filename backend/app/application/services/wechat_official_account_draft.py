"""Fail-closed local preparation and orchestration for independent MP drafts."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from math import gcd
from pathlib import Path, PurePosixPath
from typing import Final, cast
from urllib.parse import urlsplit
from zipfile import BadZipFile

from PIL import Image, UnidentifiedImageError

from app.application.ports.wechat_official_account import (
    WECHAT_MP_MAX_CONTENT_SOURCE_URL_BYTES,
    WECHAT_MP_MAX_DRAFT_AUTHOR_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_CONTENT_BYTES,
    WECHAT_MP_MAX_DRAFT_CONTENT_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_DIGEST_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_TITLE_CHARACTERS,
    WECHAT_MP_MAX_IMAGE_BYTES,
    WECHAT_MP_MAX_INLINE_IMAGE_BYTES,
    WECHAT_MP_MAX_THUMB_BYTES,
    WECHAT_MP_MIN_IMAGE_BYTES,
    WeChatDraftArticleRequest,
    WeChatDraftReceipt,
    WeChatDraftRole,
    WeChatMpDraftPreparationError,
    WeChatOfficialAccountDraftClient,
)
from app.application.services.official_account_weekly_edition import load_finalized_v2_child
from app.domain.official_account_weekly_edition import WEEKLY_EDITION_ROLE_ORDER, WeeklyArticleRole

_SHA256_LENGTH: Final = 64
_ALLOWED_TAG_ATTRIBUTES: Final[dict[str, frozenset[str]]] = {
    "section": frozenset({"style"}),
    "p": frozenset({"style"}),
    "span": frozenset({"style", "leaf"}),
    "a": frozenset({"href", "rel", "referrerpolicy", "style"}),
    "img": frozenset({"src", "alt", "style"}),
    "br": frozenset(),
}
_VOID_TAGS: Final = frozenset({"img", "br"})


@dataclass(frozen=True, slots=True)
class WeChatDraftLocalSource:
    """One finalized V2 directory and its draft-only presentation choices."""

    directory: Path
    role: WeChatDraftRole
    content_source_url: str | None = None
    need_open_comment: bool = False
    only_fans_can_comment: bool = False


@dataclass(frozen=True, slots=True)
class WeChatPreparedMedia:
    path: str
    media_type: str
    body: bytes = field(repr=False)
    upload_filename: str


@dataclass(frozen=True, slots=True)
class WeChatPreparedDraft:
    role: WeChatDraftRole
    article_fingerprint: str
    content_fingerprint: str
    title: str
    author: str
    digest: str
    content_source_url: str | None
    body_html: str = field(repr=False)
    body_media: tuple[WeChatPreparedMedia, ...] = field(repr=False)
    cover: WeChatPreparedMedia = field(repr=False)
    need_open_comment: bool
    only_fans_can_comment: bool


class WeChatOfficialAccountDraftPreparer:
    """Pure finalized-child preflight with no provider client or network capability."""

    def __init__(self, *, max_image_bytes: int = WECHAT_MP_MAX_IMAGE_BYTES) -> None:
        self._max_image_bytes = _validated_max_image_bytes(max_image_bytes)

    def prepare(self, source: WeChatDraftLocalSource) -> WeChatPreparedDraft:
        return _prepare_draft_source(source, max_image_bytes=self._max_image_bytes)

    def prepare_weekly(
        self,
        sources: tuple[
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
        ],
    ) -> tuple[WeChatPreparedDraft, WeChatPreparedDraft, WeChatPreparedDraft]:
        if tuple(item.role for item in sources) != tuple(WEEKLY_EDITION_ROLE_ORDER):
            raise WeChatMpDraftPreparationError()
        prepared = cast(
            tuple[WeChatPreparedDraft, WeChatPreparedDraft, WeChatPreparedDraft],
            tuple(self.prepare(source) for source in sources),
        )
        if (
            len({item.article_fingerprint for item in prepared}) != 3
            or len({item.content_fingerprint for item in prepared}) != 3
        ):
            raise WeChatMpDraftPreparationError()
        return prepared


class WeChatOfficialAccountDraftOnlyService:
    """Prepare all local bytes before the first network write, then create drafts."""

    def __init__(
        self,
        *,
        client: WeChatOfficialAccountDraftClient,
        max_image_bytes: int = WECHAT_MP_MAX_IMAGE_BYTES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._preparer = WeChatOfficialAccountDraftPreparer(
            max_image_bytes=max_image_bytes,
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create_draft(self, source: WeChatDraftLocalSource) -> WeChatDraftReceipt:
        prepared = self.prepare(source)
        created_at = self._validated_created_at()
        return await self._create_prepared(prepared, created_at=created_at)

    async def create_weekly_drafts(
        self,
        sources: tuple[
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
        ],
    ) -> tuple[WeChatDraftReceipt, WeChatDraftReceipt, WeChatDraftReceipt]:
        prepared = self._preparer.prepare_weekly(sources)
        created_at = tuple(self._validated_created_at() for _item in prepared)
        receipts = [
            await self._create_prepared(item, created_at=item_created_at)
            for item, item_created_at in zip(prepared, created_at, strict=True)
        ]
        return cast(
            tuple[WeChatDraftReceipt, WeChatDraftReceipt, WeChatDraftReceipt],
            tuple(receipts),
        )

    def prepare(self, source: WeChatDraftLocalSource) -> WeChatPreparedDraft:
        """Resolve and validate a complete finalized child without a provider call."""

        return self._preparer.prepare(source)

    async def create_prepared(self, prepared: WeChatPreparedDraft) -> WeChatDraftReceipt:
        """Execute one previously preflighted draft after the durable side-effect fence."""

        return await self._create_prepared(
            prepared,
            created_at=self._validated_created_at(),
        )

    def _validated_created_at(self) -> datetime:
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise WeChatMpDraftPreparationError()
        return created_at

    async def _create_prepared(
        self,
        prepared: WeChatPreparedDraft,
        *,
        created_at: datetime,
    ) -> WeChatDraftReceipt:
        rewritten = prepared.body_html
        for media in prepared.body_media:
            uploaded = await self._client.upload_inline_image(
                media.body,
                media.media_type,
                media.upload_filename,
            )
            needle = f'src="{media.path}"'
            if rewritten.count(needle) != 1:
                raise WeChatMpDraftPreparationError()
            rewritten = rewritten.replace(
                needle,
                f'src="{escape(uploaded.url, quote=True)}"',
                1,
            )
        if any(f'src="{item.path}"' in rewritten for item in prepared.body_media):
            raise WeChatMpDraftPreparationError()
        thumb = await self._client.upload_thumb(
            prepared.cover.body,
            prepared.cover.media_type,
            prepared.cover.upload_filename,
        )
        created = await self._client.add_draft(
            WeChatDraftArticleRequest(
                title=prepared.title,
                author=prepared.author,
                digest=prepared.digest,
                content=rewritten,
                content_source_url=prepared.content_source_url,
                thumb_media_id=thumb.media_id,
                need_open_comment=prepared.need_open_comment,
                only_fans_can_comment=prepared.only_fans_can_comment,
            )
        )
        return WeChatDraftReceipt(
            role=prepared.role,
            article_fingerprint=prepared.article_fingerprint,
            content_fingerprint=prepared.content_fingerprint,
            draft_media_id=created.media_id,
            uploaded_image_count=len(prepared.body_media),
            created_at=created_at,
        )


def _validated_max_image_bytes(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < WECHAT_MP_MIN_IMAGE_BYTES
        or value > WECHAT_MP_MAX_IMAGE_BYTES
    ):
        raise ValueError("WeChat Official Account draft image byte limit is invalid")
    return value


def _prepare_draft_source(
    source: WeChatDraftLocalSource,
    *,
    max_image_bytes: int,
) -> WeChatPreparedDraft:
    try:
        role = WeeklyArticleRole(source.role)
        child = load_finalized_v2_child(source.directory, role=role)
        article = _json_object(child.files["article.json"])
        manifest = _json_object(child.files["manifest.json"])
        title = _bounded_text(
            article.get("title"),
            minimum=1,
            maximum=WECHAT_MP_MAX_DRAFT_TITLE_CHARACTERS,
        )
        author = _bounded_text(
            article.get("author"),
            minimum=1,
            maximum=WECHAT_MP_MAX_DRAFT_AUTHOR_CHARACTERS,
        )
        digest = _bounded_text(
            article.get("digest"),
            minimum=1,
            maximum=WECHAT_MP_MAX_DRAFT_DIGEST_CHARACTERS,
        )
        body_bytes = child.files["article-body.html"]
        if sha256(body_bytes).hexdigest() != child.body_sha256:
            raise ValueError("body identity changed")
        body_html = body_bytes.decode("utf-8")
        _validate_draft_html_size(body_html)
        parser = _DraftHtmlValidator()
        parser.feed(body_html)
        parser.close()
        image_paths = parser.finish()
        body_media, cover = _prepare_media(
            manifest=manifest,
            files=child.files,
            image_paths=image_paths,
            max_image_bytes=max_image_bytes,
        )
        content_source_url = _optional_https_url(source.content_source_url)
        if source.only_fans_can_comment and not source.need_open_comment:
            raise ValueError("invalid comment policy")
        if not isinstance(source.need_open_comment, bool) or not isinstance(
            source.only_fans_can_comment,
            bool,
        ):
            raise TypeError("invalid comment policy")
    except (
        BadZipFile,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ):
        raise WeChatMpDraftPreparationError() from None
    return WeChatPreparedDraft(
        role=source.role,
        article_fingerprint=child.article_fingerprint,
        content_fingerprint=child.content_fingerprint,
        title=title,
        author=author,
        digest=digest,
        content_source_url=content_source_url,
        body_html=body_html,
        body_media=body_media,
        cover=cover,
        need_open_comment=source.need_open_comment,
        only_fans_can_comment=source.only_fans_can_comment,
    )


def _prepare_media(
    *,
    manifest: dict[str, object],
    files: Mapping[str, bytes],
    image_paths: tuple[str, ...],
    max_image_bytes: int,
) -> tuple[tuple[WeChatPreparedMedia, ...], WeChatPreparedMedia]:
    raw_media = manifest.get("media")
    if not isinstance(raw_media, list) or not raw_media:
        raise ValueError("media projection is missing")
    media_by_path: dict[str, WeChatPreparedMedia] = {}
    covers: list[WeChatPreparedMedia] = []
    for raw in raw_media:
        if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
            raise ValueError("media projection is invalid")
        path = _safe_media_path(raw.get("path"))
        if path in media_by_path:
            raise ValueError("media path is duplicated")
        role = raw.get("role")
        if role not in {"body", "context", "cover"}:
            raise ValueError("media role is invalid")
        media_type = raw.get("media_type")
        if media_type not in {"image/jpeg", "image/png"}:
            raise ValueError("media type is unsupported")
        body = files.get(path)
        if not isinstance(body, bytes):
            raise ValueError("media bytes are missing")
        declared_size = raw.get("byte_size")
        declared_sha = raw.get("sha256")
        if (
            isinstance(declared_size, bool)
            or not isinstance(declared_size, int)
            or declared_size != len(body)
            or not isinstance(declared_sha, str)
            or len(declared_sha) != _SHA256_LENGTH
            or sha256(body).hexdigest() != declared_sha
        ):
            raise ValueError("media identity changed")
        width, height = _validate_image_bytes(
            body,
            media_type=media_type,
            max_bytes=max_image_bytes,
        )
        if raw.get("width") != width or raw.get("height") != height:
            raise ValueError("media dimensions changed")
        prepared = WeChatPreparedMedia(
            path=path,
            media_type=media_type,
            body=body,
            upload_filename=_safe_upload_filename(
                PurePosixPath(path).name,
                media_type=media_type,
            ),
        )
        if role == "cover":
            normalized_thumb = _normalize_cover_thumb(body)
            _validate_image_bytes(
                normalized_thumb,
                media_type="image/jpeg",
                max_bytes=WECHAT_MP_MAX_THUMB_BYTES,
            )
            prepared = WeChatPreparedMedia(
                path=path,
                media_type="image/jpeg",
                body=normalized_thumb,
                upload_filename="cover-thumb.jpg",
            )
        elif len(body) > WECHAT_MP_MAX_INLINE_IMAGE_BYTES:
            normalized_inline = _normalize_inline_image(body)
            _validate_image_bytes(
                normalized_inline,
                media_type="image/jpeg",
                max_bytes=WECHAT_MP_MAX_INLINE_IMAGE_BYTES,
            )
            prepared = WeChatPreparedMedia(
                path=path,
                media_type="image/jpeg",
                body=normalized_inline,
                upload_filename=_safe_upload_filename(
                    f"{PurePosixPath(path).stem}.jpg",
                    media_type="image/jpeg",
                ),
            )
        media_by_path[path] = prepared
        if role == "cover":
            covers.append(prepared)
    if len(covers) != 1 or covers[0].path in image_paths:
        raise ValueError("one independent non-body cover is required")
    non_cover_paths = set(media_by_path) - {covers[0].path}
    if len(image_paths) != len(set(image_paths)) or set(image_paths) != non_cover_paths:
        raise ValueError("HTML and media references disagree")
    return tuple(media_by_path[path] for path in image_paths), covers[0]


class _DraftHtmlValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._image_paths: list[str] = []
        self._failed = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        allowed = _ALLOWED_TAG_ATTRIBUTES.get(normalized)
        if allowed is None:
            self._failed = True
            return
        names = [name.casefold() for name, _value in attrs]
        if len(names) != len(set(names)) or any(name not in allowed for name in names):
            self._failed = True
            return
        values = {name.casefold(): value for name, value in attrs}
        if any(value is None or len(value) > 4096 for value in values.values()):
            self._failed = True
            return
        style = values.get("style")
        if style is not None and any(
            marker in style.casefold() for marker in ("url(", "expression", "@import")
        ):
            self._failed = True
            return
        if normalized == "span" and "leaf" in values and values["leaf"] != "":
            self._failed = True
            return
        if normalized == "a":
            href = values.get("href")
            if href is None or not _is_safe_https_url(href):
                self._failed = True
                return
            if values.get("rel") not in {None, "noopener noreferrer"} or values.get(
                "referrerpolicy"
            ) not in {None, "no-referrer"}:
                self._failed = True
                return
        if normalized == "img":
            src = values.get("src")
            alt = values.get("alt")
            if src is None or alt is None or not alt.strip():
                self._failed = True
                return
            try:
                safe_src = _safe_media_path(src)
            except (TypeError, ValueError):
                self._failed = True
                return
            raw_tag = self.get_starttag_text() or ""
            if raw_tag.count(f'src="{safe_src}"') != 1:
                self._failed = True
                return
            self._image_paths.append(safe_src)
        if normalized not in _VOID_TAGS:
            self._stack.append(normalized)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in _VOID_TAGS or not self._stack or self._stack.pop() != normalized:
            self._failed = True

    def handle_comment(self, data: str) -> None:
        self._failed = True

    def handle_decl(self, decl: str) -> None:
        self._failed = True

    def handle_pi(self, data: str) -> None:
        self._failed = True

    def unknown_decl(self, data: str) -> None:
        self._failed = True

    def finish(self) -> tuple[str, ...]:
        if self._failed or self._stack or not self._image_paths:
            raise ValueError("article HTML is outside the allowlist")
        return tuple(self._image_paths)


def _json_object(body: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[object, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if not isinstance(key, str) or key in result:
                raise ValueError("invalid JSON object")
            result[key] = value
        return result

    raw = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(raw, dict):
        raise ValueError("JSON document must be an object")
    return cast(dict[str, object], raw)


def _bounded_text(value: object, *, minimum: int, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not (minimum <= len(value.strip()) <= maximum)
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("article text is outside the draft contract")
    return value.strip()


def _validate_draft_html_size(value: str) -> None:
    if (
        not value.strip()
        or len(value) > WECHAT_MP_MAX_DRAFT_CONTENT_CHARACTERS
        or len(value.encode("utf-8")) > WECHAT_MP_MAX_DRAFT_CONTENT_BYTES
    ):
        raise ValueError("article HTML is outside the draft size contract")


def _safe_media_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("media path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) != 2
        or path.parts[0] != "assets"
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() not in {".jpg", ".jpeg", ".png"}
    ):
        raise ValueError("media path is invalid")
    return path.as_posix()


def _safe_upload_filename(value: str, *, media_type: str) -> str:
    if not value or len(value) > 128 or any(character in value for character in "/\\\x00\r\n"):
        raise ValueError("upload filename is invalid")
    suffix = value.rsplit(".", 1)[-1].casefold() if "." in value else ""
    expected_suffixes = {
        "image/jpeg": frozenset({"jpg", "jpeg"}),
        "image/png": frozenset({"png"}),
    }
    if suffix not in expected_suffixes[media_type]:
        raise ValueError("upload filename does not match its media type")
    return value


def _validate_image_bytes(body: bytes, *, media_type: str, max_bytes: int) -> tuple[int, int]:
    if len(body) < WECHAT_MP_MIN_IMAGE_BYTES or len(body) > max_bytes:
        raise ValueError("image bytes are outside the draft limit")
    signatures = {
        "image/jpeg": b"\xff\xd8\xff",
        "image/png": b"\x89PNG\r\n\x1a\n",
    }
    expected_format = {"image/jpeg": "JPEG", "image/png": "PNG"}[media_type]
    if not body.startswith(signatures[media_type]):
        raise ValueError("image signature changed")
    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            if opened.format != expected_format:
                raise ValueError("image format changed")
            return opened.size
    except (OSError, UnidentifiedImageError):
        raise ValueError("image bytes are invalid") from None


def _normalize_cover_thumb(body: bytes) -> bytes:
    """Create a deterministic metadata-free 2.35:1 JPEG below the MP thumb limit."""

    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            source = opened.convert("RGB")
    except (OSError, UnidentifiedImageError):
        raise ValueError("cover image bytes are invalid") from None
    width, height = source.size
    if width * 20 >= height * 47:
        cropped_width = height * 47 // 20
        left = (width - cropped_width) // 2
        cropped = source.crop((left, 0, left + cropped_width, height))
    else:
        cropped_height = width * 20 // 47
        top = (height - cropped_height) // 2
        cropped = source.crop((0, top, width, top + cropped_height))
    max_multiplier = min(cropped.width // 47, cropped.height // 20, 25)
    if max_multiplier < 1:
        raise ValueError("cover is too small for the required aspect ratio")
    multipliers = tuple(
        dict.fromkeys(
            multiplier
            for multiplier in (max_multiplier, 25, 20, 16, 14, 12, 10, 8, 6, 4, 3, 2, 1)
            if multiplier <= max_multiplier
        )
    )
    for multiplier in multipliers:
        target = (47 * multiplier, 20 * multiplier)
        resized = cropped.resize(target, Image.Resampling.LANCZOS)
        for quality in (88, 82, 76, 70, 64, 58, 52, 46, 40):
            output = BytesIO()
            resized.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=False,
                subsampling=2,
            )
            payload = output.getvalue()
            if len(payload) <= WECHAT_MP_MAX_THUMB_BYTES:
                with Image.open(BytesIO(payload)) as checked:
                    checked.load()
                    if (
                        checked.format != "JPEG"
                        or checked.width * 20 != checked.height * 47
                        or checked.getexif()
                        or "comment" in checked.info
                    ):
                        raise ValueError("normalized cover identity is invalid")
                return payload
    raise ValueError("cover cannot be normalized below the WeChat thumb limit")


def _normalize_inline_image(body: bytes) -> bytes:
    """Compress one oversized bound body image without cropping its visual content."""

    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            source = opened.convert("RGB")
    except (OSError, UnidentifiedImageError):
        raise ValueError("inline image bytes are invalid") from None
    common = gcd(source.width, source.height)
    unit_width = source.width // common
    unit_height = source.height // common
    for scale_percent in (100, 90, 80, 70, 60, 50):
        multiplier = max(1, common * scale_percent // 100)
        target = (unit_width * multiplier, unit_height * multiplier)
        candidate = (
            source if target == source.size else source.resize(target, Image.Resampling.LANCZOS)
        )
        for quality in (90, 84, 78, 72, 66, 60, 54, 48, 42, 36):
            output = BytesIO()
            candidate.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=False,
                subsampling=2,
            )
            payload = output.getvalue()
            if len(payload) <= WECHAT_MP_MAX_INLINE_IMAGE_BYTES:
                with Image.open(BytesIO(payload)) as checked:
                    checked.load()
                    if (
                        checked.format != "JPEG"
                        or checked.width * source.height != checked.height * source.width
                        or checked.getexif()
                        or "comment" in checked.info
                    ):
                        raise ValueError("normalized inline image identity is invalid")
                return payload
    raise ValueError("inline image cannot be normalized below the WeChat byte limit")


def _optional_https_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if (
        not _is_safe_https_url(normalized)
        or len(normalized.encode("utf-8")) > WECHAT_MP_MAX_CONTENT_SOURCE_URL_BYTES
    ):
        raise ValueError("source URL is invalid")
    return normalized


def _is_safe_https_url(value: str) -> bool:
    if any(character.isspace() or ord(character) < 32 for character in value):
        return False
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        len(value) <= 2048
        and parsed.scheme.casefold() == "https"
        and parsed.hostname
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


__all__ = [
    "WeChatDraftLocalSource",
    "WeChatOfficialAccountDraftOnlyService",
    "WeChatOfficialAccountDraftPreparer",
    "WeChatPreparedDraft",
    "WeChatPreparedMedia",
]
