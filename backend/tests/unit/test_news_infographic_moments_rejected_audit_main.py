"""A rejected local draft may be reviewed once, but never promoted by review."""

# ruff: noqa: RUF001 -- exact Chinese review sample is intentional.

from __future__ import annotations

import asyncio
import json
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from app.application.services.news_infographic_rich_copy import MomentsRichDraft
from app.news_infographic_moments_copy_trial_main import TrialInputError, execute_trial
from app.news_infographic_moments_rejected_audit_main import (
    RejectedDraftAuditVerdict,
    execute_rejected_audit,
    preflight_rejected_audit,
)
from test_news_infographic_moments_copy_trial_main import (
    FakeChatModel,
    _draft,
    _frozen_files,
    _preflight,
)


def _rejected_source(tmp_path: Path) -> tuple[tuple[Path, Path, Path], Path, Path]:
    paths = _frozen_files(tmp_path)
    preflight = _preflight(paths)
    draft = _draft(preflight).model_dump(mode="json")
    assert isinstance(draft["top"], str)
    draft["top"] = draft["top"].replace("科学课探究", "科学课探究137亿光年")
    MomentsRichDraft.model_validate(draft)
    copy_dir = tmp_path / "copy"
    ledger_dir = tmp_path / "generation-ledger"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=copy_dir,
            models=FakeChatModel(draft),
            model_name="fake-chat",
            ledger_dir=ledger_dir,
        )
    )
    assert result["status"] == "generation_copy_rejected"
    assert result["audit_intents"] == 0
    return paths, copy_dir, ledger_dir


def _preflight_rejected(paths: tuple[Path, Path, Path], copy_dir: Path, ledger_dir: Path) -> Any:
    response = (copy_dir / "private" / "generation-response.json").read_bytes()
    return preflight_rejected_audit(
        input_bundle=paths[0],
        package_detail=paths[1],
        copy_run_detail=paths[2],
        source_copy_dir=copy_dir,
        expected_response_sha256=sha256(response).hexdigest(),
        copy_ledger_dir=ledger_dir,
    )


def _supportive_verdict() -> dict[str, object]:
    return RejectedDraftAuditVerdict(
        schema_version="daily-news-infographic-rejected-copy-review-v1",
        facts_supported=True,
        brand_aligned=True,
        child_inquiry_specific=True,
        copy_quality_sufficient=True,
        no_unsupported_assertions=True,
        reviewer_supports_candidate=True,
        issues=(),
        rationale="从审稿视角看表述可理解，但本意见不解除已有规则拒绝。",
    ).model_dump(mode="json")


def test_provider_free_preflight_reads_exact_rejected_response_without_writes(
    tmp_path: Path,
) -> None:
    paths, copy_dir, ledger_dir = _rejected_source(tmp_path)
    before = sorted(path.name for path in tmp_path.iterdir())
    preflight = _preflight_rejected(paths, copy_dir, ledger_dir)
    assert preflight.safe_projection()["audit_intents"] == 0
    assert preflight.safe_projection()["image_intents"] == 0
    assert preflight.safe_projection()["proposal_ready"] is False
    assert "rejected_candidate_exact_four_fields" in preflight.audit_prompt
    assert "137亿光年" in preflight.audit_prompt
    assert preflight.rejection_code in {"editorial_numeric_paraphrase", "assembly_policy_rejected"}
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_supportive_observational_review_never_promotes_copy_or_image(tmp_path: Path) -> None:
    paths, copy_dir, ledger_dir = _rejected_source(tmp_path)
    preflight = _preflight_rejected(paths, copy_dir, ledger_dir)
    model = FakeChatModel(_supportive_verdict())
    audit_ledger = tmp_path / "audit-ledger"
    summary = asyncio.run(
        execute_rejected_audit(
            preflight,
            output_dir=tmp_path / "audit-01",
            model=model,
            model_name="fake-reviewer",
            audit_ledger_dir=audit_ledger,
        )
    )
    assert len(model.calls) == 1
    assert summary["status"] == "observational_audit_complete"
    assert summary["reviewer_supports_candidate"] is True
    assert summary["production_effect"] == "none_observational_only"
    assert summary["generation_calls"] == 0
    assert summary["image_intents"] == 0
    assert summary["proposal_ready"] is False
    assert summary["send_ready"] is False
    assert not (copy_dir / "private" / "proposal.json").exists()
    assert not (copy_dir / "private" / "audit.intent.json").exists()
    assert (
        stat.S_IMODE((tmp_path / "audit-01" / "private" / "audit-prompt.json").stat().st_mode)
        == 0o600
    )
    assert (
        stat.S_IMODE((tmp_path / "audit-01" / "private" / "audit-verdict.json").stat().st_mode)
        == 0o600
    )
    assert len(list(audit_ledger.glob("*.intent.json"))) == 1


def test_unknown_review_consumes_fixed_intent_and_cannot_retry_elsewhere(tmp_path: Path) -> None:
    paths, copy_dir, ledger_dir = _rejected_source(tmp_path)
    preflight = _preflight_rejected(paths, copy_dir, ledger_dir)
    audit_ledger = tmp_path / "audit-ledger"
    unknown = asyncio.run(
        execute_rejected_audit(
            preflight,
            output_dir=tmp_path / "audit-01",
            model=FakeChatModel(RuntimeError("review timeout")),
            model_name="fake-reviewer",
            audit_ledger_dir=audit_ledger,
        )
    )
    assert unknown["status"] == "observational_audit_result_unknown"
    assert unknown["send_ready"] is False
    second = FakeChatModel(_supportive_verdict())
    with pytest.raises(TrialInputError, match="already exists"):
        asyncio.run(
            execute_rejected_audit(
                preflight,
                output_dir=tmp_path / "audit-02",
                model=second,
                model_name="fake-reviewer",
                audit_ledger_dir=audit_ledger,
            )
        )
    assert second.calls == []


def test_rejected_source_and_expected_hash_must_remain_immutable(tmp_path: Path) -> None:
    paths, copy_dir, ledger_dir = _rejected_source(tmp_path)
    preflight = _preflight_rejected(paths, copy_dir, ledger_dir)
    response = copy_dir / "private" / "generation-response.json"
    content = json.loads(response.read_text(encoding="utf-8"))
    content["top"] += "改"
    response.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TrialInputError, match="expected digest"):
        preflight_rejected_audit(
            input_bundle=paths[0],
            package_detail=paths[1],
            copy_run_detail=paths[2],
            source_copy_dir=copy_dir,
            expected_response_sha256=preflight.response_sha256,
            copy_ledger_dir=ledger_dir,
        )


def test_non_rejected_source_never_reaches_audit_intent(tmp_path: Path) -> None:
    paths, copy_dir, ledger_dir = _rejected_source(tmp_path)
    summary_path = copy_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "copy_audit_passed_unpublished"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(TrialInputError, match="not this exact rejected package"):
        _preflight_rejected(paths, copy_dir, ledger_dir)
    assert not (tmp_path / "audit-ledger").exists()


def test_invalid_observational_verdict_is_not_approval(tmp_path: Path) -> None:
    paths, copy_dir, ledger_dir = _rejected_source(tmp_path)
    preflight = _preflight_rejected(paths, copy_dir, ledger_dir)
    verdict = _supportive_verdict()
    verdict["issues"] = ["other_unbound_fact"]
    result = asyncio.run(
        execute_rejected_audit(
            preflight,
            output_dir=tmp_path / "audit-01",
            model=FakeChatModel(verdict),
            model_name="fake-reviewer",
            audit_ledger_dir=tmp_path / "audit-ledger",
        )
    )
    assert result["status"] == "observational_audit_schema_invalid"
    assert result["reviewer_supports_candidate"] is None
    assert result["send_ready"] is False
