export type AdminDataMode = "demo" | "production" | "unknown";

/** An operator-supplied label, never an authentication or write-access check. */
export function adminDataMode(value: unknown): AdminDataMode {
  return value === "demo" || value === "production" ? value : "unknown";
}

export const ADMIN_ENVIRONMENT_LABELS: Readonly<Record<AdminDataMode, string>> =
  {
    demo: "演示环境 · 模拟数据 · 只读",
    production: "生产环境 · 真实数据",
    unknown: "环境未配置 · 请确认数据来源",
  };
