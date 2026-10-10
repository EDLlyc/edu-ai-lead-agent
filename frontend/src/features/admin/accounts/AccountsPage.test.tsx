import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { UnsavedChangesProvider } from "../unsaved/UnsavedChanges";
import { describe, expect, it, vi } from "vitest";

import type { AccountsApi, AdminAccount } from "./api";
import { AccountsPage } from "./AccountsPage";

const ME: AdminAccount = {
  username: "liyuchen",
  display_name: "liyuchen",
  role: "owner",
  active: true,
  locked: false,
  last_login_at: "2026-10-09T01:00:00Z",
  created_at: "2026-10-08T10:00:00Z",
  live_sessions: 1,
};
const WANG: AdminAccount = {
  ...ME,
  username: "wang",
  display_name: "王老师",
  role: "editor",
  last_login_at: null,
  live_sessions: 0,
};

function api(overrides: Partial<AccountsApi> = {}) {
  return {
    list: vi.fn(() => Promise.resolve<readonly AdminAccount[]>([ME, WANG])),
    create: vi.fn(() =>
      Promise.resolve({
        account: { ...WANG, username: "zhang", display_name: "张老师" },
        initialPassword: "Kp7mXq2RtV9wNa",
      }),
    ),
    resetPassword: vi.fn(() =>
      Promise.resolve({ account: WANG, initialPassword: "Hn4bZs8YcW3eLm" }),
    ),
    setActive: vi.fn((username: string, active: boolean) =>
      Promise.resolve({ ...(username === "wang" ? WANG : ME), active }),
    ),
    update: vi.fn(() =>
      Promise.resolve({ ...WANG, display_name: "王老师（科学）" }),
    ),
    ...overrides,
  } satisfies AccountsApi;
}

describe("账号管理", () => {
  it("lists accounts and never offers to disable my own", async () => {
    const view = render(
      <AccountsPage api={api()} me="liyuchen" onSessionExpired={vi.fn()} />,
    );
    const rows = await screen.findAllByRole("row");
    expect(rows.slice(1).map((row) => row.textContent)).toEqual([
      "liyuchen（我）liyuchen管理员正常10/09 09:001修改重设密码",
      "wang王老师编辑正常从未登录0修改重设密码停用",
    ]);
    expect((await axe(view.container)).violations).toEqual([]);
  });

  it("creates an account and shows the generated password once", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(
      <AccountsPage api={calls} me="liyuchen" onSessionExpired={vi.fn()} />,
    );
    await user.click(await screen.findByRole("button", { name: "新建账号" }));
    const form = screen.getByRole("form", { name: "新建账号" });
    await user.type(within(form).getByLabelText(/用户名/), "zhang");
    await user.type(within(form).getByLabelText("显示名"), "张老师");
    await user.click(
      within(form).getByRole("button", { name: "新建并生成密码" }),
    );

    expect(calls.create).toHaveBeenCalledWith({
      username: "zhang",
      displayName: "张老师",
      role: "editor",
    });
    const issued = await screen.findByRole("alertdialog", { name: "初始密码" });
    expect(issued).toHaveTextContent("已新建「张老师」（zhang）的密码");
    expect(issued).toHaveTextContent("Kp7mXq2RtV9wNa");
    expect(issued).toHaveTextContent("只显示这一次");
    await user.click(within(issued).getByRole("button", { name: "我已记下" }));
    expect(screen.queryByText("Kp7mXq2RtV9wNa")).toBeNull();
    await waitFor(() => expect(calls.list).toHaveBeenCalledTimes(2));
  });

  it("asks before resetting a password or disabling an account", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(
      <AccountsPage api={calls} me="liyuchen" onSessionExpired={vi.fn()} />,
    );
    const wang = (await screen.findAllByRole("row"))[2]!;

    await user.click(within(wang).getByRole("button", { name: "重设密码" }));
    const confirm = within(wang).getByRole("group", { name: "确认操作" });
    expect(confirm).toHaveTextContent("旧密码立即失效");
    expect(calls.resetPassword).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "确认" }));
    expect(
      await screen.findByRole("alertdialog", { name: "初始密码" }),
    ).toHaveTextContent("Hn4bZs8YcW3eLm");
    expect(calls.resetPassword).toHaveBeenCalledWith("wang");

    const again = (await screen.findAllByRole("row"))[2]!;
    await user.click(within(again).getByRole("button", { name: "停用" }));
    await user.click(within(again).getByRole("button", { name: "确认" }));
    await waitFor(() =>
      expect(calls.setActive).toHaveBeenCalledWith("wang", false),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已停用「王老师」",
    );
  });

  it("edits a display name and role, but not my own role", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(
      <AccountsPage api={calls} me="liyuchen" onSessionExpired={vi.fn()} />,
    );
    const rows = await screen.findAllByRole("row");

    await user.click(within(rows[1]!).getByRole("button", { name: "修改" }));
    expect(within(rows[1]!).getByLabelText("角色")).toBeDisabled();
    await user.click(within(rows[1]!).getByRole("button", { name: "取消" }));

    await user.click(within(rows[2]!).getByRole("button", { name: "修改" }));
    const name = within(rows[2]!).getByLabelText("显示名");
    await user.clear(name);
    await user.type(name, "王老师（科学）");
    await user.selectOptions(within(rows[2]!).getByLabelText("角色"), "owner");
    await user.click(within(rows[2]!).getByRole("button", { name: "保存" }));
    expect(calls.update).toHaveBeenCalledWith("wang", {
      displayName: "王老师（科学）",
      role: "owner",
    });
  });

  it("shows the server's refusal", async () => {
    const user = userEvent.setup();
    render(
      <AccountsPage
        api={api({
          create: vi.fn(() =>
            Promise.reject(
              new Error(
                "这个用户名已经有了（停用的账号也占用用户名），请换一个",
              ),
            ),
          ),
        })}
        me="liyuchen"
        onSessionExpired={vi.fn()}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "新建账号" }));
    const form = screen.getByRole("form", { name: "新建账号" });
    await user.type(within(form).getByLabelText(/用户名/), "wang");
    await user.type(within(form).getByLabelText("显示名"), "王");
    await user.click(
      within(form).getByRole("button", { name: "新建并生成密码" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "用户名已经有了",
    );
  });
});

it("keeps failed account edits until save or explicit discard and guards switching rows", async () => {
  const user = userEvent.setup();
  const calls = api({
    update: vi.fn(() => Promise.reject(new Error("保存失败"))),
  });
  render(
    <UnsavedChangesProvider>
      <AccountsPage api={calls} me="liyuchen" onSessionExpired={vi.fn()} />
    </UnsavedChangesProvider>,
  );
  const rows = await screen.findAllByRole("row");
  await user.click(within(rows[2]!).getByRole("button", { name: "修改" }));
  await user.type(screen.getByLabelText("显示名"), "新名称");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
  await user.click(within(rows[1]!).getByRole("button", { name: "修改" }));
  await user.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByLabelText("显示名")).toHaveValue("王老师新名称");
  await user.click(screen.getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
  expect(screen.queryByLabelText("显示名")).not.toBeInTheDocument();
  const reload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(reload);
  expect(reload.defaultPrevented).toBe(false);
});

it("freezes name and role while an account update is pending", async () => {
  const user = userEvent.setup();
  const calls = api({
    update: vi.fn(() => new Promise<AdminAccount>(() => undefined)),
  });
  render(<AccountsPage api={calls} me="liyuchen" onSessionExpired={vi.fn()} />);
  const rows = await screen.findAllByRole("row");
  await user.click(within(rows[2]!).getByRole("button", { name: "修改" }));
  await user.type(screen.getByLabelText("显示名"), "编辑");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(screen.getByLabelText("显示名")).toBeDisabled();
  expect(screen.getByLabelText("角色")).toBeDisabled();
});
