"""Load repo-owned Official Account framing and verify sealed derivatives."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from app.domain.official_account_upload_media import (
    OFFICIAL_ACCOUNT_UPLOAD_FOOTER_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_HEADER_POLICY_VERSION,
    normalize_official_account_upload_footer,
    normalize_official_account_upload_header,
)
from app.domain.official_account_xiaosai_footer import (
    CHENGYUE_HEADER_MASTER_SHA256,
    CHENGYUE_HEADER_PUBLICATION_SHA256,
    XIAOSAI_FOOTER_MASTER_SHA256,
    XIAOSAI_FOOTER_PUBLICATION_SHA256,
    ChengyueIntroductionHeaderAsset,
    XiaosaiMarketingFooterAsset,
    validate_chengyue_header,
    validate_xiaosai_footer,
)

_ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
_HEADER_MASTER_FILE = _ASSET_ROOT / "chengyue-top-intro-master.png"
_HEADER_PUBLICATION_FILE = _ASSET_ROOT / "chengyue-top-intro.jpg"
_MASTER_FILE = _ASSET_ROOT / "xiaosai-marketing-footer-master.png"
_PUBLICATION_FILE = _ASSET_ROOT / "xiaosai-marketing-footer.jpg"


def _read_pair(master_path: Path, publication_path: Path, *, label: str) -> tuple[bytes, bytes]:
    try:
        if any(path.is_symlink() or not path.is_file() for path in (master_path, publication_path)):
            raise ValueError(f"{label} asset is unavailable")
        return master_path.read_bytes(), publication_path.read_bytes()
    except OSError as error:
        raise ValueError(f"{label} asset is unavailable") from error


def load_chengyue_introduction_header() -> tuple[ChengyueIntroductionHeaderAsset, bytes]:
    """Return the exact approved Cheng Yue banner publication."""
    master, publication = _read_pair(
        _HEADER_MASTER_FILE,
        _HEADER_PUBLICATION_FILE,
        label="Cheng Yue introduction header",
    )
    if (
        len(master) != 5_882_944
        or sha256(master).hexdigest() != CHENGYUE_HEADER_MASTER_SHA256
        or len(publication) != 716_140
        or sha256(publication).hexdigest() != CHENGYUE_HEADER_PUBLICATION_SHA256
    ):
        raise ValueError("Cheng Yue introduction header packaged bytes changed")
    derivative = normalize_official_account_upload_header(master)
    if (
        derivative.policy_version != OFFICIAL_ACCOUNT_UPLOAD_HEADER_POLICY_VERSION
        or derivative.source_sha256 != CHENGYUE_HEADER_MASTER_SHA256
        or derivative.sha256 != CHENGYUE_HEADER_PUBLICATION_SHA256
        or derivative.content != publication
        or derivative.mime_type != "image/jpeg"
        or (derivative.width, derivative.height) != (3840, 1920)
    ):
        raise ValueError("Cheng Yue introduction header derivative changed")
    header = ChengyueIntroductionHeaderAsset()
    validate_chengyue_header(header, content=publication)
    return header, publication


def load_xiaosai_marketing_footer() -> tuple[XiaosaiMarketingFooterAsset, bytes]:
    """Return only when packaged master, policy and publication still agree exactly."""
    master, publication = _read_pair(
        _MASTER_FILE,
        _PUBLICATION_FILE,
        label="Xiaosai marketing footer",
    )
    if (
        len(master) != 2_092_946
        or sha256(master).hexdigest() != XIAOSAI_FOOTER_MASTER_SHA256
        or len(publication) != 383_664
        or sha256(publication).hexdigest() != XIAOSAI_FOOTER_PUBLICATION_SHA256
    ):
        raise ValueError("Xiaosai marketing footer packaged bytes changed")
    derivative = normalize_official_account_upload_footer(master)
    if (
        derivative.policy_version != OFFICIAL_ACCOUNT_UPLOAD_FOOTER_POLICY_VERSION
        or derivative.source_sha256 != XIAOSAI_FOOTER_MASTER_SHA256
        or derivative.sha256 != XIAOSAI_FOOTER_PUBLICATION_SHA256
        or derivative.content != publication
        or derivative.mime_type != "image/jpeg"
        or (derivative.width, derivative.height) != (2048, 1152)
    ):
        raise ValueError("Xiaosai marketing footer derivative changed")
    footer = XiaosaiMarketingFooterAsset()
    validate_xiaosai_footer(footer, article=None, content=publication)
    return footer, publication


def load_official_account_marketing_framing() -> tuple[
    ChengyueIntroductionHeaderAsset,
    bytes,
    XiaosaiMarketingFooterAsset,
    bytes,
]:
    """Load both approved boundaries before a future V5 owner emits either one."""
    header, header_content = load_chengyue_introduction_header()
    footer, footer_content = load_xiaosai_marketing_footer()
    return header, header_content, footer, footer_content
