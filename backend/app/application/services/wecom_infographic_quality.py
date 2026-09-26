"""Closed, safe advisory-quality evidence shared by producer and WeCom send gate."""

from __future__ import annotations

from collections.abc import Iterable

ADVISORY_NOTICE_VERSION = "wecom-infographic-advisory-notice-v1"
ADVISORY_NOTICE_TEXT = "AI生成 · 内容/排版未核实"
ADVISORY_WARNING_CODES = frozenset(
    {
        "advisory_unverified",
        "copy_deterministic_rejected",
        "copy_audit_rejected",
        "copy_audit_unavailable",
        "copy_audit_schema_invalid",
        "layout_unverified",
        "layout_overflow",
        "body_ocr_failed",
        "body_ocr_unavailable",
        "footer_ocr_unavailable",
        "visual_failed",
        "visual_unavailable",
        "brand_unverified",
    }
)


def normalize_advisory_warnings(codes: Iterable[str]) -> list[str]:
    """Return a bounded canonical list; never persist arbitrary reviewer prose."""
    if isinstance(codes, str):
        raise ValueError("advisory warnings must be a code collection")
    result = set(codes)
    if not result <= ADVISORY_WARNING_CODES:
        raise ValueError("advisory warning code is not allowed")
    result.add("advisory_unverified")
    if len(result) > 16:
        raise ValueError("too many advisory warning codes")
    return sorted(result)


def valid_advisory_warnings(value: object) -> bool:
    """Require the exact canonical durable shape before a warning-marked send."""
    return bool(
        isinstance(value, list)
        and all(isinstance(code, str) for code in value)
        and "advisory_unverified" in value
        and len(value) <= 16
        and value == sorted(set(value))
        and set(value) <= ADVISORY_WARNING_CODES
    )


def advisory_gate_warnings_match(
    value: object,
    *,
    body_ocr_status: str,
    footer_ocr_status: str,
    visual_status: str,
) -> bool:
    """A failed/unchecked quality observation must remain visible in durable codes."""
    if not valid_advisory_warnings(value) or not isinstance(value, list):
        return False
    codes = set(value)
    if "layout_unverified" not in codes:
        return False
    for status, failed_code, unavailable_code in (
        (body_ocr_status, "body_ocr_failed", "body_ocr_unavailable"),
        (footer_ocr_status, "", "footer_ocr_unavailable"),
        (visual_status, "visual_failed", "visual_unavailable"),
    ):
        if status == "passed":
            continue
        if status == "failed":
            if not failed_code or failed_code not in codes:
                return False
        elif status in {"not_checked", "unavailable", "result_unknown"}:
            if unavailable_code not in codes:
                return False
        else:
            return False
    return True


def advisory_copy_warnings_match(
    value: object,
    *,
    candidate: object,
    audit: object,
    package_id: str,
    input_fingerprint: str,
) -> bool:
    """Keep relaxed review outcomes attached to their exact frozen candidate."""
    if (
        not valid_advisory_warnings(value)
        or not isinstance(value, list)
        or not isinstance(candidate, dict)
        or not isinstance(audit, dict)
        or candidate.get("package_id") != package_id
        or candidate.get("input_fingerprint") != input_fingerprint
        or candidate.get("content_approved") is not False
    ):
        return False
    codes = set(value)
    candidate_warnings = candidate.get("warning_codes")
    if not isinstance(candidate_warnings, list) or not all(
        isinstance(code, str) for code in candidate_warnings
    ):
        return False
    for code in candidate_warnings:
        if code in {"copy_schema_warning", "copy_binding_warning"}:
            if "copy_deterministic_rejected" not in codes:
                return False
        elif code == "copy_layout_warning":
            if "layout_overflow" not in codes:
                return False
        else:
            return False
    status = audit.get("status")
    if isinstance(status, str) and status in {"unavailable", "schema_invalid"}:
        return (
            "copy_audit_unavailable" in codes
            if status == "unavailable"
            else "copy_audit_schema_invalid" in codes
        )
    if status is not None:
        return False
    accepted = audit.get("accepted")
    issues = audit.get("issues")
    if not isinstance(accepted, bool) or not isinstance(issues, list):
        return False
    if accepted:
        if issues:
            return False
    elif not issues or "copy_audit_rejected" not in codes:
        return False
    return audit.get("brand_bound") is not False or "brand_unverified" in codes
