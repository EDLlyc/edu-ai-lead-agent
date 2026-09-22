"""Exact-target September 21 single-draft backfill.

This is a transient, fixed-target operator, not a scheduler entry point.  ``plan``
is the default and performs no model, WeChat, or SQL write.  ``--apply`` freezes
one two-hour authorization in the existing private manual journal, makes at most
one new image request per body slot (five total), and creates at most one
draft-only draft through the existing journaled client.

The module intentionally uses only application APIs present in production commit
``abfb89d``.  It does not depend on the later tolerant-geometry recovery code.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import UUID

import httpx
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerator,
    ImageReference,
)
from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountGeneratedVisualStore,
    OfficialAccountSourceMedia,
    StoredOfficialAccountArticle,
    StoredOfficialAccountRender,
)
from app.application.ports.wechat_official_account import (
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
    WeChatInlineImage,
    WeChatOfficialAccountDraftClient,
    WeChatThumbMedia,
)
from app.application.ports.wechat_official_account_manual_draft import (
    ManualDraftJournal,
    require,
)
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    plan_generated_body_visual,
    prepare_generated_visual_result,
)
from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
    WeChatPreparedDraft,
    _DraftHtmlValidator,
    _prepare_media,
)
from app.application.services.wechat_single_edition_delivery import (
    JournaledSingleDraftClient,
)
from app.core.errors import classify_image_generation_failure
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
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
from app.domain.official_account_visual_pipeline import STRICT_VISUAL_POLICY
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.domain.wechat_official_account_draft_jobs import (
    wechat_draft_account_fingerprint,
)
from app.infrastructure.ai.official_account_visual_strict import (
    LazyStrictOfficialAccountImageGenerator,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel as Attempt,
)
from app.infrastructure.db.models import OfficialAccountArticleRunModel as Run
from app.infrastructure.db.models import OfficialAccountArticleVersionModel as Article
from app.infrastructure.db.models import OfficialAccountDraftOwnerModel as Owner
from app.infrastructure.db.models import OfficialAccountGeneratedVisualModel as Visual
from app.infrastructure.db.models import OfficialAccountRenderVersionModel as Render
from app.infrastructure.db.models import OfficialAccountSingleEditionModel as Edition
from app.infrastructure.db.models import (
    WeChatOfficialAccountDraftItemModel as DraftItem,
)
from app.infrastructure.db.official_account_local import _stored_article, _stored_render
from app.infrastructure.db.official_account_single_edition import _snapshot
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
)
from app.infrastructure.official_account_marketing_footer import (
    load_official_account_marketing_framing,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)
from PIL import Image
from sqlalchemy import insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

POLICY = "single-edition-sep21-backfill-v1"
ACCOUNT = "ae3a5056a1c78eddf728060ecc5287b6a93e48d99e496bc9a22292a2b4eb8fd7"
DAY = date(2026, 9, 21)
EDITION = UUID("3afa48cb-f0a1-5912-b538-5ed2d2fb14c0")
AUTH_NAME = f"backfill-{EDITION.hex}-authorization.json"
PREFIX = f"backfill-{EDITION.hex}"
SELECTION_NAME = f"{PREFIX}-visual-selection.json"
EXPECTED_PRIOR_ERRORS = (
    "provider_unavailable",
    "image_provider_timeout",
    "image_provider_timeout",
)
MAX_VISUAL_CALLS = 5


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode()


def _sha(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class PriorVisualAttempt:
    ordinal: int
    request_fingerprint: str
    error_code: str
    disposition: str


@dataclass(frozen=True, slots=True)
class BackfillTarget:
    edition: Any
    article: StoredOfficialAccountArticle
    render: StoredOfficialAccountRender
    run_id: UUID
    event_id: UUID
    source_identity: str
    prior_attempts: tuple[PriorVisualAttempt, PriorVisualAttempt, PriorVisualAttempt]
    plan_version: str
    prompt_version: str
    reconciled: bool = False


@dataclass(frozen=True, slots=True)
class BackfillVisualSlot:
    ordinal: int
    plan: OfficialAccountGeneratedVisualPlan
    request: ImageGenerationRequest


@dataclass(frozen=True, slots=True)
class VisualSelection:
    origin: Literal["generated", "approved_catalog_fallback"]
    bodies: tuple[bytes, bytes, bytes, bytes, bytes] | None
    safe_results: tuple[dict[str, Any], ...]


class BackfillRepository(Protocol):
    async def load_target(self) -> BackfillTarget: ...

    async def reconcile(
        self,
        *,
        target: BackfillTarget,
        prepared: WeChatPreparedDraft,
        receipt_fingerprint: str,
        authorization_fingerprint: str,
        now: datetime,
    ) -> bool: ...


class DraftReadback(Protocol):
    async def verify(
        self, media_id: str, expected: WeChatDraftArticleRequest
    ) -> bool: ...


class CatalogProvider(Protocol):
    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]: ...

    async def read_publication_bytes(
        self,
        *,
        catalog_asset_ref: str,
        catalog_version: str,
        source_master_sha256: str,
        publication_sha256: str,
    ) -> bytes: ...


def _media_record(
    path: str,
    body: bytes,
    *,
    ordinal: int,
    role: str = "body",
    alt: str = "小赛教育配图",
) -> dict[str, Any]:
    with Image.open(BytesIO(body)) as image:
        image.load()
        require(image.format == "JPEG", "backfill_image_invalid")
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


def _render_prepared(
    package: ArticlePackage,
    bodies: tuple[bytes, bytes, bytes, bytes, bytes],
    *,
    origin: Literal["generated", "approved_catalog_fallback"],
    lineage: object,
) -> WeChatPreparedDraft:
    require(
        package.media_selection is not None
        and len(package.media_selection.assignments) == MAX_VISUAL_CALLS,
        "backfill_media_assignments_invalid",
    )
    selection = package.media_selection
    assert selection is not None
    assignments = sorted(selection.assignments, key=lambda item: item.ordinal)
    require(
        [item.ordinal for item in assignments] == list(range(MAX_VISUAL_CALLS)),
        "backfill_media_assignments_invalid",
    )
    files: dict[str, bytes] = {}
    assets: list[EditorHandoffMediaAsset] = []
    for assignment, body in zip(assignments, bodies, strict=True):
        path = f"assets/body-{assignment.ordinal:02d}.jpg"
        files[path] = body
        assets.append(
            EditorHandoffMediaAsset(
                **_media_record(path, body, ordinal=assignment.ordinal),
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
        "backfill_source_presentation_invalid",
    )
    files["assets/cover-wide.jpg"] = files["assets/body-00.jpg"]
    records = [
        _media_record(
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
    content_fingerprint = fingerprint(
        POLICY,
        origin,
        lineage,
        body_html,
        tuple(
            (item.path, sha256(item.body).hexdigest()) for item in (*body_media, cover)
        ),
    )
    return WeChatPreparedDraft(
        role="official_anchor",
        article_fingerprint=package.content_fingerprint,
        content_fingerprint=content_fingerprint,
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


async def prepare_fallback(
    target: BackfillTarget, catalog: CatalogProvider
) -> WeChatPreparedDraft:
    selection = target.article.article.media_selection
    require(
        selection is not None and len(selection.assignments) == MAX_VISUAL_CALLS,
        "backfill_catalog_selection_invalid",
    )
    assert selection is not None
    bodies: list[bytes] = []
    lineage: list[tuple[object, ...]] = []
    for assignment in sorted(selection.assignments, key=lambda item: item.ordinal):
        body = await catalog.read_publication_bytes(
            catalog_asset_ref=assignment.candidate_ref,
            catalog_version=selection.catalog_version,
            source_master_sha256=assignment.source_checksum,
            publication_sha256=assignment.publication_checksum,
        )
        require(
            sha256(body).hexdigest() == assignment.publication_checksum,
            "backfill_catalog_bytes_changed",
        )
        bodies.append(body)
        lineage.append(
            (
                assignment.ordinal,
                assignment.candidate_ref,
                selection.catalog_version,
                assignment.source_checksum,
                assignment.publication_checksum,
            )
        )
    return _render_prepared(
        target.article.article,
        cast(tuple[bytes, bytes, bytes, bytes, bytes], tuple(bodies)),
        origin="approved_catalog_fallback",
        lineage=tuple(lineage),
    )


def assigned_reference(
    *, assignment: Any, catalog_version: str, reference: OfficialAccountSourceMedia
) -> OfficialAccountSourceMedia:
    require(
        reference.catalog_version == catalog_version
        and reference.source_master_sha256 == assignment.source_checksum
        and reference.sha256 == assignment.publication_checksum
        and reference.catalog_asset_ref == assignment.candidate_ref,
        "backfill_reference_changed",
    )
    # Catalog candidates intentionally carry only immutable asset identity.
    # Rehydrate the frozen per-article assignment metadata exactly as the
    # production selector does before planning a generated visual.
    return replace(
        reference,
        ordinal=assignment.ordinal,
        assigned_section_index=assignment.section_index,
        selection_reason_code=assignment.reason_code,
        selection_method=assignment.selection_method,
        similarity_band=assignment.similarity_band,
    )


async def plan_visual_slots(
    target: BackfillTarget, catalog: CatalogProvider
) -> tuple[BackfillVisualSlot, ...]:
    selection = target.article.article.media_selection
    require(
        selection is not None and len(selection.assignments) == MAX_VISUAL_CALLS,
        "backfill_catalog_selection_invalid",
    )
    assert selection is not None
    candidates = await catalog.load_candidates()
    by_ref = {item.catalog_asset_ref: item for item in candidates}
    require(len(by_ref) == len(candidates), "backfill_catalog_candidates_invalid")
    slots: list[BackfillVisualSlot] = []
    for assignment in sorted(selection.assignments, key=lambda item: item.ordinal):
        reference = by_ref.get(assignment.candidate_ref)
        require(reference is not None, "backfill_reference_missing")
        assert reference is not None
        reference = assigned_reference(
            assignment=assignment,
            catalog_version=selection.catalog_version,
            reference=reference,
        )
        content = await catalog.read_publication_bytes(
            catalog_asset_ref=reference.catalog_asset_ref or "",
            catalog_version=reference.catalog_version or "",
            source_master_sha256=reference.source_master_sha256 or "",
            publication_sha256=reference.sha256,
        )
        plan = plan_generated_body_visual(
            run_id=target.run_id,
            article=target.article,
            render=target.render,
            ordinal=assignment.ordinal,
            reference=reference,
            reference_bytes=content,
            provider=STRICT_VISUAL_POLICY.generation_provider,
            model=STRICT_VISUAL_POLICY.generation_model,
            plan_version=target.plan_version,
            prompt_version=target.prompt_version,
        )
        prompt = build_generated_visual_prompt(
            article=target.article,
            section_index=plan.section_index,
            reference=reference,
            prompt_version=plan.prompt_version,
            block_index=plan.block_index,
        )
        request = ImageGenerationRequest(
            run_id=target.run_id,
            draft_version_id=target.article.id,
            prompt=prompt,
            request_fingerprint=plan.request_fingerprint,
            output_size=STRICT_VISUAL_POLICY.output_size,
            references=(
                ImageReference(
                    role="approved_ip_reference",
                    asset_id=plan.reference_asset_ref,
                    filename=f"reference-{plan.reference_asset_ref}.jpg",
                    sha256=reference.sha256,
                    image_bytes=content,
                    selection_reason="approved_catalog_semantic_reference",
                    input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
                    provider_input_sha256=plan.reference_input_checksum,
                ),
            ),
            reference_mode="single_reference",
        )
        slots.append(BackfillVisualSlot(assignment.ordinal, plan, request))
    require(
        [slot.ordinal for slot in slots] == list(range(MAX_VISUAL_CALLS)),
        "backfill_visual_slots_invalid",
    )
    return tuple(slots)


def authorize(
    journal: ManualDraftJournal,
    *,
    target: BackfillTarget,
    fallback: WeChatPreparedDraft,
    slots: tuple[BackfillVisualSlot, ...],
    now: datetime,
    apply: bool,
) -> dict[str, Any]:
    require(now.utcoffset() is not None, "backfill_clock_invalid")
    binding = {
        "version": POLICY,
        "account": ACCOUNT,
        "business_date": DAY.isoformat(),
        "edition_id": str(EDITION),
        "run_id": str(target.run_id),
        "article_id": str(target.article.id),
        "render_id": str(target.render.id),
        "event_id": str(target.event_id),
        "source_identity": target.source_identity,
        "prior_unknown_attempts": [asdict(item) for item in target.prior_attempts],
        "fallback_article_fingerprint": fallback.article_fingerprint,
        "fallback_content_fingerprint": fallback.content_fingerprint,
        "fallback_media": [
            [item.path, len(item.body), sha256(item.body).hexdigest()]
            for item in (*fallback.body_media, fallback.cover)
        ],
        "visual_plans": [
            {
                "ordinal": slot.ordinal,
                "logical_request_fingerprint": slot.plan.request_fingerprint,
                "reference_publication_checksum": slot.plan.reference_publication_checksum,
            }
            for slot in slots
        ],
        "max_visual_calls": MAX_VISUAL_CALLS,
        "all_or_nothing": True,
        "draft_only": True,
    }
    old = journal.read(AUTH_NAME)
    if old is not None:
        require(
            set(old) == {"binding", "authorized_at", "expires_at"}
            and old["binding"] == binding,
            "backfill_authorization_changed",
        )
        authorized_at = datetime.fromisoformat(cast(str, old["authorized_at"]))
        expires_at = datetime.fromisoformat(cast(str, old["expires_at"]))
        require(
            authorized_at.utcoffset() is not None
            and expires_at.utcoffset() is not None
            and timedelta(0) < expires_at - authorized_at <= timedelta(hours=2)
            and authorized_at <= now,
            "backfill_authorization_deadline_invalid",
        )
        return old
    require(not target.reconciled, "backfill_already_reconciled")
    value = {
        "binding": binding,
        "authorized_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
    }
    if apply:
        journal.write(AUTH_NAME, value)
    return value


def authorization_fingerprint(auth: dict[str, Any]) -> str:
    return _sha(auth)


def _visual_names(ordinal: int) -> tuple[str, str]:
    require(0 <= ordinal < MAX_VISUAL_CALLS, "backfill_visual_ordinal_invalid")
    stem = f"{PREFIX}-visual-{ordinal}"
    return stem + "-intent.json", stem + "-result.json"


async def select_visuals(
    *,
    journal: ManualDraftJournal,
    auth: dict[str, Any],
    slots: tuple[BackfillVisualSlot, ...],
    generator: ImageGenerator,
    store: OfficialAccountGeneratedVisualStore,
    authorize_side_effect: Callable[[], Awaitable[bool]],
) -> VisualSelection:
    auth_fingerprint = authorization_fingerprint(auth)
    bodies: list[bytes] = []
    safe_results: list[dict[str, Any]] = []
    for slot in slots:
        intent_name, result_name = _visual_names(slot.ordinal)
        physical = fingerprint(
            POLICY,
            "physical-visual-request",
            auth_fingerprint,
            slot.ordinal,
            slot.plan.request_fingerprint,
        )
        intent = {
            "version": POLICY,
            "authorization_fingerprint": auth_fingerprint,
            "ordinal": slot.ordinal,
            "logical_request_fingerprint": slot.plan.request_fingerprint,
            "provider_request_fingerprint": physical,
            "reference_publication_checksum": slot.plan.reference_publication_checksum,
            "maximum_calls": 1,
        }
        old_intent = journal.read(intent_name)
        result = journal.read(result_name)
        if old_intent is not None:
            require(old_intent == intent, "backfill_visual_intent_changed")
            if result is None:
                # A durable intent without a result may have crossed the paid POST.
                # Persist the inferred unknown exactly once so the whole-catalog
                # fallback can be sealed and handed to the isolated delivery phase.
                result = {
                    "intent_sha256": _sha(intent),
                    "ordinal": slot.ordinal,
                    "status": "outcome_unknown",
                    "error_code": "official_account_generated_visual_result_unknown",
                    "disposition": "unknown",
                    "reason": "lease_authority_lost",
                    "http_status": None,
                    "response_kind": None,
                }
                journal.write(result_name, result)
                safe_results.append(result)
                return VisualSelection(
                    "approved_catalog_fallback", None, tuple(safe_results)
                )
            require(
                result.get("intent_sha256") == _sha(intent),
                "backfill_visual_result_changed",
            )
            status = result.get("status")
            if status != "ready":
                safe_results.append(dict(result))
                return VisualSelection(
                    "approved_catalog_fallback", None, tuple(safe_results)
                )
            media_type = result.get("media_type")
            byte_size = result.get("byte_size")
            digest = result.get("sha256")
            require(
                isinstance(media_type, str)
                and type(byte_size) is int
                and isinstance(digest, str),
                "backfill_visual_result_changed",
            )
            body = await store.get_content_addressed_bytes(
                media_type=cast(str, media_type),
                byte_size=cast(int, byte_size),
                sha256=cast(str, digest),
            )
            require(
                sha256(body).hexdigest() == digest, "backfill_visual_artifact_changed"
            )
            bodies.append(body)
            safe_results.append(dict(result))
            continue
        require(result is None, "backfill_visual_result_without_intent")
        expires_at = datetime.fromisoformat(cast(str, auth["expires_at"]))
        require(datetime.now(UTC) < expires_at, "backfill_authorization_expired")
        require(await authorize_side_effect(), "backfill_target_changed")
        journal.write(intent_name, intent)
        request = replace(slot.request, provider_request_fingerprint=physical)
        try:
            generated = await generator.generate(request)
            prepared = prepare_generated_visual_result(
                result=generated,
                plan=slot.plan,
                max_bytes=STRICT_VISUAL_POLICY.maximum_image_bytes,
            )
            await store.put_immutable(
                prepared.image_bytes, media_type=prepared.result.media_type
            )
        except BaseException as error:
            if isinstance(
                error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)
            ):
                raise
            diagnostic = classify_image_generation_failure(cast(Exception, error))
            result = {
                "intent_sha256": _sha(intent),
                "ordinal": slot.ordinal,
                "status": (
                    "outcome_unknown"
                    if diagnostic.disposition == "unknown"
                    else "failed"
                ),
                "error_code": diagnostic.error_code,
                "disposition": diagnostic.disposition,
                "reason": diagnostic.reason,
                "http_status": diagnostic.http_status,
                "response_kind": diagnostic.response_kind,
            }
            journal.write(result_name, result)
            safe_results.append(result)
            return VisualSelection(
                "approved_catalog_fallback", None, tuple(safe_results)
            )
        result = {
            "intent_sha256": _sha(intent),
            "ordinal": slot.ordinal,
            "status": "ready",
            "media_type": prepared.result.media_type,
            "byte_size": prepared.result.byte_size,
            "sha256": prepared.result.sha256,
            "width": prepared.result.width,
            "height": prepared.result.height,
            "provider_request_fingerprint": physical,
        }
        journal.write(result_name, result)
        bodies.append(prepared.image_bytes)
        safe_results.append(result)
    require(len(bodies) == MAX_VISUAL_CALLS, "backfill_visual_batch_incomplete")
    return VisualSelection(
        "generated",
        cast(tuple[bytes, bytes, bytes, bytes, bytes], tuple(bodies)),
        tuple(safe_results),
    )


def seal_visual_selection(
    journal: ManualDraftJournal,
    *,
    auth: dict[str, Any],
    selection: VisualSelection,
) -> dict[str, Any]:
    result_hashes: list[list[object]] = []
    for item in selection.safe_results:
        ordinal = item.get("ordinal")
        require(type(ordinal) is int, "backfill_visual_selection_invalid")
        _intent_name, result_name = _visual_names(cast(int, ordinal))
        stored = journal.read(result_name)
        require(stored == item, "backfill_visual_selection_invalid")
        result_hashes.append([ordinal, _sha(stored)])
    require(
        selection.origin == "approved_catalog_fallback"
        or (
            len(result_hashes) == MAX_VISUAL_CALLS
            and all(item.get("status") == "ready" for item in selection.safe_results)
        ),
        "backfill_visual_selection_invalid",
    )
    receipt = {
        "version": POLICY,
        "authorization_fingerprint": authorization_fingerprint(auth),
        "origin": selection.origin,
        "result_sha256s": result_hashes,
        "all_or_nothing": True,
    }
    old = journal.read(SELECTION_NAME)
    if old is None:
        journal.write(SELECTION_NAME, receipt)
    else:
        require(old == receipt, "backfill_visual_selection_changed")
    return receipt


async def load_visual_selection(
    journal: ManualDraftJournal,
    *,
    auth: dict[str, Any],
    slots: tuple[BackfillVisualSlot, ...],
    store: OfficialAccountGeneratedVisualStore,
) -> VisualSelection | None:
    receipt = journal.read(SELECTION_NAME)
    if receipt is None:
        return None
    require(
        set(receipt)
        == {
            "version",
            "authorization_fingerprint",
            "origin",
            "result_sha256s",
            "all_or_nothing",
        }
        and receipt["version"] == POLICY
        and receipt["authorization_fingerprint"] == authorization_fingerprint(auth)
        and receipt["origin"] in {"generated", "approved_catalog_fallback"}
        and receipt["all_or_nothing"] is True
        and isinstance(receipt["result_sha256s"], list),
        "backfill_visual_selection_changed",
    )
    result_hashes = receipt["result_sha256s"]
    results: list[dict[str, Any]] = []
    bodies: list[bytes] = []
    for entry in result_hashes:
        require(
            isinstance(entry, list)
            and len(entry) == 2
            and type(entry[0]) is int
            and isinstance(entry[1], str),
            "backfill_visual_selection_changed",
        )
        ordinal, expected_hash = entry
        _intent_name, result_name = _visual_names(ordinal)
        result = journal.read(result_name)
        require(
            result is not None and _sha(result) == expected_hash,
            "backfill_visual_selection_changed",
        )
        assert result is not None
        results.append(result)
        if receipt["origin"] == "generated":
            require(
                result.get("status") == "ready"
                and isinstance(result.get("media_type"), str)
                and type(result.get("byte_size")) is int
                and isinstance(result.get("sha256"), str),
                "backfill_visual_selection_changed",
            )
            body = await store.get_content_addressed_bytes(
                media_type=cast(str, result["media_type"]),
                byte_size=cast(int, result["byte_size"]),
                sha256=cast(str, result["sha256"]),
            )
            require(
                sha256(body).hexdigest() == result["sha256"],
                "backfill_visual_artifact_changed",
            )
            bodies.append(body)
    if receipt["origin"] == "generated":
        require(
            len(results) == len(slots) == MAX_VISUAL_CALLS
            and [item.get("ordinal") for item in results]
            == [slot.ordinal for slot in slots],
            "backfill_visual_selection_changed",
        )
        return VisualSelection(
            "generated",
            cast(tuple[bytes, bytes, bytes, bytes, bytes], tuple(bodies)),
            tuple(results),
        )
    require(1 <= len(results) <= MAX_VISUAL_CALLS, "backfill_visual_selection_changed")
    return VisualSelection("approved_catalog_fallback", None, tuple(results))


class _ObservedDraftClient:
    def __init__(self, delegate: WeChatOfficialAccountDraftClient) -> None:
        self.delegate = delegate
        self.article: WeChatDraftArticleRequest | None = None

    async def upload_inline_image(
        self, image_bytes: bytes, media_type: str, filename: str
    ) -> WeChatInlineImage:
        return await self.delegate.upload_inline_image(
            image_bytes, media_type, filename
        )

    async def upload_thumb(
        self, image_bytes: bytes, media_type: str, filename: str
    ) -> WeChatThumbMedia:
        return await self.delegate.upload_thumb(image_bytes, media_type, filename)

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        self.article = article
        return await self.delegate.add_draft(article)


async def deliver_and_reconcile(
    *,
    repository: BackfillRepository,
    target: BackfillTarget,
    prepared: WeChatPreparedDraft,
    journal: ManualDraftJournal,
    client: WeChatOfficialAccountDraftClient,
    readback: DraftReadback,
    auth: dict[str, Any],
    authorize_side_effect: Callable[[], Awaitable[bool]],
) -> dict[str, Any]:
    deadline = datetime.fromisoformat(cast(str, auth["expires_at"]))
    journaled = JournaledSingleDraftClient(
        client=client,
        journal=journal,
        edition=replace(target.edition, expires_at=deadline, max_attempts=1),
        prepared=prepared,
        authorize=authorize_side_effect,
        clock=lambda: datetime.now(UTC),
    )
    observed = _ObservedDraftClient(journaled)
    receipt = await WeChatOfficialAccountDraftOnlyService(
        client=observed
    ).create_prepared(prepared)
    require(observed.article is not None, "backfill_draft_request_missing")
    assert observed.article is not None
    receipt_fingerprint = sha256(receipt.draft_media_id.encode()).hexdigest()
    verify_name = f"{PREFIX}-readback.json"
    old_verify = journal.read(verify_name)
    expected_verify = {
        "version": POLICY,
        "authorization_fingerprint": authorization_fingerprint(auth),
        "receipt_fingerprint": receipt_fingerprint,
        "article_fingerprint": prepared.article_fingerprint,
        "content_fingerprint": prepared.content_fingerprint,
        "request_fingerprint": _sha(asdict(observed.article)),
        "verified": True,
        "not_published": True,
    }
    if old_verify is None:
        verified = await readback.verify(receipt.draft_media_id, observed.article)
        if not verified:
            return {
                "status": "created_unverified",
                "receipt_fingerprint": receipt_fingerprint,
                "not_published": True,
                "database_reconciled": False,
            }
        journal.write(verify_name, expected_verify)
    else:
        require(old_verify == expected_verify, "backfill_readback_changed")
    reconciled = await repository.reconcile(
        target=target,
        prepared=prepared,
        receipt_fingerprint=receipt_fingerprint,
        authorization_fingerprint=authorization_fingerprint(auth),
        now=datetime.now(UTC),
    )
    require(reconciled, "backfill_database_reconciliation_failed")
    return {
        "status": "delivered",
        "receipt_fingerprint": receipt_fingerprint,
        "not_published": True,
        "readback_verified": True,
        "database_reconciled": True,
    }


class PostgresBackfillRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def load_target(self) -> BackfillTarget:
        async with self.sessions() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            return await _load_target(session)

    async def reconcile(
        self,
        *,
        target: BackfillTarget,
        prepared: WeChatPreparedDraft,
        receipt_fingerprint: str,
        authorization_fingerprint: str,
        now: datetime,
    ) -> bool:
        async with self.sessions() as session, session.begin():
            edition = await session.scalar(
                select(Edition).where(Edition.id == EDITION).with_for_update()
            )
            if edition is None:
                return False
            event_owner = await session.scalar(
                select(Owner)
                .where(
                    Owner.account_fingerprint == ACCOUNT,
                    Owner.key_kind == "event",
                    Owner.key_value == str(target.event_id),
                )
                .with_for_update()
            )
            article_owner = await session.scalar(
                select(Owner)
                .where(
                    Owner.account_fingerprint == ACCOUNT,
                    Owner.key_kind == "article",
                    Owner.key_value == prepared.article_fingerprint,
                )
                .with_for_update()
            )
            if edition.status == "delivered":
                return bool(
                    edition.receipt_fingerprint == receipt_fingerprint
                    and edition.article_fingerprint == prepared.article_fingerprint
                    and edition.content_fingerprint == prepared.content_fingerprint
                    and event_owner is not None
                    and event_owner.owner == str(EDITION)
                    and event_owner.status == "acknowledged"
                    and article_owner is not None
                    and article_owner.owner == str(EDITION)
                    and article_owner.status == "acknowledged"
                )
            current = await _load_target(session, lock=False)
            if current.source_identity != target.source_identity or current.reconciled:
                return False
            provenance = fingerprint(
                POLICY,
                authorization_fingerprint,
                prepared.article_fingerprint,
                prepared.content_fingerprint,
                receipt_fingerprint,
            )
            if article_owner is None:
                await session.execute(
                    insert(Owner).values(
                        account_fingerprint=ACCOUNT,
                        key_kind="article",
                        key_value=prepared.article_fingerprint,
                        owner=str(EDITION),
                        status="acknowledged",
                        provenance_fingerprint=provenance,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif (
                article_owner.owner != str(EDITION)
                or article_owner.status == "conflict"
            ):
                return False
            else:
                article_owner.status = "acknowledged"
                article_owner.provenance_fingerprint = provenance
                article_owner.updated_at = now
            if event_owner is None or event_owner.owner != str(EDITION):
                return False
            event_owner.status = "acknowledged"
            event_owner.provenance_fingerprint = provenance
            event_owner.updated_at = now
            artifact_payload = {
                "version": POLICY,
                "authorization_fingerprint": authorization_fingerprint,
                "article_fingerprint": prepared.article_fingerprint,
                "content_fingerprint": prepared.content_fingerprint,
                "receipt_fingerprint": receipt_fingerprint,
            }
            artifact = WeeklyDagArtifact(
                opaque_ref=f"single-backfill:{authorization_fingerprint}",
                fingerprint=_sha(artifact_payload),
                media_type="application/json",
                byte_size=len(_canonical(artifact_payload)),
            )
            edition.status = "delivered"
            edition.prepared_artifact = asdict(artifact)
            edition.article_fingerprint = prepared.article_fingerprint
            edition.content_fingerprint = prepared.content_fingerprint
            edition.receipt_fingerprint = receipt_fingerprint
            edition.error_code = None
            edition.lease_token = None
            edition.lease_expires_at = None
            edition.updated_at = now
            return True


def _diagnostic_disposition(row: Attempt) -> str | None:
    value = row.safe_metadata.get("image_failure")
    return str(value.get("disposition")) if isinstance(value, dict) else None


def _diagnostic_error_code(row: Attempt) -> str | None:
    value = row.safe_metadata.get("image_failure")
    return str(value.get("error_code")) if isinstance(value, dict) else None


async def _load_target(session: AsyncSession, *, lock: bool = False) -> BackfillTarget:
    edition_query = select(Edition).where(Edition.id == EDITION)
    if lock:
        edition_query = edition_query.with_for_update()
    edition = await session.scalar(edition_query)
    require(
        edition is not None
        and edition.account_fingerprint == ACCOUNT
        and edition.business_date == DAY
        and edition.id == EDITION
        and edition.event_id is not None
        and edition.article_run_id is not None
        and edition.lease_token is None
        and edition.lease_expires_at is None,
        "backfill_target_changed",
    )
    assert (
        edition is not None
        and edition.event_id is not None
        and edition.article_run_id is not None
    )
    run = await session.get(Run, edition.article_run_id)
    require(
        run is not None
        and run.id == edition.article_run_id
        and run.active_article_version_id is not None
        and run.active_render_version_id is not None
        and run.active_body_media_id is None
        and run.active_cover_media_id is None
        and run.active_draft_id is None
        and run.lease_owner is None
        and run.lease_token is None
        and run.lease_expires_at is None
        and run.status == "failed"
        and run.current_stage == "failed"
        and run.error_code == "strict_visual_generation_attempts_exhausted",
        "backfill_target_changed",
    )
    assert run is not None and run.active_article_version_id is not None
    assert run.active_render_version_id is not None
    article_row = await session.get(Article, run.active_article_version_id)
    render_row = await session.get(Render, run.active_render_version_id)
    require(
        article_row is not None
        and render_row is not None
        and article_row.run_id == run.id
        and render_row.run_id == run.id
        and render_row.article_version_id == article_row.id
        and article_row.audit_snapshot.get("accepted") is True
        and article_row.validation_snapshot.get("passed") is True,
        "backfill_content_changed",
    )
    assert article_row is not None and render_row is not None
    article = _stored_article(article_row)
    render = _stored_render(render_row)
    require(
        article.article.content_fingerprint == article_row.content_fingerprint,
        "backfill_content_changed",
    )
    visual = await session.scalar(
        select(Visual).where(Visual.run_id == run.id, Visual.ordinal == 0)
    )
    require(
        visual is not None
        and visual.article_version_id == article.id
        and visual.render_version_id == render.id
        and visual.status == "result_unknown"
        and visual.error_code == "official_account_generated_visual_result_unknown",
        "backfill_visual_history_changed",
    )
    attempts = tuple(
        (
            await session.scalars(
                select(Attempt)
                .where(
                    Attempt.run_id == run.id,
                    Attempt.capability == "visual_generation",
                    Attempt.stage == "generating_body_visuals",
                    Attempt.ordinal.in_((101, 102, 103)),
                )
                .order_by(Attempt.ordinal)
            )
        ).all()
    )
    require(
        len(attempts) == 3
        and tuple(row.ordinal for row in attempts) == (101, 102, 103)
        and tuple(_diagnostic_error_code(row) for row in attempts)
        == EXPECTED_PRIOR_ERRORS
        and all(
            row.status == "failed"
            and row.error_code == "official_account_generated_visual_result_unknown"
            and row.provider_request_id is None
            and _diagnostic_disposition(row) == "unknown"
            for row in attempts
        )
        and len({row.request_fingerprint for row in attempts}) == 3,
        "backfill_visual_history_changed",
    )
    event_owner = await session.get(Owner, (ACCOUNT, "event", str(edition.event_id)))
    article_owner = await session.get(
        Owner, (ACCOUNT, "article", article.article.content_fingerprint)
    )
    drafts = await session.scalar(
        select(DraftItem.job_id)
        .where(
            or_(
                DraftItem.source_ref == str(run.id),
                DraftItem.source_ref == str(edition.id),
                DraftItem.source_fingerprint == run.source_fingerprint,
                DraftItem.article_fingerprint == article.article.content_fingerprint,
            )
        )
        .limit(1)
    )
    reconciled = edition.status == "delivered"
    if reconciled:
        require(
            edition.prepared_artifact is not None
            and edition.receipt_fingerprint is not None
            and edition.article_fingerprint == article.article.content_fingerprint
            and event_owner is not None
            and event_owner.owner == str(EDITION)
            and event_owner.status == "acknowledged"
            and article_owner is not None
            and article_owner.owner == str(EDITION)
            and article_owner.status == "acknowledged",
            "backfill_reconciliation_changed",
        )
    else:
        require(
            edition.status == "failed"
            and edition.error_code == "single_article_failed"
            and edition.prepared_artifact is None
            and edition.receipt_fingerprint is None
            and edition.article_fingerprint is None
            and edition.content_fingerprint is None
            and event_owner is not None
            and event_owner.owner == str(EDITION)
            and event_owner.status == "reserved"
            and article_owner is None
            and drafts is None,
            "backfill_target_changed",
        )
    plan_version = run.version_bundle.get("generated_visual_plan_version")
    prompt_version = run.version_bundle.get("generated_visual_prompt_version")
    require(
        isinstance(plan_version, str) and isinstance(prompt_version, str),
        "backfill_visual_policy_changed",
    )
    prior = cast(
        tuple[PriorVisualAttempt, PriorVisualAttempt, PriorVisualAttempt],
        tuple(
            PriorVisualAttempt(
                row.ordinal,
                row.request_fingerprint,
                cast(str, _diagnostic_error_code(row)),
                cast(str, _diagnostic_disposition(row)),
            )
            for row in attempts
        ),
    )
    source_identity = fingerprint(
        POLICY,
        {
            "edition_id": edition.id,
            "account": edition.account_fingerprint,
            "business_date": edition.business_date,
            "version": edition.version,
            "article_identity": edition.article_identity,
            "retry_policy": edition.retry_policy,
            "selection_artifact": edition.selection_artifact,
            "material_package_id": edition.material_package_id,
            "event_id": edition.event_id,
            "article_run_id": edition.article_run_id,
            "role": edition.role,
        },
        {
            "run_id": run.id,
            "material_package_id": run.material_package_id,
            "generation_mode": run.generation_mode,
            "source_fingerprint": run.source_fingerprint,
            "request_fingerprint": run.request_fingerprint,
            "provider": run.provider,
            "model": run.model,
            "version_bundle": run.version_bundle,
            "active_article_version_id": run.active_article_version_id,
            "active_render_version_id": run.active_render_version_id,
        },
        _row_snapshot(article_row),
        _row_snapshot(render_row),
        _row_snapshot(visual),
        tuple(_row_snapshot(row) for row in attempts),
        {
            "account": event_owner.account_fingerprint,
            "key_kind": event_owner.key_kind,
            "key_value": event_owner.key_value,
            "owner": event_owner.owner,
        }
        if event_owner is not None
        else None,
    )
    return BackfillTarget(
        edition=_snapshot(edition),
        article=article,
        render=render,
        run_id=run.id,
        event_id=edition.event_id,
        source_identity=source_identity,
        prior_attempts=prior,
        plan_version=cast(str, plan_version),
        prompt_version=cast(str, prompt_version),
        reconciled=reconciled,
    )


def _row_snapshot(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


class _HtmlProjection(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[object] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        require(
            len({name for name, _ in attrs}) == len(attrs),
            "backfill_readback_html_invalid",
        )
        normalized: list[tuple[str, str | None]] = []
        for name, value in attrs:
            key = "src" if tag == "img" and name in {"src", "data-src"} else name
            if key == "leaf" and value in {None, "", "leaf"}:
                # WeChat serializes the renderer's bare boolean marker `leaf`
                # as `leaf="leaf"`; attribute presence is the same DOM signal.
                value = "{present}"
            if key == "src" and value is not None:
                value = re.sub(r"/(?:0|640)(?=\?|$)", "/{size}", value)
            normalized.append((key, value))
        require(
            len({name for name, _ in normalized}) == len(normalized),
            "backfill_readback_html_invalid",
        )
        self.tokens.append(("start", tag, tuple(sorted(normalized))))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in {"img", "br"}:
            self.tokens.append(("end", tag))

    def handle_endtag(self, tag: str) -> None:
        if tag not in {"img", "br"}:
            self.tokens.append(("end", tag))

    def handle_data(self, data: str) -> None:
        self.tokens.append(("text", data))

    def handle_comment(self, data: str) -> None:
        raise ValueError("backfill_readback_html_invalid")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("backfill_readback_html_invalid")


def equivalent_draft(
    expected: WeChatDraftArticleRequest, actual: WeChatDraftArticleRequest
) -> bool:
    if replace(expected, content=actual.content) != actual:
        return False
    left, right = _HtmlProjection(), _HtmlProjection()
    try:
        left.feed(expected.content)
        left.close()
        right.feed(actual.content)
        right.close()
    except ValueError:
        return False
    return left.tokens == right.tokens


class OfficialDraftReadback:
    """Narrow read-only companion using the product client's token/cache/transport."""

    def __init__(self, client: WeChatOfficialAccountHttpClient) -> None:
        self.client = client

    async def verify(self, media_id: str, expected: WeChatDraftArticleRequest) -> bool:
        token = await self.client._get_access_token()
        try:
            async with asyncio.timeout(self.client._total_timeout_seconds):
                async with self.client._client.stream(
                    "POST",
                    self.client._base_url + "/cgi-bin/draft/get",
                    params={"access_token": token.value},
                    json={"media_id": media_id},
                    follow_redirects=False,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    timeout=self.client._timeout,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        return False
                    if response.headers.get(
                        "content-encoding", "identity"
                    ).casefold() not in {
                        "",
                        "identity",
                    }:
                        return False
                    chunks: list[bytes] = []
                    count = 0
                    async for chunk in response.aiter_bytes():
                        count += len(chunk)
                        if count > 1024 * 1024:
                            return False
                        chunks.append(chunk)
        except (TimeoutError, httpx.HTTPError):
            return False
        try:
            payload = json.loads(
                b"".join(chunks),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_constant,
            )
            require(isinstance(payload, dict), "backfill_readback_invalid")
            if payload.get("errcode") not in {None, 0}:
                return False
            items = payload.get("news_item")
            require(
                isinstance(items, list) and len(items) == 1, "backfill_readback_invalid"
            )
            item = items[0]
            require(isinstance(item, dict), "backfill_readback_invalid")
            actual = WeChatDraftArticleRequest(
                title=_readback_text(item, "title"),
                author=_readback_text(item, "author"),
                digest=_readback_text(item, "digest"),
                content=_readback_text(item, "content"),
                content_source_url=(
                    _readback_text(item, "content_source_url")
                    if item.get("content_source_url") not in {None, ""}
                    else None
                ),
                thumb_media_id=_readback_text(item, "thumb_media_id"),
                need_open_comment=_readback_bool(item, "need_open_comment"),
                only_fans_can_comment=_readback_bool(item, "only_fans_can_comment"),
            )
            require(
                item.get("article_type", "news") == "news", "backfill_readback_invalid"
            )
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            return False
        return equivalent_draft(expected, actual)


def _unique_object(pairs: list[tuple[object, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if not isinstance(key, str) or key in value:
            raise ValueError("backfill_readback_invalid")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError("backfill_readback_invalid")


def _readback_text(item: dict[str, object], key: str) -> str:
    value = item[key]
    require(isinstance(value, str), "backfill_readback_invalid")
    return cast(str, value)


def _readback_bool(item: dict[str, object], key: str) -> bool:
    value = item.get(key, 0)
    require(type(value) is int and value in {0, 1}, "backfill_readback_invalid")
    return bool(value)


async def _plan_context(
    *,
    repository: BackfillRepository,
    journal: ManualDraftJournal,
    catalog: CatalogProvider,
    now: datetime,
) -> tuple[
    BackfillTarget,
    WeChatPreparedDraft,
    tuple[BackfillVisualSlot, ...],
    dict[str, Any],
    dict[str, Any],
]:
    target = await repository.load_target()
    fallback = await prepare_fallback(target, catalog)
    slots = await plan_visual_slots(target, catalog)
    auth = authorize(
        journal,
        target=target,
        fallback=fallback,
        slots=slots,
        now=now,
        apply=False,
    )
    summary: dict[str, Any] = {
        "policy": POLICY,
        "business_date": DAY.isoformat(),
        "edition_fingerprint": sha256(str(EDITION).encode()).hexdigest(),
        "source_identity": target.source_identity,
        "article_fingerprint": target.article.article.content_fingerprint,
        "fallback_content_fingerprint": fallback.content_fingerprint,
        "prior_unknown_attempts": len(target.prior_attempts),
        "new_visual_call_limit": MAX_VISUAL_CALLS,
        "draft_only": True,
        "not_published": True,
        "already_reconciled": target.reconciled,
    }
    return target, fallback, slots, auth, summary


async def generate_visuals_phase(
    *,
    repository: BackfillRepository,
    journal: ManualDraftJournal,
    catalog: CatalogProvider,
    generator: ImageGenerator | None,
    store: OfficialAccountGeneratedVisualStore | None,
    apply: bool,
    now: datetime,
) -> dict[str, Any]:
    target, fallback, slots, preview_auth, summary = await _plan_context(
        repository=repository, journal=journal, catalog=catalog, now=now
    )
    summary = {
        **summary,
        "phase": "generate_visuals",
        "mode": "apply" if apply else "plan",
    }
    if not apply or target.reconciled:
        return summary
    require(
        generator is not None and store is not None, "backfill_image_runtime_missing"
    )
    assert generator is not None and store is not None
    auth = authorize(
        journal,
        target=target,
        fallback=fallback,
        slots=slots,
        now=now,
        apply=True,
    )
    require(auth == preview_auth, "backfill_authorization_changed")

    async def still_authorized() -> bool:
        current = await repository.load_target()
        return (
            not current.reconciled
            and current.source_identity == target.source_identity
            and datetime.now(UTC)
            < datetime.fromisoformat(cast(str, auth["expires_at"]))
        )

    selection = await select_visuals(
        journal=journal,
        auth=auth,
        slots=slots,
        generator=generator,
        store=store,
        authorize_side_effect=still_authorized,
    )
    receipt = seal_visual_selection(journal, auth=auth, selection=selection)
    return {
        **summary,
        "visual_origin": selection.origin,
        "selection_fingerprint": _sha(receipt),
        "visual_results": [
            {
                key: value
                for key, value in item.items()
                if key in {"ordinal", "status", "error_code", "disposition", "reason"}
            }
            for item in selection.safe_results
        ],
        "provider_calls_consumed": len(selection.safe_results),
        "wechat_calls": 0,
    }


async def deliver_phase(
    *,
    repository: BackfillRepository,
    journal: ManualDraftJournal,
    catalog: CatalogProvider,
    store: OfficialAccountGeneratedVisualStore,
    client: WeChatOfficialAccountDraftClient | None,
    readback: DraftReadback | None,
    apply: bool,
    now: datetime,
) -> dict[str, Any]:
    target, fallback, slots, auth, summary = await _plan_context(
        repository=repository, journal=journal, catalog=catalog, now=now
    )
    summary = {**summary, "phase": "deliver", "mode": "apply" if apply else "plan"}
    if target.reconciled:
        return summary
    require(
        journal.read(AUTH_NAME) is not None or not apply,
        "backfill_visual_phase_not_authorized",
    )
    selection = await load_visual_selection(
        journal, auth=auth, slots=slots, store=store
    )
    if selection is None:
        require(not apply, "backfill_visual_selection_missing")
        return {**summary, "status": "awaiting_visual_selection"}
    if selection.origin == "generated":
        assert selection.bodies is not None
        prepared = _render_prepared(
            target.article.article,
            selection.bodies,
            origin="generated",
            lineage=tuple(
                (item["ordinal"], item["sha256"], item["provider_request_fingerprint"])
                for item in selection.safe_results
            ),
        )
    else:
        prepared = fallback
    if not apply:
        return {
            **summary,
            "status": "ready_to_deliver",
            "visual_origin": selection.origin,
            "content_fingerprint": prepared.content_fingerprint,
            "provider_calls": 0,
            "wechat_calls": 0,
        }
    require(
        client is not None and readback is not None, "backfill_wechat_runtime_missing"
    )
    assert client is not None and readback is not None

    async def still_authorized() -> bool:
        current = await repository.load_target()
        return (
            not current.reconciled
            and current.source_identity == target.source_identity
            and datetime.now(UTC)
            < datetime.fromisoformat(cast(str, auth["expires_at"]))
        )

    result = await deliver_and_reconcile(
        repository=repository,
        target=target,
        prepared=prepared,
        journal=journal,
        client=client,
        readback=readback,
        auth=auth,
        authorize_side_effect=still_authorized,
    )
    return {
        **summary,
        **result,
        "visual_origin": selection.origin,
        "visual_results": [
            {
                key: value
                for key, value in item.items()
                if key in {"ordinal", "status", "error_code", "disposition", "reason"}
            }
            for item in selection.safe_results
        ],
        "content_fingerprint": prepared.content_fingerprint,
        "provider_calls": 0,
    }


async def _main(command: str, apply: bool) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.infrastructure.db.session import create_engine, create_session_factory

    settings = get_settings()
    require(
        command in {"plan", "generate-visuals", "deliver"}, "backfill_command_invalid"
    )
    require(command != "plan" or not apply, "backfill_plan_apply_invalid")
    if command == "deliver":
        require(
            settings.wechat_mp_app_id is not None
            and wechat_draft_account_fingerprint(
                settings.wechat_mp_app_id.get_secret_value()
            )
            == ACCOUNT,
            "backfill_account_mismatch",
        )
    root = Path(settings.wechat_mp_draft_artifact_root)
    directory = root / "manual-v1" / ACCOUNT
    require(
        directory.is_dir() and not directory.is_symlink(),
        "backfill_journal_mount_missing",
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    repository = PostgresBackfillRepository(sessions)
    journal: LocalManualDraftJournal | None = None
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        journal = LocalManualDraftJournal(root, ACCOUNT)
        catalog = LocalOfficialAccountCatalogMediaProvider(
            settings.image_asset_manifest
        )
        if command == "plan":
            _target, _fallback, _slots, _auth, summary = await _plan_context(
                repository=repository,
                journal=journal,
                catalog=catalog,
                now=datetime.now(UTC),
            )
            return {**summary, "phase": "plan", "mode": "plan", "remote_calls": 0}
        if command == "generate-visuals":
            return await generate_visuals_phase(
                repository=repository,
                journal=journal,
                catalog=catalog,
                generator=LazyStrictOfficialAccountImageGenerator(settings)
                if apply
                else None,
                store=MinioImageStore(settings) if apply else None,
                apply=apply,
                now=datetime.now(UTC),
            )
        store = MinioImageStore(settings)
        if apply:
            client = WeChatOfficialAccountHttpClient(settings)
        return await deliver_phase(
            repository=repository,
            journal=journal,
            catalog=catalog,
            store=store,
            client=client,
            readback=OfficialDraftReadback(client) if client is not None else None,
            apply=apply,
            now=datetime.now(UTC),
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
    parser.add_argument(
        "command",
        nargs="?",
        default="plan",
        choices=("plan", "generate-visuals", "deliver"),
    )
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        print(
            json.dumps(
                asyncio.run(_main(arguments.command, arguments.apply)),
                ensure_ascii=False,
            )
        )
    except Exception as error:  # noqa: BLE001 - constant, secret-free operator boundary
        code = getattr(error, "code", None)
        if not isinstance(code, str) and isinstance(error, ValueError):
            code = str(error)
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{1,79}", code) is None
        ):
            code = "backfill_operator_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}))
        raise SystemExit(1) from None
