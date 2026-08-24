import type { components } from "@/lib/api/generated/schema";
import { apiBaseUrl, apiClient, resolveApiResourceUrl } from "@/lib/api/client";

export type IpAsset = components["schemas"]["IpAssetCardResponse"];
export type IpAssetDetail = components["schemas"]["IpAssetDetailResponse"];
export type IpAssetCapabilities =
  components["schemas"]["IpAssetCapabilitiesResponse"];
export type IpAssetCharacter = components["schemas"]["IpAssetCharacter"];
export type IpAssetType = components["schemas"]["IpAssetType"];
export type IpAssetSource = components["schemas"]["IpAssetSource"];
export type IpAssetOrientation = components["schemas"]["IpAssetOrientation"];
export type IpAssetSearchResponse =
  components["schemas"]["IpAssetSearchResponse"];
export type IpAssetUploadResponse =
  components["schemas"]["IpAssetUploadResponse"];
export type IpAssetRecognition =
  components["schemas"]["IpAssetRecognitionResponse"];
export type IpAssetGeneration =
  components["schemas"]["IpAssetGenerationResponse"];

export type IpAssetFilters = Readonly<{
  query: string;
  character: IpAssetCharacter | "";
  assetType: IpAssetType | "";
  sourceKind: IpAssetSource | "";
  orientation: IpAssetOrientation | "";
  department: string;
  tag: string;
}>;

export const emptyIpAssetFilters: IpAssetFilters = {
  query: "",
  character: "",
  assetType: "",
  sourceKind: "",
  orientation: "",
  department: "",
  tag: "",
};

export type IpAssetUploadInput = Readonly<{
  file: File;
  character: IpAssetCharacter;
  assetType: IpAssetType;
  department: string;
  contributor: string;
  emotion: string;
  action: string;
  scene: string;
  intendedUse: string;
  style: string;
  tags: string;
}>;

export type IpAssetGenerationInput = Readonly<{
  prompt: string;
  character: IpAssetCharacter;
  assetType: IpAssetType;
  department: string;
  contributor: string;
  referenceAssetRef: string | null;
  idempotencyKey: string;
}>;

export async function getIpAssetCapabilities(
  signal?: AbortSignal,
): Promise<IpAssetCapabilities> {
  const { data, error } = await apiClient.GET(
    "/api/v1/ip-assets/capabilities",
    signal === undefined ? {} : { signal },
  );
  if (data === undefined) throwIpAssetError(error, "capabilities_failed");
  return data;
}

export async function listIpAssets(
  filters: IpAssetFilters,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<components["schemas"]["IpAssetListResponse"]> {
  const { data, error } = await apiClient.GET("/api/v1/ip-assets", {
    params: {
      query: {
        query: filters.query,
        department: filters.department,
        tag: filters.tag,
        cursor,
        limit: 60,
        ...(filters.character === "" ? {} : { character: filters.character }),
        ...(filters.assetType === "" ? {} : { asset_type: filters.assetType }),
        ...(filters.sourceKind === ""
          ? {}
          : { source_kind: filters.sourceKind }),
        ...(filters.orientation === ""
          ? {}
          : { orientation: filters.orientation }),
      },
    },
    ...(signal === undefined ? {} : { signal }),
  });
  if (data === undefined) throwIpAssetError(error, "asset_list_failed");
  return data;
}

export async function getIpAsset(
  assetRef: string,
  signal?: AbortSignal,
): Promise<IpAssetDetail> {
  const { data, error } = await apiClient.GET("/api/v1/ip-assets/{asset_ref}", {
    params: { path: { asset_ref: assetRef } },
    ...(signal === undefined ? {} : { signal }),
  });
  if (data === undefined) throwIpAssetError(error, "asset_detail_failed");
  return data;
}

export async function uploadIpAsset(
  input: IpAssetUploadInput,
): Promise<IpAssetUploadResponse> {
  const wire = {
    action: input.action,
    asset_type: input.assetType,
    character: input.character,
    contributor: input.contributor,
    department: input.department,
    emotion: input.emotion,
    file: input.file.name,
    intended_use: input.intendedUse,
    scene: input.scene,
    style: input.style,
    tags: input.tags,
  };
  const { data, error } = await apiClient.POST("/api/v1/ip-assets", {
    body: wire,
    bodySerializer: () => {
      const form = new FormData();
      form.set("file", input.file);
      form.set("character", input.character);
      form.set("asset_type", input.assetType);
      form.set("department", input.department);
      form.set("contributor", input.contributor);
      form.set("emotion", input.emotion);
      form.set("action", input.action);
      form.set("scene", input.scene);
      form.set("intended_use", input.intendedUse);
      form.set("style", input.style);
      form.set("tags", input.tags);
      return form;
    },
  });
  if (data === undefined) throwIpAssetError(error, "asset_upload_failed");
  return data;
}

export async function recognizeIpAsset(
  file: File,
): Promise<IpAssetRecognition> {
  const { data, error } = await apiClient.POST(
    "/api/v1/ip-assets/recognitions",
    {
      body: { file: file.name },
      bodySerializer: () => {
        const form = new FormData();
        form.set("file", file);
        return form;
      },
    },
  );
  if (data === undefined) throwIpAssetError(error, "asset_recognition_failed");
  return data;
}

export async function searchIpAssetsText(input: {
  message: string;
  priorTurns: readonly string[];
  filters: IpAssetFilters;
}): Promise<IpAssetSearchResponse> {
  const { data, error } = await apiClient.POST(
    "/api/v1/ip-assets/search/text",
    {
      body: {
        message: input.message,
        prior_turns: [...input.priorTurns].slice(-4),
        department: input.filters.department,
        tag: input.filters.tag,
        limit: 40,
        ...(input.filters.character === ""
          ? {}
          : { character: input.filters.character }),
        ...(input.filters.assetType === ""
          ? {}
          : { asset_type: input.filters.assetType }),
        ...(input.filters.sourceKind === ""
          ? {}
          : { source_kind: input.filters.sourceKind }),
        ...(input.filters.orientation === ""
          ? {}
          : { orientation: input.filters.orientation }),
      },
    },
  );
  if (data === undefined) throwIpAssetError(error, "asset_search_failed");
  return data;
}

export async function searchIpAssetsImage(input: {
  file: File;
  filters: IpAssetFilters;
}): Promise<IpAssetSearchResponse> {
  const wire = {
    file: input.file.name,
    limit: 40,
    ...(input.filters.character === ""
      ? {}
      : { character: input.filters.character }),
    ...(input.filters.assetType === ""
      ? {}
      : { asset_type: input.filters.assetType }),
    ...(input.filters.orientation === ""
      ? {}
      : { orientation: input.filters.orientation }),
  };
  const { data, error } = await apiClient.POST(
    "/api/v1/ip-assets/search/image",
    {
      body: wire,
      bodySerializer: () => {
        const form = new FormData();
        form.set("file", input.file);
        form.set("limit", "40");
        if (input.filters.character !== "")
          form.set("character", input.filters.character);
        if (input.filters.assetType !== "")
          form.set("asset_type", input.filters.assetType);
        if (input.filters.orientation !== "")
          form.set("orientation", input.filters.orientation);
        return form;
      },
    },
  );
  if (data === undefined) throwIpAssetError(error, "image_search_failed");
  return data;
}

export async function createIpAssetGeneration(
  input: IpAssetGenerationInput,
): Promise<IpAssetGeneration> {
  const { data, error } = await apiClient.POST(
    "/api/v1/ip-assets/generations",
    {
      body: {
        prompt: input.prompt,
        character: input.character,
        asset_type: input.assetType,
        department: input.department,
        contributor: input.contributor,
        ratio: "1:1",
        idempotency_key: input.idempotencyKey,
        reference_asset_ref: input.referenceAssetRef,
      },
    },
  );
  if (data === undefined) throwIpAssetError(error, "generation_failed");
  return data;
}

export async function getIpAssetGeneration(
  jobRef: string,
  signal?: AbortSignal,
): Promise<IpAssetGeneration> {
  const { data, error } = await apiClient.GET(
    "/api/v1/ip-assets/generations/{job_ref}",
    {
      params: { path: { job_ref: jobRef } },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined) throwIpAssetError(error, "generation_status_failed");
  return data;
}

export async function downloadIpAssetPackage(
  assetRefs: readonly string[],
): Promise<void> {
  const response = await fetch(
    new URL("/api/v1/ip-assets/downloads", apiBaseUrl),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_refs: assetRefs }),
    },
  );
  if (!response.ok) throw new Error("asset_download_failed");
  triggerBlobDownload(await response.blob(), "ip-assets.zip");
}

export function ipAssetResourceUrl(path: string): string | null {
  const resolved = resolveApiResourceUrl(path);
  if (resolved === null) return null;
  try {
    const resource = new URL(resolved);
    const api = new URL(apiBaseUrl);
    return resource.origin === api.origin ? resource.toString() : null;
  } catch {
    return null;
  }
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function throwIpAssetError(error: unknown, fallback: string): never {
  void error;
  throw new Error(fallback);
}
