import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AdminSessionExpiredError } from "../api";
import type { NewsDecision, NewsPool, NewsReviewsApi } from "./api";
import { NewsReviewPage } from "./NewsReviewPage";

const POOL: NewsPool = {
  human_pick_enabled: false,
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
    ...overrides,
  };
}

describe("新闻审核", () => {
  it("hides the AI verdict until the item is reviewed, then records the call", async () => {
    const user = userEvent.setup();
    const calls = api();
    render(<NewsReviewPage api={calls} onSessionExpired={vi.fn()} />);

    expect(await screen.findByText("教育部部署人工智能通识教育")).toBeVisible();
    expect(screen.getByText(/盲审中/)).toBeVisible();
    expect(screen.queryByText(/AI 判断/)).toBeNull();

    await user.type(screen.getByLabelText("备注（可不填）"), "家长关心");
    await user.click(screen.getByRole("button", { name: "适合推" }));

    expect(calls.review).toHaveBeenCalledWith(
      "vn1_" + "a".repeat(24),
      "include",
      "家长关心",
    );
    expect(await screen.findByText("已记下：适合推")).toBeVisible();
    // Reviewed: the item leaves 还没审, so the next one is shown.
    expect(await screen.findByText("某地举办科技嘉年华")).toBeVisible();
    expect(screen.getByLabelText("与 AI 的一致率")).toHaveTextContent("100%");
  });

  it("shows the AI view when blind mode is off and can fill a reason as the note", async () => {
    const user = userEvent.setup();
    render(<NewsReviewPage api={api()} onSessionExpired={vi.fn()} />);
    await screen.findByText("教育部部署人工智能通识教育");
    await user.click(
      screen.getByRole("button", { name: "盲审（先不看 AI 的判断）" }),
    );
    expect(screen.getByText(/AI 判断：入选/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "像营销软文" }));
    expect(screen.getByLabelText("备注（可不填）")).toHaveValue("像营销软文");
  });

  it("shows a refusal from the API and keeps the item open", async () => {
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
    await user.click(screen.getByRole("button", { name: "不适合推" }));
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
