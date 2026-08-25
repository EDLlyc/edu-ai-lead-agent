import { describe, expect, it } from "vitest";

import { emptyIpAssetFilters } from "./api";
import { ipAssetKeys } from "./hooks";

describe("IP asset query identities", () => {
  it("uses safe profile refs and never needs a raw local token", () => {
    const profileRef = `ipp_${"a".repeat(20)}`;
    const token = "A".repeat(43);
    const keys = [
      ipAssetKeys.list(emptyIpAssetFilters, profileRef),
      ipAssetKeys.detail("ipa_11111111111111111111", profileRef),
      ipAssetKeys.profile(profileRef),
      ipAssetKeys.personal(profileRef, "favorite"),
      ipAssetKeys.generation("ipg_11111111111111111111", profileRef),
    ];

    expect(JSON.stringify(keys)).toContain(profileRef);
    expect(JSON.stringify(keys)).not.toContain(token);
  });
});
