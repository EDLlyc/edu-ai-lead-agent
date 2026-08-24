import { useEffect } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createIpAssetGeneration,
  downloadIpAssetPackage,
  getIpAsset,
  getIpAssetCapabilities,
  getIpAssetGeneration,
  listIpAssets,
  recognizeIpAsset,
  searchIpAssetsImage,
  searchIpAssetsText,
  uploadIpAsset,
  type IpAssetFilters,
} from "./api";

export const ipAssetKeys = {
  all: ["ip-assets"] as const,
  capabilities: () => [...ipAssetKeys.all, "capabilities"] as const,
  list: (filters: IpAssetFilters) =>
    [...ipAssetKeys.all, "list", filters] as const,
  detail: (assetRef: string) =>
    [...ipAssetKeys.all, "detail", assetRef] as const,
  generation: (jobRef: string) =>
    [...ipAssetKeys.all, "generation", jobRef] as const,
} as const;

export function useIpAssetCapabilities() {
  return useQuery({
    queryKey: ipAssetKeys.capabilities(),
    queryFn: ({ signal }) => getIpAssetCapabilities(signal),
  });
}

export function useIpAssets(filters: IpAssetFilters, enabled = true) {
  return useInfiniteQuery({
    queryKey: ipAssetKeys.list(filters),
    queryFn: ({ signal, pageParam }) =>
      listIpAssets(filters, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled,
  });
}

export function useIpAssetDetail(assetRef: string | null) {
  return useQuery({
    queryKey: ipAssetKeys.detail(assetRef ?? ""),
    queryFn: ({ signal }) => getIpAsset(assetRef ?? "", signal),
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

export function useIpAssetPackageDownload() {
  return useMutation({ mutationFn: downloadIpAssetPackage });
}

export function useCreateIpAssetGeneration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createIpAssetGeneration,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: ipAssetKeys.all }),
  });
}

export function useIpAssetGeneration(jobRef: string | null) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ipAssetKeys.generation(jobRef ?? ""),
    queryFn: ({ signal }) => getIpAssetGeneration(jobRef ?? "", signal),
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
    void client.invalidateQueries({
      queryKey: [...ipAssetKeys.all, "list"],
    });
  }, [client, outputAssetRef, status]);

  return query;
}
