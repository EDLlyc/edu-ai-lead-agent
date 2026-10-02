"""Local stdio MCP server for the copy repair tools.

It serves the exact registry the repair agent calls through function calling
(`build_repair_tool_registry`), so an operator's MCP client and the online agent use the same
tools, schemas, limits and refusals. The workspace is loaded once at start: the offline fixture
draft by default, or with `--copy-run-id` the newest draft of a copy run from a local development
database, or through the read-only ops role when OPS_DATABASE_URL is set. Edits stay in
this process's memory; nothing is written back.

Before an edit (replace_claim, drop_claim, rewrite_hook) the server asks the operator to confirm
through MCP form elicitation, showing the before/after of a dry run on a copy of the workspace.
Declining or cancelling returns `operator_declined` and leaves the draft unchanged. An edit the
tool would refuse anyway is not asked about. A client that cannot elicit gets today's behaviour,
marked `not_supported` in the result's `_meta`; `--require-confirmation` refuses it instead.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import copy
import os
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.agent_tools import AgentToolFailure
from app.application.services.copy_repair_tools import (
    REPAIR_TOOL_RULES,
    REPAIR_TOOLSET_VERSION,
    RepairWorkspace,
    build_repair_tool_registry,
    claim_by_id,
)
from app.core.agent_workbench_config import get_agent_workbench_settings
from app.core.config import get_settings
from app.infrastructure.agent_workbench_fixture import (
    FIXTURE_COPY_RUN_ID,
    build_fixture_material_draft,
    build_fixture_reader,
)
from app.infrastructure.db.copy_repair_workspace import brand_chunk_ids, load_repair_workspace
from app.infrastructure.db.ops_reader import (
    create_ops_engine,
    ops_database_url,
    verify_read_only_role,
)
from app.infrastructure.db.session import create_engine
from app.mcp_registry_server import (
    DEFAULT_MCP_CALL_BUDGET,
    CallLogger,
    ConfirmationMessage,
    RegistryMCPServer,
    call_budget_from_environment,
    stderr_json_logger,
)
from app.schemas.copy_generation import render_headline_hook_copy

MCP_SERVER_NAME = "edu-ai-copy-repair"
REPAIR_INSTRUCTIONS = (
    "修复一份被拦下的朋友圈草稿（工作稿只在本进程内存里，不会写回数据库）。"
    "先调用 check_draft 看有哪些 error，再按下面的规则修复：\n"
    + REPAIR_TOOL_RULES
    + "\n每个服务进程有调用次数上限。"
)


EDIT_TOOLS = ("replace_claim", "drop_claim", "rewrite_hook")
_PREVIEW_CHARACTERS = 300


def build_copy_repair_mcp_server(
    workspace: RepairWorkspace,
    *,
    call_budget: int = DEFAULT_MCP_CALL_BUDGET,
    call_logger: CallLogger | None = stderr_json_logger,
    require_confirmation: bool = False,
) -> RegistryMCPServer:
    return RegistryMCPServer(
        build_repair_tool_registry(workspace),
        name=MCP_SERVER_NAME,
        title="Copy Repair Tools",
        description="The copy repair agent's five tools over one in-memory draft workspace.",
        instructions=REPAIR_INSTRUCTIONS,
        version=REPAIR_TOOLSET_VERSION,
        call_budget=call_budget,
        call_logger=call_logger,
        confirmations=edit_confirmations(workspace),
        require_confirmation=require_confirmation,
    )


def edit_confirmations(workspace: RepairWorkspace) -> dict[str, ConfirmationMessage]:
    """For each edit tool: the before/after an operator confirms, from a dry run on a copy."""

    def for_tool(name: str) -> ConfirmationMessage:
        async def message(arguments: Mapping[str, Any]) -> str | None:
            trial = copy.deepcopy(workspace)
            try:
                result = await build_repair_tool_registry(trial).invoke(name, dict(arguments))
            except AgentToolFailure:
                return None  # invalid arguments: the real call refuses the same way
            if not getattr(result, "ok", False):
                return None  # the tool refuses this edit; nothing to confirm
            return describe_edit(name, dict(arguments), before=workspace, after=trial)

        return message

    return {name: for_tool(name) for name in EDIT_TOOLS}


def describe_edit(
    name: str, arguments: Mapping[str, Any], *, before: RepairWorkspace, after: RepairWorkspace
) -> str:
    def clip(text: str) -> str:
        return text if len(text) <= _PREVIEW_CHARACTERS else text[:_PREVIEW_CHARACTERS] + "…"

    header = "确认修改工作稿（只改本进程内存里的草稿，不会写回数据库）：\n"
    if name == "rewrite_hook":
        return (
            header
            + f"改写引导语\n改前：{clip(before.view().hook)}\n改后：{clip(after.view().hook)}"
        )
    claim_id = str(arguments.get("claim_id", ""))
    old = claim_by_id(before.draft, claim_id)
    old_text = clip(old.text) if old is not None else ""
    if name == "drop_claim":
        return header + f"删除 claim {claim_id}\n原文：{old_text}"
    new = claim_by_id(after.draft, claim_id)
    new_text = clip(new.text) if new is not None else ""
    return header + f"替换 claim {claim_id}\n改前：{old_text}\n改后：{new_text}"


# The rule version production copy runs store; the shared workbench fixture keeps an older one.
FIXTURE_RULE_VERSION = "preview-v13-headline-hook"
FIXTURE_HOOK = "人工智能走进课堂，正好和孩子聊聊怎样核对一条信息的来源🔍"


async def load_fixture_workspace() -> RepairWorkspace:
    """The offline fixture draft, rendered in today's headline-hook template and rules."""

    fixture = build_fixture_material_draft()
    context = await build_fixture_reader().load_copy_validation_context(
        copy_run_id=FIXTURE_COPY_RUN_ID, brand_chunk_ids=brand_chunk_ids(fixture)
    )
    evidence = context.topic.evidence[0]
    draft = fixture.model_copy(
        update={
            "copywriting": render_headline_hook_copy(
                f"{FIXTURE_HOOK}\n#赛先生科学 #人工智能教育 #科学思维",
                title=context.topic.title or "",
                source_name=evidence.source_name,
                source_url=evidence.source_url,
            )
        }
    )
    return RepairWorkspace(
        topic=context.topic,
        brand_context=context.brand_context,
        rule_version=FIXTURE_RULE_VERSION,
        draft=draft,
    )


async def load_run_workspace(
    copy_run_id: UUID, environ: Mapping[str, str] = os.environ
) -> RepairWorkspace:
    """The newest draft of one copy run, read in READ ONLY transactions.

    With OPS_DATABASE_URL set it reads through the SELECT-only ops role (production through an
    SSH tunnel) after checking that the role cannot write. Otherwise it reads the local
    development database, which needs explicit real-data enablement.
    """

    if environ.get("OPS_DATABASE_URL", "").strip():
        engine = create_ops_engine(ops_database_url(environ))
        needs_role_check = True
    else:
        workbench = get_agent_workbench_settings()
        settings = get_settings()
        if workbench.app_env != "development" or settings.app_env != "development":
            raise RuntimeError("the copy repair MCP server reads real runs only in development")
        if not workbench.agent_mcp_real_data_enabled:
            raise RuntimeError("real-data agent MCP requires explicit enablement")
        engine = create_engine(settings)
        needs_role_check = False
    try:
        if needs_role_check:
            await verify_read_only_role(engine)
        return await load_repair_workspace(
            async_sessionmaker(engine, expire_on_commit=False), copy_run_id
        )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copy repair tools over stdio MCP.")
    parser.add_argument("--copy-run-id", type=UUID, default=None)
    parser.add_argument(
        "--require-confirmation",
        action="store_true",
        help="refuse edits when the client cannot ask the operator (no form elicitation)",
    )
    args = parser.parse_args(argv)
    if get_agent_workbench_settings().app_env == "production":
        raise RuntimeError("the copy repair MCP server is local-only")
    workspace = asyncio.run(
        load_run_workspace(args.copy_run_id)
        if args.copy_run_id is not None
        else load_fixture_workspace()
    )
    build_copy_repair_mcp_server(
        workspace,
        call_budget=call_budget_from_environment(os.environ),
        require_confirmation=args.require_confirmation,
    ).run(transport="stdio")


if __name__ == "__main__":
    main()
