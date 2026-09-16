"""Update the one Sep 16 draft using already-generated, audited private receipts.

Default is local plan only. --update permits six uploads and ONE draft/update;
never draft/add, never publish, never SQL writes or model calls. Run with the
generation and original manual operators beside this file, same private journal,
read-only catalog mount and the affected consumer stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

from app.application.ports.wechat_official_account import WeChatDraftArticleRequest
from app.domain.official_account_local import fingerprint
from app.domain.official_account_strict_layout import (
    strict_escaped_upload_url,
    validate_strict_upload_html_headroom,
)
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
    _validate_draft_article,
)

GENERATION_SHA = "2fdfd035b82ba7c431dcbcb0aefecb09e594717366e6182f950ab968bc21b83d"


def require(condition, code="generated_update_write_binding_invalid"):
    if not condition:
        raise ValueError(code)


def load_generation():
    path = Path(__file__).with_name("generated-draft-update.py")
    require(
        sha256(path.read_bytes()).hexdigest() == GENERATION_SHA,
        "generated_update_generation_code_changed",
    )
    spec = importlib.util.spec_from_file_location("verified_generated_images", path)
    if spec is None or spec.loader is None:
        raise ValueError("generated_update_generation_import_invalid")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VisibleHtml(HTMLParser):
    """Compare content, image order and links, not WeChat's rewritten style attrs."""

    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.text, self.images, self.links = [], [], []
        self.feed(value)
        self.close()

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        require(
            len({key for key, _value in attrs}) == len(attrs),
            "generated_update_remote_duplicate_attribute",
        )
        fields = dict(attrs)
        if tag == "img":
            src, data_src = fields.get("src"), fields.get("data-src")
            require(
                (src is not None or data_src is not None)
                and (src is None or data_src is None or src == data_src),
                "generated_update_remote_image_conflict",
            )
            self.images.append(src if src is not None else data_src)
        if tag == "a":
            self.links.append(fields.get("href"))

    def identity(self):
        return " ".join("".join(self.text).split()), self.images, self.links


def same_article(current, expected):
    require(isinstance(current, dict), "generated_update_remote_article_invalid")
    for key in ("title", "author", "digest", "thumb_media_id"):
        require(current.get(key) == expected[key], "generated_update_remote_edited")
    for key in ("need_open_comment", "only_fans_can_comment"):
        require(
            current.get(key, 0) == int(expected[key]), "generated_update_remote_edited"
        )
    require(
        (current.get("content_source_url") or "")
        == (expected.get("content_source_url") or "")
        and isinstance(current.get("content"), str),
        "generated_update_remote_edited",
    )
    require(
        VisibleHtml(current["content"]).identity()
        == VisibleHtml(expected["content"]).identity(),
        "generated_update_remote_edited",
    )


def build_prepared(base, bodies, cover, auth, audits):
    require(len(bodies) == 5 and len(audits) == 6 and len(base.body_media) == 7)
    expected = tuple(f"assets/body-{i:02d}.jpg" for i in range(5))
    require(tuple(item.path for item in base.body_media[1:6]) == expected)
    media = (
        base.body_media[0],
        *(
            replace(item, body=body, media_type="image/jpeg")
            for item, body in zip(base.body_media[1:6], bodies, strict=True)
        ),
        base.body_media[6],
    )
    validate_strict_upload_html_headroom(base.body_html, tuple(x.path for x in media))
    require(not VisibleHtml(base.body_html).links, "generated_update_source_links")
    content_fp = fingerprint(
        "sep16-generated-draft-content-v1",
        base.content_fingerprint,
        fingerprint(auth),
        audits,
        [sha256(x.body).hexdigest() for x in media],
        sha256(cover).hexdigest(),
    )
    return replace(
        base,
        body_media=media,
        cover=replace(base.cover, body=cover, media_type="image/jpeg"),
        content_fingerprint=content_fp,
        content_source_url=None,
    )


def banner_urls(journal, manual, base, original_intent):
    result = {}
    for i in (0, 6):
        name = f"single-{manual.EDITION.hex}-inline-{i}-1"
        intent, ack = (
            journal.read(name + "-intent.json"),
            journal.read(name + "-ack.json"),
        )
        require(intent is not None and ack is not None)
        require(
            intent["binding"] == original_intent["binding"]
            and intent["step"] == f"inline-{i}"
            and intent["attempt"] == 1
            and intent["request"]["sha256"]
            == sha256(base.body_media[i].body).hexdigest()
            and ack["intent_sha256"] == manual_fingerprint(intent)
            and journal.read(name + "-not-applied.json") is None,
            "generated_update_banner_receipt_changed",
        )
        result[i] = strict_escaped_upload_url(ack["value"])
    return result


def manual_fingerprint(value):
    from app.infrastructure.wechat_official_account.manual_journal import (
        fingerprint as journal_fingerprint,
    )

    return journal_fingerprint(value)


class Remote:
    """One physical HTTP request per journaled operation; no automatic write retry."""

    def __init__(self, client):
        self.client = client

    async def token(self):
        return (await self.client._get_access_token()).value

    async def post(
        self, path, token, *, payload=None, files=None, limit=65536, query=None
    ):
        require(
            path
            in {
                "/cgi-bin/draft/get",
                "/cgi-bin/draft/update",
                "/cgi-bin/media/uploadimg",
                "/cgi-bin/material/add_material",
            }
            and query
            == (
                {"type": "thumb"} if path == "/cgi-bin/material/add_material" else None
            ),
            "generated_update_endpoint_forbidden",
        )
        async with asyncio.timeout(self.client._total_timeout_seconds):
            async with self.client._client.stream(
                "POST",
                self.client._base_url + path,
                params={"access_token": token, **(query or {})},
                json=payload,
                files=files,
                follow_redirects=False,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                timeout=self.client._timeout,
            ) as response:
                require(
                    200 <= response.status_code < 300
                    and response.headers.get("content-encoding", "identity").casefold()
                    in {"", "identity"},
                    "generated_update_response_not_acknowledged",
                )
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    require(size <= limit, "generated_update_response_too_large")
                    chunks.append(chunk)
        value = json.loads(
            b"".join(chunks),
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
        require(isinstance(value, dict), "generated_update_response_invalid")
        require(
            "errcode" not in value
            or (type(value["errcode"]) is int and value["errcode"] == 0),
            "generated_update_response_not_acknowledged",
        )
        return value

    async def get(self, media_id):
        value = await self.post(
            "/cgi-bin/draft/get",
            await self.token(),
            payload={"media_id": media_id},
            limit=1024 * 1024,
        )
        items = value.get("news_item")
        require(isinstance(items, list) and len(items) == 1)
        return items[0]

    async def upload(self, media, token, *, cover):
        value = await self.post(
            "/cgi-bin/material/add_material" if cover else "/cgi-bin/media/uploadimg",
            token,
            files={"media": (media.upload_filename, media.body, media.media_type)},
            query={"type": "thumb"} if cover else None,
        )
        if cover:
            media_id = value.get("media_id")
            require(
                isinstance(media_id, str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", media_id) is not None,
                "generated_update_uploaded_thumb_invalid",
            )
            return {"value": media_id}
        strict_escaped_upload_url(value.get("url"))
        return {"value": value["url"]}

    async def update(self, media_id, article, token):
        payload = asdict(article)
        payload.update(
            article_type="news",
            content_source_url="",
            need_open_comment=int(article.need_open_comment),
            only_fans_can_comment=int(article.only_fans_can_comment),
        )
        value = await self.post(
            "/cgi-bin/draft/update",
            token,
            payload={"media_id": media_id, "index": 0, "articles": payload},
        )
        require(
            type(value.get("errcode")) is int and value["errcode"] == 0,
            "generated_update_write_outcome_unknown",
        )
        return {"acknowledged": True, "not_published": True}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "generated_update_response_duplicate_key")
        value[key] = item
    return value


def invalid_constant(_value):
    raise ValueError("generated_update_response_invalid_constant")


async def execute(
    gen, journal, manual, base, prepared, auth, media_id, old_request, remote, allowed
):
    name = gen.PREFIX + "-draft-update"
    binding = {
        "authorization_fingerprint": fingerprint(auth),
        "content_fingerprint": prepared.content_fingerprint,
        "target_draft_fingerprint": gen.OLD_RECEIPT_FP,
        "original_content_fingerprint": gen.OLD_CONTENT_FP,
        "operation": "draft_update",
        "index": 0,
    }
    prior = journal.read(name + "-intent.json")
    ack = journal.read(name + "-result.json")
    if prior is not None:
        require(prior.get("binding") == binding)
        require(ack is not None, "generated_update_prior_outcome_unknown")
        require(
            ack.get("intent_fingerprint") == fingerprint(prior)
            and ack.get("acknowledged") is True
            and ack.get("not_published") is True,
        )
        return fingerprint(ack)
    require(ack is None)
    require(await allowed(), "generated_update_authority_expired")
    same_article(await remote.get(media_id), old_request)
    original_intent = journal.read(f"single-{manual.EDITION.hex}-add-1-intent.json")
    urls = banner_urls(journal, manual, base, original_intent)
    rewritten = prepared.body_html
    for i, media in enumerate(prepared.body_media):
        if i not in urls:
            token = await remote.token()
            intent = {
                "binding": binding,
                "sha256": sha256(media.body).hexdigest(),
                "ordinal": i,
            }

            async def upload(media=media, token=token):
                return await remote.upload(media, token, cover=False)

            record = await gen.once(
                journal, gen.PREFIX + f"-upload-body-{i}", intent, upload, allowed
            )
            urls[i] = strict_escaped_upload_url(record["value"])
        needle = f'src="{media.path}"'
        require(rewritten.count(needle) == 1)
        rewritten = rewritten.replace(needle, f'src="{urls[i]}"', 1)
    token = await remote.token()

    async def upload_cover():
        return await remote.upload(prepared.cover, token, cover=True)

    thumb = await gen.once(
        journal,
        gen.PREFIX + "-upload-cover",
        {"binding": binding, "sha256": sha256(prepared.cover.body).hexdigest()},
        upload_cover,
        allowed,
    )
    article = WeChatDraftArticleRequest(
        title=prepared.title,
        author=prepared.author,
        digest=prepared.digest,
        content=rewritten,
        content_source_url=None,
        thumb_media_id=thumb["value"],
        need_open_comment=prepared.need_open_comment,
        only_fans_can_comment=prepared.only_fans_can_comment,
    )
    _validate_draft_article(article)
    same_article(await remote.get(media_id), old_request)
    token = await remote.token()

    async def update():
        return await remote.update(media_id, article, token)

    result = await gen.once(
        journal,
        name,
        {"binding": binding, "request_fingerprint": fingerprint(asdict(article))},
        update,
        allowed,
    )
    require(result.get("acknowledged") is True and result.get("not_published") is True)
    return fingerprint(result)


class NoModel:
    async def generate(self, *_args, **_kwargs):
        raise AssertionError("update-only has no model capability")

    audit = generate


async def main(apply):
    gen = load_generation()
    manual, settings = gen.load_manual(), gen.get_settings()
    require(
        settings.wechat_mp_app_id is not None
        and manual.wechat_draft_account_fingerprint(
            settings.wechat_mp_app_id.get_secret_value()
        )
        == manual.ACCOUNT,
        "generated_update_account_mismatch",
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
        media_id, old_request, receipt_identity = gen.original_receipt(journal, manual)
        require(
            journal.read(gen.AUTH) is not None,
            "generated_update_generation_not_authorized",
        )
        auth = gen.authorization(
            journal, manual, source, receipt_identity, plans, datetime.now(UTC)
        )

        async def no_new_model_calls():
            return False

        bodies, cover, audits = await gen.generate(
            journal,
            auth,
            article,
            refs,
            contents,
            plans,
            NoModel(),
            NoModel(),
            no_new_model_calls,
        )
        prepared = build_prepared(base, bodies, cover, auth, audits)
        require(
            (old_request["title"], old_request["author"], old_request["digest"])
            == (prepared.title, prepared.author, prepared.digest)
        )
        print(
            json.dumps(
                {
                    "mode": "update" if apply else "plan",
                    "images": 5,
                    "audits": 6,
                    "content_fingerprint": prepared.content_fingerprint,
                    "target_draft_fingerprint": gen.OLD_RECEIPT_FP,
                    "draft_add_allowed": False,
                }
            ),
            flush=True,
        )
        if not apply:
            return

        async def allowed():
            _, _, current = await manual.load_target(sessions)
            _, _, current_receipt = gen.original_receipt(journal, manual)
            return (
                current == source
                and current_receipt == receipt_identity
                and datetime.now(UTC) < datetime.fromisoformat(auth["expires_at"])
            )

        client = WeChatOfficialAccountHttpClient(settings)
        result = await execute(
            gen,
            journal,
            manual,
            base,
            prepared,
            auth,
            media_id,
            old_request,
            Remote(client),
            allowed,
        )
        print(
            json.dumps(
                {
                    "status": "same_draft_updated",
                    "receipt_fingerprint": result,
                    "target_draft_fingerprint": gen.OLD_RECEIPT_FP,
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
    parser.add_argument("--update", action="store_true")
    try:
        asyncio.run(main(parser.parse_args().update))
    except Exception as error:  # noqa: BLE001 -- no private transport/provider output
        code = (
            str(error) if isinstance(error, ValueError) else "generated_update_stopped"
        )
        if not re.fullmatch(r"generated_update_[a-z0-9_]{1,58}", code):
            code = "generated_update_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
