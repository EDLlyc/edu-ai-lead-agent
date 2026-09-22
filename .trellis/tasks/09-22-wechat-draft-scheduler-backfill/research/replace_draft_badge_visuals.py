"""Replace exactly five body images in the fixed September 21 WeChat draft.

The operator has no caller-selected target or candidate path.  It recovers the
existing draft identity only from the durable backfill add intent/ACK, loads the
visually approved ``badgefix-...-v1`` objects only from the private journal and
content-addressed store, and preserves the same unpublished draft.  ``plan`` is
read-only.  ``replace --apply`` is the only new-write mode: five journaled
inline uploads followed by at most one journaled same-ID draft update.  An
ambiguous upload or update is never replayed; update reconciliation is readback
only.

This task-local operator intentionally uses application APIs available in the
production backend at ``abfb89d`` and has no database write path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import stat
from dataclasses import asdict, dataclass
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualStore,
)
from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
from app.domain.official_account_strict_layout import strict_escaped_upload_url
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
from app.infrastructure.wechat_official_account.manual_journal import (
    fingerprint as journal_fingerprint,
)
from PIL import Image

OPERATION_VERSION = "sep21-xiaosai-badge-same-draft-replacement-v1"
BACKFILL_VERSION = "single-edition-sep21-backfill-v1"
BADGE_VERSION = "sep21-xiaosai-ai-badge-regeneration-v1"
ACCOUNT = "ae3a5056a1c78eddf728060ecc5287b6a93e48d99e496bc9a22292a2b4eb8fd7"
BUSINESS_DATE = "2026-09-21"
EDITION = UUID("3afa48cb-f0a1-5912-b538-5ed2d2fb14c0")
BACKFILL_PREFIX = f"backfill-{EDITION.hex}"
BADGE_PREFIX = f"badgefix-{EDITION.hex}-v1"
REPLACEMENT_PREFIX = f"badge-replace-{EDITION.hex}-v1"
EXPECTED_IMAGE_SIZE = (1536, 1024)
MAX_INLINE_UPLOADS = 5
_WECHAT_IMAGE_CDN_HOSTS = frozenset({"mmbiz.qpic.cn", "mmecoa.qpic.cn"})

# These are the five images the user reviewed and approved on 2026-09-22.  The
# fixed tuple turns that human decision into an exact-set admission gate; a new
# generation result cannot silently enter this replacement operation.
APPROVED_OBJECTS: tuple[tuple[int, str, int, str, int, int], ...] = (
    (
        0,
        "image/jpeg",
        299134,
        "d9c032d5b9113b6d2659b7acfecb4a6d30044cb03f9a0a52bb4875dadaefe684",
        1536,
        1024,
    ),
    (
        1,
        "image/jpeg",
        318719,
        "ec285142d6a8f093a91b1d6612b98e3aa404538d258633ae0176795dcc948c57",
        1536,
        1024,
    ),
    (
        2,
        "image/jpeg",
        295131,
        "0ca4e6741b40d75933f7832d4a462e51b3a232e62e0df150874daf72fd225150",
        1536,
        1024,
    ),
    (
        3,
        "image/jpeg",
        286621,
        "99bec5f45337c3ed2b62c540628e2090eec1aa6cc315f0097cb9f45af362645b",
        1536,
        1024,
    ),
    (
        4,
        "image/jpeg",
        306766,
        "c9a76fc22b6642b1887ff5af5f6c59c08ff6a3e700c2ee53ceb0df435083e160",
        1536,
        1024,
    ),
)


class OperatorError(ValueError):
    """One secret-free, bounded operator failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require(condition: object, code: str) -> None:
    if not condition:
        raise OperatorError(code)


def _sha(payload: dict[str, Any]) -> str:
    return journal_fingerprint(payload)


def _hex64(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _safe_media_id(value: object) -> str:
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None,
        "badge_replace_media_id_invalid",
    )
    return cast(str, value)


def _strict_wechat_cdn_upload_url(value: object) -> str:
    require(
        isinstance(value, str)
        and 0 < len(value) <= 2048
        and not any(
            character.isspace() or ord(character) < 32 or 127 <= ord(character) <= 159
            for character in value
        )
        and not any(character in value for character in "\"'<>"),
        "badge_replace_upload_url_invalid",
    )
    parsed = urlsplit(cast(str, value))
    try:
        port = parsed.port
    except ValueError as error:
        raise OperatorError("badge_replace_upload_url_invalid") from error
    require(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname is not None
        and parsed.hostname.casefold() in _WECHAT_IMAGE_CDN_HOSTS
        and port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/")
        and parsed.path != "/"
        and not parsed.fragment,
        "badge_replace_upload_url_invalid",
    )
    assert parsed.hostname is not None
    return parsed._replace(scheme="https", netloc=parsed.hostname.casefold()).geturl()


class Journal(Protocol):
    def read(self, name: str) -> dict[str, Any] | None: ...

    def write(self, name: str, payload: dict[str, Any]) -> None: ...


class RemoteDraft(Protocol):
    async def get(self, media_id: str) -> dict[str, object]: ...

    async def upload(self, *, body: bytes, filename: str) -> str: ...

    async def update(
        self, *, media_id: str, article: WeChatDraftArticleRequest
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class FixedReplacement:
    media_id: str
    original_article: dict[str, object]
    bodies: tuple[bytes, bytes, bytes, bytes, bytes]
    binding: dict[str, Any]


class HtmlProjection(HTMLParser):
    """Compare all non-image HTML while retaining exact seven-image topology."""

    _VOID_TAGS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self, value: str) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.images: list[str] = []
        self.links: list[str | None] = []
        self.topology: list[object] = []
        self._open_tags: list[str] = []
        self.feed(value)
        self.close()
        require(not self._open_tags, "badge_replace_remote_html_invalid")

    @staticmethod
    def _attributes(
        tag: str, attrs: list[tuple[str, str | None]]
    ) -> tuple[tuple[str, str | None], ...]:
        require(
            len({key for key, _value in attrs}) == len(attrs),
            "badge_replace_remote_duplicate_attribute",
        )
        normalized: list[tuple[str, str | None]] = []
        for key, value in attrs:
            if tag == "span" and key == "leaf" and value in {None, "", "leaf"}:
                # WeChat serializes the renderer's bare boolean ``leaf`` marker
                # as ``leaf="leaf"``.  Presence is the frozen DOM signal.
                value = "<present>"
            if tag == "img" and key in {"src", "data-src"}:
                continue
            normalized.append((key, value))
        if tag == "img":
            # WeChat may round-trip the same image resource under ``src`` or
            # ``data-src`` (and may retain both).  The resource itself remains
            # separately bound in ``images``; only the observed attribute-key
            # spelling is transport-equivalent.
            normalized.append(("<inline-image-url>", "<present>"))
        return tuple(sorted(normalized))

    def _start(self, kind: str, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        if tag == "img":
            src, data_src = fields.get("src"), fields.get("data-src")
            require(
                (src is not None or data_src is not None)
                and (src is None or data_src is None or src == data_src),
                "badge_replace_remote_image_conflict",
            )
            image = src if src is not None else data_src
            require(isinstance(image, str), "badge_replace_remote_image_conflict")
            self.images.append(cast(str, image))
        if tag == "a":
            self.links.append(fields.get("href"))
        self.topology.append((kind, tag, self._attributes(tag, attrs)))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start("start", tag, attrs)
        if tag not in self._VOID_TAGS:
            self._open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start("start", tag, attrs)
        if tag not in {"img", "br"}:
            self.topology.append(("end", tag))

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID_TAGS:
            return
        require(
            bool(self._open_tags) and self._open_tags[-1] == tag,
            "badge_replace_remote_html_invalid",
        )
        self._open_tags.pop()
        self.topology.append(("end", tag))

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        self.topology.append(("text", data))

    def handle_comment(self, data: str) -> None:
        raise OperatorError("badge_replace_remote_html_invalid")

    def handle_decl(self, decl: str) -> None:
        raise OperatorError("badge_replace_remote_html_invalid")

    def handle_pi(self, data: str) -> None:
        raise OperatorError("badge_replace_remote_html_invalid")

    @property
    def normalized_text(self) -> str:
        return " ".join("".join(self.text).split())


def _response_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        require(key not in value, "badge_replace_response_duplicate_key")
        value[key] = item
    return value


def _invalid_constant(_value: str) -> None:
    raise OperatorError("badge_replace_response_invalid_constant")


class OfficialRemote:
    """Expose only readback, inline upload, and same-ID update endpoints."""

    def __init__(self, client: WeChatOfficialAccountHttpClient) -> None:
        self.client = client

    async def _token(self) -> str:
        value = (await self.client._get_access_token()).value
        require(isinstance(value, str), "badge_replace_token_invalid")
        return value

    async def _post(
        self,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        limit: int = 65_536,
    ) -> dict[str, object]:
        require(
            path
            in {
                "/cgi-bin/draft/get",
                "/cgi-bin/draft/update",
                "/cgi-bin/media/uploadimg",
            },
            "badge_replace_endpoint_forbidden",
        )
        try:
            async with asyncio.timeout(self.client._total_timeout_seconds):
                async with self.client._client.stream(
                    "POST",
                    self.client._base_url + path,
                    params={"access_token": await self._token()},
                    json=payload,
                    files=files,
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
                        "badge_replace_response_not_acknowledged",
                    )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        require(size <= limit, "badge_replace_response_too_large")
                        chunks.append(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise OperatorError("badge_replace_transport_failed") from error
        decoded = json.loads(
            b"".join(chunks),
            object_pairs_hook=_response_object,
            parse_constant=_invalid_constant,
        )
        require(isinstance(decoded, dict), "badge_replace_response_invalid")
        result = cast(dict[str, object], decoded)
        require(
            "errcode" not in result
            or (type(result["errcode"]) is int and result["errcode"] == 0),
            "badge_replace_response_not_acknowledged",
        )
        return result

    async def get(self, media_id: str) -> dict[str, object]:
        result = await self._post(
            "/cgi-bin/draft/get",
            payload={"media_id": media_id},
            limit=1_048_576,
        )
        items = result.get("news_item")
        require(
            isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict),
            "badge_replace_remote_article_invalid",
        )
        assert isinstance(items, list) and isinstance(items[0], dict)
        return dict(cast(dict[str, object], items[0]))

    async def upload(self, *, body: bytes, filename: str) -> str:
        result = await self._post(
            "/cgi-bin/media/uploadimg",
            files={"media": (filename, body, "image/jpeg")},
        )
        url = _strict_wechat_cdn_upload_url(result.get("url"))
        strict_escaped_upload_url(url)
        return url

    async def update(
        self, *, media_id: str, article: WeChatDraftArticleRequest
    ) -> None:
        request = asdict(article)
        request.update(
            article_type="news",
            need_open_comment=int(article.need_open_comment),
            only_fans_can_comment=int(article.only_fans_can_comment),
        )
        result = await self._post(
            "/cgi-bin/draft/update",
            payload={"media_id": media_id, "index": 0, "articles": request},
        )
        require(
            type(result.get("errcode")) is int and result["errcode"] == 0,
            "badge_replace_update_outcome_unknown",
        )


def _article_fields(value: dict[str, object]) -> dict[str, object]:
    fields = {
        key: value.get(key)
        for key in (
            "title",
            "author",
            "digest",
            "content",
            "content_source_url",
            "thumb_media_id",
            "need_open_comment",
            "only_fans_can_comment",
        )
    }
    require(
        all(
            isinstance(fields[key], str)
            for key in ("title", "author", "digest", "content", "thumb_media_id")
        )
        and (
            fields["content_source_url"] is None
            or isinstance(fields["content_source_url"], str)
        )
        and all(
            fields[key] in {None, 0, 1}
            for key in ("need_open_comment", "only_fans_can_comment")
        ),
        "badge_replace_remote_article_invalid",
    )
    return fields


def _same_wechat_cdn_display_variant(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    before, after = urlsplit(expected), urlsplit(actual)
    before_head, _, before_tail = before.path.rpartition("/")
    after_head, _, after_tail = after.path.rpartition("/")
    return (
        before.scheme in {"http", "https"}
        and after.scheme in {"http", "https"}
        and before.hostname is not None
        and before.hostname.casefold() in _WECHAT_IMAGE_CDN_HOSTS
        and before.hostname.casefold() == (after.hostname or "").casefold()
        and before.port == after.port
        and before.username is None
        and before.password is None
        and after.username is None
        and after.password is None
        and before.query == after.query
        and before.fragment == after.fragment == ""
        and before_head == after_head
        and (before_tail, after_tail) in {("0", "640"), ("640", "0")}
    )


def _same_original(current: dict[str, object], expected: dict[str, object]) -> None:
    current_fields, expected_fields = (
        _article_fields(current),
        _article_fields(expected),
    )
    for key in ("title", "author", "digest", "thumb_media_id"):
        require(
            current_fields[key] == expected_fields[key], "badge_replace_remote_edited"
        )
    for key in ("content_source_url", "need_open_comment", "only_fans_can_comment"):
        require(
            current_fields[key] == expected_fields[key],
            "badge_replace_remote_edited",
        )
    current_html, expected_html = current_fields["content"], expected_fields["content"]
    assert isinstance(current_html, str) and isinstance(expected_html, str)
    before, after = HtmlProjection(expected_html), HtmlProjection(current_html)
    require(
        before.normalized_text == after.normalized_text
        and before.links == after.links
        and before.topology == after.topology
        and len(before.images) == len(after.images)
        and all(
            _same_wechat_cdn_display_variant(expected_url, current_url)
            for expected_url, current_url in zip(
                before.images, after.images, strict=True
            )
        ),
        "badge_replace_remote_edited",
    )


def _verify_replacement(
    *,
    current: dict[str, object],
    original: dict[str, object],
    replacement_urls: tuple[str, str, str, str, str],
) -> None:
    _same_original({**current, "content": original["content"]}, original)
    original_content, current_content = original.get("content"), current.get("content")
    require(
        isinstance(original_content, str) and isinstance(current_content, str),
        "badge_replace_remote_article_invalid",
    )
    assert isinstance(original_content, str) and isinstance(current_content, str)
    before, after = HtmlProjection(original_content), HtmlProjection(current_content)
    require(
        before.normalized_text == after.normalized_text
        and before.links == after.links
        and before.topology == after.topology,
        "badge_replace_readback_drift",
    )
    require(
        len(before.images) == len(after.images) == 7 and len(set(after.images)) == 7,
        "badge_replace_media_topology_changed",
    )
    require(
        _same_wechat_cdn_display_variant(before.images[0], after.images[0])
        and _same_wechat_cdn_display_variant(before.images[-1], after.images[-1])
        and all(
            _same_wechat_cdn_display_variant(expected, actual)
            for expected, actual in zip(
                replacement_urls, after.images[1:6], strict=True
            )
        )
        and all(
            not _same_wechat_cdn_display_variant(old, new)
            for old, new in zip(before.images[1:6], after.images[1:6], strict=True)
        ),
        "badge_replace_readback_media_mismatch",
    )


def _rewrite_body(
    *,
    original_html: str,
    original_urls: tuple[str, ...],
    replacement_urls: tuple[str, str, str, str, str],
) -> str:
    require(
        tuple(HtmlProjection(original_html).images) == original_urls
        and len(original_urls) == 7
        and len(set(original_urls)) == 7,
        "badge_replace_media_topology_changed",
    )
    rewritten = original_html
    for original, replacement in zip(original_urls[1:6], replacement_urls, strict=True):
        escaped = strict_escaped_upload_url(replacement)
        seen = 0
        for attribute in ("src", "data-src"):
            for quote in ('"', "'"):
                old = f"{attribute}={quote}{original}{quote}"
                count = rewritten.count(old)
                require(count <= 1, "badge_replace_remote_image_duplicate")
                if count:
                    rewritten = rewritten.replace(
                        old, f"{attribute}={quote}{escaped}{quote}", 1
                    )
                    seen += 1
        require(seen in {1, 2}, "badge_replace_remote_image_missing")
    expected = (original_urls[0], *replacement_urls, original_urls[-1])
    require(
        tuple(HtmlProjection(rewritten).images) == expected,
        "badge_replace_rewrite_invalid",
    )
    return rewritten


def _replacement_article(
    *, original: dict[str, object], rewritten_html: str
) -> WeChatDraftArticleRequest:
    fields = _article_fields(original)
    article = WeChatDraftArticleRequest(
        title=cast(str, fields["title"]),
        author=cast(str, fields["author"]),
        digest=cast(str, fields["digest"]),
        content=rewritten_html,
        content_source_url=(
            cast(str, fields["content_source_url"])
            if fields["content_source_url"]
            else None
        ),
        thumb_media_id=_safe_media_id(fields["thumb_media_id"]),
        need_open_comment=bool(fields["need_open_comment"]),
        only_fans_can_comment=bool(fields["only_fans_can_comment"]),
    )
    _validate_draft_article(article)
    return article


def _require_existing_journal_root(*, root: Path) -> None:
    directory = root / "manual-v1" / ACCOUNT
    try:
        info = directory.stat(follow_symlinks=False)
        lock_info = (directory / "lock").stat(follow_symlinks=False)
    except OSError as error:
        raise OperatorError("badge_replace_journal_missing") from error
    require(
        stat.S_ISDIR(info.st_mode)
        and not directory.is_symlink()
        and stat.S_ISREG(lock_info.st_mode)
        and not (directory / "lock").is_symlink(),
        "badge_replace_journal_missing",
    )


def _read_required(journal: Journal, name: str, code: str) -> dict[str, Any]:
    value = journal.read(name)
    require(isinstance(value, dict), code)
    return cast(dict[str, Any], value)


def _load_original_binding(
    journal: Journal,
) -> tuple[str, dict[str, object], dict[str, Any]]:
    auth = _read_required(
        journal,
        f"{BACKFILL_PREFIX}-authorization.json",
        "badge_replace_backfill_binding_invalid",
    )
    binding = auth.get("binding")
    require(
        set(auth) == {"binding", "authorized_at", "expires_at"}
        and isinstance(binding, dict),
        "badge_replace_backfill_binding_invalid",
    )
    assert isinstance(binding, dict)
    require(
        binding.get("version") == BACKFILL_VERSION
        and binding.get("account") == ACCOUNT
        and binding.get("business_date") == BUSINESS_DATE
        and binding.get("edition_id") == str(EDITION)
        and all(
            _uuid(binding.get(key))
            for key in ("run_id", "article_id", "render_id", "event_id")
        )
        and _hex64(binding.get("source_identity"))
        and _hex64(binding.get("fallback_article_fingerprint"))
        and _hex64(binding.get("fallback_content_fingerprint"))
        and binding.get("max_visual_calls") == MAX_INLINE_UPLOADS
        and binding.get("all_or_nothing") is True
        and binding.get("draft_only") is True,
        "badge_replace_backfill_binding_invalid",
    )

    readback = _read_required(
        journal,
        f"{BACKFILL_PREFIX}-readback.json",
        "badge_replace_original_readback_invalid",
    )
    add_name = f"single-{EDITION.hex}-add-1"
    add_intent = _read_required(
        journal, add_name + "-intent.json", "badge_replace_original_receipt_invalid"
    )
    add_ack = _read_required(
        journal, add_name + "-ack.json", "badge_replace_original_receipt_invalid"
    )
    require(
        journal.read(add_name + "-not-applied.json") is None
        and set(add_intent) == {"binding", "step", "attempt", "request"}
        and add_intent.get("step") == "add"
        and add_intent.get("attempt") == 1
        and isinstance(add_intent.get("request"), dict)
        and set(add_ack) == {"intent_sha256", "value"}
        and add_ack.get("intent_sha256") == _sha(add_intent),
        "badge_replace_original_receipt_invalid",
    )
    request = cast(dict[str, object], add_intent["request"])
    media_id = _safe_media_id(add_ack.get("value"))
    require(
        readback.get("version") == BACKFILL_VERSION
        and readback.get("authorization_fingerprint") == _sha(auth)
        and readback.get("receipt_fingerprint") == sha256(media_id.encode()).hexdigest()
        and readback.get("article_fingerprint")
        == binding["fallback_article_fingerprint"]
        and _hex64(readback.get("content_fingerprint"))
        and readback.get("request_fingerprint") == _sha(request)
        and readback.get("verified") is True
        and readback.get("not_published") is True,
        "badge_replace_original_readback_invalid",
    )
    expected_delivery_binding = _sha(
        {
            "edition": str(EDITION),
            "article": readback["article_fingerprint"],
            "content": readback["content_fingerprint"],
            "account": ACCOUNT,
            "policy": "single-write-journal-v1",
            "max_attempts": 1,
        }
    )
    require(
        add_intent.get("binding") == expected_delivery_binding,
        "badge_replace_original_receipt_invalid",
    )
    claim = _read_required(
        journal,
        f"{readback['article_fingerprint']}-claim.json",
        "badge_replace_original_receipt_invalid",
    )
    require(
        claim
        == {
            "account": ACCOUNT,
            "binding": {
                "version": "single-edition-claim-v1",
                "raw_article": readback["article_fingerprint"],
                "edition_id": str(EDITION),
                "fingerprint": expected_delivery_binding,
            },
        },
        "badge_replace_original_receipt_invalid",
    )
    _replacement_article(original=request, rewritten_html=cast(str, request["content"]))
    return (
        media_id,
        request,
        {
            "backfill_authorization_sha256": _sha(auth),
            "original_add_intent_sha256": _sha(add_intent),
            "original_add_request_sha256": _sha(request),
            "target_draft_fingerprint": sha256(media_id.encode()).hexdigest(),
            "article_fingerprint": readback["article_fingerprint"],
            "content_fingerprint": readback["content_fingerprint"],
            "run_id": binding["run_id"],
            "article_id": binding["article_id"],
            "render_id": binding["render_id"],
            "event_id": binding["event_id"],
            "source_identity": binding["source_identity"],
        },
    )


async def _load_approved_candidates(
    journal: Journal,
    store: OfficialAccountGeneratedVisualStore,
    *,
    article_fingerprint: str,
) -> tuple[tuple[bytes, bytes, bytes, bytes, bytes], dict[str, Any]]:
    manifest = _read_required(
        journal,
        f"{BADGE_PREFIX}-manifest.json",
        "badge_replace_candidate_manifest_invalid",
    )
    selection = _read_required(
        journal,
        f"{BADGE_PREFIX}-selection.json",
        "badge_replace_candidate_selection_invalid",
    )
    slots = manifest.get("slots")
    require(
        manifest.get("version") == BADGE_VERSION
        and manifest.get("account") == ACCOUNT
        and manifest.get("business_date") == BUSINESS_DATE
        and manifest.get("edition_fingerprint")
        == sha256(str(EDITION).encode()).hexdigest()
        and manifest.get("article_fingerprint") == article_fingerprint
        and _hex64(manifest.get("target_identity"))
        and manifest.get("max_provider_calls") == MAX_INLINE_UPLOADS
        and manifest.get("one_call_per_slot") is True
        and manifest.get("generation_only") is True
        and isinstance(slots, list)
        and len(slots) == MAX_INLINE_UPLOADS
        and [item.get("ordinal") for item in slots if isinstance(item, dict)]
        == list(range(MAX_INLINE_UPLOADS)),
        "badge_replace_candidate_manifest_invalid",
    )
    expected_objects = [list(item) for item in APPROVED_OBJECTS]
    require(
        selection.get("version") == BADGE_VERSION
        and selection.get("manifest_sha256") == _sha(manifest)
        and selection.get("target_identity") == manifest["target_identity"]
        and selection.get("objects") == expected_objects
        and selection.get("requires_visual_inspection") is True
        and selection.get("generation_only") is True
        and isinstance(selection.get("result_sha256s"), list)
        and len(cast(list[object], selection["result_sha256s"])) == MAX_INLINE_UPLOADS,
        "badge_replace_candidate_selection_invalid",
    )

    bodies: list[bytes] = []
    result_hashes: list[list[object]] = []
    for approved, slot in zip(
        APPROVED_OBJECTS, cast(list[dict[str, Any]], slots), strict=True
    ):
        ordinal, media_type, byte_size, digest, width, height = approved
        require(
            isinstance(slot, dict)
            and slot.get("ordinal") == ordinal
            and _hex64(slot.get("logical_request_fingerprint"))
            and _hex64(slot.get("provider_request_fingerprint"))
            and _hex64(slot.get("prompt_sha256"))
            and _hex64(slot.get("reference_publication_checksum")),
            "badge_replace_candidate_manifest_invalid",
        )
        intent = _read_required(
            journal,
            f"{BADGE_PREFIX}-visual-{ordinal}-intent.json",
            "badge_replace_candidate_intent_invalid",
        )
        result = _read_required(
            journal,
            f"{BADGE_PREFIX}-visual-{ordinal}-result.json",
            "badge_replace_candidate_result_invalid",
        )
        require(
            intent.get("version") == BADGE_VERSION
            and intent.get("manifest_sha256") == _sha(manifest)
            and intent.get("ordinal") == ordinal
            and intent.get("logical_request_fingerprint")
            == slot["logical_request_fingerprint"]
            and intent.get("provider_request_fingerprint")
            == slot["provider_request_fingerprint"]
            and intent.get("prompt_sha256") == slot["prompt_sha256"]
            and intent.get("reference_publication_checksum")
            == slot["reference_publication_checksum"]
            and intent.get("maximum_calls") == 1,
            "badge_replace_candidate_intent_invalid",
        )
        require(
            set(result)
            == {
                "intent_sha256",
                "ordinal",
                "status",
                "media_type",
                "byte_size",
                "sha256",
                "width",
                "height",
                "provider_request_fingerprint",
            }
            and result.get("intent_sha256") == _sha(intent)
            and result.get("ordinal") == ordinal
            and result.get("status") == "ready"
            and (
                result.get("media_type"),
                result.get("byte_size"),
                result.get("sha256"),
                result.get("width"),
                result.get("height"),
            )
            == (media_type, byte_size, digest, width, height)
            and result.get("provider_request_fingerprint")
            == slot["provider_request_fingerprint"],
            "badge_replace_candidate_result_invalid",
        )
        result_hashes.append([ordinal, _sha(result)])
        body = await store.get_content_addressed_bytes(
            media_type=media_type, byte_size=byte_size, sha256=digest
        )
        require(
            len(body) == byte_size and sha256(body).hexdigest() == digest,
            "badge_replace_candidate_object_changed",
        )
        try:
            with Image.open(BytesIO(body)) as image:
                require(
                    image.format == "JPEG" and image.size == EXPECTED_IMAGE_SIZE,
                    "badge_replace_candidate_geometry_invalid",
                )
                image.verify()
        except OSError as error:
            raise OperatorError("badge_replace_candidate_geometry_invalid") from error
        bodies.append(body)
    require(
        selection["result_sha256s"] == result_hashes,
        "badge_replace_candidate_selection_invalid",
    )
    return (
        cast(tuple[bytes, bytes, bytes, bytes, bytes], tuple(bodies)),
        {
            "candidate_manifest_sha256": _sha(manifest),
            "candidate_selection_sha256": _sha(selection),
            "candidate_target_identity": manifest["target_identity"],
            "approved_object_sha256s": [item[3] for item in APPROVED_OBJECTS],
        },
    )


async def load_fixed_replacement(
    *, journal: Journal, store: OfficialAccountGeneratedVisualStore
) -> FixedReplacement:
    media_id, original, original_binding = _load_original_binding(journal)
    bodies, candidate_binding = await _load_approved_candidates(
        journal,
        store,
        article_fingerprint=cast(str, original_binding["article_fingerprint"]),
    )
    binding = {
        "version": OPERATION_VERSION,
        "account": ACCOUNT,
        "business_date": BUSINESS_DATE,
        "edition_id": str(EDITION),
        **original_binding,
        **candidate_binding,
        "inline_uploads": MAX_INLINE_UPLOADS,
        "same_draft_update": True,
        "draft_only": True,
    }
    return FixedReplacement(media_id, original, bodies, binding)


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
        require(old == payload, "badge_replace_receipt_changed")


def _upload_names(ordinal: int) -> tuple[str, str]:
    require(0 <= ordinal < MAX_INLINE_UPLOADS, "badge_replace_ordinal_invalid")
    stem = f"{REPLACEMENT_PREFIX}-upload-{ordinal}"
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
            "filename": f"badge-visual-{ordinal + 1}.jpg",
        },
    )


def _acknowledged_url(*, intent: dict[str, Any], ack: dict[str, Any] | None) -> str:
    require(
        isinstance(ack, dict)
        and set(ack) == {"intent_sha256", "value"}
        and ack.get("intent_sha256") == _sha(intent)
        and isinstance(ack.get("value"), dict),
        "badge_replace_upload_ack_changed",
    )
    assert isinstance(ack, dict)
    value = cast(dict[str, object], ack["value"])
    require(set(value) == {"url"}, "badge_replace_upload_ack_changed")
    return _strict_wechat_cdn_upload_url(value.get("url"))


async def _upload_once(
    *,
    journal: Journal,
    remote: RemoteDraft,
    target: FixedReplacement,
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
        require(old == intent, "badge_replace_upload_intent_changed")
        if ack is None:
            raise OperatorError("badge_replace_upload_outcome_unknown")
        return _acknowledged_url(intent=intent, ack=ack)
    require(ack is None, "badge_replace_upload_ack_without_intent")
    current = await remote.get(target.media_id)
    _same_original(current, target.original_article)
    journal.write(intent_name, intent)
    try:
        url = await remote.upload(
            body=body, filename=cast(str, intent["request"]["filename"])
        )
        url = _strict_wechat_cdn_upload_url(url)
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        raise
    except Exception as error:
        raise OperatorError("badge_replace_upload_outcome_unknown") from error
    journal.write(
        ack_name,
        {"intent_sha256": _sha(intent), "value": {"url": url}},
    )
    return url


def _load_all_upload_acks(
    *, journal: Journal, target: FixedReplacement, binding_sha256: str
) -> tuple[str, str, str, str, str]:
    urls: list[str] = []
    for ordinal, body in enumerate(target.bodies):
        intent_name, ack_name = _upload_names(ordinal)
        intent = _expected_upload_intent(
            binding_sha256=binding_sha256, ordinal=ordinal, body=body
        )
        require(
            journal.read(intent_name) == intent,
            "badge_replace_update_without_uploads",
        )
        urls.append(_acknowledged_url(intent=intent, ack=journal.read(ack_name)))
    require(len(set(urls)) == MAX_INLINE_UPLOADS, "badge_replace_upload_urls_invalid")
    return cast(tuple[str, str, str, str, str], tuple(urls))


def _inspect_upload_receipts(
    *, journal: Journal, target: FixedReplacement, binding_sha256: str
) -> int:
    completed = 0
    for ordinal, body in enumerate(target.bodies):
        intent_name, ack_name = _upload_names(ordinal)
        expected = _expected_upload_intent(
            binding_sha256=binding_sha256, ordinal=ordinal, body=body
        )
        intent, ack = journal.read(intent_name), journal.read(ack_name)
        if intent is None:
            require(ack is None, "badge_replace_upload_ack_without_intent")
            continue
        require(intent == expected, "badge_replace_upload_intent_changed")
        if ack is None:
            raise OperatorError("badge_replace_upload_outcome_unknown")
        _acknowledged_url(intent=expected, ack=ack)
        completed += 1
    return completed


def _update_names() -> tuple[str, str, str]:
    stem = f"{REPLACEMENT_PREFIX}-draft-update"
    return stem + "-intent.json", stem + "-ack.json", stem + "-readback.json"


def _expected_update_intent(
    *,
    binding_sha256: str,
    article: WeChatDraftArticleRequest,
    replacement_urls: tuple[str, str, str, str, str],
) -> dict[str, Any]:
    return _effect_intent(
        binding_sha256=binding_sha256,
        step="same-draft-update",
        request={
            "replacement_urls": list(replacement_urls),
            "article_request_sha256": _sha(asdict(article)),
        },
    )


def _validate_update_ack(*, intent: dict[str, Any], ack: dict[str, Any] | None) -> bool:
    if ack is None:
        return False
    require(
        ack
        == {
            "intent_sha256": _sha(intent),
            "value": {"acknowledged": True, "not_published": True},
        },
        "badge_replace_update_ack_changed",
    )
    return True


def _readback_receipt(
    *, binding_sha256: str, update_intent: dict[str, Any], resolution: str
) -> dict[str, Any]:
    require(
        resolution in {"acknowledged", "readback_after_unknown"},
        "badge_replace_readback_invalid",
    )
    return {
        "version": OPERATION_VERSION,
        "binding_sha256": binding_sha256,
        "update_intent_sha256": _sha(update_intent),
        "resolution": resolution,
        "verified": True,
        "not_published": True,
    }


async def _reconcile_existing_update(
    *,
    mode: str,
    journal: Journal,
    remote: RemoteDraft,
    target: FixedReplacement,
    binding_sha256: str,
    current: dict[str, object],
) -> dict[str, object]:
    intent_name, ack_name, readback_name = _update_names()
    intent = _read_required(journal, intent_name, "badge_replace_update_intent_invalid")
    replacement_urls = _load_all_upload_acks(
        journal=journal, target=target, binding_sha256=binding_sha256
    )
    content = target.original_article.get("content")
    require(isinstance(content, str), "badge_replace_original_receipt_invalid")
    assert isinstance(content, str)
    original_urls = tuple(HtmlProjection(content).images)
    article = _replacement_article(
        original=target.original_article,
        rewritten_html=_rewrite_body(
            original_html=content,
            original_urls=original_urls,
            replacement_urls=replacement_urls,
        ),
    )
    expected_intent = _expected_update_intent(
        binding_sha256=binding_sha256,
        article=article,
        replacement_urls=replacement_urls,
    )
    require(intent == expected_intent, "badge_replace_update_intent_changed")
    acknowledged = _validate_update_ack(intent=intent, ack=journal.read(ack_name))
    try:
        _verify_replacement(
            current=current,
            original=target.original_article,
            replacement_urls=replacement_urls,
        )
    except OperatorError:
        if acknowledged:
            raise
        return {
            "status": "outcome_unknown_reconcile_only",
            "images": MAX_INLINE_UPLOADS,
            "external_writes": 0,
            "not_published": True,
        }
    resolution = "acknowledged" if acknowledged else "readback_after_unknown"
    receipt = _readback_receipt(
        binding_sha256=binding_sha256,
        update_intent=intent,
        resolution=resolution,
    )
    old_readback = journal.read(readback_name)
    if old_readback is not None:
        require(old_readback == receipt, "badge_replace_readback_changed")
    elif mode != "plan":
        journal.write(readback_name, receipt)
    return {
        "status": (
            "readback_verified" if acknowledged else "readback_verified_after_unknown"
        ),
        "images": MAX_INLINE_UPLOADS,
        "external_writes": 0,
        "readback_verified": True,
        "not_published": True,
    }


async def replace_badge_visuals(
    *,
    mode: str,
    journal: Journal,
    store: OfficialAccountGeneratedVisualStore,
    remote: RemoteDraft,
) -> dict[str, object]:
    """Run the bounded plan/apply/reconcile state machine."""

    require(mode in {"plan", "replace", "reconcile"}, "badge_replace_mode_invalid")
    target = await load_fixed_replacement(journal=journal, store=store)
    claim_name = f"{REPLACEMENT_PREFIX}-claim.json"
    update_intent_name, update_ack_name, _readback_name = _update_names()
    current = await remote.get(target.media_id)
    existing_update = journal.read(update_intent_name)
    require(
        journal.read(update_ack_name) is None or existing_update is not None,
        "badge_replace_update_ack_without_intent",
    )
    claim = journal.read(claim_name)
    if claim is None:
        orphaned_upload_receipt = any(
            journal.read(name) is not None
            for ordinal in range(MAX_INLINE_UPLOADS)
            for name in _upload_names(ordinal)
        )
        require(
            existing_update is None and not orphaned_upload_receipt,
            "badge_replace_update_without_claim",
        )
        _same_original(current, target.original_article)
        frozen_original = current
        operation_binding = {
            **target.binding,
            "original_remote_sha256": _sha(frozen_original),
        }
        expected_claim = {
            "version": OPERATION_VERSION,
            "binding": operation_binding,
            "original_article": frozen_original,
        }
        if mode == "replace":
            journal.write(claim_name, expected_claim)
    else:
        require(
            set(claim) == {"version", "binding", "original_article"}
            and claim.get("version") == OPERATION_VERSION
            and isinstance(claim.get("binding"), dict)
            and isinstance(claim.get("original_article"), dict),
            "badge_replace_claim_changed",
        )
        frozen_original = cast(dict[str, object], claim["original_article"])
        _same_original(frozen_original, target.original_article)
        operation_binding = {
            **target.binding,
            "original_remote_sha256": _sha(frozen_original),
        }
        expected_claim = {
            "version": OPERATION_VERSION,
            "binding": operation_binding,
            "original_article": frozen_original,
        }
        require(claim == expected_claim, "badge_replace_claim_changed")
    effect_target = FixedReplacement(
        media_id=target.media_id,
        original_article=frozen_original,
        bodies=target.bodies,
        binding=operation_binding,
    )
    binding_sha256 = _sha(operation_binding)
    if existing_update is not None:
        return await _reconcile_existing_update(
            mode=mode,
            journal=journal,
            remote=remote,
            target=effect_target,
            binding_sha256=binding_sha256,
            current=current,
        )

    _same_original(current, effect_target.original_article)
    completed_uploads = _inspect_upload_receipts(
        journal=journal,
        target=effect_target,
        binding_sha256=binding_sha256,
    )
    content = effect_target.original_article.get("content")
    require(isinstance(content, str), "badge_replace_original_receipt_invalid")
    assert isinstance(content, str)
    original_urls = tuple(HtmlProjection(content).images)
    require(
        len(original_urls) == 7 and len(set(original_urls)) == 7,
        "badge_replace_media_topology_changed",
    )
    if mode == "plan":
        return {
            "status": "planned",
            "images": MAX_INLINE_UPLOADS,
            "external_writes": 0,
            "completed_uploads": completed_uploads,
            "same_draft": True,
            "not_published": True,
        }
    require(mode == "replace", "badge_replace_reconcile_without_update_intent")
    replacement_urls_list: list[str] = []
    external_writes = 0
    for ordinal, body in enumerate(target.bodies):
        intent_name, _ack_name = _upload_names(ordinal)
        was_new = journal.read(intent_name) is None
        replacement_urls_list.append(
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
    replacement_urls = cast(
        tuple[str, str, str, str, str], tuple(replacement_urls_list)
    )
    require(
        len(set(replacement_urls)) == MAX_INLINE_UPLOADS,
        "badge_replace_upload_urls_invalid",
    )

    current_before_update = await remote.get(target.media_id)
    _same_original(current_before_update, effect_target.original_article)
    article = _replacement_article(
        original=effect_target.original_article,
        rewritten_html=_rewrite_body(
            original_html=content,
            original_urls=original_urls,
            replacement_urls=replacement_urls,
        ),
    )
    update_intent = _expected_update_intent(
        binding_sha256=binding_sha256,
        article=article,
        replacement_urls=replacement_urls,
    )
    require(
        journal.read(update_intent_name) is None
        and journal.read(update_ack_name) is None,
        "badge_replace_update_receipt_invalid",
    )
    journal.write(update_intent_name, update_intent)
    try:
        await remote.update(media_id=target.media_id, article=article)
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        raise
    except Exception as error:
        raise OperatorError("badge_replace_update_outcome_unknown") from error
    external_writes += 1
    journal.write(
        update_ack_name,
        {
            "intent_sha256": _sha(update_intent),
            "value": {"acknowledged": True, "not_published": True},
        },
    )
    current_after_update = await remote.get(target.media_id)
    _verify_replacement(
        current=current_after_update,
        original=effect_target.original_article,
        replacement_urls=replacement_urls,
    )
    readback_name = _update_names()[2]
    _write_or_verify(
        journal,
        readback_name,
        _readback_receipt(
            binding_sha256=binding_sha256,
            update_intent=update_intent,
            resolution="acknowledged",
        ),
    )
    return {
        "status": "same_draft_updated",
        "images": MAX_INLINE_UPLOADS,
        "external_writes": external_writes,
        "readback_verified": True,
        "same_draft": True,
        "not_published": True,
    }


async def _main(command: str, apply: bool) -> dict[str, object]:
    from app.core.config import get_settings

    require(
        (command == "plan" and not apply)
        or (command == "replace" and apply)
        or (command == "reconcile" and not apply),
        "badge_replace_explicit_apply_required",
    )
    settings = get_settings()
    require(
        settings.wechat_mp_app_id is not None
        and wechat_draft_account_fingerprint(
            settings.wechat_mp_app_id.get_secret_value()
        )
        == ACCOUNT,
        "badge_replace_account_mismatch",
    )
    root = Path(settings.wechat_mp_draft_artifact_root)
    _require_existing_journal_root(root=root)
    journal = LocalManualDraftJournal(root, ACCOUNT)
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        client = WeChatOfficialAccountHttpClient(settings)
        return await replace_badge_visuals(
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
        "command", nargs="?", default="plan", choices=("plan", "replace", "reconcile")
    )
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        result = asyncio.run(_main(arguments.command, arguments.apply))
    except Exception as error:  # noqa: BLE001 - fixed, secret-free CLI boundary
        code = getattr(error, "code", None)
        if (
            not isinstance(code, str)
            or re.fullmatch(r"badge_replace_[a-z0-9_]{1,68}", code) is None
        ):
            code = "badge_replace_operator_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
