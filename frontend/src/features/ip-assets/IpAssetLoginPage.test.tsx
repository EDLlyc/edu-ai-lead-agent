import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearIpAssetDemoAccess, hasIpAssetDemoAccess } from "./demoAccess";
import { IpAssetLoginPage } from "./IpAssetLoginPage";
import loginStylesheet from "./IpAssetLoginPage.module.css?inline";

afterEach(() => clearIpAssetDemoAccess());

describe("IpAssetLoginPage", () => {
  it("is responsive, motion-safe, and has no automatic accessibility violations", async () => {
    const { container } = render(
      <IpAssetLoginPage onAuthenticated={vi.fn()} returnTarget="/ip-assets" />,
    );

    expect(loginStylesheet).toMatch(/@media\s*\(max-width:\s*900px\)/);
    expect(loginStylesheet).toMatch(/@media\s*\(max-width:\s*540px\)/);
    expect(loginStylesheet).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)/,
    );
    expect((await axe(container)).violations).toEqual([]);
  });

  it("focuses the first missing field and announces invalid input", async () => {
    const user = userEvent.setup();
    render(
      <IpAssetLoginPage onAuthenticated={vi.fn()} returnTarget="/ip-assets" />,
    );

    await user.click(screen.getByRole("button", { name: "进入资产中心" }));

    expect(screen.getByLabelText("用户名")).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent("请填写用户名和密码");
  });

  it("grants a tab-scoped marker without storing the entered values", async () => {
    const user = userEvent.setup();
    const onAuthenticated = vi.fn();
    render(
      <IpAssetLoginPage
        onAuthenticated={onAuthenticated}
        returnTarget="/ip-assets/create?reference=ipa_demo"
      />,
    );

    await user.type(screen.getByLabelText("用户名"), "品牌部同事");
    await user.type(screen.getByLabelText("密码"), "temporary-value");
    await user.click(screen.getByRole("button", { name: "进入资产中心" }));

    expect(screen.getByText("信息完整，正在打开工作台。")).toBeVisible();
    await waitFor(() =>
      expect(onAuthenticated).toHaveBeenCalledWith(
        "/ip-assets/create?reference=ipa_demo",
      ),
    );
    expect(hasIpAssetDemoAccess()).toBe(true);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("品牌部同事");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(
      "temporary-value",
    );
  });

  it("keeps the user on the form and announces a session-storage failure", async () => {
    const user = userEvent.setup();
    const onAuthenticated = vi.fn();
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("Storage disabled", "SecurityError");
      });

    render(
      <IpAssetLoginPage
        onAuthenticated={onAuthenticated}
        returnTarget="/ip-assets"
      />,
    );

    await user.type(screen.getByLabelText("用户名"), "demo");
    await user.type(screen.getByLabelText("密码"), "demo");
    await user.click(screen.getByRole("button", { name: "进入资产中心" }));

    expect(await screen.findByRole("alert", { name: "" })).toHaveTextContent(
      "当前浏览器无法保存本地会话",
    );
    expect(onAuthenticated).not.toHaveBeenCalled();
    expect(hasIpAssetDemoAccess()).toBe(false);

    setItem.mockRestore();
  });
});
