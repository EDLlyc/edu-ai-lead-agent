# ruff: noqa: RUF001

"""Run one isolated, real content-production preview through the public API.

This module intentionally stays outside the production scheduler and workers.  It orchestrates
the same durable API boundaries for local acceptance, writes only a redacted manifest, and never
publishes to an external social platform.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

_TERMINAL_ACQUISITION = {"succeeded", "partially_succeeded", "failed"}
_TERMINAL_GOVERNANCE = {"succeeded", "partially_succeeded", "review_required", "failed"}
_TERMINAL_TOPIC = {"succeeded", "failed"}
_TERMINAL_COPY = {"accepted", "review_required", "failed", "no_topic"}
_TERMINAL_PACKAGE = {"awaiting_manual_use", "ready", "completed", "rejected", "failed"}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_HASHTAG = re.compile(r"#[A-Za-z0-9_\u3400-\u9fff]{2,24}")


class PreviewRunError(RuntimeError):
    """A safe, user-facing failure from one preview stage."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class StageState:
    id: str
    label: str
    status: str = "queued"
    run_id: str | None = None
    version: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def as_manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "run_id": self.run_id,
            "version": self.version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class PreviewState:
    run_id: str
    business_date: str
    output_dir: Path
    stages: list[StageState] = field(default_factory=list)
    acquisition: dict[str, Any] = field(default_factory=dict)
    governance: dict[str, Any] = field(default_factory=dict)
    topic_selection: dict[str, Any] = field(default_factory=dict)
    topic: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    copy_run: dict[str, Any] = field(default_factory=dict)
    copy_detail: dict[str, Any] = field(default_factory=dict)
    package: dict[str, Any] = field(default_factory=dict)
    image: dict[str, Any] = field(default_factory=dict)
    brand_bindings: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    generated_at: str | None = None


class PreviewApi:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("API base URL must use HTTP or HTTPS")
        self.base_url = normalized
        self.client = httpx.Client(
            base_url=normalized,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
        )

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, json=payload, headers=headers)
        except httpx.HTTPError as error:
            raise PreviewRunError("api_unavailable", "本地 API 无法访问") from error
        if not response.is_success:
            raise PreviewRunError(
                f"api_http_{response.status_code}",
                _safe_http_error(response),
            )
        if not response.content:
            return {}
        try:
            value = response.json()
        except ValueError as error:
            raise PreviewRunError(
                "invalid_api_response", "本地 API 返回了无法解析的结果"
            ) from error
        if not isinstance(value, dict):
            raise PreviewRunError("invalid_api_response", "本地 API 返回了非对象结果")
        return value

    def download(self, path: str, *, max_bytes: int = 32 * 1024 * 1024) -> tuple[bytes, str]:
        try:
            response = self.client.get(path, headers={"Accept": "image/png,image/*"})
        except httpx.HTTPError as error:
            raise PreviewRunError("image_download_failed", "本地图片下载端点无法访问") from error
        if not response.is_success:
            raise PreviewRunError(
                f"image_download_http_{response.status_code}",
                "图片下载端点未返回可用图片",
            )
        body = response.content
        if not body or len(body) > max_bytes:
            raise PreviewRunError("image_download_invalid", "图片大小不符合本地预览限制")
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        return body, media_type


def _safe_http_error(response: httpx.Response) -> str:
    """Keep provider/API response bodies out of the preview report."""

    del response
    return "API 请求失败，详细原因请查看对应阶段的安全错误码"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_text(value: object, *, fallback: str = "", limit: int = 800) -> str:
    if not isinstance(value, str):
        return fallback
    return " ".join(value.split())[:limit]


def _safe_filename(value: str) -> str:
    normalized = _SAFE_FILENAME.sub("-", value).strip(".-")
    return normalized or "preview-image"


def _string_list(value: object, *, limit: int = 24) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_text(item, limit=120) for item in value if isinstance(item, str)][:limit]


def _as_stage(
    state: PreviewState,
    stage_id: str,
    label: str,
) -> StageState:
    stage = StageState(id=stage_id, label=label, started_at=_now())
    state.stages.append(stage)
    return stage


def _finish_stage(
    stage: StageState,
    *,
    status: str,
    run_id: object = None,
    version: object = None,
    error: PreviewRunError | None = None,
) -> None:
    stage.status = status
    stage.run_id = str(run_id) if run_id is not None else stage.run_id
    stage.version = str(version) if version is not None else stage.version
    if error is not None:
        stage.error_code = error.code
        stage.error_message = error.message
    stage.finished_at = _now()


def _extract_trailing_hashtags(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    hashtags = [token for token in lines[-1].split() if _HASHTAG.fullmatch(token)]
    return hashtags if 1 <= len(hashtags) <= 3 else []


def _first_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized.startswith(("https://", "http://")):
        return normalized[:2000]
    return None


def _quality_snapshot(value: object, *, default_status: str = "unknown") -> dict[str, Any]:
    record = _first_dict(value)
    passed = record.get("passed")
    accepted = record.get("accepted")
    status = record.get("status")
    if not isinstance(status, str):
        if passed is True:
            status = "passed"
        elif passed is False:
            status = "failed"
        elif accepted is True:
            status = "accepted"
        elif accepted is False:
            status = "rejected"
        else:
            status = default_status
    return {
        "status": status,
        "passed": passed if isinstance(passed, bool) else None,
        "accepted": accepted if isinstance(accepted, bool) else None,
        "version": _safe_text(
            record.get("version") or record.get("rule_version") or record.get("prompt_version"),
            limit=120,
        ),
        "issue_codes": _string_list(record.get("issue_codes") or record.get("codes")),
        "issues": _safe_issues(record.get("issues")),
    }


def _safe_issues(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    issues: list[dict[str, Any]] = []
    for index, item in enumerate(value[:24]):
        record = _first_dict(item)
        code = _safe_text(record.get("code"), fallback=f"issue_{index + 1}", limit=80)
        if not code:
            code = f"issue_{index + 1}"
        issues.append(
            {
                "id": f"finding-{index + 1}-{code}",
                "code": code,
                "message": _safe_text(record.get("message"), fallback="未提供问题说明", limit=240),
                "severity": (
                    record.get("severity")
                    if record.get("severity") in {"info", "warning", "error"}
                    else "error"
                ),
                "field": _safe_text(record.get("field"), limit=80) or None,
                "claim_id": _safe_text(record.get("claim_id"), limit=80) or None,
            }
        )
    return issues


def _findings_from_quality(
    state: PreviewState,
    *,
    stage: str,
    quality: dict[str, Any],
) -> None:
    for issue in quality.get("issues", []):
        state.findings.append(
            {
                "id": f"{stage}-{issue['id']}",
                "stage": stage,
                "severity": issue["severity"],
                "code": issue["code"],
                "message": issue["message"],
                "field": issue.get("field"),
            }
        )


def _poll(
    api: PreviewApi,
    path: str,
    *,
    terminal: set[str],
    poll_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        record = api.request("GET", path)
        status = record.get("status")
        if isinstance(status, str) and status in terminal:
            return record
        if time.monotonic() >= deadline:
            raise PreviewRunError("stage_timeout", "阶段在本地等待窗口内没有完成")
        time.sleep(max(0.2, poll_seconds))


def _choose_unused_business_date(api: PreviewApi, *, start: date) -> date:
    candidate = start
    for _ in range(60):
        try:
            api.request("GET", f"/api/v1/daily-topics/{candidate.isoformat()}?profile=preview")
        except PreviewRunError as error:
            if error.code == "api_http_404":
                return candidate
            raise
        candidate += timedelta(days=1)
    raise PreviewRunError("preview_date_unavailable", "没有找到可隔离的预览业务日期")


def _dedupe_sources(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        source_id = _safe_text(source.get("id"), limit=120)
        url = _safe_url(source.get("url"))
        key = source_id or url or f"source-{len(result) + 1}"
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "id": source_id or key,
                "title": _safe_text(source.get("title"), fallback="教育新闻候选", limit=300),
                "source_name": _safe_text(
                    source.get("source_name") or source.get("publisher"), limit=120
                )
                or None,
                "url": url,
                "source_tier": _safe_text(source.get("source_tier") or source.get("tier"), limit=8)
                or None,
                "published_at": _safe_text(source.get("published_at"), limit=80) or None,
                "summary": _safe_text(source.get("summary"), limit=500) or None,
                "status": _safe_text(source.get("status"), fallback="candidate", limit=40),
                "is_selected": source.get("is_selected") is True,
            }
        )
    return result[:100]


def _sources_from_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for member in event.get("members", []) if isinstance(event.get("members"), list) else []:
        if not isinstance(member, dict):
            continue
        occurrences = member.get("source_occurrences")
        occurrence = occurrences[0] if isinstance(occurrences, list) and occurrences else {}
        occurrence = _first_dict(occurrence)
        sources.append(
            {
                "id": member.get("candidate_id") or member.get("normalized_article_id"),
                "title": member.get("title") or event.get("representative_title"),
                "source_name": occurrence.get("source_display_name"),
                "url": occurrence.get("final_url") or member.get("canonical_url"),
                "source_tier": occurrence.get("trust_tier"),
                "published_at": member.get("published_at"),
                "summary": member.get("summary") or event.get("summary"),
                "status": "selected_event_member",
                "is_selected": True,
            }
        )
    return sources


def _sources_from_analyses(
    api: PreviewApi,
    governance: dict[str, Any],
) -> list[dict[str, Any]]:
    jobs = api.request("GET", f"/api/v1/governance-runs/{governance['id']}/jobs").get("items", [])
    sources: list[dict[str, Any]] = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or not job.get("candidate_id"):
            continue
        candidate_id = str(job["candidate_id"])
        try:
            detail = api.request("GET", f"/api/v1/candidate-analyses/{candidate_id}")
        except PreviewRunError:
            continue
        occurrences = detail.get("source_occurrences")
        occurrence = occurrences[0] if isinstance(occurrences, list) and occurrences else {}
        occurrence = _first_dict(occurrence)
        sources.append(
            {
                "id": candidate_id,
                "title": detail.get("title"),
                "source_name": occurrence.get("source_display_name"),
                "url": detail.get("canonical_url") or detail.get("original_url"),
                "source_tier": occurrence.get("trust_tier"),
                "published_at": detail.get("published_at"),
                "summary": detail.get("summary"),
                "status": detail.get("status") or job.get("status"),
                "is_selected": False,
            }
        )
    return sources


def _topic_snapshot(
    api: PreviewApi,
    selection: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    score = _first_dict(selection.get("selected_score"))
    selected_event_id = selection.get("selected_event_id")
    event: dict[str, Any] = {}
    if selected_event_id:
        event = api.request("GET", f"/api/v1/events/{selected_event_id}")
    explanation = score.get("explanation")
    if isinstance(explanation, dict):
        explanation_text = json.dumps(explanation, ensure_ascii=False, sort_keys=True)
    else:
        explanation_text = _safe_text(
            explanation, fallback="通过版本化选题评分和硬 veto 检查", limit=1000
        )
    categories = event.get("categories") if isinstance(event.get("categories"), list) else []
    topic = {
        "title": score.get("event_title") or event.get("representative_title") or "未提供选题",
        "summary": event.get("summary"),
        "category": categories[0] if categories else None,
        "source_trust": "A/B（权威或主流来源）",
        "decision": selection.get("decision"),
        "decision_kind": selection.get("decision"),
        "score": score.get("total"),
        "threshold": score.get("threshold"),
        "selection_explanation": explanation_text,
        "selected_event_id": selected_event_id,
        "selected_source_id": None,
    }
    sources = _sources_from_event(event)
    if sources:
        topic["selected_source_id"] = sources[0].get("id")
    return topic, sources


def _copy_snapshot(detail: dict[str, Any]) -> dict[str, Any]:
    raw_drafts = detail.get("drafts")
    drafts: list[object] = raw_drafts if isinstance(raw_drafts, list) else []
    active_id = detail.get("active_draft_version_id")
    draft = next(
        (
            item
            for item in drafts
            if isinstance(item, dict) and str(item.get("id")) == str(active_id)
        ),
        None,
    )
    if draft is None and drafts and isinstance(drafts[-1], dict):
        draft = drafts[-1]
    draft = draft or {}
    copywriting = _safe_text(draft.get("copywriting"), limit=1200)
    return {
        "copywriting": copywriting,
        "hashtags": _extract_trailing_hashtags(copywriting),
        "parent_takeaway": _safe_text(draft.get("parent_takeaway"), limit=300),
        "interaction": _safe_text(draft.get("interaction"), limit=180),
        "source_note": _safe_text(draft.get("source_note"), limit=500),
        "version": draft.get("version"),
        "draft_version_id": draft.get("id"),
        "validation": {
            "status": "passed" if draft.get("validation_passed") is True else "failed",
            "passed": draft.get("validation_passed")
            if isinstance(draft.get("validation_passed"), bool)
            else None,
            "version": "copy-deterministic-validation",
            "issues": _safe_issues(draft.get("issues")),
        },
        "audit": {
            "status": "accepted" if draft.get("audit_accepted") is True else "rejected",
            "accepted": draft.get("audit_accepted")
            if isinstance(draft.get("audit_accepted"), bool)
            else None,
            "version": "copy-llm-audit",
            "issues": _safe_issues(draft.get("issues")),
        },
    }


def _brand_bindings(package: dict[str, Any]) -> list[dict[str, Any]]:
    values = package.get("brand_bindings")
    if not isinstance(values, list):
        return []
    bindings: list[dict[str, Any]] = []
    for index, item in enumerate(values[:40]):
        record = _first_dict(item)
        bindings.append(
            {
                "id": _safe_text(
                    record.get("id") or record.get("brand_chunk_id"),
                    fallback=f"brand-binding-{index + 1}",
                    limit=120,
                ),
                "title": _safe_text(
                    record.get("title") or record.get("label"),
                    fallback="赛先生品牌资料",
                    limit=180,
                ),
                "role": _safe_text(record.get("role"), limit=80) or None,
                "reason": _safe_text(
                    record.get("reason") or record.get("selection_reason"), limit=300
                )
                or None,
                "tags": _string_list(record.get("tags")),
            }
        )
    return bindings


def _manifest(state: PreviewState) -> dict[str, Any]:
    image = state.image or {"status": "missing"}
    copy = _copy_snapshot(state.copy_detail) if state.copy_detail else {}
    package = state.package
    validation = _quality_snapshot(
        package.get("validation") if package else copy.get("validation"),
        default_status="pending",
    )
    audit = _quality_snapshot(
        package.get("audit") if package else copy.get("audit"),
        default_status="pending",
    )
    if not state.generated_at:
        state.generated_at = _now()
    status = "ready"
    if state.topic.get("decision") == "no_topic":
        status = "no_topic"
    elif state.error_code:
        status = "failed"
    elif any(stage.status == "failed" for stage in state.stages):
        status = "failed"
    elif image.get("status") == "review_required" or package.get("status") == "rejected":
        status = "review_required"
    elif image.get("status") not in {"succeeded", "ready"}:
        status = "loading" if image.get("status") in {"queued", "running"} else "review_required"

    safe_image = {
        "status": image.get("status", "missing"),
        "filename": image.get("filename", ""),
        "url": image.get("url"),
        "alt": f"{state.topic.get('title') or '科学教育'}的赛先生品牌 IP 预览图",
        "media_type": image.get("media_type"),
        "width": image.get("width"),
        "height": image.get("height"),
        "byte_size": image.get("byte_size"),
        "validation": _quality_snapshot(image.get("validation"), default_status="pending"),
        "audit": _quality_snapshot(image.get("audit"), default_status="not_configured"),
    }
    safe_copy = {
        "copywriting": copy.get("copywriting", ""),
        "hashtags": copy.get("hashtags", []),
        "parent_takeaway": copy.get("parent_takeaway", ""),
        "interaction": copy.get("interaction", ""),
        "source_note": copy.get("source_note", ""),
        "version": copy.get("version") or copy.get("draft_version_id"),
        "validation": validation,
        "audit": audit,
    }
    download_payload = {
        "schema_version": "preview-manifest-v1",
        "run_id": state.run_id,
        "business_date": state.business_date,
        "status": status,
        "topic": state.topic,
        "copy": safe_copy,
        "image": safe_image,
        "sources": state.sources,
        "brand_bindings": state.brand_bindings,
        "findings": state.findings,
    }
    return {
        "schema_version": "preview-manifest-v1",
        "run_id": state.run_id,
        "business_date": state.business_date,
        "generated_at": state.generated_at,
        "status": status,
        "error_code": state.error_code,
        "error_message": state.error_message,
        "stages": [stage.as_manifest() for stage in state.stages],
        "acquisition": {
            "run_id": state.acquisition.get("id"),
            "status": state.acquisition.get("status"),
            "jobs": state.acquisition.get("jobs", []),
        },
        "governance": {
            "run_id": state.governance.get("id"),
            "status": state.governance.get("status"),
        },
        "topic": state.topic,
        "sources": state.sources,
        "copy": safe_copy,
        "image": safe_image,
        "brand_bindings": state.brand_bindings,
        "validation": validation,
        "audit": audit,
        "material_package": {
            "id": package.get("id"),
            "status": package.get("status"),
            "review_status": package.get("review_status"),
        },
        "findings": state.findings,
        "download_payload": download_payload,
    }


def _write_manifest(state: PreviewState, *, latest_path: Path) -> None:
    state.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state.output_dir / "manifest.json"
    payload = json.dumps(_manifest(state), ensure_ascii=False, indent=2) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(payload, encoding="utf-8")


def _validate_png(body: bytes) -> tuple[int, int]:
    if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
        raise PreviewRunError("image_output_invalid", "下载结果不是合法 PNG 图片")
    width, height = struct.unpack(">II", body[16:24])
    if width != 1024 or height != 1024:
        raise PreviewRunError("image_dimensions_invalid", "生成图片不是 1024x1024")
    return width, height


def run_preview(
    *,
    api_base: str = "http://127.0.0.1:8000",
    business_date: date | None = None,
    output_root: Path | None = None,
    poll_seconds: float = 2.0,
    stage_timeout_seconds: float = 1800.0,
) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    root = output_root or repo_root / "output" / "preview"
    preview_id = str(uuid4())
    date_api = PreviewApi(api_base)
    try:
        resolved_business_date = business_date or _choose_unused_business_date(
            date_api,
            start=datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1),
        )
    finally:
        date_api.close()
    state = PreviewState(
        run_id=preview_id,
        business_date=resolved_business_date.isoformat(),
        output_dir=root / preview_id,
    )
    latest_path = root / "latest.json"
    api = PreviewApi(api_base)

    def checkpoint() -> None:
        _write_manifest(state, latest_path=latest_path)

    try:
        checkpoint()
        acquisition_stage = _as_stage(state, "acquisition", "权威来源采集")
        try:
            acquisition = api.request(
                "POST",
                "/api/v1/acquisition-runs",
                payload={"business_date": state.business_date},
                headers={"Idempotency-Key": f"preview-{preview_id}-acquisition"},
            )
            acquisition_id = acquisition["id"]
            acquisition = _poll(
                api,
                f"/api/v1/acquisition-runs/{acquisition_id}",
                terminal=_TERMINAL_ACQUISITION,
                poll_seconds=poll_seconds,
                timeout_seconds=stage_timeout_seconds,
            )
            jobs = api.request("GET", f"/api/v1/acquisition-runs/{acquisition_id}/jobs")
            state.acquisition = {**acquisition, "jobs": jobs.get("items", [])}
            _finish_stage(
                acquisition_stage,
                status="completed" if acquisition.get("status") != "failed" else "failed",
                run_id=acquisition_id,
                version=acquisition.get("acquisition_version"),
            )
            if acquisition.get("status") == "failed":
                raise PreviewRunError("acquisition_failed", "权威来源采集失败")
        except PreviewRunError as error:
            _finish_stage(acquisition_stage, status="failed", error=error)
            raise
        checkpoint()

        governance_stage = _as_stage(state, "governance", "事实治理")
        try:
            governance = api.request(
                "POST",
                "/api/v1/governance-runs",
                payload={"acquisition_run_id": state.acquisition["id"]},
                headers={"Idempotency-Key": f"preview-{preview_id}-governance"},
            )
            governance = _poll(
                api,
                f"/api/v1/governance-runs/{governance['id']}",
                terminal=_TERMINAL_GOVERNANCE,
                poll_seconds=poll_seconds,
                timeout_seconds=stage_timeout_seconds,
            )
            state.governance = governance
            governance_status = governance.get("status")
            _finish_stage(
                governance_stage,
                status="completed"
                if governance_status in {"succeeded", "partially_succeeded"}
                else str(governance_status),
                run_id=governance.get("id"),
                version=governance.get("version_bundle", {}).get("pipeline_version"),
            )
            if governance_status not in {"succeeded", "partially_succeeded"}:
                raise PreviewRunError("governance_failed", "事实治理未达到可选题状态")
        except PreviewRunError as error:
            _finish_stage(governance_stage, status="failed", error=error)
            raise
        checkpoint()

        topic_stage = _as_stage(state, "topic_selection", "Top 1 选题")
        try:
            selection = api.request(
                "POST",
                "/api/v1/topic-selection-runs",
                payload={"business_date": state.business_date},
            )
            selection = _poll(
                api,
                f"/api/v1/topic-selection-runs/{selection['id']}",
                terminal=_TERMINAL_TOPIC,
                poll_seconds=poll_seconds,
                timeout_seconds=stage_timeout_seconds,
            )
            state.topic_selection = selection
            state.topic, event_sources = _topic_snapshot(
                api,
                api.request("GET", f"/api/v1/daily-topics/{state.business_date}?profile=preview"),
            )
            state.sources = _dedupe_sources(
                event_sources + _sources_from_analyses(api, state.governance)
            )
            if state.topic_selection.get("status") != "succeeded":
                raise PreviewRunError("topic_selection_failed", "Top 1 选题阶段失败")
            if state.topic.get("decision") == "no_topic":
                _finish_stage(topic_stage, status="no_topic", run_id=selection.get("id"))
                state.error_code = "no_topic"
                state.error_message = "当前预览业务日期没有达到门槛的选题"
                checkpoint()
                return state.output_dir / "manifest.json"
            _finish_stage(
                topic_stage,
                status="completed",
                run_id=selection.get("id"),
                version=selection.get("scoring_version"),
            )
        except PreviewRunError as error:
            _finish_stage(topic_stage, status="failed", error=error)
            raise
        checkpoint()

        copy_stage = _as_stage(state, "copy_generation", "朋友圈文案生成")
        try:
            copy_run = api.request(
                "POST",
                "/api/v1/copy-generation-runs",
                payload={"business_date": state.business_date, "scoring_profile": "preview"},
            )
            copy_run = _poll(
                api,
                f"/api/v1/copy-generation-runs/{copy_run['id']}",
                terminal=_TERMINAL_COPY,
                poll_seconds=poll_seconds,
                timeout_seconds=stage_timeout_seconds,
            )
            state.copy_run = copy_run
            state.copy_detail = api.request(
                "GET", f"/api/v1/copy-generation-runs/{copy_run['id']}/detail"
            )
            copy_status = copy_run.get("status")
            if copy_status != "accepted":
                raise PreviewRunError(
                    str(copy_run.get("error_code") or "copy_generation_failed"),
                    "文案未通过验证和审计，已停止后续图片阶段",
                )
            draft = _copy_snapshot(state.copy_detail)
            _finish_stage(
                copy_stage,
                status="completed",
                run_id=copy_run.get("id"),
                version=str(draft.get("version") or "copy-preview"),
            )
        except PreviewRunError as error:
            _finish_stage(copy_stage, status="failed", error=error)
            raise
        checkpoint()

        material_stage = _as_stage(state, "material_package", "品牌视觉与素材包")
        try:
            package = api.request(
                "POST",
                "/api/v1/material-packages",
                payload={
                    "copy_generation_run_id": state.copy_run["id"],
                    "reviewer": "local-preview",
                },
            )
            package = _poll(
                api,
                f"/api/v1/material-packages/{package['id']}",
                terminal=_TERMINAL_PACKAGE,
                poll_seconds=poll_seconds,
                timeout_seconds=stage_timeout_seconds,
            )
            state.package = package
            state.brand_bindings = _brand_bindings(package)
            state.image = _first_dict(package.get("image"))
            package_status = package.get("status")
            image_status = state.image.get("status")
            if package_status not in {"awaiting_manual_use", "ready", "completed"}:
                raise PreviewRunError(
                    str(state.image.get("error_code") or "material_package_failed"),
                    "品牌视觉素材包未生成成功",
                )
            if image_status != "succeeded":
                raise PreviewRunError(
                    str(state.image.get("error_code") or "image_generation_failed"),
                    "图片未通过生成或安全校验",
                )
            download_url = state.image.get("download_url")
            if not isinstance(download_url, str) or not download_url.startswith("/"):
                raise PreviewRunError("image_download_invalid", "图片下载路径不是本地 API 路径")
            body, media_type = api.download(download_url)
            width, height = _validate_png(body)
            filename = f"image-{_safe_filename(state.run_id)}.png"
            image_path = state.output_dir / filename
            with image_path.open("xb") as handle:
                handle.write(body)
            state.image = {
                **state.image,
                "status": "succeeded",
                "url": f"/preview/{state.run_id}/{filename}",
                "filename": filename,
                "media_type": media_type or "image/png",
                "width": width,
                "height": height,
                "byte_size": len(body),
            }
            _finish_stage(
                material_stage,
                status="completed",
                run_id=package.get("id"),
                version=_first_dict(package.get("versions"))
                .get("image", {})
                .get("pipeline_version")
                if isinstance(_first_dict(package.get("versions")).get("image"), dict)
                else "material-package-v1",
            )
            _findings_from_quality(
                state,
                stage="copy_generation",
                quality=_quality_snapshot(package.get("validation")),
            )
            _findings_from_quality(
                state,
                stage="copy_generation",
                quality=_quality_snapshot(package.get("audit")),
            )
            _findings_from_quality(
                state,
                stage="image_generation",
                quality=_quality_snapshot(state.image.get("validation"), default_status="pending"),
            )
            _findings_from_quality(
                state,
                stage="image_generation",
                quality=_quality_snapshot(
                    state.image.get("audit"), default_status="not_configured"
                ),
            )
        except PreviewRunError as error:
            _finish_stage(material_stage, status="failed", error=error)
            state.error_code = error.code
            state.error_message = error.message
            raise
        checkpoint()
        return state.output_dir / "manifest.json"
    except PreviewRunError as error:
        state.error_code = state.error_code or error.code
        state.error_message = state.error_message or error.message
        checkpoint()
        return state.output_dir / "manifest.json"
    except Exception:
        state.error_code = state.error_code or "preview_runner_error"
        state.error_message = state.error_message or "预览 runner 发生未分类错误，未伪造成功结果"
        checkpoint()
        return state.output_dir / "manifest.json"
    finally:
        api.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--business-date", type=date.fromisoformat)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--stage-timeout-seconds", type=float, default=1800.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_args(sys.argv[1:] if argv is None else argv)
    manifest = run_preview(
        api_base=arguments.api_base,
        business_date=arguments.business_date,
        output_root=arguments.output_root,
        poll_seconds=arguments.poll_seconds,
        stage_timeout_seconds=arguments.stage_timeout_seconds,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
