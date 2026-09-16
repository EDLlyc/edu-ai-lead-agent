from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.application.ports.wechat_official_account import WeChatMpOutcomeUnknownError
from app.domain.official_account_local import ArticleImageBlock
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from test_official_account_export import _news_context_bundle_input
from test_official_account_single_edition import Client, edition, prepared

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-05-production-recovery-qwen-embedding/research"
    / "visual-recovery-20260916/manual-draft-now.py"
)
SPEC = importlib.util.spec_from_file_location("manual_draft_now_operator", PATH)
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)


def auth_args(value):
    return dict(
        prepared=value,
        source_identity="d" * 64,
        original_expiry=datetime(2026, 9, 16, 8, tzinfo=UTC),
        now=datetime(2026, 9, 16, 10, tzinfo=UTC),
    )


def test_authorization_is_fixed_and_existing_single_write_refuses_new_authority(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        args = auth_args(prepared())
        auth = operator.authorize(journal, [], **args)
        assert auth["binding"]["generated"] is False
        assert auth["binding"]["max_attempts"] == 1
        with pytest.raises(ValueError, match="prior_write"):
            operator.authorize(
                journal, [f"single-{operator.EDITION.hex}-add-1-intent.json"], **args
            )
        journal.write(operator.AUTH_NAME, auth)
        args["now"] += timedelta(minutes=30)
        assert operator.authorize(journal, [], **args) == auth
        assert journal.manual_history(operator.ACCOUNT) == ()
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_single_add_ack_reused_and_unknown_never_replayed(tmp_path, unknown):
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    value = replace(prepared(), content_source_url=None)
    selected = edition(id=operator.EDITION, account=operator.ACCOUNT)
    auth = {"expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
    first = Client()
    if unknown:

        async def fail_add(article):
            first.calls.append("add")
            raise WeChatMpOutcomeUnknownError(endpoint="draft_add")

        first.add_draft = fail_add
    try:
        if unknown:
            with pytest.raises(WeChatMpOutcomeUnknownError):
                await operator.execute(
                    value, selected, journal, first, auth, AsyncMock(return_value=True)
                )
        else:
            result = await operator.execute(
                value, selected, journal, first, auth, AsyncMock(return_value=True)
            )
            assert result["not_published"] and not result["readback_verified"]
        assert first.calls == ["inline", "thumb", "add"]
        second = Client()
        if unknown:
            with pytest.raises(WeChatMpOutcomeUnknownError):
                await operator.execute(
                    value, selected, journal, second, auth, AsyncMock(return_value=True)
                )
        else:
            assert (
                await operator.execute(
                    value, selected, journal, second, auth, AsyncMock(return_value=True)
                )
                == result
            )
        assert second.calls == []
        # Existing consumer does not import this as a conflicting manual owner.
        assert journal.manual_history(operator.ACCOUNT) == ()
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_prepare_real_rendering_preserves_text_and_catalog_bytes_with_banners():
    bundle = await _news_context_bundle_input()
    article = bundle.article
    selection = article.media_selection
    assignments = tuple(
        selection.assignments[i % len(selection.assignments)].model_copy(
            update={"ordinal": i, "section_index": i}
        )
        for i in range(5)
    )
    sections = tuple(
        article.sections[i % len(article.sections)].model_copy(
            update={
                "blocks": (
                    *(
                        block
                        for block in article.sections[i % len(article.sections)].blocks
                        if not isinstance(block, ArticleImageBlock)
                    ),
                    ArticleImageBlock(kind="image", slot_key=f"body-{i}", alt_text="小赛"),
                )
            }
        )
        for i in range(5)
    )
    article = article.model_copy(
        update={
            "sections": sections,
            "media_selection": selection.model_copy(update={"assignments": assignments}),
        }
    )
    catalog = AsyncMock()
    catalog.read_publication_bytes.return_value = bundle.body_bytes_items[0]
    result = await operator.prepare(article, catalog)
    assert catalog.read_publication_bytes.await_count == 5
    assert result.title == article.title and result.author == article.author
    assert result.digest == article.digest and result.content_source_url is None
    assert result.visual_pipeline_version is None
    assert len(result.body_media) == 7 and len(result.cover.body) < 65536
    assert result.body_media[0].path == "assets/chengyue-top-intro.jpg"
    assert result.body_media[-1].path == "assets/xiaosai-marketing-footer.jpg"
    assert "阅读原文" not in result.body_html and 'href="' not in result.body_html

    class Text(HTMLParser):
        value = ""

        def handle_data(self, data):
            self.value += data

    parsed = Text()
    parsed.feed(result.body_html)
    assert article.lead in parsed.value and article.conclusion in parsed.value
    for section in article.sections:
        for block in section.blocks:
            if hasattr(block, "text"):
                assert block.text in parsed.value
