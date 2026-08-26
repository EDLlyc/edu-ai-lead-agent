import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/schema";

const apiMocks = vi.hoisted(() => {
  const digitalIpProfile: components["schemas"]["DigitalIpProfileResponse"] = {
    profile_id: "sai-xiansheng-xiao-sai" as const,
    profile_version: "digital-ip-profile-v1" as const,
    display_name: "赛先生与小赛",
    brand_slug: "sai-xiansheng" as const,
    identity_summary: "赛先生品牌与小赛数字角色的本地受控资产视图",
    characters: [
      {
        character_id: "sai-xiansheng",
        display_name: "赛先生",
        role: "品牌主体",
      },
      {
        character_id: "xiao-sai",
        display_name: "小赛",
        role: "数字角色",
      },
    ],
    audiences: ["parents" as const, "internal" as const],
    channels: ["wechat_moments", "internal_copy_generation"],
    content_scenarios: ["science_education", "parent_communication"],
    document_bindings: [
      {
        document_id: "00000000-0000-4000-8000-000000000001",
        version_id: "00000000-0000-4000-8000-000000000002",
        version: 2,
        title: "家长沟通语气规范",
        document_kind: "tone" as const,
        audience: "parents" as const,
        valid_from: "2026-01-01",
        valid_until: null,
        tone_tags: ["准确", "温暖"],
        safety_tags: ["不制造焦虑"],
        visual_tags: ["3d"],
      },
    ],
    active_document_count: 1,
    active_version_ids: ["00000000-0000-4000-8000-000000000002"],
    document_kinds: ["tone" as const],
    tone_tags: ["准确", "温暖"],
    safety_tags: ["不制造焦虑"],
    visual_tags: ["3d"],
    visual_catalog_status: "ready" as const,
    visual_catalog_version: "brand-visual-catalog-v1",
    visual_assets: [
      {
        asset_ref: "aaaaaaaaaaaaaaaa",
        checksum_ref: "aaaaaaaaaaaaaaaa",
        display_name: "小赛讲解",
        asset_kind: "identity" as const,
        characters: ["xiao-sai"],
        roles: ["identity_reference"],
        topics: ["science"],
        poses: ["explaining"],
        scene_tags: ["classroom"],
        width: 1024,
        height: 1024,
        approved: true as const,
        priority: 100,
      },
    ],
    profile_fingerprint: "a".repeat(64),
    evidence_eligible: false as const,
  };
  return {
    activateBrandVersion: vi.fn(),
    deactivateBrandDocument: vi.fn(),
    digitalIpProfile,
    getDigitalIpProfile: vi.fn(() => Promise.resolve(digitalIpProfile)),
    listBrandDocuments: vi.fn(() => Promise.resolve({ items: [], count: 0 })),
    retrieveBrandContext: vi.fn(),
    uploadBrandDocument: vi.fn(() =>
      Promise.resolve({
        created: true,
        document_id: "00000000-0000-4000-8000-000000000001",
        document_url:
          "/api/v1/brand-documents/00000000-0000-4000-8000-000000000001",
        ingestion_job_id: "00000000-0000-4000-8000-000000000003",
        status: "queued",
        status_url:
          "/api/v1/brand-ingestion-jobs/00000000-0000-4000-8000-000000000003",
        version_id: "00000000-0000-4000-8000-000000000002",
      }),
    ),
  };
});

vi.mock("@/features/brand/api", () => apiMocks);
vi.mock("@/features/official-account-local/OfficialAccountLocalPanel", () => ({
  OfficialAccountLocalPanel: () => (
    <section>
      <h2>公众号本地草稿台</h2>
      <p>本地模拟，未同步公众号</p>
    </section>
  ),
}));
import { App } from "./App";

afterEach(() => {
  vi.unstubAllEnvs();
  window.localStorage.clear();
  vi.clearAllMocks();
});

function TestProviders({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function renderApp() {
  return render(<App />, { wrapper: TestProviders });
}

describe("brand knowledge workspace", () => {
  it("keeps the Agent workbench absent without an explicit local flag", () => {
    renderApp();

    expect(
      screen.queryByRole("heading", { name: "Agent 研究工作台" }),
    ).not.toBeInTheDocument();
  });

  it("loads the Agent workbench only after the local development opt-in", async () => {
    vi.stubEnv("VITE_AGENT_WORKBENCH_ENABLED", "true");
    renderApp();

    expect(
      await screen.findByRole(
        "heading",
        { name: "Agent 研究工作台" },
        { timeout: 5_000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("仅限本地开发")).toBeVisible();
  });

  it("loads the local article workbench only after its development opt-in", async () => {
    vi.stubEnv("VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED", "true");
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "公众号本地草稿台" }),
    ).toBeInTheDocument();
    expect(screen.getByText("本地模拟，未同步公众号")).toBeVisible();
  });

  it("keeps the standalone IP asset hub outside the shared console tree", () => {
    vi.stubEnv("VITE_IP_ASSET_HUB_ENABLED", "true");
    renderApp();

    expect(
      screen.queryByRole("heading", { name: "IP 数字资产中心" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("公司内网 · 无登录")).not.toBeInTheDocument();
  });

  it("positions brand retrieval as internal copy-generation context", async () => {
    renderApp();

    expect(
      screen.getByRole("heading", { level: 1, name: /品牌知识/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "文案上下文召回测试" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/不是面向家长的检索服务/)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "家长语境检索" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("品牌资料不能证明外部事实")).toBeInTheDocument();
    expect(screen.getByText(/最大 25 MiB/)).toBeInTheDocument();
    expect(await screen.findByText("等待第一份品牌资料")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /发布/ }),
    ).not.toBeInTheDocument();
  });

  it("shows the structured digital IP profile and approved visual metadata", async () => {
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "赛先生与小赛" }),
    ).toBeInTheDocument();
    expect(screen.getByText("品牌主体")).toBeVisible();
    expect(screen.getByText("数字角色")).toBeVisible();
    expect(screen.getByText("小赛讲解")).toBeVisible();
    expect(screen.getByText(/REF aaaaaaaaaaaaaaaa/)).toBeVisible();
    expect(screen.getByText("ACTIVE / READY")).toBeVisible();
    expect(screen.getByText("有效期：2026-01-01 → 长期有效")).toBeVisible();
    expect(screen.getByText("identity_reference")).toBeVisible();
    expect(screen.getByText("science")).toBeVisible();
    expect(screen.getByText("不制造焦虑")).toBeVisible();
    expect(document.body.textContent).not.toContain("relative_path");
    expect(document.body.textContent).not.toContain("private/brand-materials");
  });

  it("keeps text identity available when the visual manifest is unavailable", async () => {
    apiMocks.getDigitalIpProfile.mockResolvedValueOnce({
      ...apiMocks.digitalIpProfile,
      visual_catalog_status: "unavailable",
      visual_catalog_version: null,
      visual_assets: [],
    });
    renderApp();

    expect(await screen.findByText("视觉 manifest 当前不可用")).toBeVisible();
    expect(screen.getByText("赛先生")).toBeVisible();
    expect(screen.getByText(/不会暴露私有路径/)).toBeVisible();
  });

  it("keeps the document workflow usable when the profile request fails", async () => {
    apiMocks.getDigitalIpProfile.mockRejectedValueOnce(
      new Error("digital_ip_profile_failed"),
    );
    renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "数字 IP 人设暂不可用",
    );
    expect(screen.getByText("等待第一份品牌资料")).toBeVisible();
    expect(screen.getByRole("form", { name: "上传品牌资料" })).toBeVisible();
  });

  it("explains retrieval provenance and stores bounded browser-local feedback", async () => {
    const user = userEvent.setup();
    apiMocks.retrieveBrandContext.mockResolvedValueOnce({
      retrieval_version: "brand-hybrid-rrf-v2-diverse",
      query: "面向家长介绍人工智能时，如何保持准确和克制？",
      audience: "parents",
      valid_on: "2026-08-18",
      items: [
        {
          chunk_id: "00000000-0000-4000-8000-000000000010",
          document_id: "00000000-0000-4000-8000-000000000001",
          version_id: "00000000-0000-4000-8000-000000000002",
          document_title: "家长沟通语气规范",
          document_kind: "tone",
          audience: "parents",
          text: "准确解释技术边界，避免夸大效果。",
          tone_tags: ["准确", "克制"],
          safety_tags: ["不作效果承诺"],
          visual_tags: ["3d"],
          full_text_score: 0.72,
          vector_score: 0.81,
          fused_score: 0.91,
        },
      ],
      count: 1,
      evidence_eligible: false,
    });
    renderApp();

    await user.click(screen.getByRole("button", { name: "测试生成上下文" }));
    expect(
      await screen.findByText("准确解释技术边界，避免夸大效果。"),
    ).toBeVisible();
    expect(screen.getByText("VERSION / 00000000")).toBeVisible();
    expect(screen.getByText("evidence_eligible = false")).toBeVisible();
    expect(screen.getByText("0.9100")).toBeVisible();

    await user.click(screen.getByRole("radio", { name: "不采纳" }));
    await user.selectOptions(screen.getByLabelText("受控原因"), "missing_rule");
    await user.type(screen.getByLabelText(/短备注/), "需要补充渠道规则");
    await user.click(screen.getByRole("button", { name: "保存本地反馈" }));

    expect(await screen.findByText("当前浏览器：1 条")).toBeVisible();
    expect(screen.getByText(/不会自动修改品牌知识/)).toBeVisible();
    const stored = window.localStorage.getItem(
      "edu-ai-lead-agent.digital-ip-feedback.v1",
    );
    expect(stored).not.toBeNull();
    expect(stored).not.toContain("准确解释技术边界");
    expect(stored).not.toContain("面向家长介绍人工智能");

    await user.click(screen.getByRole("button", { name: "清除本地反馈" }));
    expect(await screen.findByText("当前浏览器：0 条")).toBeVisible();
  });

  it("uploads a controlled brand file and announces the durable job", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.type(screen.getByLabelText("文档标题"), "赛先生家长沟通规范");
    await user.upload(
      screen.getByLabelText(/^原始文件/),
      new File(["准确、克制、温暖"], "tone.md", { type: "text/markdown" }),
    );
    const submit = screen.getByRole("button", { name: "上传并建立新版本" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.submit(screen.getByRole("form", { name: "上传品牌资料" }));

    await waitFor(() =>
      expect(apiMocks.uploadBrandDocument).toHaveBeenCalledOnce(),
    );
    expect(
      await screen.findByText(/00000000-0000-4000-8000-000000000003/),
    ).toHaveAttribute("role", "status");
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = renderApp();
    await screen.findByText("等待第一份品牌资料");
    const results = await axe(container);

    expect(
      results.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        targets: violation.nodes.map((node) => node.target),
      })),
    ).toEqual([]);
  });
});
