import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApp } from "./AdminApp";
import {
  AdminSessionExpiredError,
  type AdminApi,
  type AdminAuditEvent,
  type AdminMe,
} from "./api";
import { sectionFromPath, visibleSections } from "./sections";
import type { SourcesApi } from "./sources/api";

// The 新闻源 page is the landing section; these tests only need it quiet.
const NO_SOURCES: SourcesApi = {
  list: () => Promise.resolve([]),
  preview: () => Promise.reject(new Error("unused")),
  create: () => Promise.reject(new Error("unused")),
  update: () => Promise.reject(new Error("unused")),
  setEnabled: () => Promise.reject(new Error("unused")),
  archive: () => Promise.reject(new Error("unused")),
  articles: () => Promise.resolve([]),
};

const OWNER: AdminMe = {
  username: "teacher.li",
  display_name: "李老师",
  role: "owner",
  expires_at: "2026-10-08T14:00:00Z",
};
const EDITOR: AdminMe = {
  ...OWNER,
  username: "wang",
  display_name: "王老师",
  role: "editor",
};

const EVENTS: readonly AdminAuditEvent[] = [
  {
    id: "00000000-0000-0000-0000-000000000002",
    occurred_at: "2026-10-08T02:05:00Z",
    username: "teacher.li",
    action: "auth.login",
    target_type: null,
    target_id: null,
    detail: {},
  },
  {
    id: "00000000-0000-0000-0000-000000000001",
    occurred_at: "2026-10-08T02:04:00Z",
    username: "teacher.li",
    action: "auth.login_failed",
    target_type: null,
    target_id: null,
    detail: { reason: "wrong_password" },
  },
  {
    id: "00000000-0000-0000-0000-000000000003",
    occurred_at: "2026-10-08T02:03:00Z",
    username: "teacher.li",
    action: "source.updated",
    target_type: "source",
    target_id: "a6ddb3d7-1853-4443-a558-3edcefc467dd",
    detail: { changed: ["display_name", "connector_config"], version: 2 },
  },
];

function api(overrides: Partial<AdminApi> = {}) {
  return {
    me: vi.fn(() => Promise.resolve<AdminMe | null>(null)),
    login: vi.fn(() => Promise.resolve(OWNER)),
    logout: vi.fn(() => Promise.resolve()),
    auditEvents: vi.fn(() => Promise.resolve(EVENTS)),
    changePassword: vi.fn(() => Promise.resolve(0)),
    ...overrides,
  } satisfies AdminApi;
}

function openAt(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("运营后台", () => {
  it("logs in, shows the server's refusal, then opens the first section", async () => {
    const user = userEvent.setup();
    const calls = api({
      login: vi
        .fn()
        .mockRejectedValueOnce(
          new Error("用户名或密码不对。连续输错 5 次，账号会锁定 15 分钟。"),
        )
        .mockResolvedValueOnce(OWNER),
    });
    openAt("/admin");
    const view = render(<AdminApp api={calls} sourcesApi={NO_SOURCES} />);

    await user.type(await screen.findByLabelText("用户名"), " Teacher.Li ");
    await user.type(screen.getByLabelText("密码"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("连续输错 5 次");
    expect(calls.login).toHaveBeenLastCalledWith(
      "Teacher.Li",
      "wrong-password",
    );
    // The password field is cleared after a refusal.
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect((await axe(view.container)).violations).toEqual([]);

    await user.type(screen.getByLabelText("密码"), "teacher-pass-2026");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("李老师（管理员）")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "新闻源" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "新增新闻源" }),
    ).toBeInTheDocument();
  });

  it("shows an editor only the sections an editor may open", async () => {
    openAt("/admin/models");
    render(
      <AdminApp
        api={api({ me: vi.fn(() => Promise.resolve(EDITOR)) })}
        sourcesApi={NO_SOURCES}
      />,
    );

    const menu = await screen.findByRole("navigation", { name: "后台菜单" });
    const links = within(menu)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links).toEqual([
      "新闻源",
      "关键词",
      "新闻审核",
      "发布",
      "数据",
      "排版模板",
      "海报风格待上线",
      "我的账号",
    ]);
    // A link to an owner-only page falls back to the first allowed section.
    expect(screen.getByText(/当前账号不能打开这个页面/)).toBeInTheDocument();
    expect(within(menu).getByRole("link", { name: /新闻源/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("moves between sections and reads the audit log as the owner", async () => {
    const user = userEvent.setup();
    const calls = api({ me: vi.fn(() => Promise.resolve(OWNER)) });
    openAt("/admin/sources");
    render(<AdminApp api={calls} sourcesApi={NO_SOURCES} />);

    const menu = await screen.findByRole("navigation", { name: "后台菜单" });
    expect(within(menu).getAllByRole("link")).toHaveLength(12);
    await user.click(within(menu).getByRole("link", { name: /海报风格/ }));
    expect(window.location.pathname).toBe("/admin/poster-styles");
    expect(screen.getByText(/先出样图/)).toBeInTheDocument();

    await user.click(within(menu).getByRole("link", { name: "操作记录" }));
    expect(window.location.pathname).toBe("/admin/audit");
    const rows = await screen.findAllByRole("row");
    expect(rows.slice(1).map((row) => row.textContent)).toEqual([
      "10/08 10:05:00teacher.li登录",
      "10/08 10:04:00teacher.li登录失败密码不对",
      "10/08 10:03:00teacher.li修改新闻源对象：a6ddb3d7-1853-4443-a558-3edcefc467dd；改了：名称、抓取设置；第 2 版",
    ]);
  });

  it("returns to the login page when the session ends or the user logs out", async () => {
    const user = userEvent.setup();
    const expired = api({
      me: vi.fn(() => Promise.resolve(OWNER)),
      auditEvents: vi.fn(() => Promise.reject(new AdminSessionExpiredError())),
    });
    openAt("/admin/audit");
    const first = render(<AdminApp api={expired} sourcesApi={NO_SOURCES} />);
    expect(
      await screen.findByText("登录已过期，请重新登录"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "登录" })).toBeInTheDocument();
    first.unmount();

    const calls = api({ me: vi.fn(() => Promise.resolve(OWNER)) });
    openAt("/admin");
    render(<AdminApp api={calls} sourcesApi={NO_SOURCES} />);
    await user.click(await screen.findByRole("button", { name: "退出" }));
    expect(calls.logout).toHaveBeenCalledOnce();
    expect(await screen.findByText("已退出")).toBeInTheDocument();
  });

  it("says so when the API cannot be reached", async () => {
    openAt("/admin");
    render(
      <AdminApp
        sourcesApi={NO_SOURCES}
        api={api({
          me: vi.fn(() =>
            Promise.reject(new Error("连不上后台服务，请确认服务已启动")),
          ),
        })}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "连不上后台服务",
    );
  });
});

describe("admin sections", () => {
  it("maps paths and roles", () => {
    expect(sectionFromPath("/admin/keywords")).toBe("keywords");
    expect(sectionFromPath("/admin/keywords/")).toBe("keywords");
    expect(sectionFromPath("/admin")).toBeNull();
    expect(sectionFromPath("/admin/unknown")).toBeNull();
    expect(visibleSections("owner")).toHaveLength(12);
    expect(
      visibleSections("editor").map((section) => section.key),
    ).not.toContain("audit");
  });
});
