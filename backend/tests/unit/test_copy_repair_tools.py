# ruff: noqa: RUF001

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from app.application.services.copy_repair_agent import ChatToolCall, ChatTurn, CopyRepairAgent
from app.application.services.copy_repair_tools import (
    EditResult,
    RepairWorkspace,
    build_repair_tool_registry,
)
from app.domain.copy_generation import (
    ActiveBrandContext,
    EligibleEvidence,
    LegacyDailyTopicOrigin,
    LockedTopicContext,
)
from app.schemas.copy_generation import (
    CopyIssue,
    DraftClaim,
    MaterialDraft,
    render_headline_hook_copy,
)

EVIDENCE_A = uuid4()
EVIDENCE_B = uuid4()
BRAND = uuid4()
QUOTE_A = "研究团队发布了用于机器人学习的世界模型。该模型在三项测试中表现领先。"
QUOTE_B = "专家表示，这项研究有助于机器人理解真实环境。"


def _workspace(claim_text: str = "该模型在三项测试中表现领先。") -> RepairWorkspace:
    topic = LockedTopicContext(
        origin=LegacyDailyTopicOrigin(
            daily_topic_selection_id=uuid4(), topic_selection_run_id=uuid4()
        ),
        business_date=date(2026, 9, 30),
        timezone="Asia/Shanghai",
        scoring_profile="preview",
        decision_kind="selected",
        selected_event_id=uuid4(),
        selected_event_version_id=uuid4(),
        no_topic_code=None,
        title="机器人世界模型取得新进展",
        summary="研究团队发布世界模型。",
        evidence=tuple(
            EligibleEvidence(
                evidence_id=evidence_id,
                candidate_id=uuid4(),
                passage_id=uuid4(),
                occurrence_id=uuid4(),
                snapshot_id=uuid4(),
                source_name="科技日报",
                source_url="https://example.test/article",
                source_tier="A",
                published_at=datetime(2026, 9, 30, tzinfo=UTC),
                exact_quote=quote,
            )
            for evidence_id, quote in ((EVIDENCE_A, QUOTE_A), (EVIDENCE_B, QUOTE_B))
        ),
    )
    brand = (
        ActiveBrandContext(
            chunk_id=BRAND,
            document_id=uuid4(),
            version_id=uuid4(),
            document_title="赛先生品牌介绍",
            document_kind="positioning",
            text="赛先生重视科学精神、好奇心、思考力和创造力。",
        ),
    )
    draft = MaterialDraft(
        copywriting=render_headline_hook_copy(
            "当机器人开始理解世界，正好和孩子聊聊怎样观察身边的变化🔭\n#赛先生科学 #人工智能",
            title=topic.title or "",
            source_name="科技日报",
            source_url="https://example.test/article",
        ),
        parent_takeaway="和孩子一起观察。",
        interaction="你觉得机器人怎样认识世界？",
        source_note="科技日报",
        image_prompt="小赛和赛先生观察机器人",
        claims=(
            DraftClaim(
                id="fact-1", text=claim_text, kind="external_fact", evidence_ids=(EVIDENCE_A,)
            ),
            DraftClaim(
                id="brand-1",
                text="赛先生重视科学精神、好奇心、思考力和创造力。",
                kind="brand_statement",
                brand_chunk_ids=(BRAND,),
            ),
        ),
    )
    return RepairWorkspace(
        topic=topic, brand_context=brand, rule_version="preview-v13-headline-hook", draft=draft
    )


@pytest.mark.asyncio
async def test_find_evidence_returns_verbatim_sentences_with_their_ids() -> None:
    registry = build_repair_tool_registry(_workspace())

    result = await registry.invoke("find_evidence", {"query": "三项测试"})

    sentence = result.model_dump()["sentences"][0]
    assert sentence == {
        "evidence_id": str(EVIDENCE_A),
        "source_name": "科技日报",
        "text": "该模型在三项测试中表现领先。",
    }


@pytest.mark.asyncio
async def test_replace_claim_accepts_only_verbatim_evidence_spans() -> None:
    workspace = _workspace(claim_text="该模型在五项测试中表现领先。")
    registry = build_repair_tool_registry(workspace)

    refused = await registry.invoke(
        "replace_claim",
        {"claim_id": "fact-1", "text": "该模型全球第一。", "evidence_ids": [str(EVIDENCE_A)]},
    )
    applied = await registry.invoke(
        "replace_claim",
        {
            "claim_id": "fact-1",
            "text": "该模型在三项测试中表现领先。",
            "evidence_ids": [str(EVIDENCE_A)],
        },
    )

    assert isinstance(refused, EditResult) and refused.ok is False
    assert refused.error_code == "claim_not_in_evidence"
    assert isinstance(applied, EditResult) and applied.ok is True
    assert workspace.draft.claims[0].text == "该模型在三项测试中表现领先。"
    assert workspace.edits == ["replace_claim:fact-1"]


@pytest.mark.asyncio
async def test_brand_claims_must_come_from_the_brand_text() -> None:
    registry = build_repair_tool_registry(_workspace())

    result = await registry.invoke(
        "replace_claim", {"claim_id": "brand-1", "text": "赛先生课程保证孩子成绩提高。"}
    )

    assert isinstance(result, EditResult) and result.error_code == "claim_not_in_brand"


@pytest.mark.asyncio
async def test_rewrite_hook_keeps_heading_source_and_tags() -> None:
    workspace = _workspace()
    registry = build_repair_tool_registry(workspace)

    result = await registry.invoke(
        "rewrite_hook", {"text": "机器人也要学着认识世界，正好和孩子聊聊我们是怎么观察的🔍"}
    )

    assert isinstance(result, EditResult) and result.ok
    assert result.draft.hook == "机器人也要学着认识世界，正好和孩子聊聊我们是怎么观察的🔍"
    assert "#赛先生科学" in workspace.draft.copywriting
    assert "科技日报" in workspace.draft.copywriting


@pytest.mark.asyncio
async def test_drop_claim_keeps_at_least_one_claim_and_check_draft_reports() -> None:
    workspace = _workspace()
    registry = build_repair_tool_registry(workspace)

    dropped = await registry.invoke("drop_claim", {"claim_id": "fact-1"})
    last = await registry.invoke("drop_claim", {"claim_id": "brand-1"})
    checked = await registry.invoke("check_draft", {})

    assert isinstance(dropped, EditResult) and dropped.ok
    assert isinstance(last, EditResult) and last.error_code in {
        "last_claim",
        "brand_claim_required",
    }
    assert [claim.id for claim in workspace.draft.claims] == ["brand-1"]
    assert "passed" in checked.model_dump()


@pytest.mark.asyncio
async def test_the_only_brand_statement_cannot_be_dropped_but_can_be_replaced() -> None:
    # 2026-10-03 noon: the agent dropped a repeated brand sentence, and the post lost its long
    # image (which needs one brand statement). Now it must swap in another brand sentence.
    workspace = _workspace()
    other = ActiveBrandContext(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        document_title="赛先生课程理念",
        document_kind="positioning",
        text="在赛先生科学，孩子亲手做实验，把观察到的现象说清楚。",
    )
    workspace.brand_context = (*workspace.brand_context, other)
    registry = build_repair_tool_registry(workspace)

    refused = await registry.invoke("drop_claim", {"claim_id": "brand-1"})
    replaced = await registry.invoke(
        "replace_claim",
        {
            "claim_id": "brand-1",
            "text": "在赛先生科学，孩子亲手做实验，把观察到的现象说清楚。",
            "brand_chunk_ids": [str(other.chunk_id)],
        },
    )

    assert isinstance(refused, EditResult) and refused.error_code == "brand_claim_required"
    assert any(str(other.chunk_id) in candidate for candidate in refused.candidates)
    assert isinstance(replaced, EditResult) and replaced.ok
    brand = [claim for claim in workspace.draft.claims if claim.kind == "brand_statement"]
    assert len(brand) == 1 and brand[0].brand_chunk_ids == (other.chunk_id,)


def test_repair_registry_describes_every_field_and_marks_workspace_tools() -> None:
    registry = build_repair_tool_registry(_workspace())
    schema = registry.canonical_schema()

    tools = {tool["name"]: tool for tool in schema["tools"]}  # type: ignore[index]
    assert list(tools) == [
        "check_draft",
        "drop_claim",
        "find_evidence",
        "list_brand_sentences",
        "replace_claim",
        "rewrite_hook",
        "use_brand_sentence",
    ]
    for name in ("drop_claim", "replace_claim", "rewrite_hook", "use_brand_sentence"):
        assert tools[name]["annotations"]["workspace_only"] is True
    assert tools["find_evidence"]["annotations"] == {"read_only": True, "open_world": False}
    for tool in tools.values():
        for field in tool["input_schema"].get("properties", {}).values():
            assert field.get("description"), tool["name"]


class _ScriptedModel:
    """Replays tool-call turns; records the tool results the agent sends back."""

    def __init__(self, turns: list[ChatTurn]) -> None:
        self._turns = turns
        self.seen_tool_results: list[str] = []

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.seen_tool_results = [m["content"] for m in messages if m.get("role") == "tool"]
        assert {tool["function"]["name"] for tool in tools} >= {"check_draft", "replace_claim"}
        return self._turns.pop(0)


def _call(call_id: str, name: str, arguments: dict[str, object]) -> ChatToolCall:
    return ChatToolCall(
        call_id=call_id, name=name, arguments_json=json.dumps(arguments, ensure_ascii=False)
    )


@pytest.mark.asyncio
async def test_agent_repairs_a_wrong_number_with_an_evidence_sentence() -> None:
    workspace = _workspace(claim_text="该模型在五项测试中表现领先。")
    model = _ScriptedModel(
        [
            ChatTurn(None, (_call("1", "find_evidence", {"query": "测试"}),), 100, 10),
            ChatTurn(
                None,
                (
                    _call(
                        "2",
                        "replace_claim",
                        {
                            "claim_id": "fact-1",
                            "text": "该模型在三项测试中表现领先。",
                            "evidence_ids": [str(EVIDENCE_A)],
                        },
                    ),
                    _call("3", "check_draft", {}),
                ),
                120,
                20,
            ),
            ChatTurn("完成", (), 130, 2),
        ]
    )
    issue = CopyIssue(code="evidence_mismatch", message="数字与原文不符", claim_id="fact-1")

    outcome = await CopyRepairAgent(model).repair(workspace, [issue])

    # check_draft passed after the flagged claim was edited, so the loop stops by itself.
    assert outcome.stopped == "checked"
    assert outcome.draft.claims[0].text == "该模型在三项测试中表现领先。"
    assert (outcome.rounds, outcome.tool_calls) == (2, 3)
    assert (outcome.prompt_tokens, outcome.completion_tokens) == (220, 30)
    assert outcome.edits == ("replace_claim:fact-1",)
    assert [step["tool"] for step in outcome.trace] == [
        "find_evidence",
        "replace_claim",
        "check_draft",
    ]


@pytest.mark.asyncio
async def test_agent_passes_structured_refusals_back_and_respects_the_call_cap() -> None:
    workspace = _workspace()
    refused = _call(
        "1",
        "replace_claim",
        {"claim_id": "fact-1", "text": "全球第一", "evidence_ids": [str(EVIDENCE_A)]},
    )
    unknown = _call("2", "delete_everything", {})
    model = _ScriptedModel([ChatTurn(None, (refused, unknown), 50, 5), ChatTurn("放弃", (), 60, 1)])

    flagged = CopyIssue(code="evidence_mismatch", message="与原文不符", claim_id="fact-1")
    outcome = await CopyRepairAgent(model).repair(workspace, [flagged])

    assert outcome.stopped == "gave_up"
    assert '"error_code":"claim_not_in_evidence"' in model.seen_tool_results[0]
    assert '"error_code": "agent_tool_unknown"' in model.seen_tool_results[1]
    assert outcome.edits == ()

    capped = _ScriptedModel(
        [ChatTurn(None, tuple(_call(str(i), "check_draft", {}) for i in range(3)), 10, 1)]
    )
    capped_outcome = await CopyRepairAgent(capped, max_tool_calls=2).repair(_workspace(), [])
    assert capped_outcome.stopped == "call_limit"
    assert capped_outcome.tool_calls == 2


@pytest.mark.asyncio
async def test_scoped_workspace_refuses_unflagged_edits_and_offers_candidates() -> None:
    workspace = _workspace(claim_text="该模型在五项测试中表现领先。")
    workspace.scope_to([("fact-1", "evidence_mismatch")])
    registry = build_repair_tool_registry(workspace)

    hook = await registry.invoke("rewrite_hook", {"text": "机器人也在学着观察世界，和孩子聊聊吧🔍"})
    brand = await registry.invoke("drop_claim", {"claim_id": "brand-1"})
    paraphrased = await registry.invoke(
        "replace_claim",
        {"claim_id": "fact-1", "text": "模型三项测试领先", "evidence_ids": [str(EVIDENCE_A)]},
    )

    assert isinstance(hook, EditResult) and hook.error_code == "not_flagged"
    assert isinstance(brand, EditResult) and brand.error_code == "not_flagged"
    assert isinstance(paraphrased, EditResult)
    assert paraphrased.error_code == "claim_not_in_evidence"
    assert paraphrased.candidates[0] == "该模型在三项测试中表现领先。"
    assert workspace.edits == []
    assert workspace.flagged_targets_edited() is False


@pytest.mark.asyncio
async def test_rewrite_hook_refuses_a_hook_that_breaks_the_hook_rules() -> None:
    workspace = _workspace()
    before = workspace.draft
    registry = build_repair_tool_registry(workspace)

    result = await registry.invoke(
        "rewrite_hook", {"text": "全国已有87%的家长开始让孩子学机器人，别让孩子输在起跑线😟"}
    )

    assert isinstance(result, EditResult) and result.ok is False
    assert result.error_code == "hook_breaks_rules"
    assert workspace.draft == before and workspace.edits == []


def test_workspace_refuses_copy_templates_the_tools_cannot_edit() -> None:
    from app.application.services.copy_repair_tools import UnsupportedRuleVersionError

    workspace = _workspace()
    with pytest.raises(UnsupportedRuleVersionError):
        RepairWorkspace(
            topic=workspace.topic,
            brand_context=workspace.brand_context,
            rule_version="preview-v12-standalone-heading-advisory",
            draft=workspace.draft,
        )


@pytest.mark.asyncio
async def test_a_brand_sentence_is_picked_by_id_not_copied() -> None:
    workspace = _workspace()
    other = ActiveBrandContext(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        document_title="赛先生课程理念",
        document_kind="positioning",
        text="在赛先生科学，孩子亲手做实验。孩子把观察到的现象说清楚。",
    )
    workspace.brand_context = (*workspace.brand_context, other)
    workspace.scope_to([("brand-1", "unsupported_brand_claim")])
    registry = build_repair_tool_registry(workspace)

    listed = await registry.invoke("list_brand_sentences", {})
    ids = {s.text: s.sentence_id for s in listed.sentences}  # type: ignore[attr-defined]
    in_use = [s.sentence_id for s in listed.sentences if s.in_use]  # type: ignore[attr-defined]
    same = await registry.invoke(
        "use_brand_sentence", {"claim_id": "brand-1", "sentence_id": in_use[0]}
    )
    unknown = await registry.invoke(
        "use_brand_sentence", {"claim_id": "brand-1", "sentence_id": "b99"}
    )
    not_brand = await registry.invoke(
        "use_brand_sentence",
        {"claim_id": "fact-1", "sentence_id": ids["孩子把观察到的现象说清楚。"]},
    )
    used = await registry.invoke(
        "use_brand_sentence",
        {"claim_id": "brand-1", "sentence_id": ids["孩子把观察到的现象说清楚。"]},
    )

    assert set(ids) == {
        "赛先生重视科学精神、好奇心、思考力和创造力。",
        "在赛先生科学，孩子亲手做实验。",
        "孩子把观察到的现象说清楚。",
    }
    assert isinstance(same, EditResult) and same.error_code == "same_sentence"
    assert isinstance(unknown, EditResult) and unknown.error_code == "unknown_sentence"
    assert isinstance(not_brand, EditResult) and not_brand.error_code == "not_flagged"
    assert isinstance(used, EditResult) and used.ok
    brand = next(c for c in workspace.draft.claims if c.id == "brand-1")
    assert brand.text == "孩子把观察到的现象说清楚。" and brand.brand_chunk_ids == (other.chunk_id,)
    assert workspace.edits == ["use_brand_sentence:brand-1"]
    assert workspace.flagged_targets_edited()


@pytest.mark.asyncio
async def test_the_agent_stops_after_the_same_error_three_times() -> None:
    workspace = _workspace()
    bad = {"claim_id": "brand-1", "text": "赛先生让孩子爱上科学。", "brand_chunk_ids": [str(BRAND)]}
    turns = [ChatTurn(None, (_call(str(n), "replace_claim", bad),), 300, 20) for n in range(6)]

    outcome = await CopyRepairAgent(_ScriptedModel(turns)).repair(
        workspace, (CopyIssue(code="unsupported_brand_claim", message="x", claim_id="brand-1"),)
    )

    assert outcome.stopped == "repeated_error"
    assert outcome.rounds == 3 and outcome.edits == ()
