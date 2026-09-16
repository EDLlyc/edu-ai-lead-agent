from __future__ import annotations

import importlib.util
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from app.application.services.wechat_official_account_draft import (
    WeChatPreparedDraft,
    WeChatPreparedMedia,
)
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from pydantic import SecretStr

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-05-production-recovery-qwen-embedding/research"
    / "visual-recovery-20260916/draft-generated-update-only.py"
)
SPEC = importlib.util.spec_from_file_location("draft_generated_update_only_operator", PATH)
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)
gen = operator.load_generation()


def fixture(journal):
    manual = SimpleNamespace(EDITION=UUID("41b26b7f-e792-56ff-bdfa-643171114056"))
    media = tuple(
        WeChatPreparedMedia(path, "image/jpeg", f"original-{i}".encode(), f"image-{i}.jpg")
        for i, path in enumerate(
            (
                "assets/header.jpg",
                *(f"assets/body-{i:02d}.jpg" for i in range(5)),
                "assets/footer.jpg",
            )
        )
    )
    html = "<p>保留原文内容。</p>" + "".join(f'<img src="{x.path}">' for x in media)
    base = WeChatPreparedDraft(
        "official_anchor",
        gen.ARTICLE_FP,
        gen.OLD_CONTENT_FP,
        "原始标题",
        "小赛",
        "原始摘要",
        None,
        html,
        media,
        media[0],
        False,
        False,
    )
    auth = {"authorized": "exact-fixture"}
    prepared = operator.build_prepared(
        base, tuple(b"new-body" + bytes([i]) for i in range(5)), b"cover", auth, ("pass",) * 6
    )
    old = {
        "title": base.title,
        "author": base.author,
        "digest": base.digest,
        "content": "<p>保留原文内容。</p>"
        + "".join(f'<img src="https://mmbiz.qpic.cn/old-{i}">' for i in range(7)),
        "thumb_media_id": "old-thumb",
        "content_source_url": None,
        "need_open_comment": False,
        "only_fans_can_comment": False,
    }
    prefix = f"single-{manual.EDITION.hex}"
    journal.write(prefix + "-add-1-intent.json", {"binding": "old-binding"})
    for i in (0, 6):
        intent = {
            "binding": "old-binding",
            "step": f"inline-{i}",
            "attempt": 1,
            "request": {"sha256": sha256(media[i].body).hexdigest()},
        }
        journal.write(prefix + f"-inline-{i}-1-intent.json", intent)
        journal.write(
            prefix + f"-inline-{i}-1-ack.json",
            {
                "intent_sha256": operator.manual_fingerprint(intent),
                "value": f"https://mmbiz.qpic.cn/old-{i}",
            },
        )
    return manual, base, prepared, auth, old


class Remote:
    def __init__(self, journal, old, *, unknown=False):
        self.journal, self.old, self.unknown = journal, old, unknown
        self.uploads, self.updates, self.gets = [], [], []

    async def get(self, media_id):
        self.gets.append(media_id)
        return self.old

    async def token(self):
        return "private-token"

    async def upload(self, media, token, *, cover):
        assert token == "private-token"
        self.uploads.append((media, cover))
        return {"value": "new-thumb" if cover else f"https://mmbiz.qpic.cn/new-{len(self.uploads)}"}

    async def update(self, media_id, article, token):
        assert self.journal.read(gen.PREFIX + "-draft-update-intent.json") is not None
        self.updates.append((media_id, article))
        if self.unknown:
            raise TimeoutError("private transport message")
        return {"acknowledged": True, "not_published": True}


@pytest.mark.asyncio
async def test_updates_same_draft_once_reuses_banners_preserves_words_and_audited_bytes(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, auth, old = fixture(journal)
        remote = Remote(journal, old)
        args = (gen, journal, manual, base, prepared, auth, "original-media-id", old, remote)
        receipt = await operator.execute(*args, AsyncMock(return_value=True))
        assert len(remote.uploads) == 6 and len(remote.updates) == 1
        assert remote.gets == ["original-media-id"] * 2
        assert [x[0].body for x in remote.uploads] == [x.body for x in prepared.body_media[1:6]] + [
            prepared.cover.body
        ]
        target, request = remote.updates[0]
        assert target == "original-media-id" and request.title == base.title
        assert request.author == base.author and request.digest == base.digest
        assert "保留原文内容。" in request.content
        assert "old-0" in request.content and "old-6" in request.content
        assert "old-1" not in request.content and request.content_source_url is None
        assert await operator.execute(*args, AsyncMock(return_value=False)) == receipt
        assert len(remote.uploads) == 6 and len(remote.updates) == 1
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_unknown_update_never_replays_or_reuploads(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, auth, old = fixture(journal)
        remote = Remote(journal, old, unknown=True)
        args = (
            gen,
            journal,
            manual,
            base,
            prepared,
            auth,
            "original-media-id",
            old,
            remote,
            AsyncMock(return_value=True),
        )
        with pytest.raises(TimeoutError):
            await operator.execute(*args)
        with pytest.raises(ValueError, match="generated_update_prior_outcome_unknown"):
            await operator.execute(*args)
        assert len(remote.uploads) == 6 and len(remote.updates) == 1
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_remote_edit_blocks_before_any_upload(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, auth, old = fixture(journal)
        remote = Remote(journal, {**old, "title": "编辑人员的新标题"})
        with pytest.raises(ValueError, match="generated_update_remote_edited"):
            await operator.execute(
                gen,
                journal,
                manual,
                base,
                prepared,
                auth,
                "original-media-id",
                old,
                remote,
                AsyncMock(return_value=True),
            )
        assert not remote.uploads and not remote.updates
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_http_remote_posts_only_update_to_exact_id_explicitly_clears_source_url():
    from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
    from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient

    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"errcode": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WeChatOfficialAccountApiClient(
            client=http, app_id=SecretStr("fixture-app"), app_secret=SecretStr("fixture-secret")
        )
        article = WeChatDraftArticleRequest(
            "标题", "作者", "摘要", "<p>正文</p>", None, "thumb", False, False
        )
        result = await operator.Remote(client).update("exact-target", article, "token")
    import json

    payload = json.loads(requests[0].content)
    assert len(requests) == 1 and requests[0].url.path == "/cgi-bin/draft/update"
    assert payload["media_id"] == "exact-target" and payload["index"] == 0
    assert payload["articles"]["content_source_url"] == ""
    assert "cover_info" not in payload["articles"] and result["acknowledged"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"errcode": False}, {"errcode": "0"}, {"errcode": 40003}])
async def test_update_requires_explicit_integer_zero_ack(response):
    remote = operator.Remote(None)
    remote.post = AsyncMock(return_value=response)
    from app.application.ports.wechat_official_account import WeChatDraftArticleRequest

    article = WeChatDraftArticleRequest(
        "标题", "作者", "摘要", "<p>正文</p>", None, "thumb", False, False
    )
    with pytest.raises(ValueError, match="generated_update_write_outcome_unknown"):
        await remote.update("exact-target", article, "token")


def test_readback_accepts_wechat_data_src_but_rejects_ambiguous_images():
    expected = '<p>正文</p><img src="https://mmbiz.qpic.cn/a">'
    actual = '<p>正文</p><img data-src="https://mmbiz.qpic.cn/a">'
    assert operator.VisibleHtml(expected).identity() == operator.VisibleHtml(actual).identity()
    with pytest.raises(ValueError, match="generated_update_remote_image_conflict"):
        operator.VisibleHtml(
            '<img src="https://mmbiz.qpic.cn/a" data-src="https://mmbiz.qpic.cn/b">'
        )
    with pytest.raises(ValueError, match="generated_update_remote_duplicate_attribute"):
        operator.VisibleHtml('<img src="https://mmbiz.qpic.cn/a" src="https://mmbiz.qpic.cn/b">')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/cgi-bin/draft/add", "/cgi-bin/freepublish/submit", "/cgi-bin/message/mass/sendall"]
)
async def test_remote_cannot_create_publish_or_mass_send(path):
    # No client is needed: the route is denied before touching transport or credentials.
    with pytest.raises(ValueError, match="generated_update_endpoint_forbidden"):
        await operator.Remote(None).post(path, "unused-token", payload={})


@pytest.mark.asyncio
async def test_unknown_upload_cannot_replay_or_advance_to_update(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        manual, base, prepared, auth, old = fixture(journal)

        class UnknownUpload(Remote):
            async def upload(self, media, token, *, cover):
                result = await super().upload(media, token, cover=cover)
                if len(self.uploads) == 2:
                    raise TimeoutError("private upload outcome unknown")
                return result

        remote = UnknownUpload(journal, old)
        args = (
            gen,
            journal,
            manual,
            base,
            prepared,
            auth,
            "original-media-id",
            old,
            remote,
            AsyncMock(return_value=True),
        )
        with pytest.raises(TimeoutError):
            await operator.execute(*args)
        with pytest.raises(ValueError, match="generated_update_prior_outcome_unknown"):
            await operator.execute(*args)
        assert len(remote.uploads) == 2 and remote.updates == []
        assert journal.read(gen.PREFIX + "-draft-update-intent.json") is None
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_thumb_request_preserves_type_and_access_token_query():
    from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient

    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"media_id": "new-thumb"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WeChatOfficialAccountApiClient(
            client=http, app_id=SecretStr("fixture-app"), app_secret=SecretStr("fixture-secret")
        )
        media = WeChatPreparedMedia("cover.jpg", "image/jpeg", b"cover", "cover.jpg")
        result = await operator.Remote(client).upload(media, "token", cover=True)
    assert result == {"value": "new-thumb"}
    assert len(requests) == 1
    assert requests[0].url.path == "/cgi-bin/material/add_material"
    assert dict(requests[0].url.params) == {"access_token": "token", "type": "thumb"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"errcode":5,"errcode":0}', b'{"errcode":0,"x":NaN}'])
async def test_http_response_rejects_duplicate_keys_and_nonfinite_constants(body):
    from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient

    async def handler(_request):
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WeChatOfficialAccountApiClient(
            client=http, app_id=SecretStr("fixture-app"), app_secret=SecretStr("fixture-secret")
        )
        with pytest.raises(ValueError, match="generated_update_response_"):
            await operator.Remote(client).post("/cgi-bin/draft/update", "token", payload={})
