import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import {
  clearIpAssetDemoAccess,
  grantIpAssetDemoAccess,
  hasIpAssetDemoAccess,
} from "./demoAccess";
import { IpAssetLogoutButton } from "./IpAssetLogoutButton";
import { loadLocalIpAssetProfile, saveLocalIpAssetProfile } from "./profile";

const localProfile = {
  token: "A".repeat(43),
  profileRef: `ipp_${"a".repeat(20)}`,
  displayName: "内容同事",
  department: "品牌部",
};

afterEach(() => {
  clearIpAssetDemoAccess();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("IpAssetLogoutButton", () => {
  it("ends only demo access and returns to login with the current IP route", async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      null,
      "",
      "/ip-assets/create?reference=ipa_demo",
    );
    saveLocalIpAssetProfile(localProfile);
    grantIpAssetDemoAccess();
    render(<IpAssetLogoutButton className="logout" />);

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    expect(hasIpAssetDemoAccess()).toBe(false);
    expect(window.location.pathname).toBe("/ip-assets/login");
    expect(new URLSearchParams(window.location.search).get("returnTo")).toBe(
      "/ip-assets/create?reference=ipa_demo",
    );
    expect(loadLocalIpAssetProfile()).toEqual(localProfile);
  });
});
