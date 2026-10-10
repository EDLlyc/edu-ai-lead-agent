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
        with self.assertRaisesRegex(RuntimeError, "existing_image_override"):
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
        with self.assertRaisesRegex(RuntimeError, "pipeline_pin_already_exists"):
            common.patch_release(result, common.BASE)
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
