"""Run the ops assistant: a local chat page, or a one-shot conversation from the command line.

  # local page on http://127.0.0.1:4190 (needs the SSH tunnel and a model key in the environment)
  python -m app.ops_assistant_main --serve
  # non-interactive, e.g. in a one-off server container; edits are denied unless approved
  python -m app.ops_assistant_main --ask "今天中午的推送都发出去了吗？" [--approve-edits]

The database is read only through OPS_DATABASE_URL (the SELECT-only ops role, checked first).
The page listens on 127.0.0.1 only, accepts JSON only and checks the Host header, so another
website open in the browser cannot drive it.
"""

# ruff: noqa: RUF001, RUF002

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.services.ops_assistant import (
    OPS_ASSISTANT_VERSION,
    AssistantReply,
    AssistantSession,
    OpsAssistant,
    build_assistant_registry,
)

TZ = ZoneInfo("Asia/Shanghai")
PAGE = Path(__file__).with_name("ops_assistant_page.html")


class AssistantRuntime:
    """Owns the database engine, the HTTP client and one conversation at a time."""

    def __init__(self) -> None:
        self._engine: Any = None
        self._client: Any = None
        self._model: Any = None
        self._reader: Any = None
        self._factory: Any = None
        self.assistant: OpsAssistant | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> str:
        import httpx
        from pydantic import SecretStr
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.core.config import get_settings
        from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
        from app.infrastructure.ai.copy_repair import ZhipuRepairChatModel
        from app.infrastructure.db.ops_reader import (
            PostgresOpsReader,
            create_ops_engine,
            ops_database_url,
            verify_read_only_role,
        )

        settings = get_settings()
        if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
            raise RuntimeError("AI_PLATFORM_BASE_URL and AI_PLATFORM_API_KEY are required")
        self._engine = create_ops_engine(ops_database_url(os.environ))
        role = await verify_read_only_role(self._engine)
        self._factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._reader = PostgresOpsReader(self._factory)
        self._client = httpx.AsyncClient(follow_redirects=False)
        generator, _ = create_zhipu_copy_models(
            client=self._client,
            base_url=settings.ai_platform_base_url,
            api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
            model=settings.ai_chat_model,
            connect_timeout_seconds=settings.ai_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_read_timeout_seconds,
            total_timeout_seconds=settings.ai_total_timeout_seconds,
            concurrency=settings.ai_provider_concurrency,
            max_attempts=settings.ai_max_attempts,
            max_input_characters=settings.ai_max_input_characters,
            max_output_tokens=settings.copy_max_output_tokens,
            max_validation_corrections=settings.ai_max_validation_corrections,
        )
        self._model = ZhipuRepairChatModel(generator._client, max_output_tokens=1_500)
        self.reset()
        return role

    def reset(self) -> None:
        from app.infrastructure.db.copy_repair_workspace import load_repair_workspace

        session = AssistantSession()

        async def load(run_id: UUID) -> Any:
            return await load_repair_workspace(self._factory, run_id)

        self.assistant = OpsAssistant(
            self._model,
            build_assistant_registry(self._reader, session, load),
            session,
            today=datetime.now(UTC).astimezone(TZ).date(),
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        if self._engine is not None:
            await self._engine.dispose()


def reply_json(reply: AssistantReply) -> dict[str, Any]:
    return asdict(reply)


def create_app(runtime: AssistantRuntime, *, port: int) -> Any:
    from contextlib import asynccontextmanager

    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        role = await runtime.start()
        print(json.dumps({"event": "ops_assistant_ready", "role": role}), file=sys.stderr)
        yield
        await runtime.stop()

    app = FastAPI(title="Ops assistant", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next: Any) -> Any:
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.method == "POST" and not request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            return JSONResponse({"detail": "JSON only"}, status_code=415)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.post("/api/message")
    async def message(body: dict[str, Any]) -> dict[str, Any]:
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(422, "empty message")
        async with runtime.lock:
            assert runtime.assistant is not None
            if runtime.assistant.awaiting is not None:
                raise HTTPException(409, "answer the pending approval first")
            return reply_json(await runtime.assistant.send(text))

    @app.post("/api/decision")
    async def decision(body: dict[str, Any]) -> dict[str, Any]:
        async with runtime.lock:
            assert runtime.assistant is not None
            if runtime.assistant.awaiting is None:
                raise HTTPException(409, "nothing is waiting for approval")
            return reply_json(await runtime.assistant.decide(bool(body.get("approve"))))

    @app.post("/api/reset")
    async def reset(_: dict[str, Any]) -> dict[str, str]:
        async with runtime.lock:
            runtime.reset()
        return {"status": "reset", "version": OPS_ASSISTANT_VERSION}

    return app


async def ask(questions: list[str], *, approve_edits: bool) -> int:
    runtime = AssistantRuntime()
    try:
        role = await runtime.start()
        print(f"# ops assistant ({OPS_ASSISTANT_VERSION}), database role {role}\n")
        assert runtime.assistant is not None
        for question in questions:
            print(f"## 运营：{question}\n")
            reply = await runtime.assistant.send(question)
            while True:
                for step in reply.steps:
                    status = "ok" if step.ok else step.error_code
                    print(
                        f"- 工具 `{step.tool}` · {step.approval} · {status} · {step.duration_ms} ms"
                    )
                if reply.kind != "approval" or reply.approval is None:
                    break
                pending = reply.approval
                decision = "确认" if approve_edits else "拒绝"
                preview = json.dumps(pending.preview, ensure_ascii=False)
                print(f"- 待确认 `{pending.tool}`：{preview} → {decision}")
                reply = await runtime.assistant.decide(approve_edits)
            usage = f"输入 {reply.prompt_tokens} / 输出 {reply.completion_tokens} token"
            print(f"\n助手（{reply.kind}，{usage}）：\n")
            print((reply.text or "").strip() + "\n")
            if reply.draft and reply.draft.get("edits"):
                print("沙盒修改：" + "、".join(reply.draft["edits"]) + "\n")
    finally:
        await runtime.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="local chat page on 127.0.0.1")
    mode.add_argument("--ask", action="append", help="question; repeat for a conversation")
    parser.add_argument("--approve-edits", action="store_true", help="--ask mode: approve edits")
    parser.add_argument("--port", type=int, default=4190)
    args = parser.parse_args(argv)
    if args.ask:
        return asyncio.run(ask(args.ask, approve_edits=args.approve_edits))
    import uvicorn

    uvicorn.run(create_app(AssistantRuntime(), port=args.port), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
