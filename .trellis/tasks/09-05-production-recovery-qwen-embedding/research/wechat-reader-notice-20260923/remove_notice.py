"""Remove only two internal news-image notices from one unpublished draft.

This task-local operator cannot add or publish a draft. It journals a single
same-ID `draft/update` and reconciles ambiguous outcomes without replay.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict
from hashlib import sha256
from html import unescape
from pathlib import Path

import replace_brand_illustrations as brand
import replace_cover as cover
from app.application.ports.wechat_official_account import WeChatOfficialAccountError
from app.core.config import get_settings
from app.domain.official_account_local import fingerprint
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    fingerprint as journal_fingerprint,
)
from sqlalchemy.exc import SQLAlchemyError

base = brand.base
NOTICE = "按当前本地策略直接使用，发布权未验证；仅作上下文参考，不是事实证据。"
EXPECTED_TITLE = "从智能制造到家庭科学教育：家长如何帮孩子准备未来"
VERSION = "xiaosai-context-notice-same-draft-update-20260923-v1"
PARAGRAPH = re.compile(r"<p\b[^>]*>.*?</p>", re.DOTALL)
TAGS = re.compile(r"<[^>]+>")


def _strip_notices(content: str) -> str:
    matches = [
        match
        for match in PARAGRAPH.finditer(content)
        if unescape(TAGS.sub("", match.group())) == NOTICE
    ]
    slots = [
        len(base.VisibleHtml(content[: match.start()]).images) - 1 for match in matches
    ]
    base.require(
        content.count(NOTICE) == 2 and len(matches) == 2 and slots == [1, 6],
        "notice_replace_target_changed",
    )
    rewritten = content
    for match in reversed(matches):
        rewritten = rewritten[: match.start()] + rewritten[match.end() :]
    before, after = (
        base.VisibleHtml(content).identity(),
        base.VisibleHtml(rewritten).identity(),
    )
    base.require(
        NOTICE not in rewritten
        and after[1] == before[1]
        and after[2] == before[2]
        and before[0].replace(NOTICE, "").split() == after[0].split(),
        "notice_replace_rewrite_invalid",
    )
    return rewritten


def _cover_guard(
    journal: LocalManualDraftJournal, edition_hex: str, current: dict[str, object]
) -> str:
    prefix = f"xiaosai-cover-{edition_hex}"
    intent = journal.read(prefix + "-draft-update-intent.json")
    ack = journal.read(prefix + "-draft-update-ack.json")
    receipt = journal.read(prefix + "-readback.json")
    original = journal.read(prefix + "-original.json")
    base.require(
        isinstance(intent, dict)
        and isinstance(ack, dict)
        and isinstance(receipt, dict)
        and isinstance(original, dict)
        and ack.get("intent_sha256") == journal_fingerprint(intent)
        and ack.get("value") == {"acknowledged": True, "not_published": True}
        and receipt.get("binding") == intent.get("binding")
        and receipt.get("verified") is True,
        "notice_replace_cover_receipt_invalid",
    )
    request = intent.get("request")
    base.require(isinstance(request, dict), "notice_replace_cover_receipt_invalid")
    assert isinstance(request, dict)
    new_thumb_id = base._safe_media_id(request.get("new_thumb_media_id"))
    cover._verify_cover(current, original, new_thumb_id)
    return journal_fingerprint(intent)


def _verify_readback(current: dict[str, object], original: dict[str, object]) -> None:
    old_fields, new_fields = (
        base._article_fields(original),
        base._article_fields(current),
    )
    for key in (
        "title",
        "author",
        "digest",
        "content_source_url",
        "thumb_media_id",
        "need_open_comment",
        "only_fans_can_comment",
    ):
        base.require(
            old_fields[key] == new_fields[key], "notice_replace_readback_field_changed"
        )
    old_html, new_html = old_fields["content"], new_fields["content"]
    assert isinstance(old_html, str) and isinstance(new_html, str)
    expected = base.VisibleHtml(_strip_notices(old_html)).identity()
    actual = base.VisibleHtml(new_html).identity()
    base.require(
        NOTICE not in new_html
        and actual[0] == expected[0]
        and actual[2] == expected[2]
        and len(actual[1]) == len(expected[1]) == 9
        and all(
            base._same_wechat_cdn_display_variant(want, got)
            for want, got in zip(expected[1], actual[1], strict=True)
        ),
        "notice_replace_readback_mismatch",
    )


async def run(mode: str) -> dict[str, object]:
    base.require(mode in {"plan", "apply", "reconcile"}, "notice_replace_mode_invalid")
    edition, root = await base._load_edition()
    base._require_existing_journal_root(root=root, account=edition.account_fingerprint)
    journal = LocalManualDraftJournal(Path(root), edition.account_fingerprint)
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        draft_id, _ = base._load_target(journal=journal, edition=edition)
        prefix = f"xiaosai-context-notice-{edition.id.hex}"
        client = WeChatOfficialAccountHttpClient(get_settings())
        remote = base.Remote(client)
        current = await remote.get(draft_id)
        update_intent = journal.read(prefix + "-draft-update-intent.json")
        update_ack = journal.read(prefix + "-draft-update-ack.json")
        if update_intent is not None:
            original = journal.read(prefix + "-original.json")
            base.require(isinstance(original, dict), "notice_replace_original_missing")
            binding = update_intent.get("binding")
            base.require(
                isinstance(binding, dict)
                and binding.get("version") == VERSION
                and binding.get("run_id") == str(brand.RUN_ID)
                and binding.get("edition_id") == str(edition.id)
                and binding.get("account") == edition.account_fingerprint
                and binding.get("target_draft_fingerprint")
                == sha256(draft_id.encode()).hexdigest()
                and binding.get("original_content_sha256")
                == sha256(str(original.get("content")).encode()).hexdigest(),
                "notice_replace_intent_changed",
            )
            if update_ack is None:
                try:
                    _verify_readback(current, original)
                except ValueError:
                    return {
                        "status": "outcome_unknown_reconcile_only",
                        "not_published": True,
                    }
                status = "readback_verified_after_unknown"
            else:
                base.require(
                    update_ack.get("intent_sha256")
                    == journal_fingerprint(update_intent)
                    and update_ack.get("value")
                    == {"acknowledged": True, "not_published": True},
                    "notice_replace_ack_changed",
                )
                _verify_readback(current, original)
                status = "readback_verified"
            if mode != "plan":
                receipt = {"binding": binding, "verified": True}
                prior = journal.read(prefix + "-readback.json")
                if prior is None:
                    journal.write(prefix + "-readback.json", receipt)
                else:
                    base.require(prior == receipt, "notice_replace_readback_changed")
            return {"status": status, "not_published": True}

        base.require(update_ack is None, "notice_replace_ack_without_intent")
        cover_receipt = _cover_guard(journal, edition.id.hex, current)
        base.require(
            current.get("title") == EXPECTED_TITLE, "notice_replace_title_changed"
        )
        content = current.get("content")
        base.require(isinstance(content, str), "notice_replace_article_invalid")
        assert isinstance(content, str)
        rewritten = _strip_notices(content)
        binding = {
            "version": VERSION,
            "run_id": str(brand.RUN_ID),
            "edition_id": str(edition.id),
            "account": edition.account_fingerprint,
            "target_draft_fingerprint": sha256(draft_id.encode()).hexdigest(),
            "cover_receipt_fingerprint": cover_receipt,
            "original_content_sha256": sha256(content.encode()).hexdigest(),
            "article_fingerprint": edition.article_fingerprint,
            "content_fingerprint": edition.content_fingerprint,
        }
        if mode == "plan":
            return {"status": "planned", "notices": 2, "not_published": True}
        base.require(mode == "apply", "notice_replace_reconcile_without_intent")
        base._claim(journal, prefix=prefix, binding=binding)
        prior_original = journal.read(prefix + "-original.json")
        if prior_original is None:
            journal.write(prefix + "-original.json", current)
        else:
            base._same_original(current, prior_original)
            base.require(
                current.get("content") == prior_original.get("content"),
                "notice_replace_original_changed",
            )
        before_update = await remote.get(draft_id)
        base._same_original(before_update, current)
        base.require(
            before_update.get("content") == content, "notice_replace_remote_edited"
        )
        article = base._replacement_article(original=current, rewritten_html=rewritten)

        async def update() -> dict[str, object]:
            await remote.update(
                media_id=draft_id, article=article, token=await remote.token()
            )
            return {"acknowledged": True, "not_published": True}

        await base._once(
            journal=journal,
            prefix=prefix,
            step="draft-update",
            binding=binding,
            request={
                "request_fingerprint": fingerprint(asdict(article)),
                "removed_notice_count": 2,
            },
            send=update,
        )
        readback = await remote.get(draft_id)
        _verify_readback(readback, current)
        journal.write(prefix + "-readback.json", {"binding": binding, "verified": True})
        return {
            "status": "same_draft_notice_removed",
            "notices": 2,
            "not_published": True,
            "readback_verified": True,
        }
    finally:
        if client is not None:
            await client.aclose()
        journal.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "reconcile"))
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.mode))
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        SQLAlchemyError,
        TimeoutError,
        TypeError,
        ValueError,
        WeChatOfficialAccountError,
    ) as error:
        code = str(error) if isinstance(error, ValueError) else "notice_replace_stopped"
        if (
            re.fullmatch(
                r"(notice_replace|cover_replace|xiaosai_replace)_[a-z0-9_]{1,58}", code
            )
            is None
        ):
            code = "notice_replace_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
