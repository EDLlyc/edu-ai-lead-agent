from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "release-prod.sh"
COMMIT = "a" * 40
IMAGE_REPOSITORY = "registry.example.test/edu-ai/edu-ai-lead-agent"


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_make_target_exposes_local_release_entrypoint() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "release-prod:" in makefile
    assert "@bash scripts/release-prod.sh" in makefile


def test_local_release_uses_authoritative_source_and_existing_contracts() -> None:
    script = script_text()
    assert "refs/remotes/origin/main" in script
    assert (
        "https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/"
        "marketingUseOnly/edu-ai-lead-agent.git"
    ) in script
    assert (
        "git@codeup-edu-ai:601cdb1a841cc46b7c49b115/"
        "marketingUseOnly/edu-ai-lead-agent.git"
    ) in script
    assert 'git -C "${PROJECT_ROOT}" fetch --quiet --no-tags ' in script
    assert '"refs/heads/main:${SOURCE_REF}"' in script
    assert "GIT_TERMINAL_PROMPT=0" in script
    assert "GIT_ASKPASS=/bin/false" in script
    assert "SSH_ASKPASS=/bin/false" in script
    assert 'worktree add --detach "${worktree}" "${release_commit}"' in script
    assert "release_orchestrator_not_committed" in script
    assert "deploy/release/release_tool.py build-bundle" in script
    assert "deploy/release/release_tool.py create-manifest" in script
    assert "deploy/release/release_tool.py verify-bundle" in script
    assert script.count('--gate "') == 9
    assert "/usr/local/sbin/edu-ai-deploy" in script
    assert "--manifest ${remote_dir}/release-manifest.json" in script
    assert "--expected-commit ${release_commit}" in script
    assert "edu-ai-release-evidence/${release_commit}" in script
    assert 'install -m 0600 "${bundle}" "${members}" "${manifest}"' in script
    assert 'manifest["bundle"]["member_manifest_sha256"]' in script
    assert "local_evidence_retained=true" in script


def test_real_release_orders_preflight_before_mutation_and_transfers_fixed_files() -> (
    None
):
    script = script_text()
    main = script.split("main() {", 1)[1].split('\n}\n\nif [[ "${BASH_SOURCE[0]}"', 1)[
        0
    ]
    assert main.index("remote_preflight") < main.index("fetch_and_create_worktree")
    assert main.index("fetch_and_create_worktree") < main.index(
        "prepare_toolchains_and_infrastructure"
    )
    assert main.index("prepare_toolchains_and_infrastructure") < main.index(
        "run_quality_gates"
    )
    assert main.index("run_quality_gates") < main.index("publish_verified_release")
    transfer = script.split("transfer_and_deploy() {", 1)[1].split(
        "\n}\n\npublish_verified_release", 1
    )[0]
    assert '"${artifact_dir}/${bundle_name}"' in transfer
    assert '"${artifact_dir}/${members_name}"' in transfer
    assert '"${artifact_dir}/release-manifest.json"' in transfer
    assert "${artifact_dir}/*" not in transfer
    assert transfer.count("scp ") == 1


def test_local_release_resolves_and_exercises_immutable_image() -> None:
    script = script_text()
    local_exercise = script.index('exercise_application_image "${readable_image}"')
    push = script.index('docker push "${readable_image}"')
    resolve = script.index('resolved_image_reference="$(')
    immutable_exercise = script.index(
        'exercise_application_image "${resolved_image_reference}"'
    )
    cache_update = script.index('docker push "${cache_image}"')
    migration = script.index("docker compose run --rm --no-deps backend-migrate")
    doctor = script.index('DOCTOR_PYTHON="${worktree}/.ci-bin/python" make doctor')
    artifacts = script.index("build_and_verify_artifacts()")
    assert local_exercise < push < resolve < immutable_exercise < cache_update
    assert immutable_exercise < migration < doctor < artifacts
    assert 'export APP_IMAGE="${readable_image}"' not in script
    assert '--cache-from "${cache_image}"' in script
    assert 'docker pull "${resolved_image_reference}"' in script
    assert "^sha256:[0-9a-f]{64}$" in script


def test_verbose_release_stages_do_not_return_values_through_stdout() -> None:
    script = script_text()
    assert 'image_reference="$(build_push_and_resolve_image' not in script
    assert 'artifact_dir="$(build_and_verify_artifacts' not in script
    assert 'build_push_and_resolve_image "${created}"' in script
    assert (
        'build_and_verify_artifacts "${created}" "${resolved_image_reference}"'
        in script
    )
    assert 'transfer_and_deploy "${verified_artifact_dir}"' in script


def test_noisy_release_stages_cannot_corrupt_explicit_results(tmp_path: Path) -> None:
    capture = tmp_path / "published"
    shell = f"""
source {SCRIPT!s}
release_commit={"a" * 40}
build_push_and_resolve_image() {{
  printf '%s\\n' 'noisy docker output'
  resolved_image_reference='{IMAGE_REPOSITORY}@sha256:{"b" * 64}'
}}
build_and_verify_artifacts() {{
  printf '%s\\n' 'noisy release_tool output'
  [[ "$2" == "$resolved_image_reference" ]]
  verified_artifact_dir='/verified/release-artifacts'
}}
transfer_and_deploy() {{
  [[ "$1" == '/verified/release-artifacts' ]]
  printf '%s\\n' "$resolved_image_reference|$1" > {capture!s}
}}
publish_verified_release '2026-08-14T00:00:00Z'
"""
    result = subprocess.run(
        ["bash", "-c", shell], check=False, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "noisy docker output" in result.stdout
    assert "noisy release_tool output" in result.stdout
    assert capture.read_text(encoding="utf-8").strip() == (
        f"{IMAGE_REPOSITORY}@sha256:{'b' * 64}|/verified/release-artifacts"
    )


def test_local_release_forbids_interactive_or_argv_credentials() -> None:
    script = script_text()
    for option in (
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no",
        "NumberOfPasswordPrompts=0",
        "ConnectTimeout=10",
        "ServerAliveInterval=30",
        "ServerAliveCountMax=3",
    ):
        assert option in script
    for forbidden in (
        "docker login",
        "sshpass",
        "StrictHostKeyChecking=no",
        "--password",
        "--identity-file",
    ):
        assert forbidden not in script
    assert "positional_arguments_forbidden" in script
    assert "forbidden_secret_input" in script
    assert 'scp "${SSH_OPTIONS[@]}" --' in script
    assert "ssh-keygen -F" in script
    assert "unsupported_release_environment" in script
    assert "nonlocal_docker_context" in script


def test_local_release_neutralizes_compose_and_external_effect_environment(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "source"
    (worktree / "scripts").mkdir(parents=True)
    shell = f"""
source {SCRIPT!s}
release_commit={"a" * 40}
worktree={worktree!s}
docker() {{
  case " $* " in
    *" compose ps -q postgres "*) printf '%s\n' postgres-id ;;
    *" inspect --format "*) printf '%s\n' release-network ;;
  esac
}}
python() {{ return 0; }}
node() {{ return 0; }}
npm() {{ return 0; }}
prepare_toolchains_and_infrastructure
printf '%s\n' \
  "$COMPOSE_FILE" "$COMPOSE_DISABLE_ENV_FILE" "${{APP_IMAGE-unset}}" \
  "$AI_PROVIDER_MODE" "$AI_PLATFORM_API_KEY" "$IMAGE_ENABLED" \
  "$TOAPIS_API_KEY" "$COMFLY_API_KEY" "$WECOM_ENABLED" \
  "$WECOM_CORP_SECRET" "$POSTGRES_PASSWORD" "$MINIO_ROOT_PASSWORD"
"""
    environment = os.environ.copy()
    environment.update(
        {
            "APP_IMAGE": "production.example/app@sha256:" + "f" * 64,
            "COMPOSE_FILE": "/tmp/production-compose.yaml",
            "AI_PROVIDER_MODE": "live",
            "AI_PLATFORM_API_KEY": "host-ai-secret",
            "IMAGE_ENABLED": "true",
            "TOAPIS_API_KEY": "host-image-secret",
            "COMFLY_API_KEY": "host-comfly-secret",
            "WECOM_ENABLED": "true",
            "WECOM_CORP_SECRET": "host-wecom-secret",
            "POSTGRES_PASSWORD": "host-db-secret",
            "MINIO_ROOT_PASSWORD": "host-minio-secret",
        }
    )
    result = subprocess.run(
        ["bash", "-c", shell],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(worktree / "compose.yaml"),
        "true",
        "unset",
        "disabled",
        "",
        "false",
        "",
        "",
        "false",
        "",
        "edu_ai_local_change_me",
        "edu_ai_minio_local_change_me",
    ]
    assert "host-" not in result.stdout + result.stderr


def test_unknown_remote_deploy_status_retains_remote_inbox(tmp_path: Path) -> None:
    capture = tmp_path / "ssh-called"
    shell = f"""
source {SCRIPT!s}
release_commit={"a" * 40}
remote_dir=/tmp/edu-ai-release.${{release_commit}}.abc123
remote_deploy_started=true
remote_deploy_finished=false
ssh() {{ touch {capture!s}; }}
cleanup_remote
[[ "$remote_dir" == /tmp/edu-ai-release.${{release_commit}}.abc123 ]]
"""
    result = subprocess.run(
        ["bash", "-c", shell], check=False, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "remote_cleanup_deferred" in result.stdout
    assert not capture.exists()


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _dry_run_sandbox(
    tmp_path: Path, request: pytest.FixtureRequest
) -> tuple[Path, dict[str, str]]:
    sandbox = tmp_path / "repository"
    scripts = sandbox / "scripts"
    fake_bin = Path(tempfile.mkdtemp(prefix=".local-release-test-", dir=PROJECT_ROOT))
    request.addfinalizer(lambda: shutil.rmtree(fake_bin, ignore_errors=True))
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    capture = tmp_path / "commands.log"

    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
printf 'git' >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf ' <%s>' "$@" >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf '\n' >> "$LOCAL_RELEASE_TEST_CAPTURE"
case " $* " in
  *" remote get-url origin "*)
    printf '%s\n' "$LOCAL_RELEASE_TEST_ORIGIN_URL"
    ;;
  *" rev-parse --verify refs/remotes/origin/main^{commit} "*)
    printf '%s\n' "$LOCAL_RELEASE_TEST_COMMIT"
    ;;
  *" cat-file -e "*) ;;
  *) exit 91 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
printf 'docker' >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf ' <%s>' "$@" >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf '\n' >> "$LOCAL_RELEASE_TEST_CAPTURE"
case " $* " in
  " context inspect --format "*) printf '%s\n' "$LOCAL_RELEASE_TEST_DOCKER_ENDPOINT" ;;
  " info --format "*) printf '%s\n' '29.1.3' ;;
  " compose version --short "*) printf '%s\n' '2.40.3' ;;
  *) exit 92 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
printf 'ssh' >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf ' <%s>' "$@" >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf '\n' >> "$LOCAL_RELEASE_TEST_CAPTURE"
case " $* " in
  *" -G codeup-edu-ai "*)
    printf '%s\n' \
      'hostname codeup.aliyun.com' \
      'port 22' \
      'user git' \
      "userknownhostsfile $LOCAL_RELEASE_TEST_KNOWN_HOSTS"
    ;;
  *" -G "*)
    printf '%s\n' \
      'hostname 192.0.2.10' \
      'port 22' \
      "userknownhostsfile $LOCAL_RELEASE_TEST_KNOWN_HOSTS"
    ;;
  *) exit 93 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "ssh-keygen",
        """#!/usr/bin/env bash
printf 'ssh-keygen' >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf ' <%s>' "$@" >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf '\n' >> "$LOCAL_RELEASE_TEST_CAPTURE"
[[ "$LOCAL_RELEASE_TEST_KNOWN_HOST_PRESENT" == true ]]
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
printf 'scp' >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf ' <%s>' "$@" >> "$LOCAL_RELEASE_TEST_CAPTURE"
printf '\n' >> "$LOCAL_RELEASE_TEST_CAPTURE"
exit 94
""",
    )
    _write_executable(fake_bin / "make", "#!/usr/bin/env bash\nexit 0\n")
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("RELEASE_"):
            environment.pop(key)
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "RELEASE_DRY_RUN": "true",
            "RELEASE_IMAGE_REPOSITORY": IMAGE_REPOSITORY,
            "RELEASE_SSH_HOST": "edu-ai-production",
            "LOCAL_RELEASE_TEST_CAPTURE": str(capture),
            "LOCAL_RELEASE_TEST_COMMIT": COMMIT,
            "LOCAL_RELEASE_TEST_DOCKER_ENDPOINT": "unix:///var/run/docker.sock",
            "LOCAL_RELEASE_TEST_KNOWN_HOSTS": str(tmp_path / "known_hosts"),
            "LOCAL_RELEASE_TEST_KNOWN_HOST_PRESENT": "true",
            "LOCAL_RELEASE_TEST_ORIGIN_URL": (
                "git@codeup.aliyun.com:601cdb1a841cc46b7c49b115/"
                "marketingUseOnly/edu-ai-lead-agent.git"
            ),
        }
    )
    (tmp_path / "known_hosts").write_text("hashed test host\n", encoding="utf-8")
    return sandbox, environment


def test_dry_run_is_read_only_and_does_not_connect(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    sandbox, environment = _dry_run_sandbox(tmp_path, request)
    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / SCRIPT.name)],
        cwd=sandbox,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"commit={COMMIT}" in result.stdout
    assert "mutation=false" in result.stdout
    commands = Path(environment["LOCAL_RELEASE_TEST_CAPTURE"]).read_text(
        encoding="utf-8"
    )
    assert "docker <info>" in commands
    assert "docker <compose> <version>" in commands
    assert "ssh" in commands and " <-G> <edu-ai-production>" in commands
    assert "ssh-keygen <-F> <192.0.2.10>" in commands
    for forbidden in (
        " fetch ",
        " worktree ",
        "docker <build>",
        "docker <push>",
        "scp",
        "<edu-ai-production> <true>",
        "sudo",
    ):
        assert forbidden not in commands


@pytest.mark.parametrize(
    ("environment_change", "expected_code"),
    [
        ({"RELEASE_IMAGE_REPOSITORY": ""}, "invalid_image_repository"),
        (
            {"RELEASE_IMAGE_REPOSITORY": f"{IMAGE_REPOSITORY}:latest"},
            "invalid_image_repository",
        ),
        ({"RELEASE_SSH_HOST": "root@production"}, "invalid_ssh_host"),
        ({"RELEASE_DRY_RUN": "sometimes"}, "invalid_dry_run"),
        ({"RELEASE_TOKEN": "must-not-be-printed"}, "forbidden_secret_input"),
        ({"DOCKER_AUTH_CONFIG": "must-not-be-printed"}, "forbidden_secret_input"),
        ({"RELEASE_UNDOCUMENTED": "value"}, "unsupported_release_environment"),
    ],
)
def test_invalid_input_fails_before_capability_or_source_checks(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    environment_change: dict[str, str],
    expected_code: str,
) -> None:
    sandbox, environment = _dry_run_sandbox(tmp_path, request)
    environment.update(environment_change)
    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / SCRIPT.name)],
        cwd=sandbox,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert f"release_prod_failed code={expected_code}" in result.stderr
    assert "must-not-be-printed" not in result.stdout + result.stderr
    capture = Path(environment["LOCAL_RELEASE_TEST_CAPTURE"])
    assert not capture.exists()


def test_dry_run_validates_codeup_alias_origin_and_known_host(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    sandbox, environment = _dry_run_sandbox(tmp_path, request)
    environment["LOCAL_RELEASE_TEST_ORIGIN_URL"] = (
        "git@codeup-edu-ai:601cdb1a841cc46b7c49b115/"
        "marketingUseOnly/edu-ai-lead-agent.git"
    )
    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / SCRIPT.name)],
        cwd=sandbox,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    commands = Path(environment["LOCAL_RELEASE_TEST_CAPTURE"]).read_text(
        encoding="utf-8"
    )
    assert " <-G> <codeup-edu-ai>" in commands

    sandbox, environment = _dry_run_sandbox(tmp_path / "evil-origin", request)
    environment["LOCAL_RELEASE_TEST_ORIGIN_URL"] = (
        "ssh://codeup.evil.example/marketingUseOnly/edu-ai-lead-agent.git"
    )
    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / SCRIPT.name)],
        cwd=sandbox,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "code=origin_is_not_authoritative_codeup" in result.stderr

    sandbox, environment = _dry_run_sandbox(tmp_path / "missing-host", request)
    environment["LOCAL_RELEASE_TEST_KNOWN_HOST_PRESENT"] = "false"
    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / SCRIPT.name)],
        cwd=sandbox,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "code=ssh_known_host_missing" in result.stderr
    commands = Path(environment["LOCAL_RELEASE_TEST_CAPTURE"]).read_text(
        encoding="utf-8"
    )
    assert "git" not in commands


def test_dry_run_rejects_nonlocal_docker_context(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    sandbox, environment = _dry_run_sandbox(tmp_path, request)
    environment["LOCAL_RELEASE_TEST_DOCKER_ENDPOINT"] = "ssh://production.example"
    result = subprocess.run(
        ["bash", str(sandbox / "scripts" / SCRIPT.name)],
        cwd=sandbox,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "code=nonlocal_docker_context" in result.stderr
    assert "production.example" not in result.stdout + result.stderr
