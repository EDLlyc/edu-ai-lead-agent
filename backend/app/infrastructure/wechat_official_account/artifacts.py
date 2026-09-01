"""Immutable local owner for content-addressed WeChat draft sources."""

from __future__ import annotations

import shutil
import tempfile
from collections import Counter
from heapq import nsmallest
from pathlib import Path, PurePosixPath
from typing import Final, cast

from app.application.ports.wechat_official_account_draft_artifacts import (
    WECHAT_DRAFT_ARTIFACT_INVALID,
    WECHAT_DRAFT_ARTIFACT_REF_VERSION,
    ResolvedWeChatDraftArtifactSource,
    WeChatDraftArtifactBatch,
    WeChatDraftArtifactDiscovery,
    WeChatDraftArtifactError,
    WeChatDraftArtifactSource,
)
from app.application.services.official_account_weekly_edition import (
    WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED,
    FinalizedWeeklyEdition,
    WeeklyEditionLiveProvenanceError,
    load_finalized_weekly_edition,
)
from app.domain.official_account_weekly_edition import WeeklyArticleRole

_MAX_DISCOVERY_COUNT: Final = 1000


class LocalWeChatDraftArtifactStore:
    """Stage and resolve live weekly aggregates without exposing private paths."""

    def __init__(self, *, staging_root: Path, inbox_root: Path | None = None) -> None:
        self._staging_root = _validated_root(staging_root, label="staging")
        self._inbox_root = (
            _validated_root(inbox_root, label="inbox") if inbox_root is not None else None
        )
        if self._inbox_root is not None and (
            self._inbox_root == self._staging_root
            or self._inbox_root.is_relative_to(self._staging_root)
            or self._staging_root.is_relative_to(self._inbox_root)
        ):
            raise ValueError("WeChat draft inbox and staging roots must be independent")

    def stage_weekly(self, source_directory: Path) -> WeChatDraftArtifactBatch:
        try:
            edition = load_finalized_weekly_edition(source_directory)
            target = self._target(edition.zip_sha256)
            self._staging_root.mkdir(parents=True, exist_ok=True)
            if _path_has_symlink_component(self._staging_root):
                raise ValueError("WeChat draft staging root cannot contain symlinks")
            if target.exists() or target.is_symlink():
                staged = load_finalized_weekly_edition(target)
                if staged.zip_sha256 != edition.zip_sha256:
                    raise ValueError("staged WeChat draft artifact identity changed")
                return _batch_projection(staged)

            temporary = Path(
                tempfile.mkdtemp(
                    prefix=f".{target.name}.",
                    dir=self._staging_root,
                )
            )
            clean_temporary = True
            try:
                for relative, body in edition.files.items():
                    path = temporary.joinpath(*PurePosixPath(relative).parts)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                (temporary / edition.bundle_filename).write_bytes(edition.zip_bytes)
                try:
                    temporary.rename(target)
                except OSError:
                    if not target.exists():
                        raise
                    staged = load_finalized_weekly_edition(target)
                    if staged.zip_sha256 != edition.zip_sha256:
                        raise ValueError("staged WeChat draft artifact identity changed") from None
                else:
                    clean_temporary = False
            finally:
                if clean_temporary and temporary.exists():
                    shutil.rmtree(temporary)
            staged = load_finalized_weekly_edition(target)
            if staged.zip_sha256 != edition.zip_sha256:
                raise ValueError("staged WeChat draft artifact identity changed")
            return _batch_projection(staged)
        except WeeklyEditionLiveProvenanceError:
            raise
        except (OSError, ValueError) as exc:
            raise WeChatDraftArtifactError("WeChat draft artifact staging failed") from exc

    def resolve(self, source_ref: str) -> ResolvedWeChatDraftArtifactSource:
        try:
            aggregate_fingerprint, role = _parse_source_ref(source_ref)
            edition = load_finalized_weekly_edition(self._target(aggregate_fingerprint))
            if edition.zip_sha256 != aggregate_fingerprint:
                raise ValueError("WeChat draft artifact aggregate identity changed")
            batch = _batch_projection(edition)
            source = batch.sources[role.ordinal - 1]
            if source.source_ref != source_ref:
                raise ValueError("WeChat draft artifact source ref changed")
            directory = edition.directory / f"articles/{role.ordinal:02d}-{role.value}"
            return ResolvedWeChatDraftArtifactSource(
                directory=directory,
                source=source,
                batch_fingerprint=edition.batch_fingerprint,
                aggregate_fingerprint=edition.zip_sha256,
            )
        except WeeklyEditionLiveProvenanceError:
            raise
        except (OSError, ValueError) as exc:
            raise WeChatDraftArtifactError("WeChat draft artifact resolution failed") from exc

    def discover_weekly(self, *, maximum: int = 100) -> WeChatDraftArtifactDiscovery:
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= _MAX_DISCOVERY_COUNT
        ):
            raise ValueError("WeChat draft discovery bound is invalid")
        if self._inbox_root is None:
            raise ValueError("WeChat draft artifact inbox is not configured")
        if not self._inbox_root.exists():
            return WeChatDraftArtifactDiscovery(batches=(), skipped_by_code={})
        if (
            not self._inbox_root.is_dir()
            or self._inbox_root.is_symlink()
            or _path_has_symlink_component(self._inbox_root)
        ):
            raise ValueError("WeChat draft artifact inbox is unsafe")
        candidates = nsmallest(
            maximum,
            (
                candidate
                for candidate in self._inbox_root.iterdir()
                if candidate.name.startswith("official-account-weekly-edition-")
            ),
            key=lambda item: item.name,
        )
        batches: dict[str, WeChatDraftArtifactBatch] = {}
        skipped: Counter[str] = Counter()
        for candidate in candidates:
            try:
                batch = self.stage_weekly(candidate)
            except WeeklyEditionLiveProvenanceError:
                skipped[WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED] += 1
            except WeChatDraftArtifactError:
                skipped[WECHAT_DRAFT_ARTIFACT_INVALID] += 1
            else:
                batches.setdefault(batch.aggregate_fingerprint, batch)
        return WeChatDraftArtifactDiscovery(
            batches=tuple(batches[key] for key in sorted(batches)),
            skipped_by_code=dict(skipped),
        )

    def _target(self, aggregate_fingerprint: str) -> Path:
        if not _is_sha256(aggregate_fingerprint):
            raise ValueError("WeChat draft aggregate fingerprint is invalid")
        target = self._staging_root / f"official-account-weekly-edition-{aggregate_fingerprint}"
        if target.parent != self._staging_root:
            raise ValueError("WeChat draft artifact target escaped its root")
        return target


def _batch_projection(edition: FinalizedWeeklyEdition) -> WeChatDraftArtifactBatch:
    sources = tuple(
        WeChatDraftArtifactSource(
            role=child.role.value,
            ordinal=child.role.ordinal,
            source_ref=(
                f"{WECHAT_DRAFT_ARTIFACT_REF_VERSION}:{edition.zip_sha256}:{child.role.value}"
            ),
            source_fingerprint=child.artifact_fingerprint,
            article_fingerprint=child.article_fingerprint,
            content_fingerprint=child.content_fingerprint,
            child_zip_sha256=child.child_zip_sha256,
        )
        for child in edition.children
    )
    return WeChatDraftArtifactBatch(
        week_start=edition.week_start,
        batch_fingerprint=edition.batch_fingerprint,
        aggregate_fingerprint=edition.zip_sha256,
        sources=cast(
            tuple[
                WeChatDraftArtifactSource,
                WeChatDraftArtifactSource,
                WeChatDraftArtifactSource,
            ],
            sources,
        ),
    )


def _parse_source_ref(value: str) -> tuple[str, WeeklyArticleRole]:
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError("WeChat draft source ref is invalid")
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != WECHAT_DRAFT_ARTIFACT_REF_VERSION:
        raise ValueError("WeChat draft source ref is invalid")
    aggregate_fingerprint = parts[1]
    if not _is_sha256(aggregate_fingerprint):
        raise ValueError("WeChat draft source ref is invalid")
    try:
        role = WeeklyArticleRole(parts[2])
    except ValueError as exc:
        raise ValueError("WeChat draft source ref is invalid") from exc
    return aggregate_fingerprint, role


def _validated_root(value: Path, *, label: str) -> Path:
    raw = value.expanduser().absolute()
    if raw == Path(raw.anchor) or _path_has_symlink_component(raw):
        raise ValueError(f"WeChat draft artifact {label} root is unsafe")
    return raw.resolve()


def _path_has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = ["LocalWeChatDraftArtifactStore"]
