from collections.abc import Mapping

import pytest
from app.core.config import Settings
from pydantic import SecretStr, ValidationError

_APP_ID = SecretStr("wx-test-app-id")
_APP_SECRET = SecretStr("test-app-secret")


def _settings(overrides: Mapping[str, object] | None = None) -> Settings:
    # Keep negative/default cases independent from a developer shell or local .env
    # that has the opt-in adapter enabled for manual testing.
    values: dict[str, object] = {
        "wechat_mp_enabled": False,
        "wechat_mp_draft_worker_enabled": False,
        "wechat_mp_draft_auto_enqueue_enabled": False,
        "wechat_mp_app_id": None,
        "wechat_mp_app_secret": None,
    }
    values.update(overrides or {})
    return Settings.model_validate(values)


def _enabled_settings(overrides: Mapping[str, object] | None = None) -> Settings:
    values: dict[str, object] = {
        "app_env": "development",
        "wechat_mp_enabled": True,
        "wechat_mp_app_id": _APP_ID,
        "wechat_mp_app_secret": _APP_SECRET,
        "wechat_mp_draft_worker_enabled": True,
    }
    values.update(overrides or {})
    return _settings(values)


def test_wechat_draft_automation_defaults_are_disabled_and_bounded() -> None:
    settings = _settings()

    assert settings.wechat_mp_draft_worker_enabled is False
    assert settings.wechat_mp_draft_auto_enqueue_enabled is False
    assert settings.wechat_mp_draft_poll_seconds == 2.0
    assert settings.wechat_mp_draft_lease_seconds == 300
    assert settings.wechat_mp_draft_heartbeat_seconds == 60
    assert settings.wechat_mp_draft_max_attempts == 3
    assert settings.wechat_mp_draft_retry_base_seconds == 30
    assert settings.wechat_mp_draft_weekly_inbox_root == ("output/official-account-weekly-inbox")
    assert settings.wechat_mp_draft_artifact_root == "output/wechat-mp-draft-artifacts"


def test_wechat_draft_worker_and_auto_enqueue_can_be_enabled_explicitly() -> None:
    settings = _enabled_settings({"wechat_mp_draft_auto_enqueue_enabled": True})

    assert settings.wechat_mp_draft_worker_enabled is True
    assert settings.wechat_mp_draft_auto_enqueue_enabled is True


def test_wechat_draft_auto_enqueue_requires_the_worker() -> None:
    with pytest.raises(ValidationError, match="automatic WeChat draft enqueue requires"):
        _settings(
            {
                "wechat_mp_draft_worker_enabled": False,
                "wechat_mp_draft_auto_enqueue_enabled": True,
            }
        )


def test_wechat_draft_worker_requires_the_existing_adapter() -> None:
    with pytest.raises(ValidationError, match="draft worker requires the draft adapter"):
        _settings(
            {
                "wechat_mp_enabled": False,
                "wechat_mp_draft_worker_enabled": True,
            }
        )


@pytest.mark.parametrize(
    "missing_credential",
    [
        {"wechat_mp_app_id": None},
        {"wechat_mp_app_secret": None},
        {"wechat_mp_app_id": SecretStr("invalid app id")},
        {"wechat_mp_app_secret": SecretStr("invalid\nsecret")},
    ],
)
def test_wechat_draft_worker_requires_valid_adapter_credentials(
    missing_credential: Mapping[str, object],
) -> None:
    with pytest.raises(ValidationError, match="requires AppID and AppSecret"):
        _enabled_settings(missing_credential)


def test_wechat_draft_worker_is_development_only() -> None:
    with pytest.raises(ValidationError, match="draft automation is development-only"):
        _enabled_settings({"app_env": "test"})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            {"wechat_mp_draft_heartbeat_seconds": 60, "wechat_mp_draft_lease_seconds": 60},
            "draft heartbeat must be shorter",
        ),
        (
            {
                "wechat_mp_request_timeout_seconds": 60,
                "wechat_mp_draft_lease_seconds": 60,
                "wechat_mp_draft_heartbeat_seconds": 30,
            },
            "draft lease must outlast",
        ),
    ],
)
def test_wechat_draft_worker_enforces_lease_timing(
    override: Mapping[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _settings(override)


@pytest.mark.parametrize(
    "override",
    [
        {"wechat_mp_draft_poll_seconds": 0},
        {"wechat_mp_draft_lease_seconds": 59},
        {"wechat_mp_draft_heartbeat_seconds": 4},
        {"wechat_mp_draft_max_attempts": 0},
        {"wechat_mp_draft_max_attempts": 11},
        {"wechat_mp_draft_retry_base_seconds": 0},
    ],
)
def test_wechat_draft_worker_bounds_are_enforced(override: Mapping[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(override)


@pytest.mark.parametrize(
    "field_name",
    ["wechat_mp_draft_weekly_inbox_root", "wechat_mp_draft_artifact_root"],
)
@pytest.mark.parametrize("invalid_path", ["", "   ", "output/weekly\nunsafe", "output/\x7funsafe"])
def test_wechat_draft_process_paths_reject_blank_or_control_characters(
    field_name: str,
    invalid_path: str,
) -> None:
    with pytest.raises(ValidationError, match="draft process paths"):
        _settings({field_name: invalid_path})


def test_wechat_draft_process_paths_remain_process_configuration() -> None:
    settings = _settings(
        {
            "wechat_mp_draft_weekly_inbox_root": "private output/weekly inbox",
            "wechat_mp_draft_artifact_root": "private output/draft artifacts",
        }
    )

    assert settings.wechat_mp_draft_weekly_inbox_root == "private output/weekly inbox"
    assert settings.wechat_mp_draft_artifact_root == "private output/draft artifacts"
