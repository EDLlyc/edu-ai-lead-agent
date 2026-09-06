from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import app
import httpx
import pytest
from app.application.ports.copy_generation import DraftGenerationRequest
from app.application.services.copy_generation import build_copy_version_bundle
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.content_slots import ContentSlot
from app.domain.copy_generation import (
    ActiveBrandContext,
    ContentSlotTopicOrigin,
    EligibleEvidence,
    LockedTopicContext,
)
from app.infrastructure.ai.copy_generation import DeterministicFakeMaterialDraftGenerator
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    EventClusterVersionModel,
)
from app.schemas.copy_generation import CopyIssue
from pydantic import SecretStr

SCRIPT = Path(__file__).with_name("production-recovery-canary.py")
spec = importlib.util.spec_from_file_location("recovery_canary", SCRIPT)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = canary
spec.loader.exec_module(canary)
RUN = UUID("1929a4fa-43f3-4636-816a-7cde3175e24c")
SELECTION = UUID("249c02f0-9389-44ea-b571-2a1676b943a4")
ID = UUID("11111111-1111-4111-8111-111111111111")
SECRET = "private_sentinel_provider_body_and_credential"


def settings():
    # Synthetic settings only, no .env, network or production credentials.
    return Settings(_env_file=None, ai_provider_mode="fake").model_copy(
        update={
            "app_env": "production",
            "content_enabled": True,
            "content_slot_mode_enabled": True,
            "content_copy_provider_required": True,
            "ai_provider_mode": "zhipu",
            "brand_embedding_provider_mode": "zhipu",
            "ai_embedding_model": "embedding-3",
            "ai_embedding_dimensions": 2048,
            "ai_platform_base_url": "https://provider.example.test/api",
            "ai_platform_api_key": SecretStr(SECRET),
            "ai_max_attempts": 3,
        }
    )


def selection(*, live=False):
    s = settings()
    return canary.Selection(
        release=canary.RELEASE,
        run_id=RUN,
        selection_id=SELECTION,
        business_date=date(2026, 9, 5),
        slot="evening",
        ordinal=1,
        live=live,
        max_http_calls=3 if live else 0,
        expected_config=canary.config_fingerprint(s) if live else None,
        expected_copy_version=build_copy_version_bundle(s, scoring_profile="preview").fingerprint
        if live
        else None,
    )


def topic():
    return LockedTopicContext(
        origin=ContentSlotTopicOrigin(
            content_slot_selection_id=SELECTION,
            content_slot=ContentSlot.EVENING,
            ordinal=1,
            target_at=datetime(2026, 9, 5, 10, 30, tzinfo=UTC),
            expires_at=datetime(2026, 9, 5, 11, 30, tzinfo=UTC),
        ),
        business_date=date(2026, 9, 5),
        timezone="Asia/Shanghai",
        scoring_profile="preview",
        decision_kind="selected",
        selected_event_id=ID,
        selected_event_version_id=ID,
        no_topic_code=None,
        title="机器人研究进展",
        summary="研究团队发布机器人研究。",
        evidence=(
            EligibleEvidence(
                evidence_id=ID,
                candidate_id=ID,
                passage_id=ID,
                occurrence_id=ID,
                snapshot_id=ID,
                source_name="测试机构",
                source_url="https://example.test/article",
                source_tier="A",
                published_at=datetime(2026, 9, 5, tzinfo=UTC),
                exact_quote="研究团队发布了用于机器人学习的世界模型研究进展。",
            ),
        ),
    )


def brand():
    return ActiveBrandContext(
        chunk_id=ID,
        document_id=ID,
        version_id=ID,
        document_title="品牌测试资料",
        document_kind="positioning",
        text="赛先生重视科学精神、好奇心、思考力和创造力。",
    )


def cli_args():
    return [
        "--expected-release",
        canary.RELEASE,
        "--copy-run-id",
        str(RUN),
        "--selection-id",
        str(SELECTION),
        "--business-date",
        "2026-09-05",
        "--slot",
        "evening",
        "--ordinal",
        "1",
    ]


def test_cli_default_no_calls_and_explicit_exact_selectors():
    parsed = canary.parse_args(cli_args())
    assert parsed == selection()
    assert not parsed.live and parsed.max_http_calls == 0


@pytest.mark.parametrize(
    "change",
    [
        {"release": "0" * 40},
        {"slot": "latest"},
        {"ordinal": 0},
        {"ordinal": 4},
        {"max_http_calls": 1},
        {"live": True},
        {"expected_config": SECRET},
        {"expected_copy_version": "0" * 40},
    ],
)
def test_bad_selectors_fail_closed(change):
    with pytest.raises(canary.CanaryError):
        replace(selection(), **change).validate()


@pytest.mark.parametrize(
    "extra",
    [
        ["--live-no-send"],
        ["--max-http-calls", "3"],
        ["--api-key", SECRET],
        ["--copy-run-id", SECRET],
        ["--business-date", SECRET],
    ],
)
def test_cli_errors_never_echo_input(extra, capsys):
    with pytest.raises(canary.CanaryError):
        canary.parse_args(cli_args() + extra)
    assert SECRET not in capsys.readouterr().err


def test_source_bound_to_exact_deployed_release():
    canary.verify_source(Path(app.__file__).parent)


def test_source_rejects_missing_or_other_release(tmp_path):
    with pytest.raises(canary.CanaryError, match="source_mismatch"):
        canary.verify_source(tmp_path)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE jobs SET status='queued'",
        "DELETE FROM jobs",
        "INSERT INTO jobs VALUES(1)",
        "SET TRANSACTION READ WRITE",
        "SET default_transaction_read_only=off",
        "COMMIT",
        "CREATE TABLE jobs(id int)",
        "WITH modified AS (DELETE FROM jobs RETURNING *) SELECT * FROM modified",
        "/* comment */ DELETE FROM jobs",
    ],
)
def test_sql_write_guard(sql):
    with pytest.raises(canary.CanaryError, match="database_statement_denied"):
        canary.guard_statement(sql)


def test_engine_readonly_defaults_and_every_transaction(monkeypatch):
    events = {}
    captured = {}
    fake_engine = SimpleNamespace(sync_engine=object())

    def create(url, **kwargs):
        captured.update(kwargs)
        return fake_engine

    def listens(target, event_name):
        assert target is fake_engine.sync_engine

        def install(callback):
            events[event_name] = callback
            return callback

        return install

    monkeypatch.setattr(canary, "create_async_engine", create)
    monkeypatch.setattr(canary.event, "listens_for", listens)
    assert canary.readonly_engine(settings()) is fake_engine
    assert captured["connect_args"]["server_settings"]["default_transaction_read_only"] == "on"
    assert captured["connect_args"]["server_settings"]["statement_timeout"] == "10000"
    assert captured["poolclass"] is canary.NullPool
    assert captured["hide_parameters"] is True
    statements = []
    for _ in range(3):
        events["begin"](SimpleNamespace(exec_driver_sql=statements.append))
    assert statements == ["SET TRANSACTION READ ONLY"] * 3
    with pytest.raises(canary.CanaryError):
        events["before_cursor_execute"](
            None, None, "UPDATE jobs SET status='queued'", (), None, False
        )
    events["before_cursor_execute"](None, None, "SELECT 1", (), None, False)


@pytest.mark.asyncio
async def test_physical_http_stage_caps_and_total():
    calls = []
    s, chosen, report = settings(), selection(live=True), canary.Report()
    transport = canary.CappedTransport(
        httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200)), s, chosen, report
    )
    async with httpx.AsyncClient(transport=transport) as client:
        for stage in ("embedding", "generation", "audit"):
            report.stage = stage
            suffix = "embeddings" if stage == "embedding" else "chat/completions"
            model = s.ai_embedding_model if stage == "embedding" else s.ai_chat_model
            await client.post(f"{s.ai_platform_base_url}/{suffix}", json={"model": model})
            with pytest.raises(canary.CanaryError, match="http_call_cap_exceeded"):
                await client.post(f"{s.ai_platform_base_url}/{suffix}", json={"model": model})
    assert len(calls) == 3
    assert report.http_calls == {"embedding": 1, "generation": 1, "audit": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,model",
    [
        ("https://qyapi.weixin.qq.com/cgi-bin/webhook/send", "glm-5.2"),
        ("https://provider.example.test/api/images/generations", "glm-5.2"),
        ("https://provider.example.test/api/chat/completions", "another-model"),
    ],
)
async def test_transport_rejects_send_image_and_alternate_model(url, model):
    calls = []
    report = canary.Report(stage="generation")
    transport = canary.CappedTransport(
        httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200)),
        settings(),
        selection(live=True),
        report,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(canary.CanaryError):
            await client.post(url, json={"model": model})
    assert calls == [] and sum(report.http_calls.values()) == 0


@pytest.mark.asyncio
async def test_transport_dry_run_denies_even_valid_request():
    calls = []
    transport = canary.CappedTransport(
        httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200)),
        settings(),
        selection(),
        canary.Report(stage="embedding"),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(canary.CanaryError, match="live_calls_disabled"):
            await client.post(
                "https://provider.example.test/api/embeddings", json={"model": "embedding-3"}
            )
    assert calls == []


class Session:
    def __init__(self, rows, *, readonly=True, vector_count=57):
        self.rows, self.readonly, self.vector_count = rows, readonly, vector_count
        self.statements = []
        self.closed = False

    async def __aenter__(self):
        self.closed = False
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def scalar(self, statement):
        canary.guard_statement(str(statement))
        self.statements.append(str(statement))
        return (
            ("on" if self.readonly else "off")
            if str(statement).startswith("SHOW")
            else self.vector_count
        )

    async def get(self, model, row_id):
        return self.rows.get((model, row_id))


def db_session():
    s, t = settings(), topic()
    bundle = build_copy_version_bundle(s, scoring_profile="preview")
    run = CopyGenerationRunModel(
        id=RUN,
        content_slot_selection_id=SELECTION,
        business_date=t.business_date,
        timezone=t.timezone,
        scoring_profile=t.scoring_profile,
        decision_kind="selected",
        selected_event_id=ID,
        selected_event_version_id=ID,
        status="review_required",
        error_code="copy_provider_unavailable",
        active_draft_version_id=None,
        repair_count=0,
        version_bundle=bundle.as_metadata(),
        version_fingerprint=bundle.fingerprint,
    )
    selected = ContentSlotSelectionModel(
        id=SELECTION,
        run_id=ID,
        business_date=t.business_date,
        timezone=t.timezone,
        selected_event_id=ID,
        selected_event_version_id=ID,
        content_slot="evening",
        ordinal=1,
    )
    slot_run = ContentSlotRunModel(
        id=ID,
        scoring_profile=t.scoring_profile,
        status="succeeded",
        target_at=t.origin.target_at,
        expires_at=t.origin.expires_at,
    )
    version = EventClusterVersionModel(
        id=ID,
        event_id=ID,
        representative_title=t.title,
        summary_projection={"summary": t.summary},
    )
    return Session(
        {
            (CopyGenerationRunModel, RUN): run,
            (ContentSlotSelectionModel, SELECTION): selected,
            (ContentSlotRunModel, ID): slot_run,
            (EventClusterVersionModel, ID): version,
        }
    )


@pytest.mark.asyncio
async def test_read_only_loader_exact_existing_lineage(monkeypatch):
    session, report = db_session(), canary.Report()
    evidence = AsyncMock(return_value=topic().evidence)
    monkeypatch.setattr(canary, "load_governed_event_evidence", evidence)
    loaded, bundle = await canary.load_topic(lambda: session, selection(), settings(), report)
    assert loaded == topic() and report.evidence_count == 1
    assert report.active_brand_vector_count == 57 and session.closed
    assert report.copy_version_sha256 == bundle.fingerprint
    # SQL count includes both vector and active-version provider/model filtering.
    sql = session.statements[-1]
    for fragment in (
        "active_version_id",
        "brand_chunk_embeddings.provider",
        "embedding_model",
        "dimensions",
    ):
        assert fragment in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "missing",
        "wrong_selection",
        "wrong_date",
        "wrong_slot",
        "wrong_ordinal",
        "accepted",
        "active_draft",
        "wrong_failure",
        "wrong_version",
        "event_mismatch",
        "empty_evidence",
        "empty_brand",
        "not_readonly",
        "slot_not_succeeded",
    ],
)
async def test_read_only_loader_rejects_unhappy_paths(monkeypatch, scenario):
    session = db_session()
    run = session.rows[(CopyGenerationRunModel, RUN)]
    if scenario == "missing":
        session.rows.pop((CopyGenerationRunModel, RUN))
    elif scenario == "wrong_selection":
        run.content_slot_selection_id = ID
    elif scenario == "wrong_date":
        run.business_date = date(2026, 9, 4)
    elif scenario == "wrong_slot":
        session.rows[(ContentSlotSelectionModel, SELECTION)].content_slot = "morning"
    elif scenario == "wrong_ordinal":
        session.rows[(ContentSlotSelectionModel, SELECTION)].ordinal = 2
    elif scenario == "accepted":
        run.status = "accepted"
    elif scenario == "active_draft":
        run.active_draft_version_id = ID
    elif scenario == "wrong_failure":
        run.error_code = "provider_input_limit"
    elif scenario == "wrong_version":
        run.version_fingerprint = "f" * 64
    elif scenario == "event_mismatch":
        session.rows[(EventClusterVersionModel, ID)].event_id = RUN
    elif scenario == "empty_brand":
        session.vector_count = 0
    elif scenario == "not_readonly":
        session.readonly = False
    elif scenario == "slot_not_succeeded":
        session.rows[(ContentSlotRunModel, ID)].status = "running"
    evidence = AsyncMock(return_value=() if scenario == "empty_evidence" else topic().evidence)
    monkeypatch.setattr(canary, "load_governed_event_evidence", evidence)
    with pytest.raises((canary.CanaryError, RuntimeError)):
        await canary.load_topic(lambda: session, selection(), settings(), canary.Report())
    assert session.closed


async def exercise_fixture(monkeypatch, *, live, scenario="success", capture=False):
    s, chosen, report = (
        settings(),
        replace(selection(live=live), capture_provider_error_codes=capture),
        canary.Report(),
    )
    t, b = topic(), brand()
    bundle = build_copy_version_bundle(s, scoring_profile="preview")
    request = DraftGenerationRequest(RUN, t, (b,), bundle, 1, s.copy_max_output_tokens)
    generated = await DeterministicFakeMaterialDraftGenerator(model=s.ai_chat_model).generate(
        request
    )
    draft = generated.draft
    if scenario == "invalid_binding":
        draft = draft.model_copy(
            update={
                "claims": (
                    draft.claims[0].model_copy(update={"evidence_ids": (RUN,)}),
                    *draft.claims[1:],
                )
            }
        )
    calls = []

    async def handler(req):
        calls.append(req)
        if req.url.path.endswith("embeddings"):
            if scenario == "embedding_429":
                return httpx.Response(429, content=SECRET)
            if scenario == "embedding_500":
                return httpx.Response(500, content=SECRET)
            if scenario == "embedding_timeout":
                raise httpx.ReadTimeout(SECRET)
            return httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [1.0] + [0.0] * 2047}],
                    "model": "embedding-3",
                },
            )
        if report.stage == "generation":
            if scenario == "generation_400":
                return httpx.Response(400, json={"error": {"code": "1210", "message": SECRET}})
            if scenario == "generation_500":
                return httpx.Response(500, content=SECRET)
            content = SECRET if scenario == "invalid_json" else draft.model_dump_json()
        else:
            if scenario == "audit_invalid_json":
                return httpx.Response(200, json={"choices": [{"message": {"content": SECRET}}]})
            content = json.dumps(
                {
                    "accepted": scenario != "audit_rejected",
                    "issues": [
                        {
                            "code": "unbound_external_fact",
                            "message": "synthetic error",
                            "severity": "error",
                        }
                    ]
                    if scenario == "audit_rejected"
                    else [],
                }
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def load(*args):
        report.evidence_count, report.active_brand_vector_count = 1, 57
        return t, bundle

    async def retrieve(**kwargs):
        assert kwargs["query_provider"] == "zhipu" and kwargs["query_model"] == "embedding-3"
        if scenario == "no_brand_hit":
            return ()
        hit = SimpleNamespace(**asdict(b))
        if scenario == "oversized_brand_hit":
            hit.text = SECRET * 3000
        hit.document_kind = SimpleNamespace(value=b.document_kind)
        return (hit,)

    monkeypatch.setattr(canary, "load_topic", load)
    monkeypatch.setattr(
        canary,
        "PostgresBrandKnowledgeRepository",
        lambda factory: SimpleNamespace(retrieve=retrieve),
    )
    transport = canary.CappedTransport(httpx.MockTransport(handler), s, chosen, report)
    async with httpx.AsyncClient(transport=transport) as client:
        try:
            await canary.exercise(s, chosen, report, None, client)
        except canary.DryRunStop:
            report.outcome = "preflight_passed_live_unverified"
        except (canary.CanaryError, AppError) as error:
            report.outcome = "failed"
            report.error_code = str(error) if isinstance(error, canary.CanaryError) else error.code
    return report, calls


@pytest.mark.asyncio
async def test_full_dry_run_uses_factories_but_zero_http(monkeypatch):
    report, calls = await exercise_fixture(monkeypatch, live=False)
    assert not calls and report.outcome == "preflight_passed_live_unverified"
    assert report.embedding_query_characters > 0 and report.generator_prompt_min_characters > 0
    assert report.http_calls == {"embedding": 0, "generation": 0, "audit": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,counts",
    [
        ("success", (1, 1, 1)),
        ("invalid_binding", (1, 1, 0)),
        ("invalid_json", (1, 1, 0)),
        ("embedding_429", (1, 0, 0)),
        ("embedding_500", (1, 0, 0)),
        ("embedding_timeout", (1, 0, 0)),
        ("generation_500", (1, 1, 0)),
        ("audit_invalid_json", (1, 1, 1)),
        ("oversized_brand_hit", (1, 0, 0)),
        ("no_brand_hit", (1, 0, 0)),
        ("audit_rejected", (1, 1, 1)),
    ],
)
async def test_real_factories_schema_validation_policy_and_caps(monkeypatch, scenario, counts):
    report, calls = await exercise_fixture(monkeypatch, live=True, scenario=scenario)
    assert tuple(report.http_calls.values()) == counts and len(calls) == sum(counts)
    assert report.database_writes == report.packages_created == report.send_calls == 0
    assert not report.delivery_verified
    assert SECRET not in json.dumps(asdict(report))
    if scenario == "success":
        assert report.deterministic_error_count == 0 and report.audit_accepted is True
        assert report.outcome in {"first_draft_passed", "repair_needed_not_attempted"}
    elif scenario == "invalid_binding":
        assert report.outcome == "deterministic_validation_failed"
        assert report.deterministic_error_count > 0
    elif scenario in {"embedding_429", "embedding_500", "embedding_timeout"}:
        assert report.error_code == "http_call_cap_exceeded"
        if scenario == "embedding_timeout":
            assert report.transport_errors == {"embedding": "provider_timeout"}
        else:
            assert report.http_status_codes == {"embedding": int(scenario.split("_")[1])}
    elif scenario in {"invalid_json", "audit_invalid_json"}:
        assert report.error_code == "invalid_provider_output"
    elif scenario == "generation_500":
        assert report.error_code == "provider_unavailable"
    elif scenario == "oversized_brand_hit":
        assert report.error_code == "provider_input_limit"
    elif scenario == "audit_rejected":
        assert report.outcome == "audit_rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(SECRET),
        canary.CanaryError(SECRET),
        AppError(SECRET, SECRET),
    ],
)
async def test_top_level_error_redaction(monkeypatch, error):
    def fail(*args):
        raise error

    monkeypatch.setattr(canary, "verify_source", fail)
    report = await canary.run(selection())
    assert report.outcome == "failed" and SECRET not in json.dumps(asdict(report))
    assert report.error_code in {"diagnostic_internal_error", "provider_failure"}


def test_settings_identity_and_no_credentials_in_fingerprint():
    s, report = settings(), canary.Report()
    canary.validate_settings(s, selection(live=True), report)
    assert SECRET not in json.dumps(asdict(report))
    changed = s.model_copy(update={"ai_chat_model": "different-model"})
    with pytest.raises(canary.CanaryError, match="config_mismatch"):
        canary.validate_settings(changed, selection(live=True), canary.Report())


def test_issue_projection_is_allowlisted_and_never_echoes_provider_fields():
    issues = (
        CopyIssue(code="unbound_external_fact", message=SECRET, severity="error", field=SECRET),
        CopyIssue(code=SECRET, message=SECRET, severity="error", claim_id=SECRET),
        CopyIssue(code=SECRET, message=SECRET, severity="warning"),
    )
    counts = canary.safe_issue_counts(issues)
    assert counts == {"unbound_external_fact": 1, "other_issue": 2}
    assert SECRET not in json.dumps(counts)


@pytest.mark.asyncio
async def test_preflight_input_floor_stops_before_embedding(monkeypatch):
    s = settings().model_copy(update={"ai_max_input_characters": 1000})
    t, report = topic(), canary.Report()
    bundle = build_copy_version_bundle(s, scoring_profile="preview")
    monkeypatch.setattr(canary, "load_topic", AsyncMock(return_value=(t, bundle)))
    calls = []
    transport = canary.CappedTransport(
        httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200)),
        s,
        selection(live=True),
        report,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(canary.CanaryError, match="provider_input_limit"):
            await canary.exercise(s, selection(live=True), report, None, client)
    assert report.generator_prompt_min_characters > 1000 and not calls


@pytest.mark.asyncio
async def test_live_identity_drift_stops_before_db_or_http(monkeypatch):
    s = settings().model_copy(update={"ai_chat_model": "changed-model"})
    monkeypatch.setattr(canary, "verify_source", lambda root: None)
    monkeypatch.setattr(canary, "Settings", lambda: s)

    def forbidden(*args):
        pytest.fail("database must not be constructed after config drift")

    monkeypatch.setattr(canary, "readonly_engine", forbidden)
    report = await canary.run(selection(live=True))
    assert report.error_code == "config_mismatch" and sum(report.http_calls.values()) == 0


def test_construction_has_no_executor_package_checkpoint_or_send_entrypoint():
    # Complements exercised transports/readonly connections; not a substitute for them.
    import ast

    tree = ast.parse(SCRIPT.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        any(word in item for word in ("material_package", "wecom", "checkpoint"))
        for item in imports
    )
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "CopyGenerationExecutor" not in calls


def test_error_observation_flag_is_explicit_and_legacy_defaults_unchanged():
    assert not canary.parse_args(cli_args()).capture_provider_error_codes
    assert canary.parse_args(
        [*cli_args(), "--capture-provider-error-codes"]
    ).capture_provider_error_codes


@pytest.mark.asyncio
async def test_error_observation_schema_identifies_new_invocation(monkeypatch):
    def stop(root):
        raise canary.CanaryError("source_mismatch")

    monkeypatch.setattr(canary, "verify_source", stop)
    legacy = await canary.run(selection())
    captured = await canary.run(replace(selection(), capture_provider_error_codes=True))
    assert legacy.schema == "production-recovery-no-send-v1" and legacy.mode == "dry_run"
    assert captured.schema == "production-recovery-no-send-v2-error-observation"
    assert captured.mode == "dry_run_error_codes" and captured.capture_provider_error_codes
    assert sum(captured.http_calls.values()) == 0


def test_observation_allowlist_matches_independently_reviewed_probe():
    import ast

    tree = ast.parse(SCRIPT.with_name("zhipu-chat-parameter-probe.py").read_text())
    statement = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "OFFICIAL_ERROR_CODES"
            for target in node.targets
        )
    )
    assert canary.OFFICIAL_ERROR_CODES == frozenset(ast.literal_eval(statement.value.args[0]))
    for code in canary.OFFICIAL_ERROR_CODES:
        for value in (code, int(code)):
            assert (
                canary.official_error_code(
                    json.dumps({"error": {"code": value, "message": SECRET}}).encode()
                )
                == code
            )


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"error": {"code": SECRET, "message": SECRET}}).encode(),
        json.dumps({"error": {"code": True, "message": SECRET}}).encode(),
        json.dumps({"error": {"code": {"private": SECRET}}}).encode(),
        b'{"error":{"code":"1210","code":"1234"}}',
        b'{"error":{"code":NaN}}',
        b"not-json",
        b'{"code":"1210"}',
    ],
)
def test_observation_business_code_redaction(body):
    assert canary.official_error_code(body) == "other_code"


@pytest.mark.asyncio
async def test_observation_default_zero_and_identical_request_payloads(monkeypatch):
    dry, dry_calls = await exercise_fixture(monkeypatch, live=False, capture=True)
    assert not dry_calls and dry.outcome == "preflight_passed_live_unverified"
    original, original_calls = await exercise_fixture(
        monkeypatch, live=True, scenario="generation_400"
    )
    observed, observed_calls = await exercise_fixture(
        monkeypatch, live=True, scenario="generation_400", capture=True
    )
    assert original.provider_business_error_codes == {}
    assert observed.provider_business_error_codes == {"generation": "1210"}
    assert (
        original.http_calls == observed.http_calls == {"embedding": 1, "generation": 1, "audit": 0}
    )
    assert [req.content for req in original_calls] == [req.content for req in observed_calls]
    assert observed.error_code == original.error_code == "provider_request_rejected"
    assert observed.database_writes == observed.packages_created == observed.send_calls == 0
    assert SECRET not in json.dumps(asdict(observed))


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,counts", [("success", (1, 1, 1)), ("embedding_429", (1, 0, 0))])
async def test_observation_cannot_increase_physical_budgets(monkeypatch, scenario, counts):
    report, calls = await exercise_fixture(monkeypatch, live=True, scenario=scenario, capture=True)
    assert tuple(report.http_calls.values()) == counts and len(calls) == sum(counts)
    if scenario == "embedding_429":
        assert report.provider_business_error_codes == {"embedding": "other_code"}
        assert report.error_code == "http_call_cap_exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("capture,status", [(False, 400), (True, 200), (True, 400)])
async def test_observation_reads_body_only_for_flagged_errors(capture, status):
    class Body(httpx.AsyncByteStream):
        reads = 0
        closed = False

        async def __aiter__(self):
            self.reads += 1
            yield json.dumps({"error": {"code": "1214", "message": SECRET}}).encode()

        async def aclose(self):
            self.closed = True

    body, report, s = Body(), canary.Report(stage="generation"), settings()

    def handler(req):
        return httpx.Response(status, stream=body)

    chosen = replace(selection(live=True), capture_provider_error_codes=capture)
    transport = canary.CappedTransport(httpx.MockTransport(handler), s, chosen, report)
    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream(
            "POST", f"{s.ai_platform_base_url}/chat/completions", json={"model": s.ai_chat_model}
        ):
            pass
    assert body.closed and body.reads == int(capture and status == 400)
    assert report.provider_business_error_codes == (
        {"generation": "1214"} if capture and status == 400 else {}
    )
    assert report.http_calls == {"embedding": 0, "generation": 1, "audit": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["chunked_large", "declared_large", "gzip_expansion", "gzip_truncated", "gzip_valid"]
)
async def test_observation_stream_bounds_gzip_and_closure(kind):
    normal = json.dumps({"error": {"code": "1210", "message": SECRET}}).encode()
    raw = gzip.compress(normal) if kind.startswith("gzip") else SECRET.encode() * 2000
    if kind == "gzip_expansion":
        raw = gzip.compress(SECRET.encode() * 2000)
    elif kind == "gzip_truncated":
        raw = raw[:-5]

    class Body(httpx.AsyncByteStream):
        closed = False
        yielded_bytes = 0

        async def __aiter__(self):
            for offset in range(0, len(raw), 4096):
                chunk = raw[offset : offset + 4096]
                self.yielded_bytes += len(chunk)
                yield chunk

        async def aclose(self):
            self.closed = True

    body, report, s = Body(), canary.Report(stage="generation"), settings()

    def handler(req):
        headers = {"content-encoding": "gzip"} if kind.startswith("gzip") else {}
        if kind == "declared_large":
            headers["content-length"] = "999999999"
        return httpx.Response(400, stream=body, headers=headers)

    chosen = replace(selection(live=True), capture_provider_error_codes=True)
    transport = canary.CappedTransport(httpx.MockTransport(handler), s, chosen, report)
    async with httpx.AsyncClient(transport=transport) as client:
        if kind == "gzip_valid":
            response = await client.post(
                f"{s.ai_platform_base_url}/chat/completions", json={"model": s.ai_chat_model}
            )
            assert response.content == b"" and response.status_code == 400
            assert report.provider_business_error_codes == {"generation": "1210"}
        else:
            with pytest.raises(AppError):
                await client.post(
                    f"{s.ai_platform_base_url}/chat/completions", json={"model": s.ai_chat_model}
                )
            assert report.provider_business_error_codes == {}
    assert body.closed and body.yielded_bytes <= canary.MAX_ERROR_RESPONSE_BYTES + 4096
    assert report.http_calls == {"embedding": 0, "generation": 1, "audit": 0}
    assert SECRET not in json.dumps(asdict(report))
