import type { components } from "@/lib/api/generated/schema";
import { apiClient } from "@/lib/api/client";

export type MaterialPackage = components["schemas"]["MaterialPackageResponse"];
export type MaterialPackageList =
  components["schemas"]["MaterialPackageListResponse"];

export async function listMaterialPackages(): Promise<MaterialPackageList> {
  const { data, error } = await apiClient.GET("/api/v1/material-packages");
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_list_failed" : "material_api_error",
    );
  return data;
}

export async function getMaterialPackage(
  packageId: string,
): Promise<MaterialPackage> {
  const { data, error } = await apiClient.GET(
    "/api/v1/material-packages/{package_id}",
    { params: { path: { package_id: packageId } } },
  );
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_detail_failed" : "material_api_error",
    );
  return data;
}

export async function generateMaterialPackage(
  copyGenerationRunId: string,
): Promise<MaterialPackage> {
  const { data, error } = await apiClient.POST("/api/v1/material-packages", {
    body: { copy_generation_run_id: copyGenerationRunId, reviewer: "internal" },
  });
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_generate_failed" : "material_api_error",
    );
  return data;
}

export async function reviewMaterialPackage(
  packageId: string,
  decision: "approved" | "rejected",
  note: string,
): Promise<MaterialPackage> {
  const { data, error } = await apiClient.POST(
    "/api/v1/material-packages/{package_id}/review",
    {
      params: { path: { package_id: packageId } },
      body: { decision, reviewer: "internal", note: note || null },
    },
  );
  if (data === undefined)
    throw new Error(
      error === undefined ? "material_review_failed" : "material_api_error",
    );
  return data;
}
