"""Content-addressed prepared draft artifacts derived from persisted local runs."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Final, cast
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.wechat_official_account import WeChatDraftRole
from app.application.ports.wechat_official_account_draft_artifacts import (
    WECHAT_DRAFT_PREPARED_ARTIFACT_REF_VERSION,
    WeChatDraftArtifactBatch,
    WeChatDraftArtifactSource,
)
from app.application.services.wechat_official_account_draft import (
    WeChatDraftLocalSource,
    WeChatOfficialAccountDraftPreparer,
    WeChatPreparedDraft,
)
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.infrastructure.db.models import OfficialAccountLocalMediaModel
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    persisted_media_snapshot,
)

PREPARED_DRAFT_CHILD_VERSION: Final = "wechat-draft-prepared-child-v1"
PREPARED_DRAFT_BATCH_VERSION: Final = "wechat-draft-prepared-batch-v1"
PREPARED_DRAFT_SOURCE_REF_VERSION: Final = WECHAT_DRAFT_PREPARED_ARTIFACT_REF_VERSION
PREPARED_DRAFT_CHILD_REF_VERSION: Final = "wechat-prepared-child-v1"
PREPARED_DRAFT_BATCH_REF_VERSION: Final = "wechat-prepared-batch-v1"
_MAX_BATCH_BYTES: Final = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PreparedDraftChildProjection:
    role: str
    ordinal: int
    directory_name: str
    child_fingerprint: str
    article_fingerprint: str
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class FinalizedPreparedDraftBatch:
    directory: Path = field(repr=False)
    week_start: str
    batch_fingerprint: str
    aggregate_fingerprint: str
    children: tuple[
        PreparedDraftChildProjection,
        PreparedDraftChildProjection,
        PreparedDraftChildProjection,
    ]

    def as_artifact_batch(self) -> WeChatDraftArtifactBatch:
        sources = tuple(
            WeChatDraftArtifactSource(
                role=cast(WeChatDraftRole, child.role),
                ordinal=child.ordinal,
                source_ref=(
                    f"{PREPARED_DRAFT_SOURCE_REF_VERSION}:{self.aggregate_fingerprint}:{child.role}"
                ),
                source_fingerprint=child.child_fingerprint,
                article_fingerprint=child.article_fingerprint,
                content_fingerprint=child.content_fingerprint,
                child_zip_sha256=child.child_fingerprint,
            )
            for child in self.children
        )
        return WeChatDraftArtifactBatch(
            week_start=self.week_start,
            batch_fingerprint=self.batch_fingerprint,
            aggregate_fingerprint=self.aggregate_fingerprint,
            sources=cast(
                tuple[
                    WeChatDraftArtifactSource,
                    WeChatDraftArtifactSource,
                    WeChatDraftArtifactSource,
                ],
                sources,
            ),
        )


class PreparedWeeklyDraftArtifactOwner:
    """Build safe prepared children and expose only a complete three-item inbox batch."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        resolver: OfficialAccountLocalMediaResolver,
        work_root: Path,
        inbox_root: Path,
        max_image_bytes: int,
    ) -> None:
        self._session_factory = session_factory
        self._repository = PostgresOfficialAccountRepository(session_factory)
        self._resolver = resolver
        self._work_root = _validated_root(work_root, "work")
        self._inbox_root = _validated_root(inbox_root, "inbox")
        if (
            self._work_root == self._inbox_root
            or self._work_root.is_relative_to(self._inbox_root)
            or self._inbox_root.is_relative_to(self._work_root)
        ):
            raise ValueError("prepared draft work and inbox roots must be independent")
        self._preparer = WeChatOfficialAccountDraftPreparer(max_image_bytes=max_image_bytes)
        self._max_image_bytes = max_image_bytes

    async def build_child(
        self,
        *,
        run_id: UUID,
        role: WeeklyArticleRole,
    ) -> WeeklyDagArtifact:
        run = await self._repository.get_run(run_id)
        article = await self._repository.get_article(run_id)
        draft = await self._repository.get_draft(run_id)
        if (
            run.status != "ready"
            or run.generation_mode != "live"
            or article is None
            or not article.validation_passed
            or article.audit is None
            or not article.audit.accepted
            or draft is None
            or draft.state != "ready"
            or draft.simulation is not True
        ):
            raise ValueError("official-account run is not automatically draft-ready")
        media_rows = await self._load_media_rows(run_id)
        if not media_rows:
            raise ValueError("official-account run has no ready media")
        files: dict[str, bytes] = {}
        media_projection: list[dict[str, object]] = []
        replacements: dict[str, str] = {}
        async with self._session_factory() as session:
            for row in media_rows:
                snapshot = persisted_media_snapshot(row)
                body = await self._resolver.read_verified_bytes(session=session, media=snapshot)
                body, media_type = _normalize_supported_media(body, snapshot.media_type)
                suffix = ".jpg" if media_type == "image/jpeg" else ".png"
                path = f"assets/{snapshot.role}-{snapshot.ordinal}{suffix}"
                width, height = _image_dimensions(body, media_type)
                files[path] = body
                media_projection.append(
                    {
                        "path": path,
                        "role": snapshot.role,
                        "ordinal": snapshot.ordinal,
                        "media_type": media_type,
                        "byte_size": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "width": width,
                        "height": height,
                    }
                )
                if snapshot.role != "cover":
                    replacements[snapshot.local_media_id] = path
        resolved_html = draft.resolved_html
        for row in media_rows:
            if row.role == "cover":
                continue
            path = replacements[row.local_media_id]
            old = f'src="{_media_url(row.local_media_id)}"'
            if resolved_html.count(old) != 1:
                raise ValueError("official-account persisted HTML/media binding changed")
            resolved_html = resolved_html.replace(old, f'src="{path}"', 1)
        if "/api/v1/official-account-local/media/" in resolved_html:
            raise ValueError("prepared draft retained a private local media URL")
        files["article-body.html"] = resolved_html.encode("utf-8")
        file_projection = [
            {
                "path": path,
                "byte_size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            for path, body in sorted(files.items())
        ]
        content_fingerprint = _fingerprint(
            {
                "article_fingerprint": article.article.content_fingerprint,
                "draft_resolved_fingerprint": draft.resolved_fingerprint,
                "files": file_projection,
            }
        )
        identity: dict[str, object] = {
            "version": PREPARED_DRAFT_CHILD_VERSION,
            "role": role.value,
            "run_id": str(run_id),
            "article_fingerprint": article.article.content_fingerprint,
            "content_fingerprint": content_fingerprint,
            "title": article.article.title,
            "author": article.article.author,
            "digest": article.article.digest,
            "media": media_projection,
            "files": file_projection,
            "published": False,
            "draft_only": True,
        }
        child_fingerprint = _fingerprint(identity)
        manifest = {**identity, "child_fingerprint": child_fingerprint}
        target = self._child_path(child_fingerprint)
        _write_directory(target, files={**files, "prepared-manifest.json": _json_bytes(manifest)})
        prepared = self._preparer.prepare(WeChatDraftLocalSource(directory=target, role=role.value))
        if (
            prepared.article_fingerprint != article.article.content_fingerprint
            or prepared.content_fingerprint != content_fingerprint
        ):
            raise ValueError("prepared draft child identity changed")
        return WeeklyDagArtifact(
            opaque_ref=f"{PREPARED_DRAFT_CHILD_REF_VERSION}:{child_fingerprint}",
            fingerprint=child_fingerprint,
            media_type="application/vnd.wechat.prepared-draft-child+directory",
            byte_size=_directory_size(target),
        )

    def validate_child(
        self,
        artifact: WeeklyDagArtifact,
        *,
        role: WeeklyArticleRole,
    ) -> WeChatPreparedDraft:
        fingerprint = _artifact_fingerprint(
            artifact,
            ref_version=PREPARED_DRAFT_CHILD_REF_VERSION,
            media_type="application/vnd.wechat.prepared-draft-child+directory",
        )
        target = self._child_path(fingerprint)
        if _directory_size(target) != artifact.byte_size:
            raise ValueError("prepared draft child byte size changed")
        prepared = self._preparer.prepare(WeChatDraftLocalSource(directory=target, role=role.value))
        manifest = _json_object((target / "prepared-manifest.json").read_bytes())
        if manifest.get("child_fingerprint") != fingerprint:
            raise ValueError("prepared draft child fingerprint changed")
        return prepared

    def aggregate(
        self,
        *,
        week_start: date,
        children: tuple[WeeklyDagArtifact, WeeklyDagArtifact, WeeklyDagArtifact],
    ) -> WeeklyDagArtifact:
        if week_start.weekday() != 0:
            raise ValueError("prepared weekly batch must start on Monday")
        projections: list[dict[str, object]] = []
        child_paths: list[Path] = []
        for role, artifact in zip(WeeklyArticleRole, children, strict=True):
            prepared = self.validate_child(artifact, role=role)
            child_fingerprint = artifact.fingerprint
            directory_name = f"{role.ordinal:02d}-{role.value}"
            projections.append(
                {
                    "role": role.value,
                    "ordinal": role.ordinal,
                    "directory": f"articles/{directory_name}",
                    "child_fingerprint": child_fingerprint,
                    "article_fingerprint": prepared.article_fingerprint,
                    "content_fingerprint": prepared.content_fingerprint,
                }
            )
            child_paths.append(self._child_path(child_fingerprint))
        batch_fingerprint = _fingerprint(
            {
                "version": PREPARED_DRAFT_BATCH_VERSION,
                "week_start": week_start.isoformat(),
                "children": projections,
            }
        )
        identity: dict[str, object] = {
            "version": PREPARED_DRAFT_BATCH_VERSION,
            "week_start": week_start.isoformat(),
            "batch_fingerprint": batch_fingerprint,
            "children": projections,
            "published": False,
            "draft_only": True,
        }
        aggregate_fingerprint = _fingerprint(identity)
        manifest = {**identity, "aggregate_fingerprint": aggregate_fingerprint}
        target = self._batch_path(aggregate_fingerprint)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
            clean = True
            try:
                articles = temporary / "articles"
                articles.mkdir()
                for role, child in zip(WeeklyArticleRole, child_paths, strict=True):
                    shutil.copytree(child, articles / f"{role.ordinal:02d}-{role.value}")
                (temporary / "prepared-weekly.json").write_bytes(_json_bytes(manifest))
                try:
                    temporary.rename(target)
                except OSError:
                    if not target.exists():
                        raise
                else:
                    clean = False
            finally:
                if clean and temporary.exists():
                    shutil.rmtree(temporary)
        finalized = load_prepared_weekly_draft_batch(
            target,
            max_image_bytes=self._max_image_bytes,
        )
        if finalized.aggregate_fingerprint != aggregate_fingerprint:
            raise ValueError("prepared weekly aggregate identity changed")
        return WeeklyDagArtifact(
            opaque_ref=f"{PREPARED_DRAFT_BATCH_REF_VERSION}:{aggregate_fingerprint}",
            fingerprint=aggregate_fingerprint,
            media_type="application/vnd.wechat.prepared-draft-batch+directory",
            byte_size=_directory_size(target),
        )

    def validate_batch(self, artifact: WeeklyDagArtifact) -> FinalizedPreparedDraftBatch:
        fingerprint = _artifact_fingerprint(
            artifact,
            ref_version=PREPARED_DRAFT_BATCH_REF_VERSION,
            media_type="application/vnd.wechat.prepared-draft-batch+directory",
        )
        target = self._batch_path(fingerprint)
        if _directory_size(target) != artifact.byte_size:
            raise ValueError("prepared weekly batch byte size changed")
        batch = load_prepared_weekly_draft_batch(
            target,
            max_image_bytes=self._max_image_bytes,
        )
        if batch.aggregate_fingerprint != fingerprint:
            raise ValueError("prepared weekly batch fingerprint changed")
        return batch

    async def _load_media_rows(
        self,
        run_id: UUID,
    ) -> tuple[OfficialAccountLocalMediaModel, ...]:
        async with self._session_factory() as session:
            return tuple(
                await session.scalars(
                    select(OfficialAccountLocalMediaModel)
                    .where(
                        OfficialAccountLocalMediaModel.run_id == run_id,
                        OfficialAccountLocalMediaModel.status == "ready",
                    )
                    .order_by(
                        OfficialAccountLocalMediaModel.role,
                        OfficialAccountLocalMediaModel.ordinal,
                    )
                )
            )

    def _child_path(self, fingerprint: str) -> Path:
        _validate_sha(fingerprint)
        return self._work_root / "children" / f"wechat-draft-prepared-child-{fingerprint}"

    def _batch_path(self, fingerprint: str) -> Path:
        _validate_sha(fingerprint)
        return self._inbox_root / f"official-account-prepared-weekly-{fingerprint}"


def load_prepared_weekly_draft_batch(
    directory: Path,
    *,
    max_image_bytes: int,
) -> FinalizedPreparedDraftBatch:
    root = directory.expanduser().resolve(strict=True)
    if not root.is_dir() or directory.is_symlink():
        raise ValueError("prepared weekly directory is invalid")
    total_bytes = _directory_size(root)
    manifest_path = root / "prepared-weekly.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("prepared weekly manifest is unavailable")
    manifest = _json_object(manifest_path.read_bytes())
    if manifest.get("version") != PREPARED_DRAFT_BATCH_VERSION:
        raise ValueError("prepared weekly version is unsupported")
    if manifest.get("published") is not False or manifest.get("draft_only") is not True:
        raise ValueError("prepared weekly publication boundary changed")
    week_start = date.fromisoformat(str(manifest.get("week_start")))
    if week_start.weekday() != 0:
        raise ValueError("prepared weekly week start is invalid")
    raw_children = manifest.get("children")
    if not isinstance(raw_children, list) or len(raw_children) != 3:
        raise ValueError("prepared weekly children are incomplete")
    preparer = WeChatOfficialAccountDraftPreparer(max_image_bytes=max_image_bytes)
    projections: list[PreparedDraftChildProjection] = []
    sources: list[WeChatDraftLocalSource] = []
    for role, raw in zip(WeeklyArticleRole, raw_children, strict=True):
        if not isinstance(raw, dict):
            raise ValueError("prepared weekly child projection is invalid")
        directory_name = f"{role.ordinal:02d}-{role.value}"
        if (
            raw.get("role") != role.value
            or raw.get("ordinal") != role.ordinal
            or raw.get("directory") != f"articles/{directory_name}"
        ):
            raise ValueError("prepared weekly child order changed")
        child_fingerprint = _sha_value(raw.get("child_fingerprint"))
        child_directory = root / "articles" / directory_name
        child_manifest = _json_object((child_directory / "prepared-manifest.json").read_bytes())
        if child_manifest.get("child_fingerprint") != child_fingerprint:
            raise ValueError("prepared weekly child fingerprint changed")
        projections.append(
            PreparedDraftChildProjection(
                role=role.value,
                ordinal=role.ordinal,
                directory_name=directory_name,
                child_fingerprint=child_fingerprint,
                article_fingerprint=_sha_value(raw.get("article_fingerprint")),
                content_fingerprint=_sha_value(raw.get("content_fingerprint")),
            )
        )
        sources.append(WeChatDraftLocalSource(directory=child_directory, role=role.value))
    prepared = preparer.prepare_weekly(
        cast(
            tuple[WeChatDraftLocalSource, WeChatDraftLocalSource, WeChatDraftLocalSource],
            tuple(sources),
        )
    )
    if any(
        projection.article_fingerprint != draft.article_fingerprint
        or projection.content_fingerprint != draft.content_fingerprint
        for projection, draft in zip(projections, prepared, strict=True)
    ):
        raise ValueError("prepared weekly draft identities changed")
    if {item.name for item in root.iterdir()} != {"articles", "prepared-weekly.json"}:
        raise ValueError("prepared weekly root file set changed")
    articles_root = root / "articles"
    if (
        not articles_root.is_dir()
        or articles_root.is_symlink()
        or {item.name for item in articles_root.iterdir()}
        != {f"{role.ordinal:02d}-{role.value}" for role in WeeklyArticleRole}
    ):
        raise ValueError("prepared weekly article directory set changed")
    identity = dict(manifest)
    aggregate_fingerprint = _sha_value(identity.pop("aggregate_fingerprint", None))
    if _fingerprint(identity) != aggregate_fingerprint:
        raise ValueError("prepared weekly aggregate fingerprint changed")
    batch_fingerprint = _sha_value(manifest.get("batch_fingerprint"))
    if (
        _fingerprint(
            {
                "version": PREPARED_DRAFT_BATCH_VERSION,
                "week_start": week_start.isoformat(),
                "children": raw_children,
            }
        )
        != batch_fingerprint
    ):
        raise ValueError("prepared weekly batch fingerprint changed")
    if total_bytes > _MAX_BATCH_BYTES:
        raise ValueError("prepared weekly batch exceeds its byte bound")
    return FinalizedPreparedDraftBatch(
        directory=root,
        week_start=week_start.isoformat(),
        batch_fingerprint=batch_fingerprint,
        aggregate_fingerprint=aggregate_fingerprint,
        children=cast(
            tuple[
                PreparedDraftChildProjection,
                PreparedDraftChildProjection,
                PreparedDraftChildProjection,
            ],
            tuple(projections),
        ),
    )


def _media_url(local_media_id: str) -> str:
    return f"/api/v1/official-account-local/media/{local_media_id}"


def _normalize_supported_media(body: bytes, media_type: str) -> tuple[bytes, str]:
    if media_type in {"image/jpeg", "image/png"}:
        _image_dimensions(body, media_type)
        return body, media_type
    if media_type != "image/webp":
        raise ValueError("prepared draft media type is unsupported")
    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            image = opened.convert("RGB")
    except (OSError, UnidentifiedImageError):
        raise ValueError("prepared draft WebP bytes are invalid") from None
    output = BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True, progressive=False, subsampling=2)
    return output.getvalue(), "image/jpeg"


def _image_dimensions(body: bytes, media_type: str) -> tuple[int, int]:
    expected = {"image/jpeg": "JPEG", "image/png": "PNG"}.get(media_type)
    if expected is None:
        raise ValueError("prepared draft image type is unsupported")
    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            if opened.format != expected:
                raise ValueError("prepared draft image format changed")
            return opened.size
    except (OSError, UnidentifiedImageError):
        raise ValueError("prepared draft image bytes are invalid") from None


def _write_directory(target: Path, *, files: dict[str, bytes]) -> None:
    if target.exists():
        _directory_size(target)
        for relative, body in files.items():
            path = target.joinpath(*PurePosixPath(relative).parts)
            if not path.is_file() or path.is_symlink() or path.read_bytes() != body:
                raise ValueError("prepared draft existing artifact changed")
        actual = {
            path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
        }
        if actual != set(files):
            raise ValueError("prepared draft existing file set changed")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    clean = True
    try:
        for relative, body in files.items():
            path = temporary.joinpath(*PurePosixPath(relative).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        try:
            temporary.rename(target)
        except OSError:
            if not target.exists():
                raise
        else:
            clean = False
    finally:
        if clean and temporary.exists():
            shutil.rmtree(temporary)
    _write_directory(target, files=files)


def _directory_size(root: Path) -> int:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("prepared draft artifact directory is unavailable")
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("prepared draft artifact contains a symlink")
        if path.is_file():
            total += path.stat().st_size
            if total > _MAX_BATCH_BYTES:
                raise ValueError("prepared draft artifact exceeds its byte bound")
    return total


def _artifact_fingerprint(
    artifact: WeeklyDagArtifact,
    *,
    ref_version: str,
    media_type: str,
) -> str:
    if (
        artifact.opaque_ref != f"{ref_version}:{artifact.fingerprint}"
        or artifact.media_type != media_type
        or artifact.byte_size < 1
        or artifact.byte_size > _MAX_BATCH_BYTES
    ):
        raise ValueError("prepared draft artifact metadata is invalid")
    _validate_sha(artifact.fingerprint)
    return artifact.fingerprint


def _json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_object(body: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("prepared draft JSON contains duplicate fields")
            result[key] = value
        return result

    payload = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(payload, dict):
        raise ValueError("prepared draft JSON must be an object")
    return cast(dict[str, object], payload)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _sha_value(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("prepared draft SHA-256 is invalid")
    _validate_sha(value)
    return value


def _validate_sha(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("prepared draft SHA-256 is invalid")


def _validated_root(root: Path, label: str) -> Path:
    value = root.expanduser().resolve()
    if value == Path(value.anchor):
        raise ValueError(f"prepared draft {label} root cannot be a filesystem root")
    return value


__all__ = [
    "PREPARED_DRAFT_BATCH_REF_VERSION",
    "PREPARED_DRAFT_BATCH_VERSION",
    "PREPARED_DRAFT_CHILD_REF_VERSION",
    "PREPARED_DRAFT_CHILD_VERSION",
    "PREPARED_DRAFT_SOURCE_REF_VERSION",
    "FinalizedPreparedDraftBatch",
    "PreparedDraftChildProjection",
    "PreparedWeeklyDraftArtifactOwner",
    "load_prepared_weekly_draft_batch",
]
