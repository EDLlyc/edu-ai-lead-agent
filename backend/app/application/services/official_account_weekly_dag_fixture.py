"""Zero-network local fixture handlers for the durable weekly DAG demonstration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from app.application.ports.official_account_weekly_dag import (
    WeeklyDagNodeFailure,
    WeeklyDagNodeResult,
)
from app.application.services.official_account_editor_handoff_v2 import (
    EditorHandoffV2Artifact,
    write_editor_handoff_v2_artifact,
)
from app.application.services.official_account_weekly_dag import (
    StaticWeeklyDagHandlerRegistry,
)
from app.application.services.official_account_weekly_edition import (
    bind_weekly_child,
    build_weekly_edition_artifact,
    load_finalized_v2_child,
    write_weekly_edition_artifact,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WeeklyDagArtifact,
    WeeklyDagClaim,
    WeeklyDagErrorCode,
    WeeklyDagNodeKind,
)
from app.domain.official_account_weekly_edition import (
    WeeklyArticleRole,
    WeeklyEditionSchedule,
    weekly_selection_projection,
)
from app.official_account_weekly_edition_demo import (
    build_fixture_children,
    build_fixture_selection,
    fixture_mobile_validation,
)


class LocalWeeklyDagFixtureHandlers:
    def __init__(self, output_root: Path) -> None:
        root = output_root.expanduser().resolve()
        if root == Path(root.anchor):
            raise ValueError("weekly DAG fixture output cannot be a filesystem root")
        self._root = root
        self._children: (
            tuple[
                EditorHandoffV2Artifact,
                EditorHandoffV2Artifact,
                EditorHandoffV2Artifact,
            ]
            | None
        ) = None
        self._children_lock = asyncio.Lock()

    def registry(self) -> StaticWeeklyDagHandlerRegistry:
        return StaticWeeklyDagHandlerRegistry(
            {definition.key: self.execute for definition in WEEKLY_DAG_NODES}
        )

    async def execute(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        kind = claim.node.definition.kind
        if kind is WeeklyDagNodeKind.SCHEDULE:
            return self._schedule(claim)
        if kind is WeeklyDagNodeKind.SELECT_ROLES:
            return self._select_roles(claim)
        if kind is WeeklyDagNodeKind.BUILD_ARTICLE:
            return self._build_article(claim)
        if kind is WeeklyDagNodeKind.PLAN_MEDIA:
            return self._plan_media(claim)
        if kind is WeeklyDagNodeKind.RENDER_HANDOFF:
            return await self._render_handoff(claim)
        if kind is WeeklyDagNodeKind.VALIDATE_CHILD:
            return await self._validate_child(claim)
        if kind is WeeklyDagNodeKind.AGGREGATE:
            return await self._aggregate(claim)
        if kind is WeeklyDagNodeKind.FINALIZE:
            return await self._finalize(claim)
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.PERMISSION_DENIED.value,
            retryable=False,
        )

    def _schedule(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        schedule = WeeklyEditionSchedule()
        payload = {
            "version": "official-account-weekly-dag-schedule-checkpoint-v1",
            "week_start": claim.run.week_start.isoformat(),
            "timezone": schedule.timezone,
            "schedule_fingerprint": schedule.fingerprint,
            "request_fingerprint": claim.run.request_fingerprint,
            "due_policy_reused": True,
            "wechat_calls": 0,
            "wecom_calls": 0,
        }
        return self._checkpoint(claim, payload)

    def _select_roles(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        selection = build_fixture_selection()
        if selection.week_start != claim.run.week_start:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_SELECTION.value,
                retryable=False,
            )
        return self._checkpoint(claim, weekly_selection_projection(selection))

    def _build_article(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _required_role(claim)
        selected = next(item for item in build_fixture_selection().selected if item.role is role)
        return self._checkpoint(
            claim,
            {
                "version": "official-account-weekly-dag-article-checkpoint-v1",
                "role": role.value,
                "event_id": str(selected.event_id),
                "event_version_id": str(selected.event_version_id),
                "selection_fingerprint": build_fixture_selection().fingerprint,
                "content_owner": "official_account_editor_handoff_v2",
                "content_not_embedded": True,
            },
        )

    def _plan_media(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _required_role(claim)
        return self._checkpoint(
            claim,
            {
                "version": "official-account-weekly-dag-media-plan-checkpoint-v1",
                "role": role.value,
                "selection_method": "deterministic_fixture_semantic",
                "provider_execution": "not_claimed",
                "artifact_owner": "official_account_editor_handoff_v2",
                "image_bytes_not_embedded": True,
            },
        )

    async def _render_handoff(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _required_role(claim)
        artifact = await self._child_artifact(role)
        children_root = self._root / "children"
        target = children_root / f"wechat-editor-handoff-v2-{artifact.artifact_fingerprint[:16]}"
        if target.exists():
            loaded = load_finalized_v2_child(target, role=role)
            if (
                loaded.artifact_fingerprint != artifact.artifact_fingerprint
                or loaded.child_zip_sha256 != artifact.zip_sha256
            ):
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
                    retryable=False,
                )
        else:
            write_editor_handoff_v2_artifact(artifact, children_root)
        return WeeklyDagNodeResult(
            artifact=WeeklyDagArtifact(
                opaque_ref=_opaque_ref(claim),
                fingerprint=artifact.artifact_fingerprint,
                media_type="application/zip",
                byte_size=len(artifact.zip_bytes),
            )
        )

    async def _validate_child(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _required_role(claim)
        artifact = await self._child_artifact(role)
        target = (
            self._root
            / "children"
            / f"wechat-editor-handoff-v2-{artifact.artifact_fingerprint[:16]}"
        )
        try:
            child = load_finalized_v2_child(target, role=role)
            selected = next(
                item for item in build_fixture_selection().selected if item.role is role
            )
            binding = bind_weekly_child(selected=selected, child=child)
        except (FileNotFoundError, ValueError):
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_CHILD.value,
                retryable=False,
            ) from None
        return self._checkpoint(
            claim,
            {
                "version": "official-account-weekly-dag-child-validation-v1",
                "role": role.value,
                "run_id": str(child.run_id),
                "article_fingerprint": child.article_fingerprint,
                "content_fingerprint": child.content_fingerprint,
                "artifact_fingerprint": child.artifact_fingerprint,
                "child_zip_sha256": child.child_zip_sha256,
                "binding_fingerprint": binding.binding_fingerprint,
                "mobile_passed": True,
                "local_only": True,
                "published": False,
            },
        )

    async def _aggregate(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        selection = build_fixture_selection()
        if selection.week_start != claim.run.week_start:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_SELECTION.value,
                retryable=False,
            )
        finalized = []
        for role in WeeklyArticleRole:
            artifact = await self._child_artifact(role)
            target = (
                self._root
                / "children"
                / f"wechat-editor-handoff-v2-{artifact.artifact_fingerprint[:16]}"
            )
            try:
                finalized.append(load_finalized_v2_child(target, role=role))
            except (FileNotFoundError, ValueError):
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.PARTIAL_CHILDREN.value,
                    retryable=False,
                ) from None
        bindings = tuple(
            bind_weekly_child(selected=selected, child=child)
            for selected, child in zip(selection.selected, finalized, strict=True)
        )
        weekly = build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(finalized[0], finalized[1], finalized[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )
        target = (
            self._root
            / "weekly"
            / f"official-account-weekly-edition-{weekly.batch_fingerprint[:16]}"
        )
        if target.exists():
            _verify_existing_weekly(target, weekly.files, weekly.bundle_filename, weekly.zip_bytes)
        else:
            write_weekly_edition_artifact(weekly, self._root / "weekly")
        aggregate = WeeklyDagArtifact(
            opaque_ref=_opaque_ref(claim),
            fingerprint=weekly.batch_fingerprint,
            media_type="application/zip",
            byte_size=len(weekly.zip_bytes),
        )
        return WeeklyDagNodeResult(artifact=aggregate, aggregate_artifact=aggregate)

    async def _finalize(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        dependency = claim.dependencies[0].output_artifact if claim.dependencies else None
        if dependency is None:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.PARTIAL_CHILDREN.value,
                retryable=False,
            )
        return WeeklyDagNodeResult(
            artifact=WeeklyDagArtifact(
                opaque_ref=_opaque_ref(claim),
                fingerprint=dependency.fingerprint,
                media_type=dependency.media_type,
                byte_size=dependency.byte_size,
            ),
            aggregate_artifact=dependency,
        )

    async def _child_artifact(self, role: WeeklyArticleRole) -> EditorHandoffV2Artifact:
        if self._children is None:
            async with self._children_lock:
                if self._children is None:
                    staged = await build_fixture_children()
                    reports = {
                        item_role: fixture_mobile_validation(artifact)
                        for item_role, artifact in zip(WeeklyArticleRole, staged, strict=True)
                    }
                    self._children = await build_fixture_children(browser_validations=reports)
        return self._children[role.ordinal - 1]

    def _checkpoint(self, claim: WeeklyDagClaim, payload: object) -> WeeklyDagNodeResult:
        body = (
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        opaque_ref = _opaque_ref(claim)
        checkpoint_root = self._root / "checkpoints" / claim.run.run_id.hex
        target = checkpoint_root / f"{claim.node.definition.ordinal:02d}.json"
        _write_immutable(target, body)
        return WeeklyDagNodeResult(
            artifact=WeeklyDagArtifact(
                opaque_ref=opaque_ref,
                fingerprint=sha256(body).hexdigest(),
                media_type="application/json",
                byte_size=len(body),
            )
        )


def _required_role(claim: WeeklyDagClaim) -> WeeklyArticleRole:
    role = claim.node.definition.role
    if role is None:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return role


def _opaque_ref(claim: WeeklyDagClaim) -> str:
    return f"weekly.{claim.run.run_id.hex}.{claim.node.definition.ordinal:02d}"


def _write_immutable(target: Path, body: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != body:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
                retryable=False,
            )
        return
    temporary = target.with_name(f".{target.name}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file() or temporary.read_bytes() != body:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
                retryable=False,
            )
    else:
        with temporary.open("xb") as stream:
            stream.write(body)
    temporary.rename(target)


def _verify_existing_weekly(
    target: Path,
    files: Mapping[str, bytes],
    bundle_filename: str,
    zip_bytes: bytes,
) -> None:
    if target.is_symlink() or not target.is_dir():
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
            retryable=False,
        )
    expected = dict(files)
    expected[bundle_filename] = zip_bytes
    actual_paths = {
        path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
    }
    if actual_paths != set(expected) or any(
        (target / relative).read_bytes() != body for relative, body in expected.items()
    ):
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
            retryable=False,
        )
