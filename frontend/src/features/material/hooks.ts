import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  generateMaterialPackage,
  getMaterialPackage,
  listMaterialPackages,
  reviewMaterialPackage,
  type ImageArtifactStatus,
  type MaterialPackageResponse,
} from "./api";

export const materialPackageKeys = {
  all: ["material-packages"] as const,
  list: () => [...materialPackageKeys.all, "list"] as const,
  detail: (id: string) => [...materialPackageKeys.all, "detail", id] as const,
} as const;

export function useMaterialPackages() {
  return useQuery({
    queryKey: materialPackageKeys.list(),
    queryFn: ({ signal }) => listMaterialPackages(signal),
  });
}

export function useMaterialPackage(id: string | null) {
  return useQuery({
    queryKey: materialPackageKeys.detail(id ?? ""),
    queryFn: ({ signal }) => getMaterialPackage(id ?? "", signal),
    enabled: id !== null && id.length > 0,
    refetchInterval: (query) =>
      shouldPollMaterialPackage(query.state.data) ? 2_500 : false,
  });
}

export function shouldPollMaterialPackage(
  materialPackage:
    | Readonly<{
        status: MaterialPackageResponse["status"];
        image: Readonly<{ status: ImageArtifactStatus }>;
      }>
    | undefined,
): boolean {
  if (materialPackage === undefined || materialPackage.status !== "queued") {
    return false;
  }
  return (
    materialPackage.image.status === "queued" ||
    materialPackage.image.status === "running"
  );
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
