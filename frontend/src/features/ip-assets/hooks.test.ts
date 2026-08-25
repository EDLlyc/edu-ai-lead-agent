import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listPersonalIpAssets: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listPersonalIpAssets: apiMocks.listPersonalIpAssets,
}));

import { emptyIpAssetFilters } from "./api";
import { ipAssetKeys, usePersonalIpAssets } from "./hooks";

const profile = {
  token: "A".repeat(43),
  profileRef: `ipp_${"a".repeat(20)}`,
  displayName: "内容同事",
  department: "品牌部",
};

function Providers({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listPersonalIpAssets.mockResolvedValue({
    items: [],
    next_cursor: null,
  });
});

describe("IP asset query identities", () => {
  it("uses safe profile refs and never needs a raw local token", () => {
    const profileRef = `ipp_${"a".repeat(20)}`;
    const token = "A".repeat(43);
    const keys = [
      ipAssetKeys.list(emptyIpAssetFilters, profileRef),
      ipAssetKeys.detail("ipa_11111111111111111111", profileRef),
      ipAssetKeys.profile(profileRef),
      ipAssetKeys.personal(profileRef, "favorite"),
      ipAssetKeys.generation("ipg_11111111111111111111", profileRef),
    ];

    expect(JSON.stringify(keys)).toContain(profileRef);
    expect(JSON.stringify(keys)).not.toContain(token);
  });

  it("keeps a valid profile query dormant when its explicit enabled gate is false", async () => {
    const { rerender } = renderHook(
      ({ enabled }) => usePersonalIpAssets(profile, "favorite", enabled),
      {
        initialProps: { enabled: false },
        wrapper: Providers,
      },
    );

    await Promise.resolve();
    expect(apiMocks.listPersonalIpAssets).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() =>
      expect(apiMocks.listPersonalIpAssets).toHaveBeenCalledWith(
        expect.objectContaining({
          token: profile.token,
          source: "favorite",
          cursor: null,
        }),
      ),
    );
  });
});
