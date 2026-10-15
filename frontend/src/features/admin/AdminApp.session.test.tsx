import { StrictMode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApp } from "./AdminApp";
import { AdminSessionExpiredError, type AdminApi, type AdminMe } from "./api";

const ME: AdminMe = {
  username: "operator",
  display_name: "运营员",
  role: "owner",
  expires_at: "2026-10-13T00:00:00Z",
};
const NEXT: AdminMe = {
  ...ME,
  username: "editor",
  display_name: "新编辑",
  role: "editor",
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function api(overrides: Partial<AdminApi> = {}): AdminApi {
  return {
    me: vi.fn(() => Promise.resolve(ME)),
    login: vi.fn(() => Promise.resolve(ME)),
    logout: vi.fn(() => Promise.resolve()),
    auditEvents: vi.fn(() => Promise.resolve([])),
    changePassword: vi.fn(() => Promise.resolve(0)),
    ...overrides,
  };
}
function open(calls: AdminApi) {
  window.history.replaceState(null, "", "/admin/account");
  return render(<AdminApp api={calls} />);
}
function returnEvents() {
  fireEvent(window, new Event("focus"));
  fireEvent(window, new Event("pageshow"));
  fireEvent(document, new Event("visibilitychange"));
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

describe("session continuity on return to admin", () => {
  it.each(["focus", "pageshow", "visibilitychange"])(
    "restores another tab's valid session from an anonymous page on %s",
    async (eventName) => {
      const me = vi
        .fn<AdminApi["me"]>()
        .mockResolvedValueOnce(null)
        .mockResolvedValueOnce(NEXT);
      const calls = api({ me });
      open(calls);
      await screen.findByRole("heading", { name: "登录" });
      fireEvent(
        eventName === "visibilitychange" ? document : window,
        new Event(eventName),
      );
      await screen.findByText("新编辑（编辑）");
      expect(calls.login).not.toHaveBeenCalled();
      expect(me).toHaveBeenCalledTimes(2);
    },
  );

  it("preserves typed login fields through an anonymous check failure and retry", async () => {
    const user = userEvent.setup();
    const checking = deferred<AdminMe | null>();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockResolvedValueOnce(null)
      .mockReturnValueOnce(checking.promise)
      .mockResolvedValueOnce(null);
    open(api({ me }));
    await user.type(await screen.findByLabelText("用户名"), "operator");
    await user.type(screen.getByLabelText("密码"), "memory-only");
    returnEvents();
    expect(me).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("用户名")).toHaveValue("operator");
    expect(screen.getByLabelText("密码")).toHaveValue("memory-only");
    await act(async () => {
      checking.reject(new Error("offline"));
      await checking.promise.catch(() => undefined);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("当前登录状态未确认");
    expect(screen.getByLabelText("密码")).toHaveValue("memory-only");
    await user.click(screen.getByRole("button", { name: "重新检查登录状态" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toHaveValue("operator");
    expect(screen.getByLabelText("密码")).toHaveValue("memory-only");
    expect(me).toHaveBeenCalledTimes(3);
  });

  it("keeps an in-flight login authoritative over anonymous restoration checks", async () => {
    const user = userEvent.setup();
    const oldCheck = deferred<AdminMe | null>();
    const pendingLogin = deferred<AdminMe>();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockResolvedValueOnce(null)
      .mockReturnValueOnce(oldCheck.promise);
    const login = vi.fn(() => pendingLogin.promise);
    open(api({ me, login }));
    await user.type(await screen.findByLabelText("用户名"), "editor");
    await user.type(screen.getByLabelText("密码"), "memory-only");
    returnEvents();
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(me.mock.calls[1]?.[0]?.aborted).toBe(true);
    returnEvents();
    await act(async () => {
      oldCheck.resolve(ME);
      await oldCheck.promise;
    });
    returnEvents();
    expect(screen.getByRole("button", { name: "正在登录…" })).toBeDisabled();
    expect(screen.getByLabelText("密码")).toHaveValue("memory-only");
    expect(me).toHaveBeenCalledTimes(2);
    expect(login).toHaveBeenCalledOnce();
    await act(async () => {
      pendingLogin.resolve(NEXT);
      await pendingLogin.promise;
    });
    expect(screen.getByText("新编辑（编辑）")).toBeInTheDocument();
  });

  it.each(["pagehide", "visibilitychange"])(
    "discards a pre-departure check at %s before restoration",
    async (eventName) => {
      const beforeLeaving = deferred<AdminMe | null>();
      const restored = deferred<AdminMe | null>();
      const me = vi
        .fn<AdminApi["me"]>()
        .mockResolvedValueOnce(ME)
        .mockReturnValueOnce(beforeLeaving.promise)
        .mockReturnValueOnce(restored.promise);
      open(api({ me }));
      await screen.findByText("运营员（管理员）");
      returnEvents();
      const visibility = vi
        .spyOn(document, "visibilityState", "get")
        .mockReturnValue("hidden");
      fireEvent(
        eventName === "pagehide" ? window : document,
        new Event(eventName),
      );
      expect(me.mock.calls[1]?.[0]?.aborted).toBe(true);
      visibility.mockReturnValue("visible");
      returnEvents();
      expect(me).toHaveBeenCalledTimes(3);
      await act(async () => {
        beforeLeaving.resolve(ME);
        await beforeLeaving.promise;
      });
      returnEvents();
      expect(me).toHaveBeenCalledTimes(3);
      await act(async () => {
        restored.resolve(null);
        await restored.promise;
      });
      expect(screen.getByRole("heading", { name: "登录" })).toBeInTheDocument();
    },
  );

  it("coalesces focus/pageshow/visible checks, preserves edits and expires only on confirmed absence", async () => {
    const user = userEvent.setup();
    const checking = deferred<AdminMe | null>();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockResolvedValue(null)
      .mockResolvedValueOnce(ME)
      .mockReturnValueOnce(checking.promise)
      .mockResolvedValueOnce(null);
    open(api({ me }));
    await user.type(await screen.findByLabelText("当前密码"), "memory-only");
    returnEvents();
    expect(me).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("当前密码")).toHaveValue("memory-only");
    expect(screen.getByText("正在重新检查登录状态…")).toBeInTheDocument();
    await act(async () => {
      checking.resolve(ME);
      await checking.promise;
    });
    expect(screen.getByLabelText("当前密码")).toHaveValue("memory-only");
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("hidden");
    returnEvents();
    expect(me).toHaveBeenCalledTimes(2);
    visibility.mockReturnValue("visible");
    returnEvents();
    await screen.findByRole("heading", { name: "登录" });
    expect(screen.getByText("登录已过期，请重新登录")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("当前密码")).not.toBeInTheDocument();
    const leave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(false);
    await act(async () => {
      returnEvents();
      await Promise.resolve();
    });
    expect(me).toHaveBeenCalledTimes(4);
  });

  it("labels failed revalidation as unconfirmed, retains form values and allows a retry", async () => {
    const user = userEvent.setup();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockResolvedValueOnce(ME)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(ME);
    open(api({ me }));
    await user.type(await screen.findByLabelText("当前密码"), "keep-me");
    returnEvents();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "当前登录状态未确认",
    );
    expect(screen.getByLabelText("当前密码")).toHaveValue("keep-me");
    expect(
      screen.queryByRole("heading", { name: "登录" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新检查登录状态" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前密码")).toHaveValue("keep-me");
    expect(me).toHaveBeenCalledTimes(3);
  });

  it("offers retry and the exhibit on a cold network failure, not a false anonymous login", async () => {
    vi.stubEnv("VITE_EXHIBIT_ENTRY_URL", "https://exhibit.example.com/");
    const user = userEvent.setup();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(null);
    open(api({ me }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "当前登录状态未确认",
    );
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回展厅" })).toHaveAttribute(
      "href",
      "https://exhibit.example.com/",
    );
    await user.click(screen.getByRole("button", { name: "重新检查登录状态" }));
    await screen.findByRole("heading", { name: "登录" });
  });

  it("keeps failed logout visibly retryable, deduplicates pending logout and ignores an obsolete check", async () => {
    const user = userEvent.setup();
    const oldCheck = deferred<AdminMe | null>();
    const pendingLogout = deferred<void>();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockResolvedValueOnce(ME)
      .mockReturnValueOnce(oldCheck.promise);
    const logout = vi
      .fn<AdminApi["logout"]>()
      .mockRejectedValueOnce(new Error("refused"))
      .mockReturnValueOnce(pendingLogout.promise);
    open(api({ me, logout }));
    await user.click(await screen.findByRole("button", { name: "退出" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "服务器会话可能仍有效",
    );
    expect(screen.queryByText("已退出")).not.toBeInTheDocument();
    expect(screen.getByText("运营员（管理员）")).toBeInTheDocument();
    returnEvents();
    await user.click(screen.getByRole("button", { name: "退出" }));
    expect(me.mock.calls[1]?.[0]?.aborted).toBe(true);
    await user.click(screen.getByRole("button", { name: "正在退出…" }));
    returnEvents();
    expect(logout).toHaveBeenCalledTimes(2);
    expect(me).toHaveBeenCalledTimes(2);
    await act(async () => {
      pendingLogout.resolve();
      await pendingLogout.promise;
    });
    expect(screen.getByText("已退出")).toBeInTheDocument();
    await act(async () => {
      oldCheck.resolve(ME);
      await oldCheck.promise;
    });
    expect(screen.getByRole("heading", { name: "登录" })).toBeInTheDocument();
    expect(screen.queryByText("运营员（管理员）")).not.toBeInTheDocument();
  });

  it.each(["success", "expiry", "failure"] as const)(
    "ignores obsolete check %s after expiry and a newer login, without releasing the new check",
    async (outcome) => {
      const user = userEvent.setup();
      const oldCheck = deferred<AdminMe | null>();
      const newCheck = deferred<AdminMe | null>();
      const me = vi
        .fn<AdminApi["me"]>()
        .mockResolvedValueOnce(ME)
        .mockReturnValueOnce(oldCheck.promise)
        .mockReturnValueOnce(newCheck.promise);
      const calls = api({
        me,
        login: vi.fn(() => Promise.resolve(NEXT)),
        changePassword: vi.fn(() =>
          Promise.reject(new AdminSessionExpiredError()),
        ),
      });
      open(calls);
      await user.type(await screen.findByLabelText("当前密码"), "old-password");
      await user.type(
        screen.getByLabelText("新密码（至少 8 位）"),
        "next-password",
      );
      await user.type(screen.getByLabelText("再输一次新密码"), "next-password");
      returnEvents();
      await user.click(screen.getByRole("button", { name: "修改密码" }));
      await user.type(await screen.findByLabelText("用户名"), "editor");
      await user.type(screen.getByLabelText("密码"), "fake-login-pass");
      await user.click(screen.getByRole("button", { name: "登录" }));
      await screen.findByText("新编辑（编辑）");
      expect(me.mock.calls[1]?.[0]?.aborted).toBe(true);
      returnEvents();
      await act(async () => {
        if (outcome === "failure")
          oldCheck.reject(new AdminSessionExpiredError());
        else oldCheck.resolve(outcome === "success" ? ME : null);
        await oldCheck.promise.catch(() => undefined);
      });
      returnEvents();
      expect(me).toHaveBeenCalledTimes(3);
      expect(screen.getByText("新编辑（编辑）")).toBeInTheDocument();
      await act(async () => {
        newCheck.resolve(NEXT);
        await newCheck.promise;
      });
      expect(screen.getByText("新编辑（编辑）")).toBeInTheDocument();
      expect(
        screen.queryByText("正在重新检查登录状态…"),
      ).not.toBeInTheDocument();
      expect(window.localStorage.length).toBe(0);
      expect(window.sessionStorage.length).toBe(0);
    },
  );

  it("cleans up StrictMode requests and listeners and refuses a late unmounted login", async () => {
    const oldCheck = deferred<AdminMe | null>();
    const me = vi
      .fn<AdminApi["me"]>()
      .mockReturnValueOnce(oldCheck.promise)
      .mockResolvedValueOnce(ME);
    window.history.replaceState(null, "", "/admin/account");
    const view = render(
      <StrictMode>
        <AdminApp api={api({ me })} />
      </StrictMode>,
    );
    await screen.findByText("运营员（管理员）");
    expect(me).toHaveBeenCalledTimes(2);
    expect(me.mock.calls[0]?.[0]?.aborted).toBe(true);
    await act(async () => {
      oldCheck.resolve(null);
      await oldCheck.promise;
    });
    expect(screen.getByText("运营员（管理员）")).toBeInTheDocument();
    view.unmount();
    returnEvents();
    expect(me).toHaveBeenCalledTimes(2);

    const user = userEvent.setup();
    const oldLogin = deferred<AdminMe>();
    const loginView = open(
      api({
        me: vi.fn(() => Promise.resolve(null)),
        login: vi.fn(() => oldLogin.promise),
      }),
    );
    await user.type(await screen.findByLabelText("用户名"), "operator");
    await user.type(screen.getByLabelText("密码"), "fake-password");
    await user.click(screen.getByRole("button", { name: "登录" }));
    loginView.unmount();
    open(api({ me: vi.fn(() => Promise.resolve(null)) }));
    await screen.findByRole("heading", { name: "登录" });
    await act(async () => {
      oldLogin.resolve(ME);
      await oldLogin.promise;
    });
    expect(screen.getByRole("heading", { name: "登录" })).toBeInTheDocument();
  });
});
