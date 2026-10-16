import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApp } from "./AdminApp";
import { AdminSessionExpiredError, type AdminApi, type AdminMe } from "./api";
import type {
  KeywordsApi,
  KeywordLists,
  KeywordsOverview,
} from "./keywords/api";
import type { SourcesApi } from "./sources/api";

const ME: AdminMe = {
  username: "operator",
  display_name: "运营员",
  role: "owner",
  expires_at: "2026-10-11T00:00:00Z",
};
const EMPTY: KeywordsOverview = { current: null, history: [] };
const SOURCES: SourcesApi = {
  list: vi.fn(() => Promise.resolve([])),
  preview: vi.fn(() => Promise.reject(new Error("unused"))),
  create: vi.fn(() => Promise.reject(new Error("unused"))),
  update: vi.fn(() => Promise.reject(new Error("unused"))),
  setEnabled: vi.fn(() => Promise.reject(new Error("unused"))),
  archive: vi.fn(() => Promise.reject(new Error("unused"))),
  articles: vi.fn(() => Promise.resolve([])),
};
function session(overrides: Partial<AdminApi> = {}): AdminApi {
  return {
    me: vi.fn(() => Promise.resolve(ME)),
    login: vi.fn(() => Promise.resolve(ME)),
    logout: vi.fn(() => Promise.resolve()),
    auditEvents: vi.fn(() => Promise.resolve([])),
    changePassword: vi.fn(() => Promise.resolve(0)),
    ...overrides,
  };
}
function keywords(overrides: Partial<KeywordsApi> = {}): KeywordsApi {
  return {
    load: vi.fn(() => Promise.resolve(EMPTY)),
    version: vi.fn(() => Promise.reject(new Error("unused"))),
    impact: vi.fn(() => Promise.reject(new Error("unused"))),
    save: vi.fn((lists: KeywordLists) =>
      Promise.resolve({
        current: {
          focus: [...lists.focus],
          block: [...lists.block],
          copy_banned: [...lists.copy_banned],
          version: 1,
          note: null,
          created_by: "operator",
          created_at: "2026-10-10T00:00:00Z",
        },
        history: [],
      }),
    ),
    ...overrides,
  };
}
function beforeUnload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}
function open(
  path = "/admin/keywords",
  api = session(),
  keywordApi = keywords(),
) {
  window.history.replaceState(null, "", path);
  return render(
    <AdminApp
      api={api}
      keywordsApi={keywordApi}
      builtinPhrasesApi={{
        load: () =>
          Promise.resolve({
            version: null,
            marketing: [],
            anxiety: [],
            defaults_marketing: [],
            defaults_anxiety: [],
            locked: [],
          }),
        save: () => Promise.reject(new Error("not used")),
      }}
      sourcesApi={SOURCES}
    />,
  );
}
async function traverse(delta: number) {
  await act(async () => {
    window.history.go(delta);
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 0);
    });
  });
}
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("unsaved operator changes", () => {
  it("preserves typed keywords on stay/Escape and confirms explicit discard, with keyboard focus and reload protection", async () => {
    const user = userEvent.setup();
    const view = open();
    await screen.findByLabelText("添加关注词");
    expect(beforeUnload()).toBe(false);
    await user.type(screen.getByLabelText("添加关注词"), "未提交的词");
    expect(beforeUnload()).toBe(true);
    const menu = screen.getByRole("navigation", { name: "后台菜单" });
    const link = within(menu).getByRole("link", { name: "新闻源" });
    await user.click(link);
    const prompt = screen.getByRole("alertdialog", { name: "有未保存的修改" });
    expect(screen.getByRole("button", { name: "继续编辑" })).toHaveFocus();
    expect((await axe(prompt)).violations).toEqual([]);
    await user.tab();
    expect(
      screen.getByRole("button", { name: "放弃修改并继续" }),
    ).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "继续编辑" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(link).toHaveFocus();
    expect(window.location.pathname).toBe("/admin/keywords");
    expect(screen.getByLabelText("添加关注词")).toHaveValue("未提交的词");
    await user.keyboard("{Enter}"); // follow focused menu link
    await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
    expect(
      await screen.findByRole("heading", { name: "新闻源" }),
    ).toBeInTheDocument();
    expect(beforeUnload()).toBe(false);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    view.unmount();
  });

  it("keeps the mobile menu and edits after cancellation, then collapses with visible focus after discard", async () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("添加关注词"), "继续保留");
    const toggle = screen.getByRole("button", {
      name: "内容来源 关键词 切换页面",
    });
    await user.click(toggle);
    await user.click(screen.getByRole("link", { name: "新闻源" }));
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("添加关注词")).toHaveValue("继续保留");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "新闻源" })).toHaveFocus();
    expect(window.location.pathname).toBe("/admin/keywords");
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
    await screen.findByRole("heading", { name: "新闻源" });
    expect(
      screen.getByRole("button", { name: "内容来源 新闻源 切换页面" }),
    ).toHaveFocus();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(beforeUnload()).toBe(false);
  });

  it("retains edits after failed save and clears the guard only after successful save", async () => {
    const user = userEvent.setup();
    const calls = keywords();
    const save = vi
      .fn(calls.save)
      .mockRejectedValueOnce(new Error("保存暂时失败"));
    open("/admin/keywords", session(), { ...calls, save });
    await user.type(await screen.findByLabelText("添加关注词"), "新词{Enter}");
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("保存暂时失败");
    expect(beforeUnload()).toBe(true);
    await user.click(screen.getByRole("button", { name: "放弃修改" }));
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByRole("list", { name: "关注词" })).toHaveTextContent(
      "新词",
    );
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));
    expect(await screen.findByText(/已保存为第 1 版/)).toBeInTheDocument();
    expect(beforeUnload()).toBe(false);
    await user.click(screen.getByRole("link", { name: "新闻源" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(window.location.pathname).toBe("/admin/sources");
  });

  it("protects logout while session expiry always clears credentials and returns to login", async () => {
    const user = userEvent.setup();
    const calls = session();
    const first = open("/admin/account", calls);
    await user.type(await screen.findByLabelText("当前密码"), "fake-current");
    await user.click(screen.getByRole("button", { name: "退出" }));
    expect(calls.logout).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("当前密码")).toHaveValue("fake-current");
    await user.click(screen.getByRole("button", { name: "退出" }));
    await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
    expect(
      await screen.findByRole("heading", { name: "登录" }),
    ).toBeInTheDocument();
    expect(calls.logout).toHaveBeenCalledOnce();
    expect(beforeUnload()).toBe(false);
    first.unmount();

    open(
      "/admin/account",
      session({
        changePassword: vi.fn(() =>
          Promise.reject(new AdminSessionExpiredError()),
        ),
      }),
    );
    await user.type(await screen.findByLabelText("当前密码"), "fake-current");
    await user.type(
      screen.getByLabelText("新密码（至少 8 位）"),
      "fake-next-password",
    );
    await user.type(
      screen.getByLabelText("再输一次新密码"),
      "fake-next-password",
    );
    await user.click(screen.getByRole("button", { name: "修改密码" }));
    expect(
      await screen.findByText("登录已过期，请重新登录"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("当前密码")).not.toBeInTheDocument();
    expect(beforeUnload()).toBe(false);
  });

  it("restores dirty back/forward traversals without duplicate history or a mismatched address", async () => {
    const user = userEvent.setup();
    open("/admin/sources");
    const menu = await screen.findByRole("navigation", { name: "后台菜单" });
    await user.click(within(menu).getByRole("link", { name: "关键词" }));
    await screen.findByLabelText("添加关注词");
    await user.click(within(menu).getByRole("link", { name: "我的账号" }));
    await user.type(screen.getByLabelText("当前密码"), "memory-only");
    const length = window.history.length;
    for (let retry = 0; retry < 2; retry += 1) {
      await traverse(-1);
      await screen.findByRole("alertdialog");
      expect(window.location.pathname).toBe("/admin/account");
      await user.click(screen.getByRole("button", { name: "继续编辑" }));
      expect(screen.getByLabelText("当前密码")).toHaveValue("memory-only");
      expect(window.history.length).toBe(length);
    }
    await traverse(-1);
    await user.click(
      await screen.findByRole("button", { name: "放弃修改并继续" }),
    );
    await screen.findByLabelText("添加关注词");
    await waitFor(() =>
      expect(window.location.pathname).toBe("/admin/keywords"),
    );
    await user.type(screen.getByLabelText("添加关注词"), "前进也保留");
    await traverse(1);
    await screen.findByRole("alertdialog");
    expect(window.location.pathname).toBe("/admin/keywords");
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("添加关注词")).toHaveValue("前进也保留");
    await traverse(1);
    await user.click(
      await screen.findByRole("button", { name: "放弃修改并继续" }),
    );
    await screen.findByLabelText("当前密码");
    expect(window.location.pathname).toBe("/admin/account");
    expect(screen.getByLabelText("当前密码")).toHaveValue("");
    expect(window.history.length).toBe(length);
  });

  it("protects source explicit cancellation but does not warn for an untouched form", async () => {
    const user = userEvent.setup();
    open("/admin/sources");
    await user.click(await screen.findByRole("button", { name: "新增新闻源" }));
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "新增新闻源" }));
    await user.type(screen.getByLabelText("名称"), "我的新闻源");
    await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("名称")).toHaveValue("我的新闻源");
    await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
    expect(screen.queryByLabelText("名称")).not.toBeInTheDocument();
    expect(beforeUnload()).toBe(false);
  });

  it.each([
    ["demo", "演示环境 · 模拟数据 · 只读"],
    ["production", "生产环境 · 真实数据"],
    ["", "环境未配置 · 请确认数据来源"],
  ])(
    "always labels %s explicitly, including logged-out pages",
    async (mode, label) => {
      vi.stubEnv("VITE_ADMIN_DATA_MODE", mode);
      open("/admin", session({ me: vi.fn(() => Promise.resolve(null)) }));
      expect(screen.getByLabelText("数据环境")).toHaveTextContent(label);
      await screen.findByRole("heading", { name: "登录" });
      expect(screen.getByLabelText("数据环境")).toHaveTextContent(label);
    },
  );
});
