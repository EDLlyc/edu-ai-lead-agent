"""One frozen article, fresh local visuals, and an exclusive filesystem call ledger.

This preview has no database, queue, delivery, or release capability. Its captured input is
private; exported article/source files preserve the captured bytes. All other evidence is a
bounded projection without prompts, provider prose, private catalog IDs, or provider task IDs.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerator,
    ImageReference,
)
from app.application.ports.image_validation import (
    ImageQualityAuditor,
    ImageQualityAuditRequest,
    ImageQualityAuditResult,
)
from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountSourceMedia,
    StoredOfficialAccountArticle,
    StoredOfficialAccountRender,
)
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    generated_visual_alt_text,
    plan_generated_body_visual,
    prepare_generated_visual_result,
    select_generated_visual_block_anchor,
)
from app.domain.image_provider_input import (
    IMAGE_REFERENCE_INPUT_V2,
    normalize_image_provider_reference,
)
from app.domain.image_similarity import (
    DEFAULT_IMAGE_SIMILARITY_THRESHOLD,
    perceptual_dhash,
    perceptual_hash_distance,
)
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset, media_asset_path
from app.domain.official_account_editor_handoff_v2 import render_editor_handoff_v2_body
from app.domain.official_account_local import (
    ArticlePackage,
    ArticleValidationIssue,
    OfficialAccountAuditVerdict,
    OfficialAccountSourceSnapshot,
    article_package_fingerprint,
    fingerprint,
    validate_article_package,
)

PREVIEW_VERSION = "official-account-visual-preview-v1"
INPUT_VERSION = "official-account-visual-preview-input-v1"
PREVIEW_RUBRIC = "official-account-visual-preview-quality-v1"
SOURCE_RUN_ID = UUID("1c8a0cc8-b960-4b33-82ff-e7204def40f6")
GENERATION_MODEL = "gpt-image-2"
AUDIT_MODEL = "glm-5v-turbo"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 80 * 1024 * 1024
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
_MEMBER = re.compile(
    r"(?:article\.json|source\.json|snapshot\.json|"
    r"(?:catalog/[0-4]|context/0|references/(?:[0-9]|1[01]))\.(?:jpg|png|webp))"
)
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class VisualPreviewError(ValueError):
    """A deliberately content-free operator error."""

    def __init__(self, code: str = "preview_input_invalid") -> None:
        self.code = code
        super().__init__(code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapturedFile(_FrozenModel):
    path: str = Field(min_length=1, max_length=80)
    sha256: Sha
    byte_size: int = Field(gt=0, le=MAX_IMAGE_BYTES, strict=True)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _MEMBER.fullmatch(value) is None:
            raise VisualPreviewError()
        return value


class PreviewInputManifest(_FrozenModel):
    schema_version: Literal["official-account-visual-preview-input-v1"]
    source_run_id: UUID
    status: Literal["ready"]
    files: tuple[CapturedFile, ...] = Field(min_length=10, max_length=21)


class PreviewSnapshot(_FrozenModel):
    article_version_id: UUID
    render_version_id: UUID
    render_fingerprint: Sha
    article_created_at: datetime
    validation_issues: tuple[ArticleValidationIssue, ...] = Field(max_length=100)
    audit: OfficialAccountAuditVerdict
    catalog_media: tuple[OfficialAccountSourceMedia, ...] = Field(min_length=5, max_length=5)
    context_media: OfficialAccountSourceMedia
    references: tuple[OfficialAccountSourceMedia, ...] = Field(min_length=1, max_length=12)

    @field_validator("catalog_media", "context_media", "references", mode="before")
    @classmethod
    def reject_unknown_media_fields(cls, value: object) -> object:
        allowed = {item.name for item in fields(OfficialAccountSourceMedia)}
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if isinstance(item, dict) and not set(item) <= allowed:
                raise VisualPreviewError()
        return value


@dataclass(frozen=True, slots=True)
class PreviewInput:
    manifest_sha256: str
    manifest: PreviewInputManifest
    snapshot: PreviewSnapshot
    article: StoredOfficialAccountArticle
    render: StoredOfficialAccountRender
    source: OfficialAccountSourceSnapshot
    files: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class PreviewScene:
    plan: OfficialAccountGeneratedVisualPlan
    reference: OfficialAccountSourceMedia
    reference_bytes: bytes
    normalized_reference: bytes
    prompt: str
    base_plan_request_fingerprint: str


@dataclass(frozen=True, slots=True)
class PreviewPlan:
    preview_id: UUID
    source: PreviewInput
    scenes: tuple[PreviewScene, ...]


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _json_object(body: bytes) -> dict[str, object]:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise VisualPreviewError()
            output[key] = value
        return output

    def reject_constant(value: str) -> object:
        raise VisualPreviewError()

    if len(body) > MAX_JSON_BYTES:
        raise VisualPreviewError()
    value = json.loads(body, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise VisualPreviewError()
    return value


def checked_path(path: Path, *, must_exist: bool = True) -> Path:
    """Reject traversal and every symlink component, including the supplied root."""
    if ".." in path.parts:
        raise VisualPreviewError("preview_path_invalid")
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise VisualPreviewError("preview_path_invalid")
    if must_exist and not absolute.exists():
        raise VisualPreviewError("preview_path_invalid")
    return absolute


def _read_file(path: Path, maximum: int) -> bytes:
    checked_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise VisualPreviewError()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(maximum + 1)
        if len(body) != info.st_size or len(body) > maximum:
            raise VisualPreviewError()
        return body
    finally:
        os.close(descriptor)


def image_dimensions(body: bytes, media_type: str) -> tuple[int, int]:
    if not body or len(body) > MAX_IMAGE_BYTES or media_type not in _FORMATS:
        raise VisualPreviewError("preview_image_invalid")
    with Image.open(BytesIO(body)) as opened:
        if (
            opened.format != _FORMATS[media_type]
            or getattr(opened, "n_frames", 1) != 1
            or not 1 <= opened.width <= 8192
            or not 1 <= opened.height <= 8192
            or opened.width * opened.height > 24_000_000
        ):
            raise VisualPreviewError("preview_image_invalid")
        opened.load()
        return opened.size


def _media_path(kind: str, index: int, media: OfficialAccountSourceMedia) -> str:
    try:
        return f"{kind}/{index}.{_EXTENSIONS[media.media_type]}"
    except KeyError:
        raise VisualPreviewError() from None


def load_preview_input(root: Path, *, manifest_sha256: str) -> PreviewInput:
    """Validate the entire bounded bundle before credentials or clients are constructed."""
    root = checked_path(root)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise VisualPreviewError("preview_input_must_be_private")
    body = _read_file(root / "manifest.json", MAX_JSON_BYTES)
    if sha256(body).hexdigest() != manifest_sha256:
        raise VisualPreviewError("preview_source_hash_changed")
    manifest = PreviewInputManifest.model_validate(_json_object(body))
    paths = {item.path for item in manifest.files}
    if (
        manifest.source_run_id != SOURCE_RUN_ID
        or len(paths) != len(manifest.files)
        or sum(item.byte_size for item in manifest.files) > MAX_BUNDLE_BYTES
    ):
        raise VisualPreviewError()
    actual: set[str] = set()
    for directory, subdirs, names in os.walk(root, followlinks=False):
        relative_dir = Path(directory).relative_to(root).as_posix()
        if (relative_dir == "." and set(subdirs) != {"catalog", "context", "references"}) or (
            relative_dir != "."
            and (relative_dir not in {"catalog", "context", "references"} or subdirs)
        ):
            raise VisualPreviewError()
        if len(actual) + len(subdirs) + len(names) > 40:
            raise VisualPreviewError()
        for name in (*subdirs, *names):
            checked_path(Path(directory) / name)
        actual.update((Path(directory) / name).relative_to(root).as_posix() for name in names)
    if actual != paths | {"manifest.json"}:
        raise VisualPreviewError()
    files_by_path: dict[str, bytes] = {}
    for entry in manifest.files:
        limit = MAX_JSON_BYTES if entry.path.endswith(".json") else MAX_IMAGE_BYTES
        content = _read_file(root / entry.path, min(limit, entry.byte_size))
        if len(content) != entry.byte_size or sha256(content).hexdigest() != entry.sha256:
            raise VisualPreviewError("preview_source_hash_changed")
        files_by_path[entry.path] = content
    if not {"article.json", "source.json", "snapshot.json"} <= paths:
        raise VisualPreviewError()
    snapshot = PreviewSnapshot.model_validate(_json_object(files_by_path["snapshot.json"]))
    article = ArticlePackage.model_validate(_json_object(files_by_path["article.json"]))
    source = OfficialAccountSourceSnapshot.model_validate(
        _json_object(files_by_path["source.json"])
    )
    if (
        article.content_fingerprint != article_package_fingerprint(article)
        or not snapshot.audit.accepted
        or any(issue.severity == "error" for issue in snapshot.validation_issues)
        or snapshot.article_created_at.tzinfo is None
        or article.media_selection is None
        or len(article.media_selection.assignments) != 5
        or article.news_context_media is None
        or len(article.news_context_media.items) != 1
    ):
        raise VisualPreviewError("preview_article_invalid")
    issues = validate_article_package(
        article,
        source=source,
        default_author=article.author,
        min_characters=1,
        target_min_characters=1,
        target_max_characters=20_000,
        max_characters=20_000,
    )
    if any(issue.severity == "error" for issue in issues):
        raise VisualPreviewError("preview_source_binding_invalid")
    required = {"article.json", "source.json", "snapshot.json"}
    for kind, items in (
        ("catalog", snapshot.catalog_media),
        ("context", (snapshot.context_media,)),
        ("references", snapshot.references),
    ):
        for index, media in enumerate(items):
            path = _media_path(kind, index, media)
            required.add(path)
            content = files_by_path.get(path, b"")
            dimensions = image_dimensions(content, media.media_type)
            if (
                sha256(content).hexdigest() != media.sha256
                or len(content) != media.byte_size
                or dimensions != (media.width, media.height)
            ):
                raise VisualPreviewError("preview_media_binding_invalid")
    if paths != required:
        raise VisualPreviewError()
    for assignment, media in zip(
        article.media_selection.assignments, snapshot.catalog_media, strict=True
    ):
        if (
            media.ordinal != assignment.ordinal
            or media.assigned_section_index != assignment.section_index
            or media.catalog_asset_ref != assignment.candidate_ref
            or media.catalog_version != article.media_selection.catalog_version
            or media.sha256 != assignment.publication_checksum
            or media.source_master_sha256 != assignment.source_checksum
            or media.selection_method != assignment.selection_method
            or media.similarity_band != assignment.similarity_band
        ):
            raise VisualPreviewError("preview_catalog_binding_invalid")
    context = snapshot.context_media
    original = article.news_context_media.items[0]
    if (
        (context.width, context.height) != (1004, 620)
        or context.ordinal != original.ordinal
        or context.source_article_image_id != original.source_article_image_id
        or context.sha256 != original.sha256
        or context.media_type != original.media_type
        or (context.width, context.height) != (original.width, original.height)
        or context.assigned_section_index != original.section_index
        or context.source_page_url != original.source_page_url
        or context.alt_text != original.alt_text
        or context.caption_text != (original.caption or "")
        or context.credit != original.credit
        or context.rights_status != original.rights_status
        or context.context_only_not_evidence is not True
    ):
        raise VisualPreviewError("preview_context_binding_invalid")
    stored_article = StoredOfficialAccountArticle(
        id=snapshot.article_version_id,
        article=article,
        validation_issues=snapshot.validation_issues,
        audit=snapshot.audit,
        provider_request_id=None,
        prompt_tokens=0,
        completion_tokens=0,
        reasoning_tokens=0,
        latency_ms=0,
        created_at=snapshot.article_created_at,
    )
    render = StoredOfficialAccountRender(
        id=snapshot.render_version_id,
        article_version_id=snapshot.article_version_id,
        canonical_html="",
        render_fingerprint=snapshot.render_fingerprint,
    )
    return PreviewInput(
        manifest_sha256, manifest, snapshot, stored_article, render, source, files_by_path
    )


def plan_visual_preview(source: PreviewInput, *, preview_id: UUID | None = None) -> PreviewPlan:
    preview_id = preview_id or uuid4()
    candidates = [
        (index, media)
        for index, media in enumerate(source.snapshot.references)
        if media.width is not None
        and media.height is not None
        and min(media.width, media.height) >= 512
        and media.catalog_asset_ref
        and media.catalog_version
        and media.source_master_sha256
        and media.generated_visual_id is None
        and media.source_article_image_id is None
    ]
    if not candidates:
        raise VisualPreviewError("preview_usable_reference_missing")
    scenes: list[PreviewScene] = []
    for current in source.snapshot.catalog_media:
        # Exact current reference when usable, then deterministic tag overlap/public identity.
        section_index = current.assigned_section_index
        if section_index is None:
            raise VisualPreviewError()
        heading = source.article.article.sections[section_index].heading
        index, selected = min(
            candidates,
            key=lambda item: (
                item[1].catalog_asset_ref != current.catalog_asset_ref,
                -sum(tag in heading for tag in item[1].semantic_tags),
                item[1].catalog_asset_ref or "",
                item[0],
            ),
        )
        reference = replace(
            selected,
            ordinal=current.ordinal,
            assigned_section_index=section_index,
            selection_method="deterministic_tag",
            similarity_band=None,
        )
        reference_bytes = source.files[_media_path("references", index, selected)]
        plan = plan_generated_body_visual(
            run_id=preview_id,
            article=source.article,
            render=source.render,
            ordinal=current.ordinal,
            reference=reference,
            provider="comfly",
            model=GENERATION_MODEL,
            reference_bytes=reference_bytes,
        )
        prompt = build_generated_visual_prompt(
            article=source.article,
            section_index=section_index,
            reference=reference,
            prompt_version=plan.prompt_version,
            block_index=plan.block_index,
        )
        normalized = normalize_image_provider_reference(
            reference_bytes, version=IMAGE_REFERENCE_INPUT_V2
        )
        base_request_fingerprint = plan.request_fingerprint
        # The pure production plan remains separately identifiable. This preview request adds
        # its fresh execution and explicit native geometry to the actual provider identity.
        request_fingerprint = fingerprint(
            "official-account-visual-preview-request-v1",
            str(preview_id),
            base_request_fingerprint,
            "1536x1024",
            sha256(prompt.encode()).hexdigest(),
        )
        plan = replace(plan, request_fingerprint=request_fingerprint)
        scenes.append(
            PreviewScene(
                plan,
                reference,
                reference_bytes,
                normalized.image_png,
                prompt,
                base_request_fingerprint,
            )
        )
    if len({scene.plan.block_fingerprint for scene in scenes}) != 5:
        raise VisualPreviewError("preview_scene_anchors_repeated")
    return PreviewPlan(preview_id, source, tuple(scenes))


def validate_preview_output_path(root: Path) -> Path:
    root = checked_path(root, must_exist=False)
    checked_path(root.parent)
    if any(
        part in {"weekly-inbox", "official-account-weekly-editions", "wechat-drafts"}
        for part in root.parts
    ):
        raise VisualPreviewError("preview_output_forbidden")
    if root.exists():
        raise VisualPreviewError("preview_output_exists")
    return root


def _reserve_directory(root: Path) -> Path:
    root = validate_preview_output_path(root)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        raise VisualPreviewError("preview_output_exists") from None
    for name in ("calls", "transport", "assets", "raw"):
        (root / name).mkdir(mode=0o700)
    return root


def write_private_file(root: Path, name: str, body: bytes) -> None:
    target = checked_path(root / name, must_exist=False)
    if not target.is_relative_to(root) or target == root:
        raise VisualPreviewError("preview_path_invalid")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class PreviewJournal:
    """Exclusive append-only files. Existing output is never reopened, repaired, or resumed."""

    def __init__(self, root: Path, plan: PreviewPlan) -> None:
        root = _reserve_directory(root)
        self.root = root
        self.active_call: str | None = None
        self.calls: list[dict[str, object]] = []
        self.write_json(
            "intent.json",
            {
                "schema_version": PREVIEW_VERSION,
                "preview_id": str(plan.preview_id),
                "source_run_id": str(SOURCE_RUN_ID),
                "source_manifest_sha256": plan.source.manifest_sha256,
                "generation_limit": 5,
                "audit_limit": 6,
                "transport_attempts": 1,
                "restart_policy": "never_resume",
                "published": False,
                "local_only": True,
                "database_persisted": False,
                "human_approved": False,
            },
        )

    def write(self, name: str, body: bytes) -> None:
        write_private_file(self.root, name, body)

    def write_json(self, name: str, value: object) -> None:
        self.write(name, canonical_json(value))

    def begin_call(
        self, kind: Literal["generation", "audit"], ordinal: int, metadata: dict[str, object]
    ) -> str:
        limit = 5 if kind == "generation" else 6
        if self.active_call is not None or not 0 <= ordinal < limit:
            raise VisualPreviewError("preview_call_budget_exceeded")
        key = f"{kind}-{ordinal}"
        self.write_json(
            f"calls/{key}.intent.json",
            {
                "kind": kind,
                "ordinal": ordinal,
                "attempt": 1,
                "recorded_at": datetime.now(UTC).isoformat(),
                **metadata,
            },
        )
        self.active_call = key
        return key

    def finish_call(self, key: str, result: dict[str, object]) -> None:
        self.write_json(
            f"calls/{key}.result.json", {"recorded_at": datetime.now(UTC).isoformat(), **result}
        )
        self.calls.append({"call": key, **result})
        self.active_call = None


def _image_reference(scene: PreviewScene, *, normalized: bool = False) -> ImageReference:
    body = scene.normalized_reference if normalized else scene.reference_bytes
    return ImageReference(
        role="approved_ip_reference",
        asset_id=scene.plan.reference_asset_ref,
        filename="approved-reference.png" if normalized else "approved-reference.jpg",
        sha256=sha256(body).hexdigest(),
        image_bytes=body,
        selection_reason="deterministic_approved_reference_no_embedding",
        input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
        provider_input_sha256=scene.plan.reference_input_checksum,
    )


def preview_audit_request(
    *, plan: PreviewPlan, scene: PreviewScene, body: bytes, role: Literal["body", "cover"]
) -> ImageQualityAuditRequest:
    article = plan.source.article
    anchor = select_generated_visual_block_anchor(
        article=article, section_index=scene.plan.section_index
    )
    # Eight bounded criteria retain up to 480 characters of the exact block; no raw criterion
    # text is emitted in the ledger. The adapter treats this context as untrusted input.
    criteria = (
        (
            f"Role={role}. Article title: {article.article.title}. "
            "The image must explain this article."
        )[:200],
        (
            f"Section: {article.article.sections[scene.plan.section_index].heading}. "
            "Match its specific idea."
        )[:200],
        f"Exact block context 1: {anchor.scene_text[:170]}",
        f"Exact block context 2: {anchor.scene_text[170:340] or '(continued above)'}",
        f"Exact block context 3: {anchor.scene_text[340:480] or '(continued above)'}",
        "The approved reference character must be recognizable and central in a contextual "
        "science-education scene, not an isolated avatar or catalog composition.",
        "Reject words, letters, numbers, logos, watermarks, QR codes, anatomy defects, blur, "
        "unsupported science, or confusing child/parent interaction.",
        (
            "Landscape cover: article-relevant action and character survive cropping; no cut face, "
            "isolated mascot, generic backdrop or misleading news photograph."
            if role == "cover"
            else "Body scene: clear section-specific action, coherent composition, "
            "generous margins and sharp final publication pixels; not a generic character pose."
        ),
    )
    request_fingerprint = fingerprint(
        PREVIEW_RUBRIC,
        role,
        sha256(body).hexdigest(),
        scene.plan.block_fingerprint,
        scene.plan.reference_input_checksum,
        criteria,
        AUDIT_MODEL,
    )
    return ImageQualityAuditRequest(
        image_bytes=body,
        media_type="image/jpeg",
        references=(_image_reference(scene, normalized=True),),
        criteria=criteria,
        request_fingerprint=request_fingerprint,
        rubric_version=PREVIEW_RUBRIC,
    )


def preview_audit_passes(
    result: ImageQualityAuditResult | None, *, request_fingerprint: str
) -> bool:
    """Separate from production's non-blocking observe policy; warnings cannot pass."""
    return bool(
        result is not None
        and result.accepted is True
        and not result.issues
        and result.provider == "openai-compatible"
        and result.model == AUDIT_MODEL
        and result.request_fingerprint == request_fingerprint
    )


def preview_image_checks(
    body_images: tuple[bytes, ...], *, catalog_images: tuple[bytes, ...]
) -> tuple[str, ...]:
    codes: set[str] = set()
    if len(body_images) != 5:
        codes.add("preview_body_count_invalid")
    hashes: list[str] = []
    perceptual: list[str] = []
    catalog_hashes = {sha256(body).hexdigest() for body in catalog_images}
    catalog_perceptual = tuple(perceptual_dhash(body) for body in catalog_images)
    for body in body_images:
        if image_dimensions(body, "image/jpeg") != (1536, 1024):
            codes.add("preview_body_resolution_invalid")
        value = sha256(body).hexdigest()
        dhash = perceptual_dhash(body)
        if value in hashes:
            codes.add("preview_exact_repetition")
        if any(
            perceptual_hash_distance(dhash, other) <= DEFAULT_IMAGE_SIMILARITY_THRESHOLD
            for other in perceptual
        ):
            codes.add("preview_perceptual_repetition")
        if value in catalog_hashes or any(
            perceptual_hash_distance(dhash, old) <= DEFAULT_IMAGE_SIMILARITY_THRESHOLD
            for old in catalog_perceptual
        ):
            codes.add("preview_catalog_reuse")
        hashes.append(value)
        perceptual.append(dhash)
    return tuple(sorted(codes))


def derive_preview_cover(body: bytes) -> tuple[bytes, tuple[int, int, int, int]]:
    if image_dimensions(body, "image/jpeg") != (1536, 1024):
        raise VisualPreviewError("preview_cover_source_invalid")
    # Explicit preview policy, not the historical handoff crop identity. Keep central action.
    crop = (0, 185, 1536, 839)
    with Image.open(BytesIO(body)) as opened:
        cropped = opened.convert("RGB").crop(crop)
        output = BytesIO()
        cropped.save(output, format="JPEG", quality=92, optimize=True, exif=b"")
    result = output.getvalue()
    if image_dimensions(result, "image/jpeg") != (1536, 654):
        raise VisualPreviewError("preview_cover_resolution_invalid")
    return result, crop


async def _audit(
    *,
    auditor: ImageQualityAuditor,
    journal: PreviewJournal,
    request: ImageQualityAuditRequest,
    ordinal: int,
) -> bool:
    key = journal.begin_call(
        "audit",
        ordinal,
        {
            "route_owner": "zhipu",
            "model": AUDIT_MODEL,
            "request_fingerprint": request.request_fingerprint,
            "image_sha256": sha256(request.image_bytes).hexdigest(),
            "reference_input_sha256": request.references[0].sha256,
            "rubric_version": PREVIEW_RUBRIC,
        },
    )
    try:
        result = await auditor.audit(request)
    except Exception:
        journal.finish_call(key, {"status": "unavailable_or_unknown", "accepted": False})
        return False
    passed = preview_audit_passes(result, request_fingerprint=request.request_fingerprint)
    journal.finish_call(
        key,
        {
            "status": "accepted" if passed else "review_required",
            "accepted": passed,
            "model_identity_matched": result.model == AUDIT_MODEL,
            "request_identity_matched": result.request_fingerprint == request.request_fingerprint,
            "issues": [{"code": issue.code, "severity": issue.severity} for issue in result.issues],
        },
    )
    return passed


def _asset(
    *,
    body: bytes,
    role: Literal["body", "cover", "context"],
    ordinal: int,
    media_type: str,
    alt_text: str,
    section: int | None = None,
) -> EditorHandoffMediaAsset:
    width, height = image_dimensions(body, media_type)
    return EditorHandoffMediaAsset.model_validate(
        {
            "path": media_asset_path(role, ordinal, media_type),
            "role": role,
            "ordinal": ordinal,
            "media_type": media_type,
            "byte_size": len(body),
            "sha256": sha256(body).hexdigest(),
            "width": width,
            "height": height,
            "alt_text": alt_text,
            "assigned_section_index": section,
        }
    )


def _preview_html(article: ArticlePackage, body_html: str, cover: EditorHandoffMediaAsset) -> bytes:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; img-src 'self'; style-src 'unsafe-inline'\">"
        f"<title>{escape(article.title)}</title>"
        "<style>html,body{margin:0;padding:0;background:#f4f1e9}*{box-sizing:border-box}"
        "main,header{max-width:680px;margin:auto}img{max-width:100%;height:auto}"
        "header{padding:16px;color:#344e59;font:14px sans-serif}"
        "main{background:white;overflow-wrap:anywhere}</style>"
        "</head><body><header><p>本地视觉预览 · 未发布 · 待人工确认</p>"
        f'<img src="{cover.path}" alt="{escape(cover.alt_text, quote=True)}"></header>'
        f'<main id="copy-root">{body_html}</main></body></html>'
    ).encode()


def _mobile_input(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "visual-preview-mobile-input-v1",
        "content_fingerprint": manifest["content_fingerprint"],
        "body_sha256": manifest["body_sha256"],
        "preview_sha256": manifest["preview_sha256"],
        "media_sha256_by_path": manifest["media_sha256_by_path"],
        "required_widths": [320, 430],
        "copy_root": "copy-root",
        "status": "not_run",
    }


async def execute_visual_preview(
    *,
    plan: PreviewPlan,
    journal: PreviewJournal,
    generator: ImageGenerator,
    auditor: ImageQualityAuditor,
) -> dict[str, object]:
    """Five generation calls and six audits at most; keep incomplete/failed paid artifacts."""
    images: list[bytes] = []
    assets: list[EditorHandoffMediaAsset] = []
    accepted: list[bool] = []
    lineages: list[dict[str, object]] = []
    try:
        for scene in plan.scenes:
            identity = scene.plan
            key = journal.begin_call(
                "generation",
                identity.ordinal,
                {
                    "provider": "comfly",
                    "model": GENERATION_MODEL,
                    "request_fingerprint": identity.request_fingerprint,
                    "reference_public_ref": identity.reference_asset_ref,
                    "reference_input_sha256": identity.reference_input_checksum,
                    "block_fingerprint": identity.block_fingerprint,
                    "selection_method": "deterministic_tag",
                    "embedding_calls": 0,
                },
            )
            try:
                result = await generator.generate(
                    ImageGenerationRequest(
                        run_id=plan.preview_id,
                        draft_version_id=identity.article_version_id,
                        prompt=scene.prompt,
                        request_fingerprint=identity.request_fingerprint,
                        references=(_image_reference(scene),),
                        reference_mode="single_reference",
                        output_size="1536x1024",
                    )
                )
                if result.attempts != 1:
                    raise VisualPreviewError("preview_provider_attempts_invalid")
                raw_dimensions = image_dimensions(result.image_bytes, result.media_type)
                journal.write(
                    f"raw/body-{identity.ordinal:02d}.{_EXTENSIONS[result.media_type]}",
                    result.image_bytes,
                )
                if raw_dimensions != (1536, 1024):
                    raise VisualPreviewError("preview_raw_resolution_invalid")
                prepared = prepare_generated_visual_result(
                    result=result, plan=identity, max_bytes=MAX_IMAGE_BYTES
                )
                asset = _asset(
                    body=prepared.image_bytes,
                    role="body",
                    ordinal=identity.ordinal,
                    media_type="image/jpeg",
                    section=identity.section_index,
                    alt_text=generated_visual_alt_text(article=plan.source.article, plan=identity),
                )
                journal.write(asset.path, prepared.image_bytes)
                journal.finish_call(
                    key,
                    {
                        "status": "completed",
                        "output_sha256": asset.sha256,
                        "raw_sha256": sha256(result.image_bytes).hexdigest(),
                        "raw_width": result.width,
                        "raw_height": result.height,
                        "width": asset.width,
                        "height": asset.height,
                    },
                )
            except Exception:
                if journal.active_call == key:
                    journal.finish_call(
                        key, {"status": "failed_or_unknown", "automatic_retry": False}
                    )
                raise VisualPreviewError("preview_generation_incomplete") from None
            images.append(prepared.image_bytes)
            assets.append(asset)
            lineages.append(
                {
                    "ordinal": identity.ordinal,
                    "section_index": identity.section_index,
                    "block_index": identity.block_index,
                    "block_fingerprint": identity.block_fingerprint,
                    "reference_public_ref": identity.reference_asset_ref,
                    "reference_catalog_version": identity.reference_catalog_version,
                    "reference_publication_sha256": identity.reference_publication_checksum,
                    "reference_input_sha256": identity.reference_input_checksum,
                    "selection_method": "deterministic_tag",
                    "provider": "comfly",
                    "model": GENERATION_MODEL,
                    "plan_version": identity.plan_version,
                    "prompt_version": identity.prompt_version,
                    "request_fingerprint": identity.request_fingerprint,
                    "output_sha256": asset.sha256,
                    "base_plan_request_fingerprint": scene.base_plan_request_fingerprint,
                    "request_version": "official-account-visual-preview-request-v1",
                    "requested_size": "1536x1024",
                    "generation_kind": "local_preview_provider_output",
                    "database_persisted": False,
                }
            )
            accepted.append(
                await _audit(
                    auditor=auditor,
                    journal=journal,
                    request=preview_audit_request(
                        plan=plan, scene=scene, body=prepared.image_bytes, role="body"
                    ),
                    ordinal=identity.ordinal,
                )
            )

        # The opening scene carries the article's framing. Prefer an accepted body if available;
        # every final crop still gets its own independent exact-byte audit.
        cover_ordinal = next((index for index, value in enumerate(accepted) if value), 0)
        cover, crop = derive_preview_cover(images[cover_ordinal])
        cover_asset = _asset(
            body=cover,
            role="cover",
            ordinal=0,
            media_type="image/jpeg",
            alt_text=plan.source.article.article.title,
        )
        journal.write(cover_asset.path, cover)
        assets.append(cover_asset)
        accepted.append(
            await _audit(
                auditor=auditor,
                journal=journal,
                request=preview_audit_request(
                    plan=plan, scene=plan.scenes[cover_ordinal], body=cover, role="cover"
                ),
                ordinal=5,
            )
        )
        original = plan.source.snapshot.context_media
        context_bytes = plan.source.files[_media_path("context", 0, original)]
        context = _asset(
            body=context_bytes,
            role="context",
            ordinal=0,
            media_type=original.media_type,
            alt_text=original.alt_text,
            section=original.assigned_section_index,
        )
        context = context.model_copy(
            update={
                "source_page_url": original.source_page_url,
                "caption": original.caption_text or None,
                "credit": original.credit,
                "rights_status": original.rights_status,
                "context_only_not_evidence": True,
            }
        )
        assets.append(context)
        journal.write(context.path, context_bytes)
        catalog = tuple(
            plan.source.files[_media_path("catalog", i, item)]
            for i, item in enumerate(plan.source.snapshot.catalog_media)
        )
        reference_images = tuple(
            plan.source.files[_media_path("references", i, item)]
            for i, item in enumerate(plan.source.snapshot.references)
        )
        checks = preview_image_checks(tuple(images), catalog_images=(*catalog, *reference_images))
        rendered = render_editor_handoff_v2_body(
            article=plan.source.article.article, media=tuple(assets)
        )
        body_html = rendered.body_html.encode()
        preview = _preview_html(plan.source.article.article, rendered.body_html, cover_asset)
        for name, body in (
            ("article-body.html", body_html),
            ("preview.html", preview),
            ("article.json", plan.source.files["article.json"]),
            ("source.json", plan.source.files["source.json"]),
        ):
            journal.write(name, body)
        media_hashes = {item.path: item.sha256 for item in assets}
        content_fingerprint = fingerprint(
            PREVIEW_VERSION,
            plan.source.manifest_sha256,
            sha256(body_html).hexdigest(),
            sha256(preview).hexdigest(),
            media_hashes,
        )
        manifest: dict[str, object] = {
            "schema_version": PREVIEW_VERSION,
            "preview_id": str(plan.preview_id),
            "source_run_id": str(SOURCE_RUN_ID),
            "source_manifest_sha256": plan.source.manifest_sha256,
            "source_article_version_id": str(plan.source.article.id),
            "source_render_version_id": str(plan.source.render.id),
            "source_render_fingerprint": plan.source.render.render_fingerprint,
            "source_article_content_fingerprint": plan.source.article.article.content_fingerprint,
            "article_sha256": sha256(plan.source.files["article.json"]).hexdigest(),
            "source_sha256": sha256(plan.source.files["source.json"]).hexdigest(),
            "body_sha256": sha256(body_html).hexdigest(),
            "preview_sha256": sha256(preview).hexdigest(),
            "content_fingerprint": content_fingerprint,
            "media_sha256_by_path": media_hashes,
            "media": [item.model_dump(mode="json") for item in assets],
            "body_lineage": lineages,
            "cover_lineage": {
                "source_body_ordinal": cover_ordinal,
                "source_sha256": sha256(images[cover_ordinal]).hexdigest(),
                "output_sha256": cover_asset.sha256,
                "crop_box": crop,
                "policy": "preview-centered-landscape-crop-v1",
            },
            "quality_policy": PREVIEW_RUBRIC,
            "quality_gate_passed": all(accepted) and not checks,
            "quality_blocking_codes": list(checks),
            "audit_acceptance": accepted,
            "mobile_validation": "not_run",
            "preview_accepted": False,
            "local_only": True,
            "published": False,
            "database_persisted": False,
            "human_approved": False,
            "production_activated": False,
            "drafts_replaced": False,
            "calls": journal.calls,
            "embedding_calls": 0,
            "context_placements": [item.model_dump(mode="json") for item in rendered.placements],
            "evidence_sha256_by_path": {
                "intent.json": sha256(
                    _read_file(journal.root / "intent.json", MAX_JSON_BYTES)
                ).hexdigest(),
                **{
                    path.relative_to(journal.root).as_posix(): sha256(
                        _read_file(path, MAX_IMAGE_BYTES)
                    ).hexdigest()
                    for name in ("calls", "transport", "raw")
                    for path in sorted((journal.root / name).iterdir())
                },
            },
        }
        journal.write_json("manifest.json", manifest)
        journal.write_json("mobile-input.json", _mobile_input(manifest))
        journal.write_json(
            "terminal.json",
            {
                "status": "rendered",
                "quality_gate_passed": manifest["quality_gate_passed"],
                "mobile_validation": "not_run",
                "preview_accepted": False,
            },
        )
        return manifest
    except Exception:
        journal.write_json(
            "terminal.json",
            {
                "status": "incomplete",
                "preview_accepted": False,
                "completed_body_count": len(images),
                "automatic_retry": False,
            },
        )
        raise VisualPreviewError("preview_incomplete") from None


class PreviewViewport(_FrozenModel):
    width: Literal[320, 430]
    loaded_images: Literal[7]
    failed_images: Literal[0]
    horizontal_overflow_px: Literal[0]
    external_requests: Literal[0]
    copy_root_matches_body: Literal[True]


class PreviewMobileReport(_FrozenModel):
    schema_version: Literal["visual-preview-mobile-report-v1"]
    content_fingerprint: Sha
    body_sha256: Sha
    preview_sha256: Sha
    media_sha256_by_path: dict[str, Sha]
    observations: tuple[PreviewViewport, PreviewViewport]


def _load_completed_preview(
    root: Path, manifest_sha256: str
) -> tuple[dict[str, object], dict[str, bytes]]:
    root = checked_path(root)
    manifest_bytes = _read_file(root / "manifest.json", MAX_JSON_BYTES)
    if sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise VisualPreviewError("preview_manifest_changed")
    manifest = _json_object(manifest_bytes)
    if (
        manifest.get("schema_version") != PREVIEW_VERSION
        or manifest.get("source_run_id") != str(SOURCE_RUN_ID)
        or manifest.get("local_only") is not True
        or manifest.get("published") is not False
        or manifest.get("database_persisted") is not False
        or manifest.get("human_approved") is not False
    ):
        raise VisualPreviewError("preview_manifest_invalid")
    hashes: dict[str, object] = {
        name: manifest.get(key)
        for name, key in (
            ("article.json", "article_sha256"),
            ("source.json", "source_sha256"),
            ("article-body.html", "body_sha256"),
            ("preview.html", "preview_sha256"),
        )
    }
    for field in ("media_sha256_by_path", "evidence_sha256_by_path"):
        values = manifest.get(field)
        if not isinstance(values, dict) or len(values) > 380:
            raise VisualPreviewError("preview_manifest_invalid")
        if set(hashes).intersection(values):
            raise VisualPreviewError("preview_manifest_invalid")
        hashes.update(values)
    # Unknown paid-call records must not disappear from replay/finalization provenance.
    evidence = manifest["evidence_sha256_by_path"]
    if not isinstance(evidence, dict) or "intent.json" not in evidence:
        raise VisualPreviewError("preview_manifest_invalid")
    expected_evidence = {"intent.json"}
    for name in ("calls", "transport", "raw"):
        directory = checked_path(root / name)
        entries = list(directory.iterdir())
        if len(entries) > 380:
            raise VisualPreviewError("preview_manifest_invalid")
        for entry in entries:
            checked_path(entry)
            if not entry.is_file():
                raise VisualPreviewError("preview_manifest_invalid")
            expected_evidence.add(entry.relative_to(root).as_posix())
    if set(evidence) != expected_evidence:
        raise VisualPreviewError("preview_evidence_members_changed")
    files_by_path: dict[str, bytes] = {}
    for name, expected_sha in hashes.items():
        if (
            not isinstance(name, str)
            or re.fullmatch(
                r"(?:intent\.json|article\.json|source\.json|article-body\.html|preview\.html|"
                r"assets/(?:body-0[0-4]|context-00|cover-wide)\.(?:jpg|png|webp)|"
                r"raw/body-0[0-4]\.(?:jpg|png|webp)|"
                r"(?:calls|transport)/(?:generation|audit)-[0-9]{1,3}\.(?:intent|result)\.json)",
                name,
            )
            is None
        ):
            raise VisualPreviewError("preview_manifest_invalid")
        body = _read_file(root / name, MAX_IMAGE_BYTES)
        if sha256(body).hexdigest() != expected_sha:
            raise VisualPreviewError("preview_artifact_changed")
        files_by_path[name] = body
    if sum(len(body) for body in files_by_path.values()) > 2 * MAX_BUNDLE_BYTES:
        raise VisualPreviewError("preview_artifact_too_large")
    return manifest, files_by_path


def rerender_visual_preview(
    *, source_dir: Path, manifest_sha256: str, output_dir: Path
) -> dict[str, object]:
    """Rebuild presentation in a fresh directory using verified already-paid bytes. Zero calls."""
    manifest, files_by_path = _load_completed_preview(source_dir, manifest_sha256)
    article = ArticlePackage.model_validate(_json_object(files_by_path["article.json"]))
    raw_media = manifest.get("media")
    if not isinstance(raw_media, list) or len(raw_media) != 7:
        raise VisualPreviewError("preview_manifest_invalid")
    media = tuple(EditorHandoffMediaAsset.model_validate(item) for item in raw_media)
    cover = next(item for item in media if item.role == "cover")
    rendered = render_editor_handoff_v2_body(article=article, media=media)
    files_by_path["article-body.html"] = rendered.body_html.encode()
    files_by_path["preview.html"] = _preview_html(article, rendered.body_html, cover)
    manifest.update(
        {
            "body_sha256": sha256(files_by_path["article-body.html"]).hexdigest(),
            "preview_sha256": sha256(files_by_path["preview.html"]).hexdigest(),
            "parent_preview_manifest_sha256": manifest_sha256,
            "projection_provider_calls": 0,
            "mobile_validation": "not_run",
            "preview_accepted": False,
            "context_placements": [item.model_dump(mode="json") for item in rendered.placements],
        }
    )
    manifest["content_fingerprint"] = fingerprint(
        PREVIEW_VERSION,
        manifest["source_manifest_sha256"],
        manifest["body_sha256"],
        manifest["preview_sha256"],
        manifest["media_sha256_by_path"],
    )
    output = _reserve_directory(output_dir)
    for name, body in files_by_path.items():
        write_private_file(output, name, body)
    write_private_file(output, "manifest.json", canonical_json(manifest))
    write_private_file(output, "mobile-input.json", canonical_json(_mobile_input(manifest)))
    write_private_file(
        output,
        "projection.json",
        canonical_json(
            {
                "parent_preview_manifest_sha256": manifest_sha256,
                "provider_calls": 0,
                "published": False,
                "local_only": True,
                "preview_accepted": False,
            }
        ),
    )
    return manifest


def finalize_visual_preview(
    *, root: Path, manifest_sha256: str, report_path: Path
) -> dict[str, object]:
    """Append exact browser evidence, never rewrite paid files or invent human approval."""
    manifest, _files = _load_completed_preview(root, manifest_sha256)
    report = PreviewMobileReport.model_validate(
        _json_object(_read_file(report_path, MAX_JSON_BYTES))
    )
    if (
        tuple(item.width for item in report.observations) != (320, 430)
        or report.content_fingerprint != manifest["content_fingerprint"]
        or report.body_sha256 != manifest["body_sha256"]
        or report.preview_sha256 != manifest["preview_sha256"]
        or report.media_sha256_by_path != manifest["media_sha256_by_path"]
    ):
        raise VisualPreviewError("preview_mobile_binding_invalid")
    result = {
        "schema_version": "visual-preview-acceptance-v1",
        "preview_manifest_sha256": manifest_sha256,
        "mobile_validation": "passed",
        "content_fingerprint": manifest["content_fingerprint"],
        "preview_accepted": manifest.get("quality_gate_passed") is True,
        "human_approved": False,
        "published": False,
        "database_persisted": False,
        "production_activated": False,
        "provider_calls": 0,
        "browser_report": report.model_dump(mode="json"),
    }
    # One append combines receipt and full bound report so finalization cannot leave a partial
    # two-file identity. A repeated finalization refuses to overwrite this record.
    write_private_file(checked_path(root), "acceptance.json", canonical_json(result))
    return result
