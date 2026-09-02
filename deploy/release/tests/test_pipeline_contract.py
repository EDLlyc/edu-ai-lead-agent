from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml
from contract import (
    BUNDLE_ALLOWED_PREFIXES,
    alembic_head_from_blobs,
    load_compatibility_declaration,
)

from deploy import APPLICATION_SERVICES

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_MASK_PATHS = (
    ".env",
    ".env.local",
    "backend/.env",
    "frontend/.env",
    "frontend/.env.local",
    "frontend/.env.development",
    "frontend/.env.development.local",
    "frontend/.env.production",
    "frontend/.env.production.local",
    "frontend/.env.test",
    "frontend/.env.test.local",
)
FLOW_CI_RUNS_ON = {
    "group": "public/cn-beijing",
    "container": (
        "build-steps-public-registry.cn-beijing.cr.aliyuncs.com/"
        "build-steps/alinux3@sha256:"
        "876efc938a207d8d1d0bc1c3305a1d849995ea34a769ef28715f8414dbae7bf1"
    ),
}


def test_flow_pipeline_is_inactive_and_branch_scoped() -> None:
    pipeline = Path("deploy/yunxiao/pipeline.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(pipeline)
    source = parsed["sources"]["source"]
    assert source["type"] == "codeup"
    assert source["endpoint"] == (
        "https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/"
        "edu-ai-lead-agent.git"
    )
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
    assert 'make PY_RUN="$PWD/scripts/ci-python.sh" release-tool-check' in pipeline
    assert "needs:" not in pipeline
    acr_login = parsed["stages"]["publish_stage"]["jobs"]["acr_publish_job"]["steps"][
        "acr_login"
    ]
    assert acr_login["with"]["serviceConnection"] == "c8jknt8rkk1w7tc1"
    assert "79934" not in pipeline
    assert "ADMIN_REQUIRED_CODEUP_SERVICE_CONNECTION_ID" not in pipeline
    assert pipeline.count("docker build --pull \\") == 2
    assert "python3 -c" not in pipeline
    assert ".ci-venv" not in pipeline
    assert "--file backend/Dockerfile.ci" in pipeline
    assert (
        "node:20.20.2-bookworm-slim@sha256:"
        "2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0" in pipeline
    )
    assert pipeline.count("import app.api_main") == 2
    assert "--provenance" not in pipeline
    deploy_job = pipeline.split("production_deploy_job:", 1)[1]
    deploy_config = parsed["stages"]["deploy_stage"]["jobs"]["production_deploy_job"]
    assert deploy_config["component"] == "VMDeploy"
    assert "steps" not in deploy_config
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


def test_ci_jobs_use_pinned_specified_container_and_probe_docker() -> None:
    pipeline = yaml.safe_load(pipeline_text())
    stages = pipeline["stages"]
    quality_job = stages["quality_stage"]["jobs"]["quality_job"]
    image_job = stages["image_stage"]["jobs"]["image_job"]
    for job in (quality_job, image_job):
        assert isinstance(job["runsOn"], dict)
        assert job["runsOn"] == FLOW_CI_RUNS_ON
    source_identity = quality_job["steps"]["source_identity"]["with"]["run"]
    commands = [line.strip() for line in source_identity.splitlines() if line.strip()]
    assert commands[:3] == [
        "set -Eeuo pipefail",
        "docker info --format 'docker_daemon_ready server_version={{.ServerVersion}}'",
        "docker compose version",
    ]


def test_compose_uses_one_application_image_variable() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert "image: ${APP_IMAGE:-edu-ai-lead-agent-backend:local}" in compose
    assert compose.count("<<: *app-runtime") == 15
    services = yaml.safe_load(compose)["services"]
    for service_name in (
        "official-account-local-worker",
        "official-account-local-fixture",
    ):
        assert services[service_name]["profiles"] == ["official-account-local"]
    assert services["ip-asset-worker"]["profiles"] == ["ip-assets"]
    assert services["official-account-weekly-dag-worker"]["profiles"] == [
        "official-account-weekly-dag"
    ]
    weekly_scheduler = services["official-account-weekly-scheduler"]
    assert weekly_scheduler["profiles"] == ["official-account-weekly-dag"]
    assert weekly_scheduler.get("ports") is None
    assert weekly_scheduler["command"] == [
        "python",
        "-m",
        "app.official_account_weekly_scheduler_main",
    ]
    weekly_worker = services["official-account-weekly-dag-worker"]
    assert weekly_worker.get("ports") is None
    assert weekly_worker["command"] == [
        "python",
        "-m",
        "app.official_account_weekly_dag_main",
        "--handler-mode",
        "${OFFICIAL_ACCOUNT_WEEKLY_HANDLER_MODE:-fixture}",
        "worker",
        "--concurrency",
        "3",
        "--lease-seconds",
        "${OFFICIAL_ACCOUNT_WEEKLY_WORKER_LEASE_SECONDS:-900}",
        "--poll-seconds",
        "${OFFICIAL_ACCOUNT_WEEKLY_WORKER_POLL_SECONDS:-2}",
    ]
    draft_worker = services["wechat-official-account-draft-worker"]
    assert draft_worker["profiles"] == ["wechat-official-account-draft"]
    assert draft_worker.get("ports") is None
    assert draft_worker["command"] == [
        "python",
        "-m",
        "app.wechat_official_account_draft_main",
        "worker",
    ]
    assert draft_worker["volumes"] == [
        "official_account_weekly_dag_output:/app/input/official-account-weekly-editions:ro",
        "wechat_mp_draft_artifacts:/app/output/wechat-mp-draft-artifacts",
    ]
    assert draft_worker["environment"]["WECHAT_MP_DRAFT_PRODUCTION_ENABLED"] == (
        "${WECHAT_MP_DRAFT_PRODUCTION_ENABLED:-false}"
    )
    assert draft_worker["environment"]["WECHAT_MP_DRAFT_MIN_WEEK_START"] == (
        "${WECHAT_MP_DRAFT_MIN_WEEK_START:-}"
    )
    assert draft_worker["environment"]["WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT"] == (
        "/app/input/weekly-inbox"
    )


def test_repository_migration_declaration_and_doctor_match_the_single_head() -> None:
    migration_blobs = {
        str(path): path.read_bytes()
        for path in Path("backend/alembic/versions").glob("*.py")
        if not path.name.startswith("__")
    }
    head = alembic_head_from_blobs(migration_blobs)
    declaration = Path("deploy/release/migration-compatibility.json").read_bytes()
    reviewed, compatible = load_compatibility_declaration(declaration, head)
    doctor = Path("scripts/doctor.sh").read_text(encoding="utf-8")

    assert json.loads(declaration)["alembic_head"] == head
    assert reviewed is True
    assert compatible is False
    assert f'[[ "$migration_revision" == "{head}" ]]' in doctor
    for schema_identity in (
        "brand_visual_index_jobs",
        "brand_visual_asset_embeddings",
        "embedding_input_sha256",
        "visual_embedding_vector_type",
    ):
        assert schema_identity in doctor


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
    assert "wechat-official-account-draft-worker" not in APPLICATION_SERVICES


def test_production_evidence_queries_the_bounded_diversity_warning_code() -> None:
    evidence_script = Path("scripts/edu-ai-production-evidence.sh").read_text(
        encoding="utf-8"
    )
    assert "diversity_warning = 'near_duplicate_after_retry'" in evidence_script
    assert "diversity_warning IS TRUE" not in evidence_script


def test_production_evidence_projects_only_safe_image_ocr_configuration() -> None:
    evidence_script = Path("scripts/edu-ai-production-evidence.sh").read_text(
        encoding="utf-8"
    )
    for key in (
        "image_ocr_enabled",
        "image_ocr_model",
        "image_ocr_max_input_bytes",
        "image_ocr_max_response_bytes",
        "image_ocr_timeout_seconds",
    ):
        assert f"printf '{key}=%s\\n'" in evidence_script
    assert "AI_PLATFORM_API_KEY" not in evidence_script
    assert "base64" not in evidence_script.casefold()
    assert "provider_body" not in evidence_script


def test_compose_and_doctor_share_the_bounded_image_ocr_contract() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    doctor = Path("scripts/doctor.sh").read_text(encoding="utf-8")
    defaults = {
        "IMAGE_OCR_MODEL": "glm-ocr",
        "IMAGE_OCR_MAX_INPUT_BYTES": "10485760",
        "IMAGE_OCR_MAX_RESPONSE_BYTES": "1048576",
        "IMAGE_OCR_TIMEOUT_SECONDS": "120",
    }
    for key, value in defaults.items():
        assert compose.count(f"{key}: ${{{key}:-{value}}}") == 2
        assert f'"{key}"' in doctor
    assert compose.count("IMAGE_OCR_ENABLED: ${IMAGE_OCR_ENABLED:-false}") == 2
    assert '"IMAGE_OCR_ENABLED"' in doctor
    assert "diversity_enabled = compose_bool" in doctor
    assert "ocr_enabled = compose_bool" in doctor
    assert "if diversity_enabled and ocr_enabled and environment[" in doctor
    assert "controlled image OCR must use the reviewed glm-ocr model" in doctor


def test_compose_and_doctor_pin_layered_topic_rerank_defaults() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    doctor = Path("scripts/doctor.sh").read_text(encoding="utf-8")

    assert "CONTENT_ENABLED: ${CONTENT_ENABLED:-false}" in compose
    assert "CONTENT_LLM_RERANK_ENABLED: ${CONTENT_LLM_RERANK_ENABLED:-true}" in compose
    assert (
        "CONTENT_LLM_RERANK_POLICY_VERSION: "
        "${CONTENT_LLM_RERANK_POLICY_VERSION:-topic-rerank-v4-minimal-order-contract}"
    ) in compose
    for key in (
        "CONTENT_ENABLED",
        "CONTENT_LLM_RERANK_ENABLED",
        "CONTENT_LLM_RERANK_POLICY_VERSION",
        "CONTENT_LLM_RERANK_CANDIDATE_LIMIT",
        "CONTENT_LLM_RERANK_MAX_OUTPUT_TOKENS",
        "AI_PROVIDER_MODE",
    ):
        assert f'"{key}"' in doctor
    assert "content selection rerank pool must remain capped at eight" in doctor
    assert "enabled content rerank must use fake or zhipu provider mode" in doctor
    assert '[[ "$source_count" == "11" ]]' in doctor
    assert 'pass "Eleven approved source profiles are active"' in doctor


def test_ci_toolchain_files_define_pinned_isolated_runtimes() -> None:
    dockerfile = Path("backend/Dockerfile.ci").read_text(encoding="utf-8")
    lock_script = Path("scripts/compile-python-locks.sh").read_text(encoding="utf-8")
    python_wrapper = Path("scripts/ci-python.sh").read_text(encoding="utf-8")
    node_wrapper = Path("scripts/ci-node.sh").read_text(encoding="utf-8")
    assert "python:3.11.15-slim-bookworm@sha256:" in dockerfile
    assert "--require-hashes --no-deps -r /tmp/dev.lock" in dockerfile
    assert "COPY requirements/dev.lock" in dockerfile
    assert 'readonly PIP_TOOLS_VERSION="7.6.1"' in lock_script
    assert (
        'readonly PYTHON_PACKAGE_INDEX="https://mirrors.aliyun.com/pypi/simple/"'
        in lock_script
    )
    assert lock_script.count('--index-url="${PYTHON_PACKAGE_INDEX}"') == 2
    assert "export PIP_CONFIG_FILE=/dev/null" in lock_script
    assert "unset PIP_CONSTRAINT PIP_EXTRA_INDEX_URL PIP_FIND_LINKS" in lock_script
    assert "CI_PYTHON_IMAGE is required" in python_wrapper
    assert "CI_NODE_IMAGE is required" in node_wrapper
    for wrapper in (python_wrapper, node_wrapper):
        assert '--volume "${PROJECT_ROOT}:/workspace"' in wrapper
        assert "source=/dev/null,target=/workspace/${env_path},readonly" in wrapper
        assert '[[ -f "${host_env_path}" ]]' in wrapper
        assert "reason=invalid_env_mask_target" in wrapper
        assert "--env HOME=/tmp/ci-home" in wrapper
        assert "--env-file" not in wrapper
        assert "docker.sock" not in wrapper
        assert "--network host" not in wrapper
        assert "--privileged" not in wrapper
    assert 'readonly COMPOSE_NETWORK="${CI_COMPOSE_NETWORK:-}"' in python_wrapper
    assert '--network "${COMPOSE_NETWORK}"' in python_wrapper
    assert "docker_args+=(--network none)" in python_wrapper
    assert "--env DATABASE_URL=postgresql+asyncpg://edu_ai:" in python_wrapper
    assert "--env MINIO_ENDPOINT=http://minio:9000" in python_wrapper
    assert "--env AI_PROVIDER_MODE=disabled" in python_wrapper
    assert "--env-file" not in python_wrapper
    assert 'readonly NETWORK="${CI_NODE_NETWORK:-none}"' in node_wrapper
    assert '--network "${NETWORK}"' in node_wrapper
    assert "CI_NODE_NETWORK=bridge npm ci --prefix frontend" in pipeline_text()
    assert "docker compose wait minio-init" not in pipeline_text()
    assert pipeline_starts_infra_before_backend_check()


def pipeline_text() -> str:
    return Path("deploy/yunxiao/pipeline.yaml").read_text(encoding="utf-8")


def capture_wrapper_arguments(
    wrapper: str,
    command: str,
    environment: dict[str, str],
    *,
    env_files_exist: bool = True,
) -> tuple[list[str], bool]:
    with tempfile.TemporaryDirectory(
        prefix=".ci-wrapper-test-", dir=PROJECT_ROOT
    ) as sandbox_name:
        sandbox = Path(sandbox_name)
        sandbox_scripts = sandbox / "scripts"
        fake_bin = sandbox / "fake-bin"
        sandbox_scripts.mkdir()
        fake_bin.mkdir()
        sandbox_wrapper = sandbox / wrapper
        shutil.copy2(PROJECT_ROOT / wrapper, sandbox_wrapper)
        if env_files_exist:
            for env_path in ENV_MASK_PATHS:
                target = sandbox / env_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("must-be-masked", encoding="utf-8")
        fake_docker = fake_bin / "docker"
        capture = sandbox / "docker-arguments"
        fake_docker.write_text(
            '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "${CI_CAPTURE_FILE}"\n',
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)
        process_environment = os.environ.copy()
        process_environment.update(environment)
        process_environment.update(
            {
                "CI_CAPTURE_FILE": str(capture),
                "PATH": f"{fake_bin}:{process_environment['PATH']}",
                "UNRELATED_HOST_SECRET": "must-not-reach-container",
            }
        )
        subprocess.run(
            ["bash", str(sandbox_wrapper), command, "--version"],
            check=True,
            cwd=sandbox,
            env=process_environment,
        )
        arguments = capture.read_text(encoding="utf-8").splitlines()
        env_target_created = any(
            (sandbox / env_path).exists() for env_path in ENV_MASK_PATHS
        )
        return arguments, env_target_created


def assert_common_wrapper_isolation(arguments: list[str]) -> None:
    assert "--env-file" not in arguments
    assert "--privileged" not in arguments
    assert "must-not-reach-container" not in arguments
    mounts = {
        arguments[index + 1]
        for index, argument in enumerate(arguments[:-1])
        if argument == "--mount"
    }
    for env_path in ENV_MASK_PATHS:
        assert (
            f"type=bind,source=/dev/null,target=/workspace/{env_path},readonly"
            in mounts
        )


def test_ci_wrapper_runtime_arguments_are_isolated() -> None:
    python_image = "edu-ai-lead-agent-ci-python:git-0123456789ab"
    node_image = (
        "node:20.20.2-bookworm-slim@sha256:"
        "2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
    )

    python_arguments, _ = capture_wrapper_arguments(
        "scripts/ci-python.sh",
        "python",
        {"CI_PYTHON_IMAGE": python_image, "CI_COMPOSE_NETWORK": ""},
    )
    assert_common_wrapper_isolation(python_arguments)
    assert python_arguments[python_arguments.index("--network") + 1] == "none"

    compose_arguments, _ = capture_wrapper_arguments(
        "scripts/ci-python.sh",
        "pytest",
        {
            "CI_PYTHON_IMAGE": python_image,
            "CI_COMPOSE_NETWORK": "edu_ai_default",
        },
    )
    assert_common_wrapper_isolation(compose_arguments)
    assert compose_arguments[compose_arguments.index("--network") + 1] == (
        "edu_ai_default"
    )
    assert "AI_PROVIDER_MODE=disabled" in compose_arguments
    assert "WECOM_ENABLED=false" in compose_arguments

    node_arguments, _ = capture_wrapper_arguments(
        "scripts/ci-node.sh",
        "node",
        {"CI_NODE_IMAGE": node_image},
    )
    assert_common_wrapper_isolation(node_arguments)
    assert node_arguments[node_arguments.index("--network") + 1] == "none"

    online_node_arguments, _ = capture_wrapper_arguments(
        "scripts/ci-node.sh",
        "npm",
        {"CI_NODE_IMAGE": node_image, "CI_NODE_NETWORK": "bridge"},
    )
    assert_common_wrapper_isolation(online_node_arguments)
    assert online_node_arguments[online_node_arguments.index("--network") + 1] == (
        "bridge"
    )

    clean_python_arguments, clean_python_env_target_created = capture_wrapper_arguments(
        "scripts/ci-python.sh",
        "python",
        {"CI_PYTHON_IMAGE": python_image, "CI_COMPOSE_NETWORK": ""},
        env_files_exist=False,
    )
    assert "--mount" not in clean_python_arguments
    assert not clean_python_env_target_created

    clean_node_arguments, clean_node_env_target_created = capture_wrapper_arguments(
        "scripts/ci-node.sh",
        "npx",
        {"CI_NODE_IMAGE": node_image},
        env_files_exist=False,
    )
    assert "--mount" not in clean_node_arguments
    assert not clean_node_env_target_created


def pipeline_starts_infra_before_backend_check() -> bool:
    pipeline = Path("deploy/yunxiao/pipeline.yaml").read_text(encoding="utf-8")
    quality = pipeline.split("quality_checks:", 1)[1].split("image_stage:", 1)[0]
    infra = quality.index(
        "docker compose up -d --wait --wait-timeout 120 postgres minio"
    )
    init = quality.index("docker compose run --rm --no-deps minio-init")
    backend = quality.index('make PY_RUN="$PWD/scripts/ci-python.sh" backend-check')
    return infra < init < backend


def test_external_side_effect_flags_default_closed() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    for setting in (
        "AI_PROVIDER_MODE: ${AI_PROVIDER_MODE:-disabled}",
        "GOVERNANCE_ENABLED: ${GOVERNANCE_ENABLED:-false}",
        "CONTENT_ENABLED: ${CONTENT_ENABLED:-false}",
        "CONTENT_SCHEDULER_ENABLED: ${CONTENT_SCHEDULER_ENABLED:-false}",
        "CONTENT_WORKER_ENABLED: ${CONTENT_WORKER_ENABLED:-false}",
        "IMAGE_ENABLED: ${IMAGE_ENABLED:-false}",
        "IP_ASSET_RECOGNITION_ENABLED: ${IP_ASSET_RECOGNITION_ENABLED:-false}",
        "VISUAL_SEMANTIC_ENABLED: ${VISUAL_SEMANTIC_ENABLED:-false}",
        "WECOM_ENABLED: ${WECOM_ENABLED:-false}",
        "WECOM_AUTO_DELIVERY_ENABLED: ${WECOM_AUTO_DELIVERY_ENABLED:-false}",
    ):
        assert setting in compose
