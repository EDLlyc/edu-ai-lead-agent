from __future__ import annotations

import base64
import hashlib
import json
import random
import struct
import zlib
from functools import lru_cache
from io import BytesIO

import pytest
from app.domain.visual_retrieval import (
    MAX_VISUAL_EMBEDDING_IMAGE_BYTES,
    MAX_VISUAL_PROVIDER_REQUEST_BYTES,
    VISUAL_EMBEDDING_DIMENSIONS,
    VISUAL_EMBEDDING_INPUT_POLICY_V1,
    VISUAL_EMBEDDING_MODEL,
    VisualAssetDerivation,
    VisualEmbeddingIdentity,
    normalize_visual_embedding_image,
)
from PIL import Image, PngImagePlugin


def _small_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


@lru_cache(maxsize=1)
def _large_png() -> bytes:
    pixels = random.Random(1729).randbytes(2_048 * 2_048 * 3)
    image = Image.frombytes("RGB", (2_048, 2_048), pixels)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-note", "not retained")
    output = BytesIO()
    image.save(output, format="PNG", compress_level=0, pnginfo=metadata)
    return output.getvalue()


def _chunk_types(body: bytes) -> tuple[bytes, ...]:
    offset = 8
    result: list[bytes] = []
    while offset + 12 <= len(body):
        length = struct.unpack(">I", body[offset : offset + 4])[0]
        chunk_type = body[offset + 4 : offset + 8]
        result.append(chunk_type)
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    assert offset == len(body)
    return tuple(result)


def test_visual_input_v2_large_png_is_deterministic_bounded_and_metadata_free() -> None:
    source = _large_png()
    first = normalize_visual_embedding_image(source)
    second = normalize_visual_embedding_image(source)

    assert len(source) == 12_589_099
    assert hashlib.sha256(source).hexdigest() == (
        "bc2d8e14e43bd4e9e2da968a5057e8464bc73f7d5272820fe4b230a5d7b99b0d"
    )
    assert first == second
    assert first.normalized is True
    assert (first.width, first.height) == (1_536, 1_536)
    assert len(first.png_bytes) == 7_037_350
    assert first.embedding_input_sha256 == (
        "1cd51f11fa45573405e55d291f4a9029540ffa2d56f7dafde44a41fee01804d9"
    )
    assert first.source_sha256 != first.embedding_input_sha256
    assert len(first.png_bytes) <= MAX_VISUAL_EMBEDDING_IMAGE_BYTES
    assert set(_chunk_types(first.png_bytes)) == {b"IHDR", b"IDAT", b"IEND"}

    payload = {
        "model": VISUAL_EMBEDDING_MODEL,
        "input": {
            "contents": [
                {
                    "image": "data:image/png;base64,"
                    + base64.b64encode(first.png_bytes).decode("ascii")
                }
            ]
        },
        "parameters": {"dimension": VISUAL_EMBEDDING_DIMENSIONS, "output_type": "dense"},
    }
    envelope = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(envelope) < MAX_VISUAL_PROVIDER_REQUEST_BYTES


def test_visual_input_v2_small_png_is_validated_and_byte_identical() -> None:
    source = _small_png()

    result = normalize_visual_embedding_image(source)

    assert result.png_bytes is source
    assert result.normalized is False
    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert result.embedding_input_sha256 == result.source_sha256


def test_visual_input_v2_preserves_alpha_while_removing_large_metadata() -> None:
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-note", "x" * (8 * 1024 * 1024))
    output = BytesIO()
    Image.new("RGBA", (1, 1), (10, 20, 30, 40)).save(
        output,
        format="PNG",
        compress_level=0,
        pnginfo=metadata,
    )

    result = normalize_visual_embedding_image(output.getvalue())

    assert result.normalized is True
    assert set(_chunk_types(result.png_bytes)) == {b"IHDR", b"IDAT", b"IEND"}
    with Image.open(BytesIO(result.png_bytes)) as normalized:
        normalized.load()
        assert normalized.mode == "RGBA"
        assert normalized.info == {}
        assert normalized.getpixel((0, 0)) == (10, 20, 30, 40)


def test_visual_input_v2_rejects_pixel_bomb_before_decode() -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    oversized_raster = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8_192, 8_192, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )

    with pytest.raises(ValueError, match="valid bounded PNG"):
        normalize_visual_embedding_image(oversized_raster)


def test_visual_input_v1_preserves_historical_derivation_key_formula() -> None:
    source = _small_png()
    checksum = hashlib.sha256(source).hexdigest()
    identity = VisualEmbeddingIdentity(input_policy_version=VISUAL_EMBEDDING_INPUT_POLICY_V1)

    normalized = normalize_visual_embedding_image(source, identity=identity)
    derivation = VisualAssetDerivation(
        asset_id=checksum,
        asset_checksum=checksum,
        embedding_input_sha256=checksum,
        catalog_version="brand-visual-catalog-v1",
        identity=identity,
    )
    historical_key = hashlib.sha256(
        "\0".join(
            (
                checksum,
                checksum,
                "brand-visual-catalog-v1",
                identity.fingerprint,
            )
        ).encode()
    ).hexdigest()

    assert normalized.png_bytes == source
    assert normalized.normalized is False
    assert checksum == "abc58d5127d7cdf313beb9ec8ee839860a9c6bfbc48c8b8eb6a3f7d8bb63de6f"
    assert identity.fingerprint == (
        "7aed4639d514b3680c8361d9e593f41d7541bd0e3c201707b9206a23c7b196cd"
    )
    assert historical_key == ("e535845d290da5bf043510a9b266c582582dda897bec28f7908cbe4c34e95c61")
    assert derivation.key == historical_key


def test_visual_input_v1_keeps_the_historical_ten_mib_passthrough_bound() -> None:
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("historical-metadata", "x" * (8 * 1024 * 1024))
    output = BytesIO()
    Image.new("RGB", (1, 1), (1, 2, 3)).save(output, format="PNG", pnginfo=metadata)
    source = output.getvalue()
    identity = VisualEmbeddingIdentity(input_policy_version=VISUAL_EMBEDDING_INPUT_POLICY_V1)

    result = normalize_visual_embedding_image(source, identity=identity)

    assert len(source) > MAX_VISUAL_EMBEDDING_IMAGE_BYTES
    assert result.input_policy_version == VISUAL_EMBEDDING_INPUT_POLICY_V1
    assert result.png_bytes == source
    assert result.normalized is False
