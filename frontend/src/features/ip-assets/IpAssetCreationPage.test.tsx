import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IpAsset } from "./api";
import creationStylesheet from "./IpAssetCreationPage.module.css?inline";
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
    items: [asset("one"), asset("two"), asset("three")],
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
  });
});
