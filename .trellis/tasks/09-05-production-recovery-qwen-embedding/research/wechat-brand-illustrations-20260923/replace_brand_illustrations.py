"""Replace five brand illustrations in the September 23 unpublished draft.

This task-local specialization reuses the journaled same-draft operator from
September 18. It changes only the target edition, image slots and candidate
validation. The operator still exposes only plan/apply/reconcile and cannot add
or publish a draft.
"""

from __future__ import annotations

import importlib.util
import stat
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from uuid import UUID

from PIL import Image

BASE_OPERATOR = (
    Path(__file__).resolve().parent.parent
    / "wechat-draft-xiaosai-badge-replacement-20260918"
    / "replace_today_draft_images.py"
)
if not BASE_OPERATOR.is_file():
    BASE_OPERATOR = Path(__file__).resolve().with_name("replace_today_draft_images.py")
RUN_ID = UUID("6765fd0d-ab1e-4988-85ed-f7124f4b40e0")
IMAGE_SLOTS = (2, 3, 4, 5, 7)
IMAGE_COUNT = 9
EXPECTED_SIZE = (1536, 1024)
EXPECTED_SHA256 = (
    "3a19f12f09b3a6f2a1e9fc34239c7541d6054f402432a3bdd0a2feff9e29c3fd",
    "0ebffe49e4255f8ab7d5ae43432c1161c773ba401e0a217d1152e680b24dd794",
    "7dc2b58fe1e30825e9ebe72a98c60ba3273c41bf03da0aa7871dd517a48f2414",
    "a700d1038bd50b27b7a0c9d4f406cead314a986bc39a3dfcfe8936a2982dba31",
    "aee5bb54cc6c3fb1bb94a36db5131c0f7e750dded79e0ffef01e31e8e4b8748a",
)


def _load_base() -> ModuleType:
    spec = importlib.util.spec_from_file_location("same_draft_operator", BASE_OPERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("brand_illustration_operator_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()


def _load_candidates(directory: Path) -> tuple[bytes, ...]:
    base.require(
        directory.is_dir() and not directory.is_symlink(),
        "xiaosai_replace_candidate_directory",
    )
    bodies: list[bytes] = []
    for ordinal, expected_sha in enumerate(EXPECTED_SHA256):
        image_path = directory / f"candidate-{ordinal}.jpg"
        info = image_path.stat(follow_symlinks=False)
        base.require(
            stat.S_ISREG(info.st_mode)
            and not image_path.is_symlink()
            and 0 < info.st_size < 1024 * 1024,
            "xiaosai_replace_candidate_file",
        )
        body = image_path.read_bytes()
        base.require(
            sha256(body).hexdigest() == expected_sha,
            "xiaosai_replace_candidate_metadata",
        )
        with Image.open(image_path) as image:
            base.require(
                image.format == "JPEG" and image.size == EXPECTED_SIZE,
                "xiaosai_replace_candidate_geometry",
            )
            image.verify()
        bodies.append(body)
    return tuple(bodies)


def _image_urls(html: str) -> tuple[str, ...]:
    urls = tuple(base.VisibleHtml(html).images)
    base.require(
        len(urls) == IMAGE_COUNT and len(set(urls)) == IMAGE_COUNT,
        "xiaosai_replace_media_topology_changed",
    )
    return urls


def _rewrite_body(
    *,
    original_html: str,
    original_urls: tuple[str, ...],
    replacement_html_urls: tuple[str, ...],
    replacement_readback_urls: tuple[str, ...],
) -> str:
    base.require(
        _image_urls(original_html) == original_urls
        and len(replacement_html_urls) == len(IMAGE_SLOTS)
        and len(replacement_readback_urls) == len(IMAGE_SLOTS),
        "xiaosai_replace_media_topology_changed",
    )
    rewritten = original_html
    for slot, replacement in zip(IMAGE_SLOTS, replacement_html_urls, strict=True):
        original = original_urls[slot]
        seen = 0
        for attribute in ("src", "data-src"):
            for quote in ('"', "'"):
                old = f"{attribute}={quote}{original}{quote}"
                count = rewritten.count(old)
                base.require(count <= 1, "xiaosai_replace_remote_image_duplicate")
                if count:
                    rewritten = rewritten.replace(
                        old,
                        f"{attribute}={quote}{replacement}{quote}",
                        1,
                    )
                    seen += 1
        base.require(seen in {1, 2}, "xiaosai_replace_remote_image_missing")
    expected = list(original_urls)
    for slot, replacement in zip(IMAGE_SLOTS, replacement_readback_urls, strict=True):
        expected[slot] = replacement
    base.require(
        tuple(base.VisibleHtml(rewritten).images) == tuple(expected),
        "xiaosai_replace_rewrite_invalid",
    )
    return rewritten


def _verify_replacement(
    *,
    current: dict[str, object],
    original: dict[str, object],
    replacement_urls: tuple[str, ...],
) -> None:
    base.require(len(replacement_urls) == len(IMAGE_SLOTS))
    base._same_original({**current, "content": original["content"]}, original)
    old_html = base._article_fields(original)["content"]
    new_html = base._article_fields(current)["content"]
    assert isinstance(old_html, str) and isinstance(new_html, str)
    before = base.VisibleHtml(old_html).identity()
    after = base.VisibleHtml(new_html).identity()
    base.require(
        before[0] == after[0] and before[2] == after[2],
        "xiaosai_replace_readback_drift",
    )
    old_urls, new_urls = _image_urls(old_html), _image_urls(new_html)
    wanted = list(old_urls)
    for slot, replacement in zip(IMAGE_SLOTS, replacement_urls, strict=True):
        wanted[slot] = replacement
    base.require(
        all(
            base._same_wechat_cdn_display_variant(expected, actual)
            for expected, actual in zip(wanted, new_urls, strict=True)
        ),
        "xiaosai_replace_readback_media_mismatch",
    )


base.RUN_ID = RUN_ID
base.OPERATION_VERSION = "xiaosai-brand-scenes-same-draft-update-20260923-v1"
base.SOURCE_IMAGE_COUNT = IMAGE_COUNT
base._load_candidates = _load_candidates
base._rewrite_body = _rewrite_body
base._verify_replacement = _verify_replacement

if __name__ == "__main__":
    base.main()
