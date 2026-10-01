"""Explicit paid replacement visuals for one already-created draft; no DB mutation.

Default plan has no model/WeChat calls. --generate (alias --generate-only) may
generate and audit only, with immutable independent per-operation receipts.
--update is a separate permission boundary and never creates another draft.
Run with the original manual operator beside this file and the original journal.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
import re
import warnings
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import httpx
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageReference,
)
from app.application.ports.image_validation import ImageQualityAuditRequest
from app.application.ports.official_account_strict_visual import (
    STRICT_AUDIT_PROMPT_VERSION,
)
from app.application.services.official_account_strict_visual import (
    validate_xiaosai_references,
)
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    plan_generated_body_visual,
    preflight_strict_generated_visuals,
    prepare_generated_visual_result,
    select_generated_visual_block_anchor,
)
from app.core.config import get_settings
from app.core.errors import ImageOutputValidationError, ProviderIdentityMismatchError
from app.domain.image_provider_input import (
    IMAGE_REFERENCE_INPUT_V2,
    normalize_image_provider_reference,
)
from app.domain.official_account_local import fingerprint
from app.domain.official_account_upload_media import (
    normalize_official_account_upload_body,
    normalize_official_account_upload_cover,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
    STRICT_VISUAL_POLICY,
    strict_visual_audit_criteria,
    strict_visual_audit_passes,
    strict_visual_batch_checks,
)
from app.infrastructure.ai.image_generation import (
    OpenAICompatibleImageGenerator,
    _detect_image_media_type,
)
from app.infrastructure.ai.official_account_visual_strict import (
    LazyStrictOfficialAccountImageQualityAuditor,
    StrictVisualOneShotTransport,
)
from app.infrastructure.db.official_account_local import (
    PostgresOfficialAccountRepository,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)
from app.infrastructure.wechat_official_account.manual_journal import (
    fingerprint as journal_fingerprint,
)
from PIL import Image, ImageOps

MANUAL_SHA = "301a9580de4d489762faa880ff4b6ccd819f448f1f3cebe64adbb587e85643fc"
ARTICLE_FP = "9104e8fed92d1e852a74d45a158d2ce14fb28ae7daa835dfed556f8f184a37ea"
OLD_CONTENT_FP = "6c84df64147d2b6d0fa1dfb2813c2592b27a5d412d6509d14c03b47b9a49d84d"
OLD_RECEIPT_FP = "2446ef5e01bdcc59b5624dcfbe9a554d83944bdf71824f105b6b571b405e9882"
PREFIX = "generated-update-41b26b7fe79256ffbdfa643171114056"
AUTH = PREFIX + "-authorization.json"
AUTHORIZATION_VERSION = "sep16-generated-draft-update-explicit-v1"
ORIGINAL_GENERATION_SHA = (
    "98b643344235742f05361e1fdf6659d1d26f4ebe20ea77ecd440976ca2ae3c64"
)
ORIGINAL_TERMINAL_INTENT = (
    "fc6a1e15fec14f375e99056f22320e4abcbc2b0e5c5a8f3cf186060c7c8ef57f"
)
NORMALIZATION_VERSION = "sep16-explicit-raster-fit-v1"


class NormalizedComflyGenerator(OpenAICompatibleImageGenerator):
    """Keep the existing network/security boundary; normalize only decoded raster."""

    def _normalize_image_bytes(
        self,
        body,
        *,
        expected_dimensions,
        output_geometry_policy=None,
        declared_media_type=None,
    ):
        # The base generator now passes its output-geometry policy. This recovery operator always
        # normalizes to exactly 1536x1024 JPEG, so the policy does not change its result.
        del output_geometry_policy
        if not body or len(body) > self._max_download_bytes:
            raise ImageOutputValidationError("image_download_too_large")
        media_type = _detect_image_media_type(body)
        if (
            declared_media_type in {"image/png", "image/jpeg", "image/webp"}
            and declared_media_type != media_type
        ):
            raise ImageOutputValidationError("image_raster_signature_invalid")
        if expected_dimensions != (1536, 1024):
            raise ImageOutputValidationError("image_dimensions_invalid")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(
                    BytesIO(body), formats=["PNG", "JPEG", "WEBP"]
                ) as source:
                    width, height = source.size
                    if (
                        min(width, height) < 128
                        or max(width, height) > 8192
                        or width * height > 16_000_000
                        or getattr(source, "n_frames", 1) != 1
                    ):
                        raise ImageOutputValidationError("image_dimensions_invalid")
                    source.verify()
                with Image.open(
                    BytesIO(body), formats=["PNG", "JPEG", "WEBP"]
                ) as source:
                    source.load()
                    transposed = ImageOps.exif_transpose(source)
                    rgba = transposed.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    background.alpha_composite(rgba)
                    output = ImageOps.fit(
                        background.convert("RGB"),
                        expected_dimensions,
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    )
                    target = BytesIO()
                    output.save(
                        target,
                        format="JPEG",
                        quality=90,
                        subsampling=0,
                        optimize=False,
                        progressive=False,
                    )
        except (
            OSError,
            ValueError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise ImageOutputValidationError("image_raster_signature_invalid") from None
        normalized = target.getvalue()
        if len(normalized) > self._max_download_bytes:
            raise ImageOutputValidationError("image_download_too_large")
        self.last_normalization = {
            "version": NORMALIZATION_VERSION,
            "source_sha256": sha256(body).hexdigest(),
            "source_media_type": media_type,
            "source_width": width,
            "source_height": height,
            "output_sha256": sha256(normalized).hexdigest(),
            "output_width": 1536,
            "output_height": 1024,
        }
        return normalized, "image/jpeg", 1536, 1024


class BoundedNormalizedGenerator:
    def __init__(self, settings, *, transport_factory=None):
        self.settings = settings
        self.transport_factory = transport_factory or (
            lambda: httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        )
        self.last_normalization = None

    async def generate(self, request):
        settings = self.settings
        require(
            settings.image_provider_mode == STRICT_VISUAL_POLICY.generation_provider
            and settings.image_model == STRICT_VISUAL_POLICY.generation_model
            and settings.comfly_api_key is not None
            and settings.comfly_api_key.get_secret_value().strip(),
            "generated_update_model_policy_invalid",
        )
        require(request.output_size == "1536x1024" and request.references)
        transport = StrictVisualOneShotTransport(
            inner=self.transport_factory(),
            kind="generation",
            base_url=settings.comfly_base_url,
        )
        async with httpx.AsyncClient(
            transport=transport, follow_redirects=False, trust_env=False
        ) as client:
            adapter = NormalizedComflyGenerator(
                client=client,
                base_url=settings.comfly_base_url,
                api_key=settings.comfly_api_key,
                model=settings.image_model,
                max_attempts=1,
                initial_poll_seconds=settings.image_poll_initial_seconds,
                poll_interval_seconds=settings.image_poll_interval_seconds,
                provider_window_seconds=min(
                    settings.image_provider_window_seconds, 360
                ),
                timeout_seconds=min(settings.image_provider_timeout_seconds, 300),
                max_download_bytes=min(
                    settings.image_max_download_bytes,
                    STRICT_VISUAL_POLICY.maximum_image_bytes,
                ),
                max_request_bytes=settings.image_max_request_bytes,
                max_provider_response_bytes=settings.image_max_provider_response_bytes,
                max_reference_images=settings.image_max_reference_images,
            )
            result = await adapter.generate(request)
            self.last_normalization = adapter.last_normalization
        if (
            result.provider != STRICT_VISUAL_POLICY.generation_provider
            or result.model != STRICT_VISUAL_POLICY.generation_model
            or result.request_fingerprint != request.request_fingerprint
            or result.attempts != 1
        ):
            raise ProviderIdentityMismatchError()
        return result


def require(condition, code="generated_update_binding_invalid"):
    if not condition:
        raise ValueError(code)


def load_manual():
    path = Path(__file__).with_name("manual-draft-now.py")
    require(
        sha256(path.read_bytes()).hexdigest() == MANUAL_SHA,
        "generated_update_manual_code_changed",
    )
    spec = importlib.util.spec_from_file_location("verified_manual_draft", path)
    if spec is None or spec.loader is None:
        raise ValueError("generated_update_manual_import_invalid")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def original_receipt(journal, manual):
    prefix = f"single-{manual.EDITION.hex}"
    auth = journal.read(manual.AUTH_NAME)
    intent = journal.read(prefix + "-add-1-intent.json")
    ack = journal.read(prefix + "-add-1-ack.json")
    claim = journal.read(ARTICLE_FP + "-claim.json")
    require(
        all(item is not None for item in (auth, intent, ack, claim)),
        "generated_update_add_receipt_missing",
    )
    expected_binding = journal_fingerprint(
        {
            "edition": str(manual.EDITION),
            "article": ARTICLE_FP,
            "content": OLD_CONTENT_FP,
            "account": manual.ACCOUNT,
            "policy": "single-write-journal-v1",
            "max_attempts": 1,
        }
    )
    require(
        auth["binding"]["article_fingerprint"] == ARTICLE_FP
        and auth["binding"]["content_fingerprint"] == OLD_CONTENT_FP
        and auth["binding"]["edition_id"] == str(manual.EDITION)
        and auth["binding"]["account"] == manual.ACCOUNT
        and auth["binding"]["run_id"] == str(manual.RUN)
        and auth["binding"]["article_id"] == str(manual.ARTICLE)
        and auth["binding"]["generated"] is False
        and auth["binding"]["max_attempts"] == 1
        and intent["step"] == "add"
        and intent["binding"] == expected_binding
        and intent["attempt"] == 1
        and ack["intent_sha256"] == journal_fingerprint(intent)
        and claim["account"] == manual.ACCOUNT
        and claim["binding"]["version"] == "single-edition-claim-v1"
        and claim["binding"]["edition_id"] == str(manual.EDITION)
        and claim["binding"]["raw_article"] == ARTICLE_FP
        and claim["binding"]["fingerprint"] == intent["binding"]
        and journal.read(prefix + "-add-1-not-applied.json") is None,
        "generated_update_original_journal_binding_changed",
    )
    media_id = ack["value"]
    require(
        isinstance(media_id, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", media_id) is not None,
        "generated_update_media_id_invalid",
    )
    require(
        sha256(media_id.encode()).hexdigest() == OLD_RECEIPT_FP,
        "generated_update_receipt_fingerprint_changed",
    )
    return media_id, intent["request"], fingerprint(auth, intent, ack, claim)


async def prepare_inputs(manual, sessions, catalog):
    edition, package, source_identity = await manual.load_target(sessions)
    require(
        package.content_fingerprint == ARTICLE_FP,
        "generated_update_article_fingerprint_changed",
    )
    base = await manual.prepare(package, catalog)
    require(
        base.content_fingerprint == OLD_CONTENT_FP,
        "generated_update_original_content_changed",
    )
    repository = PostgresOfficialAccountRepository(sessions)
    article, render = (
        await repository.get_article(manual.RUN),
        await repository.get_render(manual.RUN),
    )
    require(
        article is not None and article.id == manual.ARTICLE and render is not None,
        "generated_update_stored_article_missing",
    )
    assert article is not None and render is not None
    candidates = await catalog.load_candidates()
    mapping = {item.catalog_asset_ref: item for item in candidates}
    reference_items, content_items = [], []
    for assigned in package.media_selection.assignments:
        reference = replace(
            mapping[assigned.candidate_ref],
            ordinal=assigned.ordinal,
            assigned_section_index=assigned.section_index,
            selection_method=assigned.selection_method,
            similarity_band=assigned.similarity_band,
        )
        require(
            reference.catalog_version == package.media_selection.catalog_version
            and reference.source_master_sha256 == assigned.source_checksum
            and reference.sha256 == assigned.publication_checksum,
            "generated_update_reference_changed",
        )
        content_items.append(
            await catalog.read_publication_bytes(
                catalog_asset_ref=assigned.candidate_ref,
                catalog_version=reference.catalog_version,
                source_master_sha256=assigned.source_checksum,
                publication_sha256=assigned.publication_checksum,
            )
        )
        reference_items.append(reference)
    references, contents = tuple(reference_items), tuple(content_items)
    await validate_xiaosai_references(catalog, references)
    preflight_strict_generated_visuals(
        article=article, references=references, reference_bytes=contents
    )
    plans = tuple(
        plan_generated_body_visual(
            run_id=manual.RUN,
            article=article,
            render=render,
            ordinal=i,
            reference=ref,
            reference_bytes=body,
            provider=STRICT_VISUAL_POLICY.generation_provider,
            model=STRICT_VISUAL_POLICY.generation_model,
            plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
            prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
        )
        for i, (ref, body) in enumerate(zip(references, contents, strict=True))
    )
    return edition, article, base, source_identity, references, contents, plans


def authorization(journal, manual, source_identity, receipt_identity, plans, now):
    binding = {
        "version": AUTHORIZATION_VERSION,
        "edition_id": str(manual.EDITION),
        "run_id": str(manual.RUN),
        "article_id": str(manual.ARTICLE),
        "article_fingerprint": ARTICLE_FP,
        "original_content_fingerprint": OLD_CONTENT_FP,
        "original_receipt_fingerprint": OLD_RECEIPT_FP,
        "original_journal_fingerprint": receipt_identity,
        "source_identity": source_identity,
        "generation_provider": STRICT_VISUAL_POLICY.generation_provider,
        "generation_model": STRICT_VISUAL_POLICY.generation_model,
        "audit_model": STRICT_VISUAL_POLICY.audit_model,
        "plans": [plan.request_fingerprint for plan in plans],
        "images": 5,
        "audits": 6,
        "draft_add_allowed": False,
        "update_index": 0,
    }
    previous = journal.read(AUTH)
    if previous is not None:
        require(
            set(previous) == {"binding", "authorized_at", "expires_at"}
            and previous["binding"] == binding,
            "generated_update_authorization_changed",
        )
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
            == manual.DAY,
            "generated_update_deadline_invalid",
        )
        return previous
    require(
        now.astimezone(manual.ZONE).date() == manual.DAY, "generated_update_wrong_day"
    )
    end = min(
        now + timedelta(hours=2), datetime.combine(manual.DAY, time.max, manual.ZONE)
    )
    return {
        "binding": binding,
        "authorized_at": now.isoformat(),
        "expires_at": end.isoformat(),
    }


def image_bytes(record):
    require(isinstance(record.get("body_b64"), str))
    body = base64.b64decode(record["body_b64"], validate=True)
    require(len(body) <= 1024 * 1024 and sha256(body).hexdigest() == record["sha256"])
    return body


def terminal_recovery_binding(journal, auth, ordinal, *, observed_intent=None):
    require(
        type(ordinal) is int and ordinal == 0,
        "generated_update_recovery_ordinal_not_authorized",
    )
    name = f"{PREFIX}-image-{ordinal}"
    intent = journal.read(name + "-intent.json")
    require(
        intent is not None and journal.read(name + "-result.json") is None,
        "generated_update_recovery_target_not_incomplete",
    )
    require(
        intent["authorization_fingerprint"] == fingerprint(auth)
        and intent["ordinal"] == ordinal
        and fingerprint(intent) == ORIGINAL_TERMINAL_INTENT,
        "generated_update_recovery_target_changed",
    )
    terminal = journal.read(name + "-terminal-invalid.json")
    if terminal is None:
        require(
            ordinal == 0
            and observed_intent == fingerprint(intent) == ORIGINAL_TERMINAL_INTENT,
            "generated_update_terminal_evidence_required",
        )
        # This is the exact old script's observed exit, not an inferred format cause
        # and not evidence that the provider never accepted the original request.
        evidence = {
            "source": "operator_observed_exit",
            "script_sha256": ORIGINAL_GENERATION_SHA,
            "intent_fingerprint": observed_intent,
            "error_code": "image_output_invalid",
        }
    else:
        require(
            terminal.get("intent_fingerprint") == fingerprint(intent)
            and terminal.get("error_code") == "image_output_invalid",
            "generated_update_terminal_evidence_changed",
        )
        evidence = terminal
    return {
        "version": "sep16-terminal-invalid-attempt2-v1",
        "ordinal": ordinal,
        "authorization_fingerprint": fingerprint(auth),
        "old_intent_fingerprint": fingerprint(intent),
        "terminal_evidence": evidence,
        "maximum_attempt": 2,
        "normalization_version": NORMALIZATION_VERSION,
        "draft_fingerprint": OLD_RECEIPT_FP,
    }


def authorize_terminal_recovery(
    journal, auth, ordinal, *, now, observed_intent=None, persist=False
):
    binding = terminal_recovery_binding(
        journal, auth, ordinal, observed_intent=observed_intent
    )
    name = f"{PREFIX}-image-{ordinal}-attempt2-authorization.json"
    previous = journal.read(name)
    if previous is not None:
        require(
            set(previous) == {"binding", "authorized_at", "expires_at"}
            and previous["binding"] == binding
            and previous["expires_at"] == auth["expires_at"],
            "generated_update_recovery_authorization_changed",
        )
        return previous
    require(
        now < datetime.fromisoformat(auth["expires_at"]),
        "generated_update_authority_expired",
    )
    record = {
        "binding": binding,
        "authorized_at": now.isoformat(),
        "expires_at": auth["expires_at"],
    }
    if persist:
        journal.write(name, record)
    return record


def select_generation_attempt(journal, auth, ordinal, intent):
    name = f"{PREFIX}-image-{ordinal}"
    recovery = journal.read(name + "-attempt2-authorization.json")
    if recovery is None:
        return name, intent
    old = journal.read(name + "-intent.json")
    require(
        old == intent and journal.read(name + "-result.json") is None,
        "generated_update_recovery_original_changed",
    )
    observed = recovery["binding"]["terminal_evidence"].get("intent_fingerprint")
    require(
        recovery["binding"]
        == terminal_recovery_binding(journal, auth, ordinal, observed_intent=observed)
        and recovery["expires_at"] == auth["expires_at"],
        "generated_update_recovery_authorization_changed",
    )
    successor = {
        **intent,
        "provider_request_fingerprint": fingerprint(
            "explicit-terminal-invalid-attempt2",
            fingerprint(recovery),
            fingerprint(intent),
        ),
        "recovery_authorization_fingerprint": fingerprint(recovery),
        "prior_intent_fingerprint": fingerprint(intent),
        "attempt": 2,
        "normalization_version": NORMALIZATION_VERSION,
    }
    require(
        successor["provider_request_fingerprint"]
        != intent["provider_request_fingerprint"]
    )
    return name + "-attempt2", successor


async def generated_once(journal, name, intent, invoke, allowed):
    try:
        return await once(journal, name, intent, invoke, allowed)
    except ImageOutputValidationError:
        # Only this exact terminal output exception may support a later explicit
        # paid replacement. Timeouts, crashes and transport errors never get it.
        marker = {
            "error_code": "image_output_invalid",
            "intent_fingerprint": fingerprint(intent),
            "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "cause_detail_known": False,
        }
        require(journal.read(name + "-intent.json") == intent)
        if journal.read(name + "-terminal-invalid.json") is None:
            journal.write(name + "-terminal-invalid.json", marker)
        raise


async def once(journal, name, intent, invoke, allowed):
    old, result = (
        journal.read(name + "-intent.json"),
        journal.read(name + "-result.json"),
    )
    if old is not None:
        require(old == intent)
        require(result is not None, "generated_update_prior_outcome_unknown")
        require(result.get("intent_fingerprint") == fingerprint(intent))
        return result
    require(result is None)
    require(await allowed(), "generated_update_authority_expired")
    journal.write(name + "-intent.json", intent)
    value = await invoke()
    record = {**value, "intent_fingerprint": fingerprint(intent)}
    require(
        len(json.dumps(record).encode()) < 4 * 1024 * 1024,
        "generated_update_receipt_too_large",
    )
    journal.write(name + "-result.json", record)
    return record


async def audit_image(
    journal, auth, ordinal, body, reference, criteria, auditor, allowed, *, cover=False
):
    normalized = normalize_image_provider_reference(
        reference, version=IMAGE_REFERENCE_INPUT_V2
    )
    name = PREFIX + ("-audit-cover" if cover else f"-audit-{ordinal}")
    request_fp = fingerprint(
        AUTHORIZATION_VERSION,
        fingerprint(auth),
        name,
        sha256(body).hexdigest(),
        normalized.sha256,
        criteria,
    )
    intent = {
        "request_fingerprint": request_fp,
        "sha256": sha256(body).hexdigest(),
        "reference_sha256": normalized.sha256,
        "criteria_fingerprint": fingerprint(criteria),
        "authorization_fingerprint": fingerprint(auth),
    }

    async def invoke():
        result = await auditor.audit(
            ImageQualityAuditRequest(
                image_bytes=body,
                media_type="image/jpeg",
                request_fingerprint=request_fp,
                prompt_version=STRICT_AUDIT_PROMPT_VERSION,
                rubric_version=STRICT_VISUAL_POLICY.audit_rubric_version,
                criteria=criteria,
                references=(
                    ImageReference(
                        role="approved_ip_reference",
                        asset_id="xiaosai",
                        filename="reference.png",
                        sha256=normalized.sha256,
                        image_bytes=normalized.image_png,
                    ),
                ),
            )
        )
        passed = strict_visual_audit_passes(
            accepted=result.accepted,
            issues_present=bool(result.issues),
            provider=result.provider,
            model=result.model,
            request_fingerprint=result.request_fingerprint,
            expected_request_fingerprint=request_fp,
        )
        return {
            "passed": passed,
            "provider": result.provider,
            "model": result.model,
            "request_fingerprint": result.request_fingerprint,
            "issue_codes": list(result.issue_codes),
        }

    result = await once(journal, name, intent, invoke, allowed)
    require(
        result["passed"] is True
        and result["issue_codes"] == []
        and result["provider"] == "openai-compatible"
        and result["model"] == STRICT_VISUAL_POLICY.audit_model
        and result["request_fingerprint"] == request_fp,
        "generated_update_image_audit_failed",
    )
    return fingerprint(result)


async def generate(
    journal, auth, article, references, contents, plans, generator, auditor, allowed
):
    require(
        len(references)
        == len(contents)
        == len(plans)
        == STRICT_VISUAL_POLICY.scene_count
    )
    ready, audit_fingerprints = [], []
    for i, (reference, source, plan) in enumerate(
        zip(references, contents, plans, strict=True)
    ):
        physical = fingerprint(
            AUTHORIZATION_VERSION,
            fingerprint(auth),
            "generation",
            i,
            plan.request_fingerprint,
        )
        prompt = build_generated_visual_prompt(
            article=article,
            section_index=plan.section_index,
            reference=reference,
            prompt_version=plan.prompt_version,
            block_index=plan.block_index,
        )
        intent = {
            "authorization_fingerprint": fingerprint(auth),
            "ordinal": i,
            "logical_request_fingerprint": plan.request_fingerprint,
            "provider_request_fingerprint": physical,
            "prompt_fingerprint": sha256(prompt.encode()).hexdigest(),
            "reference_sha256": reference.sha256,
            "model": plan.model,
        }
        # Ordinal zero retains its immutable original intent for exact failure
        # recovery. New, not-yet-dispatched slots bind the changed raster policy.
        if i != 0:
            intent["normalization_version"] = NORMALIZATION_VERSION
            intent["provider_request_fingerprint"] = fingerprint(
                physical, NORMALIZATION_VERSION
            )
        operation_name, intent = select_generation_attempt(journal, auth, i, intent)
        physical = intent["provider_request_fingerprint"]

        async def invoke(
            plan=plan,
            prompt=prompt,
            reference=reference,
            source=source,
            physical=physical,
        ):
            result = await generator.generate(
                ImageGenerationRequest(
                    run_id=plan.run_id,
                    draft_version_id=article.id,
                    prompt=prompt,
                    request_fingerprint=plan.request_fingerprint,
                    provider_request_fingerprint=physical,
                    output_size=STRICT_VISUAL_POLICY.output_size,
                    references=(
                        ImageReference(
                            role="approved_ip_reference",
                            asset_id=plan.reference_asset_ref,
                            filename="reference.jpg",
                            sha256=reference.sha256,
                            image_bytes=source,
                            input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
                            provider_input_sha256=plan.reference_input_checksum,
                        ),
                    ),
                    reference_mode="single_reference",
                )
            )
            publication = prepare_generated_visual_result(
                result=result,
                plan=plan,
                max_bytes=STRICT_VISUAL_POLICY.maximum_image_bytes,
            )
            final = normalize_official_account_upload_body(publication.image_bytes)
            return {
                "body_b64": base64.b64encode(final.content).decode(),
                "sha256": final.sha256,
                "raw_sha256": sha256(result.image_bytes).hexdigest(),
                "width": final.width,
                "height": final.height,
                "model": result.model,
                "provider": result.provider,
                "logical_request_fingerprint": result.request_fingerprint,
                "normalization": getattr(generator, "last_normalization", None),
            }

        saved = await generated_once(journal, operation_name, intent, invoke, allowed)
        content = image_bytes(saved)
        require(
            saved["logical_request_fingerprint"] == plan.request_fingerprint
            and saved["provider"] == plan.provider
            and saved["model"] == plan.model
        )
        ready.append(content)
        anchor = select_generated_visual_block_anchor(
            article=article, section_index=plan.section_index
        )
        criteria = strict_visual_audit_criteria(
            article=article.article,
            section_index=plan.section_index,
            block_context=anchor.scene_text,
            cover=False,
        )
        audit_fingerprints.append(
            await audit_image(
                journal, auth, i, content, source, criteria, auditor, allowed
            )
        )
        print(
            json.dumps(
                {"stage": "image_ready", "ordinal": i, "sha256": saved["sha256"]}
            ),
            flush=True,
        )
    require(
        not strict_visual_batch_checks(tuple(ready), catalog_images=contents),
        "generated_update_batch_rejected",
    )
    cover = normalize_official_account_upload_cover(ready[0])
    anchor = select_generated_visual_block_anchor(
        article=article, section_index=plans[0].section_index
    )
    criteria = strict_visual_audit_criteria(
        article=article.article,
        section_index=plans[0].section_index,
        block_context=anchor.scene_text,
        cover=True,
    )
    audit_fingerprints.append(
        await audit_image(
            journal,
            auth,
            0,
            cover.content,
            contents[0],
            criteria,
            auditor,
            allowed,
            cover=True,
        )
    )
    return tuple(ready), cover.content, tuple(audit_fingerprints)


async def main(mode, *, recover_ordinal=None, observed_intent=None):
    manual, settings = load_manual(), get_settings()
    require(
        settings.image_provider_mode == "comfly"
        and settings.image_model == "gpt-image-2.5-sunburst",
        "generated_update_model_policy_invalid",
    )
    # Run in the generation worker, which deliberately has no WeChat credentials.
    # SQL + the original account journal/claim/add ACK bind this fixed account.
    # The separate update operator must validate its configured AppID before writes.
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    journal = None
    try:
        (
            _edition,
            article,
            base,
            source_identity,
            references,
            contents,
            plans,
        ) = await prepare_inputs(
            manual,
            sessions,
            LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest),
        )
        directory = (
            Path(settings.wechat_mp_draft_artifact_root) / "manual-v1" / manual.ACCOUNT
        )
        require(
            directory.is_dir() and not directory.is_symlink(),
            "generated_update_journal_mount_invalid",
        )
        journal = LocalManualDraftJournal(
            Path(settings.wechat_mp_draft_artifact_root), manual.ACCOUNT
        )
        _media_id, old_request, original_identity = original_receipt(journal, manual)
        require(
            (old_request["title"], old_request["author"], old_request["digest"])
            == (base.title, base.author, base.digest),
            "generated_update_article_metadata_changed",
        )
        auth = authorization(
            journal,
            manual,
            source_identity,
            original_identity,
            plans,
            datetime.now(UTC),
        )
        if recover_ordinal is not None:
            require(
                journal.read(AUTH) is not None,
                "generated_update_original_authority_missing",
            )
            authorize_terminal_recovery(
                journal,
                auth,
                recover_ordinal,
                now=datetime.now(UTC),
                observed_intent=observed_intent,
                persist=mode == "generate",
            )
        else:
            require(
                observed_intent is None, "generated_update_unscoped_terminal_evidence"
            )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "article_fingerprint": ARTICLE_FP,
                    "target_draft_fingerprint": OLD_RECEIPT_FP,
                    "images": 5,
                    "audits": 6,
                    "model": settings.image_model,
                    "not_published": True,
                }
            ),
            flush=True,
        )
        if mode == "plan":
            return
        require(mode == "generate", "generated_update_phase_not_released")
        if journal.read(AUTH) is None:
            journal.write(AUTH, auth)

        async def allowed():
            _, _, current = await manual.load_target(sessions)
            _, _, receipt_identity = original_receipt(journal, manual)
            return (
                current == source_identity
                and receipt_identity == original_identity
                and datetime.now(UTC) < datetime.fromisoformat(auth["expires_at"])
            )

        bodies, cover, audits = await generate(
            journal,
            auth,
            article,
            references,
            contents,
            plans,
            BoundedNormalizedGenerator(settings),
            LazyStrictOfficialAccountImageQualityAuditor(settings),
            allowed,
        )
        print(
            json.dumps(
                {
                    "stage": "generated_ready",
                    "images": len(bodies),
                    "audits": len(audits),
                    "cover_sha256": sha256(cover).hexdigest(),
                    "wechat_writes": 0,
                }
            ),
            flush=True,
        )
    finally:
        try:
            if journal is not None:
                journal.close()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--generate", "--generate-only", action="store_true")
    group.add_argument("--update", action="store_true")
    parser.add_argument("--recover-terminal-invalid", type=int, choices=[0])
    parser.add_argument("--observed-intent-fingerprint")
    args = parser.parse_args()
    try:
        asyncio.run(
            main(
                "generate" if args.generate else "update" if args.update else "plan",
                recover_ordinal=args.recover_terminal_invalid,
                observed_intent=args.observed_intent_fingerprint,
            )
        )
    except Exception as error:  # noqa: BLE001 -- never expose private provider/config details
        code = (
            str(error)
            if isinstance(error, ValueError)
            and str(error).startswith("generated_update_")
            else getattr(error, "code", "generated_update_stopped")
        )
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{1,79}", code) is None
        ):
            code = "generated_update_stopped"
        print(json.dumps({"stage": "stopped", "error_code": code}), flush=True)
        raise SystemExit(1) from None
