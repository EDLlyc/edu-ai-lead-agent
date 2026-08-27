import { ipAssetResourceUrl, type IpAsset } from "./api";

export const IP_ASSET_FLIPBOOK_MIN_PAGES = 2;
export const IP_ASSET_FLIPBOOK_MAX_PAGES = 20;

export type IpAssetFlipbookPage = Readonly<{
  assetRef: string;
  canonicalName: string;
  previewUrl: string;
  width: number;
  height: number;
}>;

export type IpAssetFlipbookDraft = Readonly<{
  version: 1;
  title: string;
  pages: readonly IpAssetFlipbookPage[];
}>;

const safeAssetRefPattern = /^ipa_[a-f0-9]{20}$/;
const defaultTitle = "赛先生与小赛 · 灵感相册";
let stagedDraft: IpAssetFlipbookDraft | null = null;

export function createIpAssetFlipbookDraft(
  assets: readonly IpAsset[],
): IpAssetFlipbookDraft {
  if (
    assets.length < IP_ASSET_FLIPBOOK_MIN_PAGES ||
    assets.length > IP_ASSET_FLIPBOOK_MAX_PAGES
  ) {
    throw new Error("flipbook_page_count_invalid");
  }

  const seen = new Set<string>();
  const pages = assets.map((asset) => {
    if (
      asset.status !== "ready" ||
      !asset.shared ||
      !safeAssetRefPattern.test(asset.asset_ref) ||
      seen.has(asset.asset_ref) ||
      !isPositiveDimension(asset.width) ||
      !isPositiveDimension(asset.height)
    ) {
      throw new Error("flipbook_asset_invalid");
    }
    const previewUrl = ipAssetResourceUrl(asset.preview_url);
    if (previewUrl === null) throw new Error("flipbook_preview_invalid");
    const canonicalName = asset.canonical_name.trim();
    if (canonicalName.length === 0) throw new Error("flipbook_name_invalid");
    seen.add(asset.asset_ref);
    return {
      assetRef: asset.asset_ref,
      canonicalName,
      previewUrl,
      width: asset.width,
      height: asset.height,
    };
  });

  return { version: 1, title: defaultTitle, pages };
}

export function stageIpAssetFlipbookDraft(draft: IpAssetFlipbookDraft): void {
  stagedDraft = copyValidDraft(draft);
}

export function readStagedIpAssetFlipbookDraft(): IpAssetFlipbookDraft | null {
  return stagedDraft === null ? null : copyValidDraft(stagedDraft);
}

export function clearStagedIpAssetFlipbookDraft(): void {
  stagedDraft = null;
}

export function openIpAssetFlipbook(draft: IpAssetFlipbookDraft): void {
  stageIpAssetFlipbookDraft(draft);
  window.history.pushState(null, "", "/ip-assets/flipbook");
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function moveIpAssetFlipbookPage(
  pages: readonly IpAssetFlipbookPage[],
  from: number,
  to: number,
): readonly IpAssetFlipbookPage[] {
  if (
    from < 0 ||
    from >= pages.length ||
    to < 0 ||
    to >= pages.length ||
    from === to
  ) {
    return pages;
  }
  const next = [...pages];
  const [page] = next.splice(from, 1);
  if (page === undefined) return pages;
  next.splice(to, 0, page);
  return next;
}

export function removeIpAssetFlipbookPage(
  pages: readonly IpAssetFlipbookPage[],
  index: number,
): readonly IpAssetFlipbookPage[] {
  if (index < 0 || index >= pages.length) return pages;
  return pages.filter((_, pageIndex) => pageIndex !== index);
}

function isPositiveDimension(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0;
}

function copyValidDraft(draft: IpAssetFlipbookDraft): IpAssetFlipbookDraft {
  if (
    draft.version !== 1 ||
    draft.title.length > 80 ||
    draft.pages.length < IP_ASSET_FLIPBOOK_MIN_PAGES ||
    draft.pages.length > IP_ASSET_FLIPBOOK_MAX_PAGES
  ) {
    throw new Error("flipbook_draft_invalid");
  }
  const seen = new Set<string>();
  const pages = draft.pages.map((page) => {
    const previewUrl = ipAssetResourceUrl(page.previewUrl);
    if (
      !safeAssetRefPattern.test(page.assetRef) ||
      seen.has(page.assetRef) ||
      page.canonicalName.trim().length === 0 ||
      previewUrl === null ||
      !isPositiveDimension(page.width) ||
      !isPositiveDimension(page.height)
    ) {
      throw new Error("flipbook_draft_invalid");
    }
    seen.add(page.assetRef);
    return {
      assetRef: page.assetRef,
      canonicalName: page.canonicalName,
      previewUrl,
      width: page.width,
      height: page.height,
    };
  });
  return { version: 1, title: draft.title, pages };
}
