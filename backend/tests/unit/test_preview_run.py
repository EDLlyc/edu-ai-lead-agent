# ruff: noqa: RUF001

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import app.preview_run as preview_run
from app.preview_run import (
    PreviewState,
    StageState,
    _extract_trailing_hashtags,
    _manifest,
    _quality_snapshot,
    _safe_http_error,
    _validate_png,
)
from pytest import MonkeyPatch


def _png_header(width: int = 1024, height: int = 1024) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def test_preview_manifest_contains_only_local_image_url_and_redacted_stage_data(
    tmp_path: Path,
) -> None:
    state = PreviewState(
        run_id="preview-123",
        business_date="2026-08-07",
        output_dir=tmp_path,
        topic={
            "title": "教育部部署开展科学教育行动",
            "decision": "selected",
            "score": 0.8,
            "selection_explanation": "official source",
        },
        sources=[
            {
                "id": "candidate-1",
                "title": "教育部科学教育新闻",
                "source_name": "教育部",
                "url": "https://www.moe.gov.cn/news/1",
                "source_tier": "A",
                "status": "selected_event_member",
                "is_selected": True,
            }
        ],
        copy_detail={
            "active_draft_version_id": "draft-1",
            "drafts": [
                {
                    "id": "draft-1",
                    "version": 1,
                    "copywriting": "家长看得懂的科学内容\n#赛先生科学 #做中学",
                    "parent_takeaway": "鼓励孩子提问和动手验证。",
                    "interaction": "你家孩子最近问过什么为什么？",
                    "source_note": "来源：教育部官网",
                    "validation_passed": True,
                    "audit_accepted": True,
                    "issues": [],
                }
            ],
        },
        image={
            "status": "succeeded",
            "url": "/preview/preview-123/image-preview-123.png",
            "filename": "image-preview-123.png",
            "validation": {"status": "passed", "passed": True},
            "audit": {"status": "not_configured"},
        },
    )
    state.stages.append(
        # The stage only carries durable IDs and safe version labels.
        StageState(id="acquisition", label="权威来源采集", status="completed", run_id="run-1")
    )

    payload = _manifest(state)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "ready"
    assert payload["image"]["url"].startswith("/preview/")
    assert "COMFLY_API_KEY" not in serialized
    assert "webstatic.aiproxy.vip" not in serialized
    assert "minio" not in serialized.lower()


def test_preview_helpers_reject_bad_png_and_keep_hashtag_contract() -> None:
    assert _extract_trailing_hashtags("正文\n#赛先生科学 #做中学") == ["#赛先生科学", "#做中学"]
    assert _extract_trailing_hashtags("正文\n#赛先生科学 #做中学 #人工智能 #多余") == []
    assert _validate_png(_png_header()) == (1024, 1024)
    try:
        _validate_png(_png_header(512, 512))
    except Exception as error:
        assert getattr(error, "code", None) == "image_dimensions_invalid"
    else:
        raise AssertionError("non-1024 image should be rejected")


def test_quality_snapshot_maps_audit_status_and_preserves_explicit_status() -> None:
    assert _quality_snapshot({"accepted": True})["status"] == "accepted"
    assert _quality_snapshot({"accepted": False})["status"] == "rejected"
    assert _quality_snapshot({"accepted": True, "status": "not_configured"})["status"] == (
        "not_configured"
    )


def test_manifest_projects_package_audit_status_at_top_level_and_in_copy() -> None:
    state = PreviewState(
        run_id="preview-audit-status",
        business_date="2026-08-08",
        output_dir=Path("output/preview/preview-audit-status"),
        copy_detail={
            "active_draft_version_id": "draft-1",
            "drafts": [
                {
                    "id": "draft-1",
                    "copywriting": "科学教育内容\n#赛先生科学 #做中学",
                    "validation_passed": True,
                    "audit_accepted": True,
                    "issues": [],
                }
            ],
        },
        package={
            "id": "package-1",
            "status": "awaiting_manual_use",
            "validation": {"passed": True},
            "audit": {"accepted": True},
        },
    )

    payload = _manifest(state)

    assert payload["audit"]["status"] == "accepted"
    assert payload["audit"]["accepted"] is True
    assert payload["copy"]["audit"]["status"] == "accepted"
    assert payload["copy"]["audit"]["accepted"] is True


def test_safe_http_error_does_not_return_provider_payload() -> None:
    import httpx

    response = httpx.Response(
        502,
        json={"detail": "provider secret key sk-test should not be persisted"},
    )
    message = _safe_http_error(response)
    assert "sk-test" not in message
    assert "API 请求失败" in message


def test_preview_run_does_not_duplicate_flattened_copy_detail_issues(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    validation_issue = {
        "code": "copy_validation_warning",
        "message": "确定性校验提示",
        "severity": "warning",
    }
    audit_issue = {
        "code": "copy_audit_warning",
        "message": "审计提示",
        "severity": "warning",
    }
    image_issue = {
        "code": "image_validation_warning",
        "message": "图片校验提示",
        "severity": "warning",
    }

    class FakePreviewApi:
        def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
            del base_url, timeout_seconds

        def close(self) -> None:
            pass

        def request(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
        ) -> dict[str, object]:
            del payload, headers
            responses = {
                ("POST", "/api/v1/acquisition-runs"): {"id": "acquisition-1"},
                ("GET", "/api/v1/acquisition-runs/acquisition-1"): {
                    "id": "acquisition-1",
                    "status": "succeeded",
                    "acquisition_version": "acquisition-v1",
                },
                ("GET", "/api/v1/acquisition-runs/acquisition-1/jobs"): {"items": []},
                ("POST", "/api/v1/governance-runs"): {"id": "governance-1"},
                ("GET", "/api/v1/governance-runs/governance-1"): {
                    "id": "governance-1",
                    "status": "succeeded",
                    "version_bundle": {"pipeline_version": "governance-v1"},
                },
                ("POST", "/api/v1/topic-selection-runs"): {"id": "topic-1"},
                ("GET", "/api/v1/topic-selection-runs/topic-1"): {
                    "id": "topic-1",
                    "status": "succeeded",
                    "scoring_version": "topic-v1",
                },
                ("GET", "/api/v1/daily-topics/2026-08-07?profile=preview"): {
                    "decision": "selected",
                    "selected_event_id": "event-1",
                    "selected_score": {
                        "event_title": "科学教育新闻",
                        "explanation": "测试选题",
                        "total": 0.9,
                        "threshold": 0.7,
                    },
                },
                ("GET", "/api/v1/events/event-1"): {
                    "representative_title": "科学教育新闻",
                    "categories": ["science"],
                    "members": [],
                },
                ("GET", "/api/v1/governance-runs/governance-1/jobs"): {"items": []},
                ("POST", "/api/v1/copy-generation-runs"): {"id": "copy-1"},
                ("GET", "/api/v1/copy-generation-runs/copy-1"): {
                    "id": "copy-1",
                    "status": "accepted",
                },
                ("GET", "/api/v1/copy-generation-runs/copy-1/detail"): {
                    "active_draft_version_id": "draft-1",
                    "drafts": [
                        {
                            "id": "draft-1",
                            "version": 1,
                            "copywriting": "科学教育内容\n#赛先生科学 #做中学",
                            "validation_passed": True,
                            "audit_accepted": True,
                            # This endpoint flattens deterministic and audit findings.
                            "issues": [validation_issue, audit_issue],
                        }
                    ],
                },
                ("POST", "/api/v1/material-packages"): {"id": "package-1"},
                ("GET", "/api/v1/material-packages/package-1"): {
                    "id": "package-1",
                    "status": "awaiting_manual_use",
                    "review_status": "pending",
                    "brand_bindings": [],
                    "validation": {"passed": True, "issues": [validation_issue]},
                    "audit": {"accepted": True, "issues": [audit_issue]},
                    "versions": {"image": {"pipeline_version": "image-v1"}},
                    "image": {
                        "status": "succeeded",
                        "download_url": "/api/v1/material-packages/package-1/image",
                        "validation": {"passed": True, "issues": [image_issue]},
                        "audit": {"status": "not_configured"},
                    },
                },
            }
            return responses[(method, path)]

        def download(self, path: str, *, max_bytes: int = 32 * 1024 * 1024) -> tuple[bytes, str]:
            del path, max_bytes
            return _png_header(), "image/png"

    monkeypatch.setattr(preview_run, "PreviewApi", FakePreviewApi)

    manifest_path = preview_run.run_preview(
        business_date=date(2026, 8, 7),
        output_root=tmp_path,
        poll_seconds=0,
    )

    findings = json.loads(manifest_path.read_text(encoding="utf-8"))["findings"]
    assert [(finding["stage"], finding["code"]) for finding in findings] == [
        ("copy_generation", "copy_validation_warning"),
        ("copy_generation", "copy_audit_warning"),
        ("image_generation", "image_validation_warning"),
    ]
