import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { HeldPickReview, NewsPick, NewsPool, NewsReviewsApi } from "./api";
import { NewsReviewApiError } from "./api";
import { NewsReviewPage } from "./NewsReviewPage";

const PICKED = "vn1_" + "a".repeat(24);
const DROPPED = "vn1_" + "b".repeat(24);

function poolWith(pick: NewsPick | null): NewsPool {
  return {
    human_pick_enabled: true,
    human_pick_review_enabled: true,
    review_enabled: true,
    batches: [
      {
        business_date: "2026-10-15",
        slot: "morning",
        target_at: "2026-10-15T01:00:00Z",
        total_count: 2,
        eligible_count: 1,
        selected_count: 1,
        candidates: [
          {
            key: PICKED,
            title: "教育部部署人工智能通识教育",
            score: 0.71,
            threshold: 0.59,
            rank: 1,
            verdict: "selected",
          },
          {
            key: DROPPED,
            title: "某地举办科技嘉年华",
            score: 0.41,
            threshold: 0.59,
            rank: 5,
            verdict: "rejected",
            reasons: ["below_threshold"],
            ...(pick === null ? {} : { human_pick: pick }),
          },
        ],
      },
    ],
  };
}

const REVIEW: HeldPickReview = {
  stage: "awaiting_review",
  editable: true,
  push_deadline: "2026-10-15T14:30:00Z",
  copywriting: "🔎【小赛洞察】\n某地举办科技嘉年华\n孩子可以动手试试✨",
  heading: "🔎【小赛洞察】",
  headline: ["某地举办科技嘉年华"],
  hook: "孩子可以动手试试✨",
  source_line: "新闻来源：某媒体",
  link_line: "原文链接：https://example.org/a",
  hashtags: ["#科学思维"],
  issues: [],
};

function api(pick: NewsPick | null, overrides: Partial<NewsReviewsApi> = {}) {
  return {
    load: vi.fn(() => Promise.resolve(poolWith(pick))),
    review: vi.fn(() => Promise.reject(new Error("not used"))),
    createPick: vi.fn(() =>
      Promise.resolve({
        stage: "queued",
        picked_at: "2026-10-15T05:00:00Z",
      } as const),
    ),
    loadReview: vi.fn(() => Promise.resolve(REVIEW)),
    revise: vi.fn(
      (
        _key: string,
        input: {
          hook: string;
          hashtags: readonly string[];
          dryRun: boolean;
        },
      ) =>
        Promise.resolve({
          ...REVIEW,
          hook: input.hook,
          hashtags: [...input.hashtags],
          saved: !input.dryRun,
          passed: true,
        }),
    ),
    push: vi.fn(() =>
      Promise.resolve({
        stage: "sending",
        picked_at: "2026-10-15T05:00:00Z",
      } as const),
    ),
    ...overrides,
  } satisfies NewsReviewsApi;
}

const HELD: NewsPick = {
  stage: "awaiting_review",
  picked_at: "2026-10-15T05:00:00Z",
};

describe("人工加推", () => {
  it("offers a pick only for items the AI did not select, and only when enabled", async () => {
    render(<NewsReviewPage api={api(null)} onSessionExpired={vi.fn()} />);
    await screen.findByText("某地举办科技嘉年华");
    expect(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", {
        name: "加推：教育部部署人工智能通识教育",
      }),
    ).toBeNull();
  });

  it("is hidden when production does not hold picks for review", async () => {
    const disabled = {
      ...poolWith(null),
      human_pick_review_enabled: false,
    };
    render(
      <NewsReviewPage
        api={api(null, { load: () => Promise.resolve(disabled) })}
        onSessionExpired={vi.fn()}
      />,
    );
    await screen.findByText("某地举办科技嘉年华");
    expect(screen.queryByRole("button", { name: /^加推：/ })).toBeNull();
  });

  it("starts a pick without sending anything and shows its progress", async () => {
    const user = userEvent.setup();
    const calls = api(null);
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("某地举办科技嘉年华");

    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    await user.click(screen.getByRole("button", { name: "生成文案和配图" }));
    expect(calls.createPick).toHaveBeenCalledWith(DROPPED);
    expect(calls.push).not.toHaveBeenCalled();
    expect(await screen.findByText(/已开始生成文案和配图/)).toBeVisible();
    expect(screen.getByText("加推：排队中")).toBeVisible();
  });

  it("shows a refusal from production in plain words", async () => {
    const user = userEvent.setup();
    const calls = api(null, {
      createPick: vi.fn(() =>
        Promise.reject(
          new NewsReviewApiError("22:30 以后不再加推，请明天再试"),
        ),
      ),
    });
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("某地举办科技嘉年华");
    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    await user.click(screen.getByRole("button", { name: "生成文案和配图" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("22:30");
  });

  it("refreshes the progress by hand while the copy is being made", async () => {
    const user = userEvent.setup();
    const calls = api({ stage: "writing", picked_at: HELD.picked_at });
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("加推：正在写文案");
    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    expect(screen.getByText(/页面会自动刷新进度/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "刷新进度" }));
    await waitFor(() => expect(calls.load).toHaveBeenCalledTimes(2));
  });

  it("reviews, checks, saves and pushes only after two confirmations", async () => {
    const user = userEvent.setup();
    const calls = api(HELD);
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("加推：等你确认");
    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    const editor = await screen.findByRole("group", { name: "审核加推文案" });

    // Edit the hook: pushing is blocked until the edit is saved.
    const hook = within(editor).getByLabelText("引导语（可改）");
    await user.clear(hook);
    await user.type(hook, "全家一起来试试");
    const push = within(editor).getByRole("button", {
      name: "推送到正式群",
    });
    expect(push).toBeDisabled();

    await user.click(within(editor).getByRole("button", { name: "检查文案" }));
    expect(calls.revise).toHaveBeenLastCalledWith(DROPPED, {
      hook: "全家一起来试试",
      hashtags: ["#科学思维"],
      dryRun: true,
    });
    expect(await within(editor).findByText("检查通过")).toBeVisible();
    expect(push).toBeDisabled();

    await user.click(within(editor).getByRole("button", { name: "保存修改" }));
    expect(await within(editor).findByText("已保存")).toBeVisible();
    expect(push).toBeEnabled();

    // First confirmation shows the exact copy; nothing is sent yet.
    await user.click(push);
    expect(
      within(editor).getByRole("group", { name: "确认推送" }),
    ).toBeVisible();
    await user.click(within(editor).getByRole("button", { name: "确认推送" }));
    expect(calls.push).not.toHaveBeenCalled();

    // Second confirmation sends.
    expect(
      within(editor).getByRole("alertdialog", { name: "再次确认推送" }),
    ).toHaveTextContent("不能撤回");
    await user.click(within(editor).getByRole("button", { name: "确认发送" }));
    expect(calls.push).toHaveBeenCalledTimes(1);
    expect(calls.push).toHaveBeenCalledWith(DROPPED);
    expect(await screen.findByText("加推：正在发送")).toBeVisible();
  });

  it("cancelling at either confirmation sends nothing", async () => {
    const user = userEvent.setup();
    const calls = api(HELD);
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("加推：等你确认");
    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    const editor = await screen.findByRole("group", { name: "审核加推文案" });
    await user.click(
      within(editor).getByRole("button", { name: "推送到正式群" }),
    );
    await user.click(within(editor).getByRole("button", { name: "取消" }));
    await user.click(
      within(editor).getByRole("button", { name: "推送到正式群" }),
    );
    await user.click(within(editor).getByRole("button", { name: "确认推送" }));
    await user.click(within(editor).getByRole("button", { name: "返回" }));
    expect(calls.push).not.toHaveBeenCalled();
  });

  it("blocks the push while the saved copy has a rule error", async () => {
    const user = userEvent.setup();
    const calls = api(HELD, {
      loadReview: () =>
        Promise.resolve({
          ...REVIEW,
          issues: [
            { code: "copy_length", severity: "error", message: "引导句太长" },
          ],
        }),
    });
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("加推：等你确认");
    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    expect(await screen.findByText("引导句太长")).toBeVisible();
    expect(screen.getByRole("button", { name: "推送到正式群" })).toBeDisabled();
  });

  it("shows why a push was refused, and does not mark it sent", async () => {
    const user = userEvent.setup();
    const calls = api(HELD, {
      push: vi.fn(() =>
        Promise.reject(
          new NewsReviewApiError("已过当天 22:30，这条加推作废了"),
        ),
      ),
    });
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("加推：等你确认");
    await user.click(
      screen.getByRole("button", { name: "加推：某地举办科技嘉年华" }),
    );
    const editor = await screen.findByRole("group", { name: "审核加推文案" });
    await user.click(
      within(editor).getByRole("button", { name: "推送到正式群" }),
    );
    await user.click(within(editor).getByRole("button", { name: "确认推送" }));
    await user.click(within(editor).getByRole("button", { name: "确认发送" }));
    expect(await within(editor).findByText(/作废了/)).toBeVisible();
    expect(screen.getByText("加推：等你确认")).toBeVisible();
  });
});
