#!/usr/bin/env bash
# Provider-free static/fake harness for the task-local builder, validator, and operator.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

readonly HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly BUILDER="${HERE}/build-wechat-draft-offline-artifacts.sh"
readonly BASELINE_CAPTURE="${HERE}/capture-wechat-draft-production-baseline.sh"
readonly VALIDATOR="${HERE}/validate-wechat-draft-offline-artifacts.py"
readonly OPERATOR="${HERE}/wechat-draft-offline-release-operator.sh"
test_root=$(mktemp -d /tmp/edu-ai-wechat-draft-harness.XXXXXX)

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "missing reviewed text: $2"; }
reject_text() { ! grep -Fqi -- "$2" "$1" || fail "forbidden text present: $2"; }

cleanup() {
  if [[ "$test_root" == /tmp/edu-ai-wechat-draft-harness.* && -d "$test_root" ]]; then
    find "$test_root" -depth -delete
  fi
}
trap cleanup EXIT

build_fixture_stage() {
  local stage=$1 source_root="${test_root}/source" image_root="${test_root}/image" config_sha
  mkdir -m 700 "$stage" "$source_root" "$image_root" "$image_root/layer"
  local path
  for path in \
    compose.yaml backend/alembic.ini backend/pyproject.toml \
    backend/app/wechat_official_account_draft_main.py \
    backend/app/infrastructure/wechat_official_account/artifacts.py \
    backend/alembic/versions/20260901_0042_wechat_official_account_draft_jobs.py \
    deploy/release/migration-compatibility.json; do
    mkdir -p "$source_root/$(dirname -- "$path")"
    printf 'fixture:%s\n' "$path" >"$source_root/$path"
  done
  (
    cd "$source_root"
    find . -type f -print0 | sort -z | while IFS= read -r -d '' path; do
      sha256sum "${path#./}"
    done >"$stage/source-files.sha256"
    tar -czf "$stage/source.tar.gz" --sort=name --mtime=@0 --owner=0 --group=0 \
      backend compose.yaml deploy
  )
  cat >"$image_root/config.json" <<'JSON'
{"architecture":"amd64","config":{"Labels":{"org.opencontainers.image.revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"User":"app"}}
JSON
  config_sha=$(sha256sum "$image_root/config.json" | awk '{print $1}')
  mv "$image_root/config.json" "$image_root/${config_sha}.json"
  printf 'fixture-layer\n' >"$image_root/layer/layer.tar"
  printf '[{"Config":"%s.json","Layers":["layer/layer.tar"],"RepoTags":["edu-ai-lead-agent-backend:wechat-draft-aaaaaaaaaaaa"]}]\n' \
    "$config_sha" >"$image_root/manifest.json"
  tar -C "$image_root" -cf - "${config_sha}.json" layer/layer.tar manifest.json \
    | gzip -n >"$stage/backend-image.tar.gz"
  install -m 600 "$VALIDATOR" "$stage/validate-wechat-draft-offline-artifacts.py"
  install -m 600 "$OPERATOR" "$stage/wechat-draft-offline-release-operator.sh"
  cat >"$stage/production-baseline.json" <<'JSON'
{
  "current_alembic_head": "20260825_0036",
  "current_image_id": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "current_image_revision": "dddddddddddddddddddddddddddddddddddddddd",
  "env_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "observed_at_utc": "2026-09-02T00:00:00Z",
    "release_env_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "restart_counts": {"acquisition-api": 0, "acquisition-scheduler": 0, "acquisition-worker": 0, "content-scheduler": 0, "content-worker": 0, "governance-scheduler": 0, "governance-worker": 0, "minio": 0, "postgres": 0, "wecom-dispatcher": 0},
  "running_services": ["acquisition-api", "acquisition-scheduler", "acquisition-worker", "content-scheduler", "content-worker", "governance-scheduler", "governance-worker", "minio", "postgres", "wecom-dispatcher"],
  "schema_version": 1,
  "source_tree_sha256": "1111111111111111111111111111111111111111111111111111111111111111"
}
JSON
  (
    cd "$stage"
    sha256sum source.tar.gz >source.tar.gz.sha256
    sha256sum backend-image.tar.gz >backend-image.tar.gz.sha256
  )
  python3 - "$stage" "$config_sha" <<'PY'
import hashlib
import json
import pathlib
import sys

stage = pathlib.Path(sys.argv[1])
config_sha = sys.argv[2]
digest = lambda name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
payload = {
    "schema_version": 1,
    "release_commit": "a" * 40,
    "candidate_tag": "edu-ai-lead-agent-backend:wechat-draft-" + "a" * 12,
    "candidate_id": "sha256:" + config_sha,
    "alembic_head": "20260901_0042",
    "source_sha256": digest("source.tar.gz"),
    "source_manifest_sha256": digest("source-files.sha256"),
    "image_archive_sha256": digest("backend-image.tar.gz"),
    "operator_sha256": digest("wechat-draft-offline-release-operator.sh"),
    "production_baseline_sha256": digest("production-baseline.json"),
    "validator_sha256": digest("validate-wechat-draft-offline-artifacts.py"),
    "runtime_modules": [
        "app.api_main", "app.scheduler_main", "app.worker_main",
        "app.governance_scheduler_main", "app.governance_worker_main",
        "app.content_scheduler_main", "app.content_worker_main",
        "app.wecom_dispatcher_main", "app.wechat_official_account_draft_main",
    ],
}
(stage / "release-metadata.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY
  (
    cd "$stage"
    sha256sum \
      backend-image.tar.gz backend-image.tar.gz.sha256 production-baseline.json \
      release-metadata.json \
      source-files.sha256 source.tar.gz source.tar.gz.sha256 \
      validate-wechat-draft-offline-artifacts.py \
      wechat-draft-offline-release-operator.sh | sort -k2 >artifacts.sha256
    chmod 600 ./*
  )
}

assert_validator_contract() {
  local stage="${test_root}/stage" tampered="${test_root}/tampered"
  build_fixture_stage "$stage"
  python3 "$VALIDATOR" "$stage" | grep -Fq artifact_validation_ok \
    || fail "valid fixture stage was rejected"
  cp -a "$stage" "$tampered"
  printf 'tamper\n' >>"$tampered/source.tar.gz"
  if python3 "$VALIDATOR" "$tampered" >/dev/null 2>&1; then
    fail "tampered source archive was accepted"
  fi
  cp -a "$stage" "${test_root}/extra"
  printf 'extra\n' >"${test_root}/extra/unexpected"
  chmod 600 "${test_root}/extra/unexpected"
  if python3 "$VALIDATOR" "${test_root}/extra" >/dev/null 2>&1; then
    fail "unexpected stage member was accepted"
  fi
  chmod 700 "$stage/source.tar.gz"
  if python3 "$VALIDATOR" "$stage" >/dev/null 2>&1; then
    fail "stage mode drift was accepted"
  fi
  chmod 600 "$stage/source.tar.gz"
  if [[ $EUID -eq 0 ]]; then
    chown 12345:12345 "$stage/source.tar.gz"
    if python3 "$VALIDATOR" "$stage" >/dev/null 2>&1; then
      fail "stage ownership drift was accepted"
    fi
    chown 0:0 "$stage/source.tar.gz"
  fi
}

assert_static_safety_contract() {
  bash -n "$BASELINE_CAPTURE" "$BUILDER" "$OPERATOR" "$0"
  python3 - "$VALIDATOR" <<'PY'
import ast
import pathlib
import sys

ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
  require_text "$BUILDER" 'refs/remotes/origin/main'
  require_text "$BUILDER" 'worktree add --detach'
  require_text "$BUILDER" '--network none --read-only --cap-drop ALL'
  require_text "$BASELINE_CAPTURE" 'metadata.st_uid'
  require_text "$BASELINE_CAPTURE" 'metadata.st_gid'
  require_text "$OPERATOR" 'operator stdin must be /dev/null'
  require_text "$OPERATOR" 'WECHAT_MP_DRAFT_MIN_WEEK_START'
  require_text "$OPERATOR" 'WECHAT_MP_DRAFT_PRODUCTION_ENABLED'
  require_text "$OPERATOR" 'previous application remains conservatively incompatible'
  require_text "$OPERATOR" 'provider_writes=0'
  require_text "$OPERATOR" 'candidate already has an attempt marker'
  require_text "$OPERATOR" '--no-build --no-deps wechat-official-account-draft-worker'
  reject_text "$OPERATOR" 'freepublish'
  reject_text "$OPERATOR" 'masssend'
  reject_text "$OPERATOR" 'seed_sources'
  reject_text "$OPERATOR" 'minio-init'
  reject_text "$OPERATOR" 'build-broad-offline-artifacts'
  reject_text "$OPERATOR" 'broad-offline-release-operator'
}

baseline_source_fingerprint() {
  local app_root=$1
  (
    export WECHAT_DRAFT_BASELINE_SOURCE_ONLY=1
    export WECHAT_DRAFT_BASELINE_TEST_APP_DIR="$app_root"
    # shellcheck source=capture-wechat-draft-production-baseline.sh
    source "$BASELINE_CAPTURE"
    source_tree_fingerprint
  )
}

operator_source_fingerprint() {
  local app_root=$1
  (
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    export WECHAT_DRAFT_OPERATOR_TEST_APP_DIR="$app_root"
    # shellcheck source=wechat-draft-offline-release-operator.sh
    source "$OPERATOR"
    source_tree_fingerprint
  )
}

assert_source_metadata_binding() {
  local app_root="${test_root}/metadata-app" name initial captured mode_changed owner_changed
  mkdir -m 700 "$app_root"
  for name in backend deploy infra scripts; do
    mkdir -m 700 "$app_root/$name"
    printf 'fixture:%s\n' "$name" >"$app_root/$name/value"
    chmod 600 "$app_root/$name/value"
  done
  for name in compose.yaml .env.example .gitattributes .gitignore AGENTS.md Makefile README.md environment.yml; do
    printf 'fixture:%s\n' "$name" >"$app_root/$name"
    chmod 600 "$app_root/$name"
  done

  initial=$(baseline_source_fingerprint "$app_root")
  captured=$(operator_source_fingerprint "$app_root")
  [[ "$initial" == "$captured" ]] \
    || fail "capture/operator source fingerprint algorithms diverged"

  chmod 640 "$app_root/backend/value"
  mode_changed=$(operator_source_fingerprint "$app_root")
  [[ "$mode_changed" != "$initial" ]] || fail "managed file mode drift was not fingerprinted"
  chmod 600 "$app_root/backend/value"

  if [[ $EUID -eq 0 ]]; then
    chown 12345:12345 "$app_root/backend/value"
    owner_changed=$(operator_source_fingerprint "$app_root")
    [[ "$owner_changed" != "$initial" ]] \
      || fail "managed file ownership drift was not fingerprinted"
    chown 0:0 "$app_root/backend/value"
  fi
  [[ "$(operator_source_fingerprint "$app_root")" == "$initial" ]] \
    || fail "source fingerprint did not return to the captured baseline"
}

assert_builder_arguments_fail_closed() {
  local output="${test_root}/builder-output" failure_rc baseline="${test_root}/builder-baseline.json"
  printf '{}\n' >"$baseline"
  chmod 600 "$baseline"
  (
    export WECHAT_DRAFT_BUILDER_SOURCE_ONLY=1
    # shellcheck source=build-wechat-draft-offline-artifacts.sh
    source "$BUILDER"
    scratch="${test_root}/builder-scratch"
    mkdir -p "$scratch"
    parse_args --release-sha "$(printf 'a%.0s' {1..40})" \
      --production-baseline "$baseline" --output-dir "$output"
    [[ "$release_sha" == "$(printf 'a%.0s' {1..40})" && "$output_dir" == "$output" ]]
  ) || fail "builder rejected valid bounded arguments"
  set +e
  (
    set -e
    export WECHAT_DRAFT_BUILDER_SOURCE_ONLY=1
    source "$BUILDER"
    parse_args --release-sha short --production-baseline "$baseline" --output-dir relative
  ) >/dev/null 2>&1
  failure_rc=$?
  set -e
  ((failure_rc != 0)) || fail "builder accepted invalid release authority arguments"
}

assert_fake_failure_boundaries() {
  local migration_marker="${test_root}/migration-recovery" failure_rc
  set +e
  (
    set -e
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    # shellcheck source=wechat-draft-offline-release-operator.sh
    source "$OPERATOR"
    prepare_attempt() { backup_dir="${test_root}/fake-backup-one"; mkdir -p "$backup_dir"; }
    quiesce_and_backup() { :; }
    disable_draft_flags() { :; }
    write_release_env() { :; }
    activate_source() { source_activated=1; }
    validate_installed_source_modes() { :; }
    compose() { [[ "${1-}" != run ]]; }
    on_exit() { printf 'migrated=%s source=%s\n' "$migrated" "$source_activated" >"$migration_marker"; }
    release_commit=$(printf 'c%.0s' {1..40})
    candidate_id="sha256:$(printf 'd%.0s' {1..64})"
    minimum_week=2026-09-07
    run_activation
  )
  failure_rc=$?
  set -e
  if ((failure_rc == 0)); then
    fail "fake migration failure unexpectedly succeeded"
  fi
  grep -Fq 'migrated=0 source=1' "$migration_marker" \
    || fail "pre-migration recovery boundary was not selected"

  local optional_marker="${test_root}/optional-incident"
  set +e
  (
    set -e
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    # shellcheck source=wechat-draft-offline-release-operator.sh
    source "$OPERATOR"
    prepare_attempt() { backup_dir="${test_root}/fake-backup-two"; mkdir -p "$backup_dir"; }
    quiesce_and_backup() { :; }
    disable_draft_flags() { :; }
    write_release_env() { :; }
    activate_source() { source_activated=1; }
    validate_installed_source_modes() { :; }
    enable_draft_flags() { :; }
    ensure_draft_volumes() { :; }
    preflight_services() { :; }
    safe_job_counts() { printf '0:0:0\n'; }
    sleep() { :; }
    compose() {
      if [[ "${1-}" == exec ]]; then printf '%s\n' "$EXPECTED_HEAD"; fi
      return 0
    }
    compose_with_draft() { [[ "${1-}" != up ]]; }
    on_exit() { printf 'migrated=%s source=%s\n' "$migrated" "$source_activated" >"$optional_marker"; }
    release_commit=$(printf 'e%.0s' {1..40})
    candidate_id="sha256:$(printf 'f%.0s' {1..64})"
    minimum_week=2026-09-07
    run_activation
  )
  failure_rc=$?
  set -e
  if ((failure_rc == 0)); then
    fail "fake optional-worker failure unexpectedly succeeded"
  fi
  grep -Fq 'migrated=1 source=1' "$optional_marker" \
    || fail "post-migration incident boundary was not selected"
}

assert_absent_volume_preflight_and_controlled_creation() {
  local failure_rc create_marker="${test_root}/volume-create-called"
  (
    set -e
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    # shellcheck source=wechat-draft-offline-release-operator.sh
    source "$OPERATOR"
    compose() {
      [[ "${1-}" == ps ]] && printf 'fixture-container\n'
      return 0
    }
    safe_job_counts() { printf '0:0:0\n'; }
    docker() {
      case "${1-}:${2-}" in
        inspect:*)
          if [[ "$*" == *State.Health* ]]; then printf 'healthy\n'; else printf 'running\n'; fi
          ;;
        volume:inspect) return 1 ;;
        volume:create) touch "$create_marker"; return 1 ;;
        *) return 1 ;;
      esac
    }
    candidate_tag=edu-ai-lead-agent-backend:wechat-draft-aaaaaaaaaaaa
    preflight_services
    [[ "$weekly_candidate_count" == 0 && ! -e "$create_marker" ]]
  ) || fail "absent first-run weekly volume did not remain read-only/empty in preflight"

  set +e
  (
    set -e
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    # shellcheck source=wechat-draft-offline-release-operator.sh
    source "$OPERATOR"
    compose() {
      [[ "${1-}" == ps ]] && printf 'fixture-container\n'
      return 0
    }
    safe_job_counts() { printf '0:0:0\n'; }
    docker() {
      case "${1-}" in
        inspect)
          if [[ "$*" == *State.Health* ]]; then printf 'healthy\n'; else printf 'running\n'; fi
          ;;
        volume) return 0 ;;
        run) return 1 ;;
        *) return 1 ;;
      esac
    }
    candidate_tag=edu-ai-lead-agent-backend:wechat-draft-aaaaaaaaaaaa
    preflight_services
  ) >/dev/null 2>&1
  failure_rc=$?
  set -e
  ((failure_rc != 0)) || fail "volume helper failure passed production preflight"

  local created_root="${test_root}/created-volumes"
  mkdir -p "$created_root"
  (
    set -e
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    source "$OPERATOR"
    docker() {
      local action=${2-} volume=${*: -1}
      case "${1-}:${action}" in
        volume:inspect)
          [[ -e "$created_root/$volume" ]] || return 1
          if [[ "$*" == *--format* ]]; then printf '%s\n' "$volume"; fi
          ;;
        volume:create)
          touch "$created_root/$volume"
          printf '%s\n' "$volume"
          ;;
        *) return 1 ;;
      esac
    }
    ensure_draft_volumes
  ) || fail "post-source activation did not create the two controlled named volumes"
  [[ -e "$created_root/edu-ai-lead-agent_official_account_weekly_dag_output" ]]
  [[ -e "$created_root/edu-ai-lead-agent_wechat_mp_draft_artifacts" ]]
}

assert_recovery_arming_and_exact_marker_restore() {
  local app_root="${test_root}/recovery-app" backup="${test_root}/recovery-backup"
  (
    set -e
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    export WECHAT_DRAFT_OPERATOR_TEST_APP_DIR="$app_root"
    source "$OPERATOR"
    mkdir -p "$APP_DIR" "$backup/source.before" "$backup/root.before"
    backup_dir=$backup
    : >"$backup/dirs-backed-up"
    : >"$backup/dirs-installed"
    : >"$backup/root-existed"
    : >"$backup/root-installed"
    local name
    for name in "${MANAGED_DIRS[@]}"; do
      mkdir -p "$APP_DIR/$name" "$backup/source.before/$name"
      printf 'candidate\n' >"$APP_DIR/$name/identity"
      printf 'previous\n' >"$backup/source.before/$name/identity"
      printf '%s\n' "$name" >>"$backup/dirs-backed-up"
      printf '%s\n' "$name" >>"$backup/dirs-installed"
    done
    for name in "${MANAGED_FILES[@]}"; do
      printf 'candidate:%s\n' "$name" >"$APP_DIR/$name"
      printf '%s\n' "$name" >>"$backup/root-installed"
    done
    printf 'previous-compose\n' >"$backup/root.before/compose.yaml"
    printf '%s\n' compose.yaml >>"$backup/root-existed"
    printf 'candidate-commit\n' >"$APP_DIR/.release-commit"
    printf 'previous-commit\n' >"$backup/root.before/.release-commit"
    printf '%s\n' .release-commit >>"$backup/root-installed"
    printf '%s\n' .release-commit >>"$backup/root-existed"
    printf 'candidate-env\n' >"$APP_DIR/.env"
    printf 'previous-env\n' >"$backup/env.before"
    printf 'candidate-release\n' >"$APP_DIR/.release.env"
    source_activated=1
    restore_before_migration
    [[ "$(<"$APP_DIR/backend/identity")" == previous ]]
    [[ "$(<"$APP_DIR/compose.yaml")" == previous-compose ]]
    [[ "$(<"$APP_DIR/.release-commit")" == previous-commit ]]
    [[ "$(<"$APP_DIR/.env")" == previous-env ]]
    [[ ! -e "$APP_DIR/README.md" && ! -e "$APP_DIR/.release.env" ]]
  ) || fail "pre-migration recovery did not restore exact prior presence/markers"

  local mutation_marker="${test_root}/unarmed-mutation"
  (
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    export WECHAT_DRAFT_OPERATOR_TEST_APP_DIR="$app_root"
    source "$OPERATOR"
    recovery_armed=0
    completed=0
    restore_before_migration() { touch "$mutation_marker"; }
    compose() { touch "$mutation_marker"; }
    set +e
    false
    on_exit
    [[ ! -e "$mutation_marker" ]]
  ) || fail "pre-mutation rejection incorrectly armed recovery"
}

assert_optional_zero_effect_recovery() {
  local app_root="${test_root}/optional-recovery-app"
  local disabled="${test_root}/optional-disabled" ordinary_stopped="${test_root}/ordinary-stopped"
  (
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    export WECHAT_DRAFT_OPERATOR_TEST_APP_DIR="$app_root"
    source "$OPERATOR"
    migrated=1
    core_verified=1
    recovery_armed=1
    completed=0
    compose_with_draft() { return 0; }
    disable_draft_flags() { touch "$disabled"; }
    safe_job_counts() { printf '0:0:0\n'; }
    verify_candidate_application_services() { return 0; }
    compose() { touch "$ordinary_stopped"; return 0; }
    set +e
    false
    on_exit
    [[ -e "$disabled" && ! -e "$ordinary_stopped" ]]
  ) || fail "zero-effect optional failure did not retain the verified core services"

  rm -f "$disabled" "$ordinary_stopped"
  (
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    export WECHAT_DRAFT_OPERATOR_TEST_APP_DIR="$app_root"
    source "$OPERATOR"
    migrated=1
    core_verified=1
    recovery_armed=1
    completed=0
    compose_with_draft() { return 0; }
    disable_draft_flags() { touch "$disabled"; }
    safe_job_counts() { printf '1:3:1\n'; }
    verify_candidate_application_services() { return 0; }
    compose() { touch "$ordinary_stopped"; return 0; }
    set +e
    false
    on_exit
    [[ -e "$disabled" && -e "$ordinary_stopped" ]]
  ) || fail "non-zero optional effects did not enter the post-migration incident boundary"
}

assert_cutoff_is_next_monday() {
  local cutoff
  cutoff=$(
    export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
    # shellcheck source=wechat-draft-offline-release-operator.sh
    source "$OPERATOR"
    derive_minimum_week
    printf '%s\n' "$minimum_week"
  )
  python3 - "$cutoff" <<'PY'
from datetime import date, datetime
import sys
from zoneinfo import ZoneInfo

cutoff = date.fromisoformat(sys.argv[1])
today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
assert cutoff.weekday() == 0 and cutoff > today and (cutoff - today).days <= 7
PY
}

assert_validator_contract
assert_static_safety_contract
assert_source_metadata_binding
assert_builder_arguments_fail_closed
assert_fake_failure_boundaries
assert_absent_volume_preflight_and_controlled_creation
assert_recovery_arming_and_exact_marker_restore
assert_optional_zero_effect_recovery
assert_cutoff_is_next_monday
printf 'wechat_draft_offline_release_harness_ok\n'
