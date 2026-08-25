import { useEffect } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createIpAssetGeneration,
  bootstrapIpAssetProfile,
  downloadIpAssetPackage,
  getIpAsset,
  getIpAssetCapabilities,
  getIpAssetGeneration,
  getIpAssetLeaderboard,
  listIpAssets,
  listPersonalIpAssets,
  recognizeIpAsset,
  restoreIpAssetProfile,
  searchIpAssetsImage,
  searchIpAssetsText,
  setIpAssetFavorite,
  shareIpAsset,
  uploadIpAsset,
  type IpAssetFilters,
  type IpAssetLeaderboardPeriod,
  type IpAssetPersonalSource,
} from "./api";
import type { LocalIpAssetProfile } from "./profile";

export const ipAssetKeys = {
  all: ["ip-assets"] as const,
  capabilities: () => [...ipAssetKeys.all, "capabilities"] as const,
  list: (filters: IpAssetFilters, profileRef = "anonymous") =>
    [...ipAssetKeys.all, "list", filters, profileRef] as const,
  detail: (assetRef: string, profileRef: string) =>
    [...ipAssetKeys.all, "detail", assetRef, profileRef] as const,
  profile: (profileRef: string) =>
    [...ipAssetKeys.all, "profile", profileRef] as const,
  personal: (profileRef: string, source: IpAssetPersonalSource) =>
    [...ipAssetKeys.all, "personal", profileRef, source] as const,
  generation: (jobRef: string, profileRef: string) =>
    [...ipAssetKeys.all, "generation", jobRef, profileRef] as const,
  leaderboard: (period: IpAssetLeaderboardPeriod) =>
    [...ipAssetKeys.all, "leaderboard", period] as const,
} as const;

export function useIpAssetCapabilities() {
  return useQuery({
    queryKey: ipAssetKeys.capabilities(),
    queryFn: ({ signal }) => getIpAssetCapabilities(signal),
  });
}

export function useIpAssets(
  filters: IpAssetFilters,
  enabled = true,
  profile: LocalIpAssetProfile | null = null,
) {
  return useInfiniteQuery({
    queryKey: ipAssetKeys.list(filters, profile?.profileRef ?? "anonymous"),
    queryFn: ({ signal, pageParam }) =>
      listIpAssets(filters, pageParam, profile?.token, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled,
  });
}

export function useIpAssetDetail(
  assetRef: string | null,
  profile: LocalIpAssetProfile | null = null,
) {
  return useQuery({
    queryKey: ipAssetKeys.detail(
      assetRef ?? "",
      profile?.profileRef ?? "anonymous",
    ),
    queryFn: ({ signal }) => getIpAsset(assetRef ?? "", profile?.token, signal),
    enabled: assetRef !== null,
  });
}

export function useUploadIpAsset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: uploadIpAsset,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: ipAssetKeys.all }),
  });
}

export function useRecognizeIpAsset() {
  return useMutation({ mutationFn: recognizeIpAsset });
}

export function useIpAssetTextSearch() {
  return useMutation({ mutationFn: searchIpAssetsText });
}

export function useIpAssetImageSearch() {
  return useMutation({ mutationFn: searchIpAssetsImage });
}

export function useIpAssetPackageDownload(
  profile: LocalIpAssetProfile | null = null,
) {
  return useMutation({
    mutationFn: (assetRefs: readonly string[]) =>
      downloadIpAssetPackage(assetRefs, profile?.token),
  });
}

export function useCreateIpAssetGeneration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createIpAssetGeneration,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: ipAssetKeys.all }),
  });
}

export function useIpAssetGeneration(
  jobRef: string | null,
  profile: LocalIpAssetProfile | null = null,
) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ipAssetKeys.generation(
      jobRef ?? "",
      profile?.profileRef ?? "anonymous",
    ),
    queryFn: ({ signal }) =>
      getIpAssetGeneration(jobRef ?? "", profile?.token, signal),
    enabled: jobRef !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "queued" || status === "running") return 2_000;
      return false;
    },
  });
  const outputAssetRef = query.data?.output_asset_ref;
  const status = query.data?.status;

  useEffect(() => {
    if (status !== "succeeded" || outputAssetRef == null) return;
    void Promise.all([
      client.invalidateQueries({ queryKey: [...ipAssetKeys.all, "list"] }),
      client.invalidateQueries({ queryKey: [...ipAssetKeys.all, "personal"] }),
    ]);
  }, [client, outputAssetRef, status]);

  return query;
}

export function useRestoreIpAssetProfile(profile: LocalIpAssetProfile | null) {
  return useQuery({
    queryKey: ipAssetKeys.profile(profile?.profileRef ?? "missing"),
    queryFn: ({ signal }) =>
      restoreIpAssetProfile(profile?.token ?? "", signal),
    enabled: profile !== null,
    retry: false,
  });
}

export function useBootstrapIpAssetProfile() {
  return useMutation({ mutationFn: bootstrapIpAssetProfile });
}

export function usePersonalIpAssets(
  profile: LocalIpAssetProfile | null,
  source: IpAssetPersonalSource,
  enabled = true,
) {
  return useInfiniteQuery({
    queryKey: ipAssetKeys.personal(profile?.profileRef ?? "missing", source),
    queryFn: ({ signal, pageParam }) =>
      listPersonalIpAssets({
        token: profile?.token ?? "",
        source,
        cursor: pageParam,
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: profile !== null && enabled,
  });
}

export function useSetIpAssetFavorite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: setIpAssetFavorite,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: ipAssetKeys.all }),
  });
}

export function useShareIpAsset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: shareIpAsset,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: ipAssetKeys.all }),
  });
}

export function useIpAssetLeaderboard(period: IpAssetLeaderboardPeriod) {
  return useQuery({
    queryKey: ipAssetKeys.leaderboard(period),
    queryFn: ({ signal }) => getIpAssetLeaderboard(period, signal),
  });
}
