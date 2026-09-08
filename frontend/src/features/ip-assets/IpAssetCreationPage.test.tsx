import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
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

import type { IpAsset, IpAssetGeneration } from "./api";
import creationStylesheet from "./IpAssetCreationPage.module.css?inline";
import comparisonStylesheet from "./IpAssetCreationComparison.module.css?inline";
import { ipAssetKeys } from "./hooks";
import { saveLocalIpAssetProfile } from "./profile";

const apiMocks = vi.hoisted(() => ({
  createIpAssetGeneration: vi.fn(),
  fetchIpAssetBlob: vi.fn(),
  getIpAsset: vi.fn(),
  getIpAssetCapabilities: vi.fn(),
  getIpAssetGeneration: vi.fn(),
  listIpAssets: vi.fn(),
  listPersonalIpAssets: vi.fn(),
  restoreIpAssetProfile: vi.fn(),
  setIpAssetFavorite: vi.fn(),
  shareIpAsset: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { IpAssetCreationPage } from "./IpAssetCreationPage";

const profile = {
  token: "A".repeat(43),
  profileRef: `ipp_${"a".repeat(20)}`,
  displayName: "内容同事",
  department: "品牌部",
};

const asset = (suffix: string): IpAsset => ({
  action: "挥手",
  asset_ref: `ipa_${suffix}`,
  asset_type: "meme_sticker",
  byte_size: 2048,
  canonical_name: `小赛-参考-${suffix}.png`,
  character: "xiao_sai",
  contributor: "内容组",
  created_at: "2026-08-24T08:00:00Z",
  department: "品牌部",
  download_url: `/api/v1/ip-assets/ipa_${suffix}/download`,
  emotion: "开心",
  favorite: false,
  has_alpha: true,
  height: 1024,
  intended_use: "社群",
  media_type: "image/png",
  orientation: "square",
  thumbnail_url: `/api/v1/ip-assets/ipa_${suffix}/thumbnail?v=1`,
  preview_url: `/api/v1/ip-assets/ipa_${suffix}/preview`,
  scene: "课堂",
  semantic_status: "ready",
  shared: true,
  source_kind: "uploaded",
  status: "ready",
  style: "3D",
  tags: ["社群"],
  width: 1024,
});

function Providers({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function succeededJob(
  overrides: Partial<IpAssetGeneration> = {},
): IpAssetGeneration {
  return {
    completed_at: "2026-08-24T08:01:00Z",
    created: true,
    created_at: "2026-08-24T08:00:00Z",
    error_code: null,
    generation_available: true,
    job_ref: "ipg_comparison",
    output_asset_ref: "ipa_result",
    reference_asset_ref: "ipa_one",
    reference_asset_refs: ["ipa_one"],
    status: "succeeded",
    status_url: "/api/v1/ip-assets/generations/ipg_comparison",
    ...overrides,
  };
}

async function submitComparison() {
  const user = userEvent.setup();
  const picker = screen.getByRole("region", { name: "选择创作素材" });
  await user.click(
    (await within(picker).findAllByRole("button", { name: "加入参考" }))[0]!,
  );
  fireEvent.change(screen.getByLabelText("画面描述"), {
    target: { value: "小赛在明亮的科学课堂里演示实验。" },
  });
  await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  window.history.replaceState(null, "", "/ip-assets/create");
  saveLocalIpAssetProfile(profile);
  apiMocks.getIpAssetCapabilities.mockResolvedValue({
    accepted_media_types: ["image/png"],
    authentication: "none",
    deployment_boundary: "company_intranet",
    enabled: true,
    generation_available: true,
    max_upload_bytes: 26_214_400,
    recognition_available: true,
    semantic_search_available: true,
  });
  apiMocks.restoreIpAssetProfile.mockResolvedValue({
    profile_ref: profile.profileRef,
    display_name: profile.displayName,
    department: profile.department,
    created_at: "2026-08-24T08:00:00Z",
  });
  apiMocks.listIpAssets.mockResolvedValue({
    items: [asset("one"), asset("two"), asset("three"), asset("four")],
    next_cursor: null,
  });
  apiMocks.listPersonalIpAssets.mockResolvedValue({
    items: [],
    next_cursor: null,
  });
  apiMocks.fetchIpAssetBlob.mockResolvedValue(
    new Blob([new Uint8Array([1])], { type: "image/png" }),
  );
  apiMocks.getIpAssetGeneration.mockResolvedValue({
    completed_at: null,
    created: false,
    created_at: "2026-08-24T08:00:00Z",
    error_code: null,
    generation_available: true,
    job_ref: "ipg_demo",
    output_asset_ref: null,
    reference_asset_ref: "ipa_one",
    reference_asset_refs: ["ipa_one", "ipa_two"],
    status: "queued",
    status_url: "/api/v1/ip-assets/generations/ipg_demo",
  });
});

describe("IpAssetCreationPage", () => {
  it("freezes the actual submitted prompt, ordered cards and taxonomy while the form changes", async () => {
    const user = userEvent.setup();
    let resolveSubmission: ((job: IpAssetGeneration) => void) | undefined;
    const job = succeededJob({ reference_asset_refs: ["ipa_one", "ipa_two"] });
    apiMocks.createIpAssetGeneration.mockImplementation(
      () =>
        new Promise<IpAssetGeneration>((resolve) => {
          resolveSubmission = resolve;
        }),
    );
    apiMocks.getIpAssetGeneration.mockResolvedValue(job);
    apiMocks.getIpAsset.mockResolvedValue(asset("result"));
    const { container } = render(<IpAssetCreationPage />, {
      wrapper: Providers,
    });
    const picker = screen.getByRole("region", { name: "选择创作素材" });
    const add = await within(picker).findAllByRole("button", {
      name: "加入参考",
    });
    await user.click(add[0]!);
    await user.click(add[1]!);
    const originalPrompt =
      "保留小赛原有配色。\n在明亮的科学课堂演示火箭实验，不添加文字。";
    fireEvent.change(screen.getByLabelText("画面描述"), {
      target: { value: originalPrompt },
    });
    await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));
    fireEvent.change(screen.getByLabelText("画面描述"), {
      target: { value: "这是下一次创作，不属于已提交的结果。" },
    });
    await user.selectOptions(screen.getByLabelText("IP 角色"), "duo");
    await user.selectOptions(screen.getByLabelText("资产类型"), "expression");
    await user.click(
      screen.getByRole("button", { name: "将 小赛-参考-one.png 后移" }),
    );
    await act(() => Promise.resolve(resolveSubmission?.(job)));

    const comparison = await screen.findByRole("region", {
      name: "从参考，到新画面",
    });
    expect(
      within(comparison).getByText(originalPrompt, {
        collapseWhitespace: false,
      }),
    ).toBeVisible();
    expect(within(comparison).queryByText(/这是下一次创作/)).toBeNull();
    expect(within(comparison).getByText("小赛")).toBeVisible();
    expect(within(comparison).getByText("场景插画")).toBeVisible();
    const references = within(comparison).getByRole("region", {
      name: /参考图/,
    });
    expect(
      within(references)
        .getAllByRole("img")
        .map((image) => image.getAttribute("alt")),
    ).toEqual([asset("one").canonical_name, asset("two").canonical_name]);
    expect(within(references).getAllByRole("img")[0]).toHaveAttribute(
      "src",
      expect.stringContaining(asset("one").preview_url),
    );
    const result = within(comparison).getByRole("region", { name: /生成画面/ });
    expect(within(result).getByRole("img")).toHaveAttribute(
      "src",
      expect.stringContaining(asset("result").preview_url),
    );
    await user.click(
      screen.getByRole("button", { name: "移除 小赛-参考-one.png" }),
    );
    expect(within(references).getAllByRole("listitem")).toHaveLength(2);
    expect((await axe(container)).violations).toEqual([]);
  });

  it.each(["pending", "rejected", "queued"] as const)(
    "removes the previous comparison when the next submission is %s",
    async (nextState) => {
      apiMocks.createIpAssetGeneration.mockResolvedValue(succeededJob());
      apiMocks.getIpAssetGeneration.mockResolvedValue(succeededJob());
      apiMocks.getIpAsset.mockResolvedValue(asset("result"));
      render(<IpAssetCreationPage />, { wrapper: Providers });
      const user = await submitComparison();
      await screen.findByRole("region", { name: "从参考，到新画面" });
      if (nextState === "pending")
        apiMocks.createIpAssetGeneration.mockImplementation(
          () => new Promise(() => {}),
        );
      if (nextState === "rejected")
        apiMocks.createIpAssetGeneration.mockRejectedValue(
          new Error("rejected"),
        );
      if (nextState === "queued") {
        const next = succeededJob({
          job_ref: "ipg_next",
          status: "queued",
          output_asset_ref: null,
        });
        apiMocks.createIpAssetGeneration.mockResolvedValue(next);
        apiMocks.getIpAssetGeneration.mockResolvedValue(next);
      }
      fireEvent.change(screen.getByLabelText("画面描述"), {
        target: { value: "下一次创作的简报" },
      });
      await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));
      if (nextState === "rejected") await screen.findByRole("alert");
      if (nextState === "queued") await screen.findByText(/后台服务未启动时/);
      expect(
        screen.queryByRole("region", { name: "从参考，到新画面" }),
      ).toBeNull();
      expect(screen.queryByRole("button", { name: "下载原图" })).toBeNull();
    },
  );

  it.each([
    ["another job", { job_ref: "ipg_other" }, {}],
    ["different references", { reference_asset_refs: ["ipa_two"] }, {}],
    ["an unready output", {}, { status: "processing" }],
    ["another output", {}, { asset_ref: "ipa_other" }],
    ["a running job with an output ref", { status: "running" }, {}],
    ["a failed job with an output ref", { status: "failed" }, {}],
  ] satisfies readonly (readonly [
    string,
    Partial<IpAssetGeneration>,
    Partial<IpAsset>,
  ])[])(
    "does not fabricate a comparison for %s",
    async (_name, jobOverride, outputOverride) => {
      apiMocks.createIpAssetGeneration.mockResolvedValue(succeededJob());
      apiMocks.getIpAssetGeneration.mockResolvedValue(
        succeededJob(jobOverride),
      );
      apiMocks.getIpAsset.mockResolvedValue({
        ...asset("result"),
        ...outputOverride,
      });
      render(<IpAssetCreationPage />, { wrapper: Providers });
      await submitComparison();
      await waitFor(() =>
        expect(apiMocks.getIpAssetGeneration).toHaveBeenCalled(),
      );
      expect(
        screen.queryByRole("region", { name: "从参考，到新画面" }),
      ).toBeNull();
    },
  );

  it("hides a ready comparison when the submitting profile is rejected", async () => {
    apiMocks.createIpAssetGeneration.mockResolvedValue(succeededJob());
    apiMocks.getIpAssetGeneration.mockResolvedValue(succeededJob());
    apiMocks.getIpAsset.mockResolvedValue(asset("result"));
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={client}>
        <IpAssetCreationPage />
      </QueryClientProvider>,
    );
    await submitComparison();
    await screen.findByRole("region", { name: "从参考，到新画面" });
    apiMocks.restoreIpAssetProfile.mockRejectedValue(
      new Error("profile_rejected"),
    );
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ipAssetKeys.profile(profile.profileRef),
      });
    });
    expect(
      await screen.findByText(/这台浏览器保存的素材名片已失效/),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "从参考，到新画面" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "下载原图" })).toBeNull();
  });

  it("does not reconstruct historical comparisons without a current-session submission", async () => {
    apiMocks.getIpAssetGeneration.mockResolvedValue(succeededJob());
    apiMocks.getIpAsset.mockResolvedValue(asset("result"));
    render(<IpAssetCreationPage />, { wrapper: Providers });
    await screen.findByText(asset("one").canonical_name);
    expect(
      screen.queryByRole("region", { name: "从参考，到新画面" }),
    ).toBeNull();
    expect(apiMocks.getIpAssetGeneration).not.toHaveBeenCalled();
    expect(comparisonStylesheet).toMatch(/@media\s*\(max-width:\s*900px\)/);
    expect(comparisonStylesheet).toMatch(
      /grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });

  it("loads a demo brief without submitting a generation", async () => {
    const user = userEvent.setup();
    render(<IpAssetCreationPage />, { wrapper: Providers });

    await user.click(
      await screen.findByRole("button", { name: "载入示例简报" }),
    );

    expect(
      screen.getByLabelText<HTMLTextAreaElement>("画面描述").value,
    ).toContain("未来科学课堂");
    expect(
      screen.getByText(/示例创作简报已填入.*尚未提交生成任务/),
    ).toBeVisible();
    expect(apiMocks.createIpAssetGeneration).not.toHaveBeenCalled();
  });

  it("keeps the IP brief required without browser character-count bounds", async () => {
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const prompt =
      await screen.findByLabelText<HTMLTextAreaElement>("画面描述");
    expect(prompt).toBeRequired();
    expect(prompt).not.toHaveAttribute("minlength");
    expect(prompt).not.toHaveAttribute("maxlength");
  });

  it("uses an accessible library return control and professional section labels", async () => {
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const backLink = await screen.findByRole("link", {
      name: /ASSET LIBRARY 返回共享图库/,
    });
    expect(backLink).toHaveAttribute("href", "/ip-assets");
    expect(within(backLink).getByText("ASSET LIBRARY")).toBeVisible();
    expect(within(backLink).getByText("返回共享图库")).toBeVisible();
    expect(screen.getByText("创作简报")).toBeVisible();
    expect(screen.getByText("OUTPUT")).toBeVisible();
    expect(screen.getByText("私人结果")).toBeVisible();
    expect(creationStylesheet).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });

  it("keeps its editorial studio responsive and motion-safe", () => {
    expect(creationStylesheet).toMatch(/@media\s*\(max-width:\s*900px\)/);
    expect(creationStylesheet).toMatch(/@media\s*\(max-width:\s*620px\)/);
    expect(creationStylesheet).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*no-preference\)/,
    );
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<IpAssetCreationPage />, {
      wrapper: Providers,
    });
    await screen.findByRole("heading", { name: "AI 视觉创作室" });
    expect(screen.getByRole("button", { name: "退出登录" })).toBeVisible();
    expect((await axe(container)).violations).toEqual([]);
  });

  it("revokes private preview object URLs when a personal card unmounts", async () => {
    const privateAsset = { ...asset("private"), shared: false };
    apiMocks.listPersonalIpAssets.mockResolvedValue({
      items: [
        {
          asset: privateAsset,
          favorite: false,
          membership_sources: ["generated"],
        },
      ],
      next_cursor: null,
    });
    const createObjectURL = vi.fn(() => "blob:private-preview");
    const revokeObjectURL = vi.fn();
    const previousCreateObjectURL = Object.getOwnPropertyDescriptor(
      URL,
      "createObjectURL",
    );
    const previousRevokeObjectURL = Object.getOwnPropertyDescriptor(
      URL,
      "revokeObjectURL",
    );
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURL,
    });

    try {
      const view = render(<IpAssetCreationPage />, { wrapper: Providers });
      expect(
        await screen.findByText(privateAsset.canonical_name),
      ).toBeVisible();
      await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
      expect(apiMocks.fetchIpAssetBlob).toHaveBeenCalledWith(
        privateAsset.preview_url,
        profile.token,
      );
      view.unmount();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:private-preview");
    } finally {
      if (previousCreateObjectURL === undefined) {
        Reflect.deleteProperty(URL, "createObjectURL");
      } else {
        Object.defineProperty(URL, "createObjectURL", previousCreateObjectURL);
      }
      if (previousRevokeObjectURL === undefined) {
        Reflect.deleteProperty(URL, "revokeObjectURL");
      } else {
        Object.defineProperty(URL, "revokeObjectURL", previousRevokeObjectURL);
      }
    }
  });

  it("keeps one to three references in a numbered, reorderable filmstrip", async () => {
    const user = userEvent.setup();
    apiMocks.createIpAssetGeneration.mockResolvedValue({
      completed_at: null,
      created: true,
      created_at: "2026-08-24T08:00:00Z",
      error_code: null,
      generation_available: true,
      job_ref: "ipg_demo",
      output_asset_ref: null,
      reference_asset_ref: "ipa_two",
      reference_asset_refs: ["ipa_two", "ipa_one"],
      status: "queued",
      status_url: "/api/v1/ip-assets/generations/ipg_demo",
    });
    render(<IpAssetCreationPage />, { wrapper: Providers });

    expect(
      await screen.findByRole("heading", { name: "AI 视觉创作室" }),
    ).toBeVisible();
    expect(screen.getAllByText("等待素材")).toHaveLength(3);
    const library = screen
      .getByRole("heading", { name: "选择创作素材" })
      .closest("section");
    if (library === null || library === undefined)
      throw new Error("reference_library_missing");
    const addButtons = await within(library).findAllByRole("button", {
      name: "加入参考",
    });
    await user.click(addButtons[0]!);
    await user.click(addButtons[1]!);

    await user.click(
      screen.getByRole("button", { name: "将 小赛-参考-one.png 后移" }),
    );
    await user.type(
      screen.getByLabelText("画面描述"),
      "小赛在科学课堂开心挥手，适合社群头图",
    );
    await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));

    await waitFor(() =>
      expect(apiMocks.createIpAssetGeneration).toHaveBeenCalledWith(
        expect.objectContaining({
          profileToken: profile.token,
          referenceAssetRefs: ["ipa_two", "ipa_one"],
        }),
        expect.anything(),
      ),
    );
  });

  it("reuses the same generation idempotency key when an unchanged submit is retried", async () => {
    const user = userEvent.setup();
    apiMocks.createIpAssetGeneration.mockRejectedValue(
      new Error("ambiguous_network_failure"),
    );
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const library = screen
      .getByRole("heading", { name: "选择创作素材" })
      .closest("section");
    if (library === null) throw new Error("reference_library_missing");
    await user.click(
      (await within(library).findAllByRole("button", { name: "加入参考" }))[0]!,
    );
    await user.type(
      screen.getByLabelText("画面描述"),
      "小赛在科学课堂开心挥手，适合社群头图",
    );
    const submit = screen.getByRole("button", { name: "生成 1:1 图片" });
    await user.click(submit);
    await screen.findByRole("alert");
    await user.click(submit);

    await waitFor(() =>
      expect(apiMocks.createIpAssetGeneration).toHaveBeenCalledTimes(2),
    );
    const first = apiMocks.createIpAssetGeneration.mock.calls[0]?.[0] as {
      idempotencyKey: string;
    };
    const second = apiMocks.createIpAssetGeneration.mock.calls[1]?.[0] as {
      idempotencyKey: string;
    };
    expect(second.idempotencyKey).toBe(first.idempotencyKey);
  });

  it("offers profile-scoped favorites from the reference picker", async () => {
    const user = userEvent.setup();
    apiMocks.setIpAssetFavorite.mockResolvedValue({
      asset_ref: "ipa_one",
      favorite: true,
    });
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const library = screen
      .getByRole("heading", { name: "选择创作素材" })
      .closest("section");
    if (library === null) throw new Error("reference_library_missing");
    await user.click(
      (await within(library).findAllByRole("button", { name: "收藏" }))[0]!,
    );

    await waitFor(() =>
      expect(apiMocks.setIpAssetFavorite).toHaveBeenCalledWith(
        {
          token: profile.token,
          assetRef: "ipa_one",
          favorite: true,
        },
        expect.anything(),
      ),
    );
    expect(screen.getByText("已收藏「小赛-参考-one.png」。")).toBeVisible();
  });

  it("switches among reference sources, keeps selection, and excludes private or unready rows", async () => {
    const user = userEvent.setup();
    const favorite = {
      ...asset("favorite"),
      canonical_name: "小赛-我的收藏-课堂.png",
      favorite: true,
    };
    const privateFavorite = {
      ...asset("private-favorite"),
      canonical_name: "私人收藏-不可引用.png",
      favorite: true,
      shared: false,
    };
    const processingFavorite = {
      ...asset("processing-favorite"),
      canonical_name: "处理中收藏-不可引用.png",
      favorite: true,
      status: "processing" as const,
    };
    apiMocks.listPersonalIpAssets.mockImplementation(
      ({ source }: { source: string }) =>
        Promise.resolve({
          items:
            source === "favorite"
              ? [favorite, privateFavorite, processingFavorite].map((item) => ({
                  asset: item,
                  favorite: true,
                  membership_sources: ["favorite"],
                }))
              : [],
          next_cursor: null,
        }),
    );
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const firstCard = (await screen.findByText("小赛-参考-one.png")).closest(
      "article",
    );
    if (firstCard === null) throw new Error("first_reference_card_missing");
    await user.click(
      within(firstCard).getByRole("button", { name: "加入参考" }),
    );
    await user.click(screen.getByRole("button", { name: "我的收藏" }));

    expect(await screen.findByText(favorite.canonical_name)).toBeVisible();
    expect(screen.queryByText(privateFavorite.canonical_name)).toBeNull();
    expect(screen.queryByText(processingFavorite.canonical_name)).toBeNull();
    expect(
      screen.getByRole("button", { name: "移除 小赛-参考-one.png" }),
    ).toBeVisible();
    expect(
      screen.getByText("已切换到「我的收藏」，已选参考保持不变。"),
    ).toBeVisible();

    await user.type(
      screen.getByPlaceholderText("按名称、动作、场景筛选…"),
      "不存在的素材",
    );
    expect(
      await screen.findByText(/私人未共享图片不会出现在这里/),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "移除 小赛-参考-one.png" }),
    ).toBeVisible();
  });

  it("gates profile-scoped reference filters through the local profile dialog", async () => {
    const user = userEvent.setup();
    localStorage.clear();
    render(<IpAssetCreationPage />, { wrapper: Providers });

    await user.click(screen.getByRole("button", { name: "我的收藏" }));

    expect(
      await screen.findByRole("dialog", {
        name: "建立这台浏览器的素材名片",
      }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "全部素材" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(apiMocks.listPersonalIpAssets).not.toHaveBeenCalled();
    expect(
      screen.getByText("查看「我的收藏」前，请先建立浏览器本地名片。"),
    ).toBeVisible();
  });

  it.each([
    ["我的上传", "uploaded" as const],
    ["我的共享 AI 作品", "generated" as const],
  ])("loads the %s reference source", async (label, source) => {
    const user = userEvent.setup();
    const sourceAsset = {
      ...asset(source),
      canonical_name: `小赛-${label}-素材.png`,
      source_kind:
        source === "generated"
          ? ("ai_generated" as const)
          : ("uploaded" as const),
    };
    apiMocks.listPersonalIpAssets.mockImplementation(
      ({ source: requestedSource }: { source: string }) =>
        Promise.resolve({
          items:
            requestedSource === source
              ? [
                  {
                    asset: sourceAsset,
                    favorite: false,
                    membership_sources: [source],
                  },
                ]
              : [],
          next_cursor: null,
        }),
    );
    render(<IpAssetCreationPage />, { wrapper: Providers });

    await user.click(screen.getByRole("button", { name: label }));

    expect(await screen.findByText(sourceAsset.canonical_name)).toBeVisible();
    expect(apiMocks.listPersonalIpAssets).toHaveBeenCalledWith(
      expect.objectContaining({ token: profile.token, source }),
    );
  });

  it("marks selected cards, explains the three-reference limit, and announces reorder and removal", async () => {
    const user = userEvent.setup();
    render(<IpAssetCreationPage />, { wrapper: Providers });

    for (const suffix of ["one", "two", "three"]) {
      const card = (await screen.findByText(`小赛-参考-${suffix}.png`)).closest(
        "article",
      );
      if (card === null) throw new Error("reference_card_missing");
      await user.click(within(card).getByRole("button", { name: "加入参考" }));
    }

    expect(screen.getByText(/已选 · 参考 01/)).toBeVisible();
    expect(screen.getByText(/已选 · 参考 02/)).toBeVisible();
    expect(screen.getByText(/已选 · 参考 03/)).toBeVisible();
    expect(screen.getByText(/已选满 3 张参考图/)).toBeVisible();
    const fourthCard = screen
      .getByText("小赛-参考-four.png")
      .closest("article");
    if (fourthCard === null) throw new Error("fourth_reference_card_missing");
    expect(
      within(fourthCard).getByRole("button", { name: "加入参考" }),
    ).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "将 小赛-参考-one.png 后移" }),
    );
    expect(
      screen.getByText("已将「小赛-参考-one.png」调整为参考 02。"),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "移除 小赛-参考-one.png" }),
    );
    expect(
      screen.getByText("已从参考胶片移除「小赛-参考-one.png」。"),
    ).toBeVisible();
  });

  it.each([
    [
      "queued" as const,
      "任务已保存，正在等待独立后台生成服务领取。后台服务未启动时，任务会继续安全排队。",
    ],
    [
      "running" as const,
      "后台生成服务已领取任务，模型正在组合参考素材与画面描述。",
    ],
    [
      "failed" as const,
      "本次生成没有完成。可以检查画面描述与参考素材后，使用同一简报重试。",
    ],
  ])("shows honest %s generation state copy", async (status, copy) => {
    const user = userEvent.setup();
    apiMocks.createIpAssetGeneration.mockResolvedValue({
      completed_at: null,
      created: true,
      created_at: "2026-08-24T08:00:00Z",
      error_code: null,
      generation_available: true,
      job_ref: "ipg_demo",
      output_asset_ref: null,
      reference_asset_ref: "ipa_one",
      reference_asset_refs: ["ipa_one"],
      status: "queued",
      status_url: "/api/v1/ip-assets/generations/ipg_demo",
    });
    apiMocks.getIpAssetGeneration.mockResolvedValue({
      completed_at: null,
      created: false,
      created_at: "2026-08-24T08:00:00Z",
      error_code: null,
      generation_available: true,
      job_ref: "ipg_demo",
      output_asset_ref: null,
      reference_asset_ref: "ipa_one",
      reference_asset_refs: ["ipa_one"],
      status,
      status_url: "/api/v1/ip-assets/generations/ipg_demo",
    });
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const card = (await screen.findByText("小赛-参考-one.png")).closest(
      "article",
    );
    if (card === null) throw new Error("reference_card_missing");
    await user.click(within(card).getByRole("button", { name: "加入参考" }));
    await user.type(
      screen.getByLabelText("画面描述"),
      "小赛在科学课堂开心挥手，适合社群头图",
    );
    await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));

    expect(await screen.findByText(copy)).toBeVisible();
    expect(screen.queryByText(/\d+%|预计完成/)).toBeNull();
    expect(screen.getByText(/这里不表示该服务当前在线/)).toBeVisible();
  });

  it("shows submission feedback before a job is stored", async () => {
    const user = userEvent.setup();
    let resolveGeneration: ((value: unknown) => void) | undefined;
    apiMocks.createIpAssetGeneration.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGeneration = resolve;
        }),
    );
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const card = (await screen.findByText("小赛-参考-one.png")).closest(
      "article",
    );
    if (card === null) throw new Error("reference_card_missing");
    await user.click(within(card).getByRole("button", { name: "加入参考" }));
    await user.type(
      screen.getByLabelText("画面描述"),
      "小赛在科学课堂开心挥手，适合社群头图",
    );
    await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));

    expect(
      await screen.findByText("正在保存创作任务，完成后才会进入后台生成队列。"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "正在建立任务…" }),
    ).toBeDisabled();

    resolveGeneration?.({
      completed_at: null,
      created: true,
      created_at: "2026-08-24T08:00:00Z",
      error_code: null,
      generation_available: true,
      job_ref: "ipg_demo",
      output_asset_ref: null,
      reference_asset_ref: "ipa_one",
      reference_asset_refs: ["ipa_one"],
      status: "queued",
      status_url: "/api/v1/ip-assets/generations/ipg_demo",
    });
    expect(
      await screen.findByText(/任务已保存，正在等待独立后台生成服务领取/),
    ).toBeVisible();
  });

  it("keeps a bounded recoverable state when generation status cannot be read", async () => {
    const user = userEvent.setup();
    apiMocks.createIpAssetGeneration.mockResolvedValue({
      completed_at: null,
      created: true,
      created_at: "2026-08-24T08:00:00Z",
      error_code: null,
      generation_available: true,
      job_ref: "ipg_demo",
      output_asset_ref: null,
      reference_asset_ref: "ipa_one",
      reference_asset_refs: ["ipa_one"],
      status: "queued",
      status_url: "/api/v1/ip-assets/generations/ipg_demo",
    });
    apiMocks.getIpAssetGeneration.mockRejectedValue(new Error("network"));
    render(<IpAssetCreationPage />, { wrapper: Providers });

    const card = (await screen.findByText("小赛-参考-one.png")).closest(
      "article",
    );
    if (card === null) throw new Error("reference_card_missing");
    await user.click(within(card).getByRole("button", { name: "加入参考" }));
    await user.type(
      screen.getByLabelText("画面描述"),
      "小赛在科学课堂开心挥手，适合社群头图",
    );
    await user.click(screen.getByRole("button", { name: "生成 1:1 图片" }));

    expect(await screen.findByText("任务状态读取失败。")).toBeVisible();
    expect(
      screen.getByText(/暂时无法读取任务状态，系统会保留已经提交的任务/),
    ).toBeVisible();
  });

  it("loads the next page for the active personal reference source", async () => {
    const user = userEvent.setup();
    apiMocks.listPersonalIpAssets.mockImplementation(
      ({ source, cursor }: { source: string; cursor: string | null }) =>
        Promise.resolve(
          source === "favorite"
            ? {
                items: [
                  {
                    asset: asset(cursor === null ? "favorite-a" : "favorite-b"),
                    favorite: true,
                    membership_sources: ["favorite"],
                  },
                ],
                next_cursor: cursor === null ? "page-two" : null,
              }
            : { items: [], next_cursor: null },
        ),
    );
    render(<IpAssetCreationPage />, { wrapper: Providers });

    await user.click(screen.getByRole("button", { name: "我的收藏" }));
    expect(await screen.findByText("小赛-参考-favorite-a.png")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "加载更多我的收藏" }));

    expect(await screen.findByText("小赛-参考-favorite-b.png")).toBeVisible();
    expect(apiMocks.listPersonalIpAssets).toHaveBeenCalledWith(
      expect.objectContaining({
        token: profile.token,
        source: "favorite",
        cursor: "page-two",
      }),
    );
  });
});
