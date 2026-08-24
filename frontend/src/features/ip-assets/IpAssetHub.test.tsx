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
}));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { IpAssetHub } from "./IpAssetHub";

beforeEach(() => vi.clearAllMocks());

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
  preview_url: "/api/v1/ip-assets/ipa_demo0001/preview",
  scene: "",
  semantic_status: "unavailable",
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
  });

  it("describes hybrid search results honestly", async () => {
    const user = userEvent.setup();
    apiMocks.searchIpAssetsText.mockResolvedValueOnce({
      degraded_reason: null,
      items: [{ asset, explanation: "文字匹配: 开心", similarity: null }],
      mode: "semantic",
      search_version: "ip-asset-hybrid-v2",
    });
    renderHub();
    await user.type(await screen.findByLabelText("自然语言找图"), "小赛开心");
    await user.click(screen.getByRole("button", { name: "开始找图" }));

    expect(await screen.findByText("语义 + 元数据结果")).toBeInTheDocument();
  });

  it("shows the no-login boundary, gallery and provider-independent controls", async () => {
    const user = userEvent.setup();
    renderHub();

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /IP 数字.*资产中心/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("公司内网 · 无登录")).toBeInTheDocument();
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
    ).toHaveAttribute("src", expect.stringContaining("/api/v1/ip-assets/"));

    await user.type(
      screen.getByLabelText("自然语言找图"),
      "小赛开心挥手，适合社群",
    );
    await user.click(screen.getByRole("button", { name: "开始找图" }));
    expect(await screen.findByText("元数据降级结果")).toBeInTheDocument();
    expect(screen.getByText(/provider_unavailable/)).toBeInTheDocument();
    expect(screen.getByText("角色与用途匹配")).toBeInTheDocument();
  });

  it("uploads a bounded image with self-reported metadata", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByText(asset.canonical_name);
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
    await screen.findByText(asset.canonical_name);
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
    await screen.findByText(asset.canonical_name);
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
    await screen.findByText(asset.canonical_name);
    await user.click(screen.getByRole("button", { name: "上传图片" }));
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("keeps manual upload available when AI recognition is disabled", async () => {
    const user = userEvent.setup();
    renderHub({ recognitionAvailable: false });
    await screen.findByText(asset.canonical_name);
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
    await screen.findByText(asset.canonical_name);

    await user.click(screen.getByRole("checkbox", { name: /选择 小赛/ }));
    await user.click(screen.getByRole("button", { name: "下载 ZIP + 清单" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "ZIP 下载已开始",
    );
  });

  it("traps tool focus, closes with Escape and restores the opener", async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByText(asset.canonical_name);

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
    expect(screen.getByText(asset.canonical_name)).toBeInTheDocument();
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

  it("links a completed generation job to its library detail", async () => {
    const user = userEvent.setup();
    const job = {
      completed_at: null,
      created: true,
      created_at: "2026-08-24T08:10:00Z",
      error_code: null,
      generation_available: true,
      job_ref: "ipg_demo0001",
      output_asset_ref: null,
      status: "queued" as const,
      status_url: "/api/v1/ip-assets/generations/ipg_demo0001",
    };
    apiMocks.createIpAssetGeneration.mockResolvedValue(job);
    apiMocks.getIpAssetGeneration.mockResolvedValue({
      ...job,
      completed_at: "2026-08-24T08:11:00Z",
      output_asset_ref: asset.asset_ref,
      status: "succeeded",
    });
    renderHub({ generationAvailable: true });
    await screen.findByText(asset.canonical_name);

    const assetButton = screen.getByRole("button", {
      name: (accessibleName) => accessibleName.includes(asset.canonical_name),
    });
    await user.click(assetButton);
    await user.click(
      await screen.findByRole("button", { name: "用作 AI 创作参考" }),
    );
    await user.click(screen.getByRole("button", { name: "关闭详情" }));

    const createButton = screen
      .getAllByRole("button", { name: "AI 创作" })
      .at(0);
    if (createButton === undefined) throw new Error("create_button_missing");
    await user.click(createButton);
    expect(
      within(screen.getByRole("dialog", { name: "AI 创作" })).getByText(
        asset.canonical_name,
      ),
    ).toBeInTheDocument();
    await user.type(
      screen.getByLabelText("画面描述"),
      "小赛在科学课堂开心挥手",
    );
    await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));

    await user.click(
      await screen.findByRole("button", { name: "查看生成图片" }),
    );
    expect(
      await screen.findByRole("dialog", { name: detail.canonical_name }),
    ).toBeInTheDocument();
    expect(apiMocks.getIpAsset).toHaveBeenCalledWith(
      asset.asset_ref,
      expect.anything(),
    );
    expect(apiMocks.getIpAssetGeneration).toHaveBeenCalledTimes(1);
  });
});
