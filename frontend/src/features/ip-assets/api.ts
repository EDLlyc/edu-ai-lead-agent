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
export type IpAssetProfile = components["schemas"]["IpAssetProfileResponse"];
export type IpAssetPersonalItem =
  components["schemas"]["IpAssetPersonalItemResponse"];
export type IpAssetPersonalSource =
  "all" | "generated" | "uploaded" | "favorite";
export type IpAssetLeaderboard =
  components["schemas"]["IpAssetLeaderboardResponse"];
export type IpAssetLeaderboardPeriod =
  components["schemas"]["IpAssetLeaderboardPeriod"];

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
  profileToken?: string;
}>;

export type IpAssetGenerationInput = Readonly<{
  prompt: string;
  character: IpAssetCharacter;
  assetType: IpAssetType;
  department: string;
  contributor: string;
  referenceAssetRefs: readonly string[];
  idempotencyKey: string;
  profileToken: string;
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
  profileToken?: string,
  signal?: AbortSignal,
): Promise<components["schemas"]["IpAssetListResponse"]> {
  const { data, error } = await apiClient.GET("/api/v1/ip-assets", {
    params: {
      query: {
        query: filters.query,
        department: filters.department,
        tag: filters.tag,
        cursor,
        limit: 16,
        ...(filters.character === "" ? {} : { character: filters.character }),
        ...(filters.assetType === "" ? {} : { asset_type: filters.assetType }),
        ...(filters.sourceKind === ""
          ? {}
          : { source_kind: filters.sourceKind }),
        ...(filters.orientation === ""
          ? {}
          : { orientation: filters.orientation }),
      },
      ...(profileToken === undefined
        ? {}
        : { header: { "X-IP-Profile-Token": profileToken } }),
    },
    ...(signal === undefined ? {} : { signal }),
  });
  if (data === undefined) throwIpAssetError(error, "asset_list_failed");
  return data;
}

export async function getIpAsset(
  assetRef: string,
  profileToken?: string,
  signal?: AbortSignal,
): Promise<IpAssetDetail> {
  const { data, error } = await apiClient.GET("/api/v1/ip-assets/{asset_ref}", {
    params: {
      path: { asset_ref: assetRef },
      ...(profileToken === undefined
        ? {}
        : { header: { "X-IP-Profile-Token": profileToken } }),
    },
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
    params:
      input.profileToken === undefined
        ? {}
        : { header: { "X-IP-Profile-Token": input.profileToken } },
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
  profileToken?: string;
}): Promise<IpAssetSearchResponse> {
  const { data, error } = await apiClient.POST(
    "/api/v1/ip-assets/search/text",
    {
      body: {
        message: input.message,
        prior_turns: [...input.priorTurns].slice(-4),
        department: input.filters.department,
        tag: input.filters.tag,
        limit: 8,
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
      params:
        input.profileToken === undefined
          ? {}
          : { header: { "X-IP-Profile-Token": input.profileToken } },
    },
  );
  if (data === undefined) throwIpAssetError(error, "asset_search_failed");
  return data;
}

export async function searchIpAssetsImage(input: {
  file: File;
  filters: IpAssetFilters;
  profileToken?: string;
}): Promise<IpAssetSearchResponse> {
  const wire = {
    file: input.file.name,
    limit: 8,
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
      params:
        input.profileToken === undefined
          ? {}
          : { header: { "X-IP-Profile-Token": input.profileToken } },
      bodySerializer: () => {
        const form = new FormData();
        form.set("file", input.file);
        form.set("limit", "8");
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
        reference_asset_refs: [...input.referenceAssetRefs],
      },
      params: { header: { "X-IP-Profile-Token": input.profileToken } },
    },
  );
  if (data === undefined) throwIpAssetError(error, "generation_failed");
  return data;
}

export async function getIpAssetGeneration(
  jobRef: string,
  profileToken?: string,
  signal?: AbortSignal,
): Promise<IpAssetGeneration> {
  const { data, error } = await apiClient.GET(
    "/api/v1/ip-assets/generations/{job_ref}",
    {
      params: {
        path: { job_ref: jobRef },
        ...(profileToken === undefined
          ? {}
          : { header: { "X-IP-Profile-Token": profileToken } }),
      },
      ...(signal === undefined ? {} : { signal }),
    },
  );
  if (data === undefined) throwIpAssetError(error, "generation_status_failed");
  return data;
}

export async function downloadIpAssetPackage(
  assetRefs: readonly string[],
  profileToken?: string,
): Promise<void> {
  const response = await fetch(
    new URL("/api/v1/ip-assets/downloads", apiBaseUrl),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(profileToken === undefined
          ? {}
          : { "X-IP-Profile-Token": profileToken }),
      },
      body: JSON.stringify({ asset_refs: assetRefs }),
    },
  );
  if (!response.ok) throw new Error("asset_download_failed");
  triggerBlobDownload(await response.blob(), "ip-assets.zip");
}

export async function bootstrapIpAssetProfile(input: {
  token: string;
  displayName: string;
  department: string;
}): Promise<IpAssetProfile> {
  const { data, error } = await apiClient.POST("/api/v1/ip-assets/profiles", {
    params: { header: { "X-IP-Profile-Token": input.token } },
    body: { display_name: input.displayName, department: input.department },
  });
  if (data === undefined) throwIpAssetError(error, "profile_setup_failed");
  return data;
}

export async function restoreIpAssetProfile(
  token: string,
  signal?: AbortSignal,
): Promise<IpAssetProfile> {
  const { data, error } = await apiClient.GET("/api/v1/ip-assets/profiles/me", {
    params: { header: { "X-IP-Profile-Token": token } },
    ...(signal === undefined ? {} : { signal }),
  });
  if (data === undefined) throwIpAssetError(error, "profile_restore_failed");
  return data;
}

export async function listPersonalIpAssets(input: {
  token: string;
  source: IpAssetPersonalSource;
  cursor: string | null;
  signal?: AbortSignal;
}): Promise<components["schemas"]["IpAssetPersonalListResponse"]> {
  const { data, error } = await apiClient.GET(
    "/api/v1/ip-assets/profiles/me/assets",
    {
      params: {
        query: { source: input.source, cursor: input.cursor, limit: 16 },
        header: { "X-IP-Profile-Token": input.token },
      },
      ...(input.signal === undefined ? {} : { signal: input.signal }),
    },
  );
  if (data === undefined) throwIpAssetError(error, "personal_assets_failed");
  return data;
}

export async function setIpAssetFavorite(input: {
  token: string;
  assetRef: string;
  favorite: boolean;
}): Promise<components["schemas"]["IpAssetFavoriteResponse"]> {
  const params = {
    path: { asset_ref: input.assetRef },
    header: { "X-IP-Profile-Token": input.token },
  };
  const result = input.favorite
    ? await apiClient.PUT("/api/v1/ip-assets/{asset_ref}/favorite", { params })
    : await apiClient.DELETE("/api/v1/ip-assets/{asset_ref}/favorite", {
        params,
      });
  if (result.data === undefined)
    throwIpAssetError(result.error, "favorite_failed");
  return result.data;
}

export async function shareIpAsset(input: {
  token: string;
  assetRef: string;
}): Promise<components["schemas"]["IpAssetShareResponse"]> {
  const { data, error } = await apiClient.PUT(
    "/api/v1/ip-assets/{asset_ref}/shared",
    {
      params: {
        path: { asset_ref: input.assetRef },
        header: { "X-IP-Profile-Token": input.token },
      },
    },
  );
  if (data === undefined) throwIpAssetError(error, "share_failed");
  return data;
}

export async function getIpAssetLeaderboard(
  period: IpAssetLeaderboardPeriod,
  signal?: AbortSignal,
): Promise<IpAssetLeaderboard> {
  const { data, error } = await apiClient.GET("/api/v1/ip-assets/leaderboard", {
    params: { query: { period, limit: 10 } },
    ...(signal === undefined ? {} : { signal }),
  });
  if (data === undefined) throwIpAssetError(error, "leaderboard_failed");
  return data;
}

export async function fetchIpAssetBlob(
  path: string,
  profileToken?: string,
): Promise<Blob> {
  const resolved = ipAssetResourceUrl(path);
  if (resolved === null) throw new Error("asset_resource_invalid");
  const response = await fetch(
    resolved,
    profileToken === undefined
      ? {}
      : { headers: { "X-IP-Profile-Token": profileToken } },
  );
  if (!response.ok) throw new Error("asset_resource_failed");
  return response.blob();
}

export async function downloadIpAssetOriginal(input: {
  asset: IpAsset;
  profileToken?: string;
}): Promise<void> {
  const blob = await fetchIpAssetBlob(
    input.asset.download_url,
    input.profileToken,
  );
  triggerBlobDownload(
    blob,
    `${input.asset.canonical_name}.${extensionFor(input.asset.media_type)}`,
  );
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

function extensionFor(mediaType: IpAsset["media_type"]): string {
  return { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" }[
    mediaType
  ];
}

function throwIpAssetError(error: unknown, fallback: string): never {
  void error;
  throw new Error(fallback);
}
