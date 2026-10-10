import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError, type AdminApi, type AdminMe } from "../api";
import { MyAccountPage } from "./MyAccountPage";
import { UnsavedChangesProvider } from "../unsaved/UnsavedChanges";

const ME: AdminMe = {
  username: "liyuchen",
  display_name: "liyuchen",
  role: "owner",
  expires_at: "2026-10-09T13:00:00Z",
};

function api(changePassword: AdminApi["changePassword"]): AdminApi {
  return {
    me: vi.fn(() => Promise.resolve(ME)),
    login: vi.fn(() => Promise.resolve(ME)),
    logout: vi.fn(() => Promise.resolve()),
    auditEvents: vi.fn(() => Promise.resolve([])),
    changePassword,
  };
}

describe("我的账号", () => {
  it("changes my password after checking the new one twice", async () => {
    const user = userEvent.setup();
    const change = vi.fn(() => Promise.resolve(2));
    render(
      <MyAccountPage api={api(change)} me={ME} onSessionExpired={vi.fn()} />,
    );
    expect(screen.getByText("10/09 21:00")).toBeInTheDocument();

    const submit = screen.getByRole("button", { name: "修改密码" });
    await user.type(screen.getByLabelText("当前密码"), "OznhQQvlrLH7ygXt");
    await user.type(screen.getByLabelText(/新密码（至少 10 位）/), "short");
    expect(screen.getByText("新密码至少 10 位。")).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/新密码（至少 10 位）/));
    await user.type(
      screen.getByLabelText(/新密码（至少 10 位）/),
      "my-own-pass-2026",
    );
    await user.type(
      screen.getByLabelText("再输一次新密码"),
      "my-own-pass-2027",
    );
    expect(screen.getByText("两次输入的新密码不一样。")).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await user.clear(screen.getByLabelText("再输一次新密码"));
    await user.type(
      screen.getByLabelText("再输一次新密码"),
      "my-own-pass-2026",
    );
    await user.click(submit);
    expect(change).toHaveBeenCalledWith("OznhQQvlrLH7ygXt", "my-own-pass-2026");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "密码已修改，其他 2 处登录已退出",
    );
    expect(screen.getByLabelText("当前密码")).toHaveValue("");
  });

  it("shows a wrong current password and handles an ended session", async () => {
    const user = userEvent.setup();
    const wrong = vi.fn(() =>
      Promise.reject(
        new Error("当前密码不对。连续输错 5 次，账号会锁定 15 分钟。"),
      ),
    );
    const view = render(
      <MyAccountPage api={api(wrong)} me={ME} onSessionExpired={vi.fn()} />,
    );
    await user.type(screen.getByLabelText("当前密码"), "guess-guess");
    await user.type(
      screen.getByLabelText(/新密码（至少 10 位）/),
      "my-own-pass-2026",
    );
    await user.type(
      screen.getByLabelText("再输一次新密码"),
      "my-own-pass-2026",
    );
    await user.click(screen.getByRole("button", { name: "修改密码" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前密码不对");
    view.unmount();

    const expired = vi.fn();
    render(
      <MyAccountPage
        api={api(vi.fn(() => Promise.reject(new AdminSessionExpiredError())))}
        me={ME}
        onSessionExpired={expired}
      />,
    );
    await user.type(screen.getByLabelText("当前密码"), "guess-guess");
    await user.type(
      screen.getByLabelText(/新密码（至少 10 位）/),
      "my-own-pass-2026",
    );
    await user.type(
      screen.getByLabelText("再输一次新密码"),
      "my-own-pass-2026",
    );
    await user.click(screen.getByRole("button", { name: "修改密码" }));
    expect(expired).toHaveBeenCalledOnce();
  });
});

it("freezes a submitted password snapshot and restores all inputs after a deferred failure", async () => {
  const user = userEvent.setup();
  let reject!: (error: Error) => void;
  const pending = new Promise<number>((_resolve, fail) => {
    reject = fail;
  });
  const change = vi.fn(() => pending);
  render(
    <UnsavedChangesProvider>
      <MyAccountPage api={api(change)} me={ME} onSessionExpired={vi.fn()} />
    </UnsavedChangesProvider>,
  );
  const current = screen.getByLabelText("当前密码");
  const next = screen.getByLabelText("新密码（至少 10 位）");
  const again = screen.getByLabelText("再输一次新密码");
  await user.type(current, "original-password");
  await user.type(next, "submitted-password");
  await user.type(again, "submitted-password");
  await user.click(screen.getByRole("button", { name: "修改密码" }));
  for (const input of [current, next, again]) expect(input).toBeDisabled();
  await user.type(next, "later-input");
  expect(next).toHaveValue("submitted-password");
  expect(change).toHaveBeenCalledOnce();
  expect(change).toHaveBeenCalledWith(
    "original-password",
    "submitted-password",
  );
  await act(async () => {
    reject(new Error("暂时无法保存"));
    await pending.catch(() => undefined);
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法保存");
  for (const input of [current, next, again]) expect(input).toBeEnabled();
  expect(current).toHaveValue("original-password");
  expect(next).toHaveValue("submitted-password");
  const reload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(reload);
  expect(reload.defaultPrevented).toBe(true);
  await user.type(next, "-corrected");
  expect(next).toHaveValue("submitted-password-corrected");
});
