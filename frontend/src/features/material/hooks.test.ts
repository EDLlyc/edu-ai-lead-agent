import { describe, expect, it } from "vitest";

import { shouldPollMaterialPackage } from "./hooks";

describe("shouldPollMaterialPackage", () => {
  it.each([
    ["queued image", "queued", "queued", true],
    ["running image", "queued", "running", true],
    ["ready package", "ready", "succeeded", false],
    ["awaiting manual use", "awaiting_manual_use", "succeeded", false],
    ["completed package", "completed", "succeeded", false],
    ["failed image", "failed", "failed", false],
    ["review-required image", "failed", "review_required", false],
  ] as const)("handles %s", (_label, packageStatus, imageStatus, expected) => {
    expect(
      shouldPollMaterialPackage({
        status: packageStatus,
        image: { status: imageStatus },
      }),
    ).toBe(expected);
  });

  it("does not schedule a second request before the first response", () => {
    expect(shouldPollMaterialPackage(undefined)).toBe(false);
  });
});
