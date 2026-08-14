import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/schema";

import { mapContentEdition } from "./api";

type Response = components["schemas"]["ContentEditionResponse"];
type Selection = components["schemas"]["ContentEditionSelectionResponse"];

function selection(ordinal: number, state: Selection["state"]): Selection {
  return {
    selection_id: `00000000-0000-4000-8000-00000000000${ordinal}`,
    ordinal,
    event_id: `10000000-0000-4000-8000-00000000000${ordinal}`,
    event_version_id: `20000000-0000-4000-8000-00000000000${ordinal}`,
    title: `独立新闻 ${ordinal}`,
    event_time: "2026-08-14T03:00:00Z",
    source_links: [
      {
        source_name: "科技日报",
        title: `权威原文 ${ordinal}`,
        url: `https://example.test/source-${ordinal}`,
      },
    ],
    copy_generation_run_id: null,
    copy_status: state === "failed" ? "failed" : "accepted",
    copy_url: null,
    material_package_id: null,
    material_package_status: state === "failed" ? "failed" : "ready",
    material_package_url:
      state === "failed"
        ? null
        : `/api/v1/material-packages/package-${ordinal}`,
    delivery_id: null,
    delivery_status: state === "delivered" ? "delivered" : null,
    delivery_url: null,
    state,
  };
}

const response: Response = {
  business_date: "2026-08-14",
  timezone: "Asia/Shanghai",
  scoring_profile: "preview",
  slot_mode_enabled: true,
  slots: [
    {
      content_slot: "morning",
      display_name: "科教晨报",
      enabled: true,
      target_at: "2026-08-14T07:30:00+08:00",
      expires_at: "2026-08-14T08:30:00+08:00",
      state: "ready",
      run_id: "30000000-0000-4000-8000-000000000001",
      run_status: "succeeded",
      item_limit: 3,
      selected_count: 0,
      unfilled_count: 3,
      unfilled_reason_codes: ["below_threshold"],
      error_code: null,
      selections: [],
      run_url: null,
    },
    {
      content_slot: "noon",
      display_name: "午间观察",
      enabled: true,
      target_at: "2026-08-14T12:30:00+08:00",
      expires_at: "2026-08-14T13:30:00+08:00",
      state: "ready",
      run_id: "30000000-0000-4000-8000-000000000002",
      run_status: "succeeded",
      item_limit: 3,
      selected_count: 1,
      unfilled_count: 2,
      unfilled_reason_codes: ["insufficient_eligible_candidates"],
      error_code: null,
      selections: [selection(1, "ready")],
      run_url: null,
    },
    {
      content_slot: "evening",
      display_name: "晚间精选",
      enabled: true,
      target_at: "2026-08-14T18:30:00+08:00",
      expires_at: "2026-08-14T19:30:00+08:00",
      state: "ready",
      run_id: "30000000-0000-4000-8000-000000000003",
      run_status: "succeeded",
      item_limit: 3,
      selected_count: 3,
      unfilled_count: 0,
      unfilled_reason_codes: [],
      error_code: null,
      selections: [
        selection(1, "delivered"),
        selection(2, "failed"),
        selection(3, "ready"),
      ],
      run_url: null,
    },
  ],
};

describe("mapContentEdition", () => {
  it("maps zero, one and three independent items without collapsing sibling states", () => {
    const edition = mapContentEdition(response);

    expect(edition.slots.map((slot) => slot.selections.length)).toEqual([
      0, 1, 3,
    ]);
    expect(edition.slots[2]?.selections.map((item) => item.state)).toEqual([
      "delivered",
      "failed",
      "ready",
    ]);
    expect(edition.slots[0]?.unfilledReasons).toEqual(["候选未达到质量阈值"]);
    expect(edition.slots[1]?.selections[0]?.sources[0]?.label).toBe(
      "权威原文 1",
    );
  });
});

export { response as contentEditionFixture };
