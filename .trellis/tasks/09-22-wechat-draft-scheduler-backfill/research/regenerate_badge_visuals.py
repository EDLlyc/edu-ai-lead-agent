"""Generate one new five-image Xiaosai chest-badge correction batch.

The default ``plan`` command is read-only. ``generate --apply`` is the only
side-effecting command: it writes durable image intents and content-addressed
image results to the existing private operator boundary. It never uploads
media, creates or changes an official-account draft, publishes content, or
writes application database state.

This transient exact-target operator deliberately stays compatible with the
production backend at ``abfb89d``. Its corrected prompt semantics are taken
from reviewed commit ``720305b``.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import re
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

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
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    plan_generated_body_visual,
    prepare_generated_visual_result,
)
from app.core.errors import classify_image_generation_failure
from app.domain.image_generation import validate_image_prompt
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_local import fingerprint
from app.domain.official_account_visual_pipeline import STRICT_VISUAL_POLICY
from app.infrastructure.ai.official_account_visual_strict import (
    LazyStrictOfficialAccountImageGenerator,
)
from app.infrastructure.db.models import OfficialAccountArticleRunModel as Run
from app.infrastructure.db.models import OfficialAccountArticleVersionModel as Article
from app.infrastructure.db.models import OfficialAccountGeneratedVisualModel as Visual
from app.infrastructure.db.models import OfficialAccountRenderVersionModel as Render
from app.infrastructure.db.models import OfficialAccountSingleEditionModel as Edition
from app.infrastructure.db.official_account_local import _stored_article, _stored_render
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

POLICY = "sep21-xiaosai-ai-badge-regeneration-v1"
ACCOUNT = "ae3a5056a1c78eddf728060ecc5287b6a93e48d99e496bc9a22292a2b4eb8fd7"
DAY = date(2026, 9, 21)
EDITION = UUID("3afa48cb-f0a1-5912-b538-5ed2d2fb14c0")
PREFIX = f"badgefix-{EDITION.hex}-v1"
MANIFEST_NAME = f"{PREFIX}-manifest.json"
SELECTION_NAME = f"{PREFIX}-selection.json"
MAX_PROVIDER_CALLS = 5
ARTIFACT_ROOT_ENV = "WECHAT_MP_DRAFT_ARTIFACT_ROOT"

_OLD_IDENTITY = (
    "Keep Xiaosai fully visible, recognizable and central, not a badge, pasted avatar or "
    "catalog pose. "
)
_NEW_IDENTITY = (
    "Keep Xiaosai fully visible, central and recognizable, with mandatory small centered blue "
    "'AI' chest panel; never avatar/catalog pose. "
)
_OLD_TEXT_RULE = (
    "palette; generous margins and safe faces/action; calm, curious. Text: none. No words, "
    "letters, numbers, logos, chest labels, UI, QR, watermarks, ads, photorealism, "
)
_NEW_TEXT_RULE = (
    "palette; generous margins; calm and curious. Text: none except Xiaosai's white 'AI' chest "
    "badge. No other words, letters, numbers, logos, marks, labels, UI, QR, watermarks, ads, "
    "photorealism, "
)


class OperatorError(ValueError):
    """One bounded, secret-free operator failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require(condition: object, code: str) -> None:
    if not condition:
        raise OperatorError(code)


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
class CorrectionTarget:
    article: StoredOfficialAccountArticle
    render: StoredOfficialAccountRender
    run_id: UUID
    target_identity: str
    plan_version: str
    prompt_version: str


@dataclass(frozen=True, slots=True)
class CorrectionVisualSlot:
    ordinal: int
    plan: OfficialAccountGeneratedVisualPlan
    request: ImageGenerationRequest
    prompt_sha256: str


class ReadOnlyRepository(Protocol):
    async def load_target(self) -> CorrectionTarget: ...


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


class PrivateJournal:
    """Create-only, descriptor-relative JSON receipts under one fixed account lock."""

    def __init__(self, artifact_root: Path, account: str) -> None:
        require(
            re.fullmatch(r"[0-9a-f]{64}", account) is not None,
            "badge_regeneration_account_invalid",
        )
        base = artifact_root.absolute()
        require(
            base != Path("/") and base.is_dir() and not base.is_symlink(),
            "badge_regeneration_journal_root_invalid",
        )
        root_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in ("manual-v1", account):
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
                os.close(root_fd)
                root_fd = child
                info = os.fstat(root_fd)
                require(
                    info.st_uid == os.getuid() and not info.st_mode & 0o077,
                    "badge_regeneration_journal_root_invalid",
                )
            self._directory = root_fd
            self._lock = os.open(
                "lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=root_fd,
            )
            self._require_safe_file(self._lock)
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise OperatorError("badge_regeneration_journal_locked") from None
        except BaseException:
            if hasattr(self, "_lock"):
                os.close(self._lock)
            os.close(root_fd)
            raise

    @staticmethod
    def _require_safe_file(fd: int) -> None:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o077,
            "badge_regeneration_journal_file_invalid",
        )

    @staticmethod
    def _safe_name(name: str) -> str:
        require(
            re.fullmatch(r"[a-z0-9_-]{1,180}\.json", name) is not None,
            "badge_regeneration_journal_name_invalid",
        )
        return name

    def close(self) -> None:
        os.close(self._lock)
        os.close(self._directory)

    def read(self, name: str) -> dict[str, Any] | None:
        try:
            fd = os.open(
                self._safe_name(name),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=self._directory,
            )
        except FileNotFoundError:
            return None
        try:
            self._require_safe_file(fd)
            before = os.fstat(fd)
            require(
                before.st_size <= 256 * 1024, "badge_regeneration_journal_oversized"
            )
            with os.fdopen(os.dup(fd), "rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            after = os.fstat(fd)
            require(
                (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "badge_regeneration_journal_changed",
            )
            envelope = json.loads(raw)
            require(
                isinstance(envelope, dict) and set(envelope) == {"payload", "sha256"},
                "badge_regeneration_journal_corrupt",
            )
            payload = envelope["payload"]
            require(
                isinstance(payload, dict) and _sha(payload) == envelope["sha256"],
                "badge_regeneration_journal_corrupt",
            )
            require(_canonical(envelope) == raw, "badge_regeneration_journal_corrupt")
            return dict(payload)
        finally:
            os.close(fd)

    def write(self, name: str, payload: dict[str, Any]) -> None:
        raw = _canonical({"payload": payload, "sha256": _sha(payload)})
        fd = os.open(
            self._safe_name(name),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._directory,
        )
        try:
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(self._directory)
        finally:
            os.close(fd)


def build_badge_visual_prompt(
    *,
    article: StoredOfficialAccountArticle,
    section_index: int,
    reference: OfficialAccountSourceMedia,
    prompt_version: str,
    block_index: int | None,
) -> str:
    """Apply the reviewed badge semantics to either old or corrected V5 code."""

    prompt = build_generated_visual_prompt(
        article=article,
        section_index=section_index,
        reference=reference,
        prompt_version=prompt_version,
        block_index=block_index,
    )
    if _NEW_IDENTITY not in prompt:
        require(_OLD_IDENTITY in prompt, "badge_regeneration_prompt_base_changed")
        prompt = prompt.replace(_OLD_IDENTITY, _NEW_IDENTITY, 1)
    if _NEW_TEXT_RULE not in prompt:
        require(_OLD_TEXT_RULE in prompt, "badge_regeneration_prompt_base_changed")
        prompt = prompt.replace(_OLD_TEXT_RULE, _NEW_TEXT_RULE, 1)
    require(
        prompt.count(_NEW_IDENTITY) == 1
        and prompt.count(_NEW_TEXT_RULE) == 1
        and "mandatory small centered blue 'AI' chest panel" in prompt
        and "Text: none except Xiaosai's white 'AI' chest badge" in prompt
        and "No other words, letters, numbers, logos, marks, labels, UI, QR, watermarks"
        in prompt
        and "chest labels" not in prompt,
        "badge_regeneration_prompt_invalid",
    )
    return validate_image_prompt(prompt)


def assigned_reference(
    *, assignment: Any, catalog_version: str, reference: OfficialAccountSourceMedia
) -> OfficialAccountSourceMedia:
    require(
        reference.catalog_version == catalog_version
        and reference.source_master_sha256 == assignment.source_checksum
        and reference.sha256 == assignment.publication_checksum
        and reference.catalog_asset_ref == assignment.candidate_ref,
        "badge_regeneration_reference_changed",
    )
    return replace(
        reference,
        ordinal=assignment.ordinal,
        assigned_section_index=assignment.section_index,
        selection_reason_code=assignment.reason_code,
        selection_method=assignment.selection_method,
        similarity_band=assignment.similarity_band,
    )


async def plan_visual_slots(
    target: CorrectionTarget, catalog: CatalogProvider
) -> tuple[CorrectionVisualSlot, ...]:
    selection = target.article.article.media_selection
    require(
        selection is not None and len(selection.assignments) == MAX_PROVIDER_CALLS,
        "badge_regeneration_selection_invalid",
    )
    assert selection is not None
    candidates = await catalog.load_candidates()
    by_ref = {item.catalog_asset_ref: item for item in candidates}
    require(len(by_ref) == len(candidates), "badge_regeneration_catalog_invalid")
    slots: list[CorrectionVisualSlot] = []
    for assignment in sorted(selection.assignments, key=lambda item: item.ordinal):
        reference = by_ref.get(assignment.candidate_ref)
        require(reference is not None, "badge_regeneration_reference_missing")
        assert reference is not None
        reference = assigned_reference(
            assignment=assignment,
            catalog_version=selection.catalog_version,
            reference=reference,
        )
        reference_bytes = await catalog.read_publication_bytes(
            catalog_asset_ref=reference.catalog_asset_ref or "",
            catalog_version=reference.catalog_version or "",
            source_master_sha256=reference.source_master_sha256 or "",
            publication_sha256=reference.sha256,
        )
        require(
            sha256(reference_bytes).hexdigest() == reference.sha256,
            "badge_regeneration_reference_changed",
        )
        base_plan = plan_generated_body_visual(
            run_id=target.run_id,
            article=target.article,
            render=target.render,
            ordinal=assignment.ordinal,
            reference=reference,
            reference_bytes=reference_bytes,
            provider=STRICT_VISUAL_POLICY.generation_provider,
            model=STRICT_VISUAL_POLICY.generation_model,
            plan_version=target.plan_version,
            prompt_version=target.prompt_version,
        )
        prompt = build_badge_visual_prompt(
            article=target.article,
            section_index=base_plan.section_index,
            reference=reference,
            prompt_version=base_plan.prompt_version,
            block_index=base_plan.block_index,
        )
        prompt_digest = sha256(prompt.encode()).hexdigest()
        logical = fingerprint(
            POLICY,
            "logical-corrected-visual-request",
            target.target_identity,
            assignment.ordinal,
            base_plan.request_fingerprint,
            prompt_digest,
        )
        plan = replace(base_plan, request_fingerprint=logical)
        request = ImageGenerationRequest(
            run_id=target.run_id,
            draft_version_id=target.article.id,
            prompt=prompt,
            request_fingerprint=logical,
            output_size=STRICT_VISUAL_POLICY.output_size,
            references=(
                ImageReference(
                    role="approved_ip_reference",
                    asset_id=plan.reference_asset_ref,
                    filename=f"reference-{plan.reference_asset_ref}.jpg",
                    sha256=reference.sha256,
                    image_bytes=reference_bytes,
                    selection_reason="approved_catalog_semantic_reference",
                    input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
                    provider_input_sha256=plan.reference_input_checksum,
                ),
            ),
            reference_mode="single_reference",
        )
        slots.append(
            CorrectionVisualSlot(
                ordinal=assignment.ordinal,
                plan=plan,
                request=request,
                prompt_sha256=prompt_digest,
            )
        )
    require(
        [slot.ordinal for slot in slots] == list(range(MAX_PROVIDER_CALLS))
        and len({slot.plan.request_fingerprint for slot in slots})
        == MAX_PROVIDER_CALLS,
        "badge_regeneration_slots_invalid",
    )
    return tuple(slots)


def _physical_identity(target_identity: str, slot: CorrectionVisualSlot) -> str:
    return fingerprint(
        POLICY,
        "physical-corrected-visual-request",
        target_identity,
        slot.ordinal,
        slot.plan.request_fingerprint,
        slot.prompt_sha256,
    )


def _intent_name(ordinal: int) -> str:
    require(0 <= ordinal < MAX_PROVIDER_CALLS, "badge_regeneration_ordinal_invalid")
    return f"{PREFIX}-visual-{ordinal}-intent.json"


def _result_name(ordinal: int) -> str:
    require(0 <= ordinal < MAX_PROVIDER_CALLS, "badge_regeneration_ordinal_invalid")
    return f"{PREFIX}-visual-{ordinal}-result.json"


def _manifest(
    target: CorrectionTarget, slots: tuple[CorrectionVisualSlot, ...]
) -> dict[str, Any]:
    return {
        "version": POLICY,
        "account": ACCOUNT,
        "business_date": DAY.isoformat(),
        "edition_fingerprint": sha256(str(EDITION).encode()).hexdigest(),
        "target_identity": target.target_identity,
        "article_fingerprint": target.article.article.content_fingerprint,
        "max_provider_calls": MAX_PROVIDER_CALLS,
        "one_call_per_slot": True,
        "generation_only": True,
        "slots": [
            {
                "ordinal": slot.ordinal,
                "logical_request_fingerprint": slot.plan.request_fingerprint,
                "provider_request_fingerprint": _physical_identity(
                    target.target_identity, slot
                ),
                "prompt_sha256": slot.prompt_sha256,
                "reference_publication_checksum": (
                    slot.plan.reference_publication_checksum
                ),
            }
            for slot in slots
        ],
    }


def _validate_slots(
    target: CorrectionTarget, slots: tuple[CorrectionVisualSlot, ...]
) -> None:
    require(
        len(slots) == MAX_PROVIDER_CALLS
        and [slot.ordinal for slot in slots] == list(range(MAX_PROVIDER_CALLS))
        and len({slot.plan.request_fingerprint for slot in slots}) == MAX_PROVIDER_CALLS
        and len({_physical_identity(target.target_identity, slot) for slot in slots})
        == MAX_PROVIDER_CALLS,
        "badge_regeneration_slots_invalid",
    )
    for slot in slots:
        request = slot.request
        plan = slot.plan
        require(
            plan.run_id == target.run_id
            and plan.article_version_id == target.article.id
            and plan.render_version_id == target.render.id
            and plan.ordinal == slot.ordinal
            and plan.plan_version == target.plan_version
            and plan.prompt_version == target.prompt_version
            and plan.provider == STRICT_VISUAL_POLICY.generation_provider
            and plan.model == STRICT_VISUAL_POLICY.generation_model
            and request.run_id == target.run_id
            and request.draft_version_id == target.article.id
            and request.request_fingerprint == plan.request_fingerprint
            and request.provider_request_fingerprint is None
            and request.output_size == STRICT_VISUAL_POLICY.output_size
            and request.reference_mode == "single_reference"
            and len(request.references) == 1
            and request.references[0].asset_id == plan.reference_asset_ref
            and request.references[0].sha256 == plan.reference_publication_checksum
            and request.references[0].provider_input_sha256
            == plan.reference_input_checksum
            and sha256(request.prompt.encode()).hexdigest() == slot.prompt_sha256,
            "badge_regeneration_slots_invalid",
        )


def _write_or_verify(
    journal: PrivateJournal, name: str, payload: dict[str, Any]
) -> None:
    stored = journal.read(name)
    if stored is None:
        journal.write(name, payload)
    else:
        require(stored == payload, "badge_regeneration_receipt_changed")


def _safe_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key
        in {
            "ordinal",
            "status",
            "error_code",
            "disposition",
            "reason",
            "media_type",
            "byte_size",
            "sha256",
            "width",
            "height",
            "provider_request_fingerprint",
        }
    }


async def _verify_ready_object(
    store: OfficialAccountGeneratedVisualStore,
    result: dict[str, Any],
    *,
    intent_sha256: str,
    ordinal: int,
    provider_request_fingerprint: str,
) -> bytes:
    require(
        set(result)
        == {
            "intent_sha256",
            "ordinal",
            "status",
            "media_type",
            "byte_size",
            "sha256",
            "width",
            "height",
            "provider_request_fingerprint",
        }
        and result.get("intent_sha256") == intent_sha256
        and result.get("ordinal") == ordinal
        and result.get("status") == "ready"
        and result.get("media_type") == "image/jpeg"
        and type(result.get("byte_size")) is int
        and cast(int, result["byte_size"]) > 0
        and isinstance(result.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", cast(str, result["sha256"])) is not None
        and (result.get("width"), result.get("height")) == (1536, 1024)
        and result.get("provider_request_fingerprint") == provider_request_fingerprint,
        "badge_regeneration_result_changed",
    )
    body = await store.get_content_addressed_bytes(
        media_type=cast(str, result["media_type"]),
        byte_size=cast(int, result["byte_size"]),
        sha256=cast(str, result["sha256"]),
    )
    require(
        len(body) == result["byte_size"]
        and sha256(body).hexdigest() == result["sha256"],
        "badge_regeneration_object_changed",
    )
    return body


async def generate_badge_visuals(
    *,
    journal: PrivateJournal,
    target: CorrectionTarget,
    slots: tuple[CorrectionVisualSlot, ...],
    generator: ImageGenerator,
    store: OfficialAccountGeneratedVisualStore,
    target_still_current: Callable[[], Awaitable[bool]],
) -> dict[str, Any]:
    _validate_slots(target, slots)
    manifest = _manifest(target, slots)
    _write_or_verify(journal, MANIFEST_NAME, manifest)
    results: list[dict[str, Any]] = []
    provider_calls = 0
    for slot in slots:
        physical = _physical_identity(target.target_identity, slot)
        intent = {
            "version": POLICY,
            "manifest_sha256": _sha(manifest),
            "ordinal": slot.ordinal,
            "logical_request_fingerprint": slot.plan.request_fingerprint,
            "provider_request_fingerprint": physical,
            "prompt_sha256": slot.prompt_sha256,
            "reference_publication_checksum": slot.plan.reference_publication_checksum,
            "maximum_calls": 1,
        }
        intent_name = _intent_name(slot.ordinal)
        result_name = _result_name(slot.ordinal)
        old_intent = journal.read(intent_name)
        result = journal.read(result_name)
        if old_intent is not None:
            require(old_intent == intent, "badge_regeneration_intent_changed")
            if result is None:
                result = {
                    "intent_sha256": _sha(intent),
                    "ordinal": slot.ordinal,
                    "status": "outcome_unknown",
                    "error_code": "official_account_generated_visual_result_unknown",
                    "disposition": "unknown",
                    "reason": "durable_intent_without_result",
                }
                journal.write(result_name, result)
                results.append(result)
                return {
                    "status": "stopped",
                    "error_code": "badge_regeneration_outcome_unknown",
                    "provider_calls": provider_calls,
                    "results": [_safe_result(item) for item in results],
                }
            require(
                result.get("intent_sha256") == _sha(intent),
                "badge_regeneration_result_changed",
            )
            results.append(result)
            if result.get("status") != "ready":
                return {
                    "status": "stopped",
                    "error_code": "badge_regeneration_batch_incomplete",
                    "provider_calls": provider_calls,
                    "results": [_safe_result(item) for item in results],
                }
            await _verify_ready_object(
                store,
                result,
                intent_sha256=_sha(intent),
                ordinal=slot.ordinal,
                provider_request_fingerprint=physical,
            )
            require(await target_still_current(), "badge_regeneration_target_changed")
            continue
        require(result is None, "badge_regeneration_result_without_intent")
        require(await target_still_current(), "badge_regeneration_target_changed")
        journal.write(intent_name, intent)
        request = replace(slot.request, provider_request_fingerprint=physical)
        provider_calls += 1
        try:
            generated = await generator.generate(request)
            prepared = prepare_generated_visual_result(
                result=generated,
                plan=slot.plan,
                max_bytes=STRICT_VISUAL_POLICY.maximum_image_bytes,
            )
            descriptor = await store.put_immutable(
                prepared.image_bytes, media_type=prepared.result.media_type
            )
            require(
                getattr(descriptor, "media_type", prepared.result.media_type)
                == prepared.result.media_type
                and getattr(descriptor, "byte_size", prepared.result.byte_size)
                == prepared.result.byte_size
                and getattr(descriptor, "sha256", prepared.result.sha256)
                == prepared.result.sha256,
                "badge_regeneration_store_changed",
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
            results.append(result)
            return {
                "status": "stopped",
                "error_code": "badge_regeneration_batch_incomplete",
                "provider_calls": provider_calls,
                "results": [_safe_result(item) for item in results],
            }
        await _verify_ready_object(
            store,
            result,
            intent_sha256=_sha(intent),
            ordinal=slot.ordinal,
            provider_request_fingerprint=physical,
        )
        require(await target_still_current(), "badge_regeneration_target_changed")
        results.append(result)
    require(
        len(results) == MAX_PROVIDER_CALLS
        and all(item.get("status") == "ready" for item in results),
        "badge_regeneration_batch_incomplete",
    )
    selection = {
        "version": POLICY,
        "manifest_sha256": _sha(manifest),
        "target_identity": target.target_identity,
        "result_sha256s": [[item["ordinal"], _sha(item)] for item in results],
        "objects": [
            [
                item["ordinal"],
                item["media_type"],
                item["byte_size"],
                item["sha256"],
                item["width"],
                item["height"],
            ]
            for item in results
        ],
        "requires_visual_inspection": True,
        "generation_only": True,
    }
    _write_or_verify(journal, SELECTION_NAME, selection)
    return {
        "status": "ready_for_visual_inspection",
        "provider_calls": provider_calls,
        "results": [_safe_result(item) for item in results],
        "selection_sha256": _sha(selection),
    }


class PostgresReadOnlyRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def load_target(self) -> CorrectionTarget:
        async with self.sessions() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            edition = await session.get(Edition, EDITION)
            require(
                edition is not None
                and edition.id == EDITION
                and edition.account_fingerprint == ACCOUNT
                and edition.business_date == DAY
                and edition.status == "delivered"
                and edition.error_code is None
                and edition.event_id is not None
                and edition.article_run_id is not None
                and edition.article_fingerprint is not None
                and edition.content_fingerprint is not None
                and edition.receipt_fingerprint is not None
                and edition.lease_token is None
                and edition.lease_expires_at is None,
                "badge_regeneration_target_changed",
            )
            assert edition is not None and edition.article_run_id is not None
            run = await session.get(Run, edition.article_run_id)
            require(
                run is not None
                and run.status == "failed"
                and run.current_stage == "failed"
                and run.error_code == "strict_visual_generation_attempts_exhausted"
                and run.active_article_version_id is not None
                and run.active_render_version_id is not None
                and run.lease_owner is None
                and run.lease_token is None
                and run.lease_expires_at is None,
                "badge_regeneration_target_changed",
            )
            assert run is not None and run.active_article_version_id is not None
            assert run.active_render_version_id is not None
            article_row = await session.get(Article, run.active_article_version_id)
            render_row = await session.get(Render, run.active_render_version_id)
            visual = await session.scalar(
                select(Visual).where(Visual.run_id == run.id, Visual.ordinal == 0)
            )
            require(
                article_row is not None
                and render_row is not None
                and article_row.run_id == run.id
                and render_row.run_id == run.id
                and render_row.article_version_id == article_row.id
                and article_row.audit_snapshot.get("accepted") is True
                and article_row.validation_snapshot.get("passed") is True
                and visual is not None
                and visual.status == "result_unknown"
                and visual.error_code
                == "official_account_generated_visual_result_unknown",
                "badge_regeneration_content_changed",
            )
            assert article_row is not None and render_row is not None
            article = _stored_article(article_row)
            render = _stored_render(render_row)
            selection = article.article.media_selection
            require(
                article.article.content_fingerprint == article_row.content_fingerprint
                and edition.article_fingerprint == article.article.content_fingerprint
                and selection is not None
                and len(selection.assignments) == MAX_PROVIDER_CALLS
                and sorted(item.ordinal for item in selection.assignments)
                == list(range(MAX_PROVIDER_CALLS)),
                "badge_regeneration_content_changed",
            )
            assert selection is not None
            plan_version = run.version_bundle.get("generated_visual_plan_version")
            prompt_version = run.version_bundle.get("generated_visual_prompt_version")
            require(
                isinstance(plan_version, str) and isinstance(prompt_version, str),
                "badge_regeneration_policy_changed",
            )
            target_identity = fingerprint(
                POLICY,
                str(EDITION),
                DAY.isoformat(),
                run.id,
                article.id,
                render.id,
                article.article.content_fingerprint,
                render.render_fingerprint,
                plan_version,
                prompt_version,
                selection.catalog_version,
                tuple(
                    (
                        item.ordinal,
                        item.section_index,
                        item.candidate_ref,
                        item.source_checksum,
                        item.publication_checksum,
                        item.selection_method,
                        item.reason_code,
                        item.similarity_band,
                    )
                    for item in sorted(
                        selection.assignments, key=lambda value: value.ordinal
                    )
                ),
            )
            return CorrectionTarget(
                article=article,
                render=render,
                run_id=run.id,
                target_identity=target_identity,
                plan_version=cast(str, plan_version),
                prompt_version=cast(str, prompt_version),
            )


def plan_summary(
    target: CorrectionTarget, slots: tuple[CorrectionVisualSlot, ...]
) -> dict[str, Any]:
    manifest = _manifest(target, slots)
    return {
        "status": "planned",
        "mode": "read_only",
        "policy": POLICY,
        "business_date": DAY.isoformat(),
        "edition_fingerprint": manifest["edition_fingerprint"],
        "target_identity": target.target_identity,
        "article_fingerprint": target.article.article.content_fingerprint,
        "visual_slots": len(slots),
        "max_provider_calls": MAX_PROVIDER_CALLS,
        "prompt_sha256s": [slot.prompt_sha256 for slot in slots],
        "generation_only": True,
        "provider_calls": 0,
        "database_writes": 0,
    }


async def _main(command: str, apply: bool) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.infrastructure.db.session import create_engine, create_session_factory

    require(command in {"plan", "generate"}, "badge_regeneration_command_invalid")
    require(
        (command == "plan" and not apply) or (command == "generate" and apply),
        "badge_regeneration_explicit_apply_required",
    )
    settings = get_settings()
    engine = create_engine(settings)
    repository = PostgresReadOnlyRepository(create_session_factory(engine))
    journal: PrivateJournal | None = None
    try:
        target = await repository.load_target()
        catalog = LocalOfficialAccountCatalogMediaProvider(
            settings.image_asset_manifest
        )
        slots = await plan_visual_slots(target, catalog)
        if command == "plan":
            return plan_summary(target, slots)
        artifact_root_value = os.environ.get(ARTIFACT_ROOT_ENV)
        require(
            isinstance(artifact_root_value, str) and artifact_root_value,
            "badge_regeneration_journal_root_missing",
        )
        assert isinstance(artifact_root_value, str)
        journal = PrivateJournal(Path(artifact_root_value), ACCOUNT)

        async def target_still_current() -> bool:
            current = await repository.load_target()
            return current.target_identity == target.target_identity

        result = await generate_badge_visuals(
            journal=journal,
            target=target,
            slots=slots,
            generator=LazyStrictOfficialAccountImageGenerator(settings),
            store=MinioImageStore(settings),
            target_still_current=target_still_current,
        )
        return {
            **plan_summary(target, slots),
            **result,
            "mode": "apply",
            "database_writes": 0,
        }
    finally:
        try:
            if journal is not None:
                journal.close()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", default="plan", choices=("plan", "generate")
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
    except Exception as error:  # noqa: BLE001 - secret-free operator boundary
        code = getattr(error, "code", None)
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{1,79}", code) is None
        ):
            code = "badge_regeneration_operator_stopped"
        print(json.dumps({"status": "stopped", "error_code": code}))
        raise SystemExit(1) from None
