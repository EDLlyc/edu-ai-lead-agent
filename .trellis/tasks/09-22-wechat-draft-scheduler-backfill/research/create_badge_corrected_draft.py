"""Create one corrected unpublished draft from the fixed published article.

The target account, edition, historical source receipt, and five user-approved
badge images are fixed in code.  ``plan`` performs only official read calls.
``create --apply`` may make exactly five journaled ``uploadimg`` calls and at
most one journaled ``draft/add`` call.  The already-published article is never
updated or deleted.  Ambiguous writes are never replayed; an ambiguous add can
only be reconciled from the frozen baseline and a unique exact batchget match.

This task-local operator intentionally uses application APIs available in the
production backend at ``abfb89d`` and has no database path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import stat
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import replace_draft_badge_visuals as shared
from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualStore,
)
from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
from app.domain.wechat_official_account_draft_jobs import (
    wechat_draft_account_fingerprint,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
    _validate_draft_article,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)

OPERATION_VERSION = "sep21-xiaosai-badge-published-redraft-v1"
SHARED_MODULE_SHA256 = (
    "d6501b9bc803c66d981bf4419f624ef43e19b4a2d700434401ae29bccf882d84"
)
ACCOUNT = shared.ACCOUNT
BUSINESS_DATE = shared.BUSINESS_DATE
EDITION = shared.EDITION
REDRAFT_PREFIX = f"badge-redraft-{EDITION.hex}-v1"
MAX_INLINE_UPLOADS = 5
MAX_REMOTE_ITEMS = 1000
PAGE_SIZE = 20
_WECHAT_ROOT_STYLE_REMOVALS = frozenset(
    {
        "background",
        "color",
        "font-family",
        "letter-spacing",
        "line-height",
        "margin",
        "max-width",
        "overflow-x",
    }
)


class OperatorError(ValueError):
    """One bounded, secret-free operator failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require(condition: object, code: str) -> None:
    if not condition:
        raise OperatorError(code)


def _sha(payload: dict[str, Any]) -> str:
    return shared._sha(payload)


def _safe_provider_id(value: object, code: str) -> str:
    require(
        isinstance(value, str)
        and 1 <= len(value) <= 512
        and not any(character.isspace() or ord(character) < 32 for character in value),
        code,
    )
    return cast(str, value)


class Journal(Protocol):
    def read(self, name: str) -> dict[str, Any] | None: ...

    def write(self, name: str, payload: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class DraftItem:
    media_id: str
    article: dict[str, object]


@dataclass(frozen=True, slots=True)
class PublishedItem:
    article_id: str
    article: dict[str, object]


class RemoteRedraft(Protocol):
    async def published_items(self) -> tuple[PublishedItem, ...]: ...

    async def draft_items(self) -> tuple[DraftItem, ...]: ...

    async def original_draft_absent(self, media_id: str) -> bool: ...

    async def get_draft(self, media_id: str) -> dict[str, object]: ...

    async def upload(self, *, body: bytes, filename: str) -> str: ...

    async def add(self, *, article: WeChatDraftArticleRequest) -> str: ...


@dataclass(frozen=True, slots=True)
class FixedRedraft:
    original_draft_media_id: str
    original_request: dict[str, object]
    published_article_id: str
    published_article: dict[str, object]
    bodies: tuple[bytes, bytes, bytes, bytes, bytes]
    binding: dict[str, Any]


def _response_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        require(key not in value, "badge_redraft_response_duplicate_key")
        value[key] = item
    return value


def _invalid_constant(_value: str) -> None:
    raise OperatorError("badge_redraft_response_invalid_constant")


class OfficialRemote:
    """Narrow official client: three reads, inline upload, and draft add only."""

    _READ_PATHS = frozenset(
        {
            "/cgi-bin/freepublish/batchget",
            "/cgi-bin/draft/batchget",
            "/cgi-bin/draft/get",
        }
    )

    def __init__(self, client: WeChatOfficialAccountHttpClient) -> None:
        self.client = client

    async def _read(
        self,
        path: str,
        *,
        payload: dict[str, object],
        accepted_errors: frozenset[int] = frozenset(),
    ) -> dict[str, object]:
        require(path in self._READ_PATHS, "badge_redraft_endpoint_forbidden")
        try:
            token = (await self.client._get_access_token()).value
            async with asyncio.timeout(self.client._total_timeout_seconds):
                async with self.client._client.stream(
                    "POST",
                    self.client._base_url + path,
                    params={"access_token": token},
                    json=payload,
                    follow_redirects=False,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    timeout=self.client._timeout,
                ) as response:
                    require(
                        200 <= response.status_code < 300
                        and response.headers.get(
                            "content-encoding", "identity"
                        ).casefold()
                        in {"", "identity"},
                        "badge_redraft_read_failed",
                    )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        require(size <= 1_048_576, "badge_redraft_response_too_large")
                        chunks.append(chunk)
        except asyncio.CancelledError:
            raise
        except OperatorError:
            raise
        except Exception as error:
            raise OperatorError("badge_redraft_read_failed") from error
        try:
            decoded = json.loads(
                b"".join(chunks),
                object_pairs_hook=_response_object,
                parse_constant=_invalid_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OperatorError("badge_redraft_response_invalid") from error
        require(isinstance(decoded, dict), "badge_redraft_response_invalid")
        result = cast(dict[str, object], decoded)
        errcode = result.get("errcode")
        require(
            errcode is None
            or (type(errcode) is int and (errcode == 0 or errcode in accepted_errors)),
            "badge_redraft_read_failed",
        )
        return result

    async def _batch(self, path: str) -> tuple[dict[str, object], ...]:
        collected: list[dict[str, object]] = []
        offset = 0
        while True:
            result = await self._read(
                path,
                payload={"offset": offset, "count": PAGE_SIZE, "no_content": 0},
            )
            total = result.get("total_count")
            items = result.get("item", [])
            require(
                type(total) is int
                and 0 <= total <= MAX_REMOTE_ITEMS
                and isinstance(items, list)
                and len(items) <= PAGE_SIZE
                and all(isinstance(item, dict) for item in items),
                "badge_redraft_batch_invalid",
            )
            assert isinstance(total, int) and isinstance(items, list)
            collected.extend(cast(list[dict[str, object]], items))
            require(len(collected) <= MAX_REMOTE_ITEMS, "badge_redraft_batch_invalid")
            if len(collected) >= total:
                require(len(collected) == total, "badge_redraft_batch_invalid")
                return tuple(collected)
            require(items, "badge_redraft_batch_invalid")
            offset += len(items)

    @staticmethod
    def _one_article(value: dict[str, object], code: str) -> dict[str, object]:
        content = value.get("content")
        news = content.get("news_item") if isinstance(content, dict) else None
        require(
            isinstance(news, list) and len(news) == 1 and isinstance(news[0], dict),
            code,
        )
        assert isinstance(news, list) and isinstance(news[0], dict)
        return dict(cast(dict[str, object], news[0]))

    async def published_items(self) -> tuple[PublishedItem, ...]:
        values: list[PublishedItem] = []
        for item in await self._batch("/cgi-bin/freepublish/batchget"):
            article_id = _safe_provider_id(
                item.get("article_id"), "badge_redraft_published_record_invalid"
            )
            values.append(
                PublishedItem(
                    article_id=article_id,
                    article=self._one_article(
                        item, "badge_redraft_published_record_invalid"
                    ),
                )
            )
        require(
            len({item.article_id for item in values}) == len(values),
            "badge_redraft_published_record_invalid",
        )
        return tuple(values)

    async def draft_items(self) -> tuple[DraftItem, ...]:
        values: list[DraftItem] = []
        for item in await self._batch("/cgi-bin/draft/batchget"):
            media_id = shared._safe_media_id(item.get("media_id"))
            values.append(
                DraftItem(
                    media_id=media_id,
                    article=self._one_article(
                        item, "badge_redraft_draft_record_invalid"
                    ),
                )
            )
        require(
            len({item.media_id for item in values}) == len(values),
            "badge_redraft_draft_record_invalid",
        )
        return tuple(values)

    async def original_draft_absent(self, media_id: str) -> bool:
        result = await self._read(
            "/cgi-bin/draft/get",
            payload={"media_id": media_id},
            accepted_errors=frozenset({40007}),
        )
        if result.get("errcode") == 40007:
            return True
        news = result.get("news_item")
        require(
            isinstance(news, list) and len(news) == 1 and isinstance(news[0], dict),
            "badge_redraft_original_draft_state_invalid",
        )
        return False

    async def get_draft(self, media_id: str) -> dict[str, object]:
        result = await self._read("/cgi-bin/draft/get", payload={"media_id": media_id})
        news = result.get("news_item")
        require(
            isinstance(news, list) and len(news) == 1 and isinstance(news[0], dict),
            "badge_redraft_draft_record_invalid",
        )
        assert isinstance(news, list) and isinstance(news[0], dict)
        return dict(cast(dict[str, object], news[0]))

    async def upload(self, *, body: bytes, filename: str) -> str:
        result = await self.client.upload_inline_image(body, "image/jpeg", filename)
        return shared._strict_wechat_cdn_upload_url(result.url)

    async def add(self, *, article: WeChatDraftArticleRequest) -> str:
        result = await self.client.add_draft(article)
        return shared._safe_media_id(result.media_id)


def _article_fields(value: dict[str, object]) -> dict[str, object]:
    fields = shared._article_fields(value)
    require(
        type(fields["need_open_comment"]) is int
        and fields["need_open_comment"] in {0, 1}
        and type(fields["only_fans_can_comment"]) is int
        and fields["only_fans_can_comment"] in {0, 1},
        "badge_redraft_published_article_invalid",
    )
    return fields


def _draft_request(
    *, original: dict[str, object], rewritten_html: str
) -> WeChatDraftArticleRequest:
    fields = _article_fields(original)
    source_url = fields["content_source_url"]
    article = WeChatDraftArticleRequest(
        title=cast(str, fields["title"]),
        author=cast(str, fields["author"]),
        digest=cast(str, fields["digest"]),
        content=rewritten_html,
        content_source_url=cast(str, source_url) if source_url else None,
        thumb_media_id=shared._safe_media_id(fields["thumb_media_id"]),
        need_open_comment=bool(fields["need_open_comment"]),
        only_fans_can_comment=bool(fields["only_fans_can_comment"]),
    )
    try:
        _validate_draft_article(article)
    except (TypeError, UnicodeError, ValueError) as error:
        raise OperatorError("badge_redraft_published_article_invalid") from error
    return article


def _source_match(
    *, candidate: dict[str, object], original_request: dict[str, object]
) -> bool:
    try:
        fields = _article_fields(candidate)
        original_fields = shared._article_fields(original_request)
        if any(
            fields[key] != original_fields[key] for key in ("title", "author", "digest")
        ):
            return False
        deleted = candidate.get("is_deleted")
        if not (
            (type(deleted) is bool and deleted is False)
            or (type(deleted) is int and deleted == 0)
        ):
            return False
        current_html = cast(str, fields["content"])
        original_html = cast(str, original_fields["content"])
        current = shared.HtmlProjection(current_html)
        original = shared.HtmlProjection(original_html)
        if (
            len(current.images) != 7
            or len(set(current.images)) != 7
            or current.links != original.links
            or len(original.images) != 7
        ):
            return False
        if not shared._same_wechat_cdn_display_variant(
            original.images[0], current.images[0]
        ) or not shared._same_wechat_cdn_display_variant(
            original.images[-1], current.images[-1]
        ):
            return False
        _draft_request(original=candidate, rewritten_html=current_html)
        return True
    except (OperatorError, shared.OperatorError, KeyError, TypeError, ValueError):
        return False


def _find_unique_published(
    *, items: tuple[PublishedItem, ...], original_request: dict[str, object]
) -> PublishedItem:
    matches = tuple(
        item
        for item in items
        if _source_match(candidate=item.article, original_request=original_request)
    )
    require(len(matches) == 1, "badge_redraft_published_target_not_unique")
    return matches[0]


def _same_frozen_source(current: PublishedItem, target: FixedRedraft) -> None:
    require(
        sha256(current.article_id.encode()).hexdigest()
        == target.binding["published_article_id_fingerprint"],
        "badge_redraft_published_source_drift",
    )
    require(
        _published_article_fingerprint(current.article)
        == target.binding["published_article_fingerprint"],
        "badge_redraft_published_source_drift",
    )
    try:
        shared._same_original(current.article, target.published_article)
    except shared.OperatorError as error:
        raise OperatorError("badge_redraft_published_source_drift") from error


def _display_image_identity(value: str) -> str:
    """Normalize only WeChat's observed terminal /0 versus /640 spelling."""

    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return value
    head, separator, tail = parsed.path.rpartition("/")
    if (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname is not None
        and parsed.hostname.casefold() in shared._WECHAT_IMAGE_CDN_HOSTS
        and port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and bool(separator)
        and tail in {"0", "640"}
    ):
        return parsed._replace(
            scheme="https",
            netloc=parsed.hostname.casefold(),
            path=head + "/<display-variant>",
        ).geturl()
    return value


def _published_article_fingerprint(article: dict[str, object]) -> str:
    """Bind every field while tolerating documented WeChat HTML normalization."""

    fields = _article_fields(article)
    content = cast(str, fields["content"])
    projection = shared.HtmlProjection(content)
    core_keys = frozenset(fields)
    return _sha(
        {
            "request_fields": {
                key: value for key, value in fields.items() if key != "content"
            },
            "content": {
                "topology": projection.topology,
                "links": projection.links,
                "images": [
                    _display_image_identity(value) for value in projection.images
                ],
            },
            "provider_fields": {
                key: (
                    _display_image_identity(value)
                    if key == "thumb_url" and isinstance(value, str)
                    else value
                )
                for key, value in article.items()
                if key not in core_keys
            },
        }
    )


def _same_non_image_article(
    *, current: dict[str, object], expected: dict[str, object]
) -> bool:
    try:
        current_fields, expected_fields = (
            _article_fields(current),
            _article_fields(expected),
        )
        for key in (
            "title",
            "author",
            "digest",
            "thumb_media_id",
            "need_open_comment",
            "only_fans_can_comment",
        ):
            if current_fields[key] != expected_fields[key]:
                return False
        if _normalized_source_url(
            current_fields["content_source_url"]
        ) != _normalized_source_url(expected_fields["content_source_url"]):
            return False
        before = shared.HtmlProjection(cast(str, expected_fields["content"]))
        after = shared.HtmlProjection(cast(str, current_fields["content"]))
        return (
            len(before.images) == len(after.images) == 7
            and before.normalized_text == after.normalized_text
            and before.links == after.links
            and _draft_topology_equivalent(before.topology, after.topology)
        )
    except (OperatorError, shared.OperatorError, KeyError, TypeError, ValueError):
        return False


def _normalized_source_url(value: object) -> str | None:
    """Treat only the two provider spellings of no source link as equivalent."""

    require(
        value is None or isinstance(value, str),
        "badge_redraft_published_article_invalid",
    )
    return cast(str, value) if value else None


def _strict_style_declarations(value: object) -> tuple[tuple[str, str], ...]:
    require(isinstance(value, str), "badge_redraft_root_style_invalid")
    raw_declarations = cast(str, value).split(";")
    if raw_declarations and raw_declarations[-1] == "":
        raw_declarations.pop()
    require(
        bool(raw_declarations) and all(raw_declarations),
        "badge_redraft_root_style_invalid",
    )
    declarations: list[tuple[str, str]] = []
    names: set[str] = set()
    for declaration in raw_declarations:
        raw_name, separator, raw_value = declaration.partition(":")
        name, css_value = raw_name.strip(), raw_value.strip()
        require(
            separator == ":"
            and re.fullmatch(r"-?[a-z][a-z0-9-]*", name) is not None
            and bool(css_value)
            and name not in names
            and not any(ord(character) < 32 for character in css_value),
            "badge_redraft_root_style_invalid",
        )
        names.add(name)
        # Keep the complete retained declaration spelling.  The equivalence
        # below is allowed to delete named declarations only; it must not also
        # normalize whitespace, punctuation, ordering, or retained values.
        declarations.append((name, declaration))
    return tuple(declarations)


def _draft_topology_equivalent(before: list[object], after: list[object]) -> bool:
    """Allow only WeChat's observed eight-property root style deletion."""

    if before == after:
        return True
    if len(before) != len(after) or not before or before[1:] != after[1:]:
        return False
    before_root, after_root = before[0], after[0]
    if not (
        isinstance(before_root, tuple)
        and len(before_root) == 3
        and before_root[:2] == ("start", "section")
        and isinstance(after_root, tuple)
        and len(after_root) == 3
        and after_root[:2] == ("start", "section")
        and isinstance(before_root[2], tuple)
        and isinstance(after_root[2], tuple)
    ):
        return False
    before_attributes = cast(tuple[tuple[str, str | None], ...], before_root[2])
    after_attributes = cast(tuple[tuple[str, str | None], ...], after_root[2])
    before_styles = tuple(value for key, value in before_attributes if key == "style")
    after_styles = tuple(value for key, value in after_attributes if key == "style")
    if len(before_styles) != 1 or len(after_styles) != 1:
        return False
    if tuple(item for item in before_attributes if item[0] != "style") != tuple(
        item for item in after_attributes if item[0] != "style"
    ):
        return False
    try:
        before_style = _strict_style_declarations(before_styles[0])
    except OperatorError:
        return False
    before_names = {name for name, _value in before_style}
    if after_styles[0] == "":
        return before_names == _WECHAT_ROOT_STYLE_REMOVALS
    try:
        after_style = _strict_style_declarations(after_styles[0])
    except OperatorError:
        return False
    assert isinstance(before_styles[0], str) and isinstance(after_styles[0], str)
    if before_styles[0].endswith(";") != after_styles[0].endswith(";"):
        return False
    if not _WECHAT_ROOT_STYLE_REMOVALS.issubset(before_names):
        return False
    return after_style == tuple(
        item for item in before_style if item[0] not in _WECHAT_ROOT_STYLE_REMOVALS
    )


def _verify_draft_replacement(
    *,
    current: dict[str, object],
    original: dict[str, object],
    replacement_urls: tuple[str, str, str, str, str],
) -> None:
    current_for_comparison = dict(current)
    original_for_comparison = dict(original)
    current_for_comparison["content_source_url"] = _normalized_source_url(
        current.get("content_source_url")
    )
    original_for_comparison["content_source_url"] = _normalized_source_url(
        original.get("content_source_url")
    )
    try:
        shared._same_original(
            {
                **current_for_comparison,
                "content": original_for_comparison["content"],
            },
            original_for_comparison,
        )
        original_content = original_for_comparison.get("content")
        current_content = current_for_comparison.get("content")
        require(
            isinstance(original_content, str) and isinstance(current_content, str),
            "badge_redraft_readback_mismatch",
        )
        assert isinstance(original_content, str) and isinstance(current_content, str)
        before = shared.HtmlProjection(original_content)
        after = shared.HtmlProjection(current_content)
        require(
            before.normalized_text == after.normalized_text
            and before.links == after.links
            and _draft_topology_equivalent(before.topology, after.topology)
            and len(before.images) == len(after.images) == 7
            and len(set(after.images)) == 7
            and shared._same_wechat_cdn_display_variant(
                before.images[0], after.images[0]
            )
            and shared._same_wechat_cdn_display_variant(
                before.images[-1], after.images[-1]
            )
            and all(
                shared._same_wechat_cdn_display_variant(expected, actual)
                for expected, actual in zip(
                    replacement_urls, after.images[1:6], strict=True
                )
            )
            and all(
                not shared._same_wechat_cdn_display_variant(old, new)
                for old, new in zip(before.images[1:6], after.images[1:6], strict=True)
            ),
            "badge_redraft_readback_mismatch",
        )
    except shared.OperatorError as error:
        raise OperatorError("badge_redraft_readback_mismatch") from error


def _matching_drafts(
    *,
    items: tuple[DraftItem, ...],
    original: dict[str, object],
    replacement_urls: tuple[str, str, str, str, str] | None = None,
) -> tuple[DraftItem, ...]:
    matches: list[DraftItem] = []
    for item in items:
        if not _same_non_image_article(current=item.article, expected=original):
            continue
        if replacement_urls is not None:
            try:
                _verify_draft_replacement(
                    current=item.article,
                    original=original,
                    replacement_urls=replacement_urls,
                )
            except OperatorError:
                continue
        matches.append(item)
    return tuple(matches)


async def _load_fixed_inputs(
    *,
    journal: Journal,
    store: OfficialAccountGeneratedVisualStore,
    remote: RemoteRedraft,
) -> FixedRedraft:
    original_media_id, original_request, original_binding = (
        shared._load_original_binding(journal)
    )
    bodies, candidate_binding = await shared._load_approved_candidates(
        journal,
        store,
        article_fingerprint=cast(str, original_binding["article_fingerprint"]),
    )
    require(
        await remote.original_draft_absent(original_media_id),
        "badge_redraft_original_draft_still_present",
    )
    published = _find_unique_published(
        items=await remote.published_items(), original_request=original_request
    )
    fields = _article_fields(published.article)
    projection = shared.HtmlProjection(cast(str, fields["content"]))
    require(
        len(projection.images) == 7 and len(set(projection.images)) == 7,
        "badge_redraft_media_topology_changed",
    )
    binding = {
        "version": OPERATION_VERSION,
        "account": ACCOUNT,
        "business_date": BUSINESS_DATE,
        "edition_id": str(EDITION),
        **original_binding,
        **candidate_binding,
        "published_article_id_fingerprint": sha256(
            published.article_id.encode()
        ).hexdigest(),
        "published_article_fingerprint": _published_article_fingerprint(
            published.article
        ),
        "inline_uploads": MAX_INLINE_UPLOADS,
        "new_unpublished_draft": True,
        "published_unchanged": True,
    }
    return FixedRedraft(
        original_draft_media_id=original_media_id,
        original_request=original_request,
        published_article_id=published.article_id,
        published_article=published.article,
        bodies=bodies,
        binding=binding,
    )


async def _verify_published_source(
    *, remote: RemoteRedraft, target: FixedRedraft
) -> None:
    current = _find_unique_published(
        items=await remote.published_items(), original_request=target.original_request
    )
    _same_frozen_source(current, target)


def _effect_intent(
    *, binding_sha256: str, step: str, request: dict[str, Any]
) -> dict[str, Any]:
    return {
        "version": OPERATION_VERSION,
        "binding_sha256": binding_sha256,
        "step": step,
        "request": request,
    }


def _write_or_verify(journal: Journal, name: str, payload: dict[str, Any]) -> None:
    old = journal.read(name)
    if old is None:
        journal.write(name, payload)
    else:
        require(old == payload, "badge_redraft_receipt_changed")


def _upload_names(ordinal: int) -> tuple[str, str]:
    require(0 <= ordinal < MAX_INLINE_UPLOADS, "badge_redraft_ordinal_invalid")
    stem = f"{REDRAFT_PREFIX}-upload-{ordinal}"
    return stem + "-intent.json", stem + "-ack.json"


def _expected_upload_intent(
    *, binding_sha256: str, ordinal: int, body: bytes
) -> dict[str, Any]:
    return _effect_intent(
        binding_sha256=binding_sha256,
        step=f"inline-upload-{ordinal}",
        request={
            "ordinal": ordinal,
            "media_type": "image/jpeg",
            "byte_size": len(body),
            "sha256": sha256(body).hexdigest(),
            "filename": f"badge-redraft-visual-{ordinal + 1}.jpg",
        },
    )


def _acknowledged_url(*, intent: dict[str, Any], ack: dict[str, Any] | None) -> str:
    require(
        isinstance(ack, dict)
        and set(ack) == {"intent_sha256", "value"}
        and ack.get("intent_sha256") == _sha(intent)
        and isinstance(ack.get("value"), dict),
        "badge_redraft_upload_ack_changed",
    )
    assert isinstance(ack, dict)
    value = cast(dict[str, object], ack["value"])
    require(set(value) == {"url"}, "badge_redraft_upload_ack_changed")
    return shared._strict_wechat_cdn_upload_url(value.get("url"))


async def _upload_once(
    *,
    journal: Journal,
    remote: RemoteRedraft,
    target: FixedRedraft,
    binding_sha256: str,
    ordinal: int,
    body: bytes,
) -> str:
    intent_name, ack_name = _upload_names(ordinal)
    intent = _expected_upload_intent(
        binding_sha256=binding_sha256, ordinal=ordinal, body=body
    )
    old, ack = journal.read(intent_name), journal.read(ack_name)
    if old is not None:
        require(old == intent, "badge_redraft_upload_intent_changed")
        if ack is None:
            raise OperatorError("badge_redraft_upload_outcome_unknown")
        return _acknowledged_url(intent=intent, ack=ack)
    require(ack is None, "badge_redraft_upload_ack_without_intent")
    await _verify_published_source(remote=remote, target=target)
    journal.write(intent_name, intent)
    try:
        url = await remote.upload(
            body=body, filename=cast(str, intent["request"]["filename"])
        )
        url = shared._strict_wechat_cdn_upload_url(url)
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        raise
    except Exception as error:
        raise OperatorError("badge_redraft_upload_outcome_unknown") from error
    journal.write(ack_name, {"intent_sha256": _sha(intent), "value": {"url": url}})
    return url


def _inspect_uploads(
    *, journal: Journal, target: FixedRedraft, binding_sha256: str
) -> int:
    completed = 0
    for ordinal, body in enumerate(target.bodies):
        intent_name, ack_name = _upload_names(ordinal)
        expected = _expected_upload_intent(
            binding_sha256=binding_sha256, ordinal=ordinal, body=body
        )
        intent, ack = journal.read(intent_name), journal.read(ack_name)
        if intent is None:
            require(ack is None, "badge_redraft_upload_ack_without_intent")
            continue
        require(intent == expected, "badge_redraft_upload_intent_changed")
        if ack is None:
            raise OperatorError("badge_redraft_upload_outcome_unknown")
        _acknowledged_url(intent=expected, ack=ack)
        completed += 1
    return completed


def _load_upload_urls(
    *, journal: Journal, target: FixedRedraft, binding_sha256: str
) -> tuple[str, str, str, str, str]:
    urls: list[str] = []
    for ordinal, body in enumerate(target.bodies):
        intent_name, ack_name = _upload_names(ordinal)
        intent = _expected_upload_intent(
            binding_sha256=binding_sha256, ordinal=ordinal, body=body
        )
        require(
            journal.read(intent_name) == intent,
            "badge_redraft_add_without_uploads",
        )
        urls.append(_acknowledged_url(intent=intent, ack=journal.read(ack_name)))
    require(len(set(urls)) == MAX_INLINE_UPLOADS, "badge_redraft_upload_urls_invalid")
    return cast(tuple[str, str, str, str, str], tuple(urls))


def _add_names() -> tuple[str, str, str]:
    stem = f"{REDRAFT_PREFIX}-draft-add"
    return stem + "-intent.json", stem + "-ack.json", stem + "-readback.json"


def _expected_add_intent(
    *,
    binding_sha256: str,
    article: WeChatDraftArticleRequest,
    replacement_urls: tuple[str, str, str, str, str],
) -> dict[str, Any]:
    return _effect_intent(
        binding_sha256=binding_sha256,
        step="new-draft-add",
        request={
            "article": asdict(article),
            "replacement_urls": list(replacement_urls),
        },
    )


def _validate_add_ack(
    *, intent: dict[str, Any], ack: dict[str, Any] | None
) -> tuple[str, str] | None:
    if ack is None:
        return None
    require(
        set(ack) == {"intent_sha256", "value"}
        and ack.get("intent_sha256") == _sha(intent)
        and isinstance(ack.get("value"), dict),
        "badge_redraft_add_ack_changed",
    )
    value = cast(dict[str, object], ack["value"])
    require(
        set(value) == {"media_id", "resolution", "not_published"}
        and value.get("resolution") in {"acknowledged", "readback_after_unknown"}
        and value.get("not_published") is True,
        "badge_redraft_add_ack_changed",
    )
    return (
        shared._safe_media_id(value.get("media_id")),
        cast(str, value["resolution"]),
    )


def _article_from_add_intent(intent: dict[str, Any]) -> WeChatDraftArticleRequest:
    request = intent.get("request")
    article = request.get("article") if isinstance(request, dict) else None
    require(isinstance(article, dict), "badge_redraft_add_intent_changed")
    try:
        result = WeChatDraftArticleRequest(**cast(dict[str, Any], article))
        _validate_draft_article(result)
    except (TypeError, UnicodeError, ValueError) as error:
        raise OperatorError("badge_redraft_add_intent_changed") from error
    return result


def _replacement_urls_from_add_intent(
    intent: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    request = intent.get("request")
    values = request.get("replacement_urls") if isinstance(request, dict) else None
    require(
        isinstance(values, list) and len(values) == MAX_INLINE_UPLOADS,
        "badge_redraft_add_intent_changed",
    )
    assert isinstance(values, list)
    urls = tuple(shared._strict_wechat_cdn_upload_url(value) for value in values)
    require(len(set(urls)) == MAX_INLINE_UPLOADS, "badge_redraft_add_intent_changed")
    return cast(tuple[str, str, str, str, str], urls)


def _readback_receipt(
    *,
    binding_sha256: str,
    add_intent: dict[str, Any],
    media_id: str,
    resolution: str,
) -> dict[str, Any]:
    return {
        "version": OPERATION_VERSION,
        "binding_sha256": binding_sha256,
        "add_intent_sha256": _sha(add_intent),
        "draft_media_fingerprint": sha256(media_id.encode()).hexdigest(),
        "resolution": resolution,
        "verified": True,
        "not_published": True,
        "published_unchanged": True,
    }


def _baseline_fingerprints(claim: dict[str, Any]) -> frozenset[str]:
    binding = claim.get("binding")
    values = (
        binding.get("baseline_draft_fingerprints")
        if isinstance(binding, dict)
        else None
    )
    require(
        isinstance(values, list)
        and len(values) <= MAX_REMOTE_ITEMS
        and len(values) == len(set(values))
        and all(shared._hex64(value) for value in values),
        "badge_redraft_claim_changed",
    )
    return frozenset(cast(list[str], values))


async def _verify_created_draft(
    *,
    remote: RemoteRedraft,
    target: FixedRedraft,
    media_id: str,
    replacement_urls: tuple[str, str, str, str, str],
) -> None:
    current = await remote.get_draft(media_id)
    _verify_draft_replacement(
        current=current,
        original=target.published_article,
        replacement_urls=replacement_urls,
    )
    matches = _matching_drafts(
        items=await remote.draft_items(),
        original=target.published_article,
        replacement_urls=replacement_urls,
    )
    require(
        len(matches) == 1 and matches[0].media_id == media_id,
        "badge_redraft_not_unique",
    )
    await _verify_published_source(remote=remote, target=target)


async def _reconcile_existing_add(
    *,
    mode: str,
    journal: Journal,
    remote: RemoteRedraft,
    target: FixedRedraft,
    claim: dict[str, Any],
    binding_sha256: str,
) -> dict[str, object]:
    intent_name, ack_name, readback_name = _add_names()
    intent = shared._read_required(
        journal, intent_name, "badge_redraft_add_intent_invalid"
    )
    urls = _load_upload_urls(
        journal=journal, target=target, binding_sha256=binding_sha256
    )
    content = target.published_article.get("content")
    require(isinstance(content, str), "badge_redraft_published_article_invalid")
    assert isinstance(content, str)
    expected_article = _draft_request(
        original=target.published_article,
        rewritten_html=shared._rewrite_body(
            original_html=content,
            original_urls=tuple(shared.HtmlProjection(content).images),
            replacement_urls=urls,
        ),
    )
    expected_intent = _expected_add_intent(
        binding_sha256=binding_sha256,
        article=expected_article,
        replacement_urls=urls,
    )
    require(intent == expected_intent, "badge_redraft_add_intent_changed")
    _article_from_add_intent(intent)
    _replacement_urls_from_add_intent(intent)
    acknowledged = _validate_add_ack(intent=intent, ack=journal.read(ack_name))
    if acknowledged is None:
        matches = _matching_drafts(
            items=await remote.draft_items(),
            original=target.published_article,
            replacement_urls=urls,
        )
        baseline = _baseline_fingerprints(claim)
        new_matches = tuple(
            item
            for item in matches
            if sha256(item.media_id.encode()).hexdigest() not in baseline
        )
        if len(new_matches) != 1 or len(matches) != 1:
            return {
                "status": "outcome_unknown_reconcile_only",
                "images": MAX_INLINE_UPLOADS,
                "external_writes": 0,
                "not_published": True,
            }
        media_id, resolution = new_matches[0].media_id, "readback_after_unknown"
        await _verify_created_draft(
            remote=remote,
            target=target,
            media_id=media_id,
            replacement_urls=urls,
        )
        if mode == "plan":
            return {
                "status": "reconcilable_after_unknown",
                "images": MAX_INLINE_UPLOADS,
                "external_writes": 0,
                "readback_verified": True,
                "not_published": True,
            }
        if mode != "reconcile":
            return {
                "status": "outcome_unknown_reconcile_only",
                "images": MAX_INLINE_UPLOADS,
                "external_writes": 0,
                "readback_verified": True,
                "not_published": True,
            }
        journal.write(
            ack_name,
            {
                "intent_sha256": _sha(intent),
                "value": {
                    "media_id": media_id,
                    "resolution": resolution,
                    "not_published": True,
                },
            },
        )
    else:
        media_id, resolution = acknowledged
        await _verify_created_draft(
            remote=remote,
            target=target,
            media_id=media_id,
            replacement_urls=urls,
        )
    receipt = _readback_receipt(
        binding_sha256=binding_sha256,
        add_intent=intent,
        media_id=media_id,
        resolution=resolution,
    )
    old = journal.read(readback_name)
    if old is not None:
        require(old == receipt, "badge_redraft_readback_changed")
    elif mode != "plan":
        journal.write(readback_name, receipt)
    return {
        "status": (
            "readback_verified"
            if resolution == "acknowledged"
            else "readback_verified_after_unknown"
        ),
        "images": MAX_INLINE_UPLOADS,
        "external_writes": 0,
        "readback_verified": True,
        "not_published": True,
        "published_unchanged": True,
    }


async def create_corrected_draft(
    *,
    mode: str,
    journal: Journal,
    store: OfficialAccountGeneratedVisualStore,
    remote: RemoteRedraft,
) -> dict[str, object]:
    """Run the bounded plan/create/reconcile state machine."""

    require(mode in {"plan", "create", "reconcile"}, "badge_redraft_mode_invalid")
    target = await _load_fixed_inputs(journal=journal, store=store, remote=remote)
    claim_name = f"{REDRAFT_PREFIX}-claim.json"
    add_intent_name, add_ack_name, readback_name = _add_names()
    claim = journal.read(claim_name)
    drafts = await remote.draft_items()
    existing_add = journal.read(add_intent_name)
    existing_add_ack = journal.read(add_ack_name)
    existing_readback = journal.read(readback_name)
    require(
        existing_add_ack is None or existing_add is not None,
        "badge_redraft_add_ack_without_intent",
    )
    require(
        existing_readback is None
        or (existing_add is not None and existing_add_ack is not None),
        "badge_redraft_readback_without_ack",
    )
    if claim is None:
        orphaned_receipt = any(
            journal.read(name) is not None
            for ordinal in range(MAX_INLINE_UPLOADS)
            for name in _upload_names(ordinal)
        )
        require(
            existing_add is None and not orphaned_receipt,
            "badge_redraft_effect_without_claim",
        )
        require(
            not _matching_drafts(items=drafts, original=target.published_article),
            "badge_redraft_preexisting_matching_draft",
        )
        baseline = sorted(sha256(item.media_id.encode()).hexdigest() for item in drafts)
        operation_binding = {
            **target.binding,
            "baseline_draft_fingerprints": baseline,
            "baseline_draft_count": len(drafts),
        }
        expected_claim = {
            "version": OPERATION_VERSION,
            "binding": operation_binding,
            "published_article": target.published_article,
        }
        if mode == "create":
            journal.write(claim_name, expected_claim)
    else:
        require(
            set(claim) == {"version", "binding", "published_article"}
            and claim.get("version") == OPERATION_VERSION
            and isinstance(claim.get("binding"), dict)
            and isinstance(claim.get("published_article"), dict),
            "badge_redraft_claim_changed",
        )
        frozen_article = cast(dict[str, object], claim["published_article"])
        try:
            shared._same_original(frozen_article, target.published_article)
        except shared.OperatorError as error:
            raise OperatorError("badge_redraft_claim_changed") from error
        operation_binding = {
            **target.binding,
            "baseline_draft_fingerprints": sorted(_baseline_fingerprints(claim)),
            "baseline_draft_count": len(_baseline_fingerprints(claim)),
        }
        expected_claim = {
            "version": OPERATION_VERSION,
            "binding": operation_binding,
            "published_article": frozen_article,
        }
        require(claim == expected_claim, "badge_redraft_claim_changed")
    effect_target = FixedRedraft(
        original_draft_media_id=target.original_draft_media_id,
        original_request=target.original_request,
        published_article_id=target.published_article_id,
        published_article=cast(dict[str, object], expected_claim["published_article"]),
        bodies=target.bodies,
        binding=operation_binding,
    )
    binding_sha256 = _sha(operation_binding)
    if existing_add is not None:
        return await _reconcile_existing_add(
            mode=mode,
            journal=journal,
            remote=remote,
            target=effect_target,
            claim=expected_claim,
            binding_sha256=binding_sha256,
        )

    require(
        {sha256(item.media_id.encode()).hexdigest() for item in drafts}
        == set(_baseline_fingerprints(expected_claim))
        and not _matching_drafts(
            items=drafts, original=effect_target.published_article
        ),
        "badge_redraft_draft_baseline_drift",
    )

    completed_uploads = _inspect_uploads(
        journal=journal, target=effect_target, binding_sha256=binding_sha256
    )
    if mode == "plan":
        return {
            "status": "planned",
            "images": MAX_INLINE_UPLOADS,
            "external_writes": 0,
            "completed_uploads": completed_uploads,
            "not_published": True,
            "published_unchanged": True,
        }
    require(mode == "create", "badge_redraft_reconcile_without_add_intent")

    urls: list[str] = []
    external_writes = 0
    for ordinal, body in enumerate(effect_target.bodies):
        intent_name, _ack_name = _upload_names(ordinal)
        was_new = journal.read(intent_name) is None
        urls.append(
            await _upload_once(
                journal=journal,
                remote=remote,
                target=effect_target,
                binding_sha256=binding_sha256,
                ordinal=ordinal,
                body=body,
            )
        )
        external_writes += int(was_new)
    replacement_urls = cast(tuple[str, str, str, str, str], tuple(urls))
    require(len(set(replacement_urls)) == 5, "badge_redraft_upload_urls_invalid")

    await _verify_published_source(remote=remote, target=effect_target)
    current_drafts = await remote.draft_items()
    require(
        {sha256(item.media_id.encode()).hexdigest() for item in current_drafts}
        == set(_baseline_fingerprints(expected_claim))
        and not _matching_drafts(
            items=current_drafts, original=effect_target.published_article
        ),
        "badge_redraft_draft_baseline_drift",
    )
    content = effect_target.published_article.get("content")
    require(isinstance(content, str), "badge_redraft_published_article_invalid")
    assert isinstance(content, str)
    article = _draft_request(
        original=effect_target.published_article,
        rewritten_html=shared._rewrite_body(
            original_html=content,
            original_urls=tuple(shared.HtmlProjection(content).images),
            replacement_urls=replacement_urls,
        ),
    )
    add_intent = _expected_add_intent(
        binding_sha256=binding_sha256,
        article=article,
        replacement_urls=replacement_urls,
    )
    require(
        journal.read(add_intent_name) is None and journal.read(add_ack_name) is None,
        "badge_redraft_add_receipt_invalid",
    )
    journal.write(add_intent_name, add_intent)
    try:
        media_id = await remote.add(article=article)
        media_id = shared._safe_media_id(media_id)
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        raise
    except Exception as error:
        raise OperatorError("badge_redraft_add_outcome_unknown") from error
    external_writes += 1
    journal.write(
        add_ack_name,
        {
            "intent_sha256": _sha(add_intent),
            "value": {
                "media_id": media_id,
                "resolution": "acknowledged",
                "not_published": True,
            },
        },
    )
    await _verify_created_draft(
        remote=remote,
        target=effect_target,
        media_id=media_id,
        replacement_urls=replacement_urls,
    )
    _write_or_verify(
        journal,
        _add_names()[2],
        _readback_receipt(
            binding_sha256=binding_sha256,
            add_intent=add_intent,
            media_id=media_id,
            resolution="acknowledged",
        ),
    )
    return {
        "status": "new_unpublished_draft_created",
        "images": MAX_INLINE_UPLOADS,
        "external_writes": external_writes,
        "readback_verified": True,
        "not_published": True,
        "published_unchanged": True,
    }


def _require_existing_journal_root(*, root: Path) -> None:
    directory = root / "manual-v1" / ACCOUNT
    try:
        info = directory.stat(follow_symlinks=False)
        lock_info = (directory / "lock").stat(follow_symlinks=False)
    except OSError as error:
        raise OperatorError("badge_redraft_journal_missing") from error
    require(
        stat.S_ISDIR(info.st_mode)
        and not directory.is_symlink()
        and stat.S_ISREG(lock_info.st_mode)
        and not (directory / "lock").is_symlink(),
        "badge_redraft_journal_missing",
    )


def _require_shared_dependency() -> None:
    location = getattr(shared, "__file__", None)
    require(isinstance(location, str), "badge_redraft_shared_dependency_changed")
    path = Path(cast(str, location))
    try:
        info = path.stat(follow_symlinks=False)
        body = path.read_bytes()
    except OSError as error:
        raise OperatorError("badge_redraft_shared_dependency_changed") from error
    require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and sha256(body).hexdigest() == SHARED_MODULE_SHA256,
        "badge_redraft_shared_dependency_changed",
    )


async def _main(command: str, apply: bool) -> dict[str, object]:
    from app.core.config import get_settings

    _require_shared_dependency()
    require(
        (command == "plan" and not apply)
        or (command == "create" and apply)
        or (command == "reconcile" and not apply),
        "badge_redraft_explicit_apply_required",
    )
    settings = get_settings()
    require(
        settings.wechat_mp_app_id is not None
        and wechat_draft_account_fingerprint(
            settings.wechat_mp_app_id.get_secret_value()
        )
        == ACCOUNT,
        "badge_redraft_account_mismatch",
    )
    root = Path(settings.wechat_mp_draft_artifact_root)
    _require_existing_journal_root(root=root)
    journal = LocalManualDraftJournal(root, ACCOUNT)
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        client = WeChatOfficialAccountHttpClient(settings)
        return await create_corrected_draft(
            mode=command,
            journal=journal,
            store=MinioImageStore(settings),
            remote=OfficialRemote(client),
        )
    finally:
        try:
            if client is not None:
                await client.aclose()
        finally:
            journal.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", default="plan", choices=("plan", "create", "reconcile")
    )
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        result = asyncio.run(_main(arguments.command, arguments.apply))
    except Exception as error:  # noqa: BLE001 - fixed, secret-free CLI boundary
        code = getattr(error, "code", None)
        if (
            not isinstance(code, str)
            or re.fullmatch(r"badge_redraft_[a-z0-9_]{1,68}", code) is None
        ):
            code = "badge_redraft_operator_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
