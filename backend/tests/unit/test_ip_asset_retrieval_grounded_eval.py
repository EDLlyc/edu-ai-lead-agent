from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.domain.visual_assets import VisualAssetError
from evals.ip_asset_retrieval_grounded.assets import (
    assert_safe_snapshot_current,
)
from evals.ip_asset_retrieval_grounded.authoring import (
    assert_frozen_v1_artifacts,
    build_query_records,
    build_seed_records,
)
from evals.ip_asset_retrieval_grounded.authoring import (
    main as authoring_main,
)
from evals.ip_asset_retrieval_grounded.dataset import (
    DEFAULT_ASSETS_PATH,
    DEFAULT_QUERIES_PATH,
    DEFAULT_SEED_PATH,
    GroundedDatasetBundle,
    GroundedDatasetError,
    load_grounded_bundle,
)
from evals.ip_asset_retrieval_grounded.metrics import (
    aggregate_scores,
    compare_runs,
    paired_bootstrap_interval,
    score_run,
)
from evals.ip_asset_retrieval_grounded.models import (
    GroundedQueryCategory,
    GroundedQueryObservation,
    GroundedRetrievalRun,
)
from evals.ip_asset_retrieval_grounded.reporting import (
    build_run_report,
    build_seed_report,
    canonical_json,
    render_run_markdown,
    render_seed_markdown,
)

FEATURE_ROOT = Path(__file__).resolve().parents[2] / "evals/ip_asset_retrieval_grounded"


def test_frozen_v1_authoring_check_does_not_require_private_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_manifest = tmp_path / "private-manifest-does-not-exist.json"

    assert authoring_main(["--check-frozen-v1", "--manifest", str(missing_manifest)]) == 0
    assert not missing_manifest.exists()
    assert "frozen Seed V1 artifacts match" in capsys.readouterr().out


def test_full_v1_authoring_check_still_requires_private_manifest(tmp_path: Path) -> None:
    missing_manifest = tmp_path / "private-manifest-does-not-exist.json"

    with pytest.raises(VisualAssetError, match="visual asset manifest is unavailable"):
        authoring_main(["--check", "--manifest", str(missing_manifest)])


@pytest.mark.parametrize(
    "drifted_name",
    ["assets.v1.json", "queries.v1.jsonl", "codex-seed.v1.jsonl"],
)
def test_frozen_v1_authoring_check_fails_closed_on_artifact_drift(
    tmp_path: Path, drifted_name: str
) -> None:
    paths = {
        "assets.v1.json": tmp_path / "assets.v1.json",
        "queries.v1.jsonl": tmp_path / "queries.v1.jsonl",
        "codex-seed.v1.jsonl": tmp_path / "codex-seed.v1.jsonl",
    }
    sources = {
        "assets.v1.json": DEFAULT_ASSETS_PATH,
        "queries.v1.jsonl": DEFAULT_QUERIES_PATH,
        "codex-seed.v1.jsonl": DEFAULT_SEED_PATH,
    }
    for name, path in paths.items():
        path.write_bytes(sources[name].read_bytes())
    assert_frozen_v1_artifacts(
        assets_path=paths["assets.v1.json"],
        queries_path=paths["queries.v1.jsonl"],
        seed_path=paths["codex-seed.v1.jsonl"],
    )

    paths[drifted_name].write_bytes(paths[drifted_name].read_bytes() + b" ")

    with pytest.raises(ValueError, match=drifted_name):
        assert_frozen_v1_artifacts(
            assets_path=paths["assets.v1.json"],
            queries_path=paths["queries.v1.jsonl"],
            seed_path=paths["codex-seed.v1.jsonl"],
        )


def test_grounded_seed_covers_real_corpus_queries_and_complete_matrix() -> None:
    bundle = load_grounded_bundle()

    assert len(bundle.assets.assets) == 41
    assert len(bundle.queries) == 100
    assert sum(query.split == "dev" for query in bundle.queries) == 80
    assert sum(query.split == "holdout" for query in bundle.queries) == 20
    assert {query.category for query in bundle.queries} == set(GroundedQueryCategory)
    assert "小赛和赛先生在空间站" in {query.query for query in bundle.queries}
    assert sum(len(matrix.grades) for matrix in bundle.seed) == 4_100
    assert {matrix.label_source for matrix in bundle.seed} == {"codex_seed"}
    assert build_query_records() == bundle.queries
    assert build_seed_records() == bundle.seed


def test_grounded_seed_canonical_report_is_review_only_and_stable() -> None:
    report = build_seed_report(load_grounded_bundle())

    assert report["truthfulness"] == {
        "human_gold": False,
        "human_agreement_available": False,
        "live_retrieval_measured": False,
    }
    assert (FEATURE_ROOT / "canonical-seed-report.json").read_text(
        encoding="utf-8"
    ) == canonical_json(report)
    assert (FEATURE_ROOT / "canonical-seed-report.md").read_text(
        encoding="utf-8"
    ) == render_seed_markdown(report)


def test_grounded_loader_rejects_prohibited_fields(tmp_path: Path) -> None:
    query = json.loads(DEFAULT_QUERIES_PATH.read_text(encoding="utf-8").splitlines()[0])
    query["filename"] = "private.png"
    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(json.dumps(query, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(GroundedDatasetError, match="prohibited fields"):
        load_grounded_bundle(
            assets_path=DEFAULT_ASSETS_PATH,
            queries_path=queries_path,
            seed_path=DEFAULT_SEED_PATH,
        )


def test_grounded_snapshot_fails_closed_on_identity_drift(tmp_path: Path) -> None:
    bundle = load_grounded_bundle()
    drifted = bundle.assets.model_copy(update={"asset_set_fingerprint": "f" * 64})

    with pytest.raises(ValueError, match="snapshot drifted"):
        assert_safe_snapshot_current(
            drifted,
            manifest_path=tmp_path / "private-manifest-does-not-exist.json",
        )


def test_grounded_snapshot_current_check_still_rebuilds_private_manifest(
    tmp_path: Path,
) -> None:
    bundle = load_grounded_bundle()

    with pytest.raises(VisualAssetError, match="visual asset manifest is unavailable"):
        assert_safe_snapshot_current(
            bundle.assets,
            manifest_path=tmp_path / "private-manifest-does-not-exist.json",
        )


def test_grounded_metrics_keep_no_answer_out_of_ranking_macro() -> None:
    bundle = load_grounded_bundle()
    run = _run(bundle, search_version="ip-asset-hybrid-v2", reverse=False)

    aggregate = aggregate_scores(score_run(bundle, run))["overall"]

    assert aggregate["answerable_query_count"] == 94
    assert aggregate["no_answer_query_count"] == 6
    assert aggregate["correct_abstention_rate"] == 1.0
    assert aggregate["false_positive_rate"] == 0.0
    assert aggregate["macro_mrr_at_5"] == 1.0


def test_grounded_pairing_is_reproducible_and_requires_one_embedding_identity() -> None:
    bundle = load_grounded_bundle()
    baseline = _run(bundle, search_version="ip-asset-hybrid-v2", reverse=True)
    candidate = _run(bundle, search_version="ip-asset-hybrid-v3-rrf", reverse=False)

    first = compare_runs(bundle, baseline, candidate, bootstrap_samples=1_000)
    second = compare_runs(bundle, baseline, candidate, bootstrap_samples=1_000)

    assert first == second
    assert first["paired_bootstrap"]["metrics"]["mrr_at_5"]["delta"] > 0
    changed_identity = candidate.model_copy(update={"embedding_execution_mode": "alibaba"})
    with pytest.raises(ValueError, match="one embedding identity"):
        compare_runs(bundle, baseline, changed_identity, bootstrap_samples=1_000)


def test_grounded_bootstrap_rejects_small_sample_budget() -> None:
    with pytest.raises(ValueError, match="at least 1,000"):
        paired_bootstrap_interval(((0.0, 1.0),), samples=999, seed=1)


def test_grounded_live_report_discloses_fake_execution() -> None:
    bundle = load_grounded_bundle()
    report = build_run_report(
        bundle,
        _run(bundle, search_version="ip-asset-hybrid-v3-rrf", reverse=False),
    )

    assert report["truthfulness"]["human_gold"] is False
    assert report["truthfulness"]["real_embedding_provider_used"] is False
    markdown = render_run_markdown(report)
    assert "`fake`" in markdown
    assert "not human Gold" in markdown


def _run(
    bundle: GroundedDatasetBundle, *, search_version: str, reverse: bool
) -> GroundedRetrievalRun:
    grades_by_query = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in bundle.seed
    }
    observations = []
    for query in bundle.queries:
        grades = grades_by_query[query.query_ref]
        if query.expected_answer_kind == "no_answer":
            selected: tuple[str, ...] = ()
        else:
            ordered = sorted(
                grades,
                key=lambda ref: (grades[ref], ref),
                reverse=not reverse,
            )
            selected = tuple(ordered[:8])
        observations.append(
            GroundedQueryObservation(
                query_ref=query.query_ref,
                mode="semantic",
                degraded_reason=None,
                selected_catalog_refs=selected,
                failure_code=None,
            )
        )
    return GroundedRetrievalRun(
        schema_version="ip-asset-grounded-run-v1",
        run_ref="igr_0123456789abcdef0123",
        created_at="2026-09-02T00:00:00+00:00",
        maturity="seed",
        search_version=search_version,
        embedding_execution_mode="fake",
        embedding_provider="alibaba-model-studio",
        embedding_model="qwen3-vl-embedding",
        embedding_dimensions=2048,
        embedding_input_policy_version="brand-visual-embedding-input-v2",
        asset_set_fingerprint=bundle.assets.asset_set_fingerprint,
        query_dataset_sha256=bundle.queries_sha256,
        seed_dataset_sha256=bundle.seed_sha256,
        observations=tuple(observations),
    )
