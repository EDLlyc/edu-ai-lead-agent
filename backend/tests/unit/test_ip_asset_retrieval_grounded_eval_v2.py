from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import pytest
from evals.ip_asset_retrieval_grounded.authoring import (
    build_v2_query_records,
    build_v2_review_ledger,
    build_v2_robustness_pairs,
    build_v2_seed_records,
)
from evals.ip_asset_retrieval_grounded.comparison_v2 import compare_runs_v2
from evals.ip_asset_retrieval_grounded.dataset import (
    DEFAULT_ASSETS_PATH,
    DEFAULT_QUERIES_PATH,
    DEFAULT_SEED_PATH,
    DEFAULT_V2_QUERIES_PATH,
    EXPECTED_V1_ASSETS_SHA256,
    EXPECTED_V1_QUERIES_SHA256,
    EXPECTED_V1_SEED_SHA256,
    GroundedDatasetBundleV2,
    GroundedDatasetError,
    load_grounded_bundle_v2,
)
from evals.ip_asset_retrieval_grounded.manifest import (
    build_safe_manifest,
    load_safe_manifest,
    validate_safe_manifest_artifacts,
)
from evals.ip_asset_retrieval_grounded.models import (
    GroundedChallengeKind,
    GroundedDecisionEvidence,
    GroundedQueryObservationV2,
    GroundedRetrievalRunV2,
)
from evals.ip_asset_retrieval_grounded.reporting import (
    build_seed_v2_report,
    canonical_json,
    render_comparison_v2_markdown,
    render_seed_v2_markdown,
    render_selective_markdown,
)
from evals.ip_asset_retrieval_grounded.runner import main as runner_main
from evals.ip_asset_retrieval_grounded.selective import build_selective_report

FEATURE_ROOT = Path(__file__).resolve().parents[2] / "evals/ip_asset_retrieval_grounded"
PAIRED_PROHIBITED_KEYS = {
    "cookie",
    "filename",
    "grade",
    "ip",
    "label",
    "object_key",
    "path",
    "profile_id",
    "profile_token",
    "prompt",
    "provider_body",
    "provider_request_id",
    "query",
    "rank",
    "score",
    "session_id",
    "similarity",
    "user_agent",
    "user_id",
    "vector",
}


def test_seed_v1_identity_is_immutable_while_seed_v2_is_complete() -> None:
    assert _sha256(DEFAULT_ASSETS_PATH) == EXPECTED_V1_ASSETS_SHA256
    assert _sha256(DEFAULT_QUERIES_PATH) == EXPECTED_V1_QUERIES_SHA256
    assert _sha256(DEFAULT_SEED_PATH) == EXPECTED_V1_SEED_SHA256

    bundle = load_grounded_bundle_v2()

    assert len(bundle.assets.assets) == 41
    assert len(bundle.queries) == 124
    assert sum(query.split == "dev" for query in bundle.queries) == 98
    assert sum(query.split == "holdout" for query in bundle.queries) == 26
    assert sum(query.expected_answer_kind == "no_answer" for query in bundle.queries) == 30
    assert sum(len(matrix.grades) for matrix in bundle.seed) == 5_084
    assert {matrix.label_source for matrix in bundle.seed} == {"codex_seed_v2"}
    assert len(bundle.review.changes) == 14
    assert bundle.review.reviewed_scopes == (
        "v1_no_answer_queries",
        "v1_combined_constraint_queries",
        "v1_grade_1_2_boundaries",
        "fixed_space_station_query",
    )
    assert bundle.review.independent_human_review is False
    assert bundle.review.rank_or_score_observations_opened is False
    assert len(bundle.robustness_pairs) == 24
    assert {
        query.challenge_kind for query in bundle.queries if query.challenge_kind is not None
    } == set(GroundedChallengeKind)


def test_seed_v2_authoring_and_canonical_report_are_stable() -> None:
    bundle = load_grounded_bundle_v2()
    report = build_seed_v2_report(bundle)

    assert build_v2_query_records() == bundle.queries
    assert build_v2_seed_records() == bundle.seed
    assert build_v2_review_ledger() == bundle.review
    assert build_v2_robustness_pairs() == bundle.robustness_pairs
    assert report["truthfulness"] == {
        "human_gold": False,
        "human_agreement_available": False,
        "independent_review_available": False,
        "live_retrieval_measured": False,
    }
    assert (FEATURE_ROOT / "canonical-seed-v2-report.json").read_text(
        encoding="utf-8"
    ) == canonical_json(report)
    assert (FEATURE_ROOT / "canonical-seed-v2-report.md").read_text(
        encoding="utf-8"
    ) == render_seed_v2_markdown(report)


def test_seed_v2_loader_fails_closed_when_a_v1_query_changes(tmp_path: Path) -> None:
    records = DEFAULT_V2_QUERIES_PATH.read_text(encoding="utf-8").splitlines()
    first = json.loads(records[0])
    first["query"] = "被污染的查询"
    records[0] = json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    queries = tmp_path / "queries.v2.jsonl"
    queries.write_text("\n".join(records) + "\n", encoding="utf-8")

    with pytest.raises(GroundedDatasetError, match="changed a Seed V1 query"):
        load_grounded_bundle_v2(queries_path=queries)


def test_seed_v2_loader_rejects_coordinated_seed_v1_identity_drift(tmp_path: Path) -> None:
    source_records = DEFAULT_QUERIES_PATH.read_text(encoding="utf-8").splitlines()
    source_first = json.loads(source_records[0])
    source_first["query"] = "被协同篡改的 V1 查询"
    source_records[0] = json.dumps(
        source_first, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    source_queries = tmp_path / "queries.v1.jsonl"
    source_queries.write_text("\n".join(source_records) + "\n", encoding="utf-8")

    v2_records = DEFAULT_V2_QUERIES_PATH.read_text(encoding="utf-8").splitlines()
    v2_first = json.loads(v2_records[0])
    assert v2_first["query_ref"] == source_first["query_ref"]
    v2_first["query"] = source_first["query"]
    v2_records[0] = json.dumps(v2_first, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    v2_queries = tmp_path / "queries.v2.jsonl"
    v2_queries.write_text("\n".join(v2_records) + "\n", encoding="utf-8")

    with pytest.raises(GroundedDatasetError, match="Seed V1 identity drifted"):
        load_grounded_bundle_v2(
            queries_path=v2_queries,
            source_v1_queries_path=source_queries,
        )


def test_selective_policy_uses_dev_only_and_reports_holdout_once() -> None:
    bundle = load_grounded_bundle_v2()
    report = build_selective_report(
        bundle,
        _run(bundle),
        bootstrap_samples=1_000,
        bootstrap_seed=7,
    )

    assert report["selection"]["split"] == "dev"
    assert report["selection"]["selected_policy"]["policy_ref"] != ("selective-v1-baseline")
    assert report["truthfulness"]["holdout_used_for_policy_selection"] is False
    assert report["truthfulness"]["production_threshold_activated"] is False
    assert report["baseline"]["dev"]["aggregate"]["no_answer_false_positive_rate"] == 1.0
    assert report["candidate"]["dev"]["aggregate"]["no_answer_false_positive_rate"] == 0.0
    assert report["candidate"]["dev"]["aggregate"]["answerable_false_abstention_rate"] == 0.0
    assert report["candidate"]["holdout"]["aggregate"]["no_answer_false_positive_rate"] == 0.0
    assert report["candidate"]["dev"]["robustness"]["consistency_rate"] == 1.0
    assert {
        "unconditional_macro_recall_at_3",
        "unconditional_macro_recall_at_5",
        "unconditional_macro_mrr_at_5",
        "unconditional_macro_ndcg_at_5",
        "retained_macro_recall_at_3",
        "retained_macro_recall_at_5",
        "retained_macro_mrr_at_5",
        "retained_macro_ndcg_at_5",
    }.issubset(report["dev_curve"][0])
    assert {
        "execution_coverage",
        "selective_risk",
        "no_answer_false_positive_rate",
        "answerable_false_abstention_rate",
        "unconditional_macro_recall_at_5",
    }.issubset(report["candidate"]["dev"]["categories"]["no_answer"])
    assert report["paired_bootstrap"]["holdout"]["decision_utility"]["query_count"] == 26
    assert report["paired_bootstrap"]["dev"]["no_answer_correct_abstention"]["query_count"] == 22
    assert report["paired_bootstrap"]["holdout"]["answerable_answer_rate"]["query_count"] == 18
    assert "not human Gold" in render_selective_markdown(report)


def test_selective_policy_selection_is_invariant_to_holdout_evidence() -> None:
    bundle = load_grounded_bundle_v2()
    run = _run(bundle)
    original = build_selective_report(bundle, run, bootstrap_samples=1_000, bootstrap_seed=7)
    split_by_ref = {query.query_ref: query.split for query in bundle.queries}
    mutated = run.model_copy(
        update={
            "observations": tuple(
                observation.model_copy(
                    update={
                        "selected_catalog_refs": (),
                        "decision_evidence": GroundedDecisionEvidence(
                            top_semantic_similarity=None,
                            semantic_margin=None,
                            metadata_match_score=None,
                            metadata_match_count=0,
                            evidence_lane_count=0,
                        ),
                    }
                )
                if split_by_ref[observation.query_ref] == "holdout"
                else observation
                for observation in run.observations
            )
        }
    )
    changed = build_selective_report(bundle, mutated, bootstrap_samples=1_000, bootstrap_seed=7)

    assert changed["selection"] == original["selection"]
    assert changed["dev_curve"] == original["dev_curve"]
    assert changed["candidate"]["dev"] == original["candidate"]["dev"]
    assert changed["candidate"]["holdout"] != original["candidate"]["holdout"]


def test_safe_manifest_hashes_artifacts_and_rejects_prohibited_fields(tmp_path: Path) -> None:
    bundle = load_grounded_bundle_v2()
    run = _run(bundle)
    report = build_selective_report(bundle, run, bootstrap_samples=1_000, bootstrap_seed=7)
    run_path = tmp_path / "run.json"
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    run_path.write_text(canonical_json(run.model_dump(mode="json")), encoding="utf-8")
    report_path.write_text(canonical_json(report), encoding="utf-8")
    manifest = build_safe_manifest(
        run=run,
        run_path=run_path,
        report=report,
        report_path=report_path,
        git_sha="a" * 40,
    )
    manifest_path.write_text(canonical_json(manifest.model_dump(mode="json")), encoding="utf-8")

    loaded = load_safe_manifest(manifest_path)
    assert "contamination_not_independently_audited" in loaded.validity_notes
    assert "corpus_drift_requires_new_asset_set_fingerprint" in loaded.validity_notes
    validate_safe_manifest_artifacts(
        loaded,
        run=run,
        run_path=run_path,
        report=report,
        report_path=report_path,
    )
    serialized = json.loads(manifest_path.read_text(encoding="utf-8"))
    serialized["query_dataset_sha256"] = "b" * 64
    manifest_path.write_text(canonical_json(serialized), encoding="utf-8")
    identity_drifted = load_safe_manifest(manifest_path)
    with pytest.raises(ValueError, match="identity or artifact hash drifted"):
        validate_safe_manifest_artifacts(
            identity_drifted,
            run=run,
            run_path=run_path,
            report=report,
            report_path=report_path,
        )

    manifest_path.write_text(canonical_json(manifest.model_dump(mode="json")), encoding="utf-8")
    serialized = json.loads(manifest_path.read_text(encoding="utf-8"))
    serialized["query"] = "secret"
    manifest_path.write_text(canonical_json(serialized), encoding="utf-8")
    with pytest.raises(ValueError, match="prohibited fields"):
        load_safe_manifest(manifest_path)

    unsafe_report = {**report, "query": "secret"}
    report_path.write_text(canonical_json(unsafe_report), encoding="utf-8")
    with pytest.raises(ValueError, match="prohibited fields"):
        build_safe_manifest(
            run=run,
            run_path=run_path,
            report=unsafe_report,
            report_path=report_path,
            git_sha="a" * 40,
        )


def test_seed_v2_real_run_pairing_reports_slices_and_reproducible_intervals() -> None:
    bundle = load_grounded_bundle_v2()
    baseline = _run(
        bundle,
        search_version="ip-asset-hybrid-v2",
        reverse=True,
        execution_mode="alibaba",
        run_ref="igr_11111111111111111111",
    )
    candidate = _run(
        bundle,
        search_version="ip-asset-hybrid-v3-rrf",
        execution_mode="alibaba",
        run_ref="igr_22222222222222222222",
    )

    first = compare_runs_v2(bundle, baseline, candidate, bootstrap_samples=1_000, bootstrap_seed=7)
    second = compare_runs_v2(bundle, baseline, candidate, bootstrap_samples=1_000, bootstrap_seed=7)

    assert first == second
    assert first["schema_version"] == "ip-asset-grounded-comparison-v2"
    assert first["truthfulness"] == {
        "human_gold": False,
        "human_agreement_available": False,
        "online_user_effectiveness": False,
        "production_threshold_activated": False,
        "live_retrieval_measured": True,
        "real_embedding_provider_used": True,
        "same_embedding_bytes_proven": False,
    }
    assert first["baseline"]["overall"]["aggregate"]["query_count"] == 124
    assert first["baseline"]["overall"]["aggregate"]["answerable_query_count"] == 94
    assert first["baseline"]["overall"]["aggregate"]["no_answer_query_count"] == 30
    assert first["paired_bootstrap"]["overall"]["mrr_at_5"]["query_count"] == 94
    assert first["paired_bootstrap"]["dev"]["mrr_at_5"]["query_count"] == 76
    assert first["paired_bootstrap"]["holdout"]["mrr_at_5"]["query_count"] == 18
    assert first["paired_bootstrap"]["overall"]["mrr_at_5"]["delta"] > 0
    assert first["paired_outcomes"]["overall"]["mrr_at_5"]["wins"] > 0
    assert set(first["baseline"]["overall"]["categories"]) == {
        query.category.value for query in bundle.queries
    }
    assert set(first["baseline"]["overall"]["challenge_kinds"]) == {
        query.challenge_kind.value for query in bundle.queries if query.challenge_kind is not None
    }
    assert first["diagnostics"]["baseline"]["overall"] == {
        "query_count": 124,
        "successful_query_count": 124,
        "execution_coverage": 1.0,
        "modes": {"semantic": 124},
        "degraded_reasons": {},
        "failure_codes": {},
    }
    markdown = render_comparison_v2_markdown(first)
    assert "248" in markdown
    assert "30 no-answer" in markdown
    assert "not human Gold" in markdown
    assert "小赛和赛先生在空间站" not in markdown
    assert "小赛和赛先生在空间站" not in canonical_json(first)
    assert not (_collect_keys(first) & PAIRED_PROHIBITED_KEYS)


def test_seed_v2_pairing_rejects_version_provider_and_identity_drift() -> None:
    bundle = load_grounded_bundle_v2()
    baseline = _run(
        bundle,
        search_version="ip-asset-hybrid-v2",
        execution_mode="alibaba",
        run_ref="igr_11111111111111111111",
    )
    candidate = _run(
        bundle,
        search_version="ip-asset-hybrid-v3-rrf",
        execution_mode="alibaba",
        run_ref="igr_22222222222222222222",
    )

    with pytest.raises(ValueError, match="baseline must use"):
        compare_runs_v2(
            bundle,
            baseline.model_copy(update={"search_version": "ip-asset-hybrid-v3-rrf"}),
            candidate,
            bootstrap_samples=1_000,
        )
    with pytest.raises(ValueError, match="candidate must use"):
        compare_runs_v2(
            bundle,
            baseline,
            candidate.model_copy(update={"search_version": "ip-asset-hybrid-v2"}),
            bootstrap_samples=1_000,
        )
    with pytest.raises(ValueError, match="requires real Alibaba"):
        compare_runs_v2(
            bundle,
            baseline.model_copy(
                update={"embedding_execution_mode": "fake", "provider_request_count": 0}
            ),
            candidate,
            bootstrap_samples=1_000,
        )
    with pytest.raises(ValueError, match="one embedding identity"):
        compare_runs_v2(
            bundle,
            baseline,
            candidate.model_copy(update={"embedding_model": "different-model"}),
            bootstrap_samples=1_000,
        )
    with pytest.raises(ValueError, match="distinct run refs"):
        compare_runs_v2(
            bundle,
            baseline,
            candidate.model_copy(update={"run_ref": baseline.run_ref}),
            bootstrap_samples=1_000,
        )
    with pytest.raises(ValueError, match="complete provider request counts"):
        compare_runs_v2(
            bundle,
            baseline,
            candidate.model_copy(update={"provider_request_count": 123}),
            bootstrap_samples=1_000,
        )
    with pytest.raises(ValueError, match="does not cover the query set"):
        compare_runs_v2(
            bundle,
            baseline,
            candidate.model_copy(update={"observations": candidate.observations[:-1]}),
            bootstrap_samples=1_000,
        )


def test_seed_v2_pairing_cli_writes_safe_local_reports(tmp_path: Path) -> None:
    bundle = load_grounded_bundle_v2()
    baseline = _run(
        bundle,
        search_version="ip-asset-hybrid-v2",
        execution_mode="alibaba",
        run_ref="igr_11111111111111111111",
    )
    candidate = _run(
        bundle,
        search_version="ip-asset-hybrid-v3-rrf",
        execution_mode="alibaba",
        run_ref="igr_22222222222222222222",
    )
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    output_json = tmp_path / "comparison.json"
    output_markdown = tmp_path / "comparison.md"
    baseline_path.write_text(canonical_json(baseline.model_dump(mode="json")), encoding="utf-8")
    candidate_path.write_text(canonical_json(candidate.model_dump(mode="json")), encoding="utf-8")

    result = runner_main(
        [
            "compare-runs-v2",
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
            "--bootstrap-samples",
            "1000",
            "--bootstrap-seed",
            "7",
        ]
    )

    assert result == 0
    assert json.loads(output_json.read_text(encoding="utf-8"))["schema_version"] == (
        "ip-asset-grounded-comparison-v2"
    )
    assert output_markdown.read_text(encoding="utf-8").startswith(
        "# IP asset grounded retrieval Seed V2 paired comparison"
    )


def _run(
    bundle: GroundedDatasetBundleV2,
    *,
    search_version: str = "ip-asset-hybrid-v3-rrf",
    reverse: bool = False,
    execution_mode: Literal["fake", "alibaba"] = "fake",
    run_ref: str = "igr_0123456789abcdef0123",
) -> GroundedRetrievalRunV2:
    grades_by_query = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in bundle.seed
    }
    fallback = bundle.assets.assets[0].catalog_ref
    observations = []
    for query in bundle.queries:
        grades = grades_by_query[query.query_ref]
        selected: tuple[str, ...]
        if query.expected_answer_kind == "no_answer":
            selected = (fallback,)
            evidence = GroundedDecisionEvidence(
                top_semantic_similarity=0.25,
                semantic_margin=0.01,
                metadata_match_score=0.0,
                metadata_match_count=0,
                evidence_lane_count=1,
            )
        else:
            selected = tuple(
                sorted(grades, key=lambda ref: (grades[ref], ref), reverse=not reverse)[:8]
            )
            evidence = GroundedDecisionEvidence(
                top_semantic_similarity=0.85,
                semantic_margin=0.10,
                metadata_match_score=0.50,
                metadata_match_count=2,
                evidence_lane_count=2,
            )
        observations.append(
            GroundedQueryObservationV2(
                query_ref=query.query_ref,
                mode="semantic",
                degraded_reason=None,
                selected_catalog_refs=selected,
                decision_evidence=evidence,
                failure_code=None,
            )
        )
    return GroundedRetrievalRunV2(
        schema_version="ip-asset-grounded-run-v2",
        run_ref=run_ref,
        created_at="2026-09-02T00:00:00+00:00",
        maturity="seed",
        search_version=search_version,
        embedding_execution_mode=execution_mode,
        embedding_provider="alibaba-model-studio",
        embedding_model="qwen3-vl-embedding",
        embedding_dimensions=2_048,
        embedding_input_policy_version="brand-visual-embedding-input-v2",
        asset_set_fingerprint=bundle.assets.asset_set_fingerprint,
        query_dataset_sha256=bundle.queries_sha256,
        seed_dataset_sha256=bundle.seed_sha256,
        robustness_dataset_sha256=bundle.robustness_sha256,
        review_ledger_sha256=bundle.review_sha256,
        duration_ms=1_000,
        provider_request_count=124 if execution_mode == "alibaba" else 0,
        input_token_count=None,
        estimated_cost_usd=None,
        observations=tuple(observations),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        result = {str(key).casefold() for key in value}
        for child in value.values():
            result.update(_collect_keys(child))
        return result
    if isinstance(value, (list, tuple)):
        result: set[str] = set()
        for child in value:
            result.update(_collect_keys(child))
        return result
    return set()
