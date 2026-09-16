from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from pydantic import SecretStr
from test_draft_generated_update_only_operator import Remote as UpdateRemote
from test_draft_generated_update_only_operator import fixture, gen

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-05-production-recovery-qwen-embedding/research"
    / "visual-recovery-20260916/draft-generated-final-add.py"
)
SPEC = importlib.util.spec_from_file_location("draft_generated_final_add_operator", PATH)
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)


def inventory():
    return {
        "total_count": 6,
        "item_count": 6,
        "item": [
            {
                "media_id": f"other-{i}",
                "content": {
                    "news_item": [{"title": f"旧标题{i}", "author": "作者", "digest": "摘要"}]
                },
            }
            for i in range(6)
        ],
    }


class Remote(UpdateRemote):
    def __init__(self, journal, old, *, unknown=False, changed=False):
        super().__init__(journal, old, unknown=unknown)
        self.evidence = operator.inventory_evidence(inventory(), "old-media", old)
        self.evidence["old_get_error_code"] = 40007
        self.absences, self.adds, self.changed = 0, [], changed

    async def absence(self, _media_id, _expected):
        self.absences += 1
        if self.changed and self.absences == 2:
            raise ValueError("final_add_old_draft_exists")
        return self.evidence

    async def add(self, article, _token):
        assert self.journal.read(operator.PREFIX + "-add-intent.json") is not None
        self.adds.append(article)
        if self.unknown:
            raise TimeoutError("private")
        return {"media_id": "new-single-generated-media", "not_published": True}


@pytest.mark.asyncio
async def test_final_add_once_after_two_absence_checks_preserves_text_and_reuses_ack(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, _auth, old = fixture(journal)
        remote = Remote(journal, old)
        final_auth = {"binding": {"absence_evidence": remote.evidence}}
        args = (gen, journal, manual, base, prepared, final_auth, "old-media", old, remote)
        receipt = await operator.execute(*args, AsyncMock(return_value=True))
        assert remote.absences == 2 and len(remote.adds) == 1 and len(remote.uploads) == 6
        assert remote.adds[0].title == prepared.title and "保留原文内容。" in remote.adds[0].content
        assert remote.adds[0].content_source_url is None
        assert await operator.execute(*args, AsyncMock(return_value=False)) == receipt
        assert len(remote.adds) == 1 and remote.absences == 2
        assert not remote.updates
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "reappeared"])
async def test_unknown_add_never_replays_and_reappeared_old_draft_blocks_add(tmp_path, failure):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, _auth, old = fixture(journal)
        remote = Remote(journal, old, unknown=failure == "unknown", changed=failure == "reappeared")
        args = (
            gen,
            journal,
            manual,
            base,
            prepared,
            {"binding": {"absence_evidence": remote.evidence}},
            "old-media",
            old,
            remote,
            AsyncMock(return_value=True),
        )
        with pytest.raises((TimeoutError, ValueError)):
            await operator.execute(*args)
        if failure == "unknown":
            with pytest.raises(ValueError, match="final_add_prior_outcome_unknown"):
                await operator.execute(*args)
            assert len(remote.adds) == 1
        else:
            assert remote.adds == []
            assert journal.read(operator.PREFIX + "-add-intent.json") is None
    finally:
        journal.close()


@pytest.mark.parametrize(
    "failure", ["old-id", "matching-secondary", "duplicate", "incomplete", "bool-count"]
)
def test_inventory_refuses_incomplete_duplicate_existing_or_secondary_matching_article(failure):
    payload = inventory()
    expected = {"title": "目标标题", "author": "目标作者", "digest": "目标摘要"}
    if failure == "old-id":
        payload["item"][0]["media_id"] = "old-media"
    elif failure == "matching-secondary":
        payload["item"][5]["content"]["news_item"].append(expected)
    elif failure == "duplicate":
        payload["item"][0]["media_id"] = payload["item"][1]["media_id"]
    elif failure == "incomplete":
        payload["item_count"] = 5
    else:
        payload["total_count"] = True
    with pytest.raises(ValueError):
        operator.inventory_evidence(payload, "old-media", expected)


@pytest.mark.parametrize("value", [None, "", 0, False, [], {"private": "PRIVATE_SENTINEL"}])
@pytest.mark.parametrize("field", ["author", "digest"])
def test_unrelated_inventory_optional_fields_accept_json_values_without_exposure(field, value):
    payload = inventory()
    payload["item"][0]["content"]["news_item"][0][field] = value
    expected = {"title": "目标标题", "author": "目标作者"}
    evidence = operator.inventory_evidence(payload, "old-media", expected)
    assert evidence == operator.inventory_evidence(payload, "old-media", expected)
    evidence["old_get_error_code"] = 40007
    operator.validate_evidence(evidence)
    assert "PRIVATE_SENTINEL" not in json.dumps(evidence, ensure_ascii=False)
    assert "旧标题" not in json.dumps(evidence, ensure_ascii=False)


def test_missing_null_empty_and_scalar_types_have_distinct_canonical_private_fingerprints():
    values = [
        {},
        {"author": None},
        {"author": ""},
        {"author": 0},
        {"author": False},
        {"author": "0"},
    ]
    fingerprints = {
        operator.optional_inventory_field_fingerprint(value, "author") for value in values
    }
    assert len(fingerprints) == len(values)
    assert operator.optional_inventory_field_fingerprint(
        {"author": {"a": 1, "b": 2}}, "author"
    ) == operator.optional_inventory_field_fingerprint({"author": {"b": 2, "a": 1}}, "author")
    payload = inventory()
    article = payload["item"][0]["content"]["news_item"][0]
    del article["author"]
    del article["digest"]
    assert (
        operator.inventory_evidence(payload, "old-media", {"title": "目标", "author": "作者"})[
            "matching_articles"
        ]
        == 0
    )


@pytest.mark.parametrize("value", [None, False, 12, {}, [], "", "  "])
def test_matching_title_with_unusable_author_is_ambiguous_and_stops(value):
    payload = inventory()
    payload["item"][5]["content"]["news_item"].append({"title": "目标", "author": value})
    with pytest.raises(ValueError, match="final_add_matching_title_author_ambiguous"):
        operator.inventory_evidence(payload, "old-media", {"title": "目标", "author": "作者"})


def test_matching_title_missing_author_stops_and_matching_author_ignores_missing_digest():
    payload = inventory()
    target = {"title": "目标"}
    payload["item"][5]["content"]["news_item"].append(target)
    expected = {"title": "目标", "author": "作者"}
    with pytest.raises(ValueError, match="final_add_matching_title_author_ambiguous"):
        operator.inventory_evidence(payload, "old-media", expected)
    target["author"] = "作者"
    with pytest.raises(ValueError, match="final_add_matching_article_exists"):
        operator.inventory_evidence(payload, "old-media", expected)
    target["digest"] = None
    with pytest.raises(ValueError, match="final_add_matching_article_exists"):
        operator.inventory_evidence(payload, "old-media", expected)


@pytest.mark.parametrize("title", [None, 0, {}, []])
def test_title_still_must_be_string(title):
    payload = inventory()
    payload["item"][0]["content"]["news_item"][0]["title"] = title
    with pytest.raises(ValueError, match="final_add_inventory_title_invalid"):
        operator.inventory_evidence(payload, "old-media", {"title": "目标", "author": "作者"})


@pytest.mark.asyncio
async def test_remote_requires_exact_40007_and_only_one_bounded_inventory_read():
    from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient

    requests = []

    async def handler(request):
        requests.append(request)
        if request.url.path.endswith("/get"):
            return httpx.Response(200, json={"errcode": 40007, "errmsg": "invalid media_id"})
        return httpx.Response(200, json=inventory())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WeChatOfficialAccountApiClient(
            client=http, app_id=SecretStr("fixture"), app_secret=SecretStr("secret")
        )
        remote = operator.Remote(client)
        remote.token = AsyncMock(return_value="token")
        evidence = await remote.absence(
            "old-media", {"title": "目标", "author": "作者", "digest": "摘要"}
        )
    assert evidence["old_target_absent"] is True and evidence["matching_articles"] == 0
    assert [r.url.path for r in requests] == ["/cgi-bin/draft/get", "/cgi-bin/draft/batchget"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{"errcode": 40001}, {"errcode": "40007"}, {"news_item": []}, {"errcode": 0}]
)
async def test_get_errors_other_than_explicit_invalid_media_are_not_absence(payload):
    from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        client = WeChatOfficialAccountApiClient(
            client=http, app_id=SecretStr("fixture"), app_secret=SecretStr("secret")
        )
        with pytest.raises(ValueError, match="final_add_old_target_not_proven_absent"):
            await operator.Remote(client).final_post(
                "/cgi-bin/draft/get", {"media_id": "old-media"}, "token"
            )


@pytest.mark.parametrize("step", ["-draft-update", "-upload-body-1", "-upload-cover"])
@pytest.mark.parametrize("suffix", ["-intent.json", "-result.json"])
def test_new_prefix_cannot_bypass_any_prior_update_effect(tmp_path, step, suffix):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        operator.ensure_prior_update_absent(journal, gen)
        journal.write(gen.PREFIX + step + suffix, {"sentinel": "prior"})
        with pytest.raises(ValueError, match="final_add_existing_update_effect"):
            operator.ensure_prior_update_absent(journal, gen)
    finally:
        journal.close()


@pytest.mark.parametrize("mutation", ["extra", "bad-hash", "bool-count"])
def test_absence_projection_cannot_persist_or_print_unrestricted_inventory(mutation):
    evidence = operator.inventory_evidence(
        inventory(), "old-media", {"title": "target", "author": "a"}
    )
    evidence["old_get_error_code"] = 40007
    operator.validate_evidence(evidence)
    if mutation == "extra":
        evidence["raw_inventory"] = "PRIVATE_SENTINEL"
    elif mutation == "bad-hash":
        evidence["inventory_fingerprint"] = "PRIVATE_SENTINEL"
    else:
        evidence["matching_articles"] = False
    with pytest.raises(ValueError, match="final_add_absence_evidence_invalid"):
        operator.validate_evidence(evidence)


@pytest.mark.asyncio
async def test_old_id_returned_from_add_is_not_saved_as_success_or_replayed(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, _auth, old = fixture(journal)
        remote = Remote(journal, old)
        remote.add = AsyncMock(return_value={"media_id": "old-media", "not_published": True})
        args = (
            gen,
            journal,
            manual,
            base,
            prepared,
            {"binding": {"absence_evidence": remote.evidence}},
            "old-media",
            old,
            remote,
            AsyncMock(return_value=True),
        )
        with pytest.raises(ValueError, match="final_add_old_receipt_returned"):
            await operator.execute(*args)
        assert journal.read(operator.PREFIX + "-add-intent.json") is not None
        assert journal.read(operator.PREFIX + "-add-result.json") is None
        with pytest.raises(ValueError, match="final_add_prior_outcome_unknown"):
            await operator.execute(*args)
        remote.add.assert_awaited_once()
    finally:
        journal.close()
