import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AUDIT_PAGE_SIZE,
  AdminSessionExpiredError,
  type AdminApi,
  type AdminAuditEvent,
  type AuditQuery,
} from "./api";
import { AuditLogPage } from "./AuditLogPage";

function event(
  index: number,
  action: string,
  detail: Record<string, unknown> = {},
) {
  return {
    id: `00000000-0000-0000-0000-${index.toString().padStart(12, "0")}`,
    occurred_at: new Date(
      Date.UTC(2026, 9, 9, 2, 0) - index * 60_000,
    ).toISOString(),
    username: "liyuchen",
    action,
    target_type: null,
    target_id: "wang",
    detail,
  } satisfies AdminAuditEvent;
}

function api(auditEvents: AdminApi["auditEvents"]): AdminApi {
  return {
    me: vi.fn(() => Promise.resolve(null)),
    login: vi.fn(() => Promise.reject(new Error("unused"))),
    logout: vi.fn(() => Promise.resolve()),
    auditEvents,
    changePassword: vi.fn(() => Promise.resolve(0)),
  };
}

function pendingPage() {
  let resolve!: (events: readonly AdminAuditEvent[]) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<readonly AdminAuditEvent[]>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function settleRequest(settle: () => void) {
  await act(async () => {
    settle();
    await Promise.resolve();
  });
}

function fullPage() {
  return Array.from({ length: AUDIT_PAGE_SIZE }, (_, index) =>
    event(index, "source.updated", { title: `新闻源记录 ${index + 1}` }),
  );
}

describe("操作记录", () => {
  it("filters by kind and pages back", async () => {
    const user = userEvent.setup();
    const firstPage = Array.from({ length: AUDIT_PAGE_SIZE }, (_, index) =>
      event(index, "auth.login"),
    );
    const older = [event(AUDIT_PAGE_SIZE, "auth.logout")];
    const accounts = [
      event(1, "user.updated", {
        changes: {
          role: { from: "editor", to: "owner" },
          display_name: { from: "王", to: "王老师" },
        },
      }),
    ];
    const auditEvents = vi.fn((query: AuditQuery = {}) => {
      if (query.kind === "user") return Promise.resolve(accounts);
      return Promise.resolve(query.before === undefined ? firstPage : older);
    });
    render(<AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />);

    expect(await screen.findAllByRole("row")).toHaveLength(AUDIT_PAGE_SIZE + 1);
    await user.click(screen.getByRole("button", { name: "加载更早的记录" }));
    await waitFor(() =>
      expect(screen.getAllByRole("row")).toHaveLength(AUDIT_PAGE_SIZE + 2),
    );
    expect(auditEvents).toHaveBeenLastCalledWith({
      before: firstPage[AUDIT_PAGE_SIZE - 1]!.occurred_at,
    });
    expect(screen.getByText("没有更早的记录了。")).toBeInTheDocument();

    const filters = screen.getByRole("group", { name: "按类型筛选" });
    await user.click(within(filters).getByRole("button", { name: "账号" }));
    expect(
      within(filters).getByRole("button", { name: "账号" }),
    ).toHaveAttribute("aria-pressed", "true");
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("修改账号");
    expect(rows[1]).toHaveTextContent(
      "显示名：王 → 王老师；角色：编辑 → 管理员",
    );
    expect(auditEvents).toHaveBeenLastCalledWith({ kind: "user" });
  });

  it.each(["filter", "refresh"] as const)(
    "ignores old pagination success after %s without replacing current rows",
    async (transition) => {
      const user = userEvent.setup();
      const older = pendingPage();
      const auditEvents = vi
        .fn<AdminApi["auditEvents"]>()
        .mockResolvedValueOnce(fullPage())
        .mockReturnValueOnce(older.promise)
        .mockResolvedValueOnce([
          event(100, "auth.login", { title: "当前记录" }),
        ]);
      render(
        <AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />,
      );
      await user.click(
        await screen.findByRole("button", { name: "加载更早的记录" }),
      );
      if (transition === "filter") {
        await user.click(
          within(screen.getByRole("group", { name: "按类型筛选" })).getByRole(
            "button",
            { name: "登录" },
          ),
        );
      } else {
        await user.click(screen.getByRole("button", { name: "刷新" }));
      }
      expect(await screen.findByText("「当前记录」")).toBeInTheDocument();
      await settleRequest(() => {
        older.resolve([
          event(50, "source.updated", { title: "过期的新闻源记录" }),
        ]);
      });
      expect(screen.getAllByRole("row")).toHaveLength(2);
      expect(screen.getByText("「当前记录」")).toBeInTheDocument();
      expect(
        screen.queryByText(/过期的新闻源记录|新闻源记录 1/),
      ).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it.each([
    ["filter", false],
    ["refresh", false],
    ["filter", true],
    ["refresh", true],
  ] as const)(
    "ignores old pagination errors after %s (session expired: %s)",
    async (transition, expired) => {
      const user = userEvent.setup();
      const older = pendingPage();
      const onSessionExpired = vi.fn();
      const auditEvents = vi
        .fn<AdminApi["auditEvents"]>()
        .mockResolvedValueOnce(fullPage())
        .mockReturnValueOnce(older.promise)
        .mockResolvedValueOnce([
          event(100, "auth.login", { title: "当前记录" }),
        ]);
      render(
        <AuditLogPage
          api={api(auditEvents)}
          onSessionExpired={onSessionExpired}
        />,
      );
      await user.click(
        await screen.findByRole("button", { name: "加载更早的记录" }),
      );
      if (transition === "filter") {
        await user.click(
          within(screen.getByRole("group", { name: "按类型筛选" })).getByRole(
            "button",
            { name: "登录" },
          ),
        );
      } else {
        await user.click(screen.getByRole("button", { name: "刷新" }));
      }
      expect(await screen.findByText("「当前记录」")).toBeInTheDocument();
      await settleRequest(() => {
        older.reject(
          expired ? new AdminSessionExpiredError() : new Error("旧分页失败"),
        );
      });
      expect(screen.getAllByRole("row")).toHaveLength(2);
      expect(screen.getByText("「当前记录」")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(onSessionExpired).not.toHaveBeenCalled();
    },
  );

  it("preserves rows on a page failure and retries the same cursor once", async () => {
    const user = userEvent.setup();
    const firstPage = fullPage();
    const older = pendingPage();
    const retry = pendingPage();
    const auditEvents = vi
      .fn<AdminApi["auditEvents"]>()
      .mockResolvedValueOnce(firstPage)
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(retry.promise);
    render(<AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />);
    await user.dblClick(
      await screen.findByRole("button", { name: "加载更早的记录" }),
    );
    expect(auditEvents).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "正在加载…" })).toBeDisabled();
    await settleRequest(() => {
      older.reject(new Error("网络中断"));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "加载更早的记录失败：网络中断",
    );
    expect(screen.getAllByRole("row")).toHaveLength(AUDIT_PAGE_SIZE + 1);
    await user.dblClick(
      screen.getByRole("button", { name: "重试加载更早的记录" }),
    );
    expect(auditEvents).toHaveBeenCalledTimes(3);
    expect(auditEvents.mock.calls[1]).toEqual(auditEvents.mock.calls[2]);
    expect(auditEvents).toHaveBeenLastCalledWith({
      before: firstPage.at(-1)?.occurred_at,
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await settleRequest(() => {
      retry.resolve([event(50, "auth.logout")]);
    });
    expect(screen.getAllByRole("row")).toHaveLength(AUDIT_PAGE_SIZE + 2);
    expect(screen.getByText("没有更早的记录了。")).toBeInTheDocument();
  });

  it("does not unlock an active new page when an obsolete request finishes", async () => {
    const user = userEvent.setup();
    const older = pendingPage();
    const current = pendingPage();
    const auditEvents = vi
      .fn<AdminApi["auditEvents"]>()
      .mockResolvedValueOnce(fullPage())
      .mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce(fullPage())
      .mockReturnValueOnce(current.promise);
    render(<AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />);
    await user.click(
      await screen.findByRole("button", { name: "加载更早的记录" }),
    );
    await user.click(screen.getByRole("button", { name: "刷新" }));
    await user.click(
      await screen.findByRole("button", { name: "加载更早的记录" }),
    );
    await settleRequest(() => {
      older.resolve([]);
    });
    expect(screen.getByRole("button", { name: "正在加载…" })).toBeDisabled();
    expect(auditEvents).toHaveBeenCalledTimes(4);
    await settleRequest(() => {
      current.resolve([event(50, "auth.login")]);
    });
    expect(screen.getAllByRole("row")).toHaveLength(AUDIT_PAGE_SIZE + 2);
  });

  it("waits for the newest request when returning to a previous filter", async () => {
    const user = userEvent.setup();
    const oldAll = pendingPage();
    const newAll = pendingPage();
    const auditEvents = vi
      .fn<AdminApi["auditEvents"]>()
      .mockReturnValueOnce(oldAll.promise)
      .mockResolvedValueOnce([event(100, "auth.login")])
      .mockReturnValueOnce(newAll.promise);
    render(<AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />);
    const filters = screen.getByRole("group", { name: "按类型筛选" });
    await user.click(within(filters).getByRole("button", { name: "登录" }));
    await screen.findByRole("table");
    await user.click(within(filters).getByRole("button", { name: "全部" }));
    await settleRequest(() => {
      oldAll.resolve(fullPage());
    });
    expect(screen.getByRole("status")).toHaveTextContent("正在读取…");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await settleRequest(() => {
      newAll.resolve([event(101, "user.created", { title: "最新的全部记录" })]);
    });
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("「最新的全部记录」")).toBeInTheDocument();
  });

  it("ignores an old initial failure after filtering and supports a current retry", async () => {
    const user = userEvent.setup();
    const oldAll = pendingPage();
    const auditEvents = vi
      .fn<AdminApi["auditEvents"]>()
      .mockReturnValueOnce(oldAll.promise)
      .mockRejectedValueOnce(new Error("当前筛选读取失败"))
      .mockResolvedValueOnce([event(100, "auth.login")]);
    render(<AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />);
    await user.click(
      within(screen.getByRole("group", { name: "按类型筛选" })).getByRole(
        "button",
        { name: "登录" },
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "当前筛选读取失败",
    );
    await user.click(screen.getByRole("button", { name: "重试" }));
    await screen.findByRole("table");
    await settleRequest(() => {
      oldAll.reject(new Error("旧请求失败"));
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(auditEvents).toHaveBeenLastCalledWith({ kind: "auth" });
  });

  it("does not reuse an old ready page when leaving and immediately returning to its filter", async () => {
    const user = userEvent.setup();
    const login = pendingPage();
    const newAll = pendingPage();
    const auditEvents = vi
      .fn<AdminApi["auditEvents"]>()
      .mockResolvedValueOnce(fullPage())
      .mockReturnValueOnce(login.promise)
      .mockReturnValueOnce(newAll.promise);
    render(<AuditLogPage api={api(auditEvents)} onSessionExpired={vi.fn()} />);
    await screen.findByRole("table");
    const filters = screen.getByRole("group", { name: "按类型筛选" });
    await user.click(within(filters).getByRole("button", { name: "登录" }));
    await user.click(within(filters).getByRole("button", { name: "全部" }));
    expect(screen.getByRole("status")).toHaveTextContent("正在读取…");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "加载更早的记录" }),
    ).not.toBeInTheDocument();
    await settleRequest(() => {
      login.resolve([event(100, "auth.login")]);
    });
    expect(screen.getByRole("status")).toHaveTextContent("正在读取…");
    await settleRequest(() => {
      newAll.resolve([event(101, "user.created")]);
    });
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("新建账号")).toBeInTheDocument();
  });

  it.each(["initial", "page"] as const)(
    "ignores an expired %s request after unmount",
    async (request) => {
      const user = userEvent.setup();
      const pending = pendingPage();
      const onSessionExpired = vi.fn();
      const auditEvents = vi.fn<AdminApi["auditEvents"]>();
      if (request === "page") auditEvents.mockResolvedValueOnce(fullPage());
      auditEvents.mockReturnValueOnce(pending.promise);
      const view = render(
        <AuditLogPage
          api={api(auditEvents)}
          onSessionExpired={onSessionExpired}
        />,
      );
      if (request === "page") {
        await user.click(
          await screen.findByRole("button", { name: "加载更早的记录" }),
        );
      }
      view.unmount();
      await settleRequest(() => {
        pending.reject(new AdminSessionExpiredError());
      });
      expect(onSessionExpired).not.toHaveBeenCalled();
    },
  );

  it.each(["initial", "page"] as const)(
    "still handles a current %s session-expiry response",
    async (request) => {
      const user = userEvent.setup();
      const onSessionExpired = vi.fn();
      const auditEvents = vi.fn<AdminApi["auditEvents"]>();
      if (request === "page") auditEvents.mockResolvedValueOnce(fullPage());
      auditEvents.mockRejectedValueOnce(new AdminSessionExpiredError());
      render(
        <AuditLogPage
          api={api(auditEvents)}
          onSessionExpired={onSessionExpired}
        />,
      );
      if (request === "page") {
        await user.click(
          await screen.findByRole("button", { name: "加载更早的记录" }),
        );
      }
      await waitFor(() => expect(onSessionExpired).toHaveBeenCalledOnce());
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it("discards the old client's pagination error when the API is replaced", async () => {
    const user = userEvent.setup();
    const older = pendingPage();
    const onSessionExpired = vi.fn();
    const oldApi = api(
      vi
        .fn<AdminApi["auditEvents"]>()
        .mockResolvedValueOnce(fullPage())
        .mockReturnValueOnce(older.promise),
    );
    const view = render(
      <AuditLogPage api={oldApi} onSessionExpired={onSessionExpired} />,
    );
    await user.click(
      await screen.findByRole("button", { name: "加载更早的记录" }),
    );
    view.rerender(
      <AuditLogPage
        api={api(vi.fn(() => Promise.resolve([event(100, "auth.login")])))}
        onSessionExpired={onSessionExpired}
      />,
    );
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(2));
    await settleRequest(() => {
      older.reject(new AdminSessionExpiredError());
    });
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(onSessionExpired).not.toHaveBeenCalled();
  });

  it("describes publication queries and manual conclusions without claiming a query published", async () => {
    const events = [
      event(0, "wechat.publish_rechecked", {
        ok: true,
        ignored_newer_state: false,
      }),
      event(1, "wechat.publish_rechecked", {
        ok: false,
        ignored_newer_state: true,
      }),
      event(2, "wechat.publish_reconciled", {
        result: "published",
        note: "在公众号后台已找到文章",
      }),
      event(3, "wechat.publish_reconciled", {
        result: "not_published",
        note: "核对公众号后台未发布",
      }),
      event(4, "future.action", {
        ok: true,
        note: "<script>未执行</script>",
        changes: { future: null, unknown: ["value"] },
      }),
      event(5, "user.updated", {
        changes: { display_name: null, role: false },
      }),
    ];
    render(
      <AuditLogPage
        api={api(vi.fn(() => Promise.resolve(events)))}
        onSessionExpired={vi.fn()}
      />,
    );
    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent("查询发布结果");
    expect(rows[1]).toHaveTextContent("已查询微信发布状态");
    expect(rows[1]).not.toHaveTextContent("发布成功");
    expect(rows[2]).toHaveTextContent("查询微信发布状态失败");
    expect(rows[2]).toHaveTextContent(
      "记录已有更新，本次查询结果未覆盖最新状态",
    );
    expect(rows[3]).toHaveTextContent("人工核对发布结果");
    expect(rows[3]).toHaveTextContent("核对结果：已发布");
    expect(rows[3]).toHaveTextContent("备注：在公众号后台已找到文章");
    expect(rows[4]).toHaveTextContent("核对结果：未发布");
    expect(rows[4]).toHaveTextContent("备注：核对公众号后台未发布");
    expect(rows[5]).toHaveTextContent("future.action");
    expect(rows[5]).toHaveTextContent("操作成功");
    expect(rows[5]).toHaveTextContent("<script>未执行</script>");
    expect(screen.getByRole("table").querySelector("script")).toBeNull();
    expect(screen.queryByText(/能抓到文章|抓不到文章/)).not.toBeInTheDocument();
  });

  it("retains source preview and account verification descriptions", async () => {
    const events = [
      event(0, "source.previewed", { ok: true }),
      event(1, "source.previewed", { ok: false }),
      event(2, "wechat_account.verified", { ok: true }),
      event(3, "wechat_account.verified", { ok: false }),
    ];
    render(
      <AuditLogPage
        api={api(vi.fn(() => Promise.resolve(events)))}
        onSessionExpired={vi.fn()}
      />,
    );
    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent("能抓到文章");
    expect(rows[2]).toHaveTextContent("抓不到文章");
    expect(rows[3]).toHaveTextContent("验证通过");
    expect(rows[4]).toHaveTextContent("验证没通过");
  });
});
