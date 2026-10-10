import { describe, expect, it } from "vitest";

import { adminDataMode, ADMIN_ENVIRONMENT_LABELS } from "./environment";

describe("explicit admin data environment", () => {
  it.each([undefined, null, "", "development", "prod", "DEMO", true])(
    "does not infer a data source from %s",
    (value) => {
      expect(adminDataMode(value)).toBe("unknown");
    },
  );
  it("only accepts explicit demo/production labels", () => {
    expect(adminDataMode("demo")).toBe("demo");
    expect(adminDataMode("production")).toBe("production");
    expect(ADMIN_ENVIRONMENT_LABELS.demo).toMatch(/模拟数据.*只读/);
    expect(ADMIN_ENVIRONMENT_LABELS.unknown).toContain("环境未配置");
  });
});
