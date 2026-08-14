import { describe, expect, it } from "vitest";

import type { ContentEditionViewModel } from "./api";
import { shouldPollContentEdition } from "./hooks";

function edition(
  state: ContentEditionViewModel["slots"][number]["state"],
  options: Readonly<{ mode?: boolean; enabled?: boolean }> = {},
): ContentEditionViewModel {
  return {
    businessDate: "2026-08-14",
    timezone: "Asia/Shanghai",
    scoringProfile: "preview",
    slotModeEnabled: options.mode ?? true,
    slots: [
      {
        slot: "morning",
        displayName: "科教晨报",
        enabled: options.enabled ?? true,
        targetLabel: "07:30",
        windowLabel: "07:30—08:30",
        state,
        stateLabel: state,
        selectedCount: 0,
        itemLimit: 3,
        unfilledCount: 0,
        unfilledReasons: [],
        errorCode: null,
        selections: [],
      },
    ],
  };
}

describe("shouldPollContentEdition", () => {
  it.each(["missing", "preparing"] as const)(
    "polls while an enabled slot is %s",
    (state) => {
      expect(shouldPollContentEdition(edition(state))).toBe(true);
    },
  );

  it.each(["ready", "failed", "expired", "disabled"] as const)(
    "stops polling for terminal slot state %s",
    (state) => {
      expect(shouldPollContentEdition(edition(state))).toBe(false);
    },
  );

  it("does not poll before data or when the mode/slot is disabled", () => {
    expect(shouldPollContentEdition(undefined)).toBe(false);
    expect(shouldPollContentEdition(edition("missing", { mode: false }))).toBe(
      false,
    );
    expect(
      shouldPollContentEdition(edition("preparing", { enabled: false })),
    ).toBe(false);
  });
});
