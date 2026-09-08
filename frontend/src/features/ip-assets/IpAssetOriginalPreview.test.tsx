import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { IpAsset } from "./api";
import { IpAssetOriginalPreview } from "./IpAssetOriginalPreview";
import mediaStylesheet from "./IpAssetOriginalPreview.module.css?inline";

const profile = {
  profileRef: "ipp_preview",
  token: "A".repeat(43),
  displayName: "同事",
  department: "品牌部",
};
const asset: IpAsset = {
  asset_ref: "ipa_preview",
  canonical_name: "小赛课堂原图",
  action: "挥手",
  asset_type: "scene_illustration",
  byte_size: 2048,
  character: "xiao_sai",
  contributor: "内容组",
  created_at: "2026-09-08T08:00:00Z",
  department: "品牌部",
  download_url: "/api/v1/ip-assets/ipa_preview/download",
  emotion: "开心",
  favorite: false,
  has_alpha: true,
  height: 720,
  intended_use: "社群",
  media_type: "image/png",
  orientation: "landscape",
  thumbnail_url: "/api/v1/ip-assets/ipa_preview/thumbnail?v=1",
  preview_url: "/api/v1/ip-assets/ipa_preview/preview",
  scene: "课堂",
  semantic_status: "ready",
  shared: true,
  source_kind: "uploaded",
  status: "ready",
  style: "3D",
  tags: [],
  width: 1280,
};
const BrowserURL = URL;
const createObjectURL = vi.fn(() => "blob:original-preview");
const revokeObjectURL = vi.fn();
const fetchMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "URL",
    class extends BrowserURL {
      static createObjectURL = createObjectURL;
      static revokeObjectURL = revokeObjectURL;
    },
  );
  fetchMock.mockImplementation(() =>
    Promise.resolve(new Response(new Blob(["preview"], { type: "image/png" }))),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("IpAssetOriginalPreview", () => {
  it("opens an original-ratio image by keyboard with a named, contained and restoring dialog", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <>
        <button type="button">外部操作</button>
        <IpAssetOriginalPreview asset={asset} profile={profile} />
      </>,
    );
    const original = screen.getByRole("img", { name: asset.canonical_name });
    expect(original).toHaveAttribute(
      "src",
      expect.stringContaining(asset.preview_url),
    );
    expect(original).not.toHaveAttribute(
      "src",
      expect.stringContaining("thumbnail"),
    );
    expect(original).toHaveAttribute("width", "1280");
    expect(original).toHaveAttribute("height", "720");
    fireEvent.load(original);
    const trigger = screen.getByRole("button", {
      name: `放大查看 ${asset.canonical_name}`,
    });
    trigger.focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: asset.canonical_name });
    const close = within(dialog).getByRole("button", { name: "关闭原图预览" });
    expect(close).toHaveFocus();
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "正在读取原图",
    );
    fireEvent.load(within(dialog).getByRole("img"));
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
    screen.getByRole("button", { name: "外部操作" }).focus();
    expect(close).toHaveFocus();
    expect((await axe(container)).violations).toEqual([]);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
    await user.click(trigger);
    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(screen.getByRole("dialog")).toBeVisible();
    const backdrop = screen.getByRole("dialog").parentElement;
    if (backdrop === null) throw new Error("backdrop_missing");
    fireEvent.mouseDown(backdrop);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "关闭原图预览" }));
    expect(trigger).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mediaStylesheet).toMatch(/object-fit:\s*contain/);
  });

  it("loads private original bytes only with the profile header and reuses the blob for zoom", async () => {
    const user = userEvent.setup();
    const view = render(
      <IpAssetOriginalPreview
        asset={{ ...asset, shared: false }}
        profile={profile}
      />,
    );
    const image = await screen.findByRole("img");
    expect(image).toHaveAttribute("src", "blob:original-preview");
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      expect.stringContaining(asset.preview_url),
      { headers: { "X-IP-Profile-Token": profile.token } },
    );
    await user.click(screen.getByRole("button", { name: /放大查看/ }));
    expect(within(screen.getByRole("dialog")).getByRole("img")).toHaveAttribute(
      "src",
      "blob:original-preview",
    );
    await user.keyboard("{Escape}");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(view.container.innerHTML).not.toContain(profile.token);
    expect(revokeObjectURL).not.toHaveBeenCalled();
    view.unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:original-preview");
  });

  it("revokes media and closes zoom on profile change, then ignores late private responses", async () => {
    const user = userEvent.setup();
    const view = render(
      <IpAssetOriginalPreview
        asset={{ ...asset, shared: false }}
        profile={profile}
      />,
    );
    await screen.findByRole("img");
    await user.click(screen.getByRole("button", { name: /放大查看/ }));
    let resolveFetch: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    view.rerender(
      <IpAssetOriginalPreview
        asset={{ ...asset, shared: false }}
        profile={{ ...profile, profileRef: "ipp_next", token: "B".repeat(43) }}
      />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:original-preview");
    expect(screen.getByRole("status")).toHaveTextContent("正在读取原图");
    view.unmount();
    await act(() =>
      Promise.resolve(resolveFetch?.(new Response(new Blob(["late"])))),
    );
    expect(createObjectURL).toHaveBeenCalledOnce();
  });

  it("shows named fetch and decode failures without losing the zoom close control", async () => {
    const user = userEvent.setup();
    const view = render(
      <IpAssetOriginalPreview asset={asset} profile={profile} />,
    );
    const trigger = screen.getByRole("button", { name: /放大查看/ });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog");
    fireEvent.error(within(dialog).getByRole("img"));
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      `${asset.canonical_name} · 原图预览不可用`,
    );
    expect(within(dialog).queryByRole("img")).toBeNull();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
    view.unmount();
    fetchMock.mockRejectedValue(new Error("network"));
    render(
      <IpAssetOriginalPreview
        asset={{ ...asset, shared: false }}
        profile={profile}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("原图预览不可用"),
    );
    expect(screen.queryByRole("img")).toBeNull();
  });

  it.each([
    { preview_url: "https://outside.example/image.png" },
    { preview_url: "javascript:alert(1)" },
    { preview_url: asset.download_url },
    { preview_url: `${asset.preview_url}?token=unsafe` },
    { preview_url: "/api/v1/ip-assets/ipa_other/preview" },
    { status: "processing" },
  ] satisfies readonly Partial<IpAsset>[])(
    "refuses unsafe or unready original resources: %j",
    (override) => {
      render(
        <IpAssetOriginalPreview
          asset={{ ...asset, ...override, shared: false }}
          profile={profile}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent("原图预览不可用");
      expect(screen.queryByRole("img")).toBeNull();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("does not fetch private media without a profile", () => {
    render(
      <IpAssetOriginalPreview
        asset={{ ...asset, shared: false }}
        profile={null}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("原图预览不可用");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
