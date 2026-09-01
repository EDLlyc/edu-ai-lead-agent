export type RichClipboardResult =
  | Readonly<{ status: "copied" }>
  | Readonly<{ status: "unavailable" }>
  | Readonly<{ status: "permission_denied" }>
  | Readonly<{ status: "failed" }>;

export async function copyRichHtml(
  html: string,
  clipboard: Clipboard | undefined = navigator.clipboard,
  documentRef: Document = document,
): Promise<RichClipboardResult> {
  if (
    clipboard?.write === undefined ||
    typeof globalThis.ClipboardItem === "undefined"
  ) {
    return copyRichHtmlWithSelection(html, documentRef);
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

function copyRichHtmlWithSelection(
  html: string,
  documentRef: Document,
): RichClipboardResult {
  if (typeof documentRef.execCommand !== "function") {
    return { status: "unavailable" };
  }
  const selection = documentRef.getSelection();
  if (selection === null) return { status: "unavailable" };
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const container = documentRef.createElement("section");
  container.setAttribute("aria-hidden", "true");
  container.style.position = "fixed";
  container.style.inset = "-10000px auto auto -10000px";
  for (const child of Array.from(parsed.body.childNodes)) {
    container.append(documentRef.importNode(child, true));
  }
  documentRef.body.append(container);
  try {
    const range = documentRef.createRange();
    range.selectNodeContents(container);
    selection.removeAllRanges();
    selection.addRange(range);
    return documentRef.execCommand("copy")
      ? { status: "copied" }
      : { status: "failed" };
  } catch {
    return { status: "failed" };
  } finally {
    selection.removeAllRanges();
    container.remove();
  }
}
