const PROFILE_STORAGE_KEY = "edu-ai.ip-assets.profile.v1";
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const PROFILE_REF_PATTERN = /^ipp_[a-f0-9]{20}$/;

export type LocalIpAssetProfile = Readonly<{
  token: string;
  profileRef: string;
  displayName: string;
  department: string;
}>;

export function createLocalProfileToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

export function loadLocalIpAssetProfile(): LocalIpAssetProfile | null {
  try {
    const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
    if (raw === null) return null;
    const value: unknown = JSON.parse(raw);
    if (!isStoredProfile(value)) {
      localStorage.removeItem(PROFILE_STORAGE_KEY);
      return null;
    }
    return value;
  } catch {
    localStorage.removeItem(PROFILE_STORAGE_KEY);
    return null;
  }
}

export function saveLocalIpAssetProfile(profile: LocalIpAssetProfile): void {
  localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
}

export function clearLocalIpAssetProfile(): void {
  localStorage.removeItem(PROFILE_STORAGE_KEY);
}

function isStoredProfile(value: unknown): value is LocalIpAssetProfile {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.token === "string" &&
    TOKEN_PATTERN.test(record.token) &&
    typeof record.profileRef === "string" &&
    PROFILE_REF_PATTERN.test(record.profileRef) &&
    typeof record.displayName === "string" &&
    record.displayName.length >= 1 &&
    record.displayName.length <= 80 &&
    typeof record.department === "string" &&
    record.department.length >= 1 &&
    record.department.length <= 80
  );
}
