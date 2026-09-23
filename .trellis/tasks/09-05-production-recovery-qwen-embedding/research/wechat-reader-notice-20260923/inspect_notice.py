"""Read only: locate reader-visible internal notices in the bound draft."""

from __future__ import annotations

import asyncio
import json
import re
from html import unescape
from pathlib import Path

import replace_brand_illustrations as brand
from app.core.config import get_settings
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)

NOTICE = "按当前本地策略直接使用，发布权未验证；仅作上下文参考，不是事实证据。"
PARAGRAPH = re.compile(r"<p\b[^>]*>.*?</p>", re.DOTALL)
TAGS = re.compile(r"<[^>]+>")


async def main() -> None:
    base = brand.base
    edition, root = await base._load_edition()
    journal = LocalManualDraftJournal(Path(root), edition.account_fingerprint)
    client = WeChatOfficialAccountHttpClient(get_settings())
    try:
        draft_id, _ = base._load_target(journal=journal, edition=edition)
        article = await base.Remote(client).get(draft_id)
        content = article["content"]
        assert isinstance(content, str)
        matches = [
            match
            for match in PARAGRAPH.finditer(content)
            if unescape(TAGS.sub("", match.group())) == NOTICE
        ]
        slots = [
            len(base.VisibleHtml(content[: match.start()]).images) - 1
            for match in matches
        ]
        print(
            json.dumps(
                {
                    "title_matches": article.get("title")
                    == "从智能制造到家庭科学教育：家长如何帮孩子准备未来",
                    "notice_paragraphs": len(matches),
                    "preceding_image_slots": slots,
                    "total_images": len(base.VisibleHtml(content).images),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await client.aclose()
        journal.close()


if __name__ == "__main__":
    asyncio.run(main())
