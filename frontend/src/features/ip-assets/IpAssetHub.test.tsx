import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IpAsset, IpAssetDetail } from "./api";
import ipAssetHubStylesheet from "./IpAssetHub.module.css?inline";
import {
  clearStagedIpAssetFlipbookDraft,
  readStagedIpAssetFlipbookDraft,
} from "./flipbookDraft";
import { saveLocalIpAssetProfile } from "./profile";

const apiMocks = vi.hoisted(() => ({
  getIpAssetCapabilities: vi.fn(),
  listIpAssets: vi.fn(),
  getIpAsset: vi.fn(),
  recognizeIpAsset: vi.fn(),
  uploadIpAsset: vi.fn(),
  searchIpAssetsText: vi.fn(),
  searchIpAssetsImage: vi.fn(),
  createIpAssetGeneration: vi.fn(),
  getIpAssetGeneration: vi.fn(),
  downloadIpAssetPackage: vi.fn(),
  downloadIpAssetOriginal: vi.fn().mockResolvedValue(undefined),
  recordIpAssetSearchEvent: vi.fn().mockResolvedValue(undefined),
  getIpAssetLeaderboard: vi.fn(),
  restoreIpAssetProfile: vi.fn(),
  bootstrapIpAssetProfile: vi.fn(),
  setIpAssetFavorite: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { IpAssetHub } from "./IpAssetHub";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  clearStagedIpAssetFlipbookDraft();
  window.history.replaceState(null, "", "/ip-assets");
});

const asset: IpAsset = {
  action: "挥手",
  asset_ref: "ipa_demo0001",
  asset_type: "meme_sticker",
  byte_size: 2048,
  canonical_name: "小赛-表情包-开心-挥手-社群-v001.png",
  character: "xiao_sai",
  contributor: "内容组",
  created_at: "2026-08-24T08:00:00Z",
  department: "品牌部",
  download_url: "/api/v1/ip-assets/ipa_demo0001/download",
  emotion: "开心",
  has_alpha: true,
  height: 1024,
  intended_use: "社群",
  media_type: "image/png",
  orientation: "square",
  thumbnail_url: "/api/v1/ip-assets/ipa_demo0001/thumbnail?v=1",
  preview_url: "/api/v1/ip-assets/ipa_demo0001/preview",
  scene: "",
  semantic_status: "unavailable",
  shared: true,
  favorite: false,
  source_kind: "uploaded",
  status: "ready",
  style: "3D",
  tags: ["社群", "开心"],
  width: 1024,
};

const detail: IpAssetDetail = {
  ...asset,
  checksum_ref: "sha256:" + "a".repeat(12),
  name_version: 1,
  safe_original_filename: "xiaosai.png",
};

function Providers({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderHub(
  options: Readonly<{
    generationAvailable?: boolean;
    recognitionAvailable?: boolean;
    listItems?: IpAsset[];
  }> = {},
) {
  apiMocks.getIpAssetCapabilities.mockResolvedValue({
    accepted_media_types: ["image/png", "image/jpeg", "image/webp"],
    authentication: "none",
    deployment_boundary: "company_intranet",
    enabled: true,
    generation_available: options.generationAvailable ?? false,
    max_upload_bytes: 26_214_400,
    recognition_available: options.recognitionAvailable ?? true,
    semantic_search_available: false,
  });
  apiMocks.listIpAssets.mockResolvedValue({
    items: options.listItems ?? [asset],
    next_cursor: null,
  });
  apiMocks.getIpAsset.mockResolvedValue(detail);
  apiMocks.getIpAssetLeaderboard.mockResolvedValue({
    period: "30d",
    generated_at: "2026-08-24T08:00:00Z",
    items: [{ asset, download_count: 7 }],
  });
  apiMocks.searchIpAssetsText.mockResolvedValue({
    degraded_reason: "provider_unavailable",
    items: [{ asset, explanation: "角色与用途匹配", similarity: null }],
    mode: "degraded_metadata",
    search_version: "ip-asset-hybrid-v2",
  });
  apiMocks.uploadIpAsset.mockResolvedValue({
    asset: detail,
    duplicate: false,
    near_duplicate_distance: null,
    near_duplicate_ref: null,
  });
  apiMocks.recognizeIpAsset.mockResolvedValue({
    action: "挥手",
    asset_type: "meme_sticker",
    character: "xiao_sai",
    emotion: "开心",
    intended_use: "社群推送",
    model: "glm-4.1v-thinking-flash",
    provider: "zhipu",
    scene: "科学课堂",
    status: "suggested",
    style: "3D",
    tags: ["开心", "社群"],
  });
  return render(<IpAssetHub />, { wrapper: Providers });
}

describe("IpAssetHub", () => {
  it("draws one rounded composite focus ring for the search input", () => {
    expect(ipAssetHubStylesheet).toMatch(
      /:has\(input:focus\)\s*\{[^}]*outline:\s*3px solid var\(--teal\)/s,
    );
    expect(ipAssetHubStylesheet).toMatch(
      /input:focus-visible\s*\{[^}]*outline:\s*none/s,
    );
    expect(ipAssetHubStylesheet).not.toMatch(
      /\.leaderboard\s*\{[^}]*order:\s*-1/s,
    );
  });

  it("fills an example prompt without starting a hidden search", async () => {
    const user = userEvent.setup();
    renderHub();
    const prompt = "小赛开心庆祝，适合社群推送的透明底图片";

    await user.click(await screen.findByRole("button", { name: prompt }));

    expect(screen.getByLabelText("自然语言找图")).toHaveValue(prompt);
    expect(screen.getByRole("status")).toHaveTextContent(
      "示例问题已填入，可以继续修改或开始找图",
    );
    expect(apiMocks.searchIpAssetsText).not.toHaveBeenCalled();
  });

  it("describes hybrid search results honestly", async () => {
    const user = userEvent.setup();
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: null,
      items: [
        {
          asset,
          explanation: "文字匹配: 开心; 画面语义相关",
          similarity: 0.08,
        },
      ],
      mode: "semantic",
      search_version: "ip-asset-hybrid-v2",
    });
    renderHub();
    await user.type(await screen.findByLabelText("自然语言找图"), "小赛开心");
    await user.click(screen.getByRole("button", { name: "开始找图" }));

    expect(await screen.findByText("语义 + 元数据结果")).toBeInTheDocument();
    expect(screen.getByText("含画面语义线索")).toBeVisible();
    expect(screen.queryByText(/8% 相似|语义相似度 0\.08/)).toBeNull();
  });

  it("records anonymous preview favorite and download only from search results", async () => {
    const user = userEvent.setup();
    const token = "A".repeat(43);
    saveLocalIpAssetProfile({
      token,
      profileRef: "ipp_11111111111111111111",
      displayName: "演示用户",
      department: "品牌中心",
    });
    apiMocks.restoreIpAssetProfile.mockResolvedValue({
      created_at: "2026-08-31T08:00:00Z",
      department: "品牌中心",
      display_name: "演示用户",
      identity_boundary: "browser_local_unverified",
      profile_ref: "ipp_11111111111111111111",
    });
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: null,
      items: [{ asset, explanation: "角色与动作匹配", similarity: 0.8 }],
      mode: "semantic",
      search_version: "ip-asset-hybrid-v3-rrf",
    });
    apiMocks.setIpAssetFavorite.mockResolvedValue({
      asset_ref: asset.asset_ref,
      favorite: true,
    });
    apiMocks.downloadIpAssetPackage.mockResolvedValue(undefined);
    renderHub();

    await user.type(await screen.findByLabelText("自然语言找图"), "小赛挥手");
    await user.click(screen.getByRole("button", { name: "开始找图" }));
    const cardButton = screen
      .getAllByRole("button", {
        name: (accessibleName) => accessibleName.includes(asset.canonical_name),
      })
      .find((button) => !button.hasAttribute("aria-pressed"));
    if (cardButton === undefined) throw new Error("search_card_missing");
    await user.click(cardButton);
    await user.click(screen.getByRole("button", { name: "关闭详情" }));

    await user.click(
      screen.getByRole("button", { name: `收藏 ${asset.canonical_name}` }),
    );
    await user.click(screen.getByRole("checkbox", { name: /选择 小赛/ }));
    await user.click(screen.getByRole("button", { name: "下载 ZIP + 清单" }));

    await waitFor(() =>
      expect(apiMocks.recordIpAssetSearchEvent).toHaveBeenCalledTimes(3),
    );
    const telemetryCalls = apiMocks.recordIpAssetSearchEvent.mock
      .calls as unknown as Array<[unknown]>;
    expect(telemetryCalls.map(([input]) => input)).toEqual([
      {
        eventKind: "preview_from_search",
        telemetry: {
          mode: "semantic",
          search_version: "ip-asset-hybrid-v3-rrf",
        },
      },
      {
        eventKind: "favorite_from_search",
        telemetry: {
          mode: "semantic",
          search_version: "ip-asset-hybrid-v3-rrf",
        },
      },
      {
        eventKind: "download_from_search",
        telemetry: {
          mode: "semantic",
          search_version: "ip-asset-hybrid-v3-rrf",
        },
      },
    ]);
    expect(
      JSON.stringify(apiMocks.recordIpAssetSearchEvent.mock.calls),
    ).not.toContain(token);
    expect(
      JSON.stringify(apiMocks.recordIpAssetSearchEvent.mock.calls),
    ).not.toContain(asset.asset_ref);
  });

  it("does not count a failed search-origin download", async () => {
    const user = userEvent.setup();
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: null,
      items: [{ asset, explanation: "角色与动作匹配", similarity: 0.8 }],
      mode: "semantic",
      search_version: "ip-asset-hybrid-v3-rrf",
    });
    apiMocks.downloadIpAssetPackage.mockRejectedValueOnce(
      new Error("asset_download_failed"),
    );
    renderHub();

    await user.type(await screen.findByLabelText("自然语言找图"), "小赛挥手");
    await user.click(screen.getByRole("button", { name: "开始找图" }));
    await user.click(screen.getByRole("checkbox", { name: /选择 小赛/ }));
    await user.click(screen.getByRole("button", { name: "下载 ZIP + 清单" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("ZIP 下载失败");
    expect(apiMocks.recordIpAssetSearchEvent).not.toHaveBeenCalled();
  });

  it("does not attribute a leaderboard detail download to an overlapping search result", async () => {
    const user = userEvent.setup();
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: null,
      items: [{ asset, explanation: "角色与动作匹配", similarity: 0.8 }],
      mode: "semantic",
      search_version: "ip-asset-hybrid-v3-rrf",
    });
    renderHub();

    await user.type(await screen.findByLabelText("自然语言找图"), "小赛挥手");
    await user.click(screen.getByRole("button", { name: "开始找图" }));
    await user.click(screen.getByRole("button", { name: /7 次下载/ }));
    await user.click(
      await screen.findByRole("button", { name: "下载不可变原件" }),
    );

    await waitFor(() =>
      expect(apiMocks.downloadIpAssetOriginal).toHaveBeenCalledTimes(1),
    );
    expect(apiMocks.recordIpAssetSearchEvent).not.toHaveBeenCalled();
  });

  it("keeps a successful download usable when anonymous telemetry fails", async () => {
    const user = userEvent.setup();
    const diagnostic = vi
      .spyOn(console, "warn")
      .mockImplementation(() => undefined);
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: null,
      items: [{ asset, explanation: "角色与动作匹配", similarity: 0.8 }],
      mode: "semantic",
      search_version: "ip-asset-hybrid-v3-rrf",
    });
    apiMocks.downloadIpAssetPackage.mockResolvedValueOnce(undefined);
    apiMocks.recordIpAssetSearchEvent.mockRejectedValueOnce(
      new Error("search_telemetry_failed"),
    );
    renderHub();

    await user.type(await screen.findByLabelText("自然语言找图"), "小赛挥手");
    await user.click(screen.getByRole("button", { name: "开始找图" }));
    await user.click(screen.getByRole("checkbox", { name: /选择 小赛/ }));
    await user.click(screen.getByRole("button", { name: "下载 ZIP + 清单" }));

    expect(await screen.findByText("ZIP 下载已开始。")).toBeVisible();
    await waitFor(() =>
      expect(diagnostic).toHaveBeenCalledWith(
        "IP asset anonymous search telemetry failed",
      ),
    );
    diagnostic.mockRestore();
  });

  it("shows the demo-login boundary, gallery and provider-independent controls", async () => {
    const user = userEvent.setup();
    renderHub();

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /IP 数字.*资产中心/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("公司内网 · 演示登录")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出登录" })).toBeVisible();
    expect(await screen.findByText(/AI 创作暂未启用/)).toBeInTheDocument();
    expect(screen.getByLabelText("来源")).toBeInTheDocument();
    expect(screen.getByLabelText("构图")).toBeInTheDocument();
    expect(screen.getByLabelText("标签")).toBeInTheDocument();
    const uploadButton = screen.getByRole("button", { name: "上传图片" });
    await user.click(uploadButton);
    expect(
      within(screen.getByLabelText("IP 角色 *")).queryByRole("option", {
        name: "全部",
      }),
    ).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      await screen.findByRole("img", { name: /小赛-表情包-开心-挥手/ }),
    ).toHaveAttribute("src", expect.stringContaining("/thumbnail?v=1"));

    await user.type(
      screen.getByLabelText("自然语言找图"),
      "小赛开心挥手，适合社群",
    );
    await user.click(screen.getByRole("button", { name: "开始找图" }));
    expect(await screen.findByText("元数据降级结果")).toBeInTheDocument();
    expect(
      screen.getByText("语义检索暂时不可用，已展示可用的元数据结果。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/provider_unavailable/)).toBeNull();
    expect(screen.getByText("角色与用途匹配")).toBeInTheDocument();
  });

  it("distinguishes an empty filtered pool from a partial semantic index", async () => {
    const user = userEvent.setup();
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: "no_filtered_candidates",
      items: [],
      mode: "degraded_metadata",
      search_version: "ip-asset-hybrid-v3-rrf",
    });
    renderHub();

    await user.type(await screen.findByLabelText("自然语言找图"), "双角色头像");
    await user.click(screen.getByRole("button", { name: "开始找图" }));

    expect(
      await screen.findByText(
        "当前筛选范围内没有可用图片，建议放宽角色、类型或构图筛选。",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/no_filtered_candidates/)).toBeNull();

    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: "partial_index",
      items: [{ asset, explanation: "角色提示: 小赛", similarity: null }],
      mode: "degraded_metadata",
      search_version: "ip-asset-hybrid-v3-rrf",
    });
    await user.click(screen.getByRole("button", { name: "开始找图" }));

    expect(
      await screen.findByText(
        "筛选结果暂未建立兼容语义索引，已展示可用的元数据结果。",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/partial_index/)).toBeNull();
  });

  it("uploads a bounded image with self-reported metadata", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });
    await user.click(screen.getByRole("button", { name: "上传图片" }));

    const file = new File([new Uint8Array([1, 2, 3])], "xiaosai.png", {
      type: "image/png",
    });
    await user.upload(screen.getByLabelText(/选择 PNG/), file);
    fireEvent.submit(screen.getByRole("form", { name: "上传资产" }));

    await waitFor(() =>
      expect(apiMocks.uploadIpAsset).toHaveBeenCalledWith(
        expect.objectContaining({
          file,
          character: "xiao_sai",
          assetType: "meme_sticker",
        }),
        expect.anything(),
      ),
    );
    expect(await screen.findByText(/已登记/)).toBeInTheDocument();
  });

  it("calls AI recognition only after an explicit click and keeps suggestions editable", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });
    await user.click(screen.getByRole("button", { name: "上传图片" }));

    const file = new File([new Uint8Array([1, 2, 3])], "first.png", {
      type: "image/png",
    });
    const uploadDialog = within(
      screen.getByRole("dialog", { name: "上传资产" }),
    );
    await user.click(uploadDialog.getByText("补充描述信息"));
    await user.type(uploadDialog.getByLabelText("部门（自填）"), "品牌部");
    await user.type(uploadDialog.getByLabelText("上传人（自填）"), "同事甲");
    await user.upload(uploadDialog.getByLabelText(/选择 PNG/), file);

    expect(apiMocks.recognizeIpAsset).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "AI 辅助识别" }));

    expect(await screen.findByText("AI 建议，请确认")).toBeInTheDocument();
    expect(apiMocks.recognizeIpAsset).toHaveBeenCalledWith(
      file,
      expect.anything(),
    );
    expect(uploadDialog.getByLabelText("部门（自填）")).toHaveValue("品牌部");
    expect(uploadDialog.getByLabelText("上传人（自填）")).toHaveValue("同事甲");
    expect(uploadDialog.getByLabelText("情绪")).toHaveValue("开心");
    expect(uploadDialog.getByLabelText("场景")).toHaveValue("科学课堂");
    expect(apiMocks.uploadIpAsset).not.toHaveBeenCalled();

    await user.clear(uploadDialog.getByLabelText("情绪"));
    await user.type(uploadDialog.getByLabelText("情绪"), "兴奋");
    fireEvent.submit(uploadDialog.getByRole("form", { name: "上传资产" }));
    await waitFor(() =>
      expect(apiMocks.uploadIpAsset).toHaveBeenCalledWith(
        expect.objectContaining({
          department: "品牌部",
          contributor: "同事甲",
          emotion: "兴奋",
        }),
        expect.anything(),
      ),
    );
  });

  it("preserves manual fields on recognition failure and clears stale suggestions on file change", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });
    await user.click(screen.getByRole("button", { name: "上传图片" }));
    await user.click(screen.getByText("补充描述信息"));

    const first = new File([new Uint8Array([1])], "first.png", {
      type: "image/png",
    });
    await user.upload(screen.getByLabelText(/选择 PNG/), first);
    await user.type(screen.getByLabelText("情绪"), "平静");
    apiMocks.recognizeIpAsset.mockRejectedValueOnce(
      new Error("asset_recognition_failed"),
    );
    await user.click(screen.getByRole("button", { name: "AI 辅助识别" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "已保留当前图片和填写内容",
    );
    expect(screen.getByLabelText("情绪")).toHaveValue("平静");

    apiMocks.recognizeIpAsset.mockResolvedValueOnce({
      action: "挥手",
      asset_type: "meme_sticker",
      character: "xiao_sai",
      emotion: "开心",
      intended_use: "社群推送",
      model: "glm-4.1v-thinking-flash",
      provider: "zhipu",
      scene: "科学课堂",
      status: "suggested",
      style: "3D",
      tags: ["开心"],
    });
    await user.click(screen.getByRole("button", { name: "AI 辅助识别" }));
    expect(await screen.findByText("AI 建议，请确认")).toBeInTheDocument();

    const second = new File([new Uint8Array([2])], "second.png", {
      type: "image/png",
    });
    await user.upload(screen.getByLabelText(/first.png/), second);
    expect(screen.queryByText("AI 建议，请确认")).toBeNull();
    expect(screen.getByLabelText("情绪")).toHaveValue("");
  });

  it("has no automatically detectable accessibility violations", async () => {
    const user = userEvent.setup();
    const { container } = renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });
    await user.click(screen.getByRole("button", { name: "上传图片" }));
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("keeps manual upload available when AI recognition is disabled", async () => {
    const user = userEvent.setup();
    renderHub({ recognitionAvailable: false });
    await screen.findByRole("checkbox", { name: /选择 小赛/ });
    await user.click(screen.getByRole("button", { name: "上传图片" }));

    const file = new File([new Uint8Array([1])], "manual.png", {
      type: "image/png",
    });
    await user.upload(screen.getByLabelText(/选择 PNG/), file);
    expect(screen.getByRole("button", { name: "AI 辅助识别" })).toBeDisabled();
    expect(screen.getByText(/仍可手动填写并上传/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "上传到共享图库" }),
    ).toBeEnabled();
    expect(apiMocks.recognizeIpAsset).not.toHaveBeenCalled();
  });

  it("announces a completed bounded ZIP download", async () => {
    const user = userEvent.setup();
    apiMocks.downloadIpAssetPackage.mockResolvedValue(undefined);
    renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });

    await user.click(screen.getByRole("checkbox", { name: /选择 小赛/ }));
    expect(screen.getByText("✓ 已选")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "下载 ZIP + 清单" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "ZIP 下载已开始",
    );
    expect(apiMocks.recordIpAssetSearchEvent).not.toHaveBeenCalled();
  });

  it("keeps ordered selection for ZIP and opens a safe in-memory flipbook draft", async () => {
    const user = userEvent.setup();
    const first = albumAsset(1, "小赛挥手.png");
    const second = albumAsset(2, "赛先生读书.png");
    renderHub({ listItems: [first, second] });

    await user.click(
      await screen.findByRole("checkbox", { name: "选择 小赛挥手.png" }),
    );
    expect(screen.getByRole("button", { name: "制作翻页相册" })).toBeDisabled();
    expect(screen.getByText("再选择 1 张图片即可制作相册")).toBeVisible();

    await user.click(
      screen.getByRole("checkbox", { name: "选择 赛先生读书.png" }),
    );
    expect(screen.getByRole("button", { name: "制作翻页相册" })).toBeEnabled();
    expect(screen.getByText("已满足 2–20 张相册范围")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "制作翻页相册" }));

    expect(window.location.pathname).toBe("/ip-assets/flipbook");
    expect(window.location.search).toBe("");
    expect(
      readStagedIpAssetFlipbookDraft()?.pages.map((page) => page.assetRef),
    ).toEqual([first.asset_ref, second.asset_ref]);
    expect(apiMocks.downloadIpAssetPackage).not.toHaveBeenCalled();
    expect(apiMocks.createIpAssetGeneration).not.toHaveBeenCalled();
  });

  it("leaves ZIP selection unbounded while disabling albums above twenty images", async () => {
    const listItems = Array.from({ length: 21 }, (_, index) =>
      albumAsset(index + 1, `相册图片-${index + 1}.png`),
    );
    renderHub({ listItems });

    const checkboxes = await screen.findAllByRole("checkbox", {
      name: /选择 相册图片-/,
    });
    checkboxes.forEach((checkbox) => fireEvent.click(checkbox));

    expect(screen.getByText("21 项已选择")).toBeVisible();
    expect(screen.getByRole("button", { name: "制作翻页相册" })).toBeDisabled();
    expect(screen.getByText("相册最多使用 20 张，请移除 1 张")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "下载 ZIP + 清单" }),
    ).toBeEnabled();
    expect(window.location.pathname).toBe("/ip-assets");
    expect(readStagedIpAssetFlipbookDraft()).toBeNull();
  });

  it("traps tool focus, closes with Escape and restores the opener", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });

    const uploadButton = screen.getByRole("button", { name: "上传图片" });
    uploadButton.focus();
    await user.click(uploadButton);

    expect(
      screen.getByRole("dialog", { name: "上传资产" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭面板" })).toHaveFocus();

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByText("补充描述信息")).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "上传资产" })).toBeNull();
    expect(uploadButton).toHaveFocus();

    await user.click(uploadButton);
    const dialog = screen.getByRole("dialog", { name: "上传资产" });
    if (dialog.parentElement === null)
      throw new Error("dialog_backdrop_missing");
    fireEvent.mouseDown(dialog.parentElement);
    expect(screen.queryByRole("dialog", { name: "上传资产" })).toBeNull();
    expect(uploadButton).toHaveFocus();
  });

  it("reports search failures without hiding provider-independent browsing", async () => {
    const user = userEvent.setup();
    apiMocks.searchIpAssetsText.mockRejectedValueOnce(
      new Error("asset_search_failed"),
    );
    renderHub();
    await screen.findByText(asset.canonical_name);

    await user.type(screen.getByLabelText("自然语言找图"), "小赛透明底表情包");
    await user.click(screen.getByRole("button", { name: "开始找图" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "检索失败：asset_search_failed",
    );
    expect(screen.getAllByText(asset.canonical_name).length).toBeGreaterThan(0);
  });

  it("does not preview or package an asset until processing is ready", async () => {
    const processingAsset: IpAsset = {
      ...asset,
      asset_ref: "ipa_processing",
      canonical_name: "小赛-表情包-处理中-v001.png",
      status: "processing",
    };
    renderHub({ listItems: [processingAsset] });

    expect(
      await screen.findByRole("img", {
        name: /小赛-表情包-处理中.*图片正在处理，暂不可预览/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /暂不可选择/ })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "下载 ZIP + 清单" }),
    ).toBeNull();
  });

  it("links the shared library and asset detail to the dedicated creation studio", async () => {
    const user = userEvent.setup();
    renderHub({ generationAvailable: true });
    await screen.findByRole("checkbox", { name: /选择 小赛/ });

    expect(screen.getByRole("link", { name: "AI 创作" })).toHaveAttribute(
      "href",
      "/ip-assets/create",
    );

    const assetButton = within(screen.getByRole("region", { name: "全部图片" }))
      .getAllByRole("button", {
        name: (accessibleName) => accessibleName.includes(asset.canonical_name),
      })
      .find((button) => !button.hasAttribute("aria-pressed"));
    if (assetButton === undefined) throw new Error("asset_card_missing");
    await user.click(assetButton);
    expect(
      await screen.findByRole("link", { name: "用作 AI 创作参考" }),
    ).toHaveAttribute("href", `/ip-assets/create?reference=${asset.asset_ref}`);
  });

  it("asks for a browser-local profile when a visitor favorites an asset", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByRole("checkbox", { name: /选择 小赛/ });

    await user.click(
      screen.getByRole("button", { name: `收藏 ${asset.canonical_name}` }),
    );

    expect(
      screen.getByRole("dialog", { name: "建立这台浏览器的素材名片" }),
    ).toBeInTheDocument();
    expect(apiMocks.setIpAssetFavorite).not.toHaveBeenCalled();
  });

  it("creates the preset demo profile through the same browser-local bootstrap", async () => {
    const user = userEvent.setup();
    apiMocks.bootstrapIpAssetProfile.mockResolvedValue({
      created_at: "2026-08-27T08:00:00Z",
      department: "品牌中心",
      display_name: "演示用户",
      identity_boundary: "browser_local_unverified",
      profile_ref: "ipp_11111111111111111111",
    });
    renderHub();
    await user.click(
      await screen.findByRole("button", {
        name: `收藏 ${asset.canonical_name}`,
      }),
    );

    await user.click(screen.getByRole("button", { name: "一键使用演示名片" }));

    await waitFor(() =>
      expect(apiMocks.bootstrapIpAssetProfile).toHaveBeenCalledTimes(1),
    );
    const input = apiMocks.bootstrapIpAssetProfile.mock.calls[0]?.[0] as
      | {
          displayName: string;
          department: string;
          token: string;
        }
      | undefined;
    expect(input).toMatchObject({
      displayName: "演示用户",
      department: "品牌中心",
    });
    expect(input?.token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(
      screen.queryByRole("dialog", { name: "建立这台浏览器的素材名片" }),
    ).toBeNull();
  });
});

function albumAsset(index: number, canonicalName: string): IpAsset {
  const suffix = index.toString(16).padStart(20, "0");
  const assetRef = `ipa_${suffix}`;
  return {
    ...asset,
    asset_ref: assetRef,
    canonical_name: canonicalName,
    download_url: `/api/v1/ip-assets/${assetRef}/download`,
    thumbnail_url: `/api/v1/ip-assets/${assetRef}/thumbnail?v=1`,
    preview_url: `/api/v1/ip-assets/${assetRef}/preview`,
  };
}
