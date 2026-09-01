"""Strict local aggregate for three finalized weekly V2 article handoffs."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional local UI copy.

from __future__ import annotations

import json
import shutil
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, cast
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from app.application.services.official_account_editor_handoff import (
    _deterministic_zip,
    _image_metadata,
)
from app.application.services.official_account_editor_handoff_v2 import EditorHandoffV2Artifact
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WEEKLY_EDITION_SELECTION_VERSION,
    WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION,
    WEEKLY_HOMEPAGE_OPERATOR_STATE_VERSION,
    WeeklyArticleRole,
    WeeklyArticleSelection,
    WeeklyEditionSchedule,
    WeeklyEditionSelection,
    WeeklyHomepageOperatorState,
    initial_weekly_homepage_operator_state,
    weekly_homepage_display_policy,
    weekly_homepage_operator_state_projection,
)

WEEKLY_EDITION_BUNDLE_VERSION: Final = "official-account-weekly-edition-bundle-v2"
WEEKLY_EDITION_MANIFEST_VERSION: Final = "official-account-weekly-edition-manifest-v3"
WEEKLY_EDITION_INDEX_VERSION: Final = "official-account-weekly-edition-index-v2"
WEEKLY_HOMEPAGE_PRESENTATION_VERSION: Final = "official-account-weekly-homepage-presentation-v1"
WEEKLY_OPERATOR_CHECKLIST_VERSION: Final = (
    "official-account-weekly-operator-publication-checklist-v1"
)
WEEKLY_OPERATOR_STATE_SIDECAR_VERSION: Final = (
    "official-account-weekly-homepage-operator-state-sidecar-v1"
)
WEEKLY_VISUAL_DISTINCTNESS_VERSION: Final = "official-account-weekly-role-visual-distinctness-v1"
WEEKLY_LIVE_ACQUISITION_AUDIT_VERSION: Final = "official-account-weekly-live-acquisition-audit-v2"
WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION: Final = "official-account-weekly-live-acquisition-audit-v3"
_CHILD_BUNDLE_VERSION: Final = "official-account-editor-handoff-bundle-v2"
_MAX_CHILD_FILE_BYTES: Final = 20 * 1024 * 1024
_MAX_CHILD_TOTAL_BYTES: Final = 100 * 1024 * 1024
_MAX_WEEKLY_EDITION_TOTAL_BYTES: Final = 512 * 1024 * 1024
WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED: Final = "weekly_edition_live_provenance_required"
_LIVE_FIXTURE_TRUTHS: Final = frozenset(
    {
        "explicit_live_opt_in_three_distinct_acquired_sources",
        "explicit_live_opt_in_one_theme_three_multi_source_clusters",
    }
)


class WeeklyEditionLiveProvenanceError(ValueError):
    """Stable rejection used when an aggregate cannot prove live acquisition."""

    code: Final = WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED


@dataclass(frozen=True, slots=True)
class _LoadedSelectedWeeklyBinding:
    role: WeeklyArticleRole
    event_id: UUID
    event_version_id: UUID
    organization_type: str
    source_metadata_fingerprint: str


@dataclass(frozen=True, slots=True)
class _LoadedWeeklySelectionBindings:
    selected: tuple[
        _LoadedSelectedWeeklyBinding,
        _LoadedSelectedWeeklyBinding,
        _LoadedSelectedWeeklyBinding,
    ]


@dataclass(frozen=True, slots=True)
class FinalizedWeeklyChild:
    role: WeeklyArticleRole
    source_directory_name: str
    title: str
    run_id: UUID
    article_fingerprint: str
    content_fingerprint: str
    artifact_fingerprint: str
    body_sha256: str
    child_zip_filename: str
    child_zip_sha256: str
    files: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class WeeklyChildBinding:
    """Explicit persisted selected-event to finalized-child lineage projection."""

    role: WeeklyArticleRole
    event_id: UUID
    event_version_id: UUID
    run_id: UUID
    article_fingerprint: str
    content_fingerprint: str
    artifact_fingerprint: str
    child_zip_sha256: str
    binding_fingerprint: str


@dataclass(frozen=True, slots=True)
class WeeklyEditionArtifact:
    week_start: str
    batch_fingerprint: str
    selection_fingerprint: str
    children: tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild]
    homepage_operator_state: WeeklyHomepageOperatorState
    files: Mapping[str, bytes]
    zip_bytes: bytes
    zip_sha256: str
    bundle_filename: str


@dataclass(frozen=True, slots=True)
class FinalizedWeeklyEdition:
    """Runtime-only, byte-validated view of one live weekly aggregate."""

    directory: Path = dataclass_field(repr=False)
    week_start: str
    batch_fingerprint: str
    selection_fingerprint: str
    live_acquisition_audit_version: str
    children: tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild]
    files: Mapping[str, bytes] = dataclass_field(repr=False)
    zip_bytes: bytes = dataclass_field(repr=False)
    zip_sha256: str
    bundle_filename: str


def load_finalized_v2_child(
    directory: Path,
    *,
    role: WeeklyArticleRole,
) -> FinalizedWeeklyChild:
    """Load a complete child directory without trusting paths, hashes or ZIP bytes."""

    root = directory.expanduser().resolve(strict=True)
    if not root.is_dir() or directory.is_symlink() or _path_has_symlink_component(directory):
        raise ValueError("weekly child directory must be a real non-symlink directory")
    manifest_path = root / "manifest.json"
    manifest_bytes = _read_regular_file(manifest_path)
    manifest = _json_object(manifest_bytes, label="weekly child manifest")
    if manifest.get("bundle_version") != _CHILD_BUNDLE_VERSION:
        raise ValueError("weekly child bundle version is unsupported")
    if not (
        manifest.get("simulation") is True
        and manifest.get("local_only") is True
        and manifest.get("copy_ready") is True
        and manifest.get("published") is False
    ):
        raise ValueError("weekly child is not a finalized local-only unpublished handoff")

    artifact_fingerprint = _sha_value(manifest.get("artifact_fingerprint"), "artifact")
    if manifest.get("fingerprint") != artifact_fingerprint:
        raise ValueError("weekly child artifact fingerprint projection changed")
    content_fingerprint = _sha_value(manifest.get("content_fingerprint"), "content")
    run_id = UUID(_string_value(manifest.get("run_id"), "run_id"))
    release = _mapping_value(manifest.get("release"), "release")
    if (
        release.get("policy") != "quality_auto"
        or release.get("decision") != "released"
        or release.get("kind") not in {"machine", "manual"}
    ):
        raise ValueError("weekly child must have a truthful quality_auto release")
    mobile = _mapping_value(manifest.get("mobile_validation"), "mobile_validation")
    if (
        mobile.get("status") != "passed"
        or mobile.get("content_fingerprint") != content_fingerprint
        or mobile.get("external_requests") != 0
        or mobile.get("copy_root_matches_body") is not True
        or mobile.get("viewports") != [320, 430]
    ):
        raise ValueError("weekly child mobile validation is incomplete")
    lineage = _mapping_value(manifest.get("lineage"), "lineage")
    body_sha256 = _sha_value(lineage.get("body_sha256"), "body")
    article_fingerprint = _sha_value(
        lineage.get("article_content_fingerprint"),
        "article",
    )
    if mobile.get("body_sha256") != body_sha256:
        raise ValueError("weekly child mobile body binding changed")

    projections = manifest.get("files")
    if not isinstance(projections, list) or not projections:
        raise ValueError("weekly child manifest files are incomplete")
    expected_paths: set[str] = set()
    child_files: dict[str, bytes] = {}
    total_bytes = len(manifest_bytes)
    for raw_projection in projections:
        projection = _mapping_value(raw_projection, "file projection")
        relative = _safe_relative(_string_value(projection.get("path"), "file path"))
        if relative in expected_paths or relative == "manifest.json":
            raise ValueError("weekly child manifest paths must be unique")
        expected_paths.add(relative)
        body = _read_regular_file(root / relative)
        total_bytes += len(body)
        if len(body) > _MAX_CHILD_FILE_BYTES or total_bytes > _MAX_CHILD_TOTAL_BYTES:
            raise ValueError("weekly child files exceed the local aggregate bound")
        if projection.get("byte_size") != len(body):
            raise ValueError("weekly child file size changed")
        if projection.get("sha256") != sha256(body).hexdigest():
            raise ValueError("weekly child file checksum changed")
        child_files[relative] = body

    required = {
        "article-body.html",
        "preview.html",
        "article.json",
        "release.json",
        "preflight.json",
        "mobile-validation.json",
    }
    if not required.issubset(expected_paths):
        raise ValueError("weekly child required files are incomplete")
    article = _json_object(child_files["article.json"], label="weekly child article")
    title = _string_value(article.get("title"), "article title")
    if article.get("content_fingerprint") != article_fingerprint:
        raise ValueError("weekly child Article identity changed")
    if sha256(child_files["article-body.html"]).hexdigest() != body_sha256:
        raise ValueError("weekly child rendered body changed")
    preflight = _json_object(child_files["preflight.json"], label="weekly child preflight")
    if preflight.get("passed") is not True or preflight.get("blocking_codes") != []:
        raise ValueError("weekly child preflight did not pass")
    release_file = _json_object(child_files["release.json"], label="weekly child release")
    if release_file != release:
        raise ValueError("weekly child release projections disagree")
    mobile_file = _json_object(
        child_files["mobile-validation.json"],
        label="weekly child mobile validation",
    )
    if mobile_file != mobile:
        raise ValueError("weekly child mobile projections disagree")

    child_zip_filename = f"wechat-editor-handoff-v2-{artifact_fingerprint[:16]}.zip"
    child_zip = _read_regular_file(root / child_zip_filename)
    _verify_child_zip(
        child_zip,
        archive_root=child_zip_filename.removesuffix(".zip"),
        files={**child_files, "manifest.json": manifest_bytes},
    )
    declared = expected_paths | {"manifest.json", child_zip_filename}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != declared:
        raise ValueError("weekly child directory contains undeclared files")
    child_files["manifest.json"] = manifest_bytes
    child_files[child_zip_filename] = child_zip
    return FinalizedWeeklyChild(
        role=role,
        source_directory_name=root.name,
        title=title,
        run_id=run_id,
        article_fingerprint=article_fingerprint,
        content_fingerprint=content_fingerprint,
        artifact_fingerprint=artifact_fingerprint,
        body_sha256=body_sha256,
        child_zip_filename=child_zip_filename,
        child_zip_sha256=sha256(child_zip).hexdigest(),
        files=MappingProxyType(child_files),
    )


def load_finalized_weekly_edition(directory: Path) -> FinalizedWeeklyEdition:
    """Load one immutable live weekly aggregate without trusting repeated projections."""

    root = directory.expanduser().resolve(strict=True)
    if not root.is_dir() or directory.is_symlink() or _path_has_symlink_component(directory):
        raise ValueError("weekly edition directory must be a real non-symlink directory")
    manifest_bytes = _read_bounded_regular_file(root / "manifest.json")
    manifest = _json_object(manifest_bytes, label="weekly edition manifest")
    if (
        manifest.get("version") != WEEKLY_EDITION_MANIFEST_VERSION
        or manifest.get("bundle_version") != WEEKLY_EDITION_BUNDLE_VERSION
        or manifest.get("article_count") != 3
        or manifest.get("simulation") is not True
        or manifest.get("local_only") is not True
        or manifest.get("published") is not False
        or manifest.get("social_delivery_calls") != 0
    ):
        raise ValueError("weekly edition manifest identity changed")

    fixture_truth = manifest.get("fixture_truth")
    live_version = manifest.get("live_acquisition_audit_version")
    if fixture_truth not in _LIVE_FIXTURE_TRUTHS or live_version not in {
        WEEKLY_LIVE_ACQUISITION_AUDIT_VERSION,
        WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION,
    }:
        raise WeeklyEditionLiveProvenanceError(
            "weekly edition requires validated live-acquisition provenance"
        )

    projections = manifest.get("files")
    if not isinstance(projections, list) or not projections:
        raise ValueError("weekly edition manifest files are incomplete")
    projected_paths: set[str] = set()
    files: dict[str, bytes] = {}
    total_bytes = len(manifest_bytes)
    for raw_projection in projections:
        projection = _mapping_value(raw_projection, "weekly edition file projection")
        relative = _safe_relative(_string_value(projection.get("path"), "file path"))
        if relative in projected_paths or relative == "manifest.json":
            raise ValueError("weekly edition manifest paths must be unique")
        projected_paths.add(relative)
        body = _read_bounded_regular_file(root / relative)
        total_bytes += len(body)
        if total_bytes > _MAX_WEEKLY_EDITION_TOTAL_BYTES:
            raise ValueError("weekly edition files exceed the aggregate bound")
        if projection.get("byte_size") != len(body):
            raise ValueError("weekly edition file size changed")
        if projection.get("sha256") != sha256(body).hexdigest():
            raise ValueError("weekly edition file checksum changed")
        files[relative] = body

    required_paths = {
        "README.md",
        "homepage-operator-initial-state.json",
        "index.html",
        "live-acquisition.json",
        "operator-publication-checklist.json",
        "operator-publication-checklist.md",
        "weekly-index.json",
    }
    if not required_paths.issubset(projected_paths):
        raise WeeklyEditionLiveProvenanceError(
            "weekly edition live-acquisition provenance is incomplete"
        )
    index = _json_object(files["weekly-index.json"], label="weekly edition index")
    if (
        index.get("version") != WEEKLY_EDITION_INDEX_VERSION
        or index.get("article_count") != 3
        or index.get("simulation") is not True
        or index.get("local_only") is not True
        or index.get("published") is not False
        or index.get("live_acquisition_audit_path") != "live-acquisition.json"
        or index.get("live_acquisition_audit_version") != live_version
        or index.get("fixture_truth") != fixture_truth
    ):
        raise WeeklyEditionLiveProvenanceError(
            "weekly edition index live-acquisition provenance changed"
        )
    try:
        live_audit = _json_object(
            files["live-acquisition.json"],
            label="weekly live acquisition audit",
        )
        validated_audit_bytes = _validated_live_acquisition_audit(live_audit)
    except ValueError as exc:
        raise WeeklyEditionLiveProvenanceError(
            "weekly edition live-acquisition provenance is invalid"
        ) from exc
    if (
        validated_audit_bytes != files["live-acquisition.json"]
        or live_audit.get("version") != live_version
    ):
        raise WeeklyEditionLiveProvenanceError("weekly edition live-acquisition bytes changed")

    batch_fingerprint = _sha_value(manifest.get("batch_fingerprint"), "batch")
    selection_fingerprint = _sha_value(
        manifest.get("selection_fingerprint"),
        "selection",
    )
    week_start = _string_value(manifest.get("week_start"), "week_start")
    try:
        parsed_week_start = date.fromisoformat(week_start)
    except ValueError as exc:
        raise ValueError("weekly edition week_start is invalid") from exc
    if parsed_week_start.weekday() != 0:
        raise ValueError("weekly edition week_start must be a Monday")
    timezone = _string_value(manifest.get("timezone"), "timezone")
    schedule = WeeklyEditionSchedule()
    if (
        timezone != schedule.timezone
        or index.get("week_start") != week_start
        or index.get("timezone") != timezone
        or index.get("selection_policy_version") != WEEKLY_EDITION_SELECTION_VERSION
        or index.get("selection_fingerprint") != selection_fingerprint
        or index.get("schedule") != schedule.as_metadata()
        or index.get("batch_fingerprint") != batch_fingerprint
    ):
        raise ValueError("weekly edition index identity changed")

    manifest_rows = manifest.get("children")
    index_rows = index.get("articles")
    if (
        not isinstance(manifest_rows, list)
        or not isinstance(index_rows, list)
        or len(manifest_rows) != 3
        or manifest_rows != index_rows
    ):
        raise ValueError("weekly edition child projections changed")
    children: list[FinalizedWeeklyChild] = []
    binding_fingerprints: list[str] = []
    for ordinal, (role_value, raw_row) in enumerate(
        zip(WEEKLY_EDITION_ROLE_ORDER, index_rows, strict=True),
        start=1,
    ):
        row = _mapping_value(raw_row, "weekly edition child row")
        role = WeeklyArticleRole(role_value)
        prefix = f"articles/{ordinal:02d}-{role.value}"
        child = load_finalized_v2_child(root / prefix, role=role)
        if (
            row.get("ordinal") != ordinal
            or row.get("role") != role.value
            or row.get("title") != child.title
            or row.get("run_id") != str(child.run_id)
            or row.get("article_fingerprint") != child.article_fingerprint
            or row.get("content_fingerprint") != child.content_fingerprint
            or row.get("artifact_fingerprint") != child.artifact_fingerprint
            or row.get("child_zip_filename") != child.child_zip_filename
            or row.get("child_zip_sha256") != child.child_zip_sha256
            or row.get("preview_path") != f"{prefix}/preview.html"
            or row.get("body_path") != f"{prefix}/article-body.html"
            or row.get("homepage_display")
            != _homepage_display_projection(child=child, prefix=prefix)
        ):
            raise ValueError("weekly edition child identity changed")
        event_id = UUID(_string_value(row.get("event_id"), "event_id"))
        event_version_id = UUID(_string_value(row.get("event_version_id"), "event_version_id"))
        binding_fingerprint = _fingerprint(
            "official-account-weekly-child-binding-v1",
            role.value,
            str(event_id),
            str(event_version_id),
            str(child.run_id),
            child.article_fingerprint,
            child.content_fingerprint,
            child.artifact_fingerprint,
            child.child_zip_sha256,
        )
        if row.get("child_binding_fingerprint") != binding_fingerprint:
            raise ValueError("weekly edition child binding changed")
        children.append(child)
        binding_fingerprints.append(binding_fingerprint)

    typed_children = cast(
        tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild],
        tuple(children),
    )
    try:
        audit_rows = live_audit.get("articles")
        if not isinstance(audit_rows, list) or len(audit_rows) != 3:
            raise ValueError("weekly live acquisition binding rows changed")
        loaded_bindings: list[_LoadedSelectedWeeklyBinding] = []
        for role_value, raw_index_row, raw_audit_row in zip(
            WEEKLY_EDITION_ROLE_ORDER,
            index_rows,
            audit_rows,
            strict=True,
        ):
            index_row = _mapping_value(raw_index_row, "weekly edition child row")
            audit_row = _mapping_value(raw_audit_row, "weekly live acquisition row")
            event_id = UUID(_string_value(index_row.get("event_id"), "event_id"))
            event_version_id = UUID(
                _string_value(index_row.get("event_version_id"), "event_version_id")
            )
            if (
                audit_row.get("role") != role_value
                or audit_row.get("event_id") != str(event_id)
                or audit_row.get("event_version_id") != str(event_version_id)
                or audit_row.get("organization_type") != index_row.get("organization_type")
            ):
                raise ValueError("weekly live acquisition selected identity changed")
            loaded_bindings.append(
                _LoadedSelectedWeeklyBinding(
                    role=WeeklyArticleRole(role_value),
                    event_id=event_id,
                    event_version_id=event_version_id,
                    organization_type=_string_value(
                        index_row.get("organization_type"),
                        "organization_type",
                    ),
                    source_metadata_fingerprint=_sha_value(
                        audit_row.get("source_metadata_fingerprint"),
                        "source metadata",
                    ),
                )
            )
        _validate_live_acquisition_bindings(
            live_audit,
            selection=_LoadedWeeklySelectionBindings(
                selected=cast(
                    tuple[
                        _LoadedSelectedWeeklyBinding,
                        _LoadedSelectedWeeklyBinding,
                        _LoadedSelectedWeeklyBinding,
                    ],
                    tuple(loaded_bindings),
                )
            ),
            children=typed_children,
        )
    except ValueError as exc:
        raise WeeklyEditionLiveProvenanceError(
            "weekly edition live-acquisition bindings changed"
        ) from exc

    expected_batch_fingerprint = _fingerprint(
        WEEKLY_EDITION_BUNDLE_VERSION,
        WEEKLY_EDITION_MANIFEST_VERSION,
        WEEKLY_EDITION_INDEX_VERSION,
        WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION,
        WEEKLY_HOMEPAGE_PRESENTATION_VERSION,
        WEEKLY_HOMEPAGE_OPERATOR_STATE_VERSION,
        WEEKLY_OPERATOR_CHECKLIST_VERSION,
        WEEKLY_VISUAL_DISTINCTNESS_VERSION,
        week_start,
        timezone,
        selection_fingerprint,
        schedule.fingerprint,
        tuple(binding_fingerprints),
        tuple(
            (
                child.role.value,
                str(child.run_id),
                child.article_fingerprint,
                child.content_fingerprint,
                child.artifact_fingerprint,
                child.child_zip_sha256,
            )
            for child in typed_children
        ),
        live_version,
        sha256(validated_audit_bytes).hexdigest(),
    )
    if expected_batch_fingerprint != batch_fingerprint:
        raise ValueError("weekly edition batch fingerprint changed")
    expected_operator_state = weekly_homepage_operator_state_projection(
        initial_weekly_homepage_operator_state(
            batch_fingerprint=batch_fingerprint,
            official_article_fingerprint=typed_children[0].article_fingerprint,
        )
    )
    if (
        manifest.get("homepage_operator_initial_state") != expected_operator_state
        or index.get("homepage_operator_state") != expected_operator_state
        or manifest.get("external_calls") != live_audit.get("external_calls")
        or index.get("external_calls") != live_audit.get("external_calls")
    ):
        raise ValueError("weekly edition aggregate truth changed")

    bundle_filename = f"official-account-weekly-edition-{batch_fingerprint[:16]}.zip"
    zip_bytes = _read_bounded_regular_file(root / bundle_filename)
    total_bytes += len(zip_bytes)
    if total_bytes > _MAX_WEEKLY_EDITION_TOTAL_BYTES:
        raise ValueError("weekly edition files exceed the aggregate bound")
    files["manifest.json"] = manifest_bytes
    _verify_child_zip(
        zip_bytes,
        archive_root=bundle_filename.removesuffix(".zip"),
        files=files,
    )
    declared = projected_paths | {"manifest.json", bundle_filename}
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("weekly edition contains an unsafe filesystem entry")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != declared:
        raise ValueError("weekly edition directory contains undeclared files")
    return FinalizedWeeklyEdition(
        directory=root,
        week_start=week_start,
        batch_fingerprint=batch_fingerprint,
        selection_fingerprint=selection_fingerprint,
        live_acquisition_audit_version=live_version,
        children=typed_children,
        files=MappingProxyType(files),
        zip_bytes=zip_bytes,
        zip_sha256=sha256(zip_bytes).hexdigest(),
        bundle_filename=bundle_filename,
    )


def finalized_v2_child_from_artifact(
    artifact: EditorHandoffV2Artifact,
    *,
    role: WeeklyArticleRole,
) -> FinalizedWeeklyChild:
    """Strict in-memory adapter for an already built V2 artifact."""

    if artifact.mobile_validation.status != "passed":
        raise ValueError("weekly child artifact mobile validation must be passed")
    manifest_bytes = artifact.files["manifest.json"]
    manifest = _json_object(manifest_bytes, label="weekly child manifest")
    if (
        manifest.get("bundle_version") != _CHILD_BUNDLE_VERSION
        or manifest.get("simulation") is not True
        or manifest.get("local_only") is not True
        or manifest.get("published") is not False
        or manifest.get("copy_ready") is not True
    ):
        raise ValueError("weekly child artifact truth changed")
    projections = manifest.get("files")
    if not isinstance(projections, list):
        raise ValueError("weekly child artifact manifest files are invalid")
    expected = set(artifact.files) - {"manifest.json"}
    projected: set[str] = set()
    for raw_projection in projections:
        projection = _mapping_value(raw_projection, "file projection")
        relative = _safe_relative(_string_value(projection.get("path"), "file path"))
        if relative in projected or relative not in artifact.files:
            raise ValueError("weekly child artifact file projection changed")
        body = artifact.files[relative]
        if (
            projection.get("byte_size") != len(body)
            or projection.get("sha256") != sha256(body).hexdigest()
        ):
            raise ValueError("weekly child artifact file integrity changed")
        projected.add(relative)
    if projected != expected:
        raise ValueError("weekly child artifact manifest is incomplete")
    if sha256(artifact.zip_bytes).hexdigest() != artifact.zip_sha256:
        raise ValueError("weekly child artifact ZIP checksum changed")
    _verify_child_zip(
        artifact.zip_bytes,
        archive_root=artifact.bundle_filename.removesuffix(".zip"),
        files=dict(artifact.files),
    )
    article = _json_object(artifact.files["article.json"], label="weekly child article")
    return FinalizedWeeklyChild(
        role=role,
        source_directory_name=f"wechat-editor-handoff-v2-{artifact.artifact_fingerprint[:16]}",
        title=_string_value(article.get("title"), "article title"),
        run_id=artifact.run_id,
        article_fingerprint=_sha_value(
            _mapping_value(manifest.get("lineage"), "lineage").get("article_content_fingerprint"),
            "article",
        ),
        content_fingerprint=artifact.content_fingerprint,
        artifact_fingerprint=artifact.artifact_fingerprint,
        body_sha256=sha256(artifact.body_html).hexdigest(),
        child_zip_filename=artifact.bundle_filename,
        child_zip_sha256=artifact.zip_sha256,
        files=MappingProxyType({**artifact.files, artifact.bundle_filename: artifact.zip_bytes}),
    )


def bind_weekly_child(
    *,
    selected: WeeklyArticleSelection,
    child: FinalizedWeeklyChild,
) -> WeeklyChildBinding:
    if selected.role is not child.role:
        raise ValueError("weekly selected event and child role disagree")
    binding_fingerprint = _fingerprint(
        "official-account-weekly-child-binding-v1",
        child.role.value,
        str(selected.event_id),
        str(selected.event_version_id),
        str(child.run_id),
        child.article_fingerprint,
        child.content_fingerprint,
        child.artifact_fingerprint,
        child.child_zip_sha256,
    )
    return WeeklyChildBinding(
        role=child.role,
        event_id=selected.event_id,
        event_version_id=selected.event_version_id,
        run_id=child.run_id,
        article_fingerprint=child.article_fingerprint,
        content_fingerprint=child.content_fingerprint,
        artifact_fingerprint=child.artifact_fingerprint,
        child_zip_sha256=child.child_zip_sha256,
        binding_fingerprint=binding_fingerprint,
    )


def build_weekly_edition_artifact(
    *,
    selection: WeeklyEditionSelection,
    schedule: WeeklyEditionSchedule,
    children: tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild],
    bindings: tuple[WeeklyChildBinding, WeeklyChildBinding, WeeklyChildBinding],
    live_acquisition_audit: Mapping[str, object] | None = None,
) -> WeeklyEditionArtifact:
    if selection.schedule_fingerprint != schedule.fingerprint:
        raise ValueError("weekly edition schedule binding changed")
    if tuple(item.role.value for item in children) != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("weekly edition child role order changed")
    if tuple(item.role.value for item in bindings) != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("weekly edition child binding role order changed")
    identity_sets = (
        {item.run_id for item in children},
        {item.article_fingerprint for item in children},
        {item.content_fingerprint for item in children},
        {item.artifact_fingerprint for item in children},
        {item.child_zip_sha256 for item in children},
        {item.body_sha256 for item in children},
        {item.title for item in children},
    )
    if any(len(values) != 3 for values in identity_sets):
        raise ValueError(
            "weekly edition child Article/run/body/artifact/ZIP identities must differ"
        )
    _validate_role_visual_distinctness(children)
    for selected, child, binding in zip(selection.selected, children, bindings, strict=True):
        if selected.role is not child.role:
            raise ValueError("weekly edition selection and child roles disagree")
        expected_binding = bind_weekly_child(selected=selected, child=child)
        if binding != expected_binding:
            raise ValueError("weekly edition selected-event child binding changed")

    live_audit_bytes = (
        _validated_live_acquisition_audit(live_acquisition_audit)
        if live_acquisition_audit is not None
        else None
    )
    if live_acquisition_audit is not None:
        _validate_live_acquisition_bindings(
            live_acquisition_audit,
            selection=selection,
            children=children,
        )
    live_audit_projection = (
        _json_object(live_audit_bytes, label="weekly live acquisition audit")
        if live_audit_bytes is not None
        else None
    )
    batch_identity: tuple[object, ...] = (
        WEEKLY_EDITION_BUNDLE_VERSION,
        WEEKLY_EDITION_MANIFEST_VERSION,
        WEEKLY_EDITION_INDEX_VERSION,
        WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION,
        WEEKLY_HOMEPAGE_PRESENTATION_VERSION,
        WEEKLY_HOMEPAGE_OPERATOR_STATE_VERSION,
        WEEKLY_OPERATOR_CHECKLIST_VERSION,
        WEEKLY_VISUAL_DISTINCTNESS_VERSION,
        selection.week_start.isoformat(),
        selection.timezone,
        selection.fingerprint,
        schedule.fingerprint,
        tuple(item.binding_fingerprint for item in bindings),
        tuple(
            (
                item.role.value,
                str(item.run_id),
                item.article_fingerprint,
                item.content_fingerprint,
                item.artifact_fingerprint,
                item.child_zip_sha256,
            )
            for item in children
        ),
    )
    if live_audit_bytes is not None:
        batch_identity += (
            cast(Mapping[str, object], live_audit_projection)["version"],
            sha256(live_audit_bytes).hexdigest(),
        )
    batch_fingerprint = _fingerprint(*batch_identity)
    article_rows: list[dict[str, object]] = []
    files: dict[str, bytes] = {}
    for selected, child, binding in zip(selection.selected, children, bindings, strict=True):
        prefix = f"articles/{child.role.ordinal:02d}-{child.role.value}"
        for relative, body in child.files.items():
            files[f"{prefix}/{_safe_relative(relative)}"] = body
        homepage_display = _homepage_display_projection(child=child, prefix=prefix)
        article_rows.append(
            {
                "ordinal": child.role.ordinal,
                "role": child.role.value,
                "title": child.title,
                "event_id": str(selected.event_id),
                "event_version_id": str(selected.event_version_id),
                "selection_reason": selected.selection_reason.value,
                "affinity_reasons": list(selected.affinity_reasons),
                "official_authority": selected.official_authority,
                "organization_type": selected.organization_type,
                "run_id": str(child.run_id),
                "article_fingerprint": child.article_fingerprint,
                "content_fingerprint": child.content_fingerprint,
                "artifact_fingerprint": child.artifact_fingerprint,
                "child_zip_filename": child.child_zip_filename,
                "child_zip_sha256": child.child_zip_sha256,
                "child_binding_fingerprint": binding.binding_fingerprint,
                "preview_path": f"{prefix}/preview.html",
                "body_path": f"{prefix}/article-body.html",
                "homepage_display": homepage_display,
            }
        )
        if (
            live_audit_projection is not None
            and live_audit_projection.get("version") == WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION
        ):
            audit_articles = cast(list[Mapping[str, object]], live_audit_projection["articles"])
            audit_article = audit_articles[child.role.ordinal - 1]
            article_rows[-1]["theme"] = live_audit_projection["theme"]
            article_rows[-1]["angle"] = audit_article["angle"]
            article_rows[-1]["source_cluster"] = _weekly_theme_source_cluster_projection(
                audit_article
            )
    homepage_operator_state = initial_weekly_homepage_operator_state(
        batch_fingerprint=batch_fingerprint,
        official_article_fingerprint=children[0].article_fingerprint,
    )
    homepage_operator_projection = weekly_homepage_operator_state_projection(
        homepage_operator_state
    )
    checklist_projection = _operator_publication_checklist(
        batch_fingerprint=batch_fingerprint,
        article_rows=article_rows,
        initial_state=homepage_operator_projection,
    )
    external_calls: dict[str, object]
    if live_audit_bytes is None:
        external_calls = {
            "news": 0,
            "model": 0,
            "embedding": 0,
            "image_generation": 0,
            "wechat": 0,
            "wecom": 0,
        }
        fixture_truth = "aggregate_consumed_frozen_finalized_children_only"
    else:
        audit_projection = cast(dict[str, object], live_audit_projection)
        external_calls = cast(dict[str, object], audit_projection["external_calls"])
        fixture_truth = (
            "explicit_live_opt_in_one_theme_three_multi_source_clusters"
            if audit_projection["version"] == WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION
            else "explicit_live_opt_in_three_distinct_acquired_sources"
        )
    index_projection = {
        "version": WEEKLY_EDITION_INDEX_VERSION,
        "batch_fingerprint": batch_fingerprint,
        "week_start": selection.week_start.isoformat(),
        "timezone": selection.timezone,
        "schedule": schedule.as_metadata(),
        "selection_policy_version": selection.policy_version,
        "selection_fingerprint": selection.fingerprint,
        "article_count": 3,
        "articles": article_rows,
        "homepage_display_policy_version": WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION,
        "homepage_presentation_version": WEEKLY_HOMEPAGE_PRESENTATION_VERSION,
        "homepage_operator_state": homepage_operator_projection,
        "visual_distinctness_version": WEEKLY_VISUAL_DISTINCTNESS_VERSION,
        "operator_publication_checklist_path": "operator-publication-checklist.md",
        "wechat_homepage_ui_owner": "wechat_homepage_system",
        "simulation": True,
        "local_only": True,
        "published": False,
        "external_calls": external_calls,
        "fixture_truth": fixture_truth,
    }
    if live_audit_bytes is not None:
        index_projection["live_acquisition_audit_path"] = "live-acquisition.json"
        index_projection["live_acquisition_audit_version"] = cast(
            Mapping[str, object], live_audit_projection
        )["version"]
        if (
            cast(Mapping[str, object], live_audit_projection)["version"]
            == WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION
        ):
            index_projection["theme"] = cast(Mapping[str, object], live_audit_projection)["theme"]
            index_projection["live_source_count"] = cast(
                Mapping[str, object], live_audit_projection
            )["source_count"]
        files["live-acquisition.json"] = live_audit_bytes
    files["homepage-operator-initial-state.json"] = _json_bytes(homepage_operator_projection)
    files["operator-publication-checklist.json"] = _json_bytes(checklist_projection)
    files["operator-publication-checklist.md"] = _operator_publication_checklist_markdown(
        checklist_projection
    ).encode("utf-8")
    files["weekly-index.json"] = _json_bytes(index_projection)
    files["index.html"] = _render_index(index_projection).encode("utf-8")
    files["README.md"] = _readme(index_projection).encode("utf-8")
    manifest = {
        "version": WEEKLY_EDITION_MANIFEST_VERSION,
        "bundle_version": WEEKLY_EDITION_BUNDLE_VERSION,
        "batch_fingerprint": batch_fingerprint,
        "week_start": selection.week_start.isoformat(),
        "timezone": selection.timezone,
        "article_count": 3,
        "selection_fingerprint": selection.fingerprint,
        "homepage_display_policy_version": WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION,
        "homepage_presentation_version": WEEKLY_HOMEPAGE_PRESENTATION_VERSION,
        "homepage_operator_initial_state": homepage_operator_projection,
        "visual_distinctness_version": WEEKLY_VISUAL_DISTINCTNESS_VERSION,
        "operator_publication_checklist": {
            "version": WEEKLY_OPERATOR_CHECKLIST_VERSION,
            "json_path": "operator-publication-checklist.json",
            "markdown_path": "operator-publication-checklist.md",
        },
        "wechat_homepage_ui_owner": "wechat_homepage_system",
        "simulation": True,
        "local_only": True,
        "published": False,
        "external_calls": external_calls,
        "fixture_truth": fixture_truth,
        "social_delivery_calls": 0,
        "children": article_rows,
        "files": [_file_projection(path, body) for path, body in sorted(files.items())],
        "archive": {
            "timestamp": "1980-01-01T00:00:00Z",
            "mode": "0644",
            "compression": "deflate-9",
        },
    }
    if live_audit_projection is not None:
        manifest["live_acquisition_audit_version"] = live_audit_projection["version"]
        if live_audit_projection["version"] == WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION:
            manifest["theme"] = live_audit_projection["theme"]
            manifest["live_source_count"] = live_audit_projection["source_count"]
    files["manifest.json"] = _json_bytes(manifest)
    archive_root = f"official-account-weekly-edition-{batch_fingerprint[:16]}"
    zip_bytes = _deterministic_zip(files, archive_root=archive_root)
    _verify_child_zip(zip_bytes, archive_root=archive_root, files=files)
    return WeeklyEditionArtifact(
        week_start=selection.week_start.isoformat(),
        batch_fingerprint=batch_fingerprint,
        selection_fingerprint=selection.fingerprint,
        children=children,
        homepage_operator_state=homepage_operator_state,
        files=MappingProxyType(files),
        zip_bytes=zip_bytes,
        zip_sha256=sha256(zip_bytes).hexdigest(),
        bundle_filename=f"{archive_root}.zip",
    )


def write_weekly_edition_artifact(
    artifact: WeeklyEditionArtifact,
    output_root: Path,
) -> Path:
    root = output_root.expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("weekly edition output cannot be a filesystem root")
    target = root / f"official-account-weekly-edition-{artifact.batch_fingerprint[:16]}"
    if target.exists() or target.is_symlink():
        raise FileExistsError("weekly edition destination already exists")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{target.name}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError("weekly edition temporary destination already exists")
    try:
        temporary.mkdir()
        for relative, body in artifact.files.items():
            path = temporary / _safe_relative(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        (temporary / artifact.bundle_filename).write_bytes(artifact.zip_bytes)
        temporary.rename(target)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return target


def build_weekly_homepage_operator_state_sidecar(
    state: WeeklyHomepageOperatorState,
) -> bytes:
    """Serialize an auditable post-export state without mutating the weekly batch."""

    return _json_bytes(
        {
            "version": WEEKLY_OPERATOR_STATE_SIDECAR_VERSION,
            "operator_state": weekly_homepage_operator_state_projection(state),
            "immutable_weekly_batch_unchanged": True,
            "wechat_homepage_ui_owner": "wechat_homepage_system",
            "wechat_calls": 0,
            "confirmation_source": "explicit_operator_events_only",
        }
    )


def write_weekly_homepage_operator_state_sidecar(
    state: WeeklyHomepageOperatorState,
    output_root: Path,
) -> Path:
    """Write a fresh sidecar; never rewrite the immutable edition directory."""

    root = output_root.expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("weekly homepage state output cannot be a filesystem root")
    if _path_is_within_weekly_batch(root):
        raise ValueError("weekly homepage state output must remain outside the immutable batch")
    root.mkdir(parents=True, exist_ok=True)
    target = root / (f"homepage-operator-state-{state.status.value}-{state.fingerprint[:16]}.json")
    with target.open("xb") as stream:
        stream.write(build_weekly_homepage_operator_state_sidecar(state))
    return target


def _validate_role_visual_distinctness(
    children: tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild],
) -> None:
    cover_hashes: list[str] = []
    cover_pixel_hashes: list[str] = []
    body_hash_sets: list[tuple[str, ...]] = []
    body_pixel_sets: list[tuple[str, ...]] = []
    all_body_hashes: list[str] = []
    all_body_pixels: list[str] = []
    for child in children:
        manifest = _json_object(child.files["manifest.json"], label="weekly child manifest")
        media = manifest.get("media")
        if not isinstance(media, list):
            raise ValueError("weekly child media projection is invalid")
        covers = [
            _mapping_value(item, "weekly child cover")
            for item in media
            if isinstance(item, Mapping) and item.get("role") == "cover"
        ]
        bodies = sorted(
            (
                _mapping_value(item, "weekly child body image")
                for item in media
                if isinstance(item, Mapping) and item.get("role") == "body"
            ),
            key=lambda item: _media_ordinal(item.get("ordinal")),
        )
        if len(covers) != 1 or len(bodies) != 3:
            raise ValueError("weekly child requires one cover and three body images")
        if tuple(item.get("ordinal") for item in bodies) != (0, 1, 2):
            raise ValueError("weekly child body image ordinals changed")

        cover_hash, cover_pixels, _cover_size = _validated_child_image(
            child=child,
            projection=covers[0],
            expected_role="cover",
        )
        cover_hashes.append(cover_hash)
        cover_pixel_hashes.append(cover_pixels)

        role_body_hashes: list[str] = []
        role_body_pixels: list[str] = []
        for body in bodies:
            body_hash, body_pixels, body_size = _validated_child_image(
                child=child,
                projection=body,
                expected_role="body",
            )
            if body_size != (1536, 1024):
                raise ValueError("weekly child body image profile changed")
            role_body_hashes.append(body_hash)
            role_body_pixels.append(body_pixels)
        if len(set(role_body_hashes)) != 3 or len(set(role_body_pixels)) != 3:
            raise ValueError("weekly child body images must be visibly distinct")
        body_hash_sets.append(tuple(role_body_hashes))
        body_pixel_sets.append(tuple(role_body_pixels))
        all_body_hashes.extend(role_body_hashes)
        all_body_pixels.extend(role_body_pixels)

    if len(set(cover_hashes)) != 3:
        raise ValueError("weekly edition role cover hashes must differ")
    if len(set(cover_pixel_hashes)) != 3:
        raise ValueError("weekly edition role cover pixels must differ")
    if len(set(body_hash_sets)) != 3:
        raise ValueError("weekly edition role body media sets must differ")
    if len(set(body_pixel_sets)) != 3:
        raise ValueError("weekly edition role body pixel sets must differ")
    if len(set(all_body_hashes)) != 9:
        raise ValueError("weekly edition body image hashes must all differ")
    if len(set(all_body_pixels)) != 9:
        raise ValueError("weekly edition body image pixels must all differ")


def _validated_child_image(
    *,
    child: FinalizedWeeklyChild,
    projection: Mapping[str, object],
    expected_role: str,
) -> tuple[str, str, tuple[int, int]]:
    if projection.get("role") != expected_role:
        raise ValueError("weekly child media role changed")
    path = _safe_relative(_string_value(projection.get("path"), "media path"))
    checksum = _sha_value(projection.get("sha256"), "media")
    body = child.files.get(path)
    if body is None or sha256(body).hexdigest() != checksum:
        raise ValueError("weekly child media bytes changed")
    if projection.get("byte_size") != len(body):
        raise ValueError("weekly child media size changed")
    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            actual_size = opened.size
            pixel_hash = sha256(opened.convert("RGB").tobytes()).hexdigest()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("weekly child media image bytes are invalid") from exc
    width = _positive_int(projection.get("width"), "media width")
    height = _positive_int(projection.get("height"), "media height")
    if actual_size != (width, height):
        raise ValueError("weekly child media dimensions changed")
    return checksum, pixel_hash, actual_size


def _homepage_display_projection(
    *,
    child: FinalizedWeeklyChild,
    prefix: str,
) -> dict[str, object]:
    manifest = _json_object(child.files["manifest.json"], label="weekly child manifest")
    media = manifest.get("media")
    if not isinstance(media, list):
        raise ValueError("weekly child media projection is invalid")
    covers = [
        _mapping_value(item, "weekly child cover")
        for item in media
        if isinstance(item, Mapping) and item.get("role") == "cover"
    ]
    if len(covers) != 1:
        raise ValueError("weekly child must expose exactly one cover")
    cover = covers[0]
    path = _safe_relative(_string_value(cover.get("path"), "cover path"))
    width = _positive_int(cover.get("width"), "cover width")
    height = _positive_int(cover.get("height"), "cover height")
    checksum = _sha_value(cover.get("sha256"), "cover")
    body = child.files.get(path)
    if body is None or sha256(body).hexdigest() != checksum:
        raise ValueError("weekly child cover bytes changed")
    if cover.get("byte_size") != len(body):
        raise ValueError("weekly child cover size changed")
    try:
        actual_width, actual_height, detected_media_type = _image_metadata(body)
    except (OSError, ValueError) as exc:
        raise ValueError("weekly child cover image bytes are invalid") from exc
    declared_media_type = _string_value(cover.get("media_type"), "cover media type")
    if (actual_width, actual_height) != (width, height):
        raise ValueError("weekly child cover dimensions changed")
    if declared_media_type != detected_media_type:
        raise ValueError("weekly child cover media type changed")
    expected_path = {
        "image/jpeg": "assets/cover-wide.jpg",
        "image/png": "assets/cover-wide.png",
        "image/webp": "assets/cover-wide.webp",
    }[detected_media_type]
    if path != expected_path:
        raise ValueError("weekly child cover path changed")
    if abs(actual_width / actual_height - 2.35) > 0.08:
        raise ValueError("weekly child cover no longer satisfies the V2 wide-cover profile")
    policy = weekly_homepage_display_policy(child.role)
    is_primary = child.role is WeeklyArticleRole.OFFICIAL_ANCHOR
    return {
        "policy_version": policy.policy_version,
        "display_intent": policy.display_intent.value,
        "homepage_pin_required": is_primary,
        "pin_control": "manual_mp_backend_only" if is_primary else "not_applicable",
        "cover": {
            "profile_version": "official-account-weekly-homepage-cover-source-v1",
            "purpose": policy.cover_purpose.value,
            "child_path": path,
            "aggregate_path": f"{prefix}/{path}",
            "sha256": checksum,
            "byte_size": len(body),
            "width": width,
            "height": height,
            "actual_aspect_ratio": f"{actual_width / actual_height:.6f}:1",
            "source_aspect_ratio_intent": policy.source_aspect_ratio_intent,
            "composition_guidance": (
                "wide_primary_subject_center_safe_for_system_crop"
                if is_primary
                else "thumbnail_subject_center_safe_for_system_crop"
            ),
            "wechat_system_crop_controlled": True,
        },
        "ui_truth": "intent_only_wechat_homepage_rendering_is_external",
    }


def _weekly_theme_source_cluster_projection(
    audit_article: Mapping[str, object],
) -> list[dict[str, object]]:
    sources = audit_article.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("weekly live theme source-cluster projection changed")
    projection: list[dict[str, object]] = []
    for raw_source in sources:
        source = _mapping_value(raw_source, "live theme source")
        images = source.get("images")
        if not isinstance(images, list) or len(images) != 1:
            raise ValueError("weekly live theme source image projection changed")
        image = _mapping_value(images[0], "live theme source image")
        projection.append(
            {
                "relation": source["relation"],
                "publisher": source["publisher"],
                "title": source["title"],
                "canonical_url": source["canonical_url"],
                "published_date": source["published_date"],
                "evidence_id": source["evidence_id"],
                "context_image_sha256": image["sha256"],
                "rights_status": image["rights_status"],
                "context_only_not_evidence": image["context_only_not_evidence"],
            }
        )
    return projection


def _operator_publication_checklist(
    *,
    batch_fingerprint: str,
    article_rows: list[dict[str, object]],
    initial_state: dict[str, object],
) -> dict[str, object]:
    official = article_rows[0]
    return {
        "version": WEEKLY_OPERATOR_CHECKLIST_VERSION,
        "batch_fingerprint": batch_fingerprint,
        "article_count": 3,
        "initial_status": initial_state["status"],
        "official_article": {
            "role": official["role"],
            "title": official["title"],
            "article_fingerprint": official["article_fingerprint"],
            "display_intent": cast(Mapping[str, object], official["homepage_display"])[
                "display_intent"
            ],
            "cover_purpose": cast(
                Mapping[str, object],
                cast(Mapping[str, object], official["homepage_display"])["cover"],
            )["purpose"],
            "preview_path": official["preview_path"],
        },
        "article_order": [item["role"] for item in article_rows],
        "steps": [
            {
                "ordinal": 1,
                "code": "review_three_local_articles",
                "instruction": "分别打开三篇独立预览，核对标题、正文、封面和证据边界。",
            },
            {
                "ordinal": 2,
                "code": "publish_three_articles_externally",
                "instruction": "在公众号后台分别发布三篇文章；本地工具不执行上传、草稿或发布。",
            },
            {
                "ordinal": 3,
                "code": "record_official_publication_confirmation",
                "instruction": (
                    "取得官方主推文章的 mp.weixin.qq.com 已发布链接后，记录显式 "
                    "publication_confirmed 事件，状态才可进入 awaiting_manual_pin。"
                ),
            },
            {
                "ordinal": 4,
                "code": "pin_official_article_in_mp_backend",
                "instruction": (
                    "公众号后台：群发功能 → 已发送 → 找到官方主推文章 → 更多 → 置顶到公众号主页。"
                ),
            },
            {
                "ordinal": 5,
                "code": "visually_verify_wechat_homepage",
                "instruction": (
                    "在公众号主页人工确认官方文章已显示为置顶卡片；微信负责实际样式和裁切。"
                ),
            },
            {
                "ordinal": 6,
                "code": "record_explicit_pin_confirmation",
                "instruction": (
                    "核对完成后记录显式 homepage_pin_confirmed 事件，状态才可进入 confirmed。"
                ),
            },
        ],
        "standard_articles": [
            {
                "role": item["role"],
                "title": item["title"],
                "display_intent": cast(Mapping[str, object], item["homepage_display"])[
                    "display_intent"
                ],
                "cover_purpose": cast(
                    Mapping[str, object],
                    cast(Mapping[str, object], item["homepage_display"])["cover"],
                )["purpose"],
                "homepage_pin_required": False,
            }
            for item in article_rows[1:]
        ],
        "prohibited_automation": [
            "wechat_public_or_private_pin_api",
            "mp_backend_browser_automation",
            "claiming_pin_success_from_local_state_without_operator_confirmation",
        ],
        "wechat_calls": 0,
        "wechat_homepage_ui_owner": "wechat_homepage_system",
    }


def _operator_publication_checklist_markdown(payload: Mapping[str, object]) -> str:
    official = cast(Mapping[str, object], payload["official_article"])
    standard = cast(list[Mapping[str, object]], payload["standard_articles"])
    steps = cast(list[Mapping[str, object]], payload["steps"])
    lines = [
        "# 公众号每周三篇发布与主页置顶清单",
        "",
        f"- 批次：`{payload['batch_fingerprint']}`",
        "- 文章数：`3`（三篇相互独立）",
        f"- 初始状态：`{payload['initial_status']}`",
        f"- 主页置顶候选：{official['title']}（`pinned_primary`）",
        f"- 官方文章封面用途：`{official['cover_purpose']}`",
        f"- 普通文章顺序：`{standard[0]['role']}` → `{standard[1]['role']}`",
        f"- 普通文章展示意图/封面用途：`standard` / `{standard[0]['cover_purpose']}`",
        "- 说明：主页大卡片、缩略图和裁切均由微信系统控制。",
        "",
        "## 操作步骤",
        "",
    ]
    lines.extend(f"{item['ordinal']}. {item['instruction']}" for item in steps)
    lines.extend(
        [
            "",
            "两篇 `standard` 文章无需主页置顶。不得使用私有接口或后台浏览器自动化。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_index(payload: Mapping[str, object]) -> str:
    articles = cast(list[Mapping[str, object]], payload["articles"])
    cards: list[str] = []
    labels = {
        "official_anchor": "官方主推",
        "industry_trend": "行业趋势",
        "application_case": "应用案例",
    }
    for item in articles:
        role = cast(str, item["role"])
        display = cast(Mapping[str, object], item["homepage_display"])
        cover = cast(Mapping[str, object], display["cover"])
        cover_path = escape(cast(str, cover["aggregate_path"]), quote=True)
        title = escape(cast(str, item["title"]))
        preview_path = escape(cast(str, item["preview_path"]), quote=True)
        label = escape(labels[role])
        source_cluster = item.get("source_cluster")
        source_summary = ""
        if isinstance(source_cluster, list):
            source_links: list[str] = []
            for raw_source in source_cluster:
                source = cast(Mapping[str, object], raw_source)
                relation = "主来源" if source["relation"] == "primary" else "补充来源"
                source_links.append(
                    f'<a href="{escape(cast(str, source["canonical_url"]), quote=True)}" '
                    'style="color:inherit;text-decoration:underline">'
                    f"{relation} · {escape(cast(str, source['publisher']))}</a>"
                )
            source_summary = (
                '<p style="margin:0 0 12px;font-size:12px;line-height:1.65;opacity:.9">'
                + " ｜ ".join(source_links)
                + "</p>"
            )
        if role == WeeklyArticleRole.OFFICIAL_ANCHOR.value:
            cards.append(
                '<article style="overflow:hidden;border:1px solid #c9dfeb;border-radius:20px;'
                'background:#0c4567;box-shadow:0 14px 34px rgba(15,57,89,.16)">'
                '<div style="position:relative;min-height:250px;background:#0c4567">'
                f'<img src="{cover_path}" alt="{title}封面" style="display:block;width:100%;'
                'height:100%;min-height:250px;object-fit:cover">'
                '<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
                "justify-content:flex-end;padding:24px;background:linear-gradient(180deg,"
                'rgba(3,32,50,.02) 26%,rgba(3,32,50,.92) 100%);box-sizing:border-box">'
                f'<p style="margin:0 0 8px;color:#8fe9dd;font-weight:800">{label} · '
                "置顶候选</p>"
                '<h2 style="margin:0 0 16px;color:#fff;font-size:25px;line-height:1.35">'
                f"{title}</h2>"
                + source_summary
                + f'<a href="{preview_path}" style="color:#fff;text-decoration:none;'
                'font-weight:800">'
                "打开独立预览 →</a></div></div>"
                '<p style="margin:0;padding:14px 20px;color:#d9f5f0;font-size:13px;'
                'line-height:1.6">'
                "展示意图 <strong>主页置顶候选</strong> · 封面用途 "
                "<strong>主页大卡片候选</strong>。发布后仍须在公众号后台人工置顶，"
                "实际主页样式与裁切由微信控制。</p></article>"
            )
        else:
            cards.append(
                '<article style="display:flex;gap:18px;align-items:center;border:1px solid #d9e6f2;'
                "border-radius:16px;padding:18px;background:#fff;box-shadow:0 8px 24px "
                'rgba(15,57,89,.08)"><div style="flex:1;min-width:0">'
                f'<p style="margin:0 0 8px;color:#176b87;font-weight:700">{label} · 普通卡片</p>'
                '<h2 style="margin:0 0 14px;color:#12344d;font-size:20px;line-height:1.45">'
                f"{title}</h2>"
                + source_summary
                + f'<a href="{preview_path}" style="color:#0b7fab;text-decoration:none;'
                'font-weight:700">'
                "打开独立预览 →</a>"
                '<p style="margin:10px 0 0;color:#62788a;font-size:12px;line-height:1.5">'
                "普通展示 · 主页缩略图候选</p></div>"
                f'<img src="{cover_path}" alt="{title}缩略封面" style="display:block;width:132px;'
                'height:94px;object-fit:cover;border-radius:12px;flex:none"></article>'
            )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>小赛 AI 每周三篇</title></head>"
        '<body style="margin:0;background:#f4f8fb;font-family:-apple-system,BlinkMacSystemFont,'
        'Segoe UI,PingFang SC,sans-serif;color:#12344d">'
        '<main style="max-width:760px;margin:0 auto;padding:32px 18px 56px">'
        '<header style="padding:28px;border-radius:20px;'
        'background:linear-gradient(135deg,#0b5f82,#17a4a4);color:#fff">'
        '<p style="margin:0 0 8px;font-weight:700">XIAOSAI WEEKLY · LOCAL EDITION</p>'
        f'<h1 style="margin:0;font-size:30px">{escape(cast(str, payload["week_start"]))}'
        " 每周三篇</h1>"
        + (
            '<p style="margin:10px 0 0;font-size:18px;font-weight:800;line-height:1.5">'
            f"本周主题：{escape(cast(str, payload['theme']))}</p>"
            if payload.get("theme") is not None
            else ""
        )
        + '<p style="margin:12px 0 0;line-height:1.7">'
        "三篇文章彼此独立；当前尚未发布，本页不执行发布或微信置顶。</p>"
        "</header>"
        '<p style="margin:16px 0 0;padding:14px 16px;border:1px solid #b9dfe0;border-radius:14px;'
        'background:#ecfafa;color:#15566b;line-height:1.65">官方文章已标记为 '
        "<strong>主页置顶候选</strong>，另外两篇为 <strong>普通文章</strong>。"
        "顺序固定为：官方主推 → 行业趋势 → 应用案例。"
        '<a href="operator-publication-checklist.md" style="margin-left:8px;color:#0b7fab;'
        'font-weight:800">查看发布与人工置顶清单 →</a></p>'
        '<section style="display:flex;flex-direction:column;gap:16px;margin-top:20px">'
        + "".join(cards)
        + "</section></main></body></html>"
    )


def _readme(payload: Mapping[str, object]) -> str:
    acquisition_line = (
        "- Aggregation performed zero news/model/embedding/image/WeChat/WeCom calls.\n"
        if payload["fixture_truth"] == "aggregate_consumed_frozen_finalized_children_only"
        else (
            "- This explicit live local run fetched the source pages and news-context images "
            "listed in `live-acquisition.json`; model/Embedding/image-generation/WeChat/WeCom "
            "calls remained zero.\n"
        )
    )
    return (
        "# Xiaosai weekly three-article local edition\n\n"
        f"- Week start: `{payload['week_start']}`\n"
        "- Article count: `3` (`official_anchor`, `industry_trend`, `application_case`)\n"
        "- Each child remains a complete, byte-preserved, finalized V2 handoff.\n"
        "- This aggregate is development-only, local-only and unpublished.\n"
        "- Initial homepage operator state: `not_published`.\n"
        "- `official_anchor` is a `pinned_primary` candidate; the other two are `standard`.\n"
        "- Cover purposes are `homepage_pinned_large_card_candidate` for the official article "
        "and `homepage_standard_thumbnail_candidate` for both standard articles.\n"
        "- Operator order is `official_anchor` -> `industry_trend` -> `application_case`, "
        "followed by the six explicit checklist steps.\n"
        "- WeChat owns the final homepage card rendering and cover crop.\n"
        "- Follow `operator-publication-checklist.md`; post-publication and pin confirmations "
        "must be explicit sidecar events.\n"
        + acquisition_line
        + "- `index.html` is navigation only; use each child `article-body.html` "
        "for WeChat editing.\n"
    )


def _validated_live_acquisition_audit(payload: Mapping[str, object]) -> bytes:
    if payload.get("version") == WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION:
        return _validated_live_theme_cluster_audit(payload)
    expected_fields = {
        "version",
        "mode",
        "selection_cutoff",
        "fetched_at",
        "article_count",
        "articles",
        "external_calls",
        "boundaries",
    }
    if set(payload) != expected_fields:
        raise ValueError("weekly live acquisition audit fields changed")
    if (
        payload.get("version") != WEEKLY_LIVE_ACQUISITION_AUDIT_VERSION
        or payload.get("mode") != "explicit_live_local_only"
        or payload.get("article_count") != 3
    ):
        raise ValueError("weekly live acquisition audit identity changed")
    rows = payload.get("articles")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly live acquisition audit requires exactly three articles")
    roles = [row.get("role") for row in rows if isinstance(row, Mapping)]
    if roles != list(WEEKLY_EDITION_ROLE_ORDER):
        raise ValueError("weekly live acquisition audit role order changed")
    article_fields = {
        "role",
        "source_key",
        "source_registry_version",
        "source_metadata_fingerprint",
        "publisher",
        "organization_type",
        "requested_url",
        "final_url",
        "canonical_url",
        "title",
        "published_at",
        "published_date",
        "page_media_type",
        "page_byte_size",
        "page_sha256",
        "page_fetched_at",
        "clean_text_byte_size",
        "clean_text_sha256",
        "evidence_id",
        "evidence_quote_sha256",
        "event_id",
        "event_version_id",
        "images",
    }
    image_fields = {
        "image_url",
        "source_page_url",
        "response_media_type",
        "byte_size",
        "sha256",
        "width",
        "height",
        "fetched_at",
        "caption",
        "credit",
        "rights_status",
        "context_only_not_evidence",
    }
    source_keys: list[str] = []
    publishers: list[str] = []
    titles: list[str] = []
    published_dates: list[date] = []
    urls: list[str] = []
    page_hashes: list[str] = []
    evidence_ids: list[UUID] = []
    event_ids: list[UUID] = []
    event_version_ids: list[UUID] = []
    image_hashes: list[str] = []
    image_count = 0
    for raw_row in rows:
        row = _mapping_value(raw_row, "live acquisition article")
        if set(row) != article_fields:
            raise ValueError("weekly live acquisition article fields changed")
        source_keys.append(_string_value(row.get("source_key"), "live source key"))
        publishers.append(_string_value(row.get("publisher"), "live publisher"))
        titles.append(_string_value(row.get("title"), "live title"))
        try:
            published_dates.append(
                date.fromisoformat(_string_value(row.get("published_date"), "live published date"))
            )
            published_at = datetime.fromisoformat(
                _string_value(row.get("published_at"), "live published_at")
            )
            page_fetched_at = datetime.fromisoformat(
                _string_value(row.get("page_fetched_at"), "live page fetched_at")
            )
        except ValueError as exc:
            raise ValueError("weekly live acquisition date projection is invalid") from exc
        if (
            published_at.tzinfo is None
            or page_fetched_at.tzinfo is None
            or row.get("page_media_type") != "text/html"
        ):
            raise ValueError("weekly live acquisition page projection is invalid")
        _positive_int(row.get("page_byte_size"), "live page byte size")
        _positive_int(row.get("clean_text_byte_size"), "live text byte size")
        requested_url = _string_value(row.get("requested_url"), "live requested URL")
        final_url = _string_value(row.get("final_url"), "live final URL")
        canonical_url = _string_value(row.get("canonical_url"), "live canonical URL")
        if requested_url != final_url or final_url != canonical_url:
            raise ValueError("weekly live acquisition URL projection changed")
        urls.append(canonical_url)
        page_hashes.append(_sha_value(row.get("page_sha256"), "live page"))
        _sha_value(row.get("source_metadata_fingerprint"), "live source metadata")
        _sha_value(row.get("clean_text_sha256"), "live clean text")
        _sha_value(row.get("evidence_quote_sha256"), "live evidence quote")
        try:
            evidence_ids.append(UUID(_string_value(row.get("evidence_id"), "live evidence")))
            event_ids.append(UUID(_string_value(row.get("event_id"), "live event")))
            event_version_ids.append(
                UUID(_string_value(row.get("event_version_id"), "live event version"))
            )
        except ValueError as exc:
            raise ValueError("weekly live acquisition UUID projection is invalid") from exc
        images = row.get("images")
        if not isinstance(images, list) or not 1 <= len(images) <= 2:
            raise ValueError("weekly live acquisition article image count changed")
        image_count += len(images)
        for raw_image in images:
            image = _mapping_value(raw_image, "live acquisition image")
            if set(image) != image_fields:
                raise ValueError("weekly live acquisition image fields changed")
            try:
                fetched_at = datetime.fromisoformat(
                    _string_value(image.get("fetched_at"), "live image fetched_at")
                )
            except ValueError as exc:
                raise ValueError("weekly live acquisition image fetched_at is invalid") from exc
            if (
                fetched_at.tzinfo is None
                or image.get("source_page_url") != canonical_url
                or image.get("response_media_type") not in {"image/jpeg", "image/png", "image/webp"}
                or image.get("rights_status") != "publish_permission_unverified"
                or image.get("context_only_not_evidence") is not True
            ):
                raise ValueError("weekly live acquisition image provenance changed")
            _string_value(image.get("image_url"), "live image URL")
            _positive_int(image.get("byte_size"), "live image byte size")
            _positive_int(image.get("width"), "live image width")
            _positive_int(image.get("height"), "live image height")
            _string_value(image.get("credit"), "live image credit")
            image_hashes.append(_sha_value(image.get("sha256"), "live image"))
    distinct_groups = (
        source_keys,
        publishers,
        titles,
        published_dates,
        urls,
        page_hashes,
        evidence_ids,
        event_ids,
        event_version_ids,
    )
    if any(len(set(values)) != 3 for values in distinct_groups):
        raise ValueError("weekly live acquisition source/event identities must be distinct")
    if len(image_hashes) != len(set(image_hashes)):
        raise ValueError("weekly live acquisition image identities must be distinct")
    official = _mapping_value(rows[0], "live official article")
    if official.get("organization_type") != "government":
        raise ValueError("weekly live official authority changed")
    calls = payload.get("external_calls")
    if not isinstance(calls, dict) or set(calls) != {
        "news",
        "source_pages",
        "news_images",
        "model",
        "embedding",
        "image_generation",
        "wechat",
        "wecom",
    }:
        raise ValueError("weekly live acquisition call counters changed")
    if (
        calls.get("source_pages") != 3
        or not isinstance(calls.get("news_images"), int)
        or cast(int, calls["news_images"]) < 3
        or calls.get("news_images") != image_count
        or calls.get("news") != cast(int, calls["source_pages"]) + cast(int, calls["news_images"])
        or any(
            calls.get(name) != 0
            for name in ("model", "embedding", "image_generation", "wechat", "wecom")
        )
    ):
        raise ValueError("weekly live acquisition call counters are not truthful")
    boundaries = payload.get("boundaries")
    if not isinstance(boundaries, dict) or boundaries != {
        "development_only": True,
        "local_only": True,
        "published": False,
        "news_images_context_only_not_evidence": True,
        "publish_permission_verified": False,
        "wechat_or_wecom_clients_constructed": False,
    }:
        raise ValueError("weekly live acquisition boundaries changed")
    return _json_bytes(payload)


def _validated_live_theme_cluster_audit(payload: Mapping[str, object]) -> bytes:
    if set(payload) != {
        "version",
        "mode",
        "selection_cutoff",
        "fetched_at",
        "theme",
        "article_count",
        "source_count",
        "articles",
        "external_calls",
        "boundaries",
    }:
        raise ValueError("weekly live theme acquisition audit fields changed")
    if (
        payload.get("version") != WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION
        or payload.get("mode") != "explicit_live_theme_clusters_local_only"
        or payload.get("article_count") != 3
        or payload.get("source_count") != 6
    ):
        raise ValueError("weekly live theme acquisition audit identity changed")
    _string_value(payload.get("theme"), "live weekly theme")
    for field in ("selection_cutoff", "fetched_at"):
        try:
            parsed = datetime.fromisoformat(_string_value(payload.get(field), field))
        except ValueError as exc:
            raise ValueError("weekly live theme audit timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("weekly live theme audit timestamp must be timezone-aware")
    rows = payload.get("articles")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly live theme audit requires exactly three article clusters")
    article_fields = {
        "role",
        "angle",
        "editorial_title",
        "event_id",
        "event_version_id",
        "organization_type",
        "source_metadata_fingerprint",
        "sources",
    }
    source_fields = {
        "relation",
        "owner_role",
        "source_key",
        "source_registry_version",
        "source_metadata_fingerprint",
        "publisher",
        "organization_type",
        "requested_url",
        "final_url",
        "canonical_url",
        "title",
        "published_at",
        "published_date",
        "page_media_type",
        "page_byte_size",
        "page_sha256",
        "page_fetched_at",
        "clean_text_byte_size",
        "clean_text_sha256",
        "evidence_id",
        "evidence_quote_sha256",
        "event_id",
        "event_version_id",
        "images",
    }
    image_fields = {
        "image_url",
        "source_page_url",
        "response_media_type",
        "byte_size",
        "sha256",
        "width",
        "height",
        "fetched_at",
        "caption",
        "credit",
        "rights_status",
        "context_only_not_evidence",
        "source_marks_preserved",
    }
    expected_angles = ("official_policy", "industry_method", "application_practice")
    canonical_urls: list[str] = []
    page_hashes: list[str] = []
    evidence_ids: list[UUID] = []
    event_ids: list[UUID] = []
    event_version_ids: list[UUID] = []
    image_hashes: list[str] = []
    for ordinal, raw_row in enumerate(rows):
        row = _mapping_value(raw_row, "live theme article")
        if set(row) != article_fields:
            raise ValueError("weekly live theme article fields changed")
        if (
            row.get("role") != WEEKLY_EDITION_ROLE_ORDER[ordinal]
            or row.get("angle") != expected_angles[ordinal]
        ):
            raise ValueError("weekly live theme role/angle order changed")
        _string_value(row.get("editorial_title"), "live theme editorial title")
        _sha_value(row.get("source_metadata_fingerprint"), "live theme source metadata")
        sources = row.get("sources")
        if not isinstance(sources, list) or len(sources) != 2:
            raise ValueError("weekly live theme cluster must contain two sources")
        for source_ordinal, raw_source in enumerate(sources):
            source = _mapping_value(raw_source, "live theme cluster source")
            if set(source) != source_fields:
                raise ValueError("weekly live theme source fields changed")
            expected_relation = "primary" if source_ordinal == 0 else "supporting"
            if (
                source.get("relation") != expected_relation
                or source.get("owner_role") != row.get("role")
                or source.get("page_media_type") != "text/html"
            ):
                raise ValueError("weekly live theme source ownership/relation changed")
            _string_value(source.get("source_key"), "live theme source key")
            _string_value(source.get("publisher"), "live theme publisher")
            _string_value(source.get("title"), "live theme source title")
            _sha_value(source.get("source_metadata_fingerprint"), "live theme source metadata")
            _sha_value(source.get("clean_text_sha256"), "live theme clean text")
            _sha_value(source.get("evidence_quote_sha256"), "live theme evidence quote")
            _positive_int(source.get("page_byte_size"), "live theme page byte size")
            _positive_int(source.get("clean_text_byte_size"), "live theme text byte size")
            requested = _string_value(source.get("requested_url"), "live theme requested URL")
            final = _string_value(source.get("final_url"), "live theme final URL")
            canonical = _string_value(source.get("canonical_url"), "live theme canonical URL")
            if requested != final or final != canonical:
                raise ValueError("weekly live theme source URL projection changed")
            canonical_urls.append(canonical)
            page_hashes.append(_sha_value(source.get("page_sha256"), "live theme page"))
            try:
                evidence_ids.append(
                    UUID(_string_value(source.get("evidence_id"), "live theme evidence"))
                )
                event_ids.append(UUID(_string_value(source.get("event_id"), "live theme event")))
                event_version_ids.append(
                    UUID(_string_value(source.get("event_version_id"), "live theme event version"))
                )
                published_at = datetime.fromisoformat(
                    _string_value(source.get("published_at"), "live theme published_at")
                )
                page_fetched_at = datetime.fromisoformat(
                    _string_value(source.get("page_fetched_at"), "live theme page fetched_at")
                )
                date.fromisoformat(
                    _string_value(source.get("published_date"), "live theme published date")
                )
            except ValueError as exc:
                raise ValueError("weekly live theme source date/UUID is invalid") from exc
            if published_at.tzinfo is None or page_fetched_at.tzinfo is None:
                raise ValueError("weekly live theme source timestamp must be timezone-aware")
            images = source.get("images")
            if not isinstance(images, list) or len(images) != 1:
                raise ValueError("weekly live theme source requires one context image")
            image = _mapping_value(images[0], "live theme context image")
            if set(image) != image_fields:
                raise ValueError("weekly live theme image fields changed")
            if (
                image.get("source_page_url") != canonical
                or image.get("response_media_type") not in {"image/jpeg", "image/png", "image/webp"}
                or image.get("rights_status") != "publish_permission_unverified"
                or image.get("context_only_not_evidence") is not True
                or image.get("source_marks_preserved") is not True
            ):
                raise ValueError("weekly live theme image provenance changed")
            _string_value(image.get("image_url"), "live theme image URL")
            _string_value(image.get("credit"), "live theme image credit")
            _positive_int(image.get("byte_size"), "live theme image byte size")
            _positive_int(image.get("width"), "live theme image width")
            _positive_int(image.get("height"), "live theme image height")
            image_hashes.append(_sha_value(image.get("sha256"), "live theme image"))
            try:
                image_fetched_at = datetime.fromisoformat(
                    _string_value(image.get("fetched_at"), "live theme image fetched_at")
                )
            except ValueError as exc:
                raise ValueError("weekly live theme image fetched_at is invalid") from exc
            if image_fetched_at.tzinfo is None:
                raise ValueError("weekly live theme image fetched_at must be timezone-aware")
        primary = _mapping_value(sources[0], "live theme primary source")
        if (
            row.get("event_id") != primary.get("event_id")
            or row.get("event_version_id") != primary.get("event_version_id")
            or row.get("organization_type") != primary.get("organization_type")
            or row.get("source_metadata_fingerprint") != primary.get("source_metadata_fingerprint")
        ):
            raise ValueError("weekly live theme primary selection projection changed")
    official_sources = cast(
        list[Mapping[str, object]],
        cast(Mapping[str, object], rows[0])["sources"],
    )
    if official_sources[0].get("organization_type") != "government":
        raise ValueError("weekly live theme official primary authority changed")
    for values in (
        canonical_urls,
        page_hashes,
        evidence_ids,
        event_ids,
        event_version_ids,
        image_hashes,
    ):
        if len(values) != 6 or len(set(values)) != 6:
            raise ValueError("weekly live theme global source identities must be distinct")
    calls = payload.get("external_calls")
    if not isinstance(calls, dict) or set(calls) != {
        "news",
        "source_pages",
        "news_images",
        "model",
        "embedding",
        "image_generation",
        "wechat",
        "wecom",
    }:
        raise ValueError("weekly live theme call counters changed")
    if calls != {
        "news": 12,
        "source_pages": 6,
        "news_images": 6,
        "model": 0,
        "embedding": 0,
        "image_generation": 0,
        "wechat": 0,
        "wecom": 0,
    }:
        raise ValueError("weekly live theme call counters are not truthful")
    if payload.get("boundaries") != {
        "development_only": True,
        "local_only": True,
        "published": False,
        "news_images_context_only_not_evidence": True,
        "publish_permission_verified": False,
        "source_marks_preserved": True,
        "wechat_or_wecom_clients_constructed": False,
    }:
        raise ValueError("weekly live theme boundaries changed")
    return _json_bytes(payload)


def _validate_live_acquisition_bindings(
    payload: Mapping[str, object],
    *,
    selection: WeeklyEditionSelection | _LoadedWeeklySelectionBindings,
    children: tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild],
) -> None:
    if payload.get("version") == WEEKLY_LIVE_THEME_CLUSTER_AUDIT_VERSION:
        _validate_live_theme_cluster_bindings(
            payload,
            selection=selection,
            children=children,
        )
        return
    rows = payload.get("articles")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly live acquisition binding rows changed")
    for raw_row, selected, child in zip(rows, selection.selected, children, strict=True):
        selected_binding = cast(
            WeeklyArticleSelection | _LoadedSelectedWeeklyBinding,
            selected,
        )
        row = _mapping_value(raw_row, "live acquisition binding")
        if (
            row.get("role") != child.role.value
            or row.get("title") != child.title
            or row.get("event_id") != str(selected_binding.event_id)
            or row.get("event_version_id") != str(selected_binding.event_version_id)
            or row.get("organization_type") != selected_binding.organization_type
            or row.get("source_metadata_fingerprint")
            != selected_binding.source_metadata_fingerprint
        ):
            raise ValueError("weekly live acquisition selected-child identity changed")
        article = _json_object(child.files["article.json"], label="weekly live child article")
        sources = article.get("sources")
        if not isinstance(sources, list) or len(sources) != 1:
            raise ValueError("weekly live child source projection changed")
        source = _mapping_value(sources[0], "live child source")
        if source.get("source_url") != row.get("canonical_url") or source.get(
            "evidence_id"
        ) != row.get("evidence_id"):
            raise ValueError("weekly live child source/evidence binding changed")
        context = _mapping_value(article.get("news_context_media"), "live child context")
        context_items = context.get("items")
        images = row.get("images")
        if not isinstance(context_items, list) or not isinstance(images, list):
            raise ValueError("weekly live child context binding changed")
        expected_context = [
            (
                image.get("sha256"),
                image.get("source_page_url"),
                image.get("rights_status"),
                image.get("context_only_not_evidence"),
            )
            for image in images
            if isinstance(image, Mapping)
        ]
        actual_context = [
            (
                item.get("sha256"),
                item.get("source_page_url"),
                item.get("rights_status"),
                item.get("context_only_not_evidence"),
            )
            for item in context_items
            if isinstance(item, Mapping)
        ]
        if actual_context != expected_context or len(actual_context) != len(images):
            raise ValueError("weekly live child news-image binding changed")


def _validate_live_theme_cluster_bindings(
    payload: Mapping[str, object],
    *,
    selection: WeeklyEditionSelection | _LoadedWeeklySelectionBindings,
    children: tuple[FinalizedWeeklyChild, FinalizedWeeklyChild, FinalizedWeeklyChild],
) -> None:
    rows = payload.get("articles")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly live theme binding rows changed")
    global_evidence_ids = {
        source["evidence_id"]
        for raw_row in rows
        for source in cast(
            list[Mapping[str, object]],
            cast(Mapping[str, object], raw_row)["sources"],
        )
    }
    seen_child_evidence: set[object] = set()
    for raw_row, selected, child in zip(rows, selection.selected, children, strict=True):
        selected_binding = cast(
            WeeklyArticleSelection | _LoadedSelectedWeeklyBinding,
            selected,
        )
        row = _mapping_value(raw_row, "live theme binding")
        if (
            row.get("role") != child.role.value
            or row.get("editorial_title") != child.title
            or row.get("event_id") != str(selected_binding.event_id)
            or row.get("event_version_id") != str(selected_binding.event_version_id)
            or row.get("organization_type") != selected_binding.organization_type
            or row.get("source_metadata_fingerprint")
            != selected_binding.source_metadata_fingerprint
        ):
            raise ValueError("weekly live theme selected-child identity changed")
        sources = row.get("sources")
        if not isinstance(sources, list) or len(sources) != 2:
            raise ValueError("weekly live theme source binding rows changed")
        article = _json_object(child.files["article.json"], label="weekly live theme child")
        article_sources = article.get("sources")
        if not isinstance(article_sources, list) or len(article_sources) != 2:
            raise ValueError("weekly live theme child source projection changed")
        expected_source_bindings = [
            (source.get("canonical_url"), source.get("evidence_id"))
            for source in sources
            if isinstance(source, Mapping)
        ]
        actual_source_bindings = [
            (source.get("source_url"), source.get("evidence_id"))
            for source in article_sources
            if isinstance(source, Mapping)
        ]
        if actual_source_bindings != expected_source_bindings:
            raise ValueError("weekly live theme child source/evidence binding changed")
        own_evidence_ids = {item[1] for item in expected_source_bindings}
        if own_evidence_ids & seen_child_evidence:
            raise ValueError("weekly live theme evidence leaked between children")
        seen_child_evidence.update(own_evidence_ids)
        claims = article.get("claims")
        if not isinstance(claims, list):
            raise ValueError("weekly live theme child claims changed")
        bound_external_evidence = {
            evidence_id
            for claim in claims
            if isinstance(claim, Mapping) and claim.get("kind") == "external_fact"
            for evidence_id in cast(list[object], claim.get("evidence_ids", []))
        }
        if bound_external_evidence != own_evidence_ids:
            raise ValueError("weekly live theme claim evidence containment changed")
        context = _mapping_value(article.get("news_context_media"), "live theme child context")
        context_items = context.get("items")
        if not isinstance(context_items, list) or len(context_items) != 2:
            raise ValueError("weekly live theme child context projection changed")
        expected_context: list[tuple[object, object, object, object]] = []
        for source in sources:
            source_mapping = _mapping_value(source, "live theme source binding")
            images = source_mapping.get("images")
            if not isinstance(images, list) or len(images) != 1:
                raise ValueError("weekly live theme source binding image changed")
            image = _mapping_value(images[0], "live theme source binding image")
            expected_context.append(
                (
                    image.get("sha256"),
                    source_mapping.get("canonical_url"),
                    image.get("rights_status"),
                    image.get("context_only_not_evidence"),
                )
            )
        actual_context = [
            (
                item.get("sha256"),
                item.get("source_page_url"),
                item.get("rights_status"),
                item.get("context_only_not_evidence"),
            )
            for item in context_items
            if isinstance(item, Mapping)
        ]
        if actual_context != expected_context:
            raise ValueError("weekly live theme context-image containment changed")
        body = child.files["article-body.html"].decode("utf-8")
        if any(cast(str, source[0]) not in body for source in expected_source_bindings):
            raise ValueError("weekly live theme HTML source provenance changed")
    if seen_child_evidence != global_evidence_ids:
        raise ValueError("weekly live theme evidence batch containment changed")


def _verify_child_zip(
    body: bytes,
    *,
    archive_root: str,
    files: Mapping[str, bytes],
) -> None:
    with zipfile.ZipFile(BytesIO(body)) as archive:
        infos = archive.infolist()
        expected_names = {f"{archive_root}/{path}" for path in files}
        if [info.filename for info in infos] != sorted(expected_names):
            raise ValueError("weekly archive members changed")
        for info in infos:
            if (
                info.is_dir()
                or info.flag_bits & 0x1
                or info.file_size > _MAX_CHILD_FILE_BYTES
                or info.date_time != (1980, 1, 1, 0, 0, 0)
                or info.compress_type != zipfile.ZIP_DEFLATED
                or info.external_attr != 0o100644 << 16
            ):
                raise ValueError("weekly archive member is unsafe")
            prefix = f"{archive_root}/"
            relative = _safe_relative(info.filename.removeprefix(prefix))
            if archive.read(info) != files[relative]:
                raise ValueError("weekly archive member bytes changed")


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or _path_has_symlink_component(path):
        raise ValueError("weekly child file must be a regular non-symlink file")
    return path.read_bytes()


def _read_bounded_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or _path_has_symlink_component(path):
        raise ValueError("weekly edition file must be a regular non-symlink file")
    if path.stat().st_size > _MAX_WEEKLY_EDITION_TOTAL_BYTES:
        raise ValueError("weekly edition file exceeds the aggregate bound")
    return path.read_bytes()


def _path_has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _path_is_within_weekly_batch(path: Path) -> bool:
    """Reject a sidecar root inside a content-addressed immutable weekly directory."""

    for candidate in (path, *path.parents):
        manifest_path = candidate / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            manifest = _json_object(
                manifest_path.read_bytes(),
                label="weekly immutable batch manifest",
            )
        except (OSError, ValueError):
            continue
        if manifest.get("bundle_version") == WEEKLY_EDITION_BUNDLE_VERSION:
            return True
    return False


def _safe_relative(value: str) -> str:
    pure = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or pure.is_absolute()
        or value != pure.as_posix()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("weekly edition path is unsafe")
    return value


def _json_object(body: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(body, object_pairs_hook=_reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("weekly JSON objects cannot contain duplicate fields")
        result[key] = value
    return result


def _mapping_value(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"weekly child {label} must be an object")
    return cast(dict[str, object], value)


def _string_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"weekly child {label} must be a non-blank string")
    return value


def _sha_value(value: object, label: str) -> str:
    string = _string_value(value, label)
    if len(string) != 64 or any(char not in "0123456789abcdef" for char in string):
        raise ValueError(f"weekly child {label} must be a SHA-256 digest")
    return string


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"weekly child {label} must be a positive integer")
    return value


def _media_ordinal(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4:
        raise ValueError("weekly child body ordinal must be a bounded integer")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _file_projection(path: str, body: bytes) -> dict[str, object]:
    return {"path": path, "byte_size": len(body), "sha256": sha256(body).hexdigest()}


def _fingerprint(*values: object) -> str:
    return sha256(_json_bytes(values)).hexdigest()
