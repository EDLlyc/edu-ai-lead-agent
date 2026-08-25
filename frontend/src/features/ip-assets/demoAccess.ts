const demoAccessStorageKey = "sai.ip-assets.demo-access.v1";
const demoAccessMarker = "granted";

const defaultReturnTarget = "/ip-assets";
const allowedReturnPaths = new Set([
  "/ip-assets",
  "/ip-assets/",
  "/ip-assets/create",
  "/ip-assets/create/",
]);

function getSessionStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function hasIpAssetDemoAccess(): boolean {
  const storage = getSessionStorage();
  if (storage === null) return false;
  try {
    return storage.getItem(demoAccessStorageKey) === demoAccessMarker;
  } catch {
    return false;
  }
}

export function grantIpAssetDemoAccess(): boolean {
  const storage = getSessionStorage();
  if (storage === null) return false;
  try {
    storage.setItem(demoAccessStorageKey, demoAccessMarker);
    return storage.getItem(demoAccessStorageKey) === demoAccessMarker;
  } catch {
    return false;
  }
}

export function clearIpAssetDemoAccess(): void {
  const storage = getSessionStorage();
  if (storage === null) return;
  try {
    storage.removeItem(demoAccessStorageKey);
  } catch {
    // A restricted browser session already behaves as logged out.
  }
}

export function safeIpAssetReturnTarget(candidate: string | null): string {
  if (
    candidate === null ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//")
  ) {
    return defaultReturnTarget;
  }
  try {
    const target = new URL(candidate, window.location.origin);
    if (
      target.origin !== window.location.origin ||
      !allowedReturnPaths.has(target.pathname)
    ) {
      return defaultReturnTarget;
    }
    return `${target.pathname}${target.search}`;
  } catch {
    return defaultReturnTarget;
  }
}

export function currentIpAssetReturnTarget(): string {
  return safeIpAssetReturnTarget(
    `${window.location.pathname}${window.location.search}`,
  );
}

export function ipAssetLoginPath(returnTarget: string): string {
  const safeTarget = safeIpAssetReturnTarget(returnTarget);
  const query = new URLSearchParams({ returnTo: safeTarget });
  return `/ip-assets/login?${query.toString()}`;
}

export function replaceIpAssetLocation(target: string): void {
  window.history.replaceState(null, "", target);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function leaveIpAssetDemo(returnTarget: string): void {
  clearIpAssetDemoAccess();
  replaceIpAssetLocation(ipAssetLoginPath(returnTarget));
}
