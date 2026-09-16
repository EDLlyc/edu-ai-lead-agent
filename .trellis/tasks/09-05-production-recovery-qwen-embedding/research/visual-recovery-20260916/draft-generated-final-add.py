"""One final generated draft ONLY after exact old-target absence reconciliation.

Plan reads the exact old target and the complete six-item inventory, prints only
safe hashes/counts, and makes no writes. --apply --inventory-fingerprint HASH
permits six journaled uploads and one draft/add after repeating reconciliation.
No model calls, SQL writes, update, publish, mass-send or unknown-write replay.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path

from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
from app.domain.official_account_local import fingerprint
from app.domain.official_account_strict_layout import strict_escaped_upload_url
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
    _validate_draft_article,
)

UPDATE_SHA = "e982e292f49c405b13b29581ff7f1a8f0c64cfddad9f2210f335b9f68d8f044e"
PREFIX = "final-generated-add-41b26b7fe79256ffbdfa643171114056"
EXPECTED_TOTAL = 6


def require(condition, code="final_add_binding_invalid"):
    if not condition:
        raise ValueError(code)


def load_update():
    path = Path(__file__).with_name("draft-generated-update-only.py")
    require(
        sha256(path.read_bytes()).hexdigest() == UPDATE_SHA, "final_add_source_changed"
    )
    spec = importlib.util.spec_from_file_location("verified_generated_update", path)
    if spec is None or spec.loader is None:
        raise ValueError("final_add_import_invalid")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update = load_update()


def validate_evidence(evidence):
    require(
        isinstance(evidence, dict)
        and set(evidence)
        == {
            "version",
            "total",
            "old_target_absent",
            "matching_articles",
            "inventory_fingerprint",
            "old_get_error_code",
        }
        and evidence["version"] == "sep16-absent-target-inventory-v1"
        and type(evidence["total"]) is int
        and evidence["total"] == EXPECTED_TOTAL
        and evidence["old_target_absent"] is True
        and type(evidence["matching_articles"]) is int
        and evidence["matching_articles"] == 0
        and type(evidence["old_get_error_code"]) is int
        and evidence["old_get_error_code"] == 40007
        and isinstance(evidence["inventory_fingerprint"], str)
        and re.fullmatch(r"[0-9a-f]{64}", evidence["inventory_fingerprint"])
        is not None,
        "final_add_absence_evidence_invalid",
    )


def ensure_prior_update_absent(journal, gen):
    for step in (
        "-draft-update",
        *(f"-upload-body-{i}" for i in range(1, 6)),
        "-upload-cover",
    ):
        require(
            all(
                journal.read(gen.PREFIX + step + suffix) is None
                for suffix in ("-intent.json", "-result.json")
            ),
            "final_add_existing_update_effect",
        )


def optional_inventory_field_fingerprint(article, key):
    if key not in article:
        return fingerprint("optional-inventory-field-v1", "missing")
    value = article[key]
    # Optional provider fields are not identity evidence for unrelated titles.
    # Preserve missing/null/type differences privately instead of coercing them
    # to text (or leaking the original field in the evidence projection).
    require(
        type(value) in {type(None), str, bool, int, float, list, dict},
        "final_add_inventory_optional_field_invalid",
    )
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return fingerprint(
        "optional-inventory-field-v1", "present", type(value).__name__, canonical
    )


def inventory_evidence(payload, old_media_id, expected):
    require(isinstance(payload, dict))
    items = payload.get("item")
    require(
        type(payload.get("total_count")) is int
        and type(payload.get("item_count")) is int
        and payload["total_count"] == payload["item_count"] == EXPECTED_TOTAL
        and isinstance(items, list)
        and len(items) == EXPECTED_TOTAL,
        "final_add_inventory_incomplete",
    )
    projection, seen = [], set()
    for item in items:
        require(isinstance(item, dict))
        media_id = item.get("media_id")
        require(
            isinstance(media_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", media_id) is not None
        )
        require(media_id not in seen, "final_add_inventory_duplicate")
        require(media_id != old_media_id, "final_add_old_draft_exists")
        seen.add(media_id)
        content = item.get("content")
        require(isinstance(content, dict))
        articles = content.get("news_item")
        require(isinstance(articles, list) and 1 <= len(articles) <= 8)
        rows = []
        for article in articles:
            require(
                isinstance(article, dict) and isinstance(article.get("title"), str),
                "final_add_inventory_title_invalid",
            )
            if article["title"] == expected["title"]:
                require(
                    isinstance(article.get("author"), str)
                    and bool(article["author"].strip()),
                    "final_add_matching_title_author_ambiguous",
                )
                require(
                    article["author"] != expected["author"],
                    "final_add_matching_article_exists",
                )
            rows.append(
                fingerprint(
                    article["title"],
                    optional_inventory_field_fingerprint(article, "author"),
                    optional_inventory_field_fingerprint(article, "digest"),
                )
            )
        projection.append((sha256(media_id.encode()).hexdigest(), rows))
    return {
        "version": "sep16-absent-target-inventory-v1",
        "total": EXPECTED_TOTAL,
        "old_target_absent": True,
        "matching_articles": 0,
        "inventory_fingerprint": fingerprint(sorted(projection)),
    }


class Remote:
    def __init__(self, client):
        self.client = client
        self._uploads = update.Remote(client)

    async def token(self):
        return await self._uploads.token()

    async def upload(self, media, token, *, cover):
        return await self._uploads.upload(media, token, cover=cover)

    async def final_post(self, path, payload, token):
        require(
            path
            in {"/cgi-bin/draft/get", "/cgi-bin/draft/batchget", "/cgi-bin/draft/add"},
            "final_add_endpoint_forbidden",
        )
        async with asyncio.timeout(self.client._total_timeout_seconds):
            async with self.client._client.stream(
                "POST",
                self.client._base_url + path,
                params={"access_token": token},
                json=payload,
                follow_redirects=False,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                timeout=self.client._timeout,
            ) as response:
                require(
                    200 <= response.status_code < 300
                    and response.headers.get("content-encoding", "identity").casefold()
                    in {"", "identity"},
                    "final_add_response_not_acknowledged",
                )
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    require(
                        size
                        <= (2 * 1024 * 1024 if path.endswith("batchget") else 65536),
                        "final_add_response_too_large",
                    )
                    chunks.append(chunk)
        result = json.loads(
            b"".join(chunks),
            object_pairs_hook=update.unique_object,
            parse_constant=update.invalid_constant,
        )
        require(isinstance(result, dict), "final_add_response_invalid")
        if path.endswith("/get"):
            require(
                type(result.get("errcode")) is int and result["errcode"] == 40007,
                "final_add_old_target_not_proven_absent",
            )
        else:
            require(
                "errcode" not in result
                or (type(result["errcode"]) is int and result["errcode"] == 0),
                "final_add_response_not_acknowledged",
            )
        return result

    async def absence(self, media_id, expected):
        token = await self.token()
        await self.final_post("/cgi-bin/draft/get", {"media_id": media_id}, token)
        payload = await self.final_post(
            "/cgi-bin/draft/batchget",
            {"offset": 0, "count": 20, "no_content": 0},
            token,
        )
        return {
            **inventory_evidence(payload, media_id, expected),
            "old_get_error_code": 40007,
        }

    async def add(self, article, token):
        value = asdict(article)
        value.update(
            article_type="news",
            content_source_url="",
            need_open_comment=int(article.need_open_comment),
            only_fans_can_comment=int(article.only_fans_can_comment),
        )
        result = await self.final_post(
            "/cgi-bin/draft/add", {"articles": [value]}, token
        )
        media_id = result.get("media_id")
        require(
            isinstance(media_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", media_id) is not None,
            "final_add_receipt_invalid",
        )
        return {"media_id": media_id, "not_published": True}


def authorization(
    journal, manual, prepared, auth, evidence, source, original_receipt, now
):
    validate_evidence(evidence)
    binding = {
        "version": "sep16-final-generated-add-v1",
        "account": manual.ACCOUNT,
        "edition_id": str(manual.EDITION),
        "article_fingerprint": prepared.article_fingerprint,
        "generated_content_fingerprint": prepared.content_fingerprint,
        "generation_authorization_fingerprint": fingerprint(auth),
        "absence_evidence": evidence,
        "source_identity": source,
        "original_receipt_identity": original_receipt,
        "original_missing_draft_fingerprint": update.load_generation().OLD_RECEIPT_FP,
        "maximum_adds": 1,
    }
    previous = journal.read(PREFIX + "-authorization.json")
    if previous is not None:
        require(previous.get("binding") == binding, "final_add_authorization_changed")
        start, end = (
            datetime.fromisoformat(previous["authorized_at"]),
            datetime.fromisoformat(previous["expires_at"]),
        )
        require(
            start.utcoffset() is not None
            and end.utcoffset() is not None
            and start < end <= start + timedelta(hours=2)
            and start.astimezone(manual.ZONE).date()
            == end.astimezone(manual.ZONE).date()
            == manual.DAY
        )
        return previous
    require(now.astimezone(manual.ZONE).date() == manual.DAY, "final_add_wrong_day")
    return {
        "binding": binding,
        "authorized_at": now.isoformat(),
        "expires_at": min(
            now + timedelta(hours=2),
            datetime.combine(manual.DAY, time.max, manual.ZONE),
        ).isoformat(),
    }


async def execute(
    gen,
    journal,
    manual,
    base,
    prepared,
    final_auth,
    old_media_id,
    old_request,
    remote,
    allowed,
):
    name = PREFIX + "-add"
    binding = {
        "authorization_fingerprint": fingerprint(final_auth),
        "content_fingerprint": prepared.content_fingerprint,
        "operation": "reconciled_single_draft_add",
    }
    previous, ack = (
        journal.read(name + "-intent.json"),
        journal.read(name + "-result.json"),
    )
    if previous is not None:
        require(previous.get("binding") == binding)
        require(ack is not None, "final_add_prior_outcome_unknown")
        require(
            ack.get("intent_fingerprint") == fingerprint(previous)
            and ack.get("not_published") is True
        )
        require(
            isinstance(ack.get("media_id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ack["media_id"]) is not None
        )
        require(ack["media_id"] != old_media_id, "final_add_old_receipt_returned")
        return sha256(ack["media_id"].encode()).hexdigest()
    require(ack is None)
    expected = final_auth["binding"]["absence_evidence"]
    validate_evidence(expected)
    require(await allowed(), "final_add_authority_expired")
    require(
        await remote.absence(old_media_id, old_request) == expected,
        "final_add_inventory_changed",
    )
    original_intent = journal.read(f"single-{manual.EDITION.hex}-add-1-intent.json")
    urls = update.banner_urls(journal, manual, base, original_intent)
    rewritten = prepared.body_html
    for i, media in enumerate(prepared.body_media):
        if i not in urls:
            token = await remote.token()

            async def upload(media=media, token=token):
                return await remote.upload(media, token, cover=False)

            result = await gen.once(
                journal,
                PREFIX + f"-body-{i}",
                {
                    "binding": binding,
                    "sha256": sha256(media.body).hexdigest(),
                    "ordinal": i,
                },
                upload,
                allowed,
            )
            urls[i] = strict_escaped_upload_url(result["value"])
        needle = f'src="{media.path}"'
        require(rewritten.count(needle) == 1)
        rewritten = rewritten.replace(needle, f'src="{urls[i]}"', 1)
    token = await remote.token()

    async def upload_cover():
        return await remote.upload(prepared.cover, token, cover=True)

    thumb = await gen.once(
        journal,
        PREFIX + "-cover",
        {"binding": binding, "sha256": sha256(prepared.cover.body).hexdigest()},
        upload_cover,
        allowed,
    )
    article = WeChatDraftArticleRequest(
        prepared.title,
        prepared.author,
        prepared.digest,
        rewritten,
        None,
        thumb["value"],
        prepared.need_open_comment,
        prepared.only_fans_can_comment,
    )
    _validate_draft_article(article)
    require(
        await remote.absence(old_media_id, old_request) == expected,
        "final_add_inventory_changed",
    )
    token = await remote.token()

    async def add():
        value = await remote.add(article, token)
        require(value.get("media_id") != old_media_id, "final_add_old_receipt_returned")
        return value

    result = await gen.once(
        journal,
        name,
        {"binding": binding, "request_fingerprint": fingerprint(asdict(article))},
        add,
        allowed,
    )
    require(
        result.get("not_published") is True and isinstance(result.get("media_id"), str)
    )
    require(result["media_id"] != old_media_id, "final_add_old_receipt_returned")
    return sha256(result["media_id"].encode()).hexdigest()


async def main(apply, inventory_fp):
    gen = update.load_generation()
    manual, settings = gen.load_manual(), gen.get_settings()
    require(
        settings.wechat_mp_app_id is not None
        and manual.wechat_draft_account_fingerprint(
            settings.wechat_mp_app_id.get_secret_value()
        )
        == manual.ACCOUNT,
        "final_add_account_mismatch",
    )
    engine = gen.create_engine(settings)
    sessions = gen.create_session_factory(engine)
    journal = client = None
    try:
        _, article, base, source, refs, contents, plans = await gen.prepare_inputs(
            manual,
            sessions,
            gen.LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest),
        )
        directory = (
            Path(settings.wechat_mp_draft_artifact_root) / "manual-v1" / manual.ACCOUNT
        )
        require(directory.is_dir() and not directory.is_symlink())
        journal = gen.LocalManualDraftJournal(
            Path(settings.wechat_mp_draft_artifact_root), manual.ACCOUNT
        )
        old_media_id, old_request, receipt_identity = gen.original_receipt(
            journal, manual
        )
        require(journal.read(gen.AUTH) is not None)
        auth = gen.authorization(
            journal, manual, source, receipt_identity, plans, datetime.now(UTC)
        )

        async def no_model():
            return False

        bodies, cover, audits = await gen.generate(
            journal,
            auth,
            article,
            refs,
            contents,
            plans,
            update.NoModel(),
            update.NoModel(),
            no_model,
        )
        prepared = update.build_prepared(base, bodies, cover, auth, audits)
        require(
            (prepared.title, prepared.author, prepared.digest)
            == (old_request["title"], old_request["author"], old_request["digest"])
        )
        # Do not escape any prior effect (including orphan result) via a new prefix.
        ensure_prior_update_absent(journal, gen)
        prior_auth = journal.read(PREFIX + "-authorization.json")
        pending = journal.read(PREFIX + "-add-intent.json")
        if pending is not None:
            require(
                journal.read(PREFIX + "-add-result.json") is not None,
                "final_add_prior_outcome_unknown",
            )
            require(prior_auth is not None)
            evidence = prior_auth["binding"]["absence_evidence"]
        else:
            client = WeChatOfficialAccountHttpClient(settings)
            evidence = await Remote(client).absence(old_media_id, old_request)
        if apply:
            require(
                inventory_fp == evidence["inventory_fingerprint"],
                "final_add_inventory_confirmation_required",
            )
        final_auth = authorization(
            journal,
            manual,
            prepared,
            auth,
            evidence,
            source,
            receipt_identity,
            datetime.now(UTC),
        )
        print(
            json.dumps(
                {
                    "mode": "apply" if apply else "plan",
                    "inventory": evidence,
                    "generated_content_fingerprint": prepared.content_fingerprint,
                    "images": 5,
                    "audits": 6,
                    "not_published": True,
                }
            ),
            flush=True,
        )
        if not apply:
            return
        if prior_auth is None:
            journal.write(PREFIX + "-authorization.json", final_auth)

        async def allowed():
            _, _, current = await manual.load_target(sessions)
            _, _, current_receipt = gen.original_receipt(journal, manual)
            return (
                current == source
                and current_receipt == receipt_identity
                and datetime.now(UTC) < datetime.fromisoformat(final_auth["expires_at"])
            )

        if client is None:
            client = WeChatOfficialAccountHttpClient(settings)
        receipt = await execute(
            gen,
            journal,
            manual,
            base,
            prepared,
            final_auth,
            old_media_id,
            old_request,
            Remote(client),
            allowed,
        )
        print(
            json.dumps(
                {
                    "status": "generated_draft_created_after_absence",
                    "draft_receipt_fingerprint": receipt,
                    "not_published": True,
                    "readback_verified": False,
                }
            ),
            flush=True,
        )
    finally:
        try:
            if client is not None:
                await client.aclose()
        finally:
            try:
                if journal is not None:
                    journal.close()
            finally:
                await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--inventory-fingerprint")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.apply, args.inventory_fingerprint))
    except Exception as error:  # noqa: BLE001 -- do not expose private draft/provider data
        code = str(error) if isinstance(error, ValueError) else "final_add_stopped"
        if not re.fullmatch(r"(?:final_add|generated_update)_[a-z0-9_]{1,58}", code):
            code = "final_add_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
