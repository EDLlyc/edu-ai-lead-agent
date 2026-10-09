import { render, screen, within } from "@testing-library/react";
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
      within(tiles).getByText("近 7 天阅读人数").parentElement,
    ).toHaveTextContent("近 7 天阅读人数189近 30 天 465");
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
      await screen.findByText("已同步：1 篇文章、30 天的公众号数据"),
    ).toBeInTheDocument();
  });

  it("explains an account that was never synced", async () => {
    render(
      <WeChatStatsPage
        api={fakeWeChatApi({
          stats: vi.fn(() =>
            Promise.resolve({
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
});
