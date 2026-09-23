"""Replace only the cover of the September 23 existing unpublished draft.

The task-local operator is bound to one delivered edition and one immutable
JPEG. It can upload one permanent thumbnail and update the same draft; it
cannot create or publish a draft. An ambiguous write is reconciled, not replayed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import stat
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import replace_brand_illustrations as brand
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
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

base = brand.base
VERSION = "xiaosai-cover-same-draft-update-20260923-v1"
EXPECTED_SHA256 = "0797be8fe22ba0f809a6bb35b2e07bc86fdadc24639499f22cc0f7ae90ad5029"
EXPECTED_TITLE = "从智能制造到家庭科学教育：家长如何帮孩子准备未来"


def _candidate(path: Path) -> bytes:
    info = path.stat(follow_symlinks=False)
    base.require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and 8 <= info.st_size < 64 * 1024,
        "cover_replace_candidate_invalid",
    )
    body = path.read_bytes()
    base.require(
        sha256(body).hexdigest() == EXPECTED_SHA256, "cover_replace_candidate_changed"
    )
    with Image.open(path) as image:
        base.require(
            image.format == "JPEG" and image.size == (1175, 500),
            "cover_replace_geometry_invalid",
        )
        image.verify()
    return body


def _body_guard(
    journal: LocalManualDraftJournal, edition_id: str, current: dict[str, object]
) -> str:
    """Require that the earlier five-image correction still matches its receipt."""
    prefix = f"xiaosai-badge-{edition_id}"
    intent = journal.read(prefix + "-draft-update-intent.json")
    ack = journal.read(prefix + "-draft-update-ack.json")
    original = journal.read(prefix + "-original.json")
    receipt = journal.read(prefix + "-readback.json")
    base.require(
        isinstance(intent, dict)
        and isinstance(ack, dict)
        and isinstance(original, dict)
        and isinstance(receipt, dict)
        and ack.get("intent_sha256") == journal_fingerprint(intent)
        and ack.get("value") == {"acknowledged": True, "not_published": True}
        and receipt.get("verified") is True
        and receipt.get("binding") == intent.get("binding"),
        "cover_replace_body_receipt_invalid",
    )
    request = intent.get("request")
    urls = request.get("replacement_urls") if isinstance(request, dict) else None
    base.require(
        isinstance(urls, list)
        and len(urls) == 5
        and all(isinstance(url, str) for url in urls),
        "cover_replace_body_receipt_invalid",
    )
    assert isinstance(urls, list)
    brand._verify_replacement(
        current=current, original=original, replacement_urls=tuple(urls)
    )
    base.require(current.get("title") == EXPECTED_TITLE, "cover_replace_title_changed")
    return journal_fingerprint(intent)


def _verify_cover(
    current: dict[str, object], original: dict[str, object], new_thumb_id: str
) -> None:
    base.require(
        current.get("thumb_media_id") == new_thumb_id, "cover_replace_readback_mismatch"
    )
    base._same_original(
        {**current, "thumb_media_id": original.get("thumb_media_id")}, original
    )


async def run(mode: str, candidate_path: Path) -> dict[str, object]:
    base.require(mode in {"plan", "apply", "reconcile"}, "cover_replace_mode_invalid")
    body = _candidate(candidate_path)
    edition, root = await base._load_edition()
    base._require_existing_journal_root(root=root, account=edition.account_fingerprint)
    journal = LocalManualDraftJournal(Path(root), edition.account_fingerprint)
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        draft_id, _ = base._load_target(journal=journal, edition=edition)
        prefix = f"xiaosai-cover-{edition.id.hex}"
        client = WeChatOfficialAccountHttpClient(get_settings())
        remote = base.Remote(client)
        current = await remote.get(draft_id)
        existing_update_intent = journal.read(prefix + "-draft-update-intent.json")
        existing_update_ack = journal.read(prefix + "-draft-update-ack.json")
        original = journal.read(prefix + "-original.json")

        if existing_update_intent is not None:
            base.require(isinstance(original, dict), "cover_replace_original_missing")
            body_receipt = _body_guard(journal, edition.id.hex, original)
            binding = existing_update_intent.get("binding")
            base.require(
                isinstance(binding, dict)
                and binding.get("version") == VERSION
                and binding.get("run_id") == str(brand.RUN_ID)
                and binding.get("edition_id") == str(edition.id)
                and binding.get("account") == edition.account_fingerprint
                and binding.get("target_draft_fingerprint")
                == sha256(draft_id.encode()).hexdigest()
                and binding.get("original_thumb_fingerprint")
                == sha256(
                    base._safe_media_id(original.get("thumb_media_id")).encode()
                ).hexdigest()
                and binding.get("body_receipt_fingerprint") == body_receipt
                and binding.get("candidate_sha256") == EXPECTED_SHA256,
                "cover_replace_intent_changed",
            )
            request = existing_update_intent.get("request")
            base.require(isinstance(request, dict), "cover_replace_intent_changed")
            assert isinstance(request, dict)
            new_thumb_id = base._safe_media_id(request.get("new_thumb_media_id"))
            if existing_update_ack is None:
                try:
                    _verify_cover(current, original, new_thumb_id)
                except ValueError:
                    return {
                        "status": "outcome_unknown_reconcile_only",
                        "not_published": True,
                    }
                status = "readback_verified_after_unknown"
            else:
                base.require(
                    existing_update_ack.get("intent_sha256")
                    == journal_fingerprint(existing_update_intent)
                    and existing_update_ack.get("value")
                    == {"acknowledged": True, "not_published": True},
                    "cover_replace_ack_changed",
                )
                _verify_cover(current, original, new_thumb_id)
                status = "readback_verified"
            if mode == "plan":
                return {"status": status, "not_published": True}
            receipt = {"binding": binding, "verified": True}
            prior = journal.read(prefix + "-readback.json")
            if prior is None:
                journal.write(prefix + "-readback.json", receipt)
            else:
                base.require(prior == receipt, "cover_replace_readback_changed")
            return {"status": status, "not_published": True}

        base.require(existing_update_ack is None, "cover_replace_ack_without_intent")
        body_receipt = _body_guard(journal, edition.id.hex, current)
        original_thumb_id = base._safe_media_id(current.get("thumb_media_id"))
        binding = {
            "version": VERSION,
            "run_id": str(brand.RUN_ID),
            "edition_id": str(edition.id),
            "account": edition.account_fingerprint,
            "target_draft_fingerprint": sha256(draft_id.encode()).hexdigest(),
            "original_thumb_fingerprint": sha256(
                original_thumb_id.encode()
            ).hexdigest(),
            "article_fingerprint": edition.article_fingerprint,
            "content_fingerprint": edition.content_fingerprint,
            "body_receipt_fingerprint": body_receipt,
            "candidate_sha256": EXPECTED_SHA256,
        }
        if mode == "plan":
            return {"status": "planned", "cover": 1, "not_published": True}
        base.require(mode == "apply", "cover_replace_reconcile_without_intent")
        base._claim(journal, prefix=prefix, binding=binding)
        stored_original = journal.read(prefix + "-original.json")
        if stored_original is None:
            journal.write(prefix + "-original.json", current)
        else:
            base._same_original(current, stored_original)
            base.require(
                current.get("content") == stored_original.get("content"),
                "cover_replace_original_changed",
            )

        async def upload() -> dict[str, object]:
            result = await client.upload_thumb(body, "image/jpeg", "cover.jpg")
            return {"media_id": base._safe_media_id(result.media_id)}

        upload_ack = await base._once(
            journal=journal,
            prefix=prefix,
            step="thumb-upload",
            binding=binding,
            request={
                "sha256": EXPECTED_SHA256,
                "mime_type": "image/jpeg",
                "width": 1175,
                "height": 500,
            },
            send=upload,
        )
        new_thumb_id = base._safe_media_id(upload_ack.get("media_id"))
        before_update = await remote.get(draft_id)
        base._same_original(before_update, current)
        base.require(
            before_update.get("content") == current.get("content"),
            "cover_replace_remote_edited",
        )
        article = replace(
            base._replacement_article(
                original=current, rewritten_html=str(current["content"])
            ),
            thumb_media_id=new_thumb_id,
        )

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
                "new_thumb_media_id": new_thumb_id,
                "request_fingerprint": fingerprint(asdict(article)),
            },
            send=update,
        )
        readback = await remote.get(draft_id)
        _verify_cover(readback, current, new_thumb_id)
        journal.write(prefix + "-readback.json", {"binding": binding, "verified": True})
        return {
            "status": "same_draft_cover_updated",
            "cover": 1,
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
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.mode, args.candidate))
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
        code = str(error) if isinstance(error, ValueError) else "cover_replace_stopped"
        if (
            re.fullmatch(r"(cover_replace|xiaosai_replace)_[a-z0-9_]{1,58}", code)
            is None
        ):
            code = "cover_replace_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
