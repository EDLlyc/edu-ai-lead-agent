import { describe, expect, it } from "vitest";

import { isIpAssetHubEnabled } from "./featureFlag";

describe("isIpAssetHubEnabled", () => {
  it("fails closed unless explicitly enabled", () => {
    expect(isIpAssetHubEnabled({})).toBe(false);
    expect(isIpAssetHubEnabled({ VITE_IP_ASSET_HUB_ENABLED: "false" })).toBe(
      false,
    );
    expect(isIpAssetHubEnabled({ VITE_IP_ASSET_HUB_ENABLED: "true" })).toBe(
      true,
    );
  });
});
