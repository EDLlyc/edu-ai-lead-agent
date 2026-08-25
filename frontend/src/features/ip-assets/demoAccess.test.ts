import { afterEach, describe, expect, it } from "vitest";

import {
  clearIpAssetDemoAccess,
  grantIpAssetDemoAccess,
  hasIpAssetDemoAccess,
  ipAssetLoginPath,
  safeIpAssetReturnTarget,
} from "./demoAccess";

afterEach(() => {
  clearIpAssetDemoAccess();
  window.history.replaceState(null, "", "/");
});

describe("IP asset demo access", () => {
  it("stores only the versioned session marker and clears it independently", () => {
    localStorage.setItem("existing-ip-profile", "keep-me");

    expect(hasIpAssetDemoAccess()).toBe(false);
    expect(grantIpAssetDemoAccess()).toBe(true);
    expect(hasIpAssetDemoAccess()).toBe(true);
    expect(sessionStorage).toHaveLength(1);

    clearIpAssetDemoAccess();

    expect(hasIpAssetDemoAccess()).toBe(false);
    expect(localStorage.getItem("existing-ip-profile")).toBe("keep-me");
    localStorage.removeItem("existing-ip-profile");
  });

  it.each([
    ["/ip-assets", "/ip-assets"],
    ["/ip-assets/", "/ip-assets/"],
    [
      "/ip-assets/create?reference=ipa_demo",
      "/ip-assets/create?reference=ipa_demo",
    ],
    [
      "/ip-assets/create/?reference=ipa_demo#ignored",
      "/ip-assets/create/?reference=ipa_demo",
    ],
  ])("accepts a known in-product return target %s", (candidate, expected) => {
    expect(safeIpAssetReturnTarget(candidate)).toBe(expected);
  });

  it.each([
    null,
    "",
    "https://evil.example/ip-assets",
    "//evil.example/ip-assets",
    "/ip-assets/login",
    "/ip-assets/archive",
    "/",
  ])("falls back for unsafe return target %s", (candidate) => {
    expect(safeIpAssetReturnTarget(candidate)).toBe("/ip-assets");
  });

  it("encodes the bounded return target in the login URL", () => {
    const loginPath = ipAssetLoginPath(
      "/ip-assets/create?reference=ipa_demo&mode=edit",
    );
    const parsed = new URL(loginPath, window.location.origin);

    expect(parsed.pathname).toBe("/ip-assets/login");
    expect(parsed.searchParams.get("returnTo")).toBe(
      "/ip-assets/create?reference=ipa_demo&mode=edit",
    );
  });
});
