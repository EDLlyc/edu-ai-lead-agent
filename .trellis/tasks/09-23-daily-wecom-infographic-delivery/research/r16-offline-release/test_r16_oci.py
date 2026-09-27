from __future__ import annotations

import gzip
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("r16_oci.py")
SPEC = importlib.util.spec_from_file_location("r16_oci", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
oci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oci)
REVISION = "a" * 40
TAG = f"{oci.REPOSITORY}:infographic-r16-{REVISION[:12]}"


def _tar(path: Path, content: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, body in content.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))


def _docker_save(
    path: Path,
    *,
    corrupt_layer: bool = False,
    compressed_layer: bool = False,
    tag: str = TAG,
) -> None:
    raw = b"one immutable layer"
    config = oci.canonical(
        {
            "architecture": "amd64",
            "os": "linux",
            "config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
            "rootfs": {"type": "layers", "diff_ids": [oci.digest(raw)]},
        }
    )
    layer_path = "blobs/sha256/source-layer" if compressed_layer else "layer.tar"
    manifest = [{"Config": "config.json", "RepoTags": [tag], "Layers": [layer_path]}]
    layer = gzip.compress(raw, mtime=0) if compressed_layer else raw
    _tar(
        path,
        {
            "manifest.json": json.dumps(manifest).encode(),
            "config.json": config,
            layer_path: b"wrong" if corrupt_layer else layer,
            **(
                {"oci-layout": b'{"imageLayoutVersion":"1.0.0"}', "index.json": b"{}"}
                if compressed_layer
                else {}
            ),
        },
    )


def test_convert_is_deterministic_and_checks_complete_graph(tmp_path: Path) -> None:
    source = tmp_path / "docker.tar"
    _docker_save(source)
    first = tmp_path / "first.oci.tar.gz"
    second = tmp_path / "second.oci.tar.gz"
    result = oci.convert(source, first, tag=TAG, revision=REVISION)
    assert result == oci.convert(source, second, tag=TAG, revision=REVISION)
    assert first.read_bytes() == second.read_bytes()
    assert result["layers"] == 1
    assert result["config_id"].startswith("sha256:")


def test_containerd_docker_save_compressed_layer_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "docker.tar"
    _docker_save(source, compressed_layer=True)
    output = tmp_path / "image.oci.tar.gz"
    result = oci.convert(source, output, tag=TAG, revision=REVISION)
    assert result["layers"] == 1
    assert (
        oci.check_oci(output, tag=TAG, revision=REVISION, config_id=result["config_id"])
        == result
    )


def test_compressed_source_layer_is_bounded_and_must_match_raw_diff_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oci, "MAX_MEMBER", 8)
    with pytest.raises(oci.ImageError, match="docker_layer_diff_id"):
        oci.raw_layer(gzip.compress(b"x" * 9), oci.digest(b"x" * 9))
    with pytest.raises(oci.ImageError, match="docker_layer_diff_id"):
        oci.raw_layer(gzip.compress(b"safe"), oci.digest(b"different"))
    with pytest.raises(oci.ImageError, match="docker_layer_gzip"):
        oci.raw_layer(b"\x1f\x8bnot-a-gzip-member", oci.digest(b"safe"))


def test_unsafe_docker_save_member_path_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.tar"
    _tar(source, {"../outside": b"value"})
    with pytest.raises(oci.ImageError, match="unsafe_archive_path"):
        oci.members(source, compressed=False)


def test_tampered_converted_blob_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "docker.tar"
    _docker_save(source, compressed_layer=True)
    output = tmp_path / "image.oci.tar.gz"
    result = oci.convert(source, output, tag=TAG, revision=REVISION)
    content = oci.members(output, compressed=True)
    config_path = "blobs/sha256/" + result["config_id"][7:]
    content[config_path] += b"tampered"
    tampered = tmp_path / "tampered.oci.tar.gz"
    tampered.write_bytes(oci.archive_bytes(content))
    with pytest.raises(oci.ImageError, match="oci_blob"):
        oci.check_oci(
            tampered, tag=TAG, revision=REVISION, config_id=result["config_id"]
        )


def test_wrong_layer_digest_fails_before_output(tmp_path: Path) -> None:
    source = tmp_path / "docker.tar"
    _docker_save(source, corrupt_layer=True)
    output = tmp_path / "out.oci.tar.gz"
    with pytest.raises(oci.ImageError, match="docker_layer_diff_id"):
        oci.convert(source, output, tag=TAG, revision=REVISION)
    assert not output.exists()


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "docker.tar"
    _docker_save(source)
    output = tmp_path / "out.oci.tar.gz"
    output.write_bytes(b"existing")
    with pytest.raises(oci.ImageError, match="output_exists"):
        oci.convert(source, output, tag=TAG, revision=REVISION)
    assert output.read_bytes() == b"existing"


def test_wrong_tag_and_revision_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "docker.tar"
    _docker_save(source)
    output = tmp_path / "out.oci.tar.gz"
    with pytest.raises(oci.ImageError, match="tag"):
        oci.convert(source, output, tag="other:latest", revision=REVISION)
    other_revision = "b" * 40
    other_tag = f"{oci.REPOSITORY}:infographic-r16-{other_revision[:12]}"
    _docker_save(source, tag=other_tag)
    with pytest.raises(oci.ImageError, match="docker_config_identity"):
        oci.convert(source, output, tag=other_tag, revision=other_revision)
