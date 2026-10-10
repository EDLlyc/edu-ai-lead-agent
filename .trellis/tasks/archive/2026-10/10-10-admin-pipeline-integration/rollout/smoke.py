#!/usr/bin/env python3
"""Candidate acceptance with synthetic in-memory clients, no DB/provider/env/worker loop."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import importlib
import io
import json
import os
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

ENTRYPOINTS = (
    "app.official_account_worker_main",
    "app.official_account_weekly_dag_main",
    "app.governance_worker_main",
    "app.wechat_official_account_draft_main",
)


def verify_source(app_root: Path, evidence: Path) -> dict:
    manifest = json.loads((evidence / "manifest.json").read_text())
    for name, digest in manifest["build_helpers_sha256"].items():
        assert hashlib.sha256((evidence / name).read_bytes()).hexdigest() == digest
    assert (
        hashlib.sha256((evidence / "legacy-config.py").read_bytes()).hexdigest()
        == manifest["legacy_config_sha256"]
    )
    assert manifest["full_legacy_manifest"], (
        "production smoke requires full legacy file manifest"
    )
    paths = [
        *app_root.joinpath("app").rglob("*"),
        *app_root.joinpath("alembic").rglob("*"),
        app_root / "pyproject.toml",
        app_root / "alembic.ini",
    ]
    assert not any(path.is_symlink() for path in paths), "candidate application symlink"
    actual = {
        path.relative_to(app_root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(paths)
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    assert actual == manifest["expected_file_sha256"], (
        "candidate source/assets/migration manifest differs"
    )
    assert len(manifest["overlay_files"]) == len(manifest["overlay_sha256"]) == 12
    preserved = {
        name: value
        for name, value in manifest["legacy_files"].items()
        if name not in manifest["overlay_files"]
    }
    assert all(actual[name] == value for name, value in preserved.items())
    assert "app/infrastructure/db/models.py" in preserved
    return manifest


def model_fixtures(evidence: Path) -> None:
    from app.core import config
    from app.domain.model_api_keys import sealed_key_purpose
    from app.domain.secret_box import open_sealed, seal
    from app.infrastructure import model_api_keys_overlay as overlay
    from pydantic import SecretStr, ValidationError

    spec = importlib.util.spec_from_file_location(
        "admin_pipeline_legacy_settings", evidence / "legacy-config.py"
    )
    assert spec is not None and spec.loader is not None
    original = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = original
    spec.loader.exec_module(original)
    old_settings = original.Settings(_env_file=None)
    new_settings = config.Settings(_env_file=None)
    assert (
        new_settings.model_dump(exclude={"model_secret_key"})
        == old_settings.model_dump()
    )
    assert set(config.Settings.model_fields) == set(original.Settings.model_fields) | {
        "model_secret_key"
    }
    # These negative checks exercise the unchanged real validators on the derived Settings.
    for invalid in (
        {"app_port": -1},
        {"app_env": "production"},
        {"governance_enabled": True, "ai_provider_mode": "zhipu"},
    ):
        outcomes = []
        for settings_class in (original.Settings, config.Settings):
            try:
                settings_class(_env_file=None, **invalid)
                outcomes.append("accepted")
            except ValidationError as error:
                outcomes.append(
                    [
                        (item["type"], item["loc"], item["msg"])
                        for item in error.errors()
                    ]
                )
        assert outcomes[0] == outcomes[1]
    key = bytes(range(32))
    assert len(key) == 32
    master = base64.urlsafe_b64encode(key).decode()
    purpose = sealed_key_purpose("zhipu")
    ciphertext = seal("synthetic-console-value", key=key, purpose=purpose)
    assert (
        open_sealed(ciphertext, key=key, purpose=purpose) == "synthetic-console-value"
    )
    configured = new_settings.model_copy(
        update={
            "model_secret_key": SecretStr(master),
            "ai_platform_api_key": SecretStr("synthetic-env-value"),
        }
    )
    with patch.object(
        overlay, "read_latest_versions", return_value={"zhipu": (7, ciphertext)}
    ) as read:
        config.get_settings.cache_clear()
        with patch.object(config, "Settings", return_value=configured):
            loaded = config.get_settings()
            assert config.get_settings() is loaded
        read.assert_called_once_with(configured)
    assert loaded.ai_platform_api_key.get_secret_value() == "synthetic-console-value"
    assert overlay._loaded_versions == {"zhipu": 7} and overlay._load_errors == {}
    with patch.object(
        overlay, "read_latest_versions", return_value={"zhipu": (8, "v1:invalid")}
    ):
        failed = overlay.with_console_model_keys(configured)
    assert failed.ai_platform_api_key.get_secret_value() == "synthetic-env-value"
    assert overlay._loaded_versions == {} and overlay._attempted_versions == {
        "zhipu": 8
    }
    assert overlay._load_errors == {"zhipu": "key_unreadable"}
    assert not overlay.keys_changed(overlay._attempted_versions, {"zhipu": 8})
    assert overlay.keys_changed(overlay._attempted_versions, {"zhipu": 9})
    with patch.object(
        overlay, "read_latest_versions", return_value={"zhipu": (9, ciphertext)}
    ):
        failed = overlay.with_console_model_keys(
            configured.model_copy(update={"model_secret_key": SecretStr("invalid")})
        )
    assert failed.ai_platform_api_key.get_secret_value() == "synthetic-env-value"
    assert overlay._loaded_versions == {} and overlay._load_errors == {
        "zhipu": "encryption_key_invalid"
    }
    with patch.object(
        overlay, "read_latest_versions", return_value={"zhipu": (10, None)}
    ):
        restored = overlay.with_console_model_keys(configured)
    assert restored.ai_platform_api_key.get_secret_value() == "synthetic-env-value"
    assert overlay._loaded_versions == {"zhipu": 10} and overlay._load_errors == {}
    with patch.object(
        overlay,
        "read_latest_versions",
        side_effect=AssertionError("missing key must not query"),
    ):
        assert overlay.with_console_model_keys(new_settings) is new_settings
        assert not overlay.start_model_key_watch(new_settings, service="offline-smoke")
    config.get_settings.cache_clear()


async def template_fixtures() -> None:
    from app.application.ports.official_account_single_edition import SingleEdition
    from app.application.ports.wechat_official_account import (
        WeChatDraftCreated,
        WeChatInlineImage,
        WeChatMpTransientError,
        WeChatThumbMedia,
    )
    from app.application.services.wechat_official_account_draft import (
        WeChatOfficialAccountDraftOnlyService,
        WeChatPreparedDraft,
        WeChatPreparedMedia,
    )
    from app.application.services.wechat_single_edition_delivery import (
        JournaledSingleDraftClient,
        deliver_single,
    )
    from app.core.config import Settings
    from app.domain.official_account_layout_templates import (
        DEFAULT_LAYOUT_TEMPLATE_ID,
        apply_layout_template,
    )
    from app.domain.official_account_single_edition import (
        edition_window,
        single_edition_id,
    )
    from app.infrastructure.official_account_runtime import (
        official_account_identity_from_settings,
    )
    from app.infrastructure.wechat_official_account.manual_journal import (
        LocalManualDraftJournal,
    )

    account = "a" * 64
    day = date(2026, 9, 16)
    now = datetime(2026, 9, 16, 2, tzinfo=UTC)
    window = edition_window(day)
    edition = SingleEdition(
        id=single_edition_id(account, day),
        account=account,
        business_date=day,
        prepare_at=window.prepare_at,
        deliver_at=window.deliver_at,
        expires_at=window.expires_at,
        identity=official_account_identity_from_settings(
            Settings(_env_file=None), provider="zhipu", model="synthetic"
        ),
        max_attempts=3,
        retry_base_seconds=60,
        status="delivering",
        attempts={},
        available_at=now,
        lease_token=UUID(int=1),
        article_fingerprint="b" * 64,
        content_fingerprint="c" * 64,
    )
    body = '<section style="color:#0D57C8"><img src="assets/body.jpg"/></section>'
    prepared = WeChatPreparedDraft(
        role="application_case",
        article_fingerprint="b" * 64,
        content_fingerprint="c" * 64,
        title="Synthetic fixture",
        author="Fixture",
        digest="Offline fixture",
        content_source_url="https://education.news.cn/fixture.html",
        body_html=body,
        body_media=(
            WeChatPreparedMedia("assets/body.jpg", "image/jpeg", b"body", "body.jpg"),
        ),
        cover=WeChatPreparedMedia(
            "assets/cover.jpg", "image/jpeg", b"cover", "cover.jpg"
        ),
        need_open_comment=False,
        only_fans_can_comment=False,
    )
    assert apply_layout_template(body, None) is body
    assert apply_layout_template(body, "unknown") is body

    class Client:
        def __init__(self, fail_thumb=False):
            self.calls = []
            self.fail_thumb = fail_thumb

        async def upload_inline_image(self, *args):
            self.calls.append("inline")
            return WeChatInlineImage("https://mmbiz.qpic.cn/synthetic.jpg")

        async def upload_thumb(self, *args):
            self.calls.append("thumb")
            if self.fail_thumb:
                raise WeChatMpTransientError(
                    endpoint="material_add_thumb", provider_code=-1
                )
            return WeChatThumbMedia("synthetic_thumb")

        async def add_draft(self, article):
            self.calls.append("add")
            self.article = article
            return WeChatDraftCreated("synthetic_draft")

    class Repository:
        async def heartbeat(self, *args, **kwargs):
            return True

        async def save(self, value, **kwargs):
            self.value = value
            return True

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        # Selected colour and a retry after a later operator change retain the original pin.
        repo, first = Repository(), Client(fail_thumb=True)
        journal = LocalManualDraftJournal(root / "retry", account)
        try:
            await deliver_single(
                repository=repo,
                edition=edition,
                prepared=prepared,
                journal=journal,
                client=first,
                clock=lambda: now,
                layout_template_id="jade-green",
            )
            assert repo.value.status == "delivering"
            second = Client()
            await deliver_single(
                repository=repo,
                edition=repo.value,
                prepared=prepared,
                journal=journal,
                client=second,
                clock=lambda: now,
                layout_template_id="ink",
            )
            assert repo.value.status == "delivered"
            assert "color:#0B7A64" in second.article.content
            assert second.calls == ["thumb", "add"]
        finally:
            journal.close()
        # An actual old default-body add ACK without a layout pin still reconciles after expiry.
        journal = LocalManualDraftJournal(root / "legacy", account)
        try:
            client = Client()

            async def authorize():
                return True

            observed = JournaledSingleDraftClient(
                client=client,
                journal=journal,
                edition=edition,
                prepared=prepared,
                authorize=authorize,
                clock=lambda: now,
            )
            await WeChatOfficialAccountDraftOnlyService(
                client=observed, clock=lambda: now
            ).create_prepared(prepared)
            assert journal.read(f"single-{edition.id.hex}-layout.json") is None
            assert "color:#0D57C8" in client.article.content
            fresh = Client()
            await deliver_single(
                repository=repo,
                edition=edition,
                prepared=prepared,
                journal=journal,
                client=fresh,
                clock=lambda: now + timedelta(days=1),
                layout_template_id="jade-green",
            )
            assert repo.value.status == "delivered" and fresh.calls == []
            assert (
                journal.read(f"single-{edition.id.hex}-layout.json")["template"]
                == DEFAULT_LAYOUT_TEMPLATE_ID
            )
        finally:
            journal.close()
        journal = LocalManualDraftJournal(root / "invalid", account)
        try:
            journal.write(
                f"single-{edition.id.hex}-layout.json",
                {"version": "future-invalid", "template": "jade-green"},
            )
            fresh = Client()
            await deliver_single(
                repository=repo,
                edition=edition,
                prepared=prepared,
                journal=journal,
                client=fresh,
                clock=lambda: now,
                layout_template_id="jade-green",
            )
            assert fresh.calls == [] and repo.value.status == "outcome_unknown"
            assert repo.value.error_code == "single_journal_invalid"
        finally:
            journal.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=Path("/app"))
    parser.add_argument(
        "--evidence", type=Path, default=Path(__file__).resolve().parent
    )
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.app_root))
    manifest = verify_source(args.app_root, args.evidence)
    forbidden = Mock(
        side_effect=AssertionError(
            "offline smoke forbids external I/O or process signaling"
        )
    )
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        for name in (
            "socket.create_connection",
            "socket.socket.connect",
            "socket.getaddrinfo",
            "os.kill",
            "threading.Thread.start",
            "psycopg.connect",
        ):
            stack.enter_context(patch(name, forbidden))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        for name in ENTRYPOINTS:
            importlib.import_module(name)
        model_fixtures(args.evidence)
        asyncio.run(template_fixtures())
    forbidden.assert_not_called()
    print(
        json.dumps(
            {
                "status": "PASS",
                "legacy_image": manifest["legacy_image"],
                "source_commit": manifest["source_commit"],
                "overlay_files": 12,
                "verified_app_files": len(manifest["expected_app_sha256"]),
                "verified_total_files": len(manifest["expected_file_sha256"]),
                "imported_entrypoints": list(ENTRYPOINTS),
                "fixtures": [
                    "legacy-settings-defaults-and-validators",
                    "encrypted-key-valid-invalid-env-restore-cache",
                    "template-selected-retry-pin",
                    "pretemplate-default-ack-after-expiry",
                    "malformed-pin-no-provider",
                ],
                "provider_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
