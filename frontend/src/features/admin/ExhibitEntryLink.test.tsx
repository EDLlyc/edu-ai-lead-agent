import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApp } from "./AdminApp";
import { ExhibitEntryLink } from "./ExhibitEntryLink";
import type { AdminApi, AdminMe } from "./api";
import { UnsavedContext } from "./unsaved/context";

const URL = "https://exhibit.example.com/";
const ME: AdminMe = {
  username: "operator",
  display_name: "运营员",
  role: "owner",
  expires_at: "2026-10-13T00:00:00Z",
};
function api(me: AdminMe | null): AdminApi {
  return {
    me: vi.fn(() => Promise.resolve(me)),
    login: vi.fn(() => Promise.resolve(ME)),
    logout: vi.fn(() => Promise.resolve()),
    auditEvents: vi.fn(() => Promise.resolve([])),
    changePassword: vi.fn(() => Promise.resolve(0)),
  };
}
afterEach(() => {
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

describe("return to the public exhibit", () => {
  it.each([
    undefined,
    "",
    "javascript:alert(1)",
    "https://user:password@example.com/",
  ])("omits absent/unsafe configuration %j", (value) => {
    vi.stubEnv("VITE_EXHIBIT_ENTRY_URL", value);
    const { container } = render(<ExhibitEntryLink />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the same credential-free entry on login and the signed-in shell", async () => {
    vi.stubEnv("VITE_EXHIBIT_ENTRY_URL", URL);
    window.history.replaceState(null, "", "/admin/account");
    const calls = api(null);
    const user = userEvent.setup();
    render(<AdminApp api={calls} />);
    await screen.findByRole("heading", { name: "登录" });
    expect(screen.getByRole("link", { name: "返回展厅" })).toHaveAttribute(
      "href",
      URL,
    );
    await user.type(screen.getByLabelText("用户名"), "operator");
    await user.type(screen.getByLabelText("密码"), "test-only-password");
    await user.click(screen.getByRole("button", { name: "登录" }));
    await screen.findByText("运营员（管理员）");
    expect(screen.getByRole("link", { name: "返回展厅" })).toHaveAttribute(
      "href",
      URL,
    );
    expect(calls.me).toHaveBeenCalledTimes(1);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("uses the existing dirty confirmation and restores focus and password edits on cancel", async () => {
    vi.stubEnv("VITE_EXHIBIT_ENTRY_URL", URL);
    window.history.replaceState(null, "", "/admin/account");
    const user = userEvent.setup();
    const calls = api(ME);
    render(<AdminApp api={calls} />);
    await user.type(await screen.findByLabelText("当前密码"), "memory-only");
    const link = screen.getByRole("link", { name: "返回展厅" });
    link.focus();
    await user.keyboard("{Enter}");
    expect(
      screen.getByRole("alertdialog", { name: "有未保存的修改" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "继续编辑" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(link).toHaveFocus();
    expect(screen.getByLabelText("当前密码")).toHaveValue("memory-only");
    expect(window.location.pathname).toBe("/admin/account");
    expect(calls.logout).not.toHaveBeenCalled();
  });

  it("guards ordinary activation but preserves native modified and middle clicks", () => {
    vi.stubEnv("VITE_EXHIBIT_ENTRY_URL", URL);
    const requestNavigation = vi.fn();
    render(
      <UnsavedContext
        value={{
          register: () => () => undefined,
          isDirty: () => true,
          clearAll: vi.fn(),
          requestDiscardFor: vi.fn(),
          requestNavigation,
        }}
      >
        <ExhibitEntryLink />
      </UnsavedContext>,
    );
    const link = screen.getByRole("link", { name: "返回展厅" });
    const normal = createEvent.click(link, { button: 0 });
    fireEvent(link, normal);
    expect(normal.defaultPrevented).toBe(true);
    expect(requestNavigation).toHaveBeenCalledOnce();
    for (const option of [
      { ctrlKey: true },
      { metaKey: true },
      { shiftKey: true },
      { altKey: true },
      { button: 1 },
    ]) {
      let preventedByLink = true;
      // Stop jsdom's unsupported navigation only after React has handled the event.
      document.addEventListener(
        "click",
        (event) => {
          preventedByLink = event.defaultPrevented;
          event.preventDefault();
        },
        { once: true },
      );
      fireEvent.click(link, option);
      expect(preventedByLink).toBe(false);
    }
    expect(requestNavigation).toHaveBeenCalledOnce();
    expect(link).not.toHaveAttribute("target");
  });
});
