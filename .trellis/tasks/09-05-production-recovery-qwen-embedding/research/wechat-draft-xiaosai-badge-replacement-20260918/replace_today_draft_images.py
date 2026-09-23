"""Replace only the five generated body images in today's existing WeChat draft.

The operator is intentionally task-local and default-deny: it never creates a
draft, publishes, sends, changes SQL records, calls an LLM, or mutates the five
historical visual rows.  ``--plan`` is read-only.  ``--apply`` has one guarded
write path: five inline uploads followed by one same-ID ``draft/update``; an
ambiguous effect is reconciled only and is never replayed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import stat
from dataclasses import asdict
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
from app.core.config import get_settings
from app.domain.official_account_local import fingerprint
from app.domain.official_account_strict_layout import strict_escaped_upload_url
from app.domain.official_account_visual_pipeline import STRICT_VISUAL_POLICY
from app.domain.wechat_official_account_draft_jobs import (
    wechat_draft_account_fingerprint,
)
from app.infrastructure.db.models import OfficialAccountSingleEditionModel
from app.infrastructure.db.session import create_engine, create_session_factory
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
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

RUN_ID = UUID("e5b84bfa-4cd1-4392-bf81-42dbc485e089")
OPERATION_VERSION = "xiaosai-ai-badge-same-draft-update-v1"
EXPECTED_IMAGE_SIZE = (1536, 1024)
SOURCE_IMAGE_COUNT = 7
_WECHAT_IMAGE_CDN_HOSTS = frozenset({"mmbiz.qpic.cn", "mmecoa.qpic.cn"})


def require(condition: object, code: str = "xiaosai_replace_invalid") -> None:
    if not condition:
        raise ValueError(code)


def _safe_media_id(value: object) -> str:
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None,
        "xiaosai_replace_media_id_invalid",
    )
    assert isinstance(value, str)
    return value


def _strict_wechat_cdn_upload_url(value: object) -> str:
    """Normalize only the inline-image CDN URLs WeChat is allowed to return."""

    require(
        isinstance(value, str)
        and value
        and len(value) <= 2048
        and not any(
            character.isspace() or ord(character) < 32 or 127 <= ord(character) <= 159
            for character in value
        )
        and not any(character in value for character in "\"'<>"),
        "xiaosai_replace_upload_url_invalid",
    )
    assert isinstance(value, str)
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("xiaosai_replace_upload_url_invalid") from error
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
        "xiaosai_replace_upload_url_invalid",
    )
    hostname = parsed.hostname
    assert hostname is not None
    return parsed._replace(scheme="https", netloc=hostname.casefold()).geturl()


class VisibleHtml(HTMLParser):
    """The narrow readback comparison: prose/links/image order, no CSS normalization."""

    def __init__(self, value: str) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.images: list[str] = []
        self.links: list[str | None] = []
        self.feed(value)
        self.close()

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        require(
            len({key for key, _value in attrs}) == len(attrs),
            "xiaosai_replace_remote_duplicate_attribute",
        )
        fields = dict(attrs)
        if tag == "img":
            src, data_src = fields.get("src"), fields.get("data-src")
            require(
                (src is not None or data_src is not None)
                and (src is None or data_src is None or src == data_src)
                and isinstance(src if src is not None else data_src, str),
                "xiaosai_replace_remote_image_conflict",
            )
            value = src if src is not None else data_src
            assert isinstance(value, str)
            self.images.append(value)
        if tag == "a":
            self.links.append(fields.get("href"))

    def identity(self) -> tuple[str, tuple[str, ...], tuple[str | None, ...]]:
        return (
            " ".join("".join(self.text).split()),
            tuple(self.images),
            tuple(self.links),
        )


def _response_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        require(key not in value, "xiaosai_replace_response_duplicate_key")
        value[key] = item
    return value


def _invalid_constant(_value: str) -> None:
    raise ValueError("xiaosai_replace_response_invalid_constant")


class Remote:
    """Only the four endpoints required for same-draft media replacement."""

    def __init__(self, client: WeChatOfficialAccountHttpClient) -> None:
        self.client = client

    async def token(self) -> str:
        value = (await self.client._get_access_token()).value
        require(isinstance(value, str), "xiaosai_replace_token_invalid")
        assert isinstance(value, str)
        return value

    async def post(
        self,
        path: str,
        token: str,
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
            "xiaosai_replace_endpoint_forbidden",
        )
        try:
            async with asyncio.timeout(self.client._total_timeout_seconds):
                async with self.client._client.stream(
                    "POST",
                    self.client._base_url + path,
                    params={"access_token": token},
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
                        "xiaosai_replace_response_not_acknowledged",
                    )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        require(size <= limit, "xiaosai_replace_response_too_large")
                        chunks.append(chunk)
        except asyncio.CancelledError:
            raise
        except (
            Exception
        ) as error:  # effect callers convert this to an unknown journal fence
            raise ValueError("xiaosai_replace_transport_failed") from error
        decoded = json.loads(
            b"".join(chunks),
            object_pairs_hook=_response_object,
            parse_constant=_invalid_constant,
        )
        require(isinstance(decoded, dict), "xiaosai_replace_response_invalid")
        value = cast(dict[str, object], decoded)
        require(
            "errcode" not in value
            or (type(value["errcode"]) is int and value["errcode"] == 0),
            "xiaosai_replace_response_not_acknowledged",
        )
        return value

    async def get(self, media_id: str) -> dict[str, object]:
        value = await self.post(
            "/cgi-bin/draft/get",
            await self.token(),
            payload={"media_id": media_id},
            limit=1_048_576,
        )
        items = value.get("news_item")
        require(
            isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict),
            "xiaosai_replace_remote_article_invalid",
        )
        assert isinstance(items, list) and isinstance(items[0], dict)
        return dict(items[0])

    async def upload(self, *, body: bytes, filename: str, token: str) -> str:
        value = await self.post(
            "/cgi-bin/media/uploadimg",
            token,
            files={"media": (filename, body, "image/jpeg")},
        )
        url = _strict_wechat_cdn_upload_url(value.get("url"))
        strict_escaped_upload_url(url)
        return url

    async def update(
        self, *, media_id: str, article: WeChatDraftArticleRequest, token: str
    ) -> None:
        payload = asdict(article)
        payload.update(
            article_type="news",
            need_open_comment=int(article.need_open_comment),
            only_fans_can_comment=int(article.only_fans_can_comment),
        )
        value = await self.post(
            "/cgi-bin/draft/update",
            token,
            payload={"media_id": media_id, "index": 0, "articles": payload},
        )
        require(
            type(value.get("errcode")) is int and value["errcode"] == 0,
            "xiaosai_replace_update_outcome_unknown",
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
        ),
        "xiaosai_replace_remote_article_invalid",
    )
    require(
        fields["content_source_url"] is None
        or isinstance(fields["content_source_url"], str),
        "xiaosai_replace_remote_article_invalid",
    )
    for key in ("need_open_comment", "only_fans_can_comment"):
        require(fields[key] in {None, 0, 1}, "xiaosai_replace_remote_article_invalid")
    return fields


def _same_original(current: dict[str, object], expected: dict[str, object]) -> None:
    current_fields, expected_fields = (
        _article_fields(current),
        _article_fields(expected),
    )
    for key in ("title", "author", "digest", "thumb_media_id"):
        require(
            current_fields[key] == expected_fields[key], "xiaosai_replace_remote_edited"
        )
    for key in ("need_open_comment", "only_fans_can_comment", "content_source_url"):
        require(
            (current_fields[key] or 0) == (expected_fields[key] or 0),
            "xiaosai_replace_remote_edited",
        )
    current_html, expected_html = current_fields["content"], expected_fields["content"]
    assert isinstance(current_html, str) and isinstance(expected_html, str)
    current_visible, expected_visible = (
        VisibleHtml(current_html).identity(),
        VisibleHtml(expected_html).identity(),
    )
    require(
        current_visible[0] == expected_visible[0]
        and current_visible[2] == expected_visible[2]
        and len(current_visible[1]) == len(expected_visible[1])
        and all(
            _same_wechat_cdn_display_variant(expected_url, current_url)
            for expected_url, current_url in zip(
                expected_visible[1], current_visible[1], strict=True
            )
        ),
        "xiaosai_replace_remote_edited",
    )


def _same_wechat_cdn_display_variant(expected: str, actual: str) -> bool:
    """Allow only WeChat's documented http(s) + terminal ``/0``/``/640`` rewrite."""

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


def _verify_replacement(
    *,
    current: dict[str, object],
    original: dict[str, object],
    replacement_urls: tuple[str, ...],
) -> None:
    _same_original({**current, "content": original["content"]}, original)
    original_fields, current_fields = (
        _article_fields(original),
        _article_fields(current),
    )
    original_html, current_html = original_fields["content"], current_fields["content"]
    assert isinstance(original_html, str) and isinstance(current_html, str)
    before, after = (
        VisibleHtml(original_html).identity(),
        VisibleHtml(current_html).identity(),
    )
    require(
        before[0] == after[0] and before[2] == after[2],
        "xiaosai_replace_readback_drift",
    )
    require(
        len(before[1]) == 7 and len(after[1]) == 7,
        "xiaosai_replace_media_topology_changed",
    )
    require(
        after[1][0] == before[1][0]
        and after[1][-1] == before[1][-1]
        and all(
            _same_wechat_cdn_display_variant(expected, actual)
            for expected, actual in zip(replacement_urls, after[1][1:6], strict=True)
        ),
        "xiaosai_replace_readback_media_mismatch",
    )


def _rewrite_body(
    *,
    original_html: str,
    original_urls: tuple[str, ...],
    replacement_html_urls: tuple[str, ...],
    replacement_readback_urls: tuple[str, ...],
) -> str:
    parsed = VisibleHtml(original_html)
    require(
        tuple(parsed.images) == original_urls and len(original_urls) == 7,
        "xiaosai_replace_media_topology_changed",
    )
    rewritten = original_html
    for original, replacement in zip(
        original_urls[1:6], replacement_html_urls, strict=True
    ):
        seen = 0
        for attribute in ("src", "data-src"):
            for quote in ('"', "'"):
                old = f"{attribute}={quote}{original}{quote}"
                new = f"{attribute}={quote}{replacement}{quote}"
                count = rewritten.count(old)
                require(count <= 1, "xiaosai_replace_remote_image_duplicate")
                if count:
                    rewritten = rewritten.replace(old, new, 1)
                    seen += 1
        require(seen in {1, 2}, "xiaosai_replace_remote_image_missing")
    expected = (original_urls[0], *replacement_readback_urls, original_urls[-1])
    require(
        tuple(VisibleHtml(rewritten).images) == expected,
        "xiaosai_replace_rewrite_invalid",
    )
    return rewritten


def _read_json(path: Path, code: str) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), code)
    try:
        decoded = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(code) from error
    require(isinstance(decoded, dict), code)
    return cast(dict[str, object], decoded)


def _load_candidates(directory: Path) -> tuple[bytes, ...]:
    require(
        directory.is_dir() and not directory.is_symlink(),
        "xiaosai_replace_candidate_directory",
    )
    bodies: list[bytes] = []
    for ordinal in range(5):
        image_path = directory / f"candidate-{ordinal}.jpg"
        info = image_path.stat(follow_symlinks=False)
        require(
            stat.S_ISREG(info.st_mode)
            and not image_path.is_symlink()
            and 0 < info.st_size <= 10 * 1024 * 1024,
            "xiaosai_replace_candidate_file",
        )
        body = image_path.read_bytes()
        metadata = _read_json(
            directory / f"candidate-{ordinal}.json",
            "xiaosai_replace_candidate_metadata",
        )
        require(
            metadata.get("ordinal") == ordinal
            and metadata.get("provider_model") == STRICT_VISUAL_POLICY.generation_model
            and metadata.get("publication_dimensions") == list(EXPECTED_IMAGE_SIZE)
            and metadata.get("publication_sha256") == sha256(body).hexdigest(),
            "xiaosai_replace_candidate_metadata",
        )
        audit = metadata.get("audit")
        if ordinal == 0 and isinstance(audit, dict) and audit.get("available") is False:
            audit = _read_json(
                directory / "candidate-0.audit.json", "xiaosai_replace_candidate_audit"
            )
        require(
            isinstance(audit, dict)
            and audit.get("available") is True
            and audit.get("accepted") is True
            and audit.get("issues") == []
            and audit.get("model") == STRICT_VISUAL_POLICY.audit_model,
            "xiaosai_replace_candidate_audit",
        )
        try:
            with Image.open(image_path) as image:
                require(
                    image.format == "JPEG" and image.size == EXPECTED_IMAGE_SIZE,
                    "xiaosai_replace_candidate_geometry",
                )
        except OSError as error:
            raise ValueError("xiaosai_replace_candidate_geometry") from error
        bodies.append(body)
    return tuple(bodies)


async def _load_edition() -> tuple[OfficialAccountSingleEditionModel, str]:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        sessions = create_session_factory(engine)
        async with sessions() as session:
            result = await session.execute(
                select(OfficialAccountSingleEditionModel).where(
                    OfficialAccountSingleEditionModel.article_run_id == RUN_ID
                )
            )
            rows = tuple(result.scalars())
        require(len(rows) == 1, "xiaosai_replace_edition_missing")
        edition = rows[0]
        require(
            edition.status == "delivered"
            and edition.lease_token is None
            and edition.lease_expires_at is None
            and edition.article_fingerprint is not None
            and edition.content_fingerprint is not None
            and edition.receipt_fingerprint is not None,
            "xiaosai_replace_edition_state",
        )
        app_id = settings.wechat_mp_app_id
        require(
            app_id is not None
            and wechat_draft_account_fingerprint(app_id.get_secret_value())
            == edition.account_fingerprint,
            "xiaosai_replace_account_mismatch",
        )
        return edition, settings.wechat_mp_draft_artifact_root
    finally:
        await engine.dispose()


def _load_target(
    *, journal: LocalManualDraftJournal, edition: OfficialAccountSingleEditionModel
) -> tuple[str, dict[str, object]]:
    name = f"single-{edition.id.hex}-add-1"
    intent, ack = journal.read(name + "-intent.json"), journal.read(name + "-ack.json")
    require(
        isinstance(intent, dict)
        and isinstance(ack, dict)
        and ack.get("intent_sha256") == journal_fingerprint(intent)
        and journal.read(name + "-not-applied.json") is None,
        "xiaosai_replace_original_receipt_invalid",
    )
    media_id = _safe_media_id(ack.get("value"))
    require(
        sha256(media_id.encode()).hexdigest() == edition.receipt_fingerprint,
        "xiaosai_replace_original_receipt_invalid",
    )
    return media_id, intent


def _require_existing_journal_root(*, root: str, account: str) -> None:
    """Keep every mode, including ``plan``, from creating journal state."""

    directory = Path(root) / "manual-v1" / account
    try:
        info = directory.stat(follow_symlinks=False)
        lock = directory / "lock"
        lock_info = lock.stat(follow_symlinks=False)
    except OSError as error:
        raise ValueError("xiaosai_replace_journal_missing") from error
    require(
        stat.S_ISDIR(info.st_mode)
        and not directory.is_symlink()
        and stat.S_ISREG(lock_info.st_mode)
        and not lock.is_symlink(),
        "xiaosai_replace_journal_missing",
    )


def _binding(
    *,
    edition: OfficialAccountSingleEditionModel,
    media_id: str,
    bodies: tuple[bytes, ...],
) -> dict[str, object]:
    return {
        "version": OPERATION_VERSION,
        "run_id": str(RUN_ID),
        "edition_id": str(edition.id),
        "account": edition.account_fingerprint,
        "target_draft_fingerprint": sha256(media_id.encode()).hexdigest(),
        "article_fingerprint": edition.article_fingerprint,
        "content_fingerprint": edition.content_fingerprint,
        "replacement_sha256": [sha256(body).hexdigest() for body in bodies],
    }


def _claim(
    journal: LocalManualDraftJournal, *, prefix: str, binding: dict[str, object]
) -> None:
    name = prefix + "-claim.json"
    prior = journal.read(name)
    if prior is None:
        journal.write(name, {"binding": binding})
    else:
        require(prior == {"binding": binding}, "xiaosai_replace_claim_changed")


async def _once(
    *,
    journal: LocalManualDraftJournal,
    prefix: str,
    step: str,
    binding: dict[str, object],
    request: dict[str, object],
    send: Any,
) -> dict[str, object]:
    name = f"{prefix}-{step}"
    intent = {"binding": binding, "step": step, "request": request}
    prior, ack = journal.read(name + "-intent.json"), journal.read(name + "-ack.json")
    if prior is not None:
        require(prior == intent, "xiaosai_replace_intent_changed")
        if ack is None:
            raise ValueError("xiaosai_replace_outcome_unknown")
        require(
            ack.get("intent_sha256") == journal_fingerprint(intent),
            "xiaosai_replace_ack_changed",
        )
        value = ack.get("value")
        require(isinstance(value, dict), "xiaosai_replace_ack_changed")
        return dict(value)
    require(ack is None, "xiaosai_replace_ack_without_intent")
    journal.write(name + "-intent.json", intent)
    try:
        value = await send()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise ValueError("xiaosai_replace_outcome_unknown") from error
    require(isinstance(value, dict), "xiaosai_replace_ack_changed")
    journal.write(
        name + "-ack.json",
        {"intent_sha256": journal_fingerprint(intent), "value": value},
    )
    return dict(value)


def _replacement_article(
    *, original: dict[str, object], rewritten_html: str
) -> WeChatDraftArticleRequest:
    fields = _article_fields(original)
    article = WeChatDraftArticleRequest(
        title=str(fields["title"]),
        author=str(fields["author"]),
        digest=str(fields["digest"]),
        content=rewritten_html,
        content_source_url=(
            str(fields["content_source_url"]) if fields["content_source_url"] else None
        ),
        thumb_media_id=_safe_media_id(fields["thumb_media_id"]),
        need_open_comment=bool(fields["need_open_comment"]),
        only_fans_can_comment=bool(fields["only_fans_can_comment"]),
    )
    _validate_draft_article(article)
    return article


async def run(*, mode: str, candidate_directory: Path) -> dict[str, object]:
    require(mode in {"plan", "apply", "reconcile"}, "xiaosai_replace_mode_invalid")
    bodies = _load_candidates(candidate_directory)
    edition, root = await _load_edition()
    _require_existing_journal_root(root=root, account=edition.account_fingerprint)
    journal = LocalManualDraftJournal(Path(root), edition.account_fingerprint)
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        media_id, original_add_intent = _load_target(journal=journal, edition=edition)
        expected_initial_article = original_add_intent.get("request")
        require(
            isinstance(expected_initial_article, dict),
            "xiaosai_replace_original_receipt_invalid",
        )
        assert isinstance(expected_initial_article, dict)
        prefix = f"xiaosai-badge-{edition.id.hex}"
        binding = _binding(edition=edition, media_id=media_id, bodies=bodies)
        client = WeChatOfficialAccountHttpClient(get_settings())
        remote = Remote(client)
        original = await remote.get(media_id)
        update_name = prefix + "-draft-update"
        existing_update_intent = journal.read(update_name + "-intent.json")
        existing_update_ack = journal.read(update_name + "-ack.json")
        if existing_update_intent is None:
            _same_original(original, expected_initial_article)
        fields = _article_fields(original)
        content = fields["content"]
        assert isinstance(content, str)
        source_urls = tuple(VisibleHtml(content).images)
        require(
            len(source_urls) == SOURCE_IMAGE_COUNT
            and len(set(source_urls)) == SOURCE_IMAGE_COUNT,
            "xiaosai_replace_media_topology_changed",
        )
        if mode == "plan":
            return {
                "status": "planned",
                "images": 5,
                "target_draft_fingerprint": sha256(media_id.encode()).hexdigest(),
                "not_published": True,
            }
        replacement_urls: tuple[str, ...]
        if existing_update_intent is not None:
            require(
                existing_update_intent.get("binding") == binding,
                "xiaosai_replace_intent_changed",
            )
            replacement_urls_raw = (
                existing_update_intent.get("request", {}).get("replacement_urls")
                if isinstance(existing_update_intent.get("request"), dict)
                else None
            )
            require(
                isinstance(replacement_urls_raw, list)
                and len(replacement_urls_raw) == 5
                and all(isinstance(item, str) for item in replacement_urls_raw),
                "xiaosai_replace_intent_changed",
            )
            assert isinstance(replacement_urls_raw, list)
            replacement_urls = tuple(replacement_urls_raw)
            if existing_update_ack is None:
                stored_original = journal.read(prefix + "-original.json")
                require(
                    isinstance(stored_original, dict),
                    "xiaosai_replace_original_missing",
                )
                try:
                    _verify_replacement(
                        current=original,
                        original=stored_original,
                        replacement_urls=replacement_urls,
                    )
                except ValueError:
                    return {
                        "status": "outcome_unknown_reconcile_only",
                        "not_published": True,
                    }
                readback = {"binding": binding, "verified": True}
                prior_readback = journal.read(prefix + "-readback.json")
                if prior_readback is None:
                    journal.write(prefix + "-readback.json", readback)
                else:
                    require(
                        prior_readback == readback,
                        "xiaosai_replace_readback_changed",
                    )
                return {
                    "status": "readback_verified_after_unknown",
                    "not_published": True,
                }
            require(
                existing_update_ack.get("intent_sha256")
                == journal_fingerprint(existing_update_intent),
                "xiaosai_replace_ack_changed",
            )
            require(
                existing_update_ack.get("value")
                == {"acknowledged": True, "not_published": True},
                "xiaosai_replace_ack_changed",
            )
            _verify_replacement(
                current=original,
                original=journal.read(prefix + "-original.json") or {},
                replacement_urls=replacement_urls,
            )
            readback = {"binding": binding, "verified": True}
            prior_readback = journal.read(prefix + "-readback.json")
            if prior_readback is None:
                journal.write(prefix + "-readback.json", readback)
            else:
                require(prior_readback == readback, "xiaosai_replace_readback_changed")
            return {"status": "readback_verified", "not_published": True}
        require(mode == "apply", "xiaosai_replace_reconcile_without_intent")
        _claim(journal, prefix=prefix, binding=binding)
        stored_original = journal.read(prefix + "-original.json")
        if stored_original is None:
            journal.write(prefix + "-original.json", original)
        else:
            _same_original(stored_original, original)
        urls: list[str] = []
        for ordinal, body in enumerate(bodies):
            request = {"sha256": sha256(body).hexdigest(), "ordinal": ordinal}

            async def upload(
                body: bytes = body, ordinal: int = ordinal
            ) -> dict[str, object]:
                return {
                    "url": await remote.upload(
                        body=body,
                        filename=f"candidate-{ordinal}.jpg",
                        token=await remote.token(),
                    )
                }

            acknowledged = await _once(
                journal=journal,
                prefix=prefix,
                step=f"upload-{ordinal}",
                binding=binding,
                request=request,
                send=upload,
            )
            url = acknowledged.get("url")
            strict_escaped_upload_url(url)
            assert isinstance(url, str)
            urls.append(url)
        replacement_urls = tuple(urls)
        original_again = await remote.get(media_id)
        _same_original(original_again, original)
        rewritten_html = _rewrite_body(
            original_html=content,
            original_urls=source_urls,
            replacement_html_urls=tuple(
                strict_escaped_upload_url(url) for url in replacement_urls
            ),
            replacement_readback_urls=replacement_urls,
        )
        article = _replacement_article(original=original, rewritten_html=rewritten_html)

        async def update() -> dict[str, object]:
            await remote.update(
                media_id=media_id, article=article, token=await remote.token()
            )
            return {"acknowledged": True, "not_published": True}

        await _once(
            journal=journal,
            prefix=prefix,
            step="draft-update",
            binding=binding,
            request={
                "replacement_urls": list(replacement_urls),
                "request_fingerprint": fingerprint(asdict(article)),
            },
            send=update,
        )
        current = await remote.get(media_id)
        _verify_replacement(
            current=current, original=original, replacement_urls=replacement_urls
        )
        journal.write(prefix + "-readback.json", {"binding": binding, "verified": True})
        return {
            "status": "same_draft_updated",
            "images": 5,
            "not_published": True,
            "readback_verified": True,
        }
    finally:
        try:
            if client is not None:
                await client.aclose()
        finally:
            journal.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "reconcile"))
    parser.add_argument("--candidate-directory", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(
            run(mode=args.mode, candidate_directory=args.candidate_directory)
        )
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        SQLAlchemyError,
        TypeError,
        ValueError,
    ) as error:
        code = (
            str(error) if isinstance(error, ValueError) else "xiaosai_replace_stopped"
        )
        if re.fullmatch(r"xiaosai_replace_[a-z0-9_]{1,58}", code) is None:
            code = "xiaosai_replace_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
