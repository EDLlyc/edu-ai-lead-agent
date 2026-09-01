import { afterEach, describe, expect, it, vi } from "vitest";

import { copyRichHtml } from "./clipboard";

class FakeClipboardItem {
  readonly items: ClipboardItemData;

  constructor(items: ClipboardItemData) {
    this.items = items;
  }
}

describe("official-account rich clipboard", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("writes both HTML and plain text only after the browser accepts", async () => {
    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    const write = vi.fn().mockResolvedValue(undefined);

    const result = await copyRichHtml(
      '<section><span leaf="">安全正文</span></section>',
      { write } as unknown as Clipboard,
    );

    expect(result.status).toBe("copied");
    expect(write).toHaveBeenCalledOnce();
  });

  it("distinguishes unavailable, permission denied and generic failure", async () => {
    expect(
      (await copyRichHtml("<section>正文</section>", {} as Clipboard)).status,
    ).toBe("unavailable");

    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    const denied = await copyRichHtml("<section>正文</section>", {
      write: vi
        .fn()
        .mockRejectedValue(new DOMException("denied", "NotAllowedError")),
    } as unknown as Clipboard);
    const failed = await copyRichHtml("<section>正文</section>", {
      write: vi.fn().mockRejectedValue(new Error("failed")),
    } as unknown as Clipboard);

    expect(denied.status).toBe("permission_denied");
    expect(failed.status).toBe("failed");
  });

  it("falls back to a local selection copy when rich ClipboardItem is unavailable", async () => {
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    const result = await copyRichHtml(
      '<section><span leaf="">兼容正文</span></section>',
      {} as Clipboard,
      document,
    );

    expect(result.status).toBe("copied");
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector('[aria-hidden="true"]')).toBeNull();
  });
});
