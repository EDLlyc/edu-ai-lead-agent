"""Private evidence writes and redacted non-activating image-panel reports."""

from __future__ import annotations

from pathlib import Path

from evals.model_panel import SecureEvidenceStore
from evals.model_panel.privacy import PrivacyProfile

from .metrics import ImagePanelReport, NonActivatingCandidateArtifact


def write_safe_reports(
    *,
    store: SecureEvidenceStore,
    run_directory: Path,
    report: ImagePanelReport,
    candidate_artifact: NonActivatingCandidateArtifact,
) -> tuple[Path, Path]:
    """Write immutable 0600 JSON artifacts after the shared safe-report privacy scan."""

    report_path = run_directory / "image-single-model-report.json"
    candidate_path = run_directory / "image-model-observation.non-activating.json"
    store.write_json_exclusive(
        report_path,
        report,
        privacy_profile=PrivacyProfile.SAFE_REPORT,
    )
    store.write_json_exclusive(
        candidate_path,
        candidate_artifact,
        privacy_profile=PrivacyProfile.SAFE_REPORT,
    )
    return report_path, candidate_path
