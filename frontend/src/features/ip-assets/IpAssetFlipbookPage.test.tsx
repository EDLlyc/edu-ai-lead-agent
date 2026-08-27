import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./IpAssetFlipbookRenderer", () => ({
  IpAssetFlipbookRenderer: ({
    pages,
    title,
  }: Readonly<{
    pages: readonly Readonly<{ assetRef: string }>[];
    title: string;
  }>) => (
    <div data-testid="flipbook-renderer">
      {title}|{pages.map((page) => page.assetRef).join(",")}
    </div>
  ),
}));

import { IpAssetFlipbookPage } from "./IpAssetFlipbookPage";
import {
  clearStagedIpAssetFlipbookDraft,
  readStagedIpAssetFlipbookDraft,
  stageIpAssetFlipbookDraft,
  type IpAssetFlipbookDraft,
} from "./flipbookDraft";

afterEach(() => {
  clearStagedIpAssetFlipbookDraft();
  window.history.replaceState(null, "", "/");
});

describe("IpAssetFlipbookPage", () => {
  it("fails closed with a gallery recovery link when no draft is staged", () => {
    render(<IpAssetFlipbookPage />);

    expect(
      screen.getByRole("heading", { name: "这本即时相册已经合上了" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "返回 IP 资产库" }),
    ).toHaveAttribute("href", "/ip-assets");
    expect(screen.queryByTestId("flipbook-renderer")).not.toBeInTheDocument();
  });

  it("reads before effect-clear and keeps the local draft under Strict Mode", () => {
    stageIpAssetFlipbookDraft(draft());
    window.history.replaceState(null, "", "/ip-assets/flipbook");

    render(
      <StrictMode>
        <IpAssetFlipbookPage />
      </StrictMode>,
    );

    expect(
      screen.getByRole("heading", { name: "把灵感，装订成一本相册。" }),
    ).toBeVisible();
    expect(screen.getByTestId("flipbook-renderer")).toHaveTextContent(
      "科学伙伴相册|ipa_00000000000000000001,ipa_00000000000000000002,ipa_00000000000000000003",
    );
    expect(readStagedIpAssetFlipbookDraft()).toBeNull();
    expect(window.location.search).toBe("");
    expect(
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ).not.toContain("ipa_00000000000000000001");
  });

  it("edits title and immutably reorders the first page as the cover", async () => {
    const user = userEvent.setup();
    stageIpAssetFlipbookDraft(draft());
    render(<IpAssetFlipbookPage />);

    const title = screen.getByLabelText("相册标题");
    await user.clear(title);
    await user.type(title, "内容组精选");
    expect(screen.getByTestId("flipbook-renderer")).toHaveTextContent(
      "内容组精选|",
    );

    await user.click(screen.getByRole("button", { name: "下移 小赛挥手.png" }));
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]!).getByText("赛先生读书.png")).toBeVisible();
    expect(within(items[0]!).getByText("封面")).toBeVisible();
    expect(screen.getByTestId("flipbook-renderer")).toHaveTextContent(
      "ipa_00000000000000000002,ipa_00000000000000000001,ipa_00000000000000000003",
    );
    expect(screen.getByText(/小赛挥手.*已移到第 2 位/)).toBeVisible();
  });

  it("pauses the renderer when removal leaves fewer than two pages", async () => {
    const user = userEvent.setup();
    stageIpAssetFlipbookDraft({ ...draft(), pages: draft().pages.slice(0, 2) });
    render(<IpAssetFlipbookPage />);

    await user.click(screen.getByRole("button", { name: "移除 小赛挥手.png" }));

    expect(screen.queryByTestId("flipbook-renderer")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "至少需要 2 张图片才能继续翻页",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "返回资产库选择图片" }),
    ).toHaveAttribute("href", "/ip-assets");
  });

  it("has no automatically detectable accessibility violations", async () => {
    stageIpAssetFlipbookDraft(draft());
    const { container } = render(<IpAssetFlipbookPage />);

    expect((await axe(container)).violations).toEqual([]);
  });
});

function draft(): IpAssetFlipbookDraft {
  return {
    version: 1,
    title: "科学伙伴相册",
    pages: [
      page("ipa_00000000000000000001", "小赛挥手.png"),
      page("ipa_00000000000000000002", "赛先生读书.png"),
      page("ipa_00000000000000000003", "小赛实验.png"),
    ],
  };
}

function page(assetRef: string, canonicalName: string) {
  return {
    assetRef,
    canonicalName,
    previewUrl: `http://127.0.0.1:8000/api/v1/ip-assets/${assetRef}/preview`,
    width: 900,
    height: 1200,
  } as const;
}
