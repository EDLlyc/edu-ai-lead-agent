import type { AdminRole } from "./api";

export type AdminSectionKey =
  | "sources"
  | "keywords"
  | "wechat-publish"
  | "wechat-stats"
  | "wechat-accounts"
  | "layout-templates"
  | "poster-styles"
  | "models"
  | "accounts"
  | "account"
  | "audit";

export interface AdminSection {
  readonly key: AdminSectionKey;
  readonly title: string;
  readonly group: string;
  /** `owner` sections hold accounts, secrets or the audit log. */
  readonly role: AdminRole;
  /** Not built yet: what it will do and when (运营后台 plan of 2026-10-08). */
  readonly plan: {
    readonly item: number;
    readonly dates: string;
    readonly summary: string;
  } | null;
}

export const ADMIN_SECTIONS: readonly AdminSection[] = [
  {
    key: "sources",
    title: "新闻源",
    group: "内容来源",
    role: "editor",
    plan: null,
  },
  {
    key: "keywords",
    title: "关键词",
    group: "内容来源",
    role: "editor",
    plan: null,
  },
  {
    key: "wechat-publish",
    title: "发布",
    group: "公众号",
    role: "editor",
    plan: null,
  },
  {
    key: "wechat-stats",
    title: "数据",
    group: "公众号",
    role: "editor",
    plan: null,
  },
  {
    key: "wechat-accounts",
    title: "账号",
    group: "公众号",
    role: "owner",
    plan: null,
  },
  {
    key: "layout-templates",
    title: "排版模板",
    group: "公众号",
    role: "editor",
    plan: null,
  },
  {
    key: "poster-styles",
    title: "海报风格",
    group: "朋友圈",
    role: "editor",
    plan: {
      item: 7,
      dates: "11/5 – 11/11",
      summary: "选择朋友圈长图海报的配色和版式，先出样图，老师确认后启用。",
    },
  },
  {
    key: "models",
    title: "模型配置",
    group: "系统",
    role: "owner",
    plan: {
      item: 8,
      dates: "11/11 – 11/16",
      summary:
        "配置大模型的接口地址和 API key，保存前先测试能否连通；key 只显示末 4 位。",
    },
  },
  {
    key: "audit",
    title: "操作记录",
    group: "系统",
    role: "owner",
    plan: null,
  },
  {
    key: "accounts",
    title: "账号管理",
    group: "系统",
    role: "owner",
    plan: null,
  },
  {
    key: "account",
    title: "我的账号",
    group: "系统",
    role: "editor",
    plan: null,
  },
];

export function visibleSections(role: AdminRole): readonly AdminSection[] {
  return ADMIN_SECTIONS.filter(
    (section) => role === "owner" || section.role === role,
  );
}

export function sectionFromPath(pathname: string): AdminSectionKey | null {
  const match = /^\/admin\/([a-z-]+)\/?$/.exec(pathname);
  const key = match?.[1];
  return ADMIN_SECTIONS.find((section) => section.key === key)?.key ?? null;
}
