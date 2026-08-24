import { describe, expect, it } from "vitest";

import { isOfficialAccountLocalEnabled } from "./featureFlag";

describe("official-account local feature flag", () => {
  it("requires both development mode and the exact opt-in value", () => {
    expect(
      isOfficialAccountLocalEnabled({
        DEV: true,
        VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED: "true",
      }),
    ).toBe(true);
    expect(
      isOfficialAccountLocalEnabled({
        DEV: false,
        VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED: "true",
      }),
    ).toBe(false);
    expect(
      isOfficialAccountLocalEnabled({
        DEV: true,
        VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED: "TRUE",
      }),
    ).toBe(false);
  });
});
