import { describe, expect, it } from "vitest";

import type { DailyStats, WeChatStats } from "./api";
import { shiftDate, statsDays, statsTotal } from "./statsView";

function reading(date: string, read_user: number): DailyStats {
  return {
    date,
    read_user,
    share_user: 0,
    like_user: 0,
    zaikan_user: 0,
    comment_count: 0,
    collection_user: 0,
  };
}

function response(changes: Partial<WeChatStats> = {}): WeChatStats {
  return {
    range_start: "2028-02-28",
    range_end: "2028-03-01",
    missing_dates: [],
    synced_on: "2028-03-02",
    sync_error: null,
    daily: [],
    articles: [],
    ...changes,
  };
}

describe("statistics business dates", () => {
  it("uses calendar days through leap days and year boundaries without browser-clock input", () => {
    expect(shiftDate("2028-03-01", -1)).toBe("2028-02-29");
    expect(shiftDate("2026-01-01", -1)).toBe("2025-12-31");
    expect(statsDays(response()).map((day) => day.date)).toEqual([
      "2028-02-28",
      "2028-02-29",
      "2028-03-01",
    ]);
  });

  it("honors coverage gaps even if a stale row is also present", () => {
    const days = statsDays(
      response({
        missing_dates: ["2028-02-29"],
        daily: [
          reading("2028-02-28", 4),
          reading("2028-02-29", 100),
          reading("2028-03-01", 0),
        ],
      }),
    );
    expect(statsTotal(days, "read_user")).toBe("已知 4（缺 1 天）");
    expect(days[1]?.values).toBeNull();
  });

  it("never fabricates a zero total when every day is missing", () => {
    expect(statsTotal(statsDays(response()), "read_user")).toBe("—");
    expect(
      statsTotal(
        statsDays(
          response({
            daily: [
              reading("2028-02-28", 0),
              reading("2028-02-29", 0),
              reading("2028-03-01", 0),
            ],
          }),
        ),
        "read_user",
      ),
    ).toBe("0");
  });
});
