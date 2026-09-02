"""Production handlers for the durable weekly official-account DAG."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date
from typing import Protocol, cast
from uuid import UUID

from app.application.ports.official_account_local import OfficialAccountVersionIdentity
from app.application.ports.official_account_weekly_dag import (
    WeeklyDagNodeFailure,
    WeeklyDagNodeResult,
)
from app.application.services.official_account_weekly_dag import (
    StaticWeeklyDagHandlerRegistry,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WeeklyDagArtifact,
    WeeklyDagClaim,
    WeeklyDagErrorCode,
    WeeklyDagNodeKind,
)
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WeeklyArticleRole,
    WeeklyEditionSchedule,
)


class WeeklyProductionCheckpointOwner(Protocol):
    def put_json(self, payload: dict[str, object]) -> WeeklyDagArtifact: ...

    def get_json(self, artifact: WeeklyDagArtifact) -> dict[str, object]: ...

    def get_json_by_fingerprint(self, fingerprint: str) -> dict[str, object]: ...


class WeeklyProductionArticleRepository(Protocol):
    async def enqueue_material_package(
        self,
        *,
        material_package_id: UUID,
        identity: OfficialAccountVersionIdentity,
    ) -> tuple[WeeklyProductionArticleRun, bool]: ...

    async def get_run(self, run_id: UUID) -> WeeklyProductionArticleRun: ...


class WeeklyProductionArticleRun(Protocol):
    id: UUID
    status: str


class WeeklyProductionPreparedDraft(Protocol):
    @property
    def article_fingerprint(self) -> str: ...

    @property
    def content_fingerprint(self) -> str: ...


class WeeklyProductionPreparedBatch(Protocol):
    @property
    def batch_fingerprint(self) -> str: ...

    @property
    def aggregate_fingerprint(self) -> str: ...


class WeeklyProductionPreparedArtifacts(Protocol):
    async def build_child(
        self,
        *,
        run_id: UUID,
        role: WeeklyArticleRole,
    ) -> WeeklyDagArtifact: ...

    def validate_child(
        self,
        artifact: WeeklyDagArtifact,
        *,
        role: WeeklyArticleRole,
    ) -> WeeklyProductionPreparedDraft: ...

    def aggregate(
        self,
        *,
        week_start: date,
        children: tuple[WeeklyDagArtifact, WeeklyDagArtifact, WeeklyDagArtifact],
    ) -> WeeklyDagArtifact: ...

    def validate_batch(self, artifact: WeeklyDagArtifact) -> WeeklyProductionPreparedBatch: ...


class ProductionWeeklyDagHandlers:
    """Reuse persisted Zhipu article runs and expose only complete prepared batches."""

    def __init__(
        self,
        *,
        checkpoints: WeeklyProductionCheckpointOwner,
        article_repository: WeeklyProductionArticleRepository,
        prepared_artifacts: WeeklyProductionPreparedArtifacts,
        article_identity: OfficialAccountVersionIdentity,
        article_wait_seconds: int = 720,
        article_poll_seconds: float = 2.0,
    ) -> None:
        if article_identity.provider != "zhipu":
            raise ValueError("production weekly handlers require the Zhipu article identity")
        if not 30 <= article_wait_seconds <= 840:
            raise ValueError("production weekly article wait must be in [30, 840] seconds")
        if not 0.5 <= article_poll_seconds <= 30:
            raise ValueError("production weekly article poll must be in [0.5, 30] seconds")
        self._checkpoints = checkpoints
        self._article_repository = article_repository
        self._prepared_artifacts = prepared_artifacts
        self._article_identity = article_identity
        self._article_wait_seconds = article_wait_seconds
        self._article_poll_seconds = article_poll_seconds

    def registry(self) -> StaticWeeklyDagHandlerRegistry:
        return StaticWeeklyDagHandlerRegistry(
            {definition.key: self.execute for definition in WEEKLY_DAG_NODES}
        )

    async def execute(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        try:
            kind = claim.node.definition.kind
            if kind is WeeklyDagNodeKind.SCHEDULE:
                return self._schedule(claim)
            if kind is WeeklyDagNodeKind.SELECT_ROLES:
                return self._select_roles(claim)
            if kind is WeeklyDagNodeKind.BUILD_ARTICLE:
                return await self._build_article(claim)
            if kind is WeeklyDagNodeKind.PLAN_MEDIA:
                return await self._plan_media(claim)
            if kind is WeeklyDagNodeKind.RENDER_HANDOFF:
                return await self._render_handoff(claim)
            if kind is WeeklyDagNodeKind.VALIDATE_CHILD:
                return self._validate_child(claim)
            if kind is WeeklyDagNodeKind.AGGREGATE:
                return self._aggregate(claim)
            if kind is WeeklyDagNodeKind.FINALIZE:
                return self._finalize(claim)
        except WeeklyDagNodeFailure:
            raise
        except (KeyError, TypeError, ValueError):
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                retryable=False,
            ) from None
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.PERMISSION_DENIED.value,
            retryable=False,
        )

    def _schedule(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        payload = self._input(claim)
        schedule = WeeklyEditionSchedule()
        return self._json_result(
            {
                "version": "weekly-production-schedule-checkpoint-v1",
                "week_start": claim.run.week_start.isoformat(),
                "input_fingerprint": claim.run.input_fingerprint,
                "selection_fingerprint": _sha(payload.get("selection_fingerprint")),
                "schedule_fingerprint": schedule.fingerprint,
                "timezone": schedule.timezone,
                "published": False,
                "draft_only": True,
            }
        )

    def _select_roles(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        payload = self._input(claim)
        items = _items(payload)
        return self._json_result(
            {
                "version": "weekly-production-role-selection-checkpoint-v1",
                "week_start": claim.run.week_start.isoformat(),
                "selection_fingerprint": _sha(payload.get("selection_fingerprint")),
                "items": items,
            }
        )

    async def _build_article(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _role(claim)
        item = _item_for_role(self._input(claim), role)
        run, _created = await self._article_repository.enqueue_material_package(
            material_package_id=UUID(_text(item.get("material_package_id"))),
            identity=self._article_identity,
        )
        run_id = UUID(str(run.id))
        deadline = asyncio.get_running_loop().time() + self._article_wait_seconds
        while True:
            current = await self._article_repository.get_run(run_id)
            status = current.status
            if status == "ready":
                break
            if status in {"review_required", "failed", "result_unknown"}:
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.PROVIDER_TERMINAL.value,
                    retryable=False,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.CAPABILITY_TIMEOUT.value,
                    retryable=True,
                )
            await asyncio.sleep(self._article_poll_seconds)
        return self._json_result(
            {
                "version": "weekly-production-article-run-checkpoint-v1",
                "role": role.value,
                "official_account_run_id": str(run_id),
                "material_package_id": _text(item.get("material_package_id")),
                "event_id": _text(item.get("event_id")),
                "event_version_id": _text(item.get("event_version_id")),
                "provider": self._article_identity.provider,
                "model": self._article_identity.model,
                "status": "ready",
            }
        )

    async def _plan_media(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _role(claim)
        dependency = self._dependency_json(claim, expected="build_article")
        run_id = UUID(_text(dependency.get("official_account_run_id")))
        run = await self._article_repository.get_run(run_id)
        if run.status != "ready":
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_CHILD.value,
                retryable=False,
            )
        return self._json_result(
            {
                "version": "weekly-production-media-ready-checkpoint-v1",
                "role": role.value,
                "official_account_run_id": str(run_id),
                "status": "ready",
                "media_owned_by_persisted_run": True,
            }
        )

    async def _render_handoff(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _role(claim)
        dependency = self._dependency_json(claim, expected="plan_media")
        artifact = await self._prepared_artifacts.build_child(
            run_id=UUID(_text(dependency.get("official_account_run_id"))),
            role=role,
        )
        return WeeklyDagNodeResult(artifact=artifact)

    def _validate_child(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        role = _role(claim)
        dependency = _dependency_artifact(claim, expected="render_handoff")
        prepared = self._prepared_artifacts.validate_child(dependency, role=role)
        return self._json_result(
            {
                "version": "weekly-production-child-validation-v1",
                "role": role.value,
                "article_fingerprint": _sha(prepared.article_fingerprint),
                "content_fingerprint": _sha(prepared.content_fingerprint),
                "child_artifact": _artifact_projection(dependency),
                "preflight_passed": True,
                "published": False,
                "draft_only": True,
            }
        )

    def _aggregate(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        children = tuple(
            _artifact_from_projection(
                self._checkpoints.get_json(_required_output(dependency)).get("child_artifact")
            )
            for dependency in claim.dependencies
        )
        artifact = self._prepared_artifacts.aggregate(
            week_start=claim.run.week_start,
            children=cast(
                tuple[WeeklyDagArtifact, WeeklyDagArtifact, WeeklyDagArtifact],
                children,
            ),
        )
        return WeeklyDagNodeResult(artifact=artifact, aggregate_artifact=artifact)

    def _finalize(self, claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        dependency = _dependency_artifact(claim, expected="aggregate")
        batch = self._prepared_artifacts.validate_batch(dependency)
        artifact = self._checkpoints.put_json(
            {
                "version": "weekly-production-finalized-batch-v1",
                "week_start": claim.run.week_start.isoformat(),
                "batch_fingerprint": _sha(batch.batch_fingerprint),
                "aggregate_fingerprint": _sha(batch.aggregate_fingerprint),
                "aggregate_artifact": _artifact_projection(dependency),
                "inbox_ready": True,
                "published": False,
                "draft_only": True,
            }
        )
        return WeeklyDagNodeResult(artifact=artifact, aggregate_artifact=dependency)

    def _input(self, claim: WeeklyDagClaim) -> dict[str, object]:
        payload = self._checkpoints.get_json_by_fingerprint(claim.run.input_fingerprint)
        if (
            payload.get("version") != "official-account-weekly-production-input-v1"
            or payload.get("week_start") != claim.run.week_start.isoformat()
            or len(_items(payload)) != 3
        ):
            raise ValueError("weekly production input snapshot changed")
        return payload

    def _dependency_json(self, claim: WeeklyDagClaim, *, expected: str) -> dict[str, object]:
        dependency = _dependency_artifact(claim, expected=expected)
        return self._checkpoints.get_json(dependency)

    def _json_result(self, payload: dict[str, object]) -> WeeklyDagNodeResult:
        return WeeklyDagNodeResult(artifact=self._checkpoints.put_json(payload))


def _role(claim: WeeklyDagClaim) -> WeeklyArticleRole:
    role = claim.node.definition.role
    if role is None:
        raise ValueError("weekly production branch role is missing")
    return role


def _items(payload: Mapping[str, object]) -> list[dict[str, object]]:
    raw = payload.get("items")
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError("weekly production input items are invalid")
    items: list[dict[str, object]] = []
    for expected_role, item in zip(WEEKLY_EDITION_ROLE_ORDER, raw, strict=True):
        if not isinstance(item, dict) or item.get("role") != expected_role:
            raise ValueError("weekly production input role order changed")
        items.append(cast(dict[str, object], item))
    if len({_text(item.get("event_id")) for item in items}) != 3:
        raise ValueError("weekly production input events must be distinct")
    return items


def _item_for_role(
    payload: Mapping[str, object],
    role: WeeklyArticleRole,
) -> dict[str, object]:
    return next(item for item in _items(payload) if item["role"] == role.value)


def _dependency_artifact(claim: WeeklyDagClaim, *, expected: str) -> WeeklyDagArtifact:
    if len(claim.dependencies) != 1:
        raise ValueError("weekly production node must have one dependency")
    dependency = claim.dependencies[0]
    if not dependency.definition.key.endswith(expected):
        raise ValueError("weekly production dependency changed")
    return _required_output(dependency)


def _required_output(node: object) -> WeeklyDagArtifact:
    artifact = getattr(node, "output_artifact", None)
    if not isinstance(artifact, WeeklyDagArtifact):
        raise ValueError("weekly production dependency artifact is missing")
    return artifact


def _artifact_projection(artifact: WeeklyDagArtifact) -> dict[str, object]:
    return {
        "opaque_ref": artifact.opaque_ref,
        "fingerprint": artifact.fingerprint,
        "media_type": artifact.media_type,
        "byte_size": artifact.byte_size,
    }


def _artifact_from_projection(value: object) -> WeeklyDagArtifact:
    if not isinstance(value, dict):
        raise ValueError("weekly production child artifact projection is invalid")
    return WeeklyDagArtifact(
        opaque_ref=_text(value.get("opaque_ref")),
        fingerprint=_sha(value.get("fingerprint")),
        media_type=_text(value.get("media_type")),
        byte_size=_positive_int(value.get("byte_size")),
    )


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError("weekly production text field is invalid")
    return value


def _sha(value: object) -> str:
    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError("weekly production SHA-256 field is invalid")
    return text


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("weekly production byte size is invalid")
    return value


__all__ = ["ProductionWeeklyDagHandlers"]
