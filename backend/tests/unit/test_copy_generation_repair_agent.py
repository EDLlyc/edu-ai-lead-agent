# ruff: noqa: RUF001
"""Agent-first repair in the copy executor: the agent's draft is kept only through the full gate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from app.application.ports.copy_generation import (
    DraftAuditRequest,
    DraftAuditResult,
    DraftGenerationRequest,
    DraftGenerationResult,
)
from app.application.services.copy_generation import (
    CopyGenerationExecutor,
    build_copy_version_bundle,
)
from app.application.services.copy_repair_agent import ChatTurn
from app.core.config import Settings
from app.core.errors import InvalidProviderOutputError
from app.domain.copy_generation import ActiveBrandContext, LockedTopicContext
from app.schemas.copy_generation import AuditVerdict, CopyIssue, MaterialDraft
from tests.unit.test_copy_generation import FakeCopyRepository
from tests.unit.test_copy_repair_tools import EVIDENCE_A, _call, _workspace

WRONG = "该模型在五项测试中表现领先。"
RIGHT = "该模型在三项测试中表现领先。"
RAW_HOOK = "当机器人开始理解世界，正好和孩子聊聊怎样观察身边的变化🔭\n#赛先生科学 #人工智能"


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(
        {"ai_provider_mode": "fake", "ai_chat_model": "fake-copy", **overrides}
    )


def _draft(claim_text: str) -> MaterialDraft:
    draft = _workspace(claim_text).draft
    return draft.model_copy(update={"copywriting": RAW_HOOK})


class Repository(FakeCopyRepository):
    def __init__(self) -> None:
        workspace = _workspace()
        super().__init__(
            workspace.topic,
            version_bundle=build_copy_version_bundle(_settings(), scoring_profile="preview"),
        )
        self.attempt_metadata: list[Mapping[str, object] | None] = []
        self.agent_attempts: list[dict[str, object]] = []

    async def persist_draft(self, **kwargs: object):  # type: ignore[no-untyped-def, override]
        self.attempt_metadata.append(kwargs.pop("attempt_metadata", None))  # type: ignore[arg-type]
        return await super().persist_draft(**kwargs)  # type: ignore[arg-type]

    async def record_repair_agent_attempt(self, **kwargs: object) -> bool:
        self.agent_attempts.append(kwargs)
        return True


class Brand:
    async def retrieve_for_copy(
        self, topic: LockedTopicContext, **_kwargs: object
    ) -> tuple[ActiveBrandContext, ...]:
        return _workspace().brand_context


class Generator:
    def __init__(self, *claims: str) -> None:
        self.claims = list(claims)
        self.calls = 0

    async def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult:
        self.calls += 1
        return DraftGenerationResult(
            draft=_draft(self.claims.pop(0)),
            provider="fake",
            model="fake-copy",
            request_fingerprint=f"generated-{self.calls}",
            provider_request_id=None,
            prompt_tokens=100,
            completion_tokens=50,
            reasoning_tokens=0,
            latency_ms=1,
        )


class Auditor:
    """Blocks a draft that still states the wrong number; can also block or fail on a call."""

    def __init__(self, *, block_calls: Sequence[int] = (), fail_calls: Sequence[int] = ()) -> None:
        self.calls = 0
        self.block_calls = set(block_calls)
        self.fail_calls = set(fail_calls)
        self.drafts: list[MaterialDraft] = []

    async def audit(self, request: DraftAuditRequest) -> DraftAuditResult:
        self.calls += 1
        self.drafts.append(request.draft)
        if self.calls in self.fail_calls:
            raise InvalidProviderOutputError(("invalid_schema",))
        wrong = any(claim.text == WRONG for claim in request.draft.claims)
        blocked = wrong or self.calls in self.block_calls
        return DraftAuditResult(
            verdict=AuditVerdict(
                accepted=not blocked,
                issues=(
                    (
                        CopyIssue(
                            code="evidence_mismatch",
                            message="数字与原文不符",
                            claim_id="fact-1",
                        ),
                    )
                    if blocked
                    else ()
                ),
            ),
            provider="fake",
            model="fake-copy",
            request_fingerprint=f"audit-{self.calls}",
            provider_request_id=None,
            prompt_tokens=900,
            completion_tokens=30,
            reasoning_tokens=0,
            latency_ms=1,
        )


class Agent:
    def __init__(self, turns: list[ChatTurn] | None = None, *, error: Exception | None = None):
        self.turns = turns or []
        self.error = error
        self.calls = 0

    async def complete(self, messages: object, tools: object) -> ChatTurn:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.turns.pop(0)


def _fixing_turns() -> list[ChatTurn]:
    return [
        ChatTurn(
            None,
            (
                _call(
                    "1",
                    "replace_claim",
                    {"claim_id": "fact-1", "text": RIGHT, "evidence_ids": [str(EVIDENCE_A)]},
                ),
                _call("2", "check_draft", {}),
            ),
            400,
            40,
        )
    ]


def _executor(
    repository: Repository,
    generator: Generator,
    auditor: Auditor,
    agent: Agent | None,
    **settings: object,
) -> CopyGenerationExecutor:
    return CopyGenerationExecutor(
        repository=repository,
        brand_retriever=Brand(),
        generator=generator,
        auditor=auditor,
        settings=_settings(**settings),
        repair_model=agent,
    )


@pytest.mark.asyncio
async def test_agent_repair_that_passes_the_gate_becomes_draft_two_without_regeneration() -> None:
    repository, generator, auditor, agent = (
        Repository(),
        Generator(WRONG),
        Auditor(),
        Agent(_fixing_turns()),
    )

    assert await _executor(repository, generator, auditor, agent).execute_next("w") is True

    assert repository.status == "accepted"
    assert repository.repair_count == 1
    assert generator.calls == 1  # draft 1 only: no regeneration
    assert auditor.calls == 2  # draft 1, then the agent's draft before it is stored
    draft_two = repository.drafts[1]
    assert draft_two.version == 2 and draft_two.repair_of_version_id == repository.drafts[0].id
    assert draft_two.draft.claims[0].text == RIGHT
    assert draft_two.audit is not None and draft_two.audit.accepted
    assert repository.active_draft_version_id == draft_two.id
    metadata = repository.attempt_metadata[1]
    assert metadata is not None and metadata["repair_method"] == "agent"
    assert metadata["stopped"] == "checked" and metadata["tool_calls"] == 2
    assert repository.agent_attempts == []


@pytest.mark.asyncio
async def test_agent_draft_blocked_by_the_auditor_is_dropped_and_regeneration_runs() -> None:
    # Audit 2 (the agent's draft) is blocked; the regenerated draft (audit 3) passes.
    repository, generator, auditor, agent = (
        Repository(),
        Generator(WRONG, RIGHT),
        Auditor(block_calls=(2,)),
        Agent(_fixing_turns()),
    )

    assert await _executor(repository, generator, auditor, agent).execute_next("w") is True

    assert repository.status == "accepted"
    assert generator.calls == 2
    assert [draft.version for draft in repository.drafts] == [1, 2]
    assert repository.attempt_metadata[1] is None  # draft 2 is the regeneration's
    (attempt,) = repository.agent_attempts
    assert attempt["error_code"] == "repair_agent_audit_blocked"
    metadata = attempt["safe_metadata"]
    assert isinstance(metadata, dict)
    assert metadata["issue_codes"] == ["evidence_mismatch"]
    assert metadata["gate_audit_prompt_tokens"] == 900
    assert attempt["prompt_tokens"] == 400 + 900


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent", "auditor", "error_code"),
    [
        (Agent(error=InvalidProviderOutputError(("invalid_schema",))), Auditor(), None),
        (Agent([ChatTurn("放弃", (), 300, 5)]), Auditor(), "repair_agent_no_fix"),
        (Agent(_fixing_turns()), Auditor(fail_calls=(2,)), "repair_agent_gate_error"),
    ],
)
async def test_agent_failure_falls_back_to_regeneration(
    agent: Agent, auditor: Auditor, error_code: str | None
) -> None:
    repository, generator = Repository(), Generator(WRONG, RIGHT)

    assert await _executor(repository, generator, auditor, agent).execute_next("w") is True

    assert repository.status == "accepted"
    assert repository.repair_count == 1
    assert generator.calls == 2
    (attempt,) = repository.agent_attempts
    if error_code is not None:
        assert attempt["error_code"] == error_code
    else:
        assert str(attempt["error_code"]).startswith("invalid")


@pytest.mark.asyncio
async def test_regenerate_mode_never_calls_the_agent() -> None:
    repository, generator, auditor, agent = (
        Repository(),
        Generator(WRONG, RIGHT),
        Auditor(),
        Agent(_fixing_turns()),
    )

    executor = _executor(repository, generator, auditor, agent, copy_repair_mode="regenerate")
    assert await executor.execute_next("w") is True

    assert agent.calls == 0
    assert generator.calls == 2
    assert repository.status == "accepted"
    assert repository.agent_attempts == []


@pytest.mark.asyncio
async def test_an_agent_draft_without_a_brand_statement_falls_back_to_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application.services import copy_generation as module
    from app.application.services.copy_repair_agent import RepairOutcome

    class DropsBrand:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def repair(self, workspace: object, issues: object) -> RepairOutcome:
            draft = _draft(RIGHT)
            draft = draft.model_copy(
                update={"claims": tuple(c for c in draft.claims if c.kind != "brand_statement")}
            )
            return RepairOutcome(draft=draft, stopped="checked", edits=("drop_claim:brand-1",))

    monkeypatch.setattr(module, "CopyRepairAgent", DropsBrand)
    repository, generator, auditor = Repository(), Generator(WRONG, RIGHT), Auditor()

    assert await _executor(repository, generator, auditor, Agent()).execute_next("w") is True

    assert generator.calls == 2  # the regeneration ran
    (attempt,) = repository.agent_attempts
    assert attempt["error_code"] == "repair_agent_rules_failed"
    metadata = attempt["safe_metadata"]
    assert isinstance(metadata, dict) and "brand_claim_missing" in metadata["issue_codes"]
    assert any(c.kind == "brand_statement" for c in repository.drafts[1].draft.claims)
