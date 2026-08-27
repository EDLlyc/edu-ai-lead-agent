import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { IpAssetFlipbookPage } from "./flipbookDraft";
import flipbookStylesheet from "./IpAssetFlipbookRenderer.module.css?inline";

const pageFlipMocks = vi.hoisted(() => ({
  flipNext: vi.fn(),
  flipPrev: vi.fn(),
  turnToNextPage: vi.fn(),
  turnToPrevPage: vi.fn(),
  turnToPage: vi.fn(),
}));

const pageFlipEvents = vi.hoisted(() => ({
  onFlip: undefined as ((event: unknown) => void) | undefined,
  onChangeOrientation: undefined as ((event: unknown) => void) | undefined,
}));

vi.mock("react-pageflip", async () => {
  const React = await import("react");
  const MockFlipBook = React.forwardRef(function MockFlipBook(
    props: Readonly<{
      children?: React.ReactNode;
      onFlip?: (event: unknown) => void;
      onChangeOrientation?: (event: unknown) => void;
      onInit?: (event: unknown) => void;
    }>,
    ref: React.ForwardedRef<unknown>,
  ) {
    const { children, onChangeOrientation, onFlip, onInit } = props;
    pageFlipEvents.onFlip = onFlip;
    pageFlipEvents.onChangeOrientation = onChangeOrientation;
    React.useImperativeHandle(ref, () => ({
      pageFlip: () => ({
        ...pageFlipMocks,
        getCurrentPageIndex: () => 0,
      }),
    }));
    React.useEffect(
      () => onInit?.({ data: { page: 0, mode: "portrait" } }),
      [onInit],
    );
    return <div data-testid="pageflip-book">{children}</div>;
  });
  return { default: MockFlipBook };
});

import { IpAssetFlipbookRenderer } from "./IpAssetFlipbookRenderer";

const pages = [
  page("ipa_00000000000000000001", "小赛挥手.png"),
  page("ipa_00000000000000000002", "赛先生读书.png"),
];

beforeEach(() => {
  vi.clearAllMocks();
  pageFlipEvents.onFlip = undefined;
  pageFlipEvents.onChangeOrientation = undefined;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("IpAssetFlipbookRenderer", () => {
  it("renders valid page classes and keeps engine leaves absolutely positioned", () => {
    const { container } = render(
      <IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />,
    );

    expect(screen.getByLabelText(/第 1 页，封面：小赛挥手/)).toHaveAttribute(
      "data-density",
      "hard",
    );
    expect(screen.getByLabelText(/第 2 页：赛先生读书/)).toHaveAttribute(
      "data-density",
      "soft",
    );
    expect(screen.getByLabelText(/内封底留白/)).toBeInTheDocument();
    expect(screen.getByLabelText(/第 4 页，封底/)).toHaveAttribute(
      "data-density",
      "hard",
    );
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(screen.getByText("第 1 / 4 页")).toBeVisible();
    expect(container.querySelector('[class~="undefined"]')).toBeNull();
    expect(flipbookStylesheet).toMatch(
      /\.[^{\s]+\.stf__item\s*\{[^}]*position:\s*absolute;/s,
    );
    expect(flipbookStylesheet).toMatch(
      /@media\s*\(max-width:\s*720px\)[\s\S]*?\.[^{\s]*stageControls[^{\s]*\s*\{[^}]*inset:\s*auto\s+8px\s+14px;[^}]*transform:\s*none;/s,
    );
  });

  it("reports desktop interior spreads while keeping covers as single pages", () => {
    render(<IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />);

    act(() => pageFlipEvents.onChangeOrientation?.({ data: "landscape" }));
    expect(screen.getByText("第 1 / 4 页")).toBeVisible();

    act(() => pageFlipEvents.onFlip?.({ data: 1 }));
    expect(screen.getByText("第 2–3 / 4 页")).toBeVisible();

    act(() => pageFlipEvents.onFlip?.({ data: 3 }));
    expect(screen.getByText("第 4 / 4 页")).toBeVisible();
  });

  it("reports a single page in portrait orientation", () => {
    render(<IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />);

    act(() => pageFlipEvents.onFlip?.({ data: 1 }));
    expect(screen.getByText("第 2 / 4 页")).toBeVisible();
  });

  it("uses explicit controls and locks them while a turn is pending", async () => {
    const user = userEvent.setup();
    render(<IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />);

    const previous = screen.getByRole("button", { name: "上一页" });
    const next = screen.getByRole("button", { name: "下一页" });
    expect(
      previous.closest('[aria-label="翻页控制"]')?.parentElement,
    ).toHaveAttribute("aria-label", "科学伙伴相册翻页区域");
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();

    await user.click(next);
    expect(pageFlipMocks.flipNext).toHaveBeenCalledOnce();
    expect(next).toBeDisabled();
    expect(screen.getByText(/翻页中/)).toBeVisible();
  });

  it("supports keyboard navigation from the named book region", () => {
    render(<IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />);

    fireEvent.keyDown(
      screen.getByRole("region", { name: "科学伙伴相册翻页区域" }),
      { key: "ArrowRight" },
    );
    expect(pageFlipMocks.flipNext).toHaveBeenCalledOnce();
  });

  it("keeps controls readable after a reduced-motion direct turn", async () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    const user = userEvent.setup();
    render(<IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />);

    const next = screen.getByRole("button", { name: "下一页" });
    await user.click(next);

    expect(pageFlipMocks.turnToNextPage).toHaveBeenCalledOnce();
    expect(pageFlipMocks.flipNext).not.toHaveBeenCalled();
    expect(screen.queryByText(/翻页中/)).not.toBeInTheDocument();
    expect(next).toBeEnabled();
  });

  it("replaces a failed preview with a named text fallback", () => {
    render(<IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />);

    fireEvent.error(screen.getByRole("img", { name: "小赛挥手.png" }));
    expect(
      screen.getByRole("img", { name: "小赛挥手.png：图片预览失败" }),
    ).toHaveTextContent("图片预览失败");
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(
      <IpAssetFlipbookRenderer pages={pages} title="科学伙伴相册" />,
    );
    expect((await axe(container)).violations).toEqual([]);
  });
});

function page(assetRef: string, canonicalName: string): IpAssetFlipbookPage {
  return {
    assetRef,
    canonicalName,
    previewUrl: `http://127.0.0.1:8000/api/v1/ip-assets/${assetRef}/preview`,
    width: 900,
    height: 1200,
  };
}
