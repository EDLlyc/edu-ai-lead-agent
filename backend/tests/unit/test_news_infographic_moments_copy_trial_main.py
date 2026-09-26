"""Frozen three-file, no-image/no-send Moments copy-only trial regression."""

# ruff: noqa: RUF001 -- frozen Chinese copy is intentional.

from __future__ import annotations

import asyncio
import json
import stat
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app import news_infographic_moments_copy_trial_main as trial_main
from app.application.services.news_infographic_rich_copy import (
    MomentsAuditVerdict,
    MomentsEditorialSpan,
    MomentsRichCard,
    MomentsRichDraft,
    MomentsRichProposal,
    build_moments_rich_draft_plan,
    preflight_moments_rich_layout,
    validate_moments_rich_proposal,
)
from app.core.config import Settings
from app.domain.news_infographic import validate_package_snapshot
from app.infrastructure.news_infographic_local import write_frozen_input_bundle
from app.news_infographic_moments_copy_trial_main import (
    CopyOnlyChatModel,
    TrialInputError,
    execute_trial,
    preflight_trial,
)
from pydantic import SecretStr
from test_news_infographic import package_payload


class FakeChatModel:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def complete_json(self, prompt: str) -> dict[str, object]:
        self.calls.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response


def _frozen_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    payload: dict[str, Any] = deepcopy(package_payload())
    payload["copy"]["prompt_version"] = "moments-generator-v19-exact-claim-span"
    payload["topic"]["content_slot_selection_id"] = str(uuid4())
    payload["topic"]["title"] = "教育部介绍科学课探究"
    payload["copy"]["copywriting"] = (
        "小赛洞察：教育部介绍科学课探究。孩子可以先问报道里到底说了什么。\n"
        "赛先生鼓励孩子提问。\n"
        f"新闻来源：教育部科学新闻\n原文链接：{payload['sources'][0]['source_url']}\n"
        "#赛先生科学"
    )
    payload["copy"]["parent_takeaway"] = "陪孩子提出一个具体问题，再共同查看新闻原文。"
    payload["copy"]["interaction"] = "你会先问孩子什么，再记录他从新闻里找到的依据？"
    payload["copy"]["source_note"] = "新闻来源与原文链接已核对。"
    case = validate_package_snapshot(payload)
    bundle_path = tmp_path / "input.json"
    write_frozen_input_bundle(bundle_path, (case,))
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    run_detail = {
        "id": str(case.copy_generation_run_id),
        "origin_kind": "content_slot",
        "content_slot_selection_id": payload["topic"]["content_slot_selection_id"],
        "business_date": case.business_date.isoformat(),
        "selected_event_id": str(case.selected_event_id),
        "selected_event_version_id": str(case.selected_event_version_id),
        "status": "accepted",
        "active_draft_version_id": str(case.draft_version_id),
        "drafts": [
            {
                "id": str(case.draft_version_id),
                "version": case.draft_version,
                "copywriting": case.copywriting,
                "parent_takeaway": payload["copy"]["parent_takeaway"],
                "interaction": payload["copy"]["interaction"],
                "source_note": payload["copy"]["source_note"],
                "claims": payload["copy"]["claims"],
                "validation_passed": True,
                "audit_accepted": True,
            }
        ],
    }
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps(run_detail, ensure_ascii=False), encoding="utf-8")
    return bundle_path, package_path, run_path


def _preflight(paths: tuple[Path, Path, Path]) -> Any:
    return preflight_trial(input_bundle=paths[0], package_detail=paths[1], copy_run_detail=paths[2])


def _proposal(preflight: Any) -> MomentsRichProposal:
    case = preflight.case
    fact = next(
        span for span in preflight.seed.available_bound_claims if span.kind == "external_fact"
    )

    brand = next(
        span for span in preflight.seed.available_bound_claims if span.kind == "brand_statement"
    )
    return MomentsRichProposal(
        input_fingerprint=case.fingerprint,
        seed_fingerprint=preflight.seed.seed_fingerprint,
        package_id=case.package_id,
        copy_generation_run_id=case.copy_generation_run_id,
        draft_version_id=case.draft_version_id,
        source_name=case.source_name,
        source_date=case.source_date,
        source_url=case.source_url,
        title="教育部介绍科学课探究",
        title_claim_id=fact.claim_id,
        top_summary=(
            MomentsEditorialSpan(
                kind="editorial_context",
                text="解读：科学课探究适合先从报道原句开始，再把自己的疑问和报道事实分开记录。",
                anchor_claim_id=fact.claim_id,
                anchor_text="科学课探究",
                inspiration="moments_body",
            ),
        ),
        cards=(
            MomentsRichCard(
                role="news_context",
                heading="读懂科学课探究",
                spans=(
                    fact,
                    MomentsEditorialSpan(
                        kind="editorial_context",
                        text="解读：围绕科学课探究，可以先核对新闻原句，再讨论我们想进一步了解什么，不把猜想当作报道结论。",
                        anchor_claim_id=fact.claim_id,
                        anchor_text="科学课探究",
                        inspiration="moments_body",
                    ),
                ),
            ),
            MomentsRichCard(
                role="child_inquiry",
                heading="和孩子聊科学课探究",
                spans=(
                    MomentsEditorialSpan(
                        kind="editorial_activity",
                        text="可以围绕科学课探究问孩子：报道到底说了什么？先圈出原句，再记录自己的疑问，最后一起讨论还需查证的地方。",
                        anchor_claim_id=fact.claim_id,
                        anchor_text="科学课探究",
                        inspiration="interaction",
                    ),
                ),
            ),
            MomentsRichCard(
                role="brand_teaching",
                heading="从孩子提问开始",
                spans=(
                    brand,
                    MomentsEditorialSpan(
                        kind="editorial_example",
                        text="例如，可以把孩子提问作为探索练习，请他先说出自己的想法，再尝试和新闻原句比较，不预设学习结果。",
                        anchor_claim_id=brand.claim_id,
                        anchor_text="孩子提问",
                        inspiration="parent_takeaway",
                    ),
                ),
            ),
        ),
    )


def _draft(preflight: Any) -> MomentsRichDraft:
    plan = build_moments_rich_draft_plan(preflight.case, preflight.binding, preflight.seed)
    return MomentsRichDraft(
        top=(f"解读：{plan.news_anchor}值得先从报道原句入手，再把自己的推断和新闻事实分开记录。"),
        news=(
            f"解读：围绕{plan.news_anchor}，可以先核对报道原句，再讨论想继续了解的地方，"
            "不要把猜想写成报道结论。"
        ),
        child=(
            "可以先问孩子：报道到底说了什么？先圈出原句，"
            "再记录自己的疑问，把证据和猜想分开，最后一起讨论哪些地方还需要继续查证。"
        ),
        brand=(
            f"例如，可以借{plan.brand_anchor}这个教学想法，围绕{plan.news_anchor}"
            "请孩子先说出自己的判断，再尝试和新闻原句比较，不预设学习结果。"
        ),
    )


def _accepted_audit() -> dict[str, object]:
    return MomentsAuditVerdict(
        fact_bound=True,
        brand_bound=True,
        editorial_distinct=True,
        child_specific=True,
        non_redundant=True,
        no_unsupported_assertions=True,
        no_exaggerated_outcomes=True,
        accepted=True,
        issues=(),
    ).model_dump(mode="json")


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            "Moments editorial introduces an unsupported number",
            "editorial_numeric_paraphrase",
        ),
        (
            "Moments editorial repeats an unsupported measurement unit",
            "editorial_unit_paraphrase",
        ),
        (
            "Moments editorial infers an unbound mechanism",
            "editorial_mechanism_unbound",
        ),
    ],
)
def test_new_editorial_rejections_have_closed_private_codes(message: str, code: str) -> None:
    assert trial_main._deterministic_diagnostic(ValueError(message), stage="assembly") == {
        "schema_version": "daily-news-infographic-moments-deterministic-diagnostic-v1",
        "stage": "assembly",
        "reason_code": code,
    }


def test_provider_free_preflight_checks_three_frozen_files_without_output(tmp_path: Path) -> None:
    paths = _frozen_files(tmp_path)
    preflight = _preflight(paths)
    assert preflight.case.package_id == preflight.binding.package_id
    assert preflight.seed.proposal_ready is False
    assert preflight.safe_projection()["model_calls"] == 0
    assert "unverified_editorial_inspiration" in preflight.generation_prompt
    assert "恰好四个字符串键" in preflight.generation_prompt
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "input.json",
        "package.json",
        "run.json",
    ]


def test_rejected_historical_v1_does_not_hide_accepted_active_v2(tmp_path: Path) -> None:
    paths = _frozen_files(tmp_path)
    package = json.loads(paths[1].read_text(encoding="utf-8"))
    run = json.loads(paths[2].read_text(encoding="utf-8"))
    active_id = str(uuid4())
    package["copy"]["draft_version_id"] = active_id
    package["copy"]["version"] = 2
    historical = run["drafts"][0]
    historical["validation_passed"] = False
    historical["audit_accepted"] = None
    active = deepcopy(historical)
    active.update(
        id=active_id,
        version=2,
        validation_passed=True,
        audit_accepted=True,
    )
    run["active_draft_version_id"] = active_id
    run["drafts"].append(active)
    paths[1].write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    rebound_bundle = tmp_path / "active-v2-input.json"
    write_frozen_input_bundle(rebound_bundle, (validate_package_snapshot(package),))
    rebound_paths = (rebound_bundle, paths[1], paths[2])

    preflight = _preflight(rebound_paths)
    assert str(preflight.case.draft_version_id) == active_id
    assert preflight.binding.copy_snapshot.version == 2

    run["drafts"][1]["copywriting"] += "不属于已接受素材包的文字"
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TrialInputError, match="active draft differs"):
        _preflight(rebound_paths)


def test_binding_id_order_is_not_a_claim_mismatch_but_missing_id_is(tmp_path: Path) -> None:
    paths = _frozen_files(tmp_path)
    package = json.loads(paths[1].read_text(encoding="utf-8"))
    run = json.loads(paths[2].read_text(encoding="utf-8"))
    extra = deepcopy(package["sources"][0])
    extra_id = str(uuid4())
    extra["evidence_binding_id"] = extra_id
    package["sources"].append(extra)
    package["copy"]["claims"][0]["evidence_ids"].append(extra_id)
    run["drafts"][0]["claims"][0]["evidence_ids"] = list(
        reversed(package["copy"]["claims"][0]["evidence_ids"])
    )
    paths[1].write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    rebound_bundle = tmp_path / "reordered-bindings-input.json"
    write_frozen_input_bundle(rebound_bundle, (validate_package_snapshot(package),))
    rebound_paths = (rebound_bundle, paths[1], paths[2])

    assert (
        _preflight(rebound_paths).case.package_id == validate_package_snapshot(package).package_id
    )

    run["drafts"][0]["claims"][0]["evidence_ids"][0] = str(uuid4())
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TrialInputError, match="active draft differs"):
        _preflight(rebound_paths)

    run["drafts"][0]["claims"][0]["evidence_ids"] = [extra_id, extra_id]
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TrialInputError, match="active draft differs"):
        _preflight(rebound_paths)


def test_cli_default_is_provider_free_and_safe_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _frozen_files(tmp_path)

    def forbidden_settings() -> None:
        raise AssertionError("default preflight must not construct provider settings")

    monkeypatch.setattr(trial_main, "get_settings", forbidden_settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "moments-copy-trial",
            "--input-bundle",
            str(paths[0]),
            "--package-detail",
            str(paths[1]),
            "--copy-run-detail",
            str(paths[2]),
        ],
    )
    assert asyncio.run(trial_main._main()) == 0
    projection = json.loads(capsys.readouterr().out)
    assert projection["status"] == "preflight_valid_copy_only"
    assert projection["model_calls"] == 0
    assert projection["send_ready"] is False


def test_copy_only_chat_needs_no_image_provider_and_makes_one_post() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":true}'}}]},
        )

    settings = Settings(
        _env_file=None,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://example.org/api/paas/v4",
        ai_platform_api_key=SecretStr("fake-chat-secret"),
        image_provider_mode="disabled",
        comfly_api_key=None,
    )

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await CopyOnlyChatModel(settings, client).complete_json("local prompt")

    assert asyncio.run(run()) == {"ok": True}
    assert len(requests) == 1
    assert requests[0].url.path == "/api/paas/v4/chat/completions"
    assert json.loads(requests[0].content)["max_tokens"] == 3200


def test_copy_only_chat_does_not_retry_provider_rejection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, text="private provider details")

    settings = Settings(
        _env_file=None,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://example.org/api/paas/v4",
        ai_platform_api_key=SecretStr("fake-chat-secret"),
        image_provider_mode="disabled",
        comfly_api_key=None,
    )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await CopyOnlyChatModel(settings, client).complete_json("local prompt")

    with pytest.raises(RuntimeError, match="request rejected"):
        asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize(
    "change", ["package_source", "run_draft", "run_status", "draft_text", "draft_source_note"]
)
def test_identity_or_acceptance_mismatch_stops_before_intent(tmp_path: Path, change: str) -> None:
    paths = _frozen_files(tmp_path)
    if change == "package_source":
        payload = json.loads(paths[1].read_text(encoding="utf-8"))
        payload["sources"][0]["source_url"] = "https://example.org/wrong"
        paths[1].write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload = json.loads(paths[2].read_text(encoding="utf-8"))
        if change == "run_draft":
            payload["active_draft_version_id"] = str(uuid4())
        elif change == "run_status":
            payload["status"] = "running"
        elif change == "draft_source_note":
            payload["drafts"][0]["source_note"] = "来源变了。"
        else:
            payload["drafts"][0]["copywriting"] += "虚构"
        paths[2].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        _preflight(paths)
    assert not list(tmp_path.glob("*.intent.json"))


def test_no_safe_topic_claim_anchor_blocks_before_any_intent(tmp_path: Path) -> None:
    paths = _frozen_files(tmp_path)
    package = json.loads(paths[1].read_text(encoding="utf-8"))
    package["topic"]["title"] = "完全无关的其他话题"
    paths[1].write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    unrelated_input = tmp_path / "unrelated-input.json"
    write_frozen_input_bundle(unrelated_input, (validate_package_snapshot(package),))
    with pytest.raises(ValueError, match="safe frozen news title"):
        preflight_trial(
            input_bundle=unrelated_input,
            package_detail=paths[1],
            copy_run_detail=paths[2],
        )
    assert not list(tmp_path.rglob("*.intent.json"))


def test_full_proposal_metadata_is_rejected_by_flat_output_contract(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    model = FakeChatModel(_proposal(preflight).model_dump(mode="json"))
    output = tmp_path / "not-flat"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=output,
            models=model,
            model_name="fake",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "generation_schema_invalid"
    assert result["audit_intents"] == 0
    assert len(model.calls) == 1
    diagnostic = json.loads(
        (output / "private" / "generation-validation.json").read_text(encoding="utf-8")
    )
    assert diagnostic["reason_code"] == "draft_schema_invalid"
    assert diagnostic["issue_count"] >= 4
    assert "source_url" not in (output / "summary.json").read_text(encoding="utf-8")


def test_successful_fake_two_call_trial_stays_copy_only_unpublished(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    proposal = _proposal(preflight)
    validate_moments_rich_proposal(preflight.case, preflight.binding, preflight.seed, proposal)
    preflight_moments_rich_layout(preflight.case, preflight.binding, preflight.seed, proposal)
    model = FakeChatModel(_draft(preflight).model_dump(mode="json"), _accepted_audit())
    output = tmp_path / "trial-a"
    ledger = tmp_path / "intent-ledger"
    result = asyncio.run(
        execute_trial(
            preflight, output_dir=output, models=model, model_name="fake-zhipu", ledger_dir=ledger
        )
    )
    assert result["status"] == "copy_audit_passed_unpublished"
    assert result["generation_intents"] == result["audit_intents"] == 1
    assert result["proposal_ready"] is result["send_ready"] is False
    assert len(model.calls) == 2
    assert "only_factual_news_claim" in model.calls[0]
    assert "unverified_moments_context" in model.calls[1]
    assert sorted(item.name for item in (output / "private").iterdir()) == [
        "audit-prompt.json",
        "audit-verdict.json",
        "audit.intent.json",
        "generation-prompt.json",
        "generation-response.json",
        "generation.intent.json",
        "proposal.json",
    ]
    assert all(
        stat.S_IMODE(item.stat().st_mode) == 0o600 for item in (output / "private").iterdir()
    )
    assert len(list(ledger.glob("*.intent.json"))) == 1
    public = (output / "summary.json").read_text(encoding="utf-8")
    assert "教育部介绍" not in public and "private" not in public and "http" not in public
    assert not list(output.rglob("*.jpg")) and not list(output.rglob("*.png"))


@pytest.mark.parametrize(
    ("responses", "expected", "calls"),
    [
        ((RuntimeError("provider response secret"),), "generation_result_unknown", 1),
        (({"unexpected": "raw model text"},), "generation_schema_invalid", 1),
        (("bad_draft",), "generation_copy_rejected", 1),
        (("valid_draft", {"accepted": True}), "audit_schema_invalid", 2),
        (("valid_draft", RuntimeError("audit secret")), "audit_result_unknown", 2),
        (("valid_draft", "rejected_audit"), "copy_audit_rejected", 2),
    ],
)
def test_failed_or_unknown_states_never_become_send_ready(
    tmp_path: Path, responses: tuple[object, ...], expected: str, calls: int
) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    draft = _draft(preflight)
    rejected = _accepted_audit() | {
        "fact_bound": False,
        "accepted": False,
        "issues": ["fact_unbound"],
    }
    resolved = tuple(
        draft.model_dump(mode="json")
        if item == "valid_draft"
        else rejected
        if item == "rejected_audit"
        else (draft.model_dump(mode="json") | {"brand": draft.brand + "保证每个人都能成功。"})
        if item == "bad_draft"
        else item
        for item in responses
    )
    model = FakeChatModel(*resolved)
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=tmp_path / "trial-failure",
            models=model,
            model_name="fake-zhipu",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == expected
    assert len(model.calls) == calls
    assert result["send_ready"] is False
    assert result["proposal_ready"] is False
    assert "secret" not in json.dumps(result)
    public = (tmp_path / "trial-failure" / "summary.json").read_text(encoding="utf-8")
    assert "provider response secret" not in public
    assert "raw model text" not in public
    assert "audit secret" not in public
    assert "http" not in public
    private = tmp_path / "trial-failure" / "private"
    if expected == "generation_schema_invalid":
        response_path = private / "generation-response.json"
        diagnostic_path = private / "generation-validation.json"
        assert json.loads(response_path.read_text(encoding="utf-8")) == resolved[0]
        diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        assert diagnostic["reason_code"] == "draft_schema_invalid"
        assert diagnostic["issue_count"] >= 1
        assert "raw model text" not in diagnostic_path.read_text(encoding="utf-8")
        assert stat.S_IMODE(response_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(diagnostic_path.stat().st_mode) == 0o600
    if expected == "generation_result_unknown":
        assert not (private / "generation-response.json").exists()
        assert not (private / "generation-validation.json").exists()


def test_measured_budget_rejection_has_private_safe_code_and_no_audit(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    plan = build_moments_rich_draft_plan(preflight.case, preflight.binding, preflight.seed)
    draft = _draft(preflight).model_dump(mode="json")
    draft["news"] = str(draft["news"]).ljust(plan.news_editorial_max_chars + 1, "字")
    assert len(str(draft["news"])) <= 140
    model = FakeChatModel(draft)
    output = tmp_path / "trial-measured-rejection"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=output,
            models=model,
            model_name="fake-zhipu",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "generation_copy_rejected"
    assert result["generation_intents"] == 1
    assert result["audit_intents"] == 0
    assert result["proposal_ready"] is False
    assert result["send_ready"] is False
    assert len(model.calls) == 1
    private = output / "private"
    diagnostic = private / "generation-deterministic.json"
    detail = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert detail["stage"] == "assembly"
    assert detail["reason_code"] == "measured_budget_exceeded"
    assert stat.S_IMODE(diagnostic.stat().st_mode) == 0o600
    assert not (private / "audit.intent.json").exists()
    public = (output / "summary.json").read_text(encoding="utf-8")
    assert str(draft["news"]) not in public
    assert "measured_budget_exceeded" not in public


def test_off_topic_brand_stops_before_audit_with_private_closed_code(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    plan = build_moments_rich_draft_plan(preflight.case, preflight.binding, preflight.seed)
    draft = _draft(preflight)
    off_topic = draft.model_copy(update={"brand": draft.brand.replace(plan.news_anchor, "", 1)})
    model = FakeChatModel(off_topic.model_dump(mode="json"), _accepted_audit())
    output = tmp_path / "trial-off-topic-brand"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=output,
            models=model,
            model_name="fake-zhipu",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "generation_copy_rejected"
    assert result["generation_intents"] == 1
    assert result["audit_intents"] == 0
    assert len(model.calls) == 1
    assert not (output / "private" / "audit.intent.json").exists()
    diagnostic = output / "private" / "generation-deterministic.json"
    assert json.loads(diagnostic.read_text(encoding="utf-8"))["reason_code"] == (
        "brand_news_context_missing"
    )
    assert stat.S_IMODE(diagnostic.stat().st_mode) == 0o600
    assert "brand_news_context_missing" not in (output / "summary.json").read_text(encoding="utf-8")


def test_framed_45_character_child_reaches_audit_not_schema_rejection(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    child = (
        "可以先问孩子：报道原句写了什么？圈出证据，比较自己的猜想，再记录一处仍需进一步查证的细节。"
    )
    assert len(child) == 45
    draft = _draft(preflight).model_copy(update={"child": child})
    model = FakeChatModel(draft.model_dump(mode="json"), _accepted_audit())
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=tmp_path / "trial-child-45",
            models=model,
            model_name="fake-zhipu",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "copy_audit_passed_unpublished"
    assert result["generation_intents"] == 1
    assert result["audit_intents"] == 1
    assert result["proposal_ready"] is False
    assert result["send_ready"] is False
    assert len(model.calls) == 2
    assert not list((tmp_path / "trial-child-45").rglob("*.jpg"))


def test_schema_diagnostic_redacts_unexpected_keys_and_values(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    response = _draft(preflight).model_dump(mode="json")
    response.pop("child")
    response["secret_provider_key"] = "PRIVATE_MODEL_VALUE"
    model = FakeChatModel(response)
    output = tmp_path / "schema-invalid"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=output,
            models=model,
            model_name="fake",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "generation_schema_invalid"
    assert result["audit_intents"] == 0
    assert len(model.calls) == 1
    private = output / "private"
    raw = private / "generation-response.json"
    diagnostic = private / "generation-validation.json"
    assert json.loads(raw.read_text(encoding="utf-8")) == response
    detail = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert detail["reason_code"] == "draft_schema_invalid"
    assert {tuple(issue["loc"]) for issue in detail["issues"]} == {
        ("child",),
        ("unknown",),
    }
    assert {issue["type"] for issue in detail["issues"]} == {"missing", "extra_forbidden"}
    assert "secret_provider_key" not in diagnostic.read_text(encoding="utf-8")
    assert "PRIVATE_MODEL_VALUE" not in diagnostic.read_text(encoding="utf-8")
    assert "PRIVATE_MODEL_VALUE" not in (output / "summary.json").read_text(encoding="utf-8")
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in private.iterdir())


def test_oversized_generation_json_is_not_persisted_or_audited(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    model = FakeChatModel({"oversized": "x" * 24_001})
    output = tmp_path / "oversized"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=output,
            models=model,
            model_name="fake",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "generation_schema_invalid"
    assert result["audit_intents"] == 0
    assert len(model.calls) == 1
    assert not (output / "private" / "generation-response.json").exists()
    diagnostic_path = output / "private" / "generation-validation.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["reason_code"] == "generation_response_not_captured"
    assert "oversized" not in diagnostic_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(diagnostic_path.stat().st_mode) == 0o600


def test_deep_generation_json_keeps_safe_terminal_summary(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    nested: dict[str, object] = {}
    for _ in range(1200):
        nested = {"nested": nested}
    output = tmp_path / "deep-response"
    model = FakeChatModel(nested)
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=output,
            models=model,
            model_name="fake",
            ledger_dir=tmp_path / "intent-ledger",
        )
    )
    assert result["status"] == "generation_schema_invalid"
    assert result["audit_intents"] == 0
    assert len(model.calls) == 1
    assert not (output / "private" / "generation-response.json").exists()
    assert (output / "summary.json").is_file()


def test_unknown_intent_cannot_be_replayed_in_a_new_output_directory(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    ledger = tmp_path / "intent-ledger"
    first = FakeChatModel(RuntimeError("ambiguous outcome"))
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=tmp_path / "first",
            models=first,
            model_name="fake",
            ledger_dir=ledger,
        )
    )
    assert result["status"] == "generation_result_unknown"
    second = FakeChatModel(_draft(preflight).model_dump(mode="json"))
    with pytest.raises(TrialInputError, match="already exists"):
        asyncio.run(
            execute_trial(
                preflight,
                output_dir=tmp_path / "second",
                models=second,
                model_name="fake",
                ledger_dir=ledger,
            )
        )
    assert not second.calls


def test_package_policy_intent_key_does_not_change_with_edited_guidance(tmp_path: Path) -> None:
    paths = _frozen_files(tmp_path)
    first = _preflight(paths)
    package = json.loads(paths[1].read_text(encoding="utf-8"))
    run = json.loads(paths[2].read_text(encoding="utf-8"))
    alternate = "陪孩子从新闻里找事实，再把感兴趣的问题记录下来。"
    package["copy"]["parent_takeaway"] = alternate
    run["drafts"][0]["parent_takeaway"] = alternate
    paths[1].write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    second = _preflight(paths)
    assert first.seed.seed_fingerprint != second.seed.seed_fingerprint
    assert first.intent_key == second.intent_key


def test_output_directory_must_be_fresh_before_provider_intent(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    output = tmp_path / "existing"
    output.mkdir()
    model = FakeChatModel(_draft(preflight).model_dump(mode="json"))
    with pytest.raises(TrialInputError, match="fresh"):
        asyncio.run(
            execute_trial(
                preflight,
                output_dir=output,
                models=model,
                model_name="fake",
                ledger_dir=tmp_path / "intent-ledger",
            )
        )
    assert not model.calls


def test_edited_preflight_prompt_cannot_dispatch_paid_call(tmp_path: Path) -> None:
    preflight = _preflight(_frozen_files(tmp_path))
    altered = replace(preflight, generation_prompt=preflight.generation_prompt + " hidden")
    model = FakeChatModel(_draft(preflight).model_dump(mode="json"))
    with pytest.raises(TrialInputError, match="differs from frozen"):
        asyncio.run(
            execute_trial(
                altered,
                output_dir=tmp_path / "altered",
                models=model,
                model_name="fake",
                ledger_dir=tmp_path / "intent-ledger",
            )
        )
    assert not model.calls
    assert not (tmp_path / "altered").exists()
