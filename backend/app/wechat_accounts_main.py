"""Bind the WeChat Official Account production already uses (env credentials) in the 运营后台.

    python -m app.wechat_accounts_main import-env --name 赛先生 [--topic 科学 --topic 教育]

Run it once in a one-off container that has `WECHAT_MP_APP_ID`, `WECHAT_MP_APP_SECRET` and
`ADMIN_SECRET_KEY`. The secret goes from the environment straight into the encrypted column:
nobody types or sees it. The account is verified with WeChat first.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from app.application.services.wechat_admin import WeChatAdminRejected, bind_account
from app.core.errors import AppError


async def _main(argv: Sequence[str]) -> int:
    from app.core.config import get_settings
    from app.infrastructure.db.session import create_engine, create_session_factory

    parser = argparse.ArgumentParser(prog="python -m app.wechat_accounts_main")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-env", help="绑定环境变量里的公众号")
    importer.add_argument("--name", required=True)
    importer.add_argument("--topic", action="append", default=[])
    args = parser.parse_args(argv)

    app_id = os.environ.get("WECHAT_MP_APP_ID", "").strip()
    app_secret = os.environ.get("WECHAT_MP_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        print("没有完成: 环境变量里没有 WECHAT_MP_APP_ID / WECHAT_MP_APP_SECRET", file=sys.stderr)
        return 2
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            account = await bind_account(
                session,
                settings=settings,
                http=None,
                actor_id=None,
                actor="cli",
                name=args.name,
                app_id=app_id,
                app_secret=app_secret,
                topics=list(args.topic),
                now=datetime.now(UTC),
            )
    except (WeChatAdminRejected, AppError) as error:
        print(f"没有完成: {error.message}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    print(f"已绑定 {account.name}（{account.app_id}，密钥末四位 {account.app_secret_last4}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
