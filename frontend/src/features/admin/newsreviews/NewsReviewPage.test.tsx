import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError } from "../api";
import type { NewsDecision, NewsPool, NewsReviewsApi } from "./api";
import { NewsReviewPage } from "./NewsReviewPage";

const POOL: NewsPool = {
  human_pick_enabled: false,
  human_pick_review_enabled: false,
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
          key: "vn1_" + "a".repeat(24),
          title: "教育部部署人工智能通识教育",
          source_name: "教育部",
          score: 0.71,
          threshold: 0.59,
          rank: 1,
          verdict: "selected",
        },
        {
          key: "vn1_" + "b".repeat(24),
          title: "某地举办科技嘉年华",
          score: 0.41,
          threshold: 0.59,
          rank: 5,
          verdict: "rejected",
          reasons: ["below_threshold"],
        },
      ],
    },
  ],
};

function api(overrides: Partial<NewsReviewsApi> = {}): NewsReviewsApi {
  return {
    load: vi.fn(() => Promise.resolve(POOL)),
    review: vi.fn((_key: string, decision: NewsDecision) =>
      Promise.resolve({ decision, reviewed_at: "2026-10-15T05:00:00Z" }),
    ),
    createPick: vi.fn(() => Promise.reject(new Error("not used"))),
    loadReview: vi.fn(() => Promise.reject(new Error("not used"))),
    revise: vi.fn(() => Promise.reject(new Error("not used"))),
    push: vi.fn(() => Promise.reject(new Error("not used"))),
    ...overrides,
  };
}

describe("新闻审核", () => {
  it("lists every news item in one table with the AI verdict beside it", async () => {
    render(<NewsReviewPage api={api()} onSessionExpired={vi.fn()} />);
    const rows = await screen.findAllByRole("row");
    // header + the two items
    expect(rows).toHaveLength(3);
    expect(
      within(rows[1]!).getByText("教育部部署人工智能通识教育"),
    ).toBeVisible();
    expect(within(rows[1]!).getByText("入选")).toBeVisible();
    expect(within(rows[2]!).getByText("没过线")).toBeVisible();
    expect(within(rows[2]!).getByText(/分数没过线/)).toBeVisible();
  });

  it("records a call with one click and moves the item out of 还没审", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("教育部部署人工智能通识教育");

    await user.click(
      screen.getByRole("button", {
        name: "适合推：教育部部署人工智能通识教育",
      }),
    );
    expect(calls.review).toHaveBeenCalledWith(
      "vn1_" + "a".repeat(24),
      "include",
      "",
    );
    await waitFor(() =>
      expect(screen.queryByText("教育部部署人工智能通识教育")).toBeNull(),
    );
    expect(screen.getByRole("button", { name: "还没审（1）" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "全部（2）" }));
    expect(
      screen.getByRole("button", {
        name: "适合推：教育部部署人工智能通识教育",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("与 AI 的一致率")).toHaveTextContent("100%");
  });

  it("searches title, source and notes across the current filter", async () => {
    const user = userEvent.setup();
    render(<NewsReviewPage api={api()} onSessionExpired={vi.fn()} />);
    await screen.findByText("教育部部署人工智能通识教育");
    const box = screen.getByRole("searchbox", { name: "搜索新闻" });

    await user.type(box, "嘉年华");
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(
      "找到 1 条",
    );
    expect(screen.getByText("某地举办科技嘉年华")).toBeVisible();
    expect(screen.queryByText("教育部部署人工智能通识教育")).toBeNull();

    await user.clear(box);
    await user.type(box, "教育部 人工智能");
    expect(screen.getByText("教育部部署人工智能通识教育")).toBeVisible();
    expect(screen.queryByText("某地举办科技嘉年华")).toBeNull();

    await user.clear(box);
    await user.type(box, "不存在的词");
    expect(screen.getByText(/没有找到符合的新闻/)).toBeVisible();
  });

  it("hides the AI verdict in blind mode until the item is reviewed", async () => {
    const user = userEvent.setup();
    render(<NewsReviewPage api={api()} onSessionExpired={vi.fn()} />);
    await screen.findByText("教育部部署人工智能通识教育");
    await user.click(
      screen.getByRole("button", { name: "盲审（先不看 AI 的判断）" }),
    );
    expect(screen.getAllByText("盲审中")).toHaveLength(2);
    expect(screen.queryByText("入选")).toBeNull();
  });

  it("saves a note, and a reason chip records 不适合推 with that reason", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("某地举办科技嘉年华");

    await user.click(
      screen.getByRole("button", { name: "备注：某地举办科技嘉年华" }),
    );
    const group = screen.getByRole("group", {
      name: "备注：某地举办科技嘉年华",
    });
    expect(
      within(group).getByRole("button", { name: "保存备注" }),
    ).toBeDisabled();
    await user.click(within(group).getByRole("button", { name: "像营销软文" }));
    expect(calls.review).toHaveBeenCalledWith(
      "vn1_" + "b".repeat(24),
      "exclude",
      "像营销软文",
    );
  });

  it("shows a refusal from the API and keeps the item in the list", async () => {
    const user = userEvent.setup();
    const { NewsReviewApiError } = await import("./api");
    const calls = api({
      review: vi.fn(() =>
        Promise.reject(
          new NewsReviewApiError("这条新闻已经不在最近的新闻里了"),
        ),
      ),
    });
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);
    await screen.findByText("教育部部署人工智能通识教育");
    await user.click(
      screen.getByRole("button", {
        name: "不适合推：教育部部署人工智能通识教育",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "已经不在最近的新闻里了",
    );
    expect(screen.getByText("教育部部署人工智能通识教育")).toBeVisible();
  });

  it("returns to the login when the session ended", async () => {
    const expired = vi.fn();
    render(
      <NewsReviewPage
        api={api({
          load: () => Promise.reject(new AdminSessionExpiredError()),
        })}
        onSessionExpired={expired}
      />,
    );
    await waitFor(() => expect(expired).toHaveBeenCalled());
  });
});
