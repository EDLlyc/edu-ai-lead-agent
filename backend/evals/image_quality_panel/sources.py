"""Fail-closed source catalog loading and Git/content provenance checks."""

from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from .models import IMAGE_PANEL_AUTHORIZATION_BASIS, SourceArtifact, SourceCatalog

FEATURE_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_CATALOG = FEATURE_ROOT / "sources.v1.json"
REPOSITORY_ROOT = FEATURE_ROOT.parents[2]
MAX_CATALOG_BYTES = 128 * 1024
APPROVED_SOURCE_PREFIX = Path("docs/portfolio/assets/content-showcase")


class ImagePanelSourceError(ValueError):
    """A public-source provenance or authorization assertion failed."""


def load_source_catalog(path: Path = DEFAULT_SOURCE_CATALOG) -> SourceCatalog:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ImagePanelSourceError("source catalog could not be read") from exc
    if not payload or len(payload) > MAX_CATALOG_BYTES:
        raise ImagePanelSourceError("source catalog has an invalid byte length")
    try:
        raw: Any = json.loads(payload)
        if not isinstance(raw, dict):
            raise TypeError
        catalog = SourceCatalog.model_validate_json(payload)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ImagePanelSourceError("source catalog failed strict schema validation") from exc
    if catalog.external_model_use_basis != IMAGE_PANEL_AUTHORIZATION_BASIS:
        raise ImagePanelSourceError("source catalog is missing the approved external-use basis")
    return catalog


def preflight_sources(
    catalog: SourceCatalog,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> None:
    """Verify tracked clean bytes, Git blobs, formats, dimensions, and public-only paths."""

    root = repository_root.resolve(strict=True)
    artifacts = (*catalog.sources, *catalog.derivatives)
    source_by_path = {item.repository_path: item for item in catalog.sources}
    for artifact in artifacts:
        _validate_public_relative_path(artifact.repository_path)
        if artifact.derivative_of is not None:
            _validate_public_relative_path(artifact.derivative_of)
            parent = source_by_path.get(artifact.derivative_of)
            if parent is None or parent.source_family != artifact.source_family:
                raise ImagePanelSourceError("derivative provenance does not resolve to its family")
        absolute = (root / artifact.repository_path).resolve(strict=True)
        if root not in absolute.parents:
            raise ImagePanelSourceError("source path escapes the repository")
        _verify_git_state(root, artifact)
        try:
            content = absolute.read_bytes()
        except OSError as exc:
            raise ImagePanelSourceError("source bytes could not be read") from exc
        if (
            len(content) != artifact.byte_size
            or sha256(content).hexdigest() != artifact.content_sha256
        ):
            raise ImagePanelSourceError("source content hash or size drifted")
        try:
            with Image.open(absolute) as image:
                image.load()
                actual_media = Image.MIME.get(image.format or "")
                actual_dimensions = image.size
        except (OSError, UnidentifiedImageError) as exc:
            raise ImagePanelSourceError("source is not a decodable approved image") from exc
        if actual_media != artifact.media_type or actual_dimensions != (
            artifact.width,
            artifact.height,
        ):
            raise ImagePanelSourceError("source media type or dimensions drifted")


def catalog_sha256(path: Path = DEFAULT_SOURCE_CATALOG) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _validate_public_relative_path(value: str) -> None:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ImagePanelSourceError("source path must be repository-relative")
    if tuple(candidate.parts[: len(APPROVED_SOURCE_PREFIX.parts)]) != APPROVED_SOURCE_PREFIX.parts:
        raise ImagePanelSourceError("source path is outside the approved public portfolio tree")
    lowered = tuple(part.lower() for part in candidate.parts)
    if "private" in lowered:
        raise ImagePanelSourceError("private source paths are forbidden")


def _verify_git_state(repository_root: Path, artifact: SourceArtifact) -> None:
    status = _git(repository_root, "status", "--porcelain", "--", artifact.repository_path)
    if status:
        raise ImagePanelSourceError("source working-tree bytes are dirty")
    tracked = _git(repository_root, "ls-files", "-s", "--", artifact.repository_path)
    fields = tracked.split()
    if len(fields) < 4 or fields[1] != artifact.git_blob_oid:
        raise ImagePanelSourceError("source is untracked or its Git blob drifted")


def _git(repository_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ImagePanelSourceError("Git source provenance check failed") from exc
    return completed.stdout.strip()
