import { describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/schema";

const clientMocks = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock("@/lib/api/client", () => ({
  apiClient: { GET: clientMocks.GET },
}));

import { getDigitalIpProfile } from "./api";

const profile: components["schemas"]["DigitalIpProfileResponse"] = {
  profile_id: "sai-xiansheng-xiao-sai",
  profile_version: "digital-ip-profile-v1",
  display_name: "赛先生与小赛",
  brand_slug: "sai-xiansheng",
  identity_summary: "本地受控资产视图",
  characters: [],
  audiences: ["parents", "internal"],
  channels: ["internal_copy_generation"],
  content_scenarios: ["brand_copy"],
  document_bindings: [],
  active_document_count: 0,
  active_version_ids: [],
  document_kinds: [],
  tone_tags: [],
  safety_tags: [],
  visual_tags: [],
  visual_catalog_status: "unavailable",
  visual_catalog_version: null,
  visual_assets: [],
  profile_fingerprint: "a".repeat(64),
  evidence_eligible: false,
};

describe("digital IP profile API adapter", () => {
  it("uses the generated read-only endpoint contract", async () => {
    clientMocks.GET.mockResolvedValueOnce({ data: profile });

    await expect(getDigitalIpProfile()).resolves.toEqual(profile);
    expect(clientMocks.GET).toHaveBeenCalledWith("/api/v1/digital-ip/profile");
  });

  it("maps an absent response to the bounded feature error", async () => {
    clientMocks.GET.mockResolvedValueOnce({
      data: undefined,
      error: undefined,
    });

    await expect(getDigitalIpProfile()).rejects.toThrow(
      "digital_ip_profile_failed",
    );
  });
});
