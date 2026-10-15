import { describe, expect, it } from "vitest";

import { passwordStrength } from "./passwordStrength";

describe("passwordStrength", () => {
  it("says nothing for an empty field", () => {
    expect(passwordStrength("")).toBeNull();
  });

  it.each([
    ["short1", "weak"],
    ["19900101", "weak"],
    ["abcdefghij", "weak"],
    ["Aa123456789", "weak"],
    ["liyuchen2026X", "weak"],
    ["a8f3k2m9Qz", "fair"],
    ["my own words 7", "strong"],
    ["Xk9#mP2vL7qR", "strong"],
  ])("rates %s as %s", (password, level) => {
    expect(passwordStrength(password, "liyuchen")?.level).toBe(level);
  });

  it("is only a hint: a weak password still has advice, not a block", () => {
    const weak = passwordStrength("19900101");
    expect(weak?.label).toBe("弱");
    expect(weak?.advice).toContain("字母");
  });
});
