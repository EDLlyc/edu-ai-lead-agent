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

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-22-wechat-draft-scheduler-backfill/research"
    / "replace_draft_badge_visuals.py"
)
SPEC = importlib.util.spec_from_file_location("replace_draft_badge_visuals", PATH)
assert SPEC is not None and SPEC.loader is not None
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)


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
        article: dict[str, object],
        *,
        fail_upload_at: int | None = None,
        fail_update: bool = False,
        apply_before_update_failure: bool = False,
    ) -> None:
        self.article = copy.deepcopy(article)
        self.fail_upload_at = fail_upload_at
        self.fail_update = fail_update
        self.apply_before_update_failure = apply_before_update_failure
        self.upload_calls = 0
        self.update_calls = 0
        self.get_calls = 0

    async def get(self, media_id: str) -> dict[str, object]:
        assert media_id == "fixed_draft_media_id"
        self.get_calls += 1
        return copy.deepcopy(self.article)

    async def upload(self, *, body: bytes, filename: str) -> str:
        ordinal = self.upload_calls
        self.upload_calls += 1
        assert filename == f"badge-visual-{ordinal + 1}.jpg"
        assert body
        if ordinal == self.fail_upload_at:
            raise TimeoutError("private provider detail")
        return f"https://mmbiz.qpic.cn/badge/{ordinal}/0?wx_fmt=jpeg"

    async def update(self, *, media_id: str, article: Any) -> None:
        assert media_id == "fixed_draft_media_id"
        self.update_calls += 1
        if not self.fail_update or self.apply_before_update_failure:
            self.article = asdict(article)
            self.article["need_open_comment"] = int(bool(self.article["need_open_comment"]))
            self.article["only_fans_can_comment"] = int(bool(self.article["only_fans_can_comment"]))
        if self.fail_update:
            raise TimeoutError("private provider detail")


def _jpeg(index: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (1536, 1024), (20 + index, 70 + index, 120)).save(
        output, format="JPEG", quality=88
    )
    return output.getvalue()


def _original_article() -> dict[str, object]:
    images = [f"https://mmbiz.qpic.cn/original/{index}/0" for index in range(7)]
    content = (
        '<section style="color:#123"><img src="'
        + images[0]
        + '"/><p>开场 <a href="https://example.com/source">来源</a></p>'
        + "".join(
            f'<section data-slot="{index}"><p>段落 {index}</p>'
            f'<img data-src="{images[index + 1]}"/></section>'
            for index in range(5)
        )
        + f'<img src="{images[-1]}"/><p>结尾</p></section>'
    )
    return {
        "title": "科学课正在走向动手探究",
        "author": "程岳",
        "digest": "以一则新闻说明探究式学习。",
        "content": content,
        "content_source_url": "https://example.com/article",
        "thumb_media_id": "fixed_thumb_media_id",
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }


def _fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MemoryJournal, MemoryStore, dict[str, object]]:
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
    monkeypatch.setattr(operator, "APPROVED_OBJECTS", approved)
    article_fingerprint = "a" * 64
    content_fingerprint = "b" * 64
    auth_binding = {
        "version": operator.BACKFILL_VERSION,
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
    original = _original_article()
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
    manifest_slots = [
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
        "version": operator.BADGE_VERSION,
        "account": operator.ACCOUNT,
        "business_date": operator.BUSINESS_DATE,
        "edition_fingerprint": sha256(str(operator.EDITION).encode()).hexdigest(),
        "target_identity": "e" * 64,
        "article_fingerprint": article_fingerprint,
        "max_provider_calls": 5,
        "one_call_per_slot": True,
        "generation_only": True,
        "slots": manifest_slots,
    }
    values: dict[str, dict[str, Any]] = {
        f"{operator.BACKFILL_PREFIX}-authorization.json": auth,
        f"{operator.BACKFILL_PREFIX}-readback.json": {
            "version": operator.BACKFILL_VERSION,
            "authorization_fingerprint": operator._sha(auth),
            "receipt_fingerprint": sha256(b"fixed_draft_media_id").hexdigest(),
            "article_fingerprint": article_fingerprint,
            "content_fingerprint": content_fingerprint,
            "request_fingerprint": operator._sha(original),
            "verified": True,
            "not_published": True,
        },
        f"single-{operator.EDITION.hex}-add-1-intent.json": add_intent,
        f"single-{operator.EDITION.hex}-add-1-ack.json": {
            "intent_sha256": operator._sha(add_intent),
            "value": "fixed_draft_media_id",
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
        f"{operator.BADGE_PREFIX}-manifest.json": manifest,
    }
    result_hashes: list[list[object]] = []
    for approved_item, slot in zip(approved, manifest_slots, strict=True):
        ordinal, media_type, byte_size, digest, width, height = approved_item
        intent = {
            "version": operator.BADGE_VERSION,
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
        values[f"{operator.BADGE_PREFIX}-visual-{ordinal}-intent.json"] = intent
        values[f"{operator.BADGE_PREFIX}-visual-{ordinal}-result.json"] = result
        result_hashes.append([ordinal, operator._sha(result)])
    values[f"{operator.BADGE_PREFIX}-selection.json"] = {
        "version": operator.BADGE_VERSION,
        "manifest_sha256": operator._sha(manifest),
        "target_identity": manifest["target_identity"],
        "result_sha256s": result_hashes,
        "objects": [list(item) for item in approved],
        "requires_visual_inspection": True,
        "generation_only": True,
    }
    return MemoryJournal(values), MemoryStore(bodies), original


def _replacement_names(journal: MemoryJournal) -> set[str]:
    return {name for name in journal.values if name.startswith(operator.REPLACEMENT_PREFIX)}


def _reseal_original_request(journal: MemoryJournal, original: dict[str, object]) -> None:
    add_name = f"single-{operator.EDITION.hex}-add-1"
    add_intent = journal.values[add_name + "-intent.json"]
    add_intent["request"] = original
    journal.values[add_name + "-ack.json"]["intent_sha256"] = operator._sha(add_intent)
    journal.values[f"{operator.BACKFILL_PREFIX}-readback.json"]["request_fingerprint"] = (
        operator._sha(original)
    )


def test_exact_five_same_draft_replacement_and_repeat_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote = FakeRemote(original)

    result = asyncio.run(
        operator.replace_badge_visuals(mode="replace", journal=journal, store=store, remote=remote)
    )

    assert result == {
        "status": "same_draft_updated",
        "images": 5,
        "external_writes": 6,
        "readback_verified": True,
        "same_draft": True,
        "not_published": True,
    }
    assert remote.upload_calls == 5
    assert remote.update_calls == 1
    before = operator.HtmlProjection(str(original["content"]))
    after = operator.HtmlProjection(str(remote.article["content"]))
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
        "content_source_url",
        "thumb_media_id",
        "need_open_comment",
        "only_fans_can_comment",
    ):
        assert remote.article[key] == original[key]

    writes = tuple(journal.writes)
    repeated = asyncio.run(
        operator.replace_badge_visuals(mode="replace", journal=journal, store=store, remote=remote)
    )
    assert repeated["status"] == "readback_verified"
    assert repeated["external_writes"] == 0
    assert remote.upload_calls == 5
    assert remote.update_calls == 1
    assert tuple(journal.writes) == writes


def test_plan_is_read_only_and_remote_drift_stops_before_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote = FakeRemote(original)
    result = asyncio.run(
        operator.replace_badge_visuals(mode="plan", journal=journal, store=store, remote=remote)
    )
    assert result["status"] == "planned"
    assert journal.writes == []
    assert remote.upload_calls == remote.update_calls == 0


def test_wechat_leaf_attribute_serialization_is_presence_equivalent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    original["content"] = str(original["content"]).replace(
        '<section style="color:#123">',
        '<section style="color:#123"><span leaf>标记</span>',
        1,
    )
    _reseal_original_request(journal, original)
    remote_article = copy.deepcopy(original)
    remote_article["content"] = str(remote_article["content"]).replace(
        "<span leaf>", '<span leaf="leaf">', 1
    )
    remote = FakeRemote(remote_article)

    result = asyncio.run(
        operator.replace_badge_visuals(mode="plan", journal=journal, store=store, remote=remote)
    )
    assert result["status"] == "planned"
    assert remote.upload_calls == remote.update_calls == 0

    remote.article["title"] = "人工改过的标题"
    with pytest.raises(operator.OperatorError, match="badge_replace_remote_edited"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    assert _replacement_names(journal) == set()
    assert remote.upload_calls == remote.update_calls == 0


def test_img_src_data_src_and_void_slash_are_transport_equivalent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote_article = copy.deepcopy(original)
    remote_article["content"] = (
        str(remote_article["content"])
        .replace("<img src=", "<img transport-src=")
        .replace("<img data-src=", "<img src=")
        .replace("<img transport-src=", "<img data-src=")
        .replace("/>", ">")
    )
    remote = FakeRemote(remote_article)

    result = asyncio.run(
        operator.replace_badge_visuals(mode="plan", journal=journal, store=store, remote=remote)
    )

    assert result["status"] == "planned"
    assert journal.writes == []
    assert remote.upload_calls == remote.update_calls == 0


def test_leaf_equivalence_is_limited_to_span_and_pi_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    original["content"] = str(original["content"]).replace(
        '<section style="color:#123">', '<section leaf style="color:#123">', 1
    )
    _reseal_original_request(journal, original)
    remote_article = copy.deepcopy(original)
    remote_article["content"] = str(remote_article["content"]).replace(
        "<section leaf ", '<section leaf="leaf" ', 1
    )

    with pytest.raises(operator.OperatorError, match="badge_replace_remote_edited"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="plan",
                journal=journal,
                store=store,
                remote=FakeRemote(remote_article),
            )
        )

    pi_article = copy.deepcopy(original)
    pi_article["content"] = "<?unsafe value?>" + str(pi_article["content"])
    with pytest.raises(operator.OperatorError, match="badge_replace_remote_html_invalid"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="plan",
                journal=journal,
                store=store,
                remote=FakeRemote(pi_article),
            )
        )
    with pytest.raises(operator.OperatorError, match="badge_replace_remote_html_invalid"):
        operator.HtmlProjection("<section><span>错序</section></span>")
    with pytest.raises(operator.OperatorError, match="badge_replace_remote_html_invalid"):
        operator.HtmlProjection("<section><span>未闭合</span>")
    assert journal.writes == []


def test_empty_source_url_is_not_equivalent_to_absent_source_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    original["content_source_url"] = None
    _reseal_original_request(journal, original)
    remote_article = copy.deepcopy(original)
    remote_article["content_source_url"] = ""

    with pytest.raises(operator.OperatorError, match="badge_replace_remote_edited"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="plan",
                journal=journal,
                store=store,
                remote=FakeRemote(remote_article),
            )
        )
    assert journal.writes == []


def test_orphaned_upload_receipt_without_operation_claim_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    intent_name, _ack_name = operator._upload_names(0)
    journal.values[intent_name] = {"orphaned": True}
    remote = FakeRemote(original)

    with pytest.raises(operator.OperatorError, match="badge_replace_update_without_claim"):
        asyncio.run(
            operator.replace_badge_visuals(mode="plan", journal=journal, store=store, remote=remote)
        )
    assert journal.writes == []
    assert remote.upload_calls == remote.update_calls == 0


def test_candidate_hash_or_order_drift_fails_before_remote_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    selection_name = f"{operator.BADGE_PREFIX}-selection.json"
    selection = journal.values[selection_name]
    selection["objects"] = list(reversed(selection["objects"]))
    remote = FakeRemote(original)

    with pytest.raises(operator.OperatorError, match="badge_replace_candidate_selection_invalid"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    assert remote.get_calls == remote.upload_calls == remote.update_calls == 0
    assert _replacement_names(journal) == set()


def test_original_add_request_fingerprint_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    journal.values[f"{operator.BACKFILL_PREFIX}-readback.json"]["request_fingerprint"] = "0" * 64
    remote = FakeRemote(original)

    with pytest.raises(operator.OperatorError, match="badge_replace_original_readback_invalid"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    assert remote.get_calls == remote.upload_calls == remote.update_calls == 0


def test_upload_unknown_is_never_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote = FakeRemote(original, fail_upload_at=2)

    with pytest.raises(operator.OperatorError, match="badge_replace_upload_outcome_unknown"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 3
    assert remote.update_calls == 0
    with pytest.raises(operator.OperatorError, match="badge_replace_upload_outcome_unknown"):
        asyncio.run(
            operator.replace_badge_visuals(mode="plan", journal=journal, store=store, remote=remote)
        )
    assert remote.upload_calls == 3
    with pytest.raises(operator.OperatorError, match="badge_replace_upload_outcome_unknown"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 3
    assert remote.update_calls == 0


def test_update_unknown_exact_readback_reconciles_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote = FakeRemote(original, fail_update=True, apply_before_update_failure=True)

    with pytest.raises(operator.OperatorError, match="badge_replace_update_outcome_unknown"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    assert remote.upload_calls == 5
    assert remote.update_calls == 1
    reconciled = asyncio.run(
        operator.replace_badge_visuals(
            mode="reconcile", journal=journal, store=store, remote=remote
        )
    )
    assert reconciled["status"] == "readback_verified_after_unknown"
    assert reconciled["external_writes"] == 0
    assert remote.upload_calls == 5
    assert remote.update_calls == 1

    writes = tuple(journal.writes)
    repeated = asyncio.run(
        operator.replace_badge_visuals(mode="replace", journal=journal, store=store, remote=remote)
    )
    assert repeated["status"] == "readback_verified_after_unknown"
    assert tuple(journal.writes) == writes
    assert remote.update_calls == 1


def test_plan_reconciles_applied_unknown_without_writing_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote = FakeRemote(original, fail_update=True, apply_before_update_failure=True)
    with pytest.raises(operator.OperatorError, match="badge_replace_update_outcome_unknown"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    writes_before_plan = tuple(journal.writes)

    result = asyncio.run(
        operator.replace_badge_visuals(mode="plan", journal=journal, store=store, remote=remote)
    )

    assert result["status"] == "readback_verified_after_unknown"
    assert result["external_writes"] == 0
    assert tuple(journal.writes) == writes_before_plan
    assert remote.upload_calls == 5
    assert remote.update_calls == 1


def test_update_unknown_mismatch_remains_reconcile_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)
    remote = FakeRemote(original, fail_update=True)

    with pytest.raises(operator.OperatorError, match="badge_replace_update_outcome_unknown"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )
    result = asyncio.run(
        operator.replace_badge_visuals(mode="replace", journal=journal, store=store, remote=remote)
    )
    assert result["status"] == "outcome_unknown_reconcile_only"
    assert result["external_writes"] == 0
    assert remote.upload_calls == 5
    assert remote.update_calls == 1


def test_remote_drift_after_uploads_stops_before_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, store, original = _fixtures(monkeypatch)

    class DriftingRemote(FakeRemote):
        async def get(self, media_id: str) -> dict[str, object]:
            if self.upload_calls == 5 and self.update_calls == 0:
                self.article["digest"] = "人工并发修改"
            return await super().get(media_id)

    remote = DriftingRemote(original)
    with pytest.raises(operator.OperatorError, match="badge_replace_remote_edited"):
        asyncio.run(
            operator.replace_badge_visuals(
                mode="replace", journal=journal, store=store, remote=remote
            )
        )

    assert remote.upload_calls == 5
    assert remote.update_calls == 0
    assert journal.read(operator._update_names()[0]) is None


def test_official_update_payload_is_single_article_at_index_zero() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    class CapturingRemote:
        async def _post(
            self,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            files: dict[str, tuple[str, bytes, str]] | None = None,
            limit: int = 65_536,
        ) -> dict[str, object]:
            assert files is None
            assert limit == 65_536
            calls.append((path, payload))
            return {"errcode": 0, "errmsg": "ok"}

    article = operator.WeChatDraftArticleRequest(
        title="标题",
        author="程岳",
        digest="摘要",
        content="<p>正文</p>",
        content_source_url="https://example.com/source",
        thumb_media_id="fixed_thumb_media_id",
        need_open_comment=True,
        only_fans_can_comment=False,
    )
    remote = CapturingRemote()
    asyncio.run(
        operator.OfficialRemote.update(remote, media_id="fixed_draft_media_id", article=article)
    )

    assert calls == [
        (
            "/cgi-bin/draft/update",
            {
                "media_id": "fixed_draft_media_id",
                "index": 0,
                "articles": {
                    **asdict(article),
                    "article_type": "news",
                    "need_open_comment": 1,
                    "only_fans_can_comment": 0,
                },
            },
        )
    ]


def test_operator_has_no_add_publish_delete_or_database_write_surface() -> None:
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
    assert "/cgi-bin/draft/add" not in source
    assert "freepublish" not in source
    assert "mass/send" not in source
    assert "/cgi-bin/draft/delete" not in source
    assert "commit(" not in source
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and isinstance(getattr(node, "args", None), ast.arguments)
    }
    assert "add_draft" not in methods
    assert "publish" not in methods
    assert "delete" not in methods
