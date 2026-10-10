import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import type { WeChatStats } from "./api";
import { fakeWeChatApi } from "./testApi";
import { WeChatStatsPage } from "./WeChatStatsPage";

const daily = Array.from({ length: 30 }, (_, index) => ({
  date: `2026-09-${String(index + 1).padStart(2, "0")}`,
  read_user: index + 1,
  share_user: 1,
  like_user: 0,
  zaikan_user: 0,
  comment_count: 0,
  collection_user: 0,
}));

const STATS: WeChatStats = {
  range_start: "2026-09-01",
  range_end: "2026-09-30",
  missing_dates: [],
  synced_on: "2026-10-09",
  sync_error: null,
  daily,
  articles: [
    {
      msgid: "1",
      title: "科学营开营",
      url: "https://mp.weixin.qq.com/s/art1",
      publish_date: "2026-09-30",
      stat_date: "2026-10-08",
      read_user: 40,
      share_user: 5,
      collection_user: 2,
      read_delivery_rate: 0.125,
      read_finish_rate: null,
      read_avg_activetime: 1.5,
      read_sources: { 全部: 40, 公众号消息: 30, 朋友圈: 12, 其他: 0 },
    },
  ],
};

describe("公众号数据", () => {
  it("shows 7-day tiles, the daily chart with a table view, and the articles", async () => {
    const user = userEvent.setup();
    const view = render(
      <WeChatStatsPage
        api={fakeWeChatApi({ stats: vi.fn(() => Promise.resolve(STATS)) })}
        onSessionExpired={vi.fn()}
      />,
    );
    const tiles = await screen.findByLabelText("近 7 天");
    // Days 24..30 sum to 189; all 30 days sum to 465.
    expect(
      within(tiles).getByText("近 7 天阅读人数之和").parentElement,
    ).toHaveTextContent("近 7 天阅读人数之和189近 30 天 465");
    expect(
      screen.getByRole("img", { name: /近 30 天合计 465，最高 30/ }),
    ).toBeInTheDocument();

    const bar = view.container.querySelector('rect[data-day="2026-09-30"]');
    expect(bar).not.toBeNull();
    await user.hover(bar!);
    expect(screen.getByRole("status")).toHaveTextContent(
      "09/30 阅读 30 · 分享 1",
    );

    const rows = screen.getAllByRole("row");
    const article = rows.find((row) => row.textContent?.includes("科学营开营"));
    expect(article).toHaveTextContent("科学营开营2026/09/3040521");
    expect(article).toHaveTextContent("12.5%");
    expect(article).toHaveTextContent("公众号消息 30、朋友圈 12");
    expect((await axe(view.container)).violations).toEqual([]);
  });

  it("syncs on request and shows a failed sync", async () => {
    const user = userEvent.setup();
    const calls = fakeWeChatApi({
      stats: vi.fn(() =>
        Promise.resolve({
          ...STATS,
          sync_error:
            "公众号没有这个接口的权限（需要认证或开通）（微信错误码 48001）",
        }),
      ),
    });
    render(<WeChatStatsPage api={calls} onSessionExpired={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "上次同步失败：公众号没有这个接口的权限",
    );
    await user.click(screen.getByRole("button", { name: "立即同步" }));
    expect(calls.syncStats).toHaveBeenCalledOnce();
    expect(
      await screen.findByText("已同步：1 篇文章、30 天的有效公众号数据"),
    ).toBeInTheDocument();
  });

  it("explains an account that was never synced", async () => {
    render(
      <WeChatStatsPage
        api={fakeWeChatApi({
          stats: vi.fn(() =>
            Promise.resolve({
              range_start: "2026-09-01",
              range_end: "2026-09-30",
              missing_dates: daily.map((row) => row.date),
              synced_on: null,
              sync_error: null,
              daily: [],
              articles: [],
            }),
          ),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(/同步后这里显示近 30 天的阅读走势/),
    ).toBeInTheDocument();
    expect(screen.getByText(/还没同步过/)).toBeInTheDocument();
  });
  it("uses calendar bounds across gaps and ignores today/future rows", async () => {
    const user = userEvent.setup();
    const view = render(
      <WeChatStatsPage
        api={fakeWeChatApi({
          stats: vi.fn(() =>
            Promise.resolve({
              ...STATS,
              daily: [
                daily[19]!,
                daily[23]!,
                daily[29]!,
                { ...daily[0]!, date: "2026-10-01", read_user: 9999 },
              ],
              missing_dates: daily
                .filter((_, index) => ![19, 23, 29].includes(index))
                .map((row) => row.date),
            }),
          ),
        })}
        onSessionExpired={vi.fn()}
      />,
    );
    const tiles = await screen.findByLabelText("近 7 天");
    expect(
      within(tiles).getByText("近 7 天阅读人数之和").parentElement,
    ).toHaveTextContent("已知 54（缺 5 天）近 30 天 已知 74（缺 27 天）");
    expect(screen.getByText(/已有 3\/30 天数据/)).toHaveTextContent(
      "缺少 27 天",
    );
    expect(screen.getByText(/未按整个区间去重/)).toBeInTheDocument();
    expect(
      view.container.querySelector('rect[data-day="2026-10-01"]'),
    ).toBeNull();
    await user.hover(
      view.container.querySelector('rect[data-day="2026-09-29"]')!,
    );
    expect(screen.getByRole("status")).toHaveTextContent("09/29 缺少数据");
    await user.click(screen.getByText("看表格"));
    expect(
      screen
        .getAllByRole("row")
        .find((row) => row.textContent?.startsWith("09/29")),
    ).toHaveTextContent("缺少数据");
  });

  it("shows a measured zero differently from no measurements", async () => {
    const response = {
      ...STATS,
      daily: daily.map((row) => ({ ...row, read_user: 0 })),
    };
    render(
      <WeChatStatsPage
        api={fakeWeChatApi({ stats: vi.fn(() => Promise.resolve(response)) })}
        onSessionExpired={vi.fn()}
      />,
    );
    const tiles = await screen.findByLabelText("近 7 天");
    expect(
      within(tiles).getByText("近 7 天阅读人数之和").parentElement,
    ).toHaveTextContent("近 7 天阅读人数之和0近 30 天 0");
    expect(screen.getByRole("img", { name: /最高 0/ })).toBeInTheDocument();
  });

  it("resets chart details when switching accounts and ignores stale replies", async () => {
    const user = userEvent.setup();
    let loadFirst: (value: WeChatStats) => void = () => {};
    const pending = new Promise<WeChatStats>((resolve) => {
      loadFirst = resolve;
    });
    const api = fakeWeChatApi({
      options: vi.fn(() =>
        Promise.resolve([
          { id: "one", name: "一号", topics: [] },
          { id: "two", name: "二号", topics: [] },
        ]),
      ),
      stats: vi.fn((id) =>
        id === "one"
          ? pending
          : Promise.resolve({
              ...STATS,
              articles: [],
              daily: daily.map((row) => ({ ...row, read_user: 2 })),
            }),
      ),
    });
    const view = render(
      <WeChatStatsPage api={api} onSessionExpired={vi.fn()} />,
    );
    const select = await screen.findByRole("combobox", { name: "公众号" });
    await user.selectOptions(select, "two");
    expect(
      await screen.findByRole("img", { name: /合计 60/ }),
    ).toBeInTheDocument();
    await user.hover(
      view.container.querySelector('rect[data-day="2026-09-30"]')!,
    );
    expect(screen.getByRole("status")).toHaveTextContent("阅读 2");
    await act(async () => {
      loadFirst(STATS);
      await pending;
    });
    expect(screen.getByRole("img", { name: /合计 60/ })).toBeInTheDocument();
    expect(screen.queryByText("科学营开营")).not.toBeInTheDocument();
    await user.selectOptions(select, "one");
    expect(
      await screen.findByRole("img", { name: /合计 465/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/09\/30 阅读 2/)).not.toBeInTheDocument();
  });
});
