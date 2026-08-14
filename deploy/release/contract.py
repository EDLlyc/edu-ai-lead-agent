from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Final, cast
from urllib.parse import urlsplit

SCHEMA_VERSION: Final = 1
COMMIT_RE: Final = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
RFC3339_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
IMAGE_REPOSITORY_RE: Final = re.compile(
    r"^[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*){2,}$"
)
READABLE_TAG_RE: Final = re.compile(r"^git-[0-9a-f]{12}$")
MAX_BUNDLE_MEMBERS: Final = 512
MAX_BUNDLE_MEMBER_BYTES: Final = 32 * 1024 * 1024
MAX_BUNDLE_BYTES: Final = 128 * 1024 * 1024

BUNDLE_ALLOWED_PREFIXES: Final[tuple[str, ...]] = (
    "compose.yaml",
    "backend/alembic.ini",
    "backend/alembic/versions/",
    "scripts/edu-ai-backup.sh",
    "scripts/edu-ai-deploy.sh",
    "scripts/edu-ai-production-evidence.sh",
    "scripts/edu-ai-release-common.sh",
    "deploy/release/contract.py",
    "deploy/release/deploy.py",
    "deploy/release/migration-compatibility.json",
    "deploy/release/release-manifest.schema.json",
    "deploy/release/release_tool.py",
)
BUNDLE_REQUIRED_FILES: Final[frozenset[str]] = frozenset(
    {
        "compose.yaml",
        "backend/alembic.ini",
        "scripts/edu-ai-backup.sh",
        "scripts/edu-ai-deploy.sh",
        "scripts/edu-ai-production-evidence.sh",
        "scripts/edu-ai-release-common.sh",
        "deploy/release/contract.py",
        "deploy/release/deploy.py",
        "deploy/release/migration-compatibility.json",
        "deploy/release/release-manifest.schema.json",
        "deploy/release/release_tool.py",
    }
)
REQUIRED_GATES: Final[frozenset[str]] = frozenset(
    {
        "api-contract",
        "backend",
        "compose",
        "doctor",
        "frontend",
        "image-runtime",
        "lock-drift",
        "secret-scan",
        "shell-syntax",
    }
)
SECRET_PATTERNS: Final[tuple[re.Pattern[bytes], ...]] = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"AKID[A-Za-z0-9]{16,}"),
    re.compile(rb"LTAI[A-Za-z0-9]{12,}"),
    re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@"),
)


class ContractError(ValueError):
    """A release input violates the versioned delivery contract."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require_exact_keys(
    value: Mapping[str, object], expected: set[str], context: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ContractError(
            f"{context} keys mismatch (missing={missing}, unexpected={unexpected})"
        )


def require_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{context} must be a non-empty string")
    return value


def require_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{context} must be a boolean")
    return value


def validate_commit(value: str) -> str:
    if COMMIT_RE.fullmatch(value) is None:
        raise ContractError("source commit must be 40 lowercase hexadecimal characters")
    return value


def validate_digest(value: str) -> str:
    if DIGEST_RE.fullmatch(value) is None:
        raise ContractError(
            "image digest must use sha256 followed by 64 lowercase hex characters"
        )
    return value


def split_digest_image(value: str) -> tuple[str, str]:
    if "@" not in value:
        raise ContractError(
            "image reference must be digest-only; mutable tags are prohibited"
        )
    repository, digest = value.rsplit("@", 1)
    if IMAGE_REPOSITORY_RE.fullmatch(repository) is None:
        raise ContractError(
            "image repository must include registry, namespace, and repository"
        )
    return repository, validate_digest(digest)


def validate_source_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
        raise ContractError("source URL must be an HTTPS or SSH repository URL")
    if parsed.password is not None:
        raise ContractError("source URL must not contain credentials")
    if parsed.scheme == "https" and parsed.username is not None:
        raise ContractError("HTTPS source URL must not contain user information")
    if parsed.query or parsed.fragment:
        raise ContractError("source URL must not contain a query or fragment")
    return value


def safe_bundle_path(value: str) -> str:
    if not value or "\\" in value:
        raise ContractError("bundle member path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError(f"unsafe bundle member path: {value!r}")
    normalized = str(path)
    if normalized != value:
        raise ContractError(f"bundle member path is not normalized: {value!r}")
    if not any(
        normalized == prefix or (prefix.endswith("/") and normalized.startswith(prefix))
        for prefix in BUNDLE_ALLOWED_PREFIXES
    ):
        raise ContractError(
            f"bundle member is outside the runtime allowlist: {value!r}"
        )
    return normalized


def scan_secret_shaped_content(path: str, value: bytes) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(value) is not None:
            raise ContractError(
                f"secret-shaped content rejected in bundle member: {path}"
            )


@dataclass(frozen=True)
class SourceContract:
    commit: str
    release_marker: str
    url: str


@dataclass(frozen=True)
class ImageContract:
    reference: str
    repository: str
    digest: str
    readable_tag: str


@dataclass(frozen=True)
class BuildContract:
    created: str
    dockerfile_sha256: str
    python_base: str
    runtime_lock_sha256: str
    dev_lock_sha256: str


@dataclass(frozen=True)
class BundleContract:
    file: str
    sha256: str
    member_manifest_sha256: str


@dataclass(frozen=True)
class DatabaseContract:
    alembic_head: str
    compatibility_declaration_sha256: str
    compatibility_reviewed: bool
    previous_application_compatible: bool


@dataclass(frozen=True)
class GateContract:
    name: str
    result_id: str


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    source: SourceContract
    image: ImageContract
    build: BuildContract
    bundle: BundleContract
    database: DatabaseContract
    gates: tuple[GateContract, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source": {
                "commit": self.source.commit,
                "release_marker": self.source.release_marker,
                "url": self.source.url,
            },
            "image": {
                "reference": self.image.reference,
                "repository": self.image.repository,
                "digest": self.image.digest,
                "readable_tag": self.image.readable_tag,
            },
            "build": {
                "created": self.build.created,
                "dockerfile_sha256": self.build.dockerfile_sha256,
                "python_base": self.build.python_base,
                "runtime_lock_sha256": self.build.runtime_lock_sha256,
                "dev_lock_sha256": self.build.dev_lock_sha256,
            },
            "bundle": {
                "file": self.bundle.file,
                "sha256": self.bundle.sha256,
                "member_manifest_sha256": self.bundle.member_manifest_sha256,
            },
            "database": {
                "alembic_head": self.database.alembic_head,
                "compatibility_declaration_sha256": (
                    self.database.compatibility_declaration_sha256
                ),
                "compatibility_reviewed": self.database.compatibility_reviewed,
                "previous_application_compatible": (
                    self.database.previous_application_compatible
                ),
            },
            "gates": [
                {"name": gate.name, "result_id": gate.result_id} for gate in self.gates
            ],
        }


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{context} must be an object")
    return cast(dict[str, object], value)


def parse_release_manifest(value: object) -> ReleaseManifest:
    root = _object(value, "release manifest")
    require_exact_keys(
        root,
        {"schema_version", "source", "image", "build", "bundle", "database", "gates"},
        "release manifest",
    )
    if root["schema_version"] != SCHEMA_VERSION:
        raise ContractError(
            f"unsupported release manifest schema: {root['schema_version']!r}"
        )

    source_value = _object(root["source"], "source")
    require_exact_keys(source_value, {"commit", "release_marker", "url"}, "source")
    commit = validate_commit(require_string(source_value["commit"], "source.commit"))
    release_marker = require_string(
        source_value["release_marker"], "source.release_marker"
    )
    if release_marker != commit[:12]:
        raise ContractError(
            "release marker must be the first 12 characters of the commit"
        )
    source = SourceContract(
        commit=commit,
        release_marker=release_marker,
        url=validate_source_url(require_string(source_value["url"], "source.url")),
    )

    image_value = _object(root["image"], "image")
    require_exact_keys(
        image_value, {"reference", "repository", "digest", "readable_tag"}, "image"
    )
    image_reference = require_string(image_value["reference"], "image.reference")
    repository, digest = split_digest_image(image_reference)
    if require_string(image_value["repository"], "image.repository") != repository:
        raise ContractError("image repository does not match the digest reference")
    if require_string(image_value["digest"], "image.digest") != digest:
        raise ContractError("image digest does not match the digest reference")
    readable_tag = require_string(image_value["readable_tag"], "image.readable_tag")
    if (
        READABLE_TAG_RE.fullmatch(readable_tag) is None
        or readable_tag != f"git-{commit[:12]}"
    ):
        raise ContractError(
            "readable image tag must be git- followed by the commit marker"
        )
    image = ImageContract(image_reference, repository, digest, readable_tag)

    build_value = _object(root["build"], "build")
    require_exact_keys(
        build_value,
        {
            "created",
            "dockerfile_sha256",
            "python_base",
            "runtime_lock_sha256",
            "dev_lock_sha256",
        },
        "build",
    )
    created = require_string(build_value["created"], "build.created")
    if RFC3339_RE.fullmatch(created) is None:
        raise ContractError(
            "build.created must be an RFC3339 UTC timestamp without fractions"
        )
    hashes = {
        name: require_string(build_value[name], f"build.{name}")
        for name in ("dockerfile_sha256", "runtime_lock_sha256", "dev_lock_sha256")
    }
    if any(SHA256_RE.fullmatch(item) is None for item in hashes.values()):
        raise ContractError("build input hashes must be lowercase SHA-256 values")
    python_base = require_string(build_value["python_base"], "build.python_base")
    if "@sha256:" not in python_base:
        raise ContractError("Python base image must be pinned by digest")
    build = BuildContract(created=created, python_base=python_base, **hashes)

    bundle_value = _object(root["bundle"], "bundle")
    require_exact_keys(
        bundle_value, {"file", "sha256", "member_manifest_sha256"}, "bundle"
    )
    bundle_file = require_string(bundle_value["file"], "bundle.file")
    if bundle_file != f"release-bundle-{commit}.tar.gz":
        raise ContractError("bundle filename must contain the full source commit")
    bundle_hash = require_string(bundle_value["sha256"], "bundle.sha256")
    member_hash = require_string(
        bundle_value["member_manifest_sha256"], "bundle.member_manifest_sha256"
    )
    if (
        SHA256_RE.fullmatch(bundle_hash) is None
        or SHA256_RE.fullmatch(member_hash) is None
    ):
        raise ContractError("bundle hashes must be lowercase SHA-256 values")
    bundle = BundleContract(bundle_file, bundle_hash, member_hash)

    database_value = _object(root["database"], "database")
    require_exact_keys(
        database_value,
        {
            "alembic_head",
            "compatibility_declaration_sha256",
            "compatibility_reviewed",
            "previous_application_compatible",
        },
        "database",
    )
    alembic_head = require_string(
        database_value["alembic_head"], "database.alembic_head"
    )
    if SAFE_ID_RE.fullmatch(alembic_head) is None:
        raise ContractError("Alembic head is not a safe identifier")
    declaration_hash = require_string(
        database_value["compatibility_declaration_sha256"],
        "database.compatibility_declaration_sha256",
    )
    if SHA256_RE.fullmatch(declaration_hash) is None:
        raise ContractError("compatibility declaration hash must be a SHA-256 value")
    database = DatabaseContract(
        alembic_head=alembic_head,
        compatibility_declaration_sha256=declaration_hash,
        compatibility_reviewed=require_bool(
            database_value["compatibility_reviewed"], "database.compatibility_reviewed"
        ),
        previous_application_compatible=require_bool(
            database_value["previous_application_compatible"],
            "database.previous_application_compatible",
        ),
    )
    if database.previous_application_compatible and not database.compatibility_reviewed:
        raise ContractError(
            "previous-application compatibility requires an explicit review"
        )

    gates_value = root["gates"]
    if not isinstance(gates_value, list):
        raise ContractError("gates must be a list")
    gates: list[GateContract] = []
    for index, item in enumerate(gates_value):
        gate_value = _object(item, f"gates[{index}]")
        require_exact_keys(gate_value, {"name", "result_id"}, f"gates[{index}]")
        name = require_string(gate_value["name"], f"gates[{index}].name")
        result_id = require_string(gate_value["result_id"], f"gates[{index}].result_id")
        if (
            SAFE_ID_RE.fullmatch(name) is None
            or SAFE_ID_RE.fullmatch(result_id) is None
        ):
            raise ContractError(
                "gate names and result IDs must be safe audit identifiers"
            )
        gates.append(GateContract(name, result_id))
    gate_names = [gate.name for gate in gates]
    if frozenset(gate_names) != REQUIRED_GATES or len(gate_names) != len(
        REQUIRED_GATES
    ):
        raise ContractError(
            f"release manifest must contain exactly these gates: {sorted(REQUIRED_GATES)}"
        )

    return ReleaseManifest(
        SCHEMA_VERSION, source, image, build, bundle, database, tuple(gates)
    )


def load_release_manifest(path: Path) -> ReleaseManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("release manifest is not readable JSON") from exc
    return parse_release_manifest(value)


def dump_release_manifest(manifest: ReleaseManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _read_limited(handle: IO[bytes], size: int) -> bytes:
    if size > MAX_BUNDLE_MEMBER_BYTES:
        raise ContractError("bundle member exceeds the size limit")
    value = handle.read(size + 1)
    if len(value) != size:
        raise ContractError("bundle member size does not match its header")
    return value


def read_release_bundle(
    bundle_path: Path,
) -> tuple[dict[str, tuple[bytes, int]], bytes]:
    if bundle_path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ContractError("release bundle exceeds the size limit")
    members: dict[str, tuple[bytes, int]] = {}
    member_manifest: bytes | None = None
    total_size = 0
    try:
        with tarfile.open(bundle_path, mode="r:gz") as archive:
            archive_members = archive.getmembers()
            if len(archive_members) > MAX_BUNDLE_MEMBERS:
                raise ContractError("release bundle has too many members")
            for member in archive_members:
                if not member.isfile():
                    raise ContractError("release bundle may contain regular files only")
                if member.name == "RELEASE-MEMBERS.sha256":
                    normalized = member.name
                else:
                    normalized = safe_bundle_path(member.name)
                if normalized in members or (
                    normalized == "RELEASE-MEMBERS.sha256"
                    and member_manifest is not None
                ):
                    raise ContractError(
                        f"duplicate release bundle member: {normalized}"
                    )
                total_size += member.size
                if total_size > MAX_BUNDLE_BYTES:
                    raise ContractError(
                        "uncompressed release bundle exceeds the size limit"
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ContractError(f"unable to read bundle member: {normalized}")
                content = _read_limited(extracted, member.size)
                mode = member.mode & 0o777
                if normalized == "RELEASE-MEMBERS.sha256":
                    member_manifest = content
                else:
                    members[normalized] = (content, mode)
    except (OSError, tarfile.TarError) as exc:
        raise ContractError("release bundle is not a valid gzip tar archive") from exc
    if member_manifest is None:
        raise ContractError("release bundle is missing RELEASE-MEMBERS.sha256")
    if not BUNDLE_REQUIRED_FILES.issubset(members):
        missing = sorted(BUNDLE_REQUIRED_FILES - set(members))
        raise ContractError(f"release bundle is missing required files: {missing}")
    return members, member_manifest


def parse_member_manifest(value: bytes) -> dict[str, str]:
    try:
        lines = value.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ContractError("member manifest must be UTF-8") from exc
    expected: dict[str, str] = {}
    for line in lines:
        if not line or len(line) < 67 or line[64:66] != "  ":
            raise ContractError("member manifest has an invalid line")
        digest = line[:64]
        path = safe_bundle_path(line[66:])
        if SHA256_RE.fullmatch(digest) is None or path in expected:
            raise ContractError("member manifest has an invalid or duplicate entry")
        expected[path] = digest
    return expected


def verify_release_bundle(
    bundle_path: Path, manifest: ReleaseManifest, extract_to: Path | None = None
) -> dict[str, tuple[bytes, int]]:
    if bundle_path.name != manifest.bundle.file:
        raise ContractError("bundle path does not match the manifest filename")
    if sha256_file(bundle_path) != manifest.bundle.sha256:
        raise ContractError("release bundle checksum mismatch")
    members, member_manifest = read_release_bundle(bundle_path)
    if sha256_bytes(member_manifest) != manifest.bundle.member_manifest_sha256:
        raise ContractError("release member-manifest checksum mismatch")
    expected = parse_member_manifest(member_manifest)
    if set(expected) != set(members):
        raise ContractError(
            "release member manifest does not match the archive member set"
        )
    for path, (content, _mode) in members.items():
        if sha256_bytes(content) != expected[path]:
            raise ContractError(f"release member checksum mismatch: {path}")
    declaration = members["deploy/release/migration-compatibility.json"][0]
    if sha256_bytes(declaration) != manifest.database.compatibility_declaration_sha256:
        raise ContractError("migration compatibility declaration checksum mismatch")
    migration_blobs = {
        path: content
        for path, (content, _mode) in members.items()
        if path.startswith("backend/alembic/versions/")
        and path.endswith(".py")
        and "/__" not in path
    }
    if not migration_blobs:
        raise ContractError("release bundle contains no Alembic migrations")
    if alembic_head_from_blobs(migration_blobs) != manifest.database.alembic_head:
        raise ContractError("release bundle Alembic head does not match the manifest")
    reviewed, compatible = load_compatibility_declaration(
        declaration, manifest.database.alembic_head
    )
    if (
        reviewed != manifest.database.compatibility_reviewed
        or compatible != manifest.database.previous_application_compatible
    ):
        raise ContractError(
            "migration compatibility declaration does not match the manifest"
        )
    if extract_to is not None:
        if extract_to.is_symlink():
            raise ContractError("release extraction directory must not be a symlink")
        if extract_to.exists() and any(extract_to.iterdir()):
            raise ContractError("release extraction directory must be empty")
        extract_to.mkdir(parents=True, mode=0o700, exist_ok=True)
        for name, (content, mode) in members.items():
            destination = extract_to.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o755 if mode & 0o111 else 0o644)
    return members


def git_output(repository: Path, arguments: Sequence[str]) -> bytes:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=repository, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError(
            "unable to read the requested committed Git object"
        ) from exc


def git_blob(repository: Path, commit: str, path: str) -> bytes:
    validate_commit(commit)
    return git_output(repository, ["show", f"{commit}:{path}"])


def _assignment_value(tree: ast.Module, name: str) -> object:
    for statement in tree.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
            and statement.value is not None
        ):
            return ast.literal_eval(statement.value)
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    raise ContractError(f"migration is missing {name}")


def alembic_head_from_blobs(blobs: Mapping[str, bytes]) -> str:
    revision_paths: dict[str, str] = {}
    revision_parents: dict[str, tuple[str, ...]] = {}
    parents: set[str] = set()
    for path, content in blobs.items():
        try:
            tree = ast.parse(content.decode("utf-8"), filename=path)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise ContractError(f"unable to parse migration: {path}") from exc
        revision = _assignment_value(tree, "revision")
        down_revision = _assignment_value(tree, "down_revision")
        if not isinstance(revision, str) or not revision:
            raise ContractError(f"migration revision is invalid: {path}")
        if revision in revision_paths:
            raise ContractError(
                "duplicate migration revision "
                f"{revision!r}: {revision_paths[revision]} and {path}"
            )
        revision_paths[revision] = path
        if isinstance(down_revision, str):
            revision_parents[revision] = (down_revision,)
            parents.add(down_revision)
        elif isinstance(down_revision, tuple):
            if not all(isinstance(item, str) for item in down_revision):
                raise ContractError(f"migration parent is invalid: {path}")
            typed_parents = cast(tuple[str, ...], down_revision)
            revision_parents[revision] = typed_parents
            parents.update(typed_parents)
        elif down_revision is not None:
            raise ContractError(f"migration parent is invalid: {path}")
        else:
            revision_parents[revision] = ()
    revisions = set(revision_paths)
    missing_parents = parents - revisions
    if missing_parents:
        raise ContractError(
            f"migration graph has missing parents: {sorted(missing_parents)}"
        )
    heads = revisions - parents
    if len(heads) != 1:
        raise ContractError(
            f"exactly one Alembic head is required (found: {sorted(heads)})"
        )
    head = next(iter(heads))
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(revision: str) -> None:
        if revision in visiting:
            raise ContractError("migration graph contains a cycle")
        if revision in visited:
            return
        visiting.add(revision)
        for parent in revision_parents[revision]:
            visit(parent)
        visiting.remove(revision)
        visited.add(revision)

    visit(head)
    if visited != revisions:
        raise ContractError(
            f"migration graph is disconnected: {sorted(revisions - visited)}"
        )
    return head


def load_compatibility_declaration(
    value: bytes, expected_head: str
) -> tuple[bool, bool]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(
            "migration compatibility declaration is invalid JSON"
        ) from exc
    declaration = _object(parsed, "migration compatibility declaration")
    require_exact_keys(
        declaration,
        {
            "schema_version",
            "alembic_head",
            "reviewed",
            "previous_application_compatible",
            "reason",
        },
        "migration compatibility declaration",
    )
    if declaration["schema_version"] != 1:
        raise ContractError("unsupported migration compatibility declaration schema")
    if require_string(declaration["alembic_head"], "alembic_head") != expected_head:
        raise ContractError(
            "migration compatibility declaration does not match Alembic head"
        )
    reviewed = require_bool(declaration["reviewed"], "reviewed")
    compatible = require_bool(
        declaration["previous_application_compatible"],
        "previous_application_compatible",
    )
    reason = require_string(declaration["reason"], "reason")
    if len(reason) < 20 or len(reason) > 500:
        raise ContractError(
            "migration compatibility reason must be between 20 and 500 characters"
        )
    if compatible and not reviewed:
        raise ContractError("backward compatibility cannot be declared without review")
    return reviewed, compatible
