import { useQuery } from "@tanstack/react-query";

import { fetchPreviewManifest, getPreviewManifestUrl } from "./api";

export const previewKeys = {
  all: ["preview"] as const,
  manifest: (manifestUrl: string) =>
    [...previewKeys.all, "manifest", manifestUrl] as const,
};

export function usePreviewManifest(manifestUrl = getPreviewManifestUrl()) {
  return useQuery({
    queryKey: previewKeys.manifest(manifestUrl),
    queryFn: ({ signal }) => fetchPreviewManifest(manifestUrl, signal),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}
