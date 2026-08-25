import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearLocalIpAssetProfile,
  createLocalProfileToken,
  loadLocalIpAssetProfile,
  saveLocalIpAssetProfile,
} from "./profile";

describe("browser-local IP asset profile", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("creates a canonical 256-bit base64url token", () => {
    vi.spyOn(crypto, "getRandomValues").mockImplementation((array) => {
      const bytes = array as Uint8Array;
      bytes.forEach((_value, index) => {
        bytes[index] = index;
      });
      return array;
    });

    expect(createLocalProfileToken()).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it("round-trips only a structurally valid local profile", () => {
    const profile = {
      token: "A".repeat(43),
      profileRef: `ipp_${"a".repeat(20)}`,
      displayName: "内容同事",
      department: "品牌部",
    };

    saveLocalIpAssetProfile(profile);
    expect(loadLocalIpAssetProfile()).toEqual(profile);

    clearLocalIpAssetProfile();
    expect(loadLocalIpAssetProfile()).toBeNull();
  });

  it("removes malformed data instead of exposing it to query keys or headers", () => {
    localStorage.setItem(
      "edu-ai.ip-assets.profile.v1",
      JSON.stringify({ token: "short", profileRef: "ipp_invalid" }),
    );

    expect(loadLocalIpAssetProfile()).toBeNull();
    expect(localStorage.getItem("edu-ai.ip-assets.profile.v1")).toBeNull();
  });
});
