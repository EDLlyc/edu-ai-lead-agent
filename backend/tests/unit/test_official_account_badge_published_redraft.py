from __future__ import annotations

import ast
import asyncio
import copy
import importlib.util
import sys
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

RESEARCH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-22-wechat-draft-scheduler-backfill/research"
)
PATH = RESEARCH / "create_badge_corrected_draft.py"
sys.path.insert(0, str(RESEARCH))
SPEC = importlib.util.spec_from_file_location("create_badge_corrected_draft", PATH)
assert SPEC is not None and SPEC.loader is not None
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)

ROOT_STYLE_BEFORE = (
    "background:#fff;color:#123;font-family:Arial;letter-spacing:1px;"
    "line-height:1.8;margin:0 auto;max-width:677px;overflow-x:hidden;"
    "padding:10px;text-align:left"
)
ROOT_STYLE_AFTER = "padding:10px;text-align:left"
ROOT_STYLE_EXACT_REMOVALS = (
    "background:#fff;color:#123;font-family:Arial;letter-spacing:1px;"
    "line-height:1.8;margin:0 auto;max-width:677px;overflow-x:hidden;"
)


class MemoryJournal:
    def __init__(self, values: dict[str, dict[str, Any]]) -> None:
        self.values = copy.deepcopy(values)
        self.writes: list[str] = []

    def read(self, name: str) -> dict[str, Any] | None:
        value = self.values.get(name)
        return copy.deepcopy(value) if value is not None else None

    def write(self, name: str, payload: dict[str, Any]) -> None:
        assert name not in self.values
        self.values[name] = copy.deepcopy(payload)
        self.writes.append(name)


class MemoryStore:
    def __init__(self, bodies: tuple[bytes, ...]) -> None:
        self.values = {("image/jpeg", len(body), sha256(body).hexdigest()): body for body in bodies}

    async def get_content_addressed_bytes(
        self, *, media_type: str, byte_size: int, sha256: str
    ) -> bytes:
        return self.values[(media_type, byte_size, sha256)]


class FakeRemote:
    def __init__(
        self,
        published: dict[str, object],
        *,
        fail_upload_at: int | None = None,
        fail_add: bool = False,
        apply_before_add_failure: bool = False,
    ) -> None:
        self.published = [
            operator.PublishedItem("fixed_published_article_id", copy.deepcopy(published))
        ]
        self.drafts: list[Any] = [operator.DraftItem("unrelated_draft", _unrelated_article())]
        self.original_absent = True
        self.fail_upload_at = fail_upload_at
        self.fail_add = fail_add
        self.apply_before_add_failure = apply_before_add_failure
        self.upload_calls = 0
        self.add_calls = 0
        self.get_calls = 0
        self.published_calls = 0
        self.draft_list_calls = 0

    async def published_items(self) -> tuple[Any, ...]:
        self.published_calls += 1
        return tuple(copy.deepcopy(self.published))

    async def draft_items(self) -> tuple[Any, ...]:
        self.draft_list_calls += 1
        return tuple(copy.deepcopy(self.drafts))

    async def original_draft_absent(self, media_id: str) -> bool:
        assert media_id == "fixed_original_draft"
        return self.original_absent

    async def get_draft(self, media_id: str) -> dict[str, object]:
        self.get_calls += 1
        matches = [item for item in self.drafts if item.media_id == media_id]
        assert len(matches) == 1
        return copy.deepcopy(matches[0].article)

    async def upload(self, *, body: bytes, filename: str) -> str:
        ordinal = self.upload_calls
        self.upload_calls += 1
        assert body
        assert filename == f"badge-redraft-visual-{ordinal + 1}.jpg"
        if ordinal == self.fail_upload_at:
            raise TimeoutError("private provider detail")
        return f"https://mmbiz.qpic.cn/redraft/{ordinal}/0?wx_fmt=jpeg"

    async def add(self, *, article: Any) -> str:
        self.add_calls += 1
        media_id = f"new_corrected_draft_{self.add_calls}"
        if not self.fail_add or self.apply_before_add_failure:
            value = asdict(article)
            value["need_open_comment"] = int(value["need_open_comment"])
            value["only_fans_can_comment"] = int(value["only_fans_can_comment"])
            self.drafts.append(operator.DraftItem(media_id, value))
        if self.fail_add:
            raise TimeoutError("private provider detail")
        return media_id


def _jpeg(index: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (1536, 1024), (30 + index, 80 + index, 130)).save(
        output, format="JPEG", quality=88
    )
    return output.getvalue()


def _article(*, published: bool) -> dict[str, object]:
    prefix = "published" if published else "original"
    images = [f"https://mmbiz.qpic.cn/{prefix}/{index}/0" for index in range(7)]
    paragraphs = "已发布正文" if published else "原始正文"
    content = (
        '<section style="color:#123"><img src="'
        + images[0]
        + '"/><p>'
        + paragraphs
        + ' <a href="https://example.com/source">来源</a></p>'
        + "".join(
            f'<section data-slot="{index}"><p>{paragraphs} {index}</p>'
            f'<img data-src="{images[index + 1]}"/></section>'
            for index in range(5)
        )
        + f'<img src="{images[-1]}"/><p>{paragraphs}结尾</p></section>'
    )
    value: dict[str, object] = {
        "title": "科学课正在走向动手探究",
        "author": "程岳",
        "digest": "以一则新闻说明探究式学习。",
        "content": content,
        "content_source_url": "" if published else "https://example.com/article",
        "thumb_media_id": "fixed_thumb_media_id",
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }
    if published:
        value["is_deleted"] = False
    return value


def _unrelated_article() -> dict[str, object]:
    value = _article(published=True)
    value["title"] = "其他草稿"
    value.pop("is_deleted")
    return value


def _with_root_style(article: dict[str, object], style: str) -> dict[str, object]:
    value = copy.deepcopy(article)
    value["content"] = str(value["content"]).replace('style="color:#123"', f'style="{style}"', 1)
    return value


def _fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MemoryJournal, MemoryStore, dict[str, object], dict[str, object]]:
    bodies = tuple(_jpeg(index) for index in range(5))
    approved = tuple(
        (
            ordinal,
            "image/jpeg",
            len(body),
            sha256(body).hexdigest(),
            1536,
            1024,
        )
        for ordinal, body in enumerate(bodies)
    )
    monkeypatch.setattr(operator.shared, "APPROVED_OBJECTS", approved)
    article_fingerprint = "a" * 64
    content_fingerprint = "b" * 64
    auth_binding = {
        "version": operator.shared.BACKFILL_VERSION,
        "account": operator.ACCOUNT,
        "business_date": operator.BUSINESS_DATE,
        "edition_id": str(operator.EDITION),
        "run_id": "11111111-1111-4111-8111-111111111111",
        "article_id": "22222222-2222-4222-8222-222222222222",
        "render_id": "33333333-3333-4333-8333-333333333333",
        "event_id": "44444444-4444-4444-8444-444444444444",
        "source_identity": "c" * 64,
        "prior_unknown_attempts": [],
        "fallback_article_fingerprint": article_fingerprint,
        "fallback_content_fingerprint": "d" * 64,
        "fallback_media": [],
        "visual_plans": [],
        "max_visual_calls": 5,
        "all_or_nothing": True,
        "draft_only": True,
    }
    auth = {
        "binding": auth_binding,
        "authorized_at": "2026-09-22T01:00:00+00:00",
        "expires_at": "2026-09-22T03:00:00+00:00",
    }
    original = _article(published=False)
    published = _article(published=True)
    original_projection = operator.shared.HtmlProjection(str(original["content"]))
    published_projection = operator.shared.HtmlProjection(str(published["content"]))
    # The current published article can have edited visible copy, but the fixed
    # historical identity still binds its first/last framing images and links.
    published["content"] = (
        str(published["content"])
        .replace(published_projection.images[0], original_projection.images[0])
        .replace(published_projection.images[-1], original_projection.images[-1])
    )
    delivery_binding = operator._sha(
        {
            "edition": str(operator.EDITION),
            "article": article_fingerprint,
            "content": content_fingerprint,
            "account": operator.ACCOUNT,
            "policy": "single-write-journal-v1",
            "max_attempts": 1,
        }
    )
    add_intent = {
        "binding": delivery_binding,
        "step": "add",
        "attempt": 1,
        "request": original,
    }
    slots = [
        {
            "ordinal": ordinal,
            "logical_request_fingerprint": f"{ordinal + 1:x}" * 64,
            "provider_request_fingerprint": f"{ordinal + 6:x}" * 64,
            "prompt_sha256": f"{ordinal + 11:x}" * 64,
            "reference_publication_checksum": f"{ordinal + 1:x}" * 64,
        }
        for ordinal in range(5)
    ]
    manifest = {
        "version": operator.shared.BADGE_VERSION,
        "account": operator.ACCOUNT,
        "business_date": operator.BUSINESS_DATE,
        "edition_fingerprint": sha256(str(operator.EDITION).encode()).hexdigest(),
        "target_identity": "e" * 64,
        "article_fingerprint": article_fingerprint,
        "max_provider_calls": 5,
        "one_call_per_slot": True,
        "generation_only": True,
        "slots": slots,
    }
    values: dict[str, dict[str, Any]] = {
        f"{operator.shared.BACKFILL_PREFIX}-authorization.json": auth,
        f"{operator.shared.BACKFILL_PREFIX}-readback.json": {
            "version": operator.shared.BACKFILL_VERSION,
            "authorization_fingerprint": operator._sha(auth),
            "receipt_fingerprint": sha256(b"fixed_original_draft").hexdigest(),
            "article_fingerprint": article_fingerprint,
            "content_fingerprint": content_fingerprint,
            "request_fingerprint": operator._sha(original),
            "verified": True,
            "not_published": True,
        },
        f"single-{operator.EDITION.hex}-add-1-intent.json": add_intent,
        f"single-{operator.EDITION.hex}-add-1-ack.json": {
            "intent_sha256": operator._sha(add_intent),
            "value": "fixed_original_draft",
        },
        f"{article_fingerprint}-claim.json": {
            "account": operator.ACCOUNT,
            "binding": {
                "version": "single-edition-claim-v1",
                "raw_article": article_fingerprint,
                "edition_id": str(operator.EDITION),
                "fingerprint": delivery_binding,
            },
        },
        f"{operator.shared.BADGE_PREFIX}-manifest.json": manifest,
    }
    result_hashes: list[list[object]] = []
    for approved_item, slot in zip(approved, slots, strict=True):
        ordinal, media_type, byte_size, digest, width, height = approved_item
        intent = {
            "version": operator.shared.BADGE_VERSION,
            "manifest_sha256": operator._sha(manifest),
            "ordinal": ordinal,
            "logical_request_fingerprint": slot["logical_request_fingerprint"],
            "provider_request_fingerprint": slot["provider_request_fingerprint"],
            "prompt_sha256": slot["prompt_sha256"],
            "reference_publication_checksum": slot["reference_publication_checksum"],
            "maximum_calls": 1,
        }
        result = {
            "intent_sha256": operator._sha(intent),
            "ordinal": ordinal,
            "status": "ready",
            "media_type": media_type,
            "byte_size": byte_size,
            "sha256": digest,
            "width": width,
            "height": height,
            "provider_request_fingerprint": slot["provider_request_fingerprint"],
        }
        values[f"{operator.shared.BADGE_PREFIX}-visual-{ordinal}-intent.json"] = intent
        values[f"{operator.shared.BADGE_PREFIX}-visual-{ordinal}-result.json"] = result
        result_hashes.append([ordinal, operator._sha(result)])
    values[f"{operator.shared.BADGE_PREFIX}-selection.json"] = {
        "version": operator.shared.BADGE_VERSION,
        "manifest_sha256": operator._sha(manifest),
        "target_identity": manifest["target_identity"],
        "result_sha256s": result_hashes,
        "objects": [list(item) for item in approved],
        "requires_visual_inspection": True,
        "generation_only": True,
    }
    return MemoryJournal(values), MemoryStore(bodies), original, published


def _redraft_names(journal: MemoryJournal) -> set[str]:
    return {name for name in journal.values if name.startswith(operator.REDRAFT_PREFIX)}


def test_create_from_published_article_and_repeat_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published)

    result = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )

    assert result == {
        "status": "new_unpublished_draft_created",
        "images": 5,
        "external_writes": 6,
        "readback_verified": True,
        "not_published": True,
        "published_unchanged": True,
    }
    assert remote.upload_calls == 5
    assert remote.add_calls == 1
    created = remote.drafts[-1].article
    before = operator.shared.HtmlProjection(str(published["content"]))
    after = operator.shared.HtmlProjection(str(created["content"]))
    assert "已发布正文" in after.normalized_text
    assert "原始正文" not in after.normalized_text
    assert before.normalized_text == after.normalized_text
    assert before.links == after.links
    assert before.topology == after.topology
    assert after.images[0] == before.images[0]
    assert after.images[-1] == before.images[-1]
    assert after.images[1:6] != before.images[1:6]
    for key in (
        "title",
        "author",
        "digest",
        "thumb_media_id",
        "need_open_comment",
        "only_fans_can_comment",
    ):
        assert created[key] == published[key]
    assert published["content_source_url"] == ""
    assert created["content_source_url"] is None

    writes = tuple(journal.writes)
    repeated = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert repeated["status"] == "readback_verified"
    assert repeated["external_writes"] == 0
    assert remote.upload_calls == 5
    assert remote.add_calls == 1
    assert tuple(journal.writes) == writes


def test_exact_wechat_root_style_sanitization_reconciles_existing_ack_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    published = _with_root_style(published, ROOT_STYLE_BEFORE)
    remote = FakeRemote(published)
    created = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert created["external_writes"] == 6
    assert remote.upload_calls == 5
    assert remote.add_calls == 1

    remote.drafts[-1].article["content"] = str(remote.drafts[-1].article["content"]).replace(
        ROOT_STYLE_BEFORE, ROOT_STYLE_AFTER, 1
    )
    writes = tuple(journal.writes)
    repeated = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert repeated["status"] == "readback_verified"
    assert repeated["external_writes"] == 0
    assert repeated["readback_verified"] is True
    assert remote.upload_calls == 5
    assert remote.add_calls == 1
    assert tuple(journal.writes) == writes


def test_exact_eight_root_styles_to_empty_reconciles_existing_ack_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    published = _with_root_style(published, ROOT_STYLE_EXACT_REMOVALS)
    remote = FakeRemote(published)
    created = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert created["external_writes"] == 6

    remote.drafts[-1].article["content"] = str(remote.drafts[-1].article["content"]).replace(
        ROOT_STYLE_EXACT_REMOVALS, "", 1
    )
    writes = tuple(journal.writes)
    repeated = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert repeated["status"] == "readback_verified"
    assert repeated["external_writes"] == 0
    assert remote.upload_calls == 5
    assert remote.add_calls == 1
    assert tuple(journal.writes) == writes


def test_exact_eight_root_styles_accept_only_literal_empty_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _journal, _store, _original, published = _fixtures(monkeypatch)
    before_article = _with_root_style(published, ROOT_STYLE_EXACT_REMOVALS)
    before = operator.shared.HtmlProjection(str(before_article["content"]))

    empty_article = _with_root_style(published, "")
    empty = operator.shared.HtmlProjection(str(empty_article["content"]))
    assert operator._draft_topology_equivalent(before.topology, empty.topology)

    whitespace_article = _with_root_style(published, " ")
    whitespace = operator.shared.HtmlProjection(str(whitespace_article["content"]))
    assert not operator._draft_topology_equivalent(before.topology, whitespace.topology)

    missing_article = copy.deepcopy(before_article)
    missing_article["content"] = str(missing_article["content"]).replace(
        f' style="{ROOT_STYLE_EXACT_REMOVALS}"', "", 1
    )
    missing = operator.shared.HtmlProjection(str(missing_article["content"]))
    assert not operator._draft_topology_equivalent(before.topology, missing.topology)


@pytest.mark.parametrize(
    "before_style",
    [
        ROOT_STYLE_BEFORE,
        ROOT_STYLE_EXACT_REMOVALS.replace("background:#fff;", "", 1),
        ROOT_STYLE_EXACT_REMOVALS + "background:#fff;",
        ROOT_STYLE_EXACT_REMOVALS.replace("background:#fff", "background", 1),
    ],
)
def test_empty_root_style_rejects_extra_missing_duplicate_or_malformed_before(
    monkeypatch: pytest.MonkeyPatch, before_style: str
) -> None:
    _journal, _store, _original, published = _fixtures(monkeypatch)
    before_article = _with_root_style(published, before_style)
    empty_article = _with_root_style(published, "")
    before = operator.shared.HtmlProjection(str(before_article["content"]))
    after = operator.shared.HtmlProjection(str(empty_article["content"]))
    assert not operator._draft_topology_equivalent(before.topology, after.topology)
    assert not operator._same_non_image_article(current=empty_article, expected=before_article)


@pytest.mark.parametrize(
    "after_style",
    [
        "background:#fff;padding:10px;text-align:left",
        "text-align:left",
        "padding:11px;text-align:left",
        "padding:10px;text-align:left;border:0",
        "padding:10px;padding:10px;text-align:left",
        "padding;text-align:left",
        "padding: 10px;text-align:left",
        "padding:10px ;text-align:left",
        "text-align:left;padding:10px",
        "padding:10px;text-align:left;",
    ],
)
def test_root_style_sanitization_rejects_partial_extra_changed_added_or_malformed(
    monkeypatch: pytest.MonkeyPatch, after_style: str
) -> None:
    _journal, _store, _original, published = _fixtures(monkeypatch)
    before_article = _with_root_style(published, ROOT_STYLE_BEFORE)
    after_article = _with_root_style(published, after_style)
    before = operator.shared.HtmlProjection(str(before_article["content"]))
    after = operator.shared.HtmlProjection(str(after_article["content"]))
    assert not operator._draft_topology_equivalent(before.topology, after.topology)
    assert not operator._same_non_image_article(current=after_article, expected=before_article)


def test_root_style_sanitization_rejects_nonroot_and_other_topology_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _journal, _store, _original, published = _fixtures(monkeypatch)
    before_article = _with_root_style(published, ROOT_STYLE_BEFORE)

    nonroot_article = copy.deepcopy(before_article)
    nonroot_article["content"] = str(nonroot_article["content"]).replace(
        '<section data-slot="0">',
        f'<section data-slot="0" style="{ROOT_STYLE_AFTER}">',
        1,
    )
    other_topology_article = copy.deepcopy(before_article)
    other_topology_article["content"] = str(other_topology_article["content"]).replace(
        'data-slot="0"', 'data-slot="changed"', 1
    )
    root_attribute_article = copy.deepcopy(before_article)
    root_attribute_article["content"] = str(root_attribute_article["content"]).replace(
        f'<section style="{ROOT_STYLE_BEFORE}">',
        f'<section data-added="true" style="{ROOT_STYLE_AFTER}">',
        1,
    )

    before = operator.shared.HtmlProjection(str(before_article["content"]))
    for changed in (
        nonroot_article,
        other_topology_article,
        root_attribute_article,
    ):
        after = operator.shared.HtmlProjection(str(changed["content"]))
        assert not operator._draft_topology_equivalent(before.topology, after.topology)
        assert not operator._same_non_image_article(current=changed, expected=before_article)


def test_plan_is_read_only_and_requires_unique_live_published_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published)
    result = asyncio.run(
        operator.create_corrected_draft(mode="plan", journal=journal, store=store, remote=remote)
    )
    assert result["status"] == "planned"
    assert result["external_writes"] == 0
    assert journal.writes == []
    assert remote.upload_calls == remote.add_calls == 0

    remote.published.append(copy.deepcopy(remote.published[0]))
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_target_not_unique"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="plan", journal=journal, store=store, remote=remote
            )
        )
    assert journal.writes == []


def test_deleted_or_drifted_published_source_and_live_original_draft_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published)
    remote.published[0].article["is_deleted"] = 1
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_target_not_unique"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert _redraft_names(journal) == set()
    assert remote.upload_calls == remote.add_calls == 0

    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published)
    remote.original_absent = False
    with pytest.raises(operator.OperatorError, match="badge_redraft_original_draft_still_present"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert _redraft_names(journal) == set()


@pytest.mark.parametrize("not_deleted", [False, 0])
def test_source_match_accepts_only_boolean_false_or_integer_zero(
    monkeypatch: pytest.MonkeyPatch, not_deleted: object
) -> None:
    _journal, _store, original, published = _fixtures(monkeypatch)
    published["is_deleted"] = not_deleted
    assert operator._source_match(candidate=published, original_request=original)


@pytest.mark.parametrize("deleted", [True, 1, None, "0", 0.0])
def test_source_match_rejects_other_deleted_types_and_values(
    monkeypatch: pytest.MonkeyPatch, deleted: object
) -> None:
    _journal, _store, original, published = _fixtures(monkeypatch)
    published["is_deleted"] = deleted
    assert not operator._source_match(candidate=published, original_request=original)


def test_nonempty_source_url_is_preserved_and_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _journal, _store, _original, published = _fixtures(monkeypatch)
    published["content_source_url"] = "https://example.com/published-source"
    request = operator._draft_request(original=published, rewritten_html=str(published["content"]))
    assert request.content_source_url == "https://example.com/published-source"

    published["content_source_url"] = "http://unsafe.example/source"
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_article_invalid"):
        operator._draft_request(original=published, rewritten_html=str(published["content"]))


@pytest.mark.parametrize("readback_source_url", [None, ""])
def test_empty_published_source_url_readback_spellings_are_equivalent(
    monkeypatch: pytest.MonkeyPatch, readback_source_url: object
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    assert published["content_source_url"] == ""

    class SourceSpellingRemote(FakeRemote):
        async def add(self, *, article: Any) -> str:
            media_id = await super().add(article=article)
            self.drafts[-1].article["content_source_url"] = readback_source_url
            return media_id

    result = asyncio.run(
        operator.create_corrected_draft(
            mode="create",
            journal=journal,
            store=store,
            remote=SourceSpellingRemote(published),
        )
    )
    assert result["status"] == "new_unpublished_draft_created"
    add_intent = journal.read(operator._add_names()[0])
    assert isinstance(add_intent, dict)
    assert add_intent["request"]["article"]["content_source_url"] is None


def test_nonempty_source_url_readback_change_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    published["content_source_url"] = "https://example.com/published-source"

    class ChangedSourceRemote(FakeRemote):
        async def add(self, *, article: Any) -> str:
            media_id = await super().add(article=article)
            self.drafts[-1].article["content_source_url"] = "https://example.com/unexpected-source"
            return media_id

    remote = ChangedSourceRemote(published)
    with pytest.raises(operator.OperatorError, match="badge_redraft_readback_mismatch"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 1


def test_matching_existing_draft_stops_before_claim_or_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published)
    existing = copy.deepcopy(published)
    existing.pop("is_deleted")
    remote.drafts.append(operator.DraftItem("existing_matching_draft", existing))

    with pytest.raises(operator.OperatorError, match="badge_redraft_preexisting_matching_draft"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert _redraft_names(journal) == set()
    assert remote.upload_calls == remote.add_calls == 0


def test_candidate_hash_or_order_drift_fails_before_remote_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    selection_name = f"{operator.shared.BADGE_PREFIX}-selection.json"
    journal.values[selection_name]["objects"] = list(
        reversed(journal.values[selection_name]["objects"])
    )
    remote = FakeRemote(published)

    with pytest.raises(
        operator.shared.OperatorError,
        match="badge_replace_candidate_selection_invalid",
    ):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == remote.add_calls == 0
    assert remote.published_calls == remote.draft_list_calls == 0


def test_upload_unknown_is_never_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published, fail_upload_at=2)

    with pytest.raises(operator.OperatorError, match="badge_redraft_upload_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 3
    assert remote.add_calls == 0
    for mode in ("plan", "create"):
        with pytest.raises(operator.OperatorError, match="badge_redraft_upload_outcome_unknown"):
            asyncio.run(
                operator.create_corrected_draft(
                    mode=mode, journal=journal, store=store, remote=remote
                )
            )
    assert remote.upload_calls == 3
    assert remote.add_calls == 0


def test_add_unknown_unique_new_exact_draft_reconciles_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published, fail_add=True, apply_before_add_failure=True)

    with pytest.raises(operator.OperatorError, match="badge_redraft_add_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 1

    pending = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert pending["status"] == "outcome_unknown_reconcile_only"
    assert pending["external_writes"] == 0
    assert remote.add_calls == 1

    reconciled = asyncio.run(
        operator.create_corrected_draft(
            mode="reconcile", journal=journal, store=store, remote=remote
        )
    )
    assert reconciled["status"] == "readback_verified_after_unknown"
    assert reconciled["external_writes"] == 0
    assert remote.add_calls == 1

    writes = tuple(journal.writes)
    repeated = asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    assert repeated["status"] == "readback_verified_after_unknown"
    assert repeated["external_writes"] == 0
    assert tuple(journal.writes) == writes
    assert remote.add_calls == 1


def test_add_unknown_without_exact_result_remains_reconcile_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published, fail_add=True)

    with pytest.raises(operator.OperatorError, match="badge_redraft_add_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    result = asyncio.run(
        operator.create_corrected_draft(
            mode="reconcile", journal=journal, store=store, remote=remote
        )
    )
    assert result["status"] == "outcome_unknown_reconcile_only"
    assert result["external_writes"] == 0
    assert remote.upload_calls == 5
    assert remote.add_calls == 1


def test_add_unknown_ambiguous_exact_results_are_not_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published, fail_add=True, apply_before_add_failure=True)

    with pytest.raises(operator.OperatorError, match="badge_redraft_add_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    duplicate = copy.deepcopy(remote.drafts[-1])
    duplicate = operator.DraftItem("second_exact_draft", duplicate.article)
    remote.drafts.append(duplicate)

    result = asyncio.run(
        operator.create_corrected_draft(
            mode="reconcile", journal=journal, store=store, remote=remote
        )
    )
    assert result["status"] == "outcome_unknown_reconcile_only"
    assert result["external_writes"] == 0
    assert journal.read(operator._add_names()[1]) is None
    assert remote.add_calls == 1


def test_published_drift_after_uploads_stops_before_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)

    class DriftingRemote(FakeRemote):
        async def published_items(self) -> tuple[Any, ...]:
            if self.upload_calls == 5:
                self.published[0].article["digest"] = "并发修改"
            return await super().published_items()

    remote = DriftingRemote(published)
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_target_not_unique"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 0
    assert journal.read(operator._add_names()[0]) is None


def test_full_published_record_drift_after_uploads_stops_before_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    published["show_cover_pic"] = 1

    class DriftingRemote(FakeRemote):
        async def published_items(self) -> tuple[Any, ...]:
            if self.upload_calls == 5:
                self.published[0].article["show_cover_pic"] = 0
            return await super().published_items()

    remote = DriftingRemote(published)
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_source_drift"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 0
    assert journal.read(operator._add_names()[0]) is None


def test_not_deleted_type_drift_after_freeze_stops_before_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    assert published["is_deleted"] is False

    class DriftingRemote(FakeRemote):
        async def published_items(self) -> tuple[Any, ...]:
            if self.upload_calls == 5:
                self.published[0].article["is_deleted"] = 0
            return await super().published_items()

    remote = DriftingRemote(published)
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_source_drift"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 0
    assert journal.read(operator._add_names()[0]) is None


def test_empty_published_source_url_drift_to_none_stops_before_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    assert published["content_source_url"] == ""

    class DriftingRemote(FakeRemote):
        async def published_items(self) -> tuple[Any, ...]:
            if self.upload_calls == 5:
                self.published[0].article["content_source_url"] = None
            return await super().published_items()

    remote = DriftingRemote(published)
    with pytest.raises(operator.OperatorError, match="badge_redraft_published_source_drift"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 0
    assert journal.read(operator._add_names()[0]) is None


def test_transport_equivalent_published_html_survives_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    published["thumb_url"] = "https://mmbiz.qpic.cn/published/thumb/0"
    remote = FakeRemote(published, fail_upload_at=1)

    with pytest.raises(operator.OperatorError, match="badge_redraft_upload_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    content = str(remote.published[0].article["content"])
    remote.published[0].article["content"] = (
        content.replace('/0"', '/640"')
        .replace('<img src="', '<img data-src="')
        .replace("来源", "&#26469;&#28304;")
    )
    remote.published[0].article["thumb_url"] = "https://mmbiz.qpic.cn/published/thumb/640"

    with pytest.raises(operator.OperatorError, match="badge_redraft_upload_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 2
    assert remote.add_calls == 0


def test_orphan_readback_cannot_recreate_a_second_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published)
    asyncio.run(
        operator.create_corrected_draft(mode="create", journal=journal, store=store, remote=remote)
    )
    intent_name, ack_name, readback_name = operator._add_names()
    assert journal.read(readback_name) is not None
    del journal.values[intent_name]
    del journal.values[ack_name]

    with pytest.raises(operator.OperatorError, match="badge_redraft_readback_without_ack"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.add_calls == 1


def test_claimed_baseline_drift_stops_before_more_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    remote = FakeRemote(published, fail_upload_at=1)
    with pytest.raises(operator.OperatorError, match="badge_redraft_upload_outcome_unknown"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    remote.drafts.append(operator.DraftItem("concurrent_draft", _unrelated_article()))

    with pytest.raises(operator.OperatorError, match="badge_redraft_draft_baseline_drift"):
        asyncio.run(
            operator.create_corrected_draft(
                mode="create", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 2
    assert remote.add_calls == 0


def test_fixed_approved_hashes_and_forbidden_surfaces() -> None:
    operator._require_shared_dependency()
    assert (
        operator.SHARED_MODULE_SHA256
        == sha256((RESEARCH / "replace_draft_badge_visuals.py").read_bytes()).hexdigest()
    )
    assert [item[3] for item in operator.shared.APPROVED_OBJECTS] == [
        "d9c032d5b9113b6d2659b7acfecb4a6d30044cb03f9a0a52bb4875dadaefe684",
        "ec285142d6a8f093a91b1d6612b98e3aa404538d258633ae0176795dcc948c57",
        "0ca4e6741b40d75933f7832d4a462e51b3a232e62e0df150874daf72fd225150",
        "99bec5f45337c3ed2b62c540628e2090eec1aa6cc315f0097cb9f45af362645b",
        "c9a76fc22b6642b1887ff5af5f6c59c08ff6a3e700c2ee53ceb0df435083e160",
    ]
    source = PATH.read_text()
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name.startswith("app.infrastructure.db") for name in imports)
    assert "sqlalchemy" not in imports
    assert "/cgi-bin/draft/update" not in source
    assert "/cgi-bin/draft/delete" not in source
    assert "/cgi-bin/freepublish/submit" not in source
    assert "/cgi-bin/message/mass/send" not in source
    assert "commit(" not in source
    assert operator.OfficialRemote._READ_PATHS == {
        "/cgi-bin/freepublish/batchget",
        "/cgi-bin/draft/batchget",
        "/cgi-bin/draft/get",
    }
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "update" not in methods
    assert "delete" not in methods
    assert "publish" not in methods


def test_safe_result_never_contains_identifiers_urls_or_article_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, _original, published = _fixtures(monkeypatch)
    result = asyncio.run(
        operator.create_corrected_draft(
            mode="create",
            journal=journal,
            store=store,
            remote=FakeRemote(published),
        )
    )
    serialized = repr(result)
    assert "fixed_" not in serialized
    assert "https://" not in serialized
    assert "已发布正文" not in serialized
    assert "media_id" not in serialized
    assert "article_id" not in serialized
