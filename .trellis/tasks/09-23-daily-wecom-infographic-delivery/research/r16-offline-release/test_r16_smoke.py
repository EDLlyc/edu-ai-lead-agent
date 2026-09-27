from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("r16_smoke.py")
SPEC = importlib.util.spec_from_file_location("r16_smoke", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_font_contract_reads_both_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    body = (
        b"ARG FONTS_NOTO_CJK_VERSION=1:20220127+repack1-1\n"
        + b"a" * 64
        + b" /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc | sha256sum --check\n"
    )
    monkeypatch.setattr(smoke, "run", lambda _args: body)
    assert smoke.font_contract(Path("."), "a" * 40) == (
        "1:20220127+repack1-1",
        "a" * 64,
    )


def test_font_contract_fails_without_full_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run",
        lambda _args: b"ARG FONTS_NOTO_CJK_VERSION=1:20220127+repack1-1\n",
    )
    with pytest.raises(smoke.SmokeError, match="font_source_contract"):
        smoke.font_contract(Path("."), "a" * 40)


def test_committed_runtime_source_tree_is_nonempty() -> None:
    repo = MODULE_PATH.parents[5]
    revision = smoke.run(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
    tree = smoke.source_tree(repo, revision)
    assert "app/api_main.py" in tree
    assert "alembic.ini" in tree
    assert any(path.startswith("alembic/versions/") for path in tree)


@pytest.mark.parametrize("docker_id_is_manifest", [True, False])
def test_loaded_oci_image_id_is_manifest_digest(
    monkeypatch: pytest.MonkeyPatch, docker_id_is_manifest: bool
) -> None:
    """Docker 29's OCI store exposes the manifest digest as image `.Id`."""
    revision = "a" * 40
    image = "sha256:" + "b" * 64
    config_id = "sha256:" + "c" * 64
    tag = f"{smoke.REPOSITORY}:infographic-r16-{revision[:12]}"

    def fake_run(args: list[str], **_kwargs: object) -> bytes:
        if args[:3] == ["git", "-C", "."]:
            return (
                revision.encode() + b"\n" if args[-2:] == ["rev-parse", "HEAD"] else b""
            )
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": image if docker_id_is_manifest else config_id,
                        "RepoTags": [tag],
                    }
                ]
            ).encode()
        if args[:2] == ["docker", "run"]:
            return json.dumps(
                {
                    "files": {},
                    "font_version": "1:version",
                    "font_sha256": "d" * 64,
                    "font_loaded": True,
                    "head": ["20260926_0050"],
                    "pip_check": 0,
                }
            ).encode()
        return b""

    monkeypatch.setattr(smoke, "run", fake_run)
    monkeypatch.setattr(
        smoke,
        "check_oci",
        lambda *_args, **_kwargs: {"image": image, "archive_sha256": "e" * 64},
    )
    monkeypatch.setattr(smoke, "source_tree", lambda *_args: {})
    monkeypatch.setattr(smoke, "font_contract", lambda *_args: ("1:version", "d" * 64))

    if docker_id_is_manifest:
        assert (
            smoke.smoke(
                Path("."),
                revision,
                Path("image.oci.tar.gz"),
                config_id=config_id,
                expected_image=image,
            )["status"]
            == "local_smoke_passed"
        )
    else:
        with pytest.raises(smoke.SmokeError, match="loaded_image_identity"):
            smoke.smoke(
                Path("."),
                revision,
                Path("image.oci.tar.gz"),
                config_id=config_id,
                expected_image=image,
            )
