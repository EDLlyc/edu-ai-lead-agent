import { describe, expect, it } from "vitest";

import type { IpAssetFlipbookPage } from "./flipbookDraft";
import {
  buildIpAssetFlipbookLeaves,
  deriveIpAssetFlipbookPageRatio,
} from "./flipbookLeaves";

const pages = [
  page("ipa_00000000000000000001", 900, 1200),
  page("ipa_00000000000000000002", 1200, 900),
  page("ipa_00000000000000000003", 1024, 1024),
];

describe("IP asset flipbook leaves", () => {
  it("marks the front and back covers hard with even interior spreads", () => {
    const leaves = buildIpAssetFlipbookLeaves(pages.slice(0, 2));

    expect(leaves.map((leaf) => leaf.kind)).toEqual([
      "image",
      "image",
      "blank",
      "back",
    ]);
    expect(leaves.map((leaf) => leaf.density)).toEqual([
      "hard",
      "soft",
      "soft",
      "hard",
    ]);
  });

  it("does not add a blank when interior image leaves are already even", () => {
    expect(buildIpAssetFlipbookLeaves(pages).map((leaf) => leaf.kind)).toEqual([
      "image",
      "image",
      "image",
      "back",
    ]);
  });

  it("bounds the physical page ratio for mixed source dimensions", () => {
    expect(deriveIpAssetFlipbookPageRatio(pages)).toBe(0.9);
    expect(
      deriveIpAssetFlipbookPageRatio([page("ipa_00000000000000000004", 1, 8)]),
    ).toBe(0.68);
    expect(deriveIpAssetFlipbookPageRatio([])).toBe(0.75);
  });
});

function page(
  assetRef: string,
  width: number,
  height: number,
): IpAssetFlipbookPage {
  return {
    assetRef,
    canonicalName: `${assetRef}.png`,
    previewUrl: `http://127.0.0.1:8000/api/v1/ip-assets/${assetRef}/preview`,
    width,
    height,
  };
}
