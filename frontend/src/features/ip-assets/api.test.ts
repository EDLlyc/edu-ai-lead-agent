import { beforeEach, describe, expect, it, vi } from "vitest";

const clientMocks = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  apiBaseUrl: "http://127.0.0.1:8000",
  apiClient: clientMocks,
  resolveApiResourceUrl: (path: string) => {
    try {
      const url = new URL(path, "http://127.0.0.1:8000");
      return url.protocol === "http:" || url.protocol === "https:"
        ? url.toString()
        : null;
    } catch {
      return null;
    }
  },
}));

import { ipAssetResourceUrl, recognizeIpAsset, uploadIpAsset } from "./api";

describe("IP asset API adapter", () => {
  beforeEach(() => vi.clearAllMocks());

  it("allows only API-origin preview and download resources", () => {
    expect(ipAssetResourceUrl("/api/v1/ip-assets/a/preview")).toBe(
      "http://127.0.0.1:8000/api/v1/ip-assets/a/preview",
    );
    expect(ipAssetResourceUrl("https://attacker.invalid/a.png")).toBeNull();
    expect(ipAssetResourceUrl("javascript:alert(1)")).toBeNull();
  });

  it("serializes uploads as multipart without inventing auth headers", async () => {
    clientMocks.POST.mockResolvedValue({
      data: {
        asset: { asset_ref: "ipa_demo0001" },
        duplicate: false,
      },
      error: undefined,
    });
    const file = new File([new Uint8Array([1])], "safe.png", {
      type: "image/png",
    });

    await uploadIpAsset({
      file,
      character: "xiao_sai",
      assetType: "meme_sticker",
      department: "品牌部",
      contributor: "内容组",
      emotion: "开心",
      action: "挥手",
      scene: "社群",
      intendedUse: "推送",
      style: "3D",
      tags: "开心,社群",
    });

    const [, request] = clientMocks.POST.mock.calls[0] as [
      string,
      {
        bodySerializer: () => FormData;
        headers?: unknown;
      },
    ];
    const form = request.bodySerializer();
    expect(form.get("file")).toBe(file);
    expect(form.get("character")).toBe("xiao_sai");
    expect(form.get("asset_type")).toBe("meme_sticker");
    expect(request.headers).toBeUndefined();
  });

  it("sends only the selected raster to the transient recognition endpoint", async () => {
    clientMocks.POST.mockResolvedValue({
      data: {
        action: "挥手",
        asset_type: "meme_sticker",
        character: "xiao_sai",
        emotion: "开心",
        intended_use: "社群",
        model: "glm-4.1v-thinking-flash",
        provider: "zhipu",
        scene: "",
        status: "suggested",
        style: "3D",
        tags: ["开心"],
      },
      error: undefined,
    });
    const file = new File([new Uint8Array([1])], "safe.png", {
      type: "image/png",
    });

    await recognizeIpAsset(file);

    expect(clientMocks.POST).toHaveBeenCalledWith(
      "/api/v1/ip-assets/recognitions",
      expect.objectContaining({ body: { file: "safe.png" } }),
    );
    const [, request] = clientMocks.POST.mock.calls[0] as [
      string,
      { bodySerializer: () => FormData; headers?: unknown },
    ];
    expect(request.bodySerializer().get("file")).toBe(file);
    expect(request.headers).toBeUndefined();
  });
});
