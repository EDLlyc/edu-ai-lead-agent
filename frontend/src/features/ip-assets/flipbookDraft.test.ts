import { afterEach, describe, expect, it } from "vitest";

import type { IpAsset } from "./api";
import {
  clearStagedIpAssetFlipbookDraft,
  createIpAssetFlipbookDraft,
  moveIpAssetFlipbookPage,
  openIpAssetFlipbook,
  readStagedIpAssetFlipbookDraft,
  removeIpAssetFlipbookPage,
  stageIpAssetFlipbookDraft,
} from "./flipbookDraft";

const firstAsset = makeAsset("ipa_00000000000000000001", "小赛挥手.png");
const secondAsset = makeAsset("ipa_00000000000000000002", "赛先生读书.png");

afterEach(() => {
  clearStagedIpAssetFlipbookDraft();
  window.history.replaceState(null, "", "/");
});

describe("IP asset flipbook draft", () => {
  it("projects ready shared assets in insertion order without cache-only fields", () => {
    const draft = createIpAssetFlipbookDraft([secondAsset, firstAsset]);

    expect(draft.pages.map((page) => page.assetRef)).toEqual([
      secondAsset.asset_ref,
      firstAsset.asset_ref,
    ]);
    expect(draft.pages[0]).toEqual({
      assetRef: secondAsset.asset_ref,
      canonicalName: secondAsset.canonical_name,
      previewUrl: `http://127.0.0.1:8000${secondAsset.preview_url}`,
      width: secondAsset.width,
      height: secondAsset.height,
    });
    expect(JSON.stringify(draft)).not.toContain("download_url");
    expect(JSON.stringify(draft)).not.toContain("contributor");
  });

  it("rejects invalid counts, duplicate refs, private rows and unsafe previews", () => {
    expect(() => createIpAssetFlipbookDraft([firstAsset])).toThrow(
      "flipbook_page_count_invalid",
    );
    expect(() => createIpAssetFlipbookDraft([firstAsset, firstAsset])).toThrow(
      "flipbook_asset_invalid",
    );
    expect(() =>
      createIpAssetFlipbookDraft([
        firstAsset,
        { ...secondAsset, shared: false },
      ]),
    ).toThrow("flipbook_asset_invalid");
    expect(() =>
      createIpAssetFlipbookDraft([
        firstAsset,
        { ...secondAsset, preview_url: "https://evil.example/image.png" },
      ]),
    ).toThrow("flipbook_preview_invalid");
  });

  it("reads a copied snapshot and clears only when explicitly consumed", () => {
    const draft = createIpAssetFlipbookDraft([firstAsset, secondAsset]);
    stageIpAssetFlipbookDraft(draft);

    const firstRead = readStagedIpAssetFlipbookDraft();
    const secondRead = readStagedIpAssetFlipbookDraft();

    expect(firstRead).toEqual(draft);
    expect(secondRead).toEqual(draft);
    expect(firstRead).not.toBe(secondRead);
    expect(firstRead?.pages).not.toBe(secondRead?.pages);
    clearStagedIpAssetFlipbookDraft();
    expect(readStagedIpAssetFlipbookDraft()).toBeNull();
  });

  it("stages before an in-app history transition without URL data", () => {
    const draft = createIpAssetFlipbookDraft([firstAsset, secondAsset]);
    openIpAssetFlipbook(draft);

    expect(window.location.pathname).toBe("/ip-assets/flipbook");
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("");
    expect(readStagedIpAssetFlipbookDraft()).toEqual(draft);
  });

  it("reorders and removes immutably while leaving invalid moves untouched", () => {
    const pages = createIpAssetFlipbookDraft([firstAsset, secondAsset]).pages;
    const moved = moveIpAssetFlipbookPage(pages, 1, 0);
    const removed = removeIpAssetFlipbookPage(moved, 1);

    expect(moved.map((page) => page.assetRef)).toEqual([
      secondAsset.asset_ref,
      firstAsset.asset_ref,
    ]);
    expect(pages[0]?.assetRef).toBe(firstAsset.asset_ref);
    expect(removed.map((page) => page.assetRef)).toEqual([
      secondAsset.asset_ref,
    ]);
    expect(moveIpAssetFlipbookPage(pages, 0, -1)).toBe(pages);
    expect(removeIpAssetFlipbookPage(pages, 5)).toBe(pages);
  });
});

function makeAsset(assetRef: string, canonicalName: string): IpAsset {
  return {
    action: "挥手",
    asset_ref: assetRef,
    asset_type: "meme_sticker",
    byte_size: 2048,
    canonical_name: canonicalName,
    character: "xiao_sai",
    contributor: "内容组",
    created_at: "2026-08-24T08:00:00Z",
    department: "品牌部",
    download_url: `/api/v1/ip-assets/${assetRef}/download`,
    emotion: "开心",
    favorite: false,
    has_alpha: true,
    height: 1200,
    intended_use: "社群",
    media_type: "image/png",
    orientation: "portrait",
    preview_url: `/api/v1/ip-assets/${assetRef}/preview`,
    scene: "",
    semantic_status: "unavailable",
    shared: true,
    source_kind: "uploaded",
    status: "ready",
    style: "3D",
    tags: ["社群", "开心"],
    width: 900,
  };
}
