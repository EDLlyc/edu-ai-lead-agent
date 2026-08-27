export type RichClipboardResult =
  | Readonly<{ status: "copied" }>
  | Readonly<{ status: "unavailable" }>
  | Readonly<{ status: "permission_denied" }>
  | Readonly<{ status: "failed" }>;

export async function copyRichHtml(
  html: string,
  clipboard: Clipboard | undefined = navigator.clipboard,
): Promise<RichClipboardResult> {
  if (
    clipboard?.write === undefined ||
    typeof globalThis.ClipboardItem === "undefined"
  ) {
    return { status: "unavailable" };
  }
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const plainText = parsed.body.textContent ?? "";
  try {
    await clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([plainText], { type: "text/plain" }),
      }),
    ]);
    return { status: "copied" };
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "NotAllowedError") {
      return { status: "permission_denied" };
    }
    return { status: "failed" };
  }
}
