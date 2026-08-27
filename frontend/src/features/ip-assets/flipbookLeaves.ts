import type { IpAssetFlipbookPage } from "./flipbookDraft";

export type IpAssetFlipbookLeaf =
  | Readonly<{
      key: string;
      kind: "image";
      density: "hard" | "soft";
      page: IpAssetFlipbookPage;
    }>
  | Readonly<{
      key: "inside-back";
      kind: "blank";
      density: "soft";
    }>
  | Readonly<{
      key: "back-cover";
      kind: "back";
      density: "hard";
    }>;

export function buildIpAssetFlipbookLeaves(
  pages: readonly IpAssetFlipbookPage[],
): readonly IpAssetFlipbookLeaf[] {
  if (pages.length === 0) return [];
  const leaves: IpAssetFlipbookLeaf[] = pages.map((page, index) => ({
    key: `asset-${page.assetRef}`,
    kind: "image",
    density: index === 0 ? "hard" : "soft",
    page,
  }));
  const interiorImageCount = pages.length - 1;
  if (interiorImageCount % 2 !== 0) {
    leaves.push({ key: "inside-back", kind: "blank", density: "soft" });
  }
  leaves.push({ key: "back-cover", kind: "back", density: "hard" });
  return leaves;
}

export function deriveIpAssetFlipbookPageRatio(
  pages: readonly IpAssetFlipbookPage[],
): number {
  if (pages.length === 0) return 0.75;
  const averageRatio =
    pages.reduce((total, page) => total + page.width / page.height, 0) /
    pages.length;
  return Math.min(0.9, Math.max(0.68, averageRatio));
}
