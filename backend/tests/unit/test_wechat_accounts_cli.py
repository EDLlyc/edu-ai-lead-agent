from __future__ import annotations

import pytest
from app import wechat_accounts_main


@pytest.mark.asyncio
async def test_import_env_refuses_without_the_wechat_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("WECHAT_MP_APP_ID", raising=False)
    monkeypatch.delenv("WECHAT_MP_APP_SECRET", raising=False)
    code = await wechat_accounts_main._main(["import-env", "--name", "赛先生"])
    assert code == 2
    assert "WECHAT_MP_APP_ID" in capsys.readouterr().err
