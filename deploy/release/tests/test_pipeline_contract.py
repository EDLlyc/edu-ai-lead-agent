from __future__ import annotations

from pathlib import Path

import yaml
from contract import BUNDLE_ALLOWED_PREFIXES

from deploy import APPLICATION_SERVICES


def test_flow_pipeline_is_inactive_and_branch_scoped() -> None:
    pipeline = Path("deploy/yunxiao/pipeline.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(pipeline)
    source = parsed["sources"]["source"]
    assert source["type"] == "codeup"
    assert source["certificate"] == {
        "type": "serviceConnection",
        "serviceConnection": "w4de9kbiwbdh3ncn",
    }
    assert all(
        variable["key"] != "CODEUP_SERVICE_CONNECTION_ID"
        for variable in parsed["variables"]
    )
    assert pipeline.count("w4de9kbiwbdh3ncn") == 1
    assert "934667" not in pipeline
    assert "ACR_PUBLISH_ENABLED\n    type: Boolean\n    value: false" in pipeline
    assert "GITHUB_BACKUP_ENABLED\n    type: Boolean\n    value: false" in pipeline
    assert "PRODUCTION_DEPLOY_ENABLED\n    type: Boolean\n    value: false" in pipeline
    assert pipeline.count('"${CI_COMMIT_REF_NAME}" == "main"') == 3
    assert "make PY_RUN= release-tool-check" in pipeline
    assert "needs: quality_job" in pipeline
    assert "needs: image_job" in pipeline
    assert pipeline.count("needs: acr_publish_job") == 2
    assert "needs: quality_stage.quality_job" not in pipeline
    assert "needs: image_stage.image_job" not in pipeline
    assert "needs: publish_stage.acr_publish_job" not in pipeline
    assert "serviceConnection: 79934" in pipeline
    assert "ADMIN_REQUIRED_CODEUP_SERVICE_CONNECTION_ID" not in pipeline
    assert pipeline.count("docker build --pull \\") == 2
    assert pipeline.count("import app.api_main") == 2
    assert "--provenance" not in pipeline
    deploy_job = pipeline.split("production_deploy_job:", 1)[1]
    assert "tar --extract" not in deploy_job
    assert "artifact_path_rejected" in deploy_job
    assert 'test "${#manifests[@]}" -eq 1' in deploy_job
    assert (
        "github"
        not in pipeline.split("sources:", 1)[1].split("defaultWorkspace:", 1)[0].lower()
    )
    assert "--no-build" not in deploy_job
    assert "/usr/local/sbin/edu-ai-deploy" in pipeline


def test_flow_display_names_fit_documented_limits() -> None:
    pipeline = yaml.safe_load(
        Path("deploy/yunxiao/pipeline.yaml").read_text(encoding="utf-8")
    )
    assert len(pipeline["name"]) <= 60
    for source in pipeline["sources"].values():
        assert len(source["name"]) <= 30
    for stage in pipeline["stages"].values():
        assert len(stage["name"]) <= 30
        for job in stage["jobs"].values():
            assert len(job["name"]) <= 30
            for step in job.get("steps", {}).values():
                assert len(step["name"]) <= 30


def test_compose_uses_one_application_image_variable() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert "image: ${APP_IMAGE:-edu-ai-lead-agent-backend:local}" in compose
    assert compose.count("<<: *app-runtime") == 9


def test_frontend_is_a_ci_gate_only() -> None:
    pipeline = Path("deploy/yunxiao/pipeline.yaml").read_text(encoding="utf-8")
    image_job = pipeline.split("image_stage:", 1)[1].split("publish_stage:", 1)[0]
    publish_job = pipeline.split("publish_stage:", 1)[1].split("backup_stage:", 1)[0]
    deploy_job = pipeline.split("deploy_stage:", 1)[1]
    assert image_job.count("docker build --pull \\") == 1
    assert publish_job.count("docker build --pull \\") == 1
    assert '--tag "$image" backend' in image_job
    assert '--tag "$tag" backend' in publish_job
    assert publish_job.lower().count("frontend") == 1
    assert '--gate "frontend=$gate_id"' in publish_job
    assert "frontend" not in deploy_job.lower()
    assert all(not path.startswith("frontend") for path in BUNDLE_ALLOWED_PREFIXES)
    assert len(APPLICATION_SERVICES) == 9
    assert all("frontend" not in service for service in APPLICATION_SERVICES)


def test_external_side_effect_flags_default_closed() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    for setting in (
        "AI_PROVIDER_MODE: ${AI_PROVIDER_MODE:-disabled}",
        "GOVERNANCE_ENABLED: ${GOVERNANCE_ENABLED:-false}",
        "CONTENT_ENABLED: ${CONTENT_ENABLED:-false}",
        "CONTENT_SCHEDULER_ENABLED: ${CONTENT_SCHEDULER_ENABLED:-false}",
        "CONTENT_WORKER_ENABLED: ${CONTENT_WORKER_ENABLED:-false}",
        "IMAGE_ENABLED: ${IMAGE_ENABLED:-false}",
        "WECOM_ENABLED: ${WECOM_ENABLED:-false}",
        "WECOM_AUTO_DELIVERY_ENABLED: ${WECOM_AUTO_DELIVERY_ENABLED:-false}",
    ):
        assert setting in compose
