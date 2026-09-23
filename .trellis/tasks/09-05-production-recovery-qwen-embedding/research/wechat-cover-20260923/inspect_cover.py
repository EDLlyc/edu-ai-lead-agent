"""Read the current cover of the bound September 23 unpublished draft."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import replace_brand_illustrations as current
from app.core.config import get_settings
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)

Remote = current.base.Remote
_load_edition = current.base._load_edition
_load_target = current.base._load_target
_safe_media_id = current.base._safe_media_id


async def main() -> None:
    edition, root = await _load_edition()
    journal = LocalManualDraftJournal(Path(root), edition.account_fingerprint)
    client = WeChatOfficialAccountHttpClient(get_settings())
    try:
        draft_id, _ = _load_target(journal=journal, edition=edition)
        remote = Remote(client)
        try:
            article = await remote.get(draft_id)
        except ValueError:
            token = await remote.token()
            response = await client._client.post(
                client._base_url + "/cgi-bin/draft/get",
                params={"access_token": token},
                json={"media_id": draft_id},
                timeout=client._timeout,
            )
            try:
                result = response.json()
                error_code = result.get("errcode") if isinstance(result, dict) else None
            except ValueError:
                error_code = None
            print(
                json.dumps(
                    {
                        "status": "draft_get_failed",
                        "http_status": response.status_code,
                        "wechat_code": error_code,
                    }
                )
            )
            return
        thumb_id = _safe_media_id(article.get("thumb_media_id"))
        token = await remote.token()
        async with asyncio.timeout(client._total_timeout_seconds):
            async with client._client.stream(
                "POST",
                client._base_url + "/cgi-bin/material/get_material",
                params={"access_token": token},
                json={"media_id": thumb_id},
                follow_redirects=False,
                headers={"Accept-Encoding": "identity"},
                timeout=client._timeout,
            ) as response:
                if response.status_code != 200:
                    raise ValueError("cover_inspect_remote_error")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 4_000_000:
                        raise ValueError("cover_inspect_response_too_large")
                    chunks.append(chunk)
        body = b"".join(chunks)
        if not body.startswith(b"\xff\xd8\xff"):
            raise ValueError("cover_inspect_not_jpeg")
        path = Path("/app/cover/current-cover.jpg")
        path.write_bytes(body)
        print(
            json.dumps(
                {
                    "status": "fetched",
                    "bytes": len(body),
                    "title": article.get("title"),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await client.aclose()
        journal.close()


if __name__ == "__main__":
    asyncio.run(main())
