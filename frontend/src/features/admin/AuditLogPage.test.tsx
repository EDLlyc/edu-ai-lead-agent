import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AUDIT_PAGE_SIZE,
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
});
