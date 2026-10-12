const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

/** Build-time navigation only: never accept credentials or URL-supplied return targets. */
export function companionEntryUrl(
  value: unknown,
  pageUrl: string,
): string | null {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 2048 ||
    /[\\?#]/u.test(value) ||
    /\s/u.test(value) ||
    !(value.startsWith("/") || /^https?:\/\/[^/]/iu.test(value)) ||
    value.startsWith("//")
  )
    return null;

  try {
    // URL accepts malformed escapes and strips controls. Refuse these before parsing.
    const decoded = decodeURIComponent(value);
    if (
      /[\\\s]/u.test(decoded) ||
      [...decoded].some((character) => {
        const code = character.charCodeAt(0);
        return code < 32 || code === 127;
      })
    )
      return null;
    const page = new URL(pageUrl);
    const destination = new URL(value, page);
    if (
      !["http:", "https:"].includes(page.protocol) ||
      !["http:", "https:"].includes(destination.protocol) ||
      destination.username !== "" ||
      destination.password !== "" ||
      destination.search !== "" ||
      destination.hash !== "" ||
      /^https?:\/\/[^/]*@/iu.test(value) ||
      (page.protocol === "https:" && destination.protocol === "http:") ||
      (LOOPBACK_HOSTS.has(destination.hostname) &&
        destination.hostname !== page.hostname)
    )
      return null;
    return destination.href;
  } catch {
    return null;
  }
}
