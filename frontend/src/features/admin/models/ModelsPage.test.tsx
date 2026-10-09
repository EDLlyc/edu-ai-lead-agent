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
});
