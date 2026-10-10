import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import type {
  ModelKeyConsumer,
  ModelKeyVersion,
  ModelProvider,
  ModelsApi,
} from "./api";
import { ModelsPage } from "./ModelsPage";
import { UnsavedChangesProvider } from "../unsaved/UnsavedChanges";

const ZHIPU: ModelProvider = {
  id: "zhipu",
  name: "智谱",
  used_for: "写文案、审核、识图、文字向量",
  base_url: "https://open.bigmodel.cn/api/paas/v4",
  models: ["embedding-3", "glm-5.2"],
  source: "env",
  key_hint: "••••0000",
  version: null,
  updated_by: null,
  updated_at: null,
};
const COMFLY: ModelProvider = {
  ...ZHIPU,
  id: "comfly",
  name: "Comfly",
  used_for: "生成配图",
  base_url: "https://ai.comfly.org",
  models: ["gpt-image-1"],
  source: "console",
  key_hint: "••••7777",
  version: 2,
  updated_by: "liyuchen",
  updated_at: "2026-10-09T02:00:00Z",
};

function consumer(
  service: string,
  label: string,
  versions: Record<string, number> | null,
): ModelKeyConsumer {
  return {
    service,
    label,
    reporting: true,
    versions,
    load_errors: {},
    started_at: "2026-10-09T01:00:00Z",
    seen_at: "2026-10-09T03:00:00Z",
  };
}
// Two services report Comfly v2; one still runs the old image and does not report.
const CONSUMERS: readonly ModelKeyConsumer[] = [
  consumer("acquisition-api", "接口服务", { comfly: 2 }),
  consumer("content-worker", "选题与文案", { comfly: 2 }),
  {
    ...consumer("governance-worker", "新闻治理", null),
    reporting: false,
    started_at: null,
    seen_at: null,
  },
];
const HISTORY: readonly ModelKeyVersion[] = [
  {
    version: 2,
    source: "console",
    key_hint: "••••7777",
    note: null,
    restored_from: null,
    probe_latency_ms: 300,
    created_by: "liyuchen",
    created_at: "2026-10-09T02:00:00Z",
    current: true,
  },
  {
    version: 1,
    source: "console",
    key_hint: "••••6666",
    note: "旧账号",
    restored_from: null,
    probe_latency_ms: 280,
    created_by: "liyuchen",
    created_at: "2026-10-08T02:00:00Z",
    current: false,
  },
];

function fakeApi(overrides: Partial<ModelsApi> = {}) {
  return {
    list: vi.fn(() =>
      Promise.resolve({
        secretKeyConfigured: true,
        providers: [ZHIPU, COMFLY],
        consumers: CONSUMERS,
      }),
    ),
    test: vi.fn((_id: string, key: string) =>
      Promise.resolve(
        key.startsWith("good")
          ? { ok: true, latency_ms: 320, message: "连接成功" }
          : { ok: false, latency_ms: 90, message: "key 不对" },
      ),
    ),
    save: vi.fn(() =>
      Promise.resolve({
        ...ZHIPU,
        source: "console" as const,
        key_hint: "••••1111",
        version: 1,
        updated_by: "liyuchen",
        updated_at: "2026-10-09T03:00:00Z",
      }),
    ),
    history: vi.fn(() => Promise.resolve(HISTORY)),
    restore: vi.fn(() =>
      Promise.resolve({ ...COMFLY, key_hint: "••••6666", version: 3 }),
    ),
    useEnv: vi.fn(() =>
      Promise.resolve({ ...COMFLY, source: "env" as const, version: 4 }),
    ),
    ...overrides,
  } satisfies ModelsApi;
}

describe("模型配置", () => {
  it("keeps live status visible while making secondary setup guidance available on demand", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<ModelsPage api={api} onSessionExpired={vi.fn()} />);
    expect(await screen.findByText(/有 1 个服务还没接入/)).toBeVisible();
    const guidance = screen.getByText(
      /加载失败时保留服务器配置，请查看下方各服务的状态/,
    );
    expect(guidance).not.toBeVisible();
    await user.click(screen.getByText("使用说明：测试、加载与接口配置"));
    expect(guidance).toBeVisible();
    expect(screen.getByText(/测试会用新 key 发一个很小的请求/)).toBeVisible();
    expect(screen.getByText(/接口地址和模型名固定在代码里/)).toBeVisible();
    expect(api.test).not.toHaveBeenCalled();
    expect(api.save).not.toHaveBeenCalled();
  });

  it("saves a new key only after it passes a test", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    const view = render(<ModelsPage api={api} onSessionExpired={vi.fn()} />);

    const zhipu = await screen.findByRole("listitem", { name: /智谱/ });
    expect(zhipu).toHaveTextContent("••••0000 · 服务器配置的 key");
    expect(zhipu).toHaveTextContent("glm-5.2（固定）");
    const comfly = screen.getByRole("listitem", { name: /Comfly/ });
    expect(comfly).toHaveTextContent("后台保存的第 2 版");
    expect(comfly).toHaveTextContent(
      "已在 2/2 个服务生效；1 个服务未接入，仍用服务器配置的 key",
    );
    expect(zhipu).toHaveTextContent("使用中；1 个服务未接入");
    expect(
      screen.getByText(/有 1 个服务还没接入（还在旧版本上）：新闻治理/),
    ).toBeInTheDocument();
    const services = screen.getByRole("table", { name: /各服务正在用的 key/ });
    expect(
      within(services).getByRole("row", { name: /选题与文案/ }),
    ).toHaveTextContent("选题与文案服务器配置第 2 版");
    expect(
      within(services).getByRole("row", { name: /新闻治理/ }),
    ).toHaveTextContent("未接入：还在旧版本上");
    expect((await axe(view.container)).violations).toEqual([]);

    await user.click(within(zhipu).getByRole("button", { name: "更换 key" }));
    const form = screen.getByRole("form", { name: "更换智谱的 key" });
    const save = within(form).getByRole("button", { name: "保存并启用" });
    await user.type(within(form).getByLabelText("新的 API key"), "bad-key-1");
    await user.click(within(form).getByRole("button", { name: "测试连接" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "没通过：key 不对",
    );
    expect(save).toBeDisabled();

    const input = within(form).getByLabelText("新的 API key");
    await user.clear(input);
    await user.type(input, "good-key-1111");
    expect(save).toBeDisabled();
    await user.click(within(form).getByRole("button", { name: "测试连接" }));
    expect(await within(form).findByRole("status")).toHaveTextContent(
      "连接成功，用时 320 毫秒",
    );
    await user.type(within(form).getByLabelText(/说明/), "学校账号");
    await user.click(save);
    expect(api.save).toHaveBeenCalledWith("zhipu", "good-key-1111", "学校账号");
    expect(await screen.findByText(/已保存第 1 版 key/)).toBeInTheDocument();
    expect(zhipu).toHaveTextContent("••••1111 · 后台保存的第 1 版");
    expect(zhipu).toHaveTextContent(
      "已在 0/2 个服务生效；2 个等待重启（约 2 分钟）",
    );
    expect(
      within(
        screen.getByRole("table", { name: /各服务正在用的 key/ }),
      ).getByRole("row", { name: /接口服务/ }),
    ).toHaveTextContent("服务器配置（等待重启）");
  });

  it("restores an older version and goes back to the server key", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<ModelsPage api={api} onSessionExpired={vi.fn()} />);

    const comfly = await screen.findByRole("listitem", { name: /Comfly/ });
    await user.click(within(comfly).getByRole("button", { name: "历史版本" }));
    const rows = await within(comfly).findAllByRole("row");
    expect(rows.slice(1).map((row) => row.textContent)).toEqual([
      expect.stringContaining("第 2 版（当前）••••7777"),
      expect.stringContaining("第 1 版••••6666旧账号"),
    ]);
    await user.click(
      within(rows[2]!).getByRole("button", { name: "恢复这一版" }),
    );
    await user.click(within(comfly).getByRole("button", { name: "确定恢复" }));
    expect(api.restore).toHaveBeenCalledWith("comfly", 1);
    expect(
      await screen.findByText(/已恢复第 1 版（存为第 3 版）/),
    ).toBeInTheDocument();

    await user.click(
      within(comfly).getByRole("button", { name: "改回服务器配置的 key" }),
    );
    await user.click(within(comfly).getByRole("button", { name: "确定改回" }));
    expect(api.useEnv).toHaveBeenCalledWith("comfly");
    expect(
      await screen.findByText(/已改回服务器配置的 key（第 4 版）/),
    ).toBeInTheDocument();
  });

  it("is read-only without the server key", async () => {
    render(
      <ModelsPage
        api={fakeApi({
          list: vi.fn(() =>
            Promise.resolve({
              secretKeyConfigured: false,
              providers: [ZHIPU],
              consumers: [],
            }),
          ),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    expect(await screen.findByText(/MODEL_SECRET_KEY/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更换 key" })).toBeDisabled();
  });

  it("separates a saved key from a failed load and refreshes after recovery", async () => {
    const user = userEvent.setup();
    const failed = {
      ...consumer("content-worker", "选题与文案", {}),
      load_errors: { comfly: "key_unreadable" },
    };
    const list = vi.fn<ModelsApi["list"]>().mockResolvedValue({
      secretKeyConfigured: true,
      providers: [COMFLY],
      consumers: [failed],
    });
    const api = fakeApi({ list });
    render(<ModelsPage api={api} onSessionExpired={vi.fn()} />);
    const comfly = await screen.findByRole("listitem", { name: /Comfly/ });
    expect(comfly).toHaveTextContent("后台保存的第 2 版");
    expect(comfly).toHaveTextContent(
      "已在 0/1 个服务生效；1 个加载失败，保留服务器配置",
    );
    expect(comfly).not.toHaveTextContent("等待重启");
    const services = screen.getByRole("table", { name: /各服务正在用的 key/ });
    expect(
      within(services).getByRole("row", { name: /选题与文案/ }),
    ).toHaveTextContent(
      "加载失败：已保存的 key 无法解密，保留服务器配置；请联系管理员检查",
    );

    list.mockResolvedValue({
      secretKeyConfigured: true,
      providers: [COMFLY],
      consumers: [consumer("content-worker", "选题与文案", { comfly: 2 })],
    });
    await user.click(screen.getByRole("button", { name: "刷新状态" }));
    expect(
      await within(comfly).findByText("已在 1/1 个服务生效"),
    ).toBeInTheDocument();
  });

  it("does not count legacy, failed or missing heartbeat details as loaded", async () => {
    render(
      <ModelsPage
        api={fakeApi({
          list: vi.fn(() =>
            Promise.resolve({
              secretKeyConfigured: true,
              providers: [ZHIPU, COMFLY],
              consumers: [
                {
                  ...consumer("acquisition-api", "接口服务", { comfly: 2 }),
                  load_errors: null,
                },
                {
                  ...consumer("content-worker", "选题与文案", null),
                  load_errors: {
                    zhipu: "configuration_unavailable",
                    comfly: "configuration_unavailable",
                  },
                },
                consumer("governance-worker", "新闻治理", null),
              ],
            }),
          ),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    const zhipu = await screen.findByRole("listitem", { name: /智谱/ });
    const comfly = screen.getByRole("listitem", { name: /Comfly/ });
    for (const card of [zhipu, comfly]) {
      expect(card).toHaveTextContent(
        "已在 0/3 个服务生效；1 个加载失败，保留服务器配置；2 个未报告加载状态，尚无法确认",
      );
      expect(card).not.toHaveTextContent("使用中");
    }
    expect(screen.getByRole("row", { name: /接口服务/ })).toHaveTextContent(
      "未报告加载状态，尚无法确认",
    );
    expect(screen.getByRole("row", { name: /选题与文案/ })).toHaveTextContent(
      "未能读取后台配置",
    );
  });

  it("never claims the environment key is in use without a reporting service", async () => {
    render(
      <ModelsPage
        api={fakeApi({
          list: vi.fn(() =>
            Promise.resolve({
              secretKeyConfigured: true,
              providers: [ZHIPU],
              consumers: [],
            }),
          ),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    const zhipu = await screen.findByRole("listitem", { name: /智谱/ });
    expect(zhipu).not.toHaveTextContent("使用中");
    expect(zhipu).toHaveTextContent("尚未收到服务加载状态");
  });
});

it("cancels only the selected provider form and preserves another unsaved key", async () => {
  const user = userEvent.setup();
  const calls = fakeApi();
  render(
    <UnsavedChangesProvider>
      <ModelsPage api={calls} onSessionExpired={vi.fn()} />
    </UnsavedChangesProvider>,
  );
  const buttons = await screen.findAllByRole("button", { name: "更换 key" });
  await user.click(buttons[0]!);
  const zhipu = screen.getByRole("form", { name: "更换智谱的 key" });
  await user.type(within(zhipu).getByLabelText("新的 API key"), "fake-key-one");
  await user.click(screen.getByRole("button", { name: "更换 key" }));
  const comfly = screen.getByRole("form", { name: "更换Comfly的 key" });
  await user.type(
    within(comfly).getByLabelText("新的 API key"),
    "fake-key-two",
  );
  await user.click(within(zhipu).getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "继续编辑" }));
  expect(within(zhipu).getByLabelText("新的 API key")).toHaveValue(
    "fake-key-one",
  );
  await user.click(within(zhipu).getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "放弃修改并继续" }));
  expect(
    screen.queryByRole("form", { name: "更换智谱的 key" }),
  ).not.toBeInTheDocument();
  expect(within(comfly).getByLabelText("新的 API key")).toHaveValue(
    "fake-key-two",
  );
  const reload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(reload);
  expect(reload.defaultPrevented).toBe(true);
  expect(calls.test).not.toHaveBeenCalled();
  expect(calls.save).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

it("freezes key and note while saving the tested key", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    save: vi.fn(() => new Promise<ModelProvider>(() => undefined)),
  });
  render(<ModelsPage api={calls} onSessionExpired={vi.fn()} />);
  await user.click(
    (await screen.findAllByRole("button", { name: "更换 key" }))[0]!,
  );
  const form = screen.getByRole("form", { name: "更换智谱的 key" });
  await user.type(within(form).getByLabelText("新的 API key"), "good-fake-key");
  await user.click(within(form).getByRole("button", { name: "测试连接" }));
  await user.click(
    await within(form).findByRole("button", { name: "保存并启用" }),
  );
  expect(within(form).getByLabelText("新的 API key")).toBeDisabled();
  expect(within(form).getByLabelText(/说明（可选/)).toBeDisabled();
});
