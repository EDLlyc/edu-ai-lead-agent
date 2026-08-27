import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OfficialAccountEditorHandoffViewModel } from "./api";

import { OfficialAccountEditorHandoff } from "./OfficialAccountEditorHandoff";

const mocks = vi.hoisted(() => ({
  getBody: vi.fn(),
  copy: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getOfficialAccountEditorHandoffBody: mocks.getBody,
}));

vi.mock("./clipboard", () => ({ copyRichHtml: mocks.copy }));

const handoff: OfficialAccountEditorHandoffViewModel = {
  state: "ready",
  copyReady: true,
  boundaryLabel: "本地交接，未同步公众号",
  fingerprint: "f".repeat(64),
  identity: {
    rendererVersion: "wechat-editor-handoff-renderer-v1-gzh-xiaosai",
    styleVersion: "wechat-editor-handoff-style-v1-xiaosai-blue",
    themeId: "xiaosai-moyu-layout-v1",
    themeSha256: "a".repeat(64),
  },
  checks: [
    {
      code: "immutable_review_approved",
      label: "最终人工审稿",
      severity: "info",
      passed: true,
      detail: "不可变人工审稿已批准",
    },
    {
      code: "context_image_rights_unverified_direct_use",
      label: "新闻图片权利",
      severity: "warning",
      passed: false,
      detail: "按当前本地策略直接使用，发布权未验证",
    },
  ],
  blockingCodes: [],
  warningCodes: ["context_image_rights_unverified_direct_use"],
  media: [
    {
      name: "context-00.jpg",
      role: "context",
      roleLabel: "新闻原图 01",
      ordinal: 0,
      downloadUrl: "http://127.0.0.1:8000/safe/context-00.jpg",
      mediaType: "image/jpeg",
      byteSize: 128,
      sha256: "b".repeat(64),
      dimensionsLabel: "1200 × 800",
      altText: "新闻现场",
      sourcePageUrl: "https://example.invalid/news",
      credit: "来源机构",
      rightsStatus: "publish_permission_unverified",
    },
    {
      name: "cover-wide.jpg",
      role: "cover",
      roleLabel: "2.35:1 封面",
      ordinal: 0,
      downloadUrl: "http://127.0.0.1:8000/safe/cover-wide.jpg",
      mediaType: "image/jpeg",
      byteSize: 256,
      sha256: "c".repeat(64),
      dimensionsLabel: "1923 × 818",
      altText: "文章封面",
      sourcePageUrl: null,
      credit: null,
      rightsStatus: null,
    },
  ],
  mobileStatus: "not_run",
  bodyUrl: "http://127.0.0.1:8000/safe/body",
  previewUrl: "http://127.0.0.1:8000/safe/preview",
  bundleUrl: "http://127.0.0.1:8000/safe/bundle",
  bundleFilename: "wechat-editor-handoff-safe.zip",
  bundleSha256: "d".repeat(64),
};

describe("OfficialAccountEditorHandoff", () => {
  beforeEach(() => {
    mocks.getBody.mockReset().mockResolvedValue("<section>正文</section>");
    mocks.copy.mockReset().mockResolvedValue({ status: "copied" });
  });

  it("shows typed gates, direct-use disclosure, sandbox preview and downloads", async () => {
    const { container } = render(
      <OfficialAccountEditorHandoff
        runId="00000000-0000-4000-8000-000000000001"
        handoff={handoff}
        loading={false}
        error={null}
      />,
    );

    expect(screen.getByText("微信公众号编辑器交接")).toBeInTheDocument();
    expect(
      screen.getByText(/发布权未验证；来源和署名会保留/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载交接 ZIP" })).toHaveAttribute(
      "download",
      "wechat-editor-handoff-safe.zip",
    );
    expect(screen.getByTitle("微信公众号编辑器交接预览")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    expect(
      screen.getByRole("link", { name: "查看新闻来源页" }),
    ).toHaveAttribute("href", "https://example.invalid/news");
    expect(container.querySelector("[dangerouslySetInnerHTML]")).toBeNull();
    expect((await axe(container, { iframes: false })).violations).toEqual([]);
  });

  it("announces copy success only after body fetch and clipboard acceptance", async () => {
    const user = userEvent.setup();
    render(
      <OfficialAccountEditorHandoff
        runId="00000000-0000-4000-8000-000000000001"
        handoff={handoff}
        loading={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: "复制公众号正文" }));

    expect(mocks.getBody).toHaveBeenCalledWith(
      "00000000-0000-4000-8000-000000000001",
    );
    expect(mocks.copy).toHaveBeenCalledWith("<section>正文</section>");
    expect(screen.getByText(/正文富文本已复制/)).toBeInTheDocument();
  });

  it("keeps copy and ZIP unavailable for a blocked projection", () => {
    render(
      <OfficialAccountEditorHandoff
        runId="00000000-0000-4000-8000-000000000001"
        handoff={{
          ...handoff,
          state: "blocked",
          copyReady: false,
          blockingCodes: ["immutable_review_pending"],
          bodyUrl: null,
          previewUrl: null,
          bundleUrl: null,
          bundleFilename: null,
        }}
        loading={false}
        error={null}
      />,
    );

    expect(
      screen.getByRole("button", { name: "复制公众号正文" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载交接 ZIP" })).toBeDisabled();
  });
});
