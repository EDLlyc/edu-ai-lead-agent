#!/usr/bin/env python3
"""Validate the exact d2e709c OCI image plus one no-source-link overlay."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

BASE_MANIFEST = (
    "sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d"
)
BASE_LAYERS = (
    "039e6f9f9752f74a3ff4a6a224f64c7c864da16ed98f882107704328f41b9c42",
    "a818f21dc3b91f21ff6a387603a68f05631236d4ef4da78c62263192f17efc5f",
    "51dd2349a5f3cda316dcc78934383fdd473c905d1070f1c822e4011c39e23774",
    "87e3be58ade05b9abd82eedde89ebfca06a7d656332edb0991939c130f9e32bd",
    "1801b54e6628a3234e0affa301f36224956b955d6d44903766d36ef6b9b40f5f",
    "2d236b05cd280c6f4ea3306b899cd52f76b6b70b9030d1c4ec0e34d526c5cc19",
    "916cd6cfcc7ddea0374b2aa5776ccb428f6c7235b22b2f9b883e66b17719c6d1",
    "3ce7f2a0a4c5341ff795dc28dcbb0e9fa5467529bc0f63dceb1edb740968687a",
    "00c9d30a24f2f1ff9b75ddb92c88f2dd0cc22bccef6237b41c540e81154a1b82",
    "ab976485073bac4d273250f05bee6dea658da5c832539bdf51cd956c8bd5ac0a",
    "e5c9deafb3cfda8cb9a41705ce224a591dd4ea03ba12b15f86ef43c7dad41890",
    "7df225901963f40df52726a3be003ea8f9c52e7168b4f22f7c610b53ff25a036",
    "d58e165229a98e75c9e2619f0e92bd40271af63c157099b64d6f523466e59efe",
    "17c3264be9961f7ac63ef68191a4313057f42e2dae226418504174da4a44ea7c",
    "d9df3569adb07f926b3dbfa68b6201c1ad589b13430bd70c839d896b268b9c9d",
    "bffa617748f48cc00eca900e93fde4fa4f3a52daad7540527a77898c51922b77",
    "013c97fc78f88dff32ddebc1fbe00563860bf7ff09f2d5e919c215f1dec08786",
    "6cec53db322199f1e3d490d40cb09e8b349ef4823c7298487debce0688af1d41",
)
BASE_DIFF_IDS = (
    "66462cc862fe2053b9863fefa3866e07bb5dfb06f6b3ce3177cc096e4021aabe",
    "54c5eda61868d7dbad42805ea56c87d48d0815597ddc095caddf3e72b81ebe4f",
    "04165bb9c9967c1f86a946005f39b3173b579df051ba5e74b7c440b5a823cf77",
    "28bcd18f93ba7019548c762541202753207f26b316a4ca5ce96bc356d8032c7f",
    "5f605a32956a804468c84ee5e76baa4950ad593b66e70f6a45859e1808e2e17d",
    "c9b257d38fff073b5e0952703f639314ee5f7272467f741d179ba66bca2bea01",
    "db5d089c7debbce095106e7153fa3422676739006613ffaab4d4032dd30aa918",
    "7a9237a759e91730a52f2472355ff6388ac171eca4f0eb370501f39844380192",
    "d8c6f3971088100b35656bd4e7bbfc9a3024eec22e1dbfda49aaf7ed23cf0162",
    "f10b4d99fbbe22e786dca4a854df584d6619785e84629a39a3b9453690cdfb46",
    "c0a88694b9bef371923891d8c4b61b125bc8ecd58272f55173092bced7fe9553",
    "b30f37f21f280c946e848c8401471ef8fe42be463526763b421efbb34480d894",
    "249f21e7c0a43b9a85ce95891eb2a0464a73f70a1932f925c56b7699e0408cce",
    "d0b8cc29cfc33719569b9cfa77bcea1c3602cd2a4562c289faa41439c362b18b",
    "9853840008213adb8e9b622482bd9809a6976d17ff8620b3172f6a4a352173bb",
    "de8e48744712b778f6a65691a1fbe10f40cbf7fff2d1308577e1f9321ce2dde2",
    "415b08adbce2f07e8a6161ac6587c169bbb2ad8f2344d421421b0ad8d534fb2e",
    "a08cf12a957f75ec1e18c3d4707c8095e19d763423bfaa488fc0106f33374977",
)
BASE_RUNTIME_SHA256 = "f296ca659261fbd508b5663507e61a485dd1f7706c4cf5a3998c72e986c01414"
BASE_HISTORY_SHA256 = "ff62b2901abf3b00b19988bf053f4b8ba78a039994f9910962e6acc784808357"
BASE_TOP_LEVEL_SHA256 = (
    "1b1b7cc9f51078db8ab76b1a49e07311138b037a64dcf59ab8b02ead6df40679"
)
OVERLAY_FILES = {
    "domain/official_account_source_presentation.py": "6bd12a2e24551ffaca1cd370d3284169463602ac8bcff0390a7dd693e77fb57a",
    "domain/official_account_editor_handoff_v2.py": "0851427717287b591ba6f9835abec530c978619a3da7a538d8dbbca9df34fd65",
    "application/services/official_account_strict_prepared.py": "919ff0a12cc015d9b5815022f7a3e0369cdb5cb90763c8b3a47e8df38435a6b1",
    "application/services/wechat_official_account_draft.py": "b116c3dba73623778f78c04c0d49f6292bdbb348b8ebd3f28046cd7b35c4965a",
    "infrastructure/wechat_official_account/prepared_artifacts.py": "70de4170346170a28b72daf1e24993f3b412d09519868cfc1e90d8855b002050",
}
SHA256 = re.compile(r"[0-9a-f]{64}")
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"


def fail(code: str) -> NoReturn:
    raise ValueError(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json(value: bytes, code: str) -> Any:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                fail(code)
            result[key] = item
        return result

    try:
        text = value.decode("utf-8")
        result = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: fail(code),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not text or text.strip() != text or "\r" in text:
        fail(code)
    return result


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def descriptor(
    value: object, media_type: str, blobs: dict[str, bytes]
) -> tuple[str, bytes]:
    if not isinstance(value, dict) or set(value) != {"mediaType", "digest", "size"}:
        fail("descriptor_shape")
    raw_digest = value.get("digest")
    size = value.get("size")
    if (
        value.get("mediaType") != media_type
        or not isinstance(raw_digest, str)
        or not raw_digest.startswith("sha256:")
        or SHA256.fullmatch(raw_digest[7:]) is None
        or type(size) is not int
    ):
        fail("descriptor_value")
    key = "blobs/sha256/" + raw_digest[7:]
    body = blobs.get(key)
    if body is None or len(body) != size or digest(body) != raw_digest[7:]:
        fail("descriptor_binding")
    return raw_digest, body


def safe_members(archive: Path) -> dict[str, bytes]:
    if (
        not archive.is_absolute()
        or archive.is_symlink()
        or archive.stat().st_size > 512 * 1024 * 1024
    ):
        fail("archive_path")
    values: dict[str, bytes] = {}
    seen: set[str] = set()
    directories: set[str] = set()
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or member.name in seen
                    or not (member.isfile() or member.isdir())
                ):
                    fail("archive_member")
                seen.add(member.name)
                if (
                    member.uid != 0
                    or member.gid != 0
                    or member.mode != (0o755 if member.isdir() else 0o644)
                ):
                    fail("archive_member_metadata")
                if member.isdir():
                    directories.add(member.name)
                    continue
                stream = bundle.extractfile(member)
                if stream is None or member.size > 256 * 1024 * 1024:
                    fail("archive_member")
                body = stream.read(member.size + 1)
                if len(body) != member.size:
                    fail("archive_member")
                values[member.name] = body
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("archive_unreadable") from exc
    if directories != {"blobs", "blobs/sha256"}:
        fail("archive_directories")
    return values


def validate_overlay_layer(raw: bytes) -> None:
    """Require one exact app-owned regular file for every reviewed overlay member."""
    if len(raw) > 2 * 1024 * 1024:
        fail("overlay_layer_size")
    expected = {"app/app/" + path: value for path, value in OVERLAY_FILES.items()}
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as layer:
            for member in layer:
                if (
                    member.name in seen
                    or member.name not in expected
                    or not member.isfile()
                    or member.type != tarfile.REGTYPE
                    or member.mode != 0o644
                    or member.uid != 999
                    or member.gid != 999
                    or member.uname != "app"
                    or member.gname != "app"
                    or member.mtime != 0
                    or member.linkname
                    or member.pax_headers
                ):
                    fail("overlay_layer_member")
                seen.add(member.name)
                stream = layer.extractfile(member)
                if stream is None or member.size > 1024 * 1024:
                    fail("overlay_layer_member")
                body = stream.read(member.size + 1)
                if len(body) != member.size or digest(body) != expected[member.name]:
                    fail("overlay_layer_hash")
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("overlay_layer_unreadable") from exc
    if seen != set(expected):
        fail("overlay_layer_files")


def validate(
    archive: Path,
    *,
    candidate_tag: str,
    candidate_ref: str,
    revision: str,
) -> dict[str, object]:
    blobs = safe_members(archive)
    if not {"index.json", "oci-layout"} <= set(blobs):
        fail("oci_members")
    layout = strict_json(blobs["oci-layout"], "oci_layout")
    index = strict_json(blobs["index.json"], "oci_index")
    if layout != {"imageLayoutVersion": "1.0.0"}:
        fail("oci_layout")
    if (
        not isinstance(index, dict)
        or index.get("schemaVersion") != 2
        or index.get("mediaType") != OCI_INDEX
        or not isinstance(index.get("manifests"), list)
        or len(index["manifests"]) != 1
    ):
        fail("oci_index")
    top = index["manifests"][0]
    if not isinstance(top, dict):
        fail("oci_index")
    annotations = top.get("annotations")
    platform = top.get("platform")
    top_descriptor = {key: top.get(key) for key in ("mediaType", "digest", "size")}
    manifest_digest, manifest_body = descriptor(top_descriptor, OCI_MANIFEST, blobs)
    if (
        annotations
        != {
            "io.containerd.image.name": candidate_tag,
            "org.opencontainers.image.ref.name": candidate_tag.rsplit(":", 1)[1],
        }
        or platform != {"architecture": "amd64", "os": "linux"}
        or candidate_ref != candidate_tag.rsplit(":", 1)[0] + "@" + manifest_digest
    ):
        fail("oci_identity")
    manifest = strict_json(manifest_body, "oci_manifest")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schemaVersion", "mediaType", "config", "layers"}
        or manifest["schemaVersion"] != 2
        or manifest["mediaType"] != OCI_MANIFEST
        or not isinstance(manifest["layers"], list)
        or len(manifest["layers"]) != len(BASE_LAYERS) + 1
    ):
        fail("oci_manifest")
    config_digest, config_body = descriptor(manifest["config"], OCI_CONFIG, blobs)
    layer_digests: list[str] = []
    diff_ids: list[str] = []
    overlay_raw: bytes | None = None
    for index, item in enumerate(manifest["layers"]):
        layer_digest, compressed = descriptor(item, OCI_LAYER, blobs)
        layer_digests.append(layer_digest[7:])
        try:
            raw = gzip.decompress(compressed)
        except gzip.BadGzipFile as exc:
            raise ValueError("layer_gzip") from exc
        if index == len(manifest["layers"]) - 1:
            overlay_raw = raw
        diff_ids.append(digest(raw))
    if (
        tuple(layer_digests[:-1]) != BASE_LAYERS
        or tuple(diff_ids[:-1]) != BASE_DIFF_IDS
    ):
        fail("base_graph_changed")
    if overlay_raw is None:
        fail("overlay_layer_missing")
    validate_overlay_layer(overlay_raw)
    config = strict_json(config_body, "oci_config")
    if (
        not isinstance(config, dict)
        or config.get("architecture") != "amd64"
        or config.get("os") != "linux"
        or not isinstance(config.get("config"), dict)
        or not isinstance(config.get("rootfs"), dict)
        or config["rootfs"].get("type") != "layers"
        or config["rootfs"].get("diff_ids") != ["sha256:" + item for item in diff_ids]
        or not isinstance(config.get("history"), list)
        or len(config["history"]) < 1
    ):
        fail("oci_config")
    top_level = {
        key: value
        for key, value in config.items()
        if key not in {"config", "rootfs", "history"}
    }
    if digest(canonical(top_level)) != BASE_TOP_LEVEL_SHA256:
        fail("top_level_config_changed")
    runtime = dict(config["config"])
    labels = runtime.pop("Labels", None)
    if digest(canonical(runtime)) != BASE_RUNTIME_SHA256 or not isinstance(
        labels, dict
    ):
        fail("runtime_config_changed")
    created = labels.get("org.opencontainers.image.created")
    if (
        labels.get("org.opencontainers.image.revision") != revision
        or not isinstance(created, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created) is None
        or labels.get("edu.ai.change") != "wechat-no-source-links-v2"
        or labels.get("edu.ai.overlay.base") != BASE_MANIFEST
        or digest(canonical(config["history"][:-1])) != BASE_HISTORY_SHA256
        or config["history"][-1]
        != {
            "created": created,
            "created_by": "COPY five reviewed no-source-link application files",
            "comment": "trellis exact-base offline overlay",
        }
    ):
        fail("overlay_identity")
    allowed_labels = {
        "org.opencontainers.image.revision",
        "org.opencontainers.image.created",
        "edu.ai.change",
        "edu.ai.overlay.base",
    }
    preserved = {
        key: value for key, value in labels.items() if key not in allowed_labels
    }
    expected_preserved = {
        "io.trellis.release.backup-sha256": "f573f1c91d25d49d261576094d19d1516a6b126ba0dc7fe3b73132e2c17261cd",
        "io.trellis.release.change": "wechat-two-banner-model-0046",
        "io.trellis.release.model-0046-archive-sha256": "d1460cd3f3103fb40f1136e11e40f9cef6e796d6601c7bc9fc1255ba525f6fbd",
        "io.trellis.release.model-compat-archive-sha256": "75959ee105b7473992c69065d717f7ded8da1ccfdc146ca436879f2bf92436b2",
        "io.trellis.release.preserved-zhipu-sha256": "b9aa021414acc1dcb25068bac707c97da3b52cbd5fc5cb3195ed1a3174514cd9",
        "io.trellis.release.runtime-archive-sha256": "c3204ad11b4bd8669af21849e9d4c8312ab2ea505ca7d7a72b4ac9be220e986b",
        "org.opencontainers.image.base.name": "python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3",
        "org.opencontainers.image.source": "https://github.com/EDLlyc/edu-ai-lead-agent.git",
    }
    if preserved != expected_preserved or set(blobs) != {
        "index.json",
        "oci-layout",
        "blobs/sha256/" + manifest_digest[7:],
        "blobs/sha256/" + config_digest[7:],
        *("blobs/sha256/" + item for item in layer_digests),
    }:
        fail("preserved_graph_changed")
    return {
        "status": "valid",
        "manifest_digest": manifest_digest,
        "config_digest": config_digest,
        "base_manifest_digest": BASE_MANIFEST,
        "overlay_layers": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--candidate-tag", required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.revision) is None:
        raise SystemExit("invalid revision")
    result = validate(
        args.archive.absolute(),
        candidate_tag=args.candidate_tag,
        candidate_ref=args.candidate_ref,
        revision=args.revision,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
