# ruff: noqa: RUF001
from __future__ import annotations

import json
import signal

import httpx
import pytest
from app.core.config import Settings
from app.domain.model_api_keys import MODEL_KEY_PROVIDERS, sealed_key_purpose, valid_api_key
from app.domain.secret_box import new_key, parse_key, seal
from app.infrastructure import model_api_keys_overlay as overlay
from app.infrastructure.ai.model_key_probe import probe_model_key
from pydantic import SecretStr

ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/"
    "multimodal-embedding"
)


def _settings(**changes) -> Settings:
    values = {
        "ai_platform_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "visual_embedding_endpoint": SecretStr(ENDPOINT),
        "ai_platform_api_key": SecretStr("env-zhipu-key-0000"),
        "comfly_api_key": SecretStr("env-comfly-key-0000"),
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_every_provider_maps_to_a_real_settings_secret():
    settings = _settings()
    for provider in MODEL_KEY_PROVIDERS:
        assert provider.settings_field in Settings.model_fields
        value = getattr(settings, provider.settings_field)
        assert value is None or isinstance(value, SecretStr)
    assert valid_api_key("sk-0123456789")
    assert not valid_api_key("short")
    assert not valid_api_key("has space 123456")


@pytest.mark.asyncio
async def test_probes_send_one_small_request_and_scrub_the_key():
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, str(request.url), body))
        if request.headers["Authorization"] != "Bearer good-key-123456":
            return httpx.Response(401, json={"error": {"message": "令牌 bad-key-123456 无效"}})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        settings = _settings()
        ok = await probe_model_key("zhipu", "good-key-123456", settings=settings, http=http)
        assert ok.ok and ok.message == "连接成功"
        method, url, body = seen[-1]
        assert (method, url) == ("POST", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        assert body is not None and body["max_tokens"] == 1
        assert body["thinking"] == {"type": "disabled"}

        bad = await probe_model_key("zhipu", "bad-key-123456", settings=settings, http=http)
        assert not bad.ok
        assert bad.message == "key 不对，或者没有这个模型的权限：令牌 •••• 无效"

        comfly = await probe_model_key("comfly", "good-key-123456", settings=settings, http=http)
        assert comfly.ok and seen[-1][:2] == ("GET", "https://ai.comfly.org/v1/models")

        visual = await probe_model_key(
            "alibaba-visual", "good-key-123456", settings=settings, http=http
        )
        assert visual.ok and seen[-1][1] == ENDPOINT
        assert seen[-1][2]["input"] == {"contents": [{"text": "连接测试"}]}

    missing = await probe_model_key(
        "alibaba-visual", "good-key-123456", settings=_settings(visual_embedding_endpoint=None)
    )
    assert missing == missing.__class__(False, 0, "服务器没有配置图片向量的接口地址")


@pytest.mark.asyncio
async def test_a_timeout_is_reported_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await probe_model_key("comfly", "good-key-123456", settings=_settings(), http=http)
    assert not result.ok and "超时" in result.message


@pytest.fixture
def fresh_overlay(monkeypatch):
    monkeypatch.setattr(overlay, "_attempted_versions", None)
    monkeypatch.setattr(overlay, "_loaded_versions", None)
    monkeypatch.setattr(overlay, "_load_errors", None)
    monkeypatch.setattr(overlay, "_watch_started", False)
    return overlay


def test_without_the_model_secret_key_nothing_is_read(fresh_overlay, monkeypatch):
    def unexpected(_settings):
        raise AssertionError("must not touch the database")

    monkeypatch.setattr(fresh_overlay, "read_latest_versions", unexpected)
    settings = _settings()
    assert fresh_overlay.with_console_model_keys(settings) is settings
    assert fresh_overlay.start_model_key_watch(settings, service="content-worker") is False


def test_stored_keys_replace_env_keys_and_bad_ones_are_skipped(fresh_overlay, monkeypatch):
    key = new_key()
    sealed = seal("console-zhipu-9999", key=parse_key(key), purpose=sealed_key_purpose("zhipu"))
    # A ciphertext copied onto another provider must not open.
    misplaced = seal("console-x-1111", key=parse_key(key), purpose=sealed_key_purpose("zhipu"))
    monkeypatch.setattr(
        fresh_overlay,
        "read_latest_versions",
        lambda _settings: {
            "zhipu": (3, sealed),
            "comfly": (2, misplaced),
            "alibaba-visual": (1, None),
        },
    )
    settings = _settings(model_secret_key=SecretStr(key))
    applied = fresh_overlay.with_console_model_keys(settings)
    assert applied.ai_platform_api_key.get_secret_value() == "console-zhipu-9999"
    assert applied.comfly_api_key.get_secret_value() == "env-comfly-key-0000"
    assert fresh_overlay.loaded_versions() == {"zhipu": 3, "alibaba-visual": 1}
    assert fresh_overlay._attempted_versions == {"zhipu": 3, "comfly": 2, "alibaba-visual": 1}
    assert fresh_overlay._load_errors == {"comfly": "key_unreadable"}


def test_a_database_failure_keeps_the_environment(fresh_overlay, monkeypatch):
    def down(_settings):
        raise OSError("connection refused")

    monkeypatch.setattr(fresh_overlay, "read_latest_versions", down)
    settings = _settings(model_secret_key=SecretStr(new_key()))
    assert fresh_overlay.with_console_model_keys(settings) is settings
    assert fresh_overlay.loaded_versions() is None
    assert fresh_overlay._attempted_versions is None
    assert fresh_overlay._load_errors == {
        provider.id: "configuration_unavailable" for provider in MODEL_KEY_PROVIDERS
    }


def test_keys_changed():
    assert not overlay.keys_changed(None, {})
    assert overlay.keys_changed(None, {"zhipu": 1})
    assert not overlay.keys_changed({"zhipu": 1}, {"zhipu": 1})
    assert overlay.keys_changed({"zhipu": 1}, {"zhipu": 2})
    assert overlay.keys_changed({}, {"comfly": 1})


def test_the_watch_reports_then_sends_sigterm_after_a_change(fresh_overlay, monkeypatch):
    monkeypatch.setattr(fresh_overlay, "_attempted_versions", {"zhipu": 1})
    monkeypatch.setattr(fresh_overlay, "_loaded_versions", {"zhipu": 1})
    monkeypatch.setattr(fresh_overlay, "_started_at", fresh_overlay.time.monotonic() - 1_000)
    reads = iter([{"zhipu": 1}, OSError("down"), {"zhipu": 2}])
    beats: list[tuple[str, str]] = []

    def beat(_settings, service, host):
        beats.append((service, host))
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value

    sleeps: list[float] = []
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(fresh_overlay, "beat_and_read", beat)
    monkeypatch.setattr(fresh_overlay.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(fresh_overlay.time, "sleep", sleeps.append)
    monkeypatch.setattr(fresh_overlay.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    fresh_overlay._watch(_settings(model_secret_key=SecretStr(new_key())), "content-worker")
    assert kills == [(fresh_overlay.os.getpid(), signal.SIGTERM)]
    assert [service for service, _host in beats] == ["content-worker"] * 3
    # Unchanged, then a failed read: one poll interval each; the change waits out no uptime.
    assert sleeps == [overlay.WATCH_POLL_SECONDS, overlay.WATCH_POLL_SECONDS, 0.0]


def test_a_young_process_waits_before_restarting(fresh_overlay, monkeypatch):
    monkeypatch.setattr(fresh_overlay, "_attempted_versions", {})
    monkeypatch.setattr(fresh_overlay, "_loaded_versions", {})
    monkeypatch.setattr(fresh_overlay, "_started_at", fresh_overlay.time.monotonic())
    monkeypatch.setattr(fresh_overlay, "beat_and_read", lambda *_args: {"comfly": 1})
    monkeypatch.setattr(fresh_overlay.random, "uniform", lambda _a, _b: 5.0)
    sleeps: list[float] = []
    monkeypatch.setattr(fresh_overlay.time, "sleep", sleeps.append)
    monkeypatch.setattr(fresh_overlay.os, "kill", lambda pid, sig: None)
    fresh_overlay._watch(_settings(model_secret_key=SecretStr(new_key())), "governance-worker")
    assert len(sleeps) == 1
    assert overlay.WATCH_MIN_UPTIME_SECONDS + 4 < sleeps[0] <= overlay.WATCH_MIN_UPTIME_SECONDS + 5


@pytest.mark.parametrize("configured", ["invalid-encryption-key", None])
def test_bad_ciphertext_is_not_restarted_again_until_a_new_version(
    fresh_overlay, monkeypatch, configured
):
    # Invalid configured key and ciphertext failures both retain env without a restart storm.
    monkeypatch.setattr(
        fresh_overlay, "read_latest_versions", lambda _settings: {"zhipu": (4, "broken-ciphertext")}
    )
    settings = _settings(model_secret_key=SecretStr(configured or new_key()))
    applied = fresh_overlay.with_console_model_keys(settings)
    assert applied.ai_platform_api_key.get_secret_value() == "env-zhipu-key-0000"
    assert fresh_overlay.loaded_versions() == {}
    assert fresh_overlay._load_errors == {
        "zhipu": "encryption_key_invalid" if configured else "key_unreadable"
    }
    reads = iter([{"zhipu": 4}, {"zhipu": 4}, {"zhipu": 5}])
    monkeypatch.setattr(fresh_overlay, "beat_and_read", lambda *_args: next(reads))
    monkeypatch.setattr(fresh_overlay, "_started_at", fresh_overlay.time.monotonic() - 1_000)
    monkeypatch.setattr(fresh_overlay.random, "uniform", lambda _a, _b: 0.0)
    sleeps: list[float] = []
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(fresh_overlay.time, "sleep", sleeps.append)
    monkeypatch.setattr(fresh_overlay.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    fresh_overlay._watch(settings, "content-worker")
    assert sleeps == [overlay.WATCH_POLL_SECONDS, overlay.WATCH_POLL_SECONDS, 0.0]
    assert kills == [(fresh_overlay.os.getpid(), signal.SIGTERM)]


def test_explicit_env_restore_is_loaded_even_with_invalid_encryption_key(
    fresh_overlay, monkeypatch
):
    monkeypatch.setattr(
        fresh_overlay, "read_latest_versions", lambda _settings: {"zhipu": (5, None)}
    )
    settings = _settings(model_secret_key=SecretStr("invalid-key"))
    assert (
        fresh_overlay.with_console_model_keys(settings).ai_platform_api_key.get_secret_value()
        == "env-zhipu-key-0000"
    )
    assert fresh_overlay.loaded_versions() == {"zhipu": 5}
    assert fresh_overlay._load_errors == {}


def test_a_recovered_database_triggers_reload_after_failed_startup(fresh_overlay, monkeypatch):
    def down(_settings):
        raise OSError("private-connection-detail")

    monkeypatch.setattr(fresh_overlay, "read_latest_versions", down)
    settings = _settings(model_secret_key=SecretStr(new_key()))
    fresh_overlay.with_console_model_keys(settings)
    monkeypatch.setattr(fresh_overlay, "beat_and_read", lambda *_args: {"comfly": 1})
    monkeypatch.setattr(fresh_overlay.time, "sleep", lambda _seconds: None)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(fresh_overlay.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    fresh_overlay._watch(settings, "content-worker")
    assert kills == [(fresh_overlay.os.getpid(), signal.SIGTERM)]
