import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError } from "../api";
import type {
  AdminSource,
  SourceArticle,
  SourceDraft,
  SourcePreview,
  SourcesApi,
} from "./api";
import { latestJobLabel } from "./labels";
import { SourcesPage } from "./SourcesPage";

const SEED: AdminSource = {
  id: "00000000-0000-0000-0000-00000000000a",
  display_name: "光明网教育",
  organization_type: "authoritative_media",
  tier: "B",
  managed_by: "seed",
  enabled: true,
  archived_at: null,
  entry_url: "https://edu.gmw.cn/",
  kind: "code",
  config: null,
  version: 3,
  robots_status: "allowed",
  latest_job: {
    status: "succeeded",
    outcome: "succeeded",
    error_code: null,
    new_count: 3,
    filtered_count: 7,
    duplicate_count: 0,
    completed_at: "2026-10-08T00:05:00Z",
  },
  new_last_7_days: 18,
};

const OPERATOR: AdminSource = {
  ...SEED,
  id: "00000000-0000-0000-0000-00000000000b",
  display_name: "示例教育网",
  managed_by: "operator",
  enabled: false,
  entry_url: "https://edu.example.cn/news/",
  kind: "html",
  config: {
    kind: "html",
    link_contains: [],
    list_selectors: [".list"],
    content_selectors: [],
  },
  version: 1,
  latest_job: null,
  new_last_7_days: 0,
};

const GOOD_PREVIEW: SourcePreview = {
  ok: true,
  robots: "allowed",
  problem: null,
  links: [
    {
      title: "人工智能教育走进中小学课堂",
      url: "https://edu.example.cn/1",
      published_at: null,
    },
    {
      title: "明星演唱会门票今日开售",
      url: "https://edu.example.cn/2",
      published_at: null,
    },
  ],
  samples: [
    {
      title: "人工智能教育走进中小学课堂",
      url: "https://edu.example.cn/1",
      published_at: "2026-10-08T00:00:00Z",
      characters: 640,
      excerpt: "教育部推动中小学开设人工智能课程",
      freshness: "fresh",
      relevant: true,
      topic: "education",
      problem: null,
    },
    {
      title: "明星演唱会门票今日开售",
      url: "https://edu.example.cn/2",
      published_at: null,
      characters: 300,
      excerpt: "某明星全国巡回演唱会",
      freshness: "unknown",
      relevant: false,
      topic: "other",
      problem: null,
    },
  ],
};

function api(overrides: Partial<SourcesApi> = {}) {
  return {
    list: vi.fn(() =>
      Promise.resolve<readonly AdminSource[]>([SEED, OPERATOR]),
    ),
    preview: vi.fn(() => Promise.resolve(GOOD_PREVIEW)),
    create: vi.fn((draft: SourceDraft) =>
      Promise.resolve({
        ...OPERATOR,
        id: "new",
        display_name: draft.display_name,
      }),
    ),
    update: vi.fn((_id: string, draft: SourceDraft) =>
      Promise.resolve({
        ...OPERATOR,
        display_name: draft.display_name,
        version: 2,
      }),
    ),
    setEnabled: vi.fn((id: string, enabled: boolean) =>
      Promise.resolve({ ...(id === SEED.id ? SEED : OPERATOR), enabled }),
    ),
    archive: vi.fn(() => Promise.resolve()),
    articles: vi.fn(() =>
      Promise.resolve<readonly SourceArticle[]>([
        {
          title: "人工智能教育走进中小学课堂",
          url: "https://edu.gmw.cn/2026-10/08/content_1.htm",
          published_at: "2026-10-08T00:00:00Z",
          fetched_at: "2026-10-08T00:05:00Z",
        },
      ]),
    ),
    ...overrides,
  } satisfies SourcesApi;
}

describe("新闻源", () => {
  it("lists sources with their last fetch and only lets operator sources be edited", async () => {
    const view = render(<SourcesPage api={api()} onSessionExpired={vi.fn()} />);
    const rows = await screen.findAllByRole("row");
    expect(rows.slice(1).map((row) => row.textContent)).toEqual([
      "光明网教育内置B 可信10/08 08:05 · 新增 3 · 过滤 718打开最近文章关闭",
      "示例教育网网页B 可信还没抓过0关闭最近文章打开修改删除",
    ]);
    expect(screen.getByText(/现在打开了 1 个/)).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole("button", { name: "修改" })).toBeNull();
    expect((await axe(view.container)).violations).toEqual([]);
  });

  it("asks before switching a source off, then reloads", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(<SourcesPage api={calls} onSessionExpired={vi.fn()} />);
    const seedRow = (await screen.findAllByRole("row"))[1]!;

    await user.click(within(seedRow).getByRole("button", { name: "关闭" }));
    const confirm = within(seedRow).getByRole("group", { name: "确认操作" });
    expect(confirm).toHaveTextContent("已抓的新闻保留");
    expect(calls.setEnabled).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "确认" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "已关闭「光明网教育」",
    );
    expect(calls.setEnabled).toHaveBeenCalledWith(SEED.id, false);
    await waitFor(() => expect(calls.list).toHaveBeenCalledTimes(2));
  });

  it("adds a source only after a preview of the same settings finds articles", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(<SourcesPage api={calls} onSessionExpired={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "新增新闻源" }));
    const form = screen.getByRole("form", { name: "新增新闻源" });

    await user.type(within(form).getByLabelText("名称"), "示例教育网");
    const url = within(form).getByLabelText(/网址/);
    await user.clear(url);
    await user.type(url, "https://edu.example.cn/news/");
    const save = within(form).getByRole("button", { name: "保存" });
    expect(save).toBeDisabled();

    await user.click(within(form).getByRole("button", { name: "预览" }));
    const result = await within(form).findByRole("region", {
      name: "预览结果",
    });
    expect(result).toHaveTextContent("找到 2 篇文章，抽查前 2 篇：1 篇会收录");
    expect(result).toHaveTextContent("科技教育，会收录");
    expect(result).toHaveTextContent("没识别到发布日期，不会收录");
    expect(calls.preview).toHaveBeenCalledWith("https://edu.example.cn/news/", {
      kind: "html",
      link_contains: [],
      list_selectors: [],
      content_selectors: [],
    });
    expect(save).toBeEnabled();

    // Changing a fetch setting needs a new preview.
    await user.click(within(form).getByText("高级设置（预览抓错了再填）"));
    await user.type(within(form).getByLabelText(/文章链接包含/), "content_");
    expect(save).toBeDisabled();
    expect(result).toHaveTextContent("设置改过了，请重新预览");
    await user.click(within(form).getByRole("button", { name: "预览" }));
    await waitFor(() => expect(save).toBeEnabled());

    await user.click(save);
    expect(calls.create).toHaveBeenCalledWith({
      display_name: "示例教育网",
      entry_url: "https://edu.example.cn/news/",
      organization_type: "authoritative_media",
      tier: "B",
      config: {
        kind: "html",
        link_contains: ["content_"],
        list_selectors: [],
        content_selectors: [],
      },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已新增「示例教育网」，现在是关闭的",
    );
    expect(screen.queryByRole("form", { name: "新增新闻源" })).toBeNull();
  });

  it("keeps save locked when the preview found a problem", async () => {
    const user = userEvent.setup();
    const calls = api({
      preview: vi.fn(() =>
        Promise.resolve<SourcePreview>({
          ok: false,
          robots: "disallowed",
          problem: "这个网站的 robots.txt 不允许抓取这个地址",
          links: [],
          samples: [],
        }),
      ),
    });
    render(<SourcesPage api={calls} onSessionExpired={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "新增新闻源" }));
    const form = screen.getByRole("form", { name: "新增新闻源" });
    await user.type(within(form).getByLabelText("名称"), "示例");
    await user.click(within(form).getByRole("button", { name: "预览" }));
    expect(
      await within(form).findByText(/robots.txt 不允许/),
    ).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("edits an operator source with its saved settings and archives it after confirmation", async () => {
    const user = userEvent.setup();
    const update = vi.fn((id: string, draft: SourceDraft) =>
      Promise.resolve({
        ...OPERATOR,
        id,
        display_name: draft.display_name,
        version: 2,
      }),
    );
    const calls = api({ update });
    render(<SourcesPage api={calls} onSessionExpired={vi.fn()} />);
    const row = (await screen.findAllByRole("row"))[2]!;

    await user.click(within(row).getByRole("button", { name: "修改" }));
    const form = screen.getByRole("form", { name: "修改新闻源" });
    expect(within(form).getByLabelText(/列表位置/)).toHaveValue(".list");
    const name = within(form).getByLabelText("名称");
    await user.clear(name);
    await user.type(name, "示例教育网（新闻）");
    await user.click(within(form).getByRole("button", { name: "预览" }));
    await user.click(await within(form).findByRole("button", { name: "保存" }));
    const [id, draft] = update.mock.calls[0]!;
    expect(id).toBe(OPERATOR.id);
    expect(draft.display_name).toBe("示例教育网（新闻）");
    expect(draft.config.list_selectors).toEqual([".list"]);
    expect(await screen.findByRole("status")).toHaveTextContent("（第 2 版）");

    const again = (await screen.findAllByRole("row"))[2]!;
    await user.click(within(again).getByRole("button", { name: "删除" }));
    await user.click(within(again).getByRole("button", { name: "确认" }));
    await waitFor(() =>
      expect(calls.archive).toHaveBeenCalledWith(OPERATOR.id),
    );
  });

  it("opens a source's latest articles in place", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(<SourcesPage api={calls} onSessionExpired={vi.fn()} />);
    const seedRow = (await screen.findAllByRole("row"))[1]!;
    const toggle = within(seedRow).getByRole("button", { name: "最近文章" });
    await user.click(toggle);
    const list = await screen.findByRole("list", { name: "最近收录的文章" });
    expect(
      within(list).getByRole("link", { name: "人工智能教育走进中小学课堂" }),
    ).toHaveAttribute("href", "https://edu.gmw.cn/2026-10/08/content_1.htm");
    expect(list).toHaveTextContent("发布 2026/10/08 · 收录 10/08 08:05");
    expect(calls.articles).toHaveBeenCalledWith(SEED.id);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(screen.queryByRole("list", { name: "最近收录的文章" })).toBeNull();
  });

  it("goes back to the login page when the session has ended", async () => {
    const expired = vi.fn();
    render(
      <SourcesPage
        api={api({
          list: vi.fn(() => Promise.reject(new AdminSessionExpiredError())),
        })}
        onSessionExpired={expired}
      />,
    );
    await waitFor(() => expect(expired).toHaveBeenCalledOnce());
  });
});

it("freezes the previewed source snapshot while saving", async () => {
  const user = userEvent.setup();
  const calls = api({
    update: vi.fn(() => new Promise<AdminSource>(() => undefined)),
  });
  render(<SourcesPage api={calls} onSessionExpired={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "修改" }));
  const form = screen.getByRole("form", { name: "修改新闻源" });
  await user.type(within(form).getByLabelText("名称"), "新名");
  await user.click(within(form).getByRole("button", { name: "预览" }));
  await user.click(await within(form).findByRole("button", { name: "保存" }));
  for (const role of ["textbox", "combobox", "radio"] as const) {
    for (const input of within(form).getAllByRole(role))
      expect(input).toBeDisabled();
  }
});

describe("latest job label", () => {
  it("states a failed fetch in words and keeps unknown codes as they are", () => {
    const failed = (error_code: string): AdminSource => ({
      ...SEED,
      latest_job: {
        ...SEED.latest_job!,
        status: "failed",
        error_code,
        completed_at: null,
      },
    });
    expect(latestJobLabel(failed("parse_failure"))).toBe(
      "失败（没有一页能读出正文）",
    );
    expect(latestJobLabel(failed("http_503"))).toBe("失败（网站返回 503）");
    expect(latestJobLabel(failed("odd_code"))).toBe("失败（odd_code）");
  });
});
