import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MaterialPackageListViewModel,
  MaterialPackageViewModel,
} from "./api";

const apiMocks = vi.hoisted(() => ({
  downloadMaterialPackage: vi.fn(),
  generateMaterialPackage: vi.fn(),
  getMaterialPackage: vi.fn(),
  listMaterialPackages: vi.fn(),
  reviewMaterialPackage: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

import { MaterialPackagePanel } from "./MaterialPackagePanel";

const materialPackage: MaterialPackageViewModel = {
  id: "package-1",
  copyGenerationRunId: "run-1",
  status: "awaiting_manual_use",
  statusLabel: "待人工使用",
  reviewStatus: "pending",
  reviewStatusLabel: "待人工审核",
  businessDate: "2026-08-03",
  createdAt: "2026-08-03T08:00:00Z",
  createdAtLabel: "2026年8月3日 16:00",
  detailUrl: "/api/v1/material-packages/package-1",
  packageVersion: 1,
  topic: {
    title: "儿童如何观察一片叶子",
    summary: "从日常观察进入科学提问。",
    category: "科学观察",
    sourceTrust: "权威来源",
    decisionKind: "selected",
    decisionLabel: "已选中",
    explanation: "满足时效、相关性和来源可信度门槛。",
    businessDate: "2026-08-03",
    timezone: "Asia/Shanghai",
    selectedEventId: "event-1",
    selectedEventVersionId: "event-version-1",
    score: 0.92,
    scoreBreakdown: [{ label: "相关性", value: "0.9" }],
  },
  copy: {
    copywriting: "一片叶子，也能成为孩子提出问题的起点。",
    parentTakeaway: "孩子可以从观察开始练习提问。",
    interaction: "你和孩子最近观察过什么？",
    sourceNote: "来源已绑定在下方证据。",
    draftVersionId: "draft-1",
    version: 2,
    claims: [],
  },
  evidence: [
    {
      id: "evidence-1",
      claimId: "claim-1",
      label: "观察研究来源",
      sourceUrl: "https://example.com/evidence",
      sourceTier: "A",
      publishedAt: "2026-08-02",
      exactQuote: "观察是提出问题的入口。",
      claimText: "观察可以成为提问的起点。",
    },
  ],
  brandBindings: [
    {
      id: "binding-1",
      claimId: "claim-1",
      brandChunkId: "brand-chunk-1",
      documentTitle: "赛先生品牌表达规范",
      audience: "parents",
      text: "鼓励从生活经验提出问题。",
      toneTags: ["温暖"],
      safetyTags: ["克制"],
    },
  ],
  validation: {
    passed: true,
    ruleVersion: "validation-v1",
    issues: [],
  },
  audit: {
    accepted: true,
    status: "accepted",
    ruleVersion: "audit-v1",
    promptVersion: "prompt-v1",
    schemaVersion: "schema-v1",
    auditId: "audit-1",
    diagnostic: null,
    issues: [
      {
        id: "audit-style",
        stage: "audit",
        code: "style_note",
        message: "可保持句子简洁。",
        severity: "warning",
        field: "copywriting",
        claimId: null,
      },
    ],
  },
  image: {
    id: "image-1",
    status: "succeeded",
    statusLabel: "图片已生成",
    provider: "fake",
    model: "fake-image",
    width: 1024,
    height: 1024,
    mediaType: "image/png",
    byteSize: 12,
    sha256: "abc",
    errorCode: null,
    downloadUrl: "https://example.com/image.png",
  },
  review: {
    status: "pending",
    statusLabel: "待人工审核",
    note: null,
    reviewedAt: null,
    reviewUrl: "/api/v1/material-packages/package-1/review",
  },
};

const summary = {
  id: materialPackage.id,
  copyGenerationRunId: materialPackage.copyGenerationRunId,
  status: materialPackage.status,
  statusLabel: materialPackage.statusLabel,
  reviewStatus: materialPackage.reviewStatus,
  reviewStatusLabel: materialPackage.reviewStatusLabel,
  businessDate: materialPackage.businessDate,
  createdAt: materialPackage.createdAt,
  createdAtLabel: materialPackage.createdAtLabel,
  detailUrl: materialPackage.detailUrl,
} satisfies MaterialPackageListViewModel["items"][number];

function TestProviders({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function renderPanel(detail = materialPackage) {
  apiMocks.listMaterialPackages.mockResolvedValue({
    items: [summary],
    count: 1,
  } satisfies MaterialPackageListViewModel);
  apiMocks.getMaterialPackage.mockResolvedValue(detail);
  apiMocks.downloadMaterialPackage.mockResolvedValue(detail);
  apiMocks.reviewMaterialPackage.mockResolvedValue(materialPackage);
  return render(<MaterialPackagePanel />, { wrapper: TestProviders });
}

describe("MaterialPackagePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the auditable material-package detail without publishing controls", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "查看素材包详情" }),
    );

    expect(
      await screen.findByRole("heading", { name: "当前状态" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "选题与解释" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "文案" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "图片" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "来源与证据" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "品牌绑定" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "验证与审计" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("满足时效、相关性和来源可信度门槛。"),
    ).toBeInTheDocument();
    expect(screen.getByText("观察是提出问题的入口。")).toBeInTheDocument();
    expect(screen.getByText("brand-chunk-1")).toBeInTheDocument();
    expect(screen.getByText("可保持句子简洁。")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "下载素材包" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /发布|post/i }),
    ).not.toBeInTheDocument();
  });

  it("announces copy and package-download feedback", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const createObjectUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:material-package");
    const revokeObjectUrl = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderPanel();
    await user.click(
      await screen.findByRole("button", { name: "查看素材包详情" }),
    );
    await user.click(screen.getByRole("button", { name: "复制文案" }));
    expect(writeText).toHaveBeenCalledWith(materialPackage.copy.copywriting);
    expect(
      await screen.findByText("文案已复制，可由内部人员手动使用。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下载素材包" }));
    expect(apiMocks.downloadMaterialPackage).toHaveBeenCalledWith("package-1");
    expect(createObjectUrl).toHaveBeenCalledOnce();
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:material-package");
    expect(click).toHaveBeenCalled();
    expect(screen.getByText("素材包清单已下载。")).toBeInTheDocument();

    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
    click.mockRestore();
  });

  it("shows an explicit empty state for packages without evidence or brand bindings", async () => {
    const user = userEvent.setup();
    const emptyPackage = {
      ...materialPackage,
      evidence: [],
      brandBindings: [],
      validation: { ...materialPackage.validation, passed: null },
      audit: {
        ...materialPackage.audit,
        accepted: null,
        status: "unknown" as const,
      },
    };
    renderPanel(emptyPackage);

    await user.click(
      await screen.findByRole("button", { name: "查看素材包详情" }),
    );
    expect(
      await screen.findByText(/没有绑定的内容不能作为外部事实依据/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("该素材包没有返回可展示的品牌片段绑定。"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("未提供").length).toBeGreaterThan(0);
  });
});
