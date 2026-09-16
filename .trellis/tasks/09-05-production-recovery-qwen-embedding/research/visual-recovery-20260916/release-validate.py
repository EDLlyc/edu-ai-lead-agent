#!/usr/bin/env python3
"""Validate the immutable current image plus one reviewed app-and-migration layer."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "visual_release_common", Path(__file__).with_name("release-common.py")
)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def validate_overlay_layer(
    raw: bytes, *, app_files: dict[str, str], migration_files: dict[str, str]
) -> None:
    C.require(len(raw) <= 2 * 1024 * 1024, "overlay_layer_size")
    expected = {
        **{"app/app/" + path: checksum for path, checksum in app_files.items()},
        **{"app/" + path: checksum for path, checksum in migration_files.items()},
    }
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as layer:
            for member in layer:
                C.require(
                    member.name not in seen
                    and member.name in expected
                    and member.isfile()
                    and member.type == tarfile.REGTYPE
                    and member.mode == 0o644
                    and member.uid == 999
                    and member.gid == 999
                    and member.uname == "app"
                    and member.gname == "app"
                    and member.mtime == 0
                    and not member.linkname
                    and not member.pax_headers,
                    "overlay_layer_member",
                )
                seen.add(member.name)
                stream = layer.extractfile(member)
                C.require(
                    stream is not None and member.size <= 1024 * 1024,
                    "overlay_layer_member",
                )
                assert stream is not None
                body = stream.read(member.size + 1)
                C.require(
                    len(body) == member.size
                    and C.digest(body) == expected[member.name],
                    "overlay_layer_hash",
                )
    except (OSError, tarfile.TarError) as error:
        raise RuntimeError("overlay_layer_unreadable") from error
    C.require(seen == set(expected), "overlay_layer_files")


def validate(
    archive: Path,
    *,
    candidate_tag: str,
    candidate_ref: str,
    revision: str,
    app_files: dict,
    migration_files: dict,
) -> dict:
    C.require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision")
    V = C.archived("validate")
    validated_app_files = C.validate_files(app_files)
    validated_migration_files = C.validate_migration_files(migration_files)
    blobs = V.safe_members(archive)
    C.require(
        V.strict_json(blobs["oci-layout"], "layout") == {"imageLayoutVersion": "1.0.0"},
        "layout",
    )
    index = V.strict_json(blobs["index.json"], "index")
    C.require(
        isinstance(index, dict)
        and set(index) == {"schemaVersion", "mediaType", "manifests"}
        and index["schemaVersion"] == 2
        and index["mediaType"] == V.OCI_INDEX
        and isinstance(index["manifests"], list)
        and len(index["manifests"]) == 1,
        "index",
    )
    top = index["manifests"][0]
    C.require(
        isinstance(top, dict)
        and set(top) == {"mediaType", "digest", "size", "annotations", "platform"},
        "index_top",
    )
    md, mb = V.descriptor(
        {k: top[k] for k in ("mediaType", "digest", "size")}, V.OCI_MANIFEST, blobs
    )
    C.require(
        candidate_tag == C.REPOSITORY + ":visual-recovery-" + revision[:12]
        and candidate_ref == C.REPOSITORY + "@" + md
        and top["platform"] == {"architecture": "amd64", "os": "linux"}
        and top["annotations"]
        == {
            "io.containerd.image.name": candidate_tag,
            "org.opencontainers.image.ref.name": candidate_tag.rsplit(":", 1)[1],
        },
        "identity",
    )
    m = V.strict_json(mb, "manifest")
    C.require(
        isinstance(m, dict)
        and set(m) == {"schemaVersion", "mediaType", "config", "layers"}
        and m["schemaVersion"] == 2
        and m["mediaType"] == V.OCI_MANIFEST
        and isinstance(m["layers"], list)
        and len(m["layers"]) == len(V.BASE_LAYERS) + 2,
        "manifest",
    )
    cd, cb = V.descriptor(m["config"], V.OCI_CONFIG, blobs)
    compressed_ids, diff_ids = [], []
    expected_base = (
        *V.BASE_LAYERS,
        "3b18c5f300807e6c65ba5f7cc4e72a87b6098c5972ceb57ab17cf313fc0994f6",
    )
    for number, layer in enumerate(m["layers"]):
        ld, compressed = V.descriptor(layer, V.OCI_LAYER, blobs)
        if number < len(expected_base):
            C.require(ld[7:] == expected_base[number], "base_graph_changed")
            raw = gzip.decompress(compressed)
        else:
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            C.require(len(raw) <= 2 * 1024 * 1024, "overlay_layer_size")
        compressed_ids.append(ld[7:])
        diff_ids.append(C.digest(raw))
        if number == len(m["layers"]) - 1:
            validate_overlay_layer(
                raw,
                app_files=validated_app_files,
                migration_files=validated_migration_files,
            )
    C.require(
        tuple(compressed_ids[:-1])
        == (
            *V.BASE_LAYERS,
            "3b18c5f300807e6c65ba5f7cc4e72a87b6098c5972ceb57ab17cf313fc0994f6",
        )
        and tuple(diff_ids[:-1])
        == (
            *V.BASE_DIFF_IDS,
            "b948e5110ce5adfa9a5337520f44f10b09b0f0b371abe20ceff3c97ccbfc3d1b",
        ),
        "base_graph_changed",
    )
    config = V.strict_json(cb, "config")
    C.require(
        isinstance(config, dict)
        and config.get("architecture") == "amd64"
        and config.get("os") == "linux"
        and config.get("rootfs")
        == {"type": "layers", "diff_ids": ["sha256:" + x for x in diff_ids]}
        and isinstance(config.get("config"), dict)
        and isinstance(config.get("history"), list),
        "config",
    )
    runtime = dict(config["config"])
    labels = runtime.pop("Labels", None)
    C.require(
        C.digest(C.canonical(runtime)) == V.BASE_RUNTIME_SHA256, "runtime_changed"
    )
    C.require(
        C.digest(
            C.canonical(
                {
                    k: v
                    for k, v in config.items()
                    if k not in {"config", "rootfs", "history"}
                }
            )
        )
        == V.BASE_TOP_LEVEL_SHA256,
        "top_level_changed",
    )
    C.require(
        isinstance(labels, dict)
        and labels.get("org.opencontainers.image.revision") == revision
        and labels.get("edu.ai.change") == C.CHANGE
        and labels.get("edu.ai.overlay.base") == C.BASE_MANIFEST,
        "labels",
    )
    created = labels.get("org.opencontainers.image.created")
    C.require(
        isinstance(created, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created) is not None,
        "created",
    )
    C.require(
        C.digest(C.canonical(config["history"][:-1]))
        == "1333a510f0f9b8a7473d237ccd5823d55c081f1907572038f1ca413de9d2cc2d"
        and config["history"][-1]
        == {
            "created": created,
            "created_by": C.HISTORY_COMMAND,
            "comment": "trellis exact-base offline overlay",
        },
        "history_changed",
    )
    # The preserved label map is part of the exact deployed image identity.
    preserved = {
        k: v
        for k, v in labels.items()
        if k
        not in {
            "org.opencontainers.image.revision",
            "org.opencontainers.image.created",
            "edu.ai.change",
            "edu.ai.overlay.base",
        }
    }
    C.require(
        C.digest(C.canonical(preserved)) == PRESERVED_LABELS_SHA256,
        "preserved_labels_changed",
    )
    C.require(
        set(blobs)
        == {
            "index.json",
            "oci-layout",
            "blobs/sha256/" + md[7:],
            "blobs/sha256/" + cd[7:],
            *("blobs/sha256/" + x for x in compressed_ids),
        },
        "extra_blobs",
    )
    return {
        "status": "valid",
        "manifest_digest": md,
        "config_digest": cd,
        "base_manifest_digest": C.BASE_MANIFEST,
        "overlay_layers": 1,
    }


PRESERVED_LABELS_SHA256 = (
    "f9087deac6d3799135a4701c566da54d7f6d08e3a5ba327e22890d2aa679dddc"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    value = C.manifest(args.manifest.absolute(), args.manifest_sha256)
    result = validate(
        args.archive.absolute(),
        candidate_tag=value["candidate_tag"],
        candidate_ref=value["candidate_ref"],
        revision=value["revision"],
        app_files=value["app_files"],
        migration_files=value["migration_files"],
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
