import createClient from "openapi-fetch";

import type { paths } from "./generated/schema";

export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const apiClient = createClient<paths>({
  baseUrl: apiBaseUrl,
});

export function resolveApiResourceUrl(resourceUrl: string): string | null {
  try {
    const url = new URL(resourceUrl, apiBaseUrl);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}
