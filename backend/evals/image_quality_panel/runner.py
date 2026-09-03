"""Provider-free preflight and fail-closed live boundary for image evaluation evidence."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from evals.model_panel import (
    MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    PanelAuthorization,
    PanelManifest,
    SecureEvidenceStore,
    validate_authorization_binding,
)

from .dataset import build_image_panel_dataset
from .models import ALL_MODEL_SPECS
from .planning import CALLS_PER_MODEL, TOTAL_CALL_CEILING
from .sources import REPOSITORY_ROOT, load_source_catalog, preflight_sources


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preflight")
    live = subcommands.add_parser("live")
    live.add_argument("--manifest", type=Path, required=True)
    live.add_argument("--authorization", type=Path, required=True)
    live.add_argument("--manifest-sha256", required=True)
    live.add_argument("--authorization-sha256", required=True)
    live.add_argument("--acknowledgement", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            return _preflight()
        return _live_boundary(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"image panel failed: {exc}", file=sys.stderr)
        return 1


def _preflight() -> int:
    catalog = load_source_catalog()
    preflight_sources(catalog)
    with tempfile.TemporaryDirectory(prefix="image-panel-preflight-") as raw:
        artifact_directory = Path(raw)
        artifact_directory.chmod(0o700)
        dataset = build_image_panel_dataset(artifact_directory=artifact_directory)
    if TOTAL_CALL_CEILING != 48 * 2 + 12 * 2:
        raise ValueError("120-call budget equation drifted")
    print(
        "image panel preflight passed: "
        f"cases={dataset.case_n}; source_clusters={dataset.effective_source_cluster_n}; "
        f"models={len(ALL_MODEL_SPECS)}; calls_per_model={CALLS_PER_MODEL}; "
        f"call_ceiling={TOTAL_CALL_CEILING}; live_calls=0"
    )
    return 0


def _live_boundary(args: argparse.Namespace) -> int:
    if args.acknowledgement != MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT:
        raise ValueError("explicit model-panel authorization acknowledgement required")
    store = SecureEvidenceStore(repository_root=REPOSITORY_ROOT)
    manifest = store.load_json_model(args.manifest, PanelManifest)
    authorization = store.load_json_model(args.authorization, PanelAuthorization)
    manifest_hash, _ = store.file_sha256(args.manifest)
    authorization_hash, _ = store.file_sha256(args.authorization)
    if manifest_hash != args.manifest_sha256 or authorization_hash != args.authorization_sha256:
        raise ValueError("CLI hashes do not bind the exact manifest and authorization files")
    validate_authorization_binding(manifest, authorization, now=datetime.now(UTC))
    expected_refs = {spec.model_ref for spec in ALL_MODEL_SPECS}
    counts = Counter(item.evaluator_model_ref for item in manifest.attempt_bindings)
    if (
        manifest.track != "image-quality-single-model-eval"
        or manifest.total_request_limit != TOTAL_CALL_CEILING
        or set(counts) != expected_refs
        or set(counts.values()) != {CALLS_PER_MODEL}
    ):
        raise ValueError("manifest is not the complete approved 120-call image plan")
    print(
        "image panel live execution refused: inject the explicit GLM-5V-Turbo transport through "
        "execute_image_plan; this provider-free CLI never reads credentials or chooses endpoints",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
