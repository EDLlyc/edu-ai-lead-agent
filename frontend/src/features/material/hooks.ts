import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  generateMaterialPackage,
  getMaterialPackage,
  listMaterialPackages,
  reviewMaterialPackage,
} from "./api";

export const materialPackageKeys = {
  all: ["material-packages"] as const,
  list: () => [...materialPackageKeys.all, "list"] as const,
  detail: (id: string) => [...materialPackageKeys.all, "detail", id] as const,
} as const;

export function useMaterialPackages() {
  return useQuery({
    queryKey: materialPackageKeys.list(),
    queryFn: listMaterialPackages,
  });
}

export function useMaterialPackage(id: string | null) {
  return useQuery({
    queryKey: materialPackageKeys.detail(id ?? ""),
    queryFn: () => getMaterialPackage(id ?? ""),
    enabled: id !== null && id.length > 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const imageStatus = query.state.data?.image.status;
      return status === "queued" ||
        status === "ready" ||
        imageStatus === "running"
        ? 2_500
        : false;
    },
  });
}

export function useGenerateMaterialPackage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: generateMaterialPackage,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: materialPackageKeys.all }),
  });
}

export function useReviewMaterialPackage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      packageId,
      decision,
      note,
    }: Readonly<{
      packageId: string;
      decision: "approved" | "rejected";
      note: string;
    }>) => reviewMaterialPackage(packageId, decision, note),
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: materialPackageKeys.all }),
  });
}
