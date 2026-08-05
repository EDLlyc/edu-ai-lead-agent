import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mapPreviewManifest, PreviewManifestError } from "./api";

const hookMocks = vi.hoisted(() => ({
  usePreviewManifest: vi.fn(),
}));

vi.mock("./hooks", () => hookMocks);

import { PreviewPanel } from "./PreviewPanel";

const readyPreview = mapPreviewManifest(
  {
    schema_version: "preview-manifest-v1",
    run_id: "preview-run-1",
    status: "ready",
    generated_at: "2026-08-05T10:30:00Z",
    business_date: "2026-08-05",
    stages: [
      { id: "acquisition", status: "completed" },
      { id: "topic_selection", status: "completed" },
      { id: "copy_generation", status: "completed" },
      { id: "material_package", status: "completed" },
    ],
    sources: [
      {
        id: "news-1",
        title: "教育部科学教育新闻",
        source_name: "教育部",
        source_tier: "A",
        url: "https://www.moe.gov.cn/news/1",
        published_at: "2026-08-04T09:00:00Z",
        is_selected: true,
      },
    ],
    topic: {
      decision_kind: "selected",
      title: "孩子如何保持科学好奇心",
      summary: "从新闻进入家庭讨论。",
      category: "科学教育",
      source_trust: "教育部权威来源",
      selection_explanation: "来源权威且适合家长理解。",
      score: 0.93,
      selected_candidate_id: "news-1",
    },
    copy: {
      copywriting: "科学教育从提问开始。\n#赛先生科学 #科学教育",
      hashtags: ["#赛先生科学", "#科学教育"],
      parent_takeaway: "把新闻变成一次共同提问。",
      interaction: "你和孩子最近讨论过什么？",
      source_note: "事实已绑定来源。",
    },
    image: {
      status: "succeeded",
      image_url: "https://preview.test/preview-run-1.png",
      filename: "preview-run-1.png",
      media_type: "image/png",
      width: 1024,
      height: 1024,
      validation: { passed: true, version: "image-validation-v1" },
      audit: { status: "accepted", passed: true, version: "image-audit-v1" },
    },
    brand_bindings: [
      {
        id: "brand-1",
        document_title: "赛先生视觉规范",
        role: "identity_reference",
        selection_reason: "匹配科学教育主题。",
      },
    ],
    validation: { passed: true },
    audit: { accepted: true },
  },
  "https://preview.test/manifest.json",
);

function renderPanel(result: Readonly<Record<string, unknown>>) {
  hookMocks.usePreviewManifest.mockReturnValue(result);
  return render(
    <PreviewPanel manifestUrl="https://preview.test/manifest.json" />,
  );
}

describe("PreviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows an accessible loading state", () => {
    renderPanel({ isPending: true, data: undefined, isError: false });

    expect(screen.getByRole("status")).toHaveTextContent(
      "正在读取本地真实预览",
    );
    expect(
      screen.getByRole("heading", { name: "真实预览" }),
    ).toBeInTheDocument();
  });

  it("keeps a loaded but running manifest in the loading state", () => {
    const runningPreview = mapPreviewManifest({
      status: "running",
      run_id: "running-run",
      stages: [
        { id: "acquisition", status: "completed" },
        { id: "copy_generation", status: "running" },
      ],
      topic: { decision_kind: "selected", title: "处理中选题" },
    });
    renderPanel({ isPending: false, data: runningPreview, isError: false });

    expect(screen.getByRole("status")).toHaveTextContent("真实链路仍在处理中");
    expect(
      screen.queryByRole("heading", { name: "完整朋友圈文案" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("朋友圈文案生成")).toBeInTheDocument();
  });

  it("renders provenance, copy, image, quality and manual download actions", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const createObjectUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:preview-package");
    const revokeObjectUrl = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderPanel({ isPending: false, data: readyPreview, isError: false });

    expect(
      screen.getByRole("heading", { name: "阶段状态" }),
    ).toBeInTheDocument();
    expect(screen.getByText("教育部科学教育新闻")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "查看来源（新窗口）" }),
    ).toHaveAttribute("href", "https://www.moe.gov.cn/news/1");
    expect(screen.getByText("孩子如何保持科学好奇心")).toBeInTheDocument();
    expect(screen.getByText("#赛先生科学")).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "孩子如何保持科学好奇心的品牌 IP 预览图片",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("验证通过")).toHaveLength(4);
    expect(screen.getByText("图片已生成")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /发布|发送|post/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "复制文案" }));
    expect(writeText).toHaveBeenCalledWith(readyPreview.copy.copywriting);
    expect(
      await screen.findByText("文案已复制，可由内部人员手动使用。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下载图片" }));
    expect(click).toHaveBeenCalled();
    expect(
      screen.getByText("图片下载已开始，请按人工审核流程使用。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下载预览包" }));
    expect(createObjectUrl).toHaveBeenCalledOnce();
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:preview-package");
    expect(screen.getByText("预览包清单已下载。")).toBeInTheDocument();
  });

  it("shows the empty, failed and review-required states explicitly", () => {
    const emptyPreview = mapPreviewManifest({
      status: "empty",
      run_id: "empty-run",
    });
    renderPanel({ isPending: false, data: emptyPreview, isError: false });
    expect(screen.getByText("还没有可展示的真实预览")).toBeInTheDocument();

    const reviewPreview = mapPreviewManifest({
      status: "review_required",
      run_id: "review-run",
      topic: { decision_kind: "selected", title: "待复核选题" },
      copy: { copywriting: "待复核文案" },
      image: {
        status: "review_required",
        image_url: "https://preview.test/review.png",
        audit: {
          status: "rejected",
          passed: false,
          issue_codes: ["visual_risk"],
        },
      },
    });
    hookMocks.usePreviewManifest.mockReturnValue({
      isPending: false,
      data: reviewPreview,
      isError: false,
    });
    render(<PreviewPanel manifestUrl="https://preview.test/manifest.json" />);
    expect(screen.getByText("待人工复核")).toBeInTheDocument();
    expect(screen.getByText("待复核文案")).toBeInTheDocument();
    expect(screen.getAllByText("visual_risk")).not.toHaveLength(0);
  });

  it("offers retry with a safe error code", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    renderPanel({
      isPending: false,
      data: undefined,
      isError: true,
      error: new PreviewManifestError("not_found", "missing", 404),
      refetch,
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "本地还没有导出的 manifest",
    );
    expect(screen.getByText("安全错误码：not_found")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新读取预览" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("has no detectable accessibility violations in the ready state", async () => {
    const { container } = renderPanel({
      isPending: false,
      data: readyPreview,
      isError: false,
    });
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
