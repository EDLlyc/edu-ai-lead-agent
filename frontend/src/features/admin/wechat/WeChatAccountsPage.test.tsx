import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { UnsavedChangesProvider } from "../unsaved/UnsavedChanges";
import { describe, expect, it, vi } from "vitest";

import { ACCOUNT, fakeWeChatApi } from "./testApi";
import { WeChatAccountsPage } from "./WeChatAccountsPage";

describe("公众号账号", () => {
  it("lists accounts with only the secret's last four characters", async () => {
    const view = render(
      <WeChatAccountsPage api={fakeWeChatApi()} onSessionExpired={vi.fn()} />,
    );
    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent(
      "赛先生wx0123456789abcdef••••cdef科学、教育通过",
    );
    expect((await axe(view.container)).violations).toEqual([]);
  });

  it("binds an account after verification and retains failed inputs only in memory", async () => {
    const user = userEvent.setup();
    const bind = vi
      .fn()
      .mockRejectedValueOnce(
        new Error("微信验证没通过：AppSecret 不对（微信错误码 40125）"),
      )
      .mockResolvedValueOnce(ACCOUNT);
    render(
      <WeChatAccountsPage
        api={fakeWeChatApi({ bind })}
        onSessionExpired={vi.fn()}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "绑定公众号" }));
    const form = screen.getByRole("form", { name: "绑定公众号" });
    await user.type(within(form).getByLabelText("名称"), "赛先生");
    await user.type(within(form).getByLabelText("AppID"), "wx0123456789abcdef");
    await user.type(
      within(form).getByLabelText("AppSecret"),
      "wrong-secret-value",
    );
    await user.type(within(form).getByLabelText(/主题/), "科学 教育");
    await user.click(within(form).getByRole("button", { name: "验证并绑定" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "AppSecret 不对",
    );
    expect(within(form).getByLabelText("AppSecret")).toHaveValue(
      "wrong-secret-value",
    );
    await user.clear(within(form).getByLabelText("AppSecret"));

    await user.type(
      within(form).getByLabelText("AppSecret"),
      "0123456789abcdef0123456789abcdef",
    );
    await user.click(within(form).getByRole("button", { name: "验证并绑定" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已绑定「赛先生」，验证通过",
    );
    expect(bind).toHaveBeenLastCalledWith({
      name: "赛先生",
      appId: "wx0123456789abcdef",
      appSecret: "0123456789abcdef0123456789abcdef",
      topics: ["科学", "教育"],
    });
  });

  it("says when the server has no encryption key", async () => {
    render(
      <WeChatAccountsPage
        api={fakeWeChatApi({
          status: vi.fn(() => Promise.resolve({ secretKeyConfigured: false })),
          accounts: vi.fn(() => Promise.resolve([])),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    expect(await screen.findByText(/还没配置加密密钥/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "绑定公众号" })).toBeDisabled();
  });

  it("verifies and disables an account", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      verify: vi.fn(() =>
        Promise.resolve({
          ...ACCOUNT,
          last_verify_error: "AppSecret 不对（微信错误码 40125）",
        }),
      ),
      update: vi.fn(() => Promise.resolve({ ...ACCOUNT, enabled: false })),
    });
    render(<WeChatAccountsPage api={calls} onSessionExpired={vi.fn()} />);
    const row = (await screen.findAllByRole("row"))[1]!;
    await user.click(within(row).getByRole("button", { name: "验证" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "「赛先生」AppSecret 不对",
    );
    await user.click(within(row).getByRole("button", { name: "停用" }));
    expect(calls.update).toHaveBeenCalledWith(ACCOUNT.id, { enabled: false });
  });
});

it("protects binding credentials when opening an existing account and keeps failed updates", async () => {
  const user = userEvent.setup();
  const calls = fakeWeChatApi({
    update: vi.fn(() => Promise.reject(new Error("保存失败"))),
  });
  render(
    <UnsavedChangesProvider>
      <WeChatAccountsPage api={calls} onSessionExpired={vi.fn()} />
    </UnsavedChangesProvider>,
  );
  await user.click(await screen.findByRole("button", { name: "绑定公众号" }));
  await user.type(screen.getByLabelText("AppSecret"), "memory-only-secret");
  await user.click(screen.getByRole("button", { name: "修改" }));
  await user.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(screen.getByLabelText("AppSecret")).toHaveValue("memory-only-secret");
  await user.click(screen.getByRole("button", { name: "修改" }));
  await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
  expect(
    screen.queryByRole("form", { name: "绑定公众号" }),
  ).not.toBeInTheDocument();
  await user.type(
    screen.getByLabelText("新的 AppSecret（不换就留空）"),
    "updated-fake-secret",
  );
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
  expect(screen.getByLabelText("新的 AppSecret（不换就留空）")).toHaveValue(
    "updated-fake-secret",
  );
  await user.click(screen.getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

it("freezes account and credential fields while binding", async () => {
  const user = userEvent.setup();
  const calls = fakeWeChatApi({
    bind: vi.fn(() => new Promise<typeof ACCOUNT>(() => undefined)),
  });
  render(<WeChatAccountsPage api={calls} onSessionExpired={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "绑定公众号" }));
  const form = screen.getByRole("form", { name: "绑定公众号" });
  await user.type(within(form).getByLabelText("名称"), "科学");
  await user.type(within(form).getByLabelText("AppID"), "wx-test");
  await user.type(within(form).getByLabelText("AppSecret"), "fake-secret");
  await user.click(within(form).getByRole("button", { name: "验证并绑定" }));
  for (const name of ["名称", "AppID", "AppSecret", /主题（可选/]) {
    expect(within(form).getByLabelText(name)).toBeDisabled();
  }
});
