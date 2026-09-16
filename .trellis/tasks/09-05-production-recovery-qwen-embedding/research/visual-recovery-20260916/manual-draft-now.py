"""One approved Sep 16 draft using frozen catalog art; compatible with release 01ff75e.

No SQL writes, model calls, generated-image claims, publish/send, or draft listing.
Run with the consumer's real journal/config and a read-only catalog mount, after
quiescing that consumer. Default plan is read-only. --apply permits one journaled
draft/add; an unknown write cannot be replayed. Repeated successful apply reuses ACKs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
    WeChatPreparedDraft,
    _DraftHtmlValidator,
    _prepare_media,
)
from app.application.services.wechat_single_edition_delivery import (
    JournaledSingleDraftClient,
)
from app.core.config import get_settings
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset
from app.domain.official_account_editor_handoff_v2 import render_editor_handoff_v2_body
from app.domain.official_account_local import ArticlePackage, fingerprint
from app.domain.official_account_source_presentation import (
    CURRENT_SOURCE_PRESENTATION_VERSION,
)
from app.domain.official_account_strict_layout import (
    STRICT_LAYOUT_PROJECTION_V2_VERSION,
    compact_strict_xiaosai_html,
    validate_strict_upload_html_headroom,
)
from app.domain.wechat_official_account_draft_jobs import (
    wechat_draft_account_fingerprint,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel as Attempt,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel as Run,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleVersionModel as Article,
)
from app.infrastructure.db.models import (
    OfficialAccountDraftOwnerModel as Owner,
)
from app.infrastructure.db.models import (
    OfficialAccountGeneratedVisualModel as Visual,
)
from app.infrastructure.db.models import (
    OfficialAccountRenderVersionModel as Render,
)
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel as Edition,
)
from app.infrastructure.db.models import (
    WeChatOfficialAccountDraftItemModel as DraftItem,
)
from app.infrastructure.db.official_account_single_edition import _snapshot
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
)
from app.infrastructure.official_account_marketing_footer import (
    load_official_account_marketing_framing,
)
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)
from PIL import Image
from sqlalchemy import or_, select, text

EDITION = UUID("41b26b7f-e792-56ff-bdfa-643171114056")
RUN = UUID("5e2bbc6e-6bec-4234-b516-7b2c58e198c6")
ARTICLE = UUID("5107bfe9-ae30-4a2d-9fd0-c57a369fa6a8")
VISUAL = UUID("31c58fc2-2722-4a28-957d-0b7b9b16d510")
EVENT = UUID("b1de9144-9300-54bc-9588-0c4c92c7e87f")
ACCOUNT = "ae3a5056a1c78eddf728060ecc5287b6a93e48d99e496bc9a22292a2b4eb8fd7"
DAY = date(2026, 9, 16)
ZONE = ZoneInfo("Asia/Shanghai")
AUTH_NAME = f"catalog-override-{EDITION.hex}.json"


def require(condition, code="manual_draft_target_changed"):
    if not condition:
        raise ValueError(code)


async def load_target(sessions):
    async with sessions() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        edition = await session.get(Edition, EDITION)
        run = await session.get(Run, RUN)
        article = await session.get(Article, ARTICLE)
        visual = await session.get(Visual, VISUAL)
        require(all(item is not None for item in (edition, run, article, visual)))
        render = await session.get(Render, run.active_render_version_id)
        require(
            edition.account_fingerprint == ACCOUNT
            and edition.business_date == DAY
            and edition.article_run_id == RUN
            and edition.event_id == EVENT
            and edition.status == "outcome_unknown"
            and edition.lease_token is None
            and edition.lease_expires_at is None
            and edition.prepared_artifact is None
            and edition.receipt_fingerprint is None
            and edition.article_fingerprint is None
            and edition.content_fingerprint is None
            and run.status == "result_unknown"
            and run.current_stage == "result_unknown"
            and run.lease_owner is None
            and run.lease_token is None
            and run.lease_expires_at is None
            and run.active_draft_id is None
            and run.active_article_version_id == ARTICLE
            and article.run_id == RUN
            and article.audit_snapshot.get("accepted") is True
            and article.validation_snapshot.get("passed") is True
            and visual.run_id == RUN
            and visual.article_version_id == ARTICLE
            and visual.status == "result_unknown"
            and visual.error_code == "official_account_generated_visual_result_unknown"
            and render is not None
            and render.run_id == RUN
            and render.article_version_id == ARTICLE
        )
        owner = await session.get(Owner, (ACCOUNT, "event", str(edition.event_id)))
        require(
            owner is not None
            and owner.owner == str(EDITION)
            and owner.status == "outcome_unknown"
        )
        require(
            await session.get(Owner, (ACCOUNT, "article", article.content_fingerprint))
            is None
        )
        require(
            await session.scalar(
                select(Attempt.id)
                .where(
                    Attempt.run_id == RUN,
                    Attempt.stage == "visual_compensation_authorized",
                )
                .limit(1)
            )
            is None,
            "manual_draft_compensation_already_authorized",
        )
        require(
            await session.scalar(
                select(DraftItem.job_id)
                .where(
                    or_(
                        DraftItem.article_fingerprint == article.content_fingerprint,
                        DraftItem.source_fingerprint == run.source_fingerprint,
                        DraftItem.source_ref == str(RUN),
                    )
                )
                .limit(1)
            )
            is None,
            "manual_draft_already_owned",
        )
        package = ArticlePackage.model_validate(article.article_payload)
        require(package.content_fingerprint == article.content_fingerprint)
        identity = fingerprint(
            article.article_payload,
            article.validation_snapshot,
            article.audit_snapshot,
            render.render_fingerprint,
            render.canonical_html,
            run.version_bundle,
            str(edition.event_id),
            owner.provenance_fingerprint,
        )
        return _snapshot(edition), package, identity


def media_record(path, body, *, ordinal, role="body", alt="小赛品牌配图"):
    with Image.open(BytesIO(body)) as image:
        image.load()
        require(image.format == "JPEG", "manual_catalog_image_invalid")
        width, height = image.size
    return {
        "path": path,
        "role": role,
        "ordinal": ordinal,
        "media_type": "image/jpeg",
        "byte_size": len(body),
        "sha256": sha256(body).hexdigest(),
        "width": width,
        "height": height,
        "alt_text": alt,
    }


async def prepare(package, catalog):
    require(
        package.media_selection is not None
        and len(package.media_selection.assignments) == 5,
        "manual_catalog_assignments_invalid",
    )
    files, assets = {}, []
    for assignment in package.media_selection.assignments:
        path = f"assets/body-{assignment.ordinal:02d}.jpg"
        body = await catalog.read_publication_bytes(
            catalog_asset_ref=assignment.candidate_ref,
            catalog_version=package.media_selection.catalog_version,
            source_master_sha256=assignment.source_checksum,
            publication_sha256=assignment.publication_checksum,
        )
        files[path] = body
        assets.append(
            EditorHandoffMediaAsset(
                **media_record(path, body, ordinal=assignment.ordinal),
                assigned_section_index=assignment.section_index,
            )
        )
    header, header_bytes, footer, footer_bytes = (
        load_official_account_marketing_framing()
    )
    files[header.path], files[footer.path] = header_bytes, footer_bytes
    rendered = render_editor_handoff_v2_body(
        article=package,
        media=tuple(assets),
        hide_body_captions=True,
        header=header,
        footer=footer,
        source_presentation=CURRENT_SOURCE_PRESENTATION_VERSION,
    )
    body_html = compact_strict_xiaosai_html(
        rendered.body_html, version=STRICT_LAYOUT_PROJECTION_V2_VERSION
    )
    parser = _DraftHtmlValidator(allow_bare_leaf=True)
    parser.feed(body_html)
    parser.close()
    image_paths = parser.finish()
    validate_strict_upload_html_headroom(body_html, image_paths)
    require(
        "阅读原文" not in body_html and 'href="' not in body_html,
        "manual_source_presentation_invalid",
    )
    files["assets/cover-wide.jpg"] = files["assets/body-00.jpg"]
    # These roles are upload-media roles, not fake native generated-image lineage.
    records = [
        media_record(
            path,
            body,
            ordinal=index,
            role="cover" if path == "assets/cover-wide.jpg" else "body",
        )
        for index, (path, body) in enumerate(files.items())
    ]
    body_media, cover = _prepare_media(
        manifest={"media": records},
        files=files,
        image_paths=image_paths,
        max_image_bytes=10 * 1024 * 1024,
    )
    content_fp = fingerprint(
        "manual-frozen-catalog-draft-v1",
        body_html,
        [(item.path, sha256(item.body).hexdigest()) for item in (*body_media, cover)],
    )
    return WeChatPreparedDraft(
        role="official_anchor",
        article_fingerprint=package.content_fingerprint,
        content_fingerprint=content_fp,
        title=package.title,
        author=package.author,
        digest=package.digest,
        content_source_url=None,
        body_html=body_html,
        body_media=body_media,
        cover=cover,
        need_open_comment=False,
        only_fans_can_comment=False,
        visual_pipeline_version=None,
    )


def authorize(journal, names, *, prepared, source_identity, original_expiry, now):
    binding = {
        "version": "manual-frozen-catalog-draft-v1",
        "edition_id": str(EDITION),
        "run_id": str(RUN),
        "article_id": str(ARTICLE),
        "account": ACCOUNT,
        "article_fingerprint": prepared.article_fingerprint,
        "content_fingerprint": prepared.content_fingerprint,
        "source_identity": source_identity,
        "body_sha256": sha256(prepared.body_html.encode()).hexdigest(),
        "media": [
            {
                "path": item.path,
                "sha256": sha256(item.body).hexdigest(),
                "bytes": len(item.body),
            }
            for item in (*prepared.body_media, prepared.cover)
        ],
        "media_origin": "existing_frozen_approved_catalog_and_packaged_banners",
        "generated": False,
        "draft_only": True,
        "max_attempts": 1,
        "original_expires_at": original_expiry.isoformat(),
    }
    prior = journal.read(AUTH_NAME)
    if prior is not None:
        require(
            set(prior) == {"binding", "authorized_at", "expires_at"}
            and prior["binding"] == binding,
            "manual_override_binding_changed",
        )
        approved_at = datetime.fromisoformat(prior["authorized_at"])
        deadline = datetime.fromisoformat(prior["expires_at"])
        require(
            approved_at.utcoffset() is not None
            and deadline.utcoffset() is not None
            and approved_at.astimezone(ZONE).date() == DAY
            and deadline.astimezone(ZONE).date() == DAY
            and timedelta(0) < deadline - approved_at <= timedelta(hours=2)
            and approved_at <= now,
            "manual_override_deadline_invalid",
        )
        return prior
    require(now.astimezone(ZONE).date() == DAY, "manual_override_wrong_day")
    require(
        not any(name.startswith(f"single-{EDITION.hex}-") for name in names),
        "manual_override_prior_write_exists",
    )
    require(
        journal.read(prepared.article_fingerprint + "-claim.json") is None,
        "manual_override_prior_claim_exists",
    )
    expires = min(now + timedelta(hours=2), datetime.combine(DAY, time.max, ZONE))
    return {
        "binding": binding,
        "authorized_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }


async def execute(prepared, edition, journal, client, auth, authorize_write):
    # The existing single namespace is skipped by the manual-history importer,
    # avoiding a conflicting second owner for this edition's already-owned event.
    observed = JournaledSingleDraftClient(
        client=client,
        journal=journal,
        prepared=prepared,
        edition=replace(
            edition,
            expires_at=datetime.fromisoformat(auth["expires_at"]),
            max_attempts=1,
        ),
        authorize=authorize_write,
        clock=lambda: datetime.now(UTC),
    )
    receipt = await WeChatOfficialAccountDraftOnlyService(
        client=observed
    ).create_prepared(prepared)
    return {
        "status": "draft_created",
        "not_published": True,
        "article_fingerprint": receipt.article_fingerprint,
        "content_fingerprint": receipt.content_fingerprint,
        "draft_receipt_fingerprint": sha256(
            receipt.draft_media_id.encode()
        ).hexdigest(),
        "uploaded_image_count": receipt.uploaded_image_count,
        "readback_verified": False,
    }


async def main(apply):
    settings = get_settings()
    require(
        settings.wechat_mp_app_id is not None
        and wechat_draft_account_fingerprint(
            settings.wechat_mp_app_id.get_secret_value()
        )
        == ACCOUNT,
        "manual_account_mismatch",
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    journal = client = None
    try:
        edition, package, source_identity = await load_target(sessions)
        prepared = await prepare(
            package,
            LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest),
        )
        directory = Path(settings.wechat_mp_draft_artifact_root) / "manual-v1" / ACCOUNT
        require(
            directory.is_dir() and not directory.is_symlink(),
            "manual_journal_mount_missing",
        )
        journal = LocalManualDraftJournal(
            Path(settings.wechat_mp_draft_artifact_root), ACCOUNT
        )
        auth = authorize(
            journal,
            os.listdir(directory),
            prepared=prepared,
            source_identity=source_identity,
            original_expiry=edition.expires_at,
            now=datetime.now(UTC),
        )
        print(
            json.dumps(
                {
                    "mode": "apply" if apply else "plan",
                    "title": prepared.title,
                    "article_fingerprint": prepared.article_fingerprint,
                    "content_fingerprint": prepared.content_fingerprint,
                    "body_images": len(prepared.body_media),
                    "generated_images": 0,
                    "body_characters": len(prepared.body_html),
                    "cover_bytes": len(prepared.cover.body),
                    "deadline": auth["expires_at"],
                    "not_published": True,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not apply:
            return
        if journal.read(AUTH_NAME) is None:
            journal.write(AUTH_NAME, auth)

        async def authorize_write():
            _edition, _article, current = await load_target(sessions)
            return current == source_identity and datetime.now(
                UTC
            ) < datetime.fromisoformat(auth["expires_at"])

        client = WeChatOfficialAccountHttpClient(settings)
        result = await execute(
            prepared, edition, journal, client, auth, authorize_write
        )
        print(json.dumps(result), flush=True)
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
    try:
        asyncio.run(main(parser.parse_args().apply))
    except Exception as error:  # noqa: BLE001 -- sanitize provider/transport failures
        code = getattr(error, "code", "manual_draft_stopped")
        if isinstance(error, ValueError) and str(error).startswith("manual_"):
            code = str(error)
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{1,79}", code) is None
        ):
            code = "manual_draft_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
