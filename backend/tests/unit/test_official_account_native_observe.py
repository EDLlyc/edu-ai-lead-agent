from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from app.application.ports.official_account_strict_visual import (
    ObserveVisualAuditSubject,
    ObserveVisualMediaEvidence,
    StrictVisualMediaEvidence,
    observe_quality_issue_codes,
    strict_audit_record_fingerprint,
)
from app.application.ports.official_account_weekly_production import (
    weekly_article_identity_from_snapshot,
)
from app.application.services.official_account_strict_prepared import (
    OBSERVE_PREPARED_CHILD_VERSION,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.application.services.wechat_official_account_draft import (
    WeChatDraftLocalSource,
    WeChatOfficialAccountDraftPreparer,
)
from app.core.errors import ProviderUnavailableError
from app.domain.image_similarity import perceptual_dhash
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset
from app.domain.official_account_local import ArticlePackage, fingerprint
from app.domain.official_account_visual_pipeline import (
    OBSERVE_VISUAL_PIPELINE_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
    native_visual_audit_releases,
    strict_visual_batch_checks,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.wechat_official_account.prepared_artifacts import _write_directory
from PIL import Image
from pydantic import TypeAdapter
from test_official_account_strict_prepared import captured, strict_projection  # noqa: F401
from test_official_account_strict_visual_policy import _settings
from test_official_account_strict_visual_worker import _components


def _observe_components():
    parts = _components()
    parts[0].identity = replace(
        parts[0].identity, visual_pipeline_version=OBSERVE_VISUAL_PIPELINE_VERSION
    )
    return parts


def test_observe_identity_is_frozen_not_an_execution_toggle():
    settings = _settings().model_copy(
        update={"official_account_local_visual_pipeline_version": OBSERVE_VISUAL_PIPELINE_VERSION}
    )
    identity = official_account_identity_from_settings(settings, provider="zhipu", model="glm-5.2")
    assert identity.visual_pipeline_version == OBSERVE_VISUAL_PIPELINE_VERSION
    assert weekly_article_identity_from_snapshot(asdict(identity)) == identity
    strict = official_account_identity_from_settings(_settings(), provider="zhipu", model="glm-5.2")
    assert identity != strict
    assert replace(identity, visual_pipeline_version=STRICT_VISUAL_PIPELINE_VERSION) == strict


@pytest.mark.parametrize("status", ["accepted", "rejected", "unavailable", "result_unknown"])
def test_release_predicate_never_changes_the_record(status):
    codes = () if status == "accepted" else ("strict_visual_audit_" + status,)
    assert native_visual_audit_releases(OBSERVE_VISUAL_PIPELINE_VERSION, status, codes)
    assert native_visual_audit_releases(STRICT_VISUAL_PIPELINE_VERSION, status, codes) == (
        status == "accepted"
    )
    assert not native_visual_audit_releases(OBSERVE_VISUAL_PIPELINE_VERSION, "calling", ())
    assert not native_visual_audit_releases("unknown-policy", status, codes)
    assert not native_visual_audit_releases(
        OBSERVE_VISUAL_PIPELINE_VERSION, "rejected", ("strict_visual_audit_identity_mismatch",)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["rejected", "unavailable", "result_unknown"])
async def test_observe_continues_six_real_subjects_without_paid_replay(outcome):
    repo, store, generator, auditor, executor = _observe_components()
    original = auditor.audit

    async def audit(request):
        result = await original(request)
        if len(auditor.calls) != 3:
            return result
        if outcome == "unavailable":
            raise ProviderUnavailableError()
        if outcome == "result_unknown":
            raise TimeoutError("synthetic unknown")
        return replace(result, accepted=False)

    auditor.audit = audit
    assert await executor.execute_next("observe")
    assert repo.failure is None and repo.draft is not None
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
    assert [row.status for row in repo.audits.values()] == [
        "accepted",
        "accepted",
        outcome,
        "accepted",
        "accepted",
        "accepted",
    ]
    assert all(isinstance(row.subject, ObserveVisualAuditSubject) for row in repo.audits.values())
    for request in auditor.calls:
        assert sha256(request.image_bytes).hexdigest() in store.images
    with Image.open(BytesIO(auditor.calls[-1].image_bytes)) as cover:
        assert cover.size == (1175, 500)
    assert len(auditor.calls[-1].image_bytes) < 65536
    repo.claimed = False
    await executor.execute_next("observe-read-recovery")
    assert len(generator.calls) == 5 and len(auditor.calls) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["identity", "generation_unknown", "persist", "cancel"])
async def test_observe_integrity_and_ownership_still_block(fault):
    repo, _store, generator, auditor, executor = _observe_components()
    original = auditor.audit

    async def audit(request):
        result = await original(request)
        if fault == "cancel":
            raise asyncio.CancelledError()
        return replace(result, request_fingerprint="f" * 64) if fault == "identity" else result

    async def unknown(request):
        generator.calls.append(request)
        raise TimeoutError("synthetic generation unknown")

    auditor.audit = audit
    if fault == "persist":
        repo.fail_completion = True
    if fault == "generation_unknown":
        generator.generate = unknown
    if fault == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_next("observe-cancel")
    else:
        await executor.execute_next("observe-integrity")
    assert repo.draft is None
    assert len(auditor.calls) <= 1


def _solid(color):
    output = BytesIO()
    Image.new("RGB", (1536, 1024), color).save(output, "JPEG")
    return output.getvalue()


def test_perceptual_warning_is_separate_from_exact_catalog_or_sibling_copy():
    bodies = tuple(_solid((10 + index, 20, 30)) for index in range(5))
    catalog = (_solid((200, 200, 200)),)
    codes = strict_visual_batch_checks(
        bodies, catalog_images=catalog, policy_version=OBSERVE_VISUAL_PIPELINE_VERSION
    )
    assert "strict_visual_perceptual_repetition" in codes
    assert "strict_visual_catalog_reuse" in codes
    copied = strict_visual_batch_checks(
        (catalog[0], *bodies[1:]),
        catalog_images=catalog,
        policy_version=OBSERVE_VISUAL_PIPELINE_VERSION,
    )
    assert "strict_visual_catalog_exact_reuse" in copied
    assert "strict_visual_exact_repetition" in strict_visual_batch_checks(
        (bodies[0],) * 5, catalog_images=catalog
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("observe", [False, True])
@pytest.mark.parametrize("echo_at", [0, 2])
async def test_raw_catalog_echo_cannot_hide_behind_jpeg_normalization(observe, echo_at):
    repo, _store, generator, auditor, executor = _observe_components() if observe else _components()
    original = generator.generate

    async def echo_reference(request):
        result = await original(request)
        if len(generator.calls) == echo_at + 1:
            return replace(result, image_bytes=request.references[0].image_bytes)
        return result

    generator.generate = echo_reference
    assert await executor.execute_next("raw-catalog-echo")
    assert repo.draft is None
    assert not auditor.calls
    if observe:
        assert repo.failure == ("strict_visual_catalog_exact_reuse", False)
        assert len(generator.calls) == echo_at + 1
        assert repo.generated[echo_at].status == "failed"
        assert repo.generated[echo_at].error_code == "strict_visual_catalog_exact_reuse"
        earlier = tuple(repo.generated[index] for index in range(echo_at))
        assert all(item.status == "ready" for item in earlier)
        repo.claimed = False
        await executor.execute_next("raw-catalog-no-paid-replay")
        assert len(generator.calls) == echo_at + 1 and not auditor.calls
        assert tuple(repo.generated[index] for index in range(echo_at)) == earlier
    else:
        assert len(generator.calls) == 5  # Preserve the original strict batch boundary.


@pytest.fixture
def observe_projection(strict_projection):  # noqa: F811
    raw = strict_projection.manifest
    media = tuple(EditorHandoffMediaAsset.model_validate(item) for item in raw["media"])
    old = tuple(
        TypeAdapter(StrictVisualMediaEvidence).validate_python(item)
        for item in raw["visual_evidence"]
    )
    catalog = tuple(sorted({item.reference_publication_sha256 for item in old}))
    evidence = []
    for index, item in enumerate(old):
        asset = next(
            asset for asset in media if (asset.role, asset.ordinal) == (item.role, item.ordinal)
        )
        subject = ObserveVisualAuditSubject(
            run_id=UUID(raw["run_id"]),
            article_version_id=UUID(raw["article_version_id"]),
            render_version_id=UUID(raw["render_version_id"]),
            **{
                key: getattr(item, key)
                for key in (
                    "role",
                    "ordinal",
                    "generated_visual_id",
                    "generated_plan_request_fingerprint",
                    "reference_asset_ref",
                    "reference_publication_sha256",
                    "publication_sha256",
                    "upload_sha256",
                    "upload_policy_version",
                    "media_type",
                    "byte_size",
                    "width",
                    "height",
                )
            },
            criteria_fingerprint="c" * 64,
            perceptual_hash=perceptual_dhash(strict_projection.files[asset.path]),
            catalog_perceptual_hashes=("0" * 16,),
            catalog_publication_sha256s=catalog,
        )
        status = ("accepted", "rejected", "unavailable", "result_unknown", "accepted", "accepted")[
            index
        ]
        codes = () if status == "accepted" else ("strict_visual_audit_" + status,)
        proof = replace(
            item,
            audit_request_fingerprint=subject.request_fingerprint,
            audit_record_fingerprint=strict_audit_record_fingerprint(subject, status, codes),
        )
        evidence.append(
            ObserveVisualMediaEvidence(
                **asdict(proof),
                audit_status=status,
                audit_issue_codes=codes,
                audit_subject=subject,
                quality_issue_codes=(),
            )
        )
    subjects = tuple(item.audit_subject for item in evidence[:5])
    evidence = tuple(
        replace(item, quality_issue_codes=observe_quality_issue_codes(item.audit_subject, subjects))
        for item in evidence
    )
    return build_strict_prepared_projection(
        run_id=UUID(raw["run_id"]),
        article_version_id=UUID(raw["article_version_id"]),
        render_version_id=UUID(raw["render_version_id"]),
        role=raw["role"],
        article=ArticlePackage.model_validate(raw["article"]),
        media=media,
        evidence=evidence,
        files={item.path: strict_projection.files[item.path] for item in media},
        context_originals={
            item["ordinal"]: strict_projection.files[item["source_path"]]
            for item in raw["context_derivatives"]
        },
        visual_pipeline_version=OBSERVE_VISUAL_PIPELINE_VERSION,
    )


def test_observe_prepared_preserves_pixels_body_and_real_audits(
    observe_projection,
    strict_projection,  # noqa: F811
    tmp_path,
):
    assert observe_projection.files == strict_projection.files
    assert observe_projection.manifest["version"] == OBSERVE_PREPARED_CHILD_VERSION
    validate_strict_prepared_projection(observe_projection.manifest, observe_projection.files)
    target = tmp_path / "child"
    _write_directory(
        target,
        files={
            **observe_projection.files,
            "prepared-manifest.json": json.dumps(observe_projection.manifest).encode(),
        },
    )
    prepared = WeChatOfficialAccountDraftPreparer(max_image_bytes=10 * 1024 * 1024).prepare(
        WeChatDraftLocalSource(directory=target, role=observe_projection.manifest["role"])
    )
    assert prepared.visual_pipeline_version == OBSERVE_VISUAL_PIPELINE_VERSION
    cover_path = next(
        item["path"] for item in observe_projection.manifest["media"] if item["role"] == "cover"
    )
    assert prepared.cover.body == observe_projection.files[cover_path]


@pytest.mark.parametrize(
    "field,value",
    [
        ("audit_status", "accepted"),
        ("audit_issue_codes", []),
        ("quality_issue_codes", ["strict_visual_perceptual_repetition"]),
        ("ordinal", True),
        ("audit_record_fingerprint", "f" * 64),
    ],
)
def test_observe_rehashed_evidence_tampering_rejected(observe_projection, field, value):
    manifest = json.loads(json.dumps(observe_projection.manifest))
    manifest["visual_evidence"][1][field] = value
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, observe_projection.files)


def test_observe_cannot_swap_to_strict_envelope(observe_projection):
    manifest = dict(
        observe_projection.manifest,
        version="wechat-draft-prepared-child-v2-native-strict",
        visual_pipeline_version=STRICT_VISUAL_PIPELINE_VERSION,
    )
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, observe_projection.files)


def _reseal_manifest(manifest):
    manifest.pop("child_fingerprint")
    manifest.pop("content_fingerprint")

    def digest(value):
        return sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    manifest["content_fingerprint"] = digest(manifest)
    manifest["child_fingerprint"] = digest(manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("width", True),
        ("ordinal", 1.0),
        ("extra", "not-registered"),
        ("run_id", str(UUID(int=987654))),
        ("model", "different-model"),
    ],
)
def test_observe_resealed_nested_subject_tampering_fails(observe_projection, field, value):
    manifest = json.loads(json.dumps(observe_projection.manifest))
    proof = manifest["visual_evidence"][1]
    proof["audit_subject"][field] = value
    proof["audit_request_fingerprint"] = fingerprint(
        "official-account-strict-visual-audit-request-v1", proof["audit_subject"]
    )
    proof["audit_record_fingerprint"] = fingerprint(
        "official-account-strict-visual-audit-record-v1",
        proof["audit_request_fingerprint"],
        proof["audit_status"],
        tuple(proof["audit_issue_codes"]),
    )
    _reseal_manifest(manifest)
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, observe_projection.files)


@pytest.mark.parametrize(
    "code",
    ["strict_visual_任意正文", "strict_visual_private\ncontent", "strict_visual_not_registered"],
)
def test_observe_resealed_arbitrary_issue_code_is_not_a_safe_observation(observe_projection, code):
    manifest = json.loads(json.dumps(observe_projection.manifest))
    proof = manifest["visual_evidence"][1]
    proof["audit_issue_codes"] = [code]
    proof["audit_record_fingerprint"] = fingerprint(
        "official-account-strict-visual-audit-record-v1",
        proof["audit_request_fingerprint"],
        proof["audit_status"],
        (code,),
    )
    _reseal_manifest(manifest)
    with pytest.raises(ValueError, match="observe prepared audit identity"):
        validate_strict_prepared_projection(manifest, observe_projection.files)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frozen_policy,current_policy",
    [
        (STRICT_VISUAL_PIPELINE_VERSION, OBSERVE_VISUAL_PIPELINE_VERSION),
        (OBSERVE_VISUAL_PIPELINE_VERSION, STRICT_VISUAL_PIPELINE_VERSION),
    ],
)
async def test_frozen_policy_dispatch_survives_opposite_future_settings(
    frozen_policy, current_policy
):
    repo, _store, generator, auditor, executor = _components()
    repo.identity = replace(repo.identity, visual_pipeline_version=frozen_policy)
    # Current composition selects future identity only, not the queued claim's identity.
    current = _settings().model_copy(
        update={"official_account_local_visual_pipeline_version": current_policy}
    )
    assert (
        official_account_identity_from_settings(
            current, provider="zhipu", model="glm-5.2"
        ).visual_pipeline_version
        == current_policy
    )
    original = auditor.audit

    async def reject(request):
        return replace(await original(request), accepted=False)

    auditor.audit = reject
    await executor.execute_next("frozen-native")
    assert repo.identity.visual_pipeline_version == frozen_policy
    assert len(generator.calls) == 5
    assert (repo.draft is not None) == (frozen_policy == OBSERVE_VISUAL_PIPELINE_VERSION)
    assert len(auditor.calls) == (6 if frozen_policy == OBSERVE_VISUAL_PIPELINE_VERSION else 1)
