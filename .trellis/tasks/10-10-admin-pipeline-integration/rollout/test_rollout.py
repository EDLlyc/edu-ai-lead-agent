"""Isolated safety regressions; no Docker/SSH/provider access is performed."""

import copy
import datetime as dt
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import common
import cutover
import postcheck


class RolloutTests(unittest.TestCase):
    def fixture_compose(self):
        return (
            "x-app-runtime: &app-runtime\n  image: ${APP_IMAGE:-old}\nservices:\n"
            + "".join(
                "  "
                + service
                + ':\n    <<: *app-runtime\n    environment:\n      <<: *backend-environment\n      PRESERVE: same\n    command: ["python"]\n\n'
                for service in common.TARGETS + ["unrelated"]
            )
        )

    def fixture_render(self):
        services = {
            service: {
                "image": "old-admin-global",
                "environment": {"PRESERVE": "unchanged"},
                "command": ["python"],
            }
            for service in common.TARGETS + ["unrelated", "acquisition-api"]
        }
        services["acquisition-api"]["environment"]["MODEL_SECRET_KEY"] = (
            "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg"
        )
        return {"services": services, "volumes": {"keep": {}}, "name": "project"}

    def test_patch_only_four_images_and_three_secret_mappings(self):
        original = self.fixture_compose()
        result = common.patch_compose(original)
        self.assertEqual(result.count("image: ${ADMIN_PIPELINE_IMAGE"), 4)
        self.assertEqual(result.count("      MODEL_SECRET_KEY: "), 3)
        self.assertIn("  unrelated:\n    <<: *app-runtime\n    environment:", result)
        draft = result.split("  " + common.DRAFT + ":\n")[1].split("\n  unrelated:")[0]
        self.assertNotIn("MODEL_SECRET_KEY", draft)
        with self.assertRaisesRegex(RuntimeError, "existing_model_mapping"):
            common.patch_compose(result)
        with self.assertRaisesRegex(RuntimeError, "service_block_not_unique"):
            common.patch_compose(
                original.replace("  governance-worker:\n", "  renamed:\n")
            )

    def test_release_preserves_app_image_and_other_bytes(self):
        original = "# keep\nAPP_IMAGE=admin-current\nSOME_SETTING=value\n"
        result = common.patch_release(original, common.BASE)
        self.assertTrue(result.startswith(original))
        self.assertEqual(result.count("APP_IMAGE=admin-current"), 1)
        self.assertEqual(common.patch_release(result, common.BASE), result)
        with self.assertRaisesRegex(RuntimeError, "pipeline_pin_not_original_base"):
            common.patch_release(
                result.replace(common.BASE, "sha256:" + "1" * 64), common.BASE
            )
        with self.assertRaisesRegex(RuntimeError, "invalid_image"):
            common.patch_release(original, "floating-tag")

    def test_render_rejects_unrelated_value_or_secret_change(self):
        before = self.fixture_render()
        after = copy.deepcopy(before)
        for service in common.TARGETS:
            after["services"][service]["image"] = (
                "offline.local/edu-ai/edu-ai-lead-agent-backend@" + common.BASE
            )
            if service in common.MODELS:
                after["services"][service]["environment"]["MODEL_SECRET_KEY"] = before[
                    "services"
                ]["acquisition-api"]["environment"]["MODEL_SECRET_KEY"]
        self.assertTrue(
            common.verify_render_patch(before, after, common.BASE)[
                "render_allowlist_verified"
            ]
        )
        for mutate in [
            lambda value: value["services"]["unrelated"]["environment"].update(
                PRESERVE="drift"
            ),
            lambda value: value["services"][common.DRAFT]["environment"].update(
                MODEL_SECRET_KEY="wrong"
            ),
            lambda value: value["volumes"].update(new={}),
        ]:
            wrong = copy.deepcopy(after)
            mutate(wrong)
            with self.assertRaisesRegex(RuntimeError, "outside_allowlist"):
                common.verify_render_patch(before, wrong, common.BASE)

    def test_recreation_admission_detects_prior_shared_env_drift(self):
        image = {
            "Env": ["PATH=/base", "BAKED_ONLY=keep"],
            "Cmd": ["python"],
            "Entrypoint": None,
            "WorkingDir": "/app",
            "User": "",
        }
        env = {
            "PATH": "/base",
            "BAKED_ONLY": "keep",
            "CONTENT_SCORING_VERSION": common.PRESERVED_LEGACY_ENV[
                "CONTENT_SCORING_VERSION"
            ],
            "PRIVATE_KEY": "never-print-this",
        }
        item = {
            "Config": dict(image, Env=[key + "=" + value for key, value in env.items()])
        }
        rendered = {
            "environment": {
                "CONTENT_SCORING_VERSION": "new-unsupported-global-value",
                "PRIVATE_KEY": "never-print-this",
            },
            "command": ["python"],
        }
        with self.assertRaisesRegex(
            RuntimeError, "effective_environment_drift:CONTENT_SCORING_VERSION"
        ) as error:
            common.verify_effective_runtime(item, rendered, image)
        self.assertNotIn("never-print", str(error.exception))
        rendered["environment"]["CONTENT_SCORING_VERSION"] = env[
            "CONTENT_SCORING_VERSION"
        ]
        self.assertTrue(
            common.verify_effective_runtime(item, rendered, image)[
                "environment_matches"
            ]
        )
        for change in [
            dict(rendered["environment"], ADDED="new"),
            {"CONTENT_SCORING_VERSION": env["CONTENT_SCORING_VERSION"]},
            dict(rendered["environment"], PRIVATE_KEY="changed-private"),
        ]:
            with self.assertRaisesRegex(RuntimeError, "effective_environment_drift"):
                common.verify_effective_runtime(
                    item, dict(rendered, environment=change), image
                )
        with self.assertRaisesRegex(RuntimeError, "effective_runtime_drift:Cmd"):
            common.verify_effective_runtime(
                item, dict(rendered, command=["wrong"]), image
            )

    def test_restored_baseline_cutover_and_rollback_preserve_exact_overrides(self):
        original = self.fixture_compose()
        restored = original
        for service in common.TARGETS:
            header = "  " + service + ":\n    <<: *app-runtime\n"
            restored = restored.replace(header, header + common.PIPELINE_IMAGE_LINE)
            start = restored.index("  " + service + ":\n")
            env_at = restored.index("    environment:\n", start) + len(
                "    environment:\n"
            )
            preserved = "".join(
                "      " + key + ": " + value + "\n"
                for key, value in common.PRESERVED_LEGACY_ENV.items()
            )
            restored = restored[:env_at] + preserved + restored[env_at:]
        patched = common.patch_compose(restored)
        self.assertEqual(patched.count(common.PIPELINE_IMAGE_LINE), 4)
        self.assertEqual(patched.count("      MODEL_SECRET_KEY: "), 3)
        self.assertEqual(
            patched.replace("      MODEL_SECRET_KEY: ${MODEL_SECRET_KEY:-}\n", ""),
            restored,
        )
        for key, value in common.PRESERVED_LEGACY_ENV.items():
            self.assertEqual(patched.count("      " + key + ": " + value + "\n"), 4)
        release = common.patch_release("APP_IMAGE=admin-current\n", common.BASE)
        candidate = "sha256:" + "a" * 64
        new_release = common.patch_release(release, candidate)
        self.assertIn("APP_IMAGE=admin-current\n", new_release)
        self.assertEqual(common.patch_release(release, common.BASE), release)
        with self.assertRaisesRegex(RuntimeError, "pipeline_pin_not_original_base"):
            common.patch_release(
                release + "ADMIN_PIPELINE_IMAGE=duplicate\n", candidate
            )
        with self.assertRaisesRegex(RuntimeError, "existing_image_override"):
            common.patch_compose(
                restored.replace(common.PIPELINE_IMAGE_LINE, "    image: other\n", 1)
            )
        with self.assertRaisesRegex(RuntimeError, "partial_pipeline_override"):
            common.patch_compose(restored.replace(common.PIPELINE_IMAGE_LINE, "", 1))

    def test_cutover_recreation_admission_precedes_any_stop(self):
        import json

        candidate = {
            "image": "sha256:" + "a" * 64,
            "legacy_image": common.BASE,
            "source_commit": "fixture-commit",
            "manifest": "manifest.json",
        }
        manifest = {
            "source_commit": "fixture-commit",
            "legacy_image": common.BASE,
            "overlay_sha256": {str(i): "hash" for i in range(12)},
        }
        image_config = {
            "Env": [],
            "Cmd": ["python"],
            "Entrypoint": None,
            "WorkingDir": "/app",
            "User": "",
        }
        items = {
            common.name(service): {
                "Id": service,
                "Config": dict(
                    image_config,
                    Env=[
                        key + "=" + value
                        for key, value in common.PRESERVED_LEGACY_ENV.items()
                    ],
                ),
            }
            for service in common.TARGETS
        }
        rendered = {
            "services": {
                service: {
                    "environment": dict(
                        common.PRESERVED_LEGACY_ENV,
                        CONTENT_SCORING_VERSION="unsupported-new-global",
                    )
                }
                for service in common.TARGETS
            }
        }
        before = {
            "at": common.now().isoformat(),
            "config_hashes": {"fixture": "stable"},
            "containers": {key: {"id": value["Id"]} for key, value in items.items()},
            "state": {},
            "volumes": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            for filename, value in [
                ("candidate.json", candidate),
                ("manifest.json", manifest),
                ("preflight-state.json", before),
            ]:
                (stage / filename).write_text(json.dumps(value))
            with (
                patch.object(cutover, "STAGE", stage),
                patch.object(cutover, "quiet_window"),
                patch.object(
                    cutover,
                    "run",
                    return_value=json.dumps([{"Id": candidate["image"]}]),
                ),
                patch.object(
                    common, "run", return_value=json.dumps([{"Config": image_config}])
                ),
                patch.object(
                    cutover, "config_hashes", return_value=before["config_hashes"]
                ),
                patch.object(cutover, "inspect", return_value=items),
                patch.object(
                    cutover,
                    "safe_container",
                    side_effect=lambda item: {"id": item["Id"]},
                ),
                patch.object(cutover, "mode_check"),
                patch.object(cutover, "db_state", return_value={}),
                patch.object(cutover, "idle"),
                patch.object(cutover, "render", return_value=rendered),
                patch.object(cutover, "graceful_stop") as stop,
                patch.object(cutover, "start") as start,
                patch.object(cutover, "atomic_text") as mutate,
                self.assertRaisesRegex(
                    RuntimeError, "effective_environment_drift:CONTENT_SCORING_VERSION"
                ),
            ):
                cutover.cutover()
            stop.assert_not_called()
            start.assert_not_called()
            mutate.assert_not_called()

    def test_unverified_old_recovery_backup_rejected_before_stop(self):
        import json

        with tempfile.TemporaryDirectory(prefix="admin-pipeline-test-") as temporary:
            backup = Path(temporary)
            (backup / "before.json").write_text(json.dumps({"containers": {}}))

            def local_path(value):
                return (
                    backup.parent
                    if str(value) == "/var/backups/edu-ai"
                    else Path(value)
                )

            with (
                patch.object(cutover, "Path", side_effect=local_path),
                patch.object(cutover, "graceful_stop") as stop,
                self.assertRaisesRegex(
                    RuntimeError, "recovery_baseline_effective_runtime_unverified"
                ),
            ):
                cutover.recover(backup)
            stop.assert_not_called()

    def test_archive_verifies_content_metadata_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "volume"
            root.mkdir()
            (root / "nested").mkdir()
            (root / "nested" / "journal.json").write_text('{"private": "fixture-only"}')
            (root / "empty").write_bytes(b"")
            expected = common.content_manifest(root)
            archive = Path(temporary) / "volume.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(root, arcname=".")
            receipt = cutover.verify_archive(archive, expected)
            self.assertEqual(receipt["files"], 2)
            changed = copy.deepcopy(expected)
            changed["empty"]["sha256"] = "wrong"
            with self.assertRaisesRegex(RuntimeError, "manifest_mismatch"):
                cutover.verify_archive(archive, changed)
            with tarfile.open(archive, "w:gz") as stream:
                member = tarfile.TarInfo("../escape")
                member.size = 1
                stream.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(RuntimeError, "unsafe_tar_path"):
                cutover.verify_archive(archive, {})

    def test_archive_symlink_and_volume_symlink_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link").symlink_to("/etc/hostname")
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                common.content_manifest(root)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                member = tarfile.TarInfo("link")
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/hostname"
                stream.addfile(member)
            with self.assertRaisesRegex(RuntimeError, "unsupported_tar_member"):
                cutover.verify_archive(archive, {})

    def test_database_backup_requires_valid_restore_listing(self):
        def dump_then_bad_listing(args, **kwargs):
            if "pg_dump" in args[-1]:
                kwargs["stdout"].write(b"fake dump" * 200)
                return subprocess.CompletedProcess(args, 0, stderr=b"")
            return subprocess.CompletedProcess(args, 0, stdout=b"no data", stderr=b"")

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(cutover.subprocess, "run", side_effect=dump_then_bad_listing),
            self.assertRaisesRegex(RuntimeError, "restore_listing_failed"),
        ):
            cutover.backup_database(Path(temporary))

    def fixture_state(self):
        return {
            key: {"digest": "stable", "count": 1}
            for key in [
                "official_account_single_editions",
                "official_account_draft_owners",
                "wechat_mp_draft_jobs",
                "wechat_mp_draft_items",
                "wechat_mp_draft_attempts",
            ]
        }

    def test_rollback_allows_only_unchanged_pin_free_state(self):
        frozen = self.fixture_state()
        files = {"manual-v1/claim.json": {"sha256": "old"}}
        self.assertTrue(
            common.rollback_draft_safe(frozen, copy.deepcopy(frozen), files, files)
        )
        modified = copy.deepcopy(frozen)
        modified["official_account_single_editions"]["digest"] = "uncertain-new-write"
        self.assertFalse(common.rollback_draft_safe(frozen, modified, files, files))
        changed_files = dict(
            files, **{"single-new-layout.json": {"sha256": "nondefault"}}
        )
        self.assertFalse(
            common.rollback_draft_safe(frozen, frozen, files, changed_files)
        )
        self.assertFalse(
            common.rollback_draft_safe(frozen, frozen, changed_files, changed_files)
        )

    def test_rollback_query_or_journal_failure_keeps_draft_stopped(self):
        before = {"volumes": {"draft": {"source": "/fixture", "files": {}}}}
        with patch.object(cutover, "db_state", side_effect=RuntimeError("db failed")):
            self.assertEqual(
                cutover.recovery_decision(self.fixture_state(), before),
                (False, "state_verification_failed"),
            )
        with (
            patch.object(cutover, "db_state", return_value=self.fixture_state()),
            patch.object(
                cutover, "content_manifest", side_effect=OSError("unreadable")
            ),
        ):
            self.assertEqual(
                cutover.recovery_decision(self.fixture_state(), before),
                (False, "state_verification_failed"),
            )

    def fixture_heartbeat(self):
        started = dt.datetime(2026, 10, 10, 8, 0, tzinfo=dt.timezone.utc)
        item = {
            "Id": "current-container-id",
            "Config": {"Hostname": "current-host"},
            "State": {"StartedAt": started.isoformat()},
        }
        beat = {
            "service": "worker",
            "host": "current-host",
            "versions": {},
            "load_errors": {},
            "started_at": (started + dt.timedelta(seconds=1)).isoformat(),
            "seen_at": (started + dt.timedelta(seconds=61)).isoformat(),
        }
        return item, beat, started + dt.timedelta(seconds=65)

    def test_heartbeat_binds_current_host_start_and_verified_versions(self):
        item, beat, instant = self.fixture_heartbeat()
        self.assertEqual(
            postcheck.check_heartbeat("worker", item, beat, {}, instant)["host"],
            "current-host",
        )
        mutations = [
            {"host": "previous-container"},
            {"started_at": (instant - dt.timedelta(hours=2)).isoformat()},
            {"seen_at": (instant - dt.timedelta(minutes=6)).isoformat()},
            {"load_errors": None},
            {"versions": None},
            {"versions": {"zhipu": 2}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                postcheck.check_heartbeat(
                    "worker", item, dict(beat, **mutation), {}, instant
                )

    def test_graceful_stop_never_forces_sigkill(self):
        captured = []
        with (
            patch.object(
                cutover, "run", side_effect=lambda args, **kwargs: captured.append(args)
            ),
            patch.object(
                cutover,
                "inspect",
                return_value={"worker": {"State": {"Running": False}}},
            ),
        ):
            cutover.graceful_stop(common.TARGETS)
        self.assertEqual(captured[0][-6:-4], ["--timeout", "-1"])

    def test_admission_rejects_even_future_runnable_and_unexpired_unknown(self):
        state = {
            "schema": {"version": "20261010_0061"},
            "active_single": {"count": 0},
            "active_current_single_unknown": {"count": 0},
            "historical_unknowns": {"count": 5},
        }
        common.idle(state)
        for key in ["active_single", "active_current_single_unknown"]:
            wrong = copy.deepcopy(state)
            wrong[key]["count"] = 1
            with self.assertRaisesRegex(RuntimeError, "not_idle"):
                common.idle(wrong)

    def test_command_failure_does_not_expose_captured_secrets(self):
        completed = subprocess.CompletedProcess(
            ["docker"],
            1,
            stdout="SECRET=fixture-private",
            stderr="PASSWORD=fixture-private",
        )
        with (
            patch.object(common.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(RuntimeError, "^command_failed_docker$"),
        ):
            common.run(["docker", "inspect", "fixture"])

    def test_state_queries_use_repeatable_read_and_only_safe_outputs(self):
        captured = {}

        def stub(queries):
            captured.update(queries)
            return {}

        with patch.object(common, "sql_json", side_effect=stub):
            common.db_state()
        self.assertIn("j-'updated_at'", captured["official_account_draft_owners"])
        self.assertIn("key_kind'='history'", captured["official_account_draft_owners"])
        self.assertIn("expires_at > now()", captured["active_current_single_unknown"])
        self.assertIn(
            "r.status NOT IN ('terminal_failed','ready')", captured["active_weekly"]
        )
        self.assertIn("execution_agent_allocations", captured["active_allocations"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
