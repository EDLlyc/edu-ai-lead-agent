"""Provider-free regression checks of exact-incident recovery mutation boundaries."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "weekly_recovery", Path(__file__).with_name("weekly_recovery.py")
)
assert _SPEC is not None and _SPEC.loader is not None
operator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(operator)
NEW_RUN = UUID("f799d979-23e1-46f0-8ced-1e0d9fbf2eae")


def observation() -> dict:
    return {
        "input_fingerprint": operator.INPUT,
        "bindings": [
            {"article_request_fingerprint": str(index) * 64} for index in range(3)
        ],
        "sibling_child_fingerprints": ["1" * 64, "2" * 64],
        "protected": {"original_root": {"sha256": "4" * 64}},
    }


class Owner:
    def __init__(self, fail_at: str = "") -> None:
        self.built = []
        self.aggregates = 0
        self.fail_at = fail_at

    async def build_child(self, *, run_id, role):
        self.built.append(run_id)
        if self.fail_at == "child":
            raise ValueError("private article body must not escape")
        return SimpleNamespace(fingerprint=str(role.ordinal) * 64)

    def validate_child(self, artifact, *, role):
        return SimpleNamespace(
            article_fingerprint=artifact.fingerprint,
            content_fingerprint=artifact.fingerprint,
        )

    def aggregate(self, *, week_start, children):
        assert week_start == operator.WEEK
        assert len(children) == 3
        self.aggregates += 1
        if self.fail_at == "aggregate":
            raise ValueError("private file path must not escape")
        return SimpleNamespace(fingerprint="7" * 64)

    def validate_batch(self, artifact):
        if self.fail_at == "validate_batch":
            raise ValueError("private batch must not escape")
        return SimpleNamespace(
            batch_fingerprint="8" * 64, aggregate_fingerprint=artifact.fingerprint
        )


class FakeRuntime:
    def __init__(self, root: Path, *, fail_at: str = "") -> None:
        self.root = root
        self.state = observation()
        self.owner = Owner(fail_at)
        self.enqueue_calls = 0
        self.fail_at = fail_at
        self.reads = 0

    async def observe(self, extra_run=None, *, permit_handoff=False):
        self.reads += 1
        if self.fail_at == "after_intent" and self.reads == 2:
            raise operator.RecoveryError("original_run_changed")
        if self.fail_at == "preaggregate" and self.reads == 4:
            raise operator.RecoveryError("draft_rows_already_exist")
        if self.fail_at == "postaggregate" and permit_handoff:
            raise operator.RecoveryError("original_root_changed")
        if extra_run is not None:
            assert extra_run == NEW_RUN
        return copy.deepcopy(self.state)

    async def enqueue(self, binding):
        assert binding == self.state["bindings"][2]
        self.enqueue_calls += 1
        if self.fail_at == "enqueue":
            raise ValueError("private source snapshot must not escape")
        return SimpleNamespace(id=NEW_RUN), self.fail_at != "already_enqueued"

    async def wait_ready(self, run_id):
        assert run_id == NEW_RUN
        if self.fail_at in {"timeout", "terminal"}:
            raise operator.RecoveryError(
                "replacement_article_wait_timeout"
                if self.fail_at == "timeout"
                else "replacement_article_terminal"
            )

    def prepared_owner(self):
        return self.owner


def run(runtime: FakeRuntime, plan=None):
    plan = plan or operator.seal(observation())
    return asyncio.run(operator.execute(runtime, plan, plan["plan_sha256"]))


def records(root: Path) -> list:
    path = root / f"{operator.POLICY}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_readonly_plan_has_no_files_or_enqueue(tmp_path):
    runtime = FakeRuntime(tmp_path)
    plan = operator.seal(asyncio.run(runtime.observe()))
    operator.verify_plan(plan, plan["plan_sha256"])
    assert list(tmp_path.iterdir()) == []
    assert runtime.enqueue_calls == runtime.owner.aggregates == 0


@pytest.mark.parametrize(
    "field", ["policy", "original_run_id", "week_start", "observation"]
)
def test_plan_tampering_refused_before_any_write(tmp_path, field):
    runtime = FakeRuntime(tmp_path)
    plan = operator.seal(observation())
    plan[field] = "changed"
    with pytest.raises(operator.RecoveryError):
        run(runtime, plan)
    assert not list(tmp_path.iterdir())
    assert runtime.enqueue_calls == 0


@pytest.mark.parametrize(
    "field",
    ["input_fingerprint", "bindings", "sibling_child_fingerprints", "protected"],
)
def test_source_or_successful_identity_drift_refused(tmp_path, field):
    runtime = FakeRuntime(tmp_path)
    runtime.state[field] = "changed"
    with pytest.raises(operator.RecoveryError, match="plan_state_drift"):
        run(runtime)
    assert not list(tmp_path.iterdir())
    assert runtime.enqueue_calls == 0


def test_success_reuses_two_siblings_and_one_enqueue_then_rejects_repeat(tmp_path):
    runtime = FakeRuntime(tmp_path)
    result = run(runtime)
    assert runtime.enqueue_calls == 1
    assert runtime.owner.built == [pair[1] for pair in operator.SIBLINGS] + [NEW_RUN]
    assert runtime.owner.aggregates == 1
    assert result["original_dag_status"] == "terminal_failed"
    assert result["recovery_status"] == "inbox_ready"
    assert result["draft_delivery_status"] == "not_observed"
    assert result["published"] is False
    audit_before = (tmp_path / f"{operator.POLICY}.jsonl").read_bytes()
    with pytest.raises(operator.RecoveryError, match="recovery_intent_already_exists"):
        run(runtime)
    assert runtime.enqueue_calls == runtime.owner.aggregates == 1
    assert (tmp_path / f"{operator.POLICY}.jsonl").read_bytes() == audit_before


@pytest.mark.parametrize(
    "fail_at,enqueues,aggregates",
    [
        ("after_intent", 0, 0),
        ("enqueue", 1, 0),
        ("already_enqueued", 1, 0),
        ("timeout", 1, 0),
        ("terminal", 1, 0),
        ("child", 1, 0),
        ("preaggregate", 1, 0),
        ("aggregate", 1, 1),
        ("validate_batch", 1, 1),
        ("postaggregate", 1, 1),
    ],
)
def test_failure_retains_append_only_intent_and_never_replays(
    tmp_path, fail_at, enqueues, aggregates
):
    runtime = FakeRuntime(tmp_path, fail_at=fail_at)
    with pytest.raises(operator.RecoveryError) as failure:
        run(runtime)
    assert "private" not in str(failure.value)
    assert runtime.enqueue_calls == enqueues
    assert runtime.owner.aggregates == aggregates
    audit = records(tmp_path)
    assert audit[0]["phase"] == "intent"
    assert audit[-1]["phase"] == "failure"
    assert audit[-1]["retry_allowed"] is False
    with pytest.raises(operator.RecoveryError, match="recovery_intent_already_exists"):
        run(runtime)
    assert runtime.enqueue_calls == enqueues
    assert runtime.owner.aggregates == aggregates
    assert "private" not in json.dumps(audit)


def test_audit_has_integrity_chain_and_private_mode(tmp_path):
    runtime = FakeRuntime(tmp_path)
    run(runtime)
    previous = "0" * 64
    for index, record in enumerate(records(tmp_path)):
        checksum = record.pop("record_sha256")
        assert operator.digest(record) == checksum
        assert record["previous_sha256"] == previous
        assert record["sequence"] == index
        previous = checksum
    assert (tmp_path / f"{operator.POLICY}.jsonl").stat().st_mode & 0o777 == 0o600


def test_existing_or_symlink_audit_refuses_no_clobber(tmp_path):
    path = tmp_path / f"{operator.POLICY}.jsonl"
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(operator.RecoveryError, match="recovery_intent_already_exists"):
        operator.Audit(tmp_path, operator.seal(observation()))
    assert path.is_symlink()


def test_readonly_session_sets_transaction_before_queries_and_rolls_back():
    session = AsyncMock()
    session.expunge_all = Mock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    runtime = object.__new__(operator.Runtime)
    runtime.factory = lambda: context

    async def read():
        async with runtime.readonly():
            pass

    asyncio.run(read())
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET LOCAL statement_timeout = '10s'",
    ]
    session.rollback.assert_awaited_once()
    session.expunge_all.assert_called_once()
    session.commit.assert_not_awaited()


def test_runtime_allows_first_missing_inbox_without_creating_it(tmp_path, monkeypatch):
    root = tmp_path / "weekly"
    root.mkdir()
    inbox = tmp_path / "inbox"
    settings = SimpleNamespace(
        app_env="production",
        official_account_weekly_production_enabled=True,
        official_account_weekly_worker_enabled=True,
        official_account_local_enabled=True,
        official_account_local_worker_enabled=True,
        ai_provider_mode="zhipu",
        ai_chat_model="glm-5.2",
        official_account_weekly_artifact_root=str(root),
        wechat_mp_draft_weekly_inbox_root=str(inbox),
    )
    monkeypatch.setattr(
        operator, "official_account_identity_from_settings", lambda *a, **k: object()
    )
    runtime = operator.Runtime(settings, object())
    assert runtime.inbox == inbox
    assert not inbox.exists()
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "kind", ["symlink", "ancestor_symlink", "missing_parent", "file"]
)
def test_inbox_requires_physical_existing_parent(tmp_path, kind):
    path = tmp_path / "inbox"
    if kind == "symlink":
        path.symlink_to(tmp_path / "absent")
    elif kind == "ancestor_symlink":
        path.symlink_to(tmp_path, target_is_directory=True)
        path = path / "absent"
    elif kind == "missing_parent":
        path = path / "absent"
    else:
        path.write_text("not a directory")
    with pytest.raises(operator.RecoveryError):
        operator.physical_directory(path, allow_missing_leaf=True)


@pytest.mark.parametrize("drift", [False, True])
def test_current_runtime_locks_and_checks_source_before_exact_enqueue(
    monkeypatch, drift
):
    runtime = object.__new__(operator.Runtime)
    runtime.identity = object()
    runtime.repository = SimpleNamespace(enqueue_material_package=AsyncMock())
    session = AsyncMock()
    session.scalar.side_effect = [SimpleNamespace(image_artifact_id=NEW_RUN), object()]
    context = AsyncMock()
    context.__aenter__.return_value = session
    runtime.factory = lambda: context
    monkeypatch.setattr(
        operator,
        "material_package_source_snapshot",
        lambda package, image: SimpleNamespace(source_fingerprint="a" * 64),
    )
    monkeypatch.setattr(operator, "run_request_fingerprint", lambda **kwargs: "b" * 64)
    binding = {
        "material_package_id": str(operator.REPLACEMENT),
        "source_fingerprint": ("c" if drift else "a") * 64,
        "article_request_fingerprint": "b" * 64,
    }
    if drift:
        with pytest.raises(operator.RecoveryError, match="enqueue_source_changed"):
            asyncio.run(runtime.enqueue(binding))
        runtime.repository.enqueue_material_package.assert_not_awaited()
    else:
        asyncio.run(runtime.enqueue(binding))
        runtime.repository.enqueue_material_package.assert_awaited_once_with(
            material_package_id=operator.REPLACEMENT, identity=runtime.identity
        )
    assert all(
        call.args[0]._for_update_arg.read for call in session.scalar.call_args_list
    )
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.fixture
def observed_runtime(tmp_path, monkeypatch):
    """Run the real observation checks, with only IO and planner results substituted."""
    from app.domain.official_account_weekly_dag import WEEKLY_DAG_NODES

    @dataclass
    class Identity:
        provider: str = "zhipu"
        model: str = "glm-5.2"
        context_media_plan_version: str | None = None

    runtime = object.__new__(operator.Runtime)
    runtime.identity = Identity()
    runtime.root = tmp_path
    runtime.inbox = tmp_path
    runtime.prepared_owner = lambda: Owner()
    packages = [pair[0] for pair in operator.SIBLINGS] + [operator.REPLACEMENT]
    items = []
    for index, (role, package_id) in enumerate(
        zip(operator.WeeklyArticleRole, packages, strict=True)
    ):
        payload = {"material_package_id": str(package_id), "role": role.value}
        items.append(
            SimpleNamespace(
                material_package_id=package_id,
                event_id=operator.EVENT if index == 2 else package_id,
                event_version_id=operator.EVENT_VERSION if index == 2 else package_id,
                role=role,
                as_dict=lambda payload=payload: payload,
            )
        )
    original = {
        "week_start": operator.WEEK.isoformat(),
        "cutoff": operator.CUTOFF.isoformat(),
        "items": [item.as_dict().copy() for item in items],
    }
    original["items"][2]["material_package_id"] = str(operator.FAILED)
    planned = SimpleNamespace(items=items, fingerprint="9" * 64)
    monkeypatch.setattr(
        operator,
        "FullPreflightPlanner",
        lambda factory: SimpleNamespace(plan=AsyncMock(return_value=planned)),
    )
    nodes = []
    for definition in WEEKLY_DAG_NODES:
        node = SimpleNamespace(
            node_key=definition.key,
            status="pending",
            lease_owner=None,
            lease_expires_at=None,
            output_media_type=None,
            output_artifact_fingerprint="0" * 64,
        )
        if definition.role in tuple(operator.WeeklyArticleRole)[:2]:
            node.status = "succeeded"
            node.output_artifact_fingerprint = str(definition.role.ordinal) * 64
            if definition.key.endswith(":render_handoff"):
                node.output_media_type = (
                    "application/vnd.wechat.prepared-draft-child+directory"
                )
                node.output_artifact_ref = (
                    f"wechat-prepared-child-v1:{node.output_artifact_fingerprint}"
                )
                node.output_byte_size = 10
        if definition.key == "application_case:build_article":
            node.status = "terminal_failed"
            node.attempt_count = node.max_attempts = 3
        nodes.append(node)

    def checkpoint(fingerprint):
        if fingerprint == operator.INPUT:
            return original
        index = int(fingerprint[0]) - 1
        return {"official_account_run_id": str(operator.SIBLINGS[index][1])}

    runtime.checkpoints = SimpleNamespace(get_json_by_fingerprint=checkpoint)
    root = SimpleNamespace(status="failed", completed_at=operator.CUTOFF)
    run_row = SimpleNamespace(
        input_fingerprint=operator.INPUT,
        week_start=operator.WEEK,
        status="terminal_failed",
        aggregate_artifact_ref=None,
    )
    article_rows = []

    def source(package, image):
        return SimpleNamespace(source_fingerprint=operator.digest(str(package.id)))

    monkeypatch.setattr(operator, "material_package_source_snapshot", source)
    for package_id, article_id in operator.SIBLINGS:
        fingerprint = operator.digest(str(package_id))
        article_rows.append(
            SimpleNamespace(
                id=article_id,
                material_package_id=package_id,
                status="ready",
                generation_mode="live",
                version_bundle=operator.identity_payload(runtime.identity),
                source_fingerprint=fingerprint,
                request_fingerprint=operator.run_request_fingerprint(
                    source_fingerprint=fingerprint,
                    generation_mode="live",
                    identity=runtime.identity,
                ),
            )
        )
    session = AsyncMock()

    async def get(model, key):
        if model is operator.models.OfficialAccountWeeklyDagRunModel:
            return run_row
        if model is operator.models.ExecutionGovernedRunModel:
            return root
        if model is operator.models.MaterialPackageModel:
            return SimpleNamespace(id=key, image_artifact_id=key)
        return SimpleNamespace(id=key)

    session.get.side_effect = get
    session.expunge_all = Mock()
    session.scalars.side_effect = lambda statement: (
        nodes if "official_account_weekly_dag_nodes" in str(statement) else article_rows
    )
    session.scalar.return_value = None
    context = AsyncMock()
    context.__aenter__.return_value = session
    runtime.factory = lambda: context
    runtime._rows = AsyncMock(return_value=[])
    return SimpleNamespace(
        runtime=runtime,
        session=session,
        root=root,
        run=run_row,
        nodes=nodes,
        articles=article_rows,
        original=original,
        planned=planned,
    )


def test_real_observer_reads_and_validates_without_mutation(observed_runtime):
    case = observed_runtime
    result = asyncio.run(case.runtime.observe())
    assert result["bindings"][2]["material_package_id"] == str(operator.REPLACEMENT)
    assert result["sibling_article_ids"] == [str(pair[1]) for pair in operator.SIBLINGS]
    case.session.commit.assert_not_awaited()
    assert all(
        str(call.args[0]).startswith("SET ")
        for call in case.session.execute.call_args_list
    )


def test_real_observer_accepts_missing_first_inbox_without_mkdir(observed_runtime):
    case = observed_runtime
    case.runtime.inbox = case.runtime.root / "new-inbox"
    asyncio.run(case.runtime.observe())
    assert not case.runtime.inbox.exists()
    case.session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "changed,code",
    [
        ("root", "original_root_changed"),
        ("run", "original_run_changed"),
        ("sibling", "successful_article_changed"),
        ("sibling_source", "successful_article_source_changed"),
        ("node", "original_nodes_active"),
        ("draft", "draft_rows_already_exist"),
        ("queued_article", "article_population_changed"),
        ("input", "original_input_changed"),
        ("replacement", "replacement_selection_changed"),
    ],
)
def test_real_observer_rejects_wrong_original_siblings_queue_and_draft(
    observed_runtime, changed, code
):
    case = observed_runtime
    if changed == "root":
        case.root.status = "running"
    elif changed == "run":
        case.run.input_fingerprint = "0" * 64
    elif changed == "sibling":
        case.articles[0].status = "review_required"
    elif changed == "sibling_source":
        case.articles[0].source_fingerprint = "0" * 64
    elif changed == "node":
        case.nodes[0].lease_owner = "other-worker"
    elif changed == "draft":
        case.session.scalar.return_value = object()
    elif changed == "queued_article":
        case.articles.append(SimpleNamespace(id=NEW_RUN, status="queued"))
    elif changed == "input":
        case.original["cutoff"] = "2026-09-07T03:00:00+00:00"
    elif changed == "replacement":
        case.planned.items[2].material_package_id = operator.FAILED
    with pytest.raises(operator.RecoveryError, match=code):
        asyncio.run(case.runtime.observe())
    case.session.commit.assert_not_awaited()
