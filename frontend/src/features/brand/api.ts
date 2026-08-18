import type { components } from "@/lib/api/generated/schema";
import { apiClient } from "@/lib/api/client";

export type BrandDocument = components["schemas"]["BrandDocumentResponse"];
export type BrandDocumentList =
  components["schemas"]["BrandDocumentListResponse"];
export type BrandContext = components["schemas"]["BrandContextResponse"];
export type DigitalIpProfile =
  components["schemas"]["DigitalIpProfileResponse"];
export type BrandUploadAccepted =
  components["schemas"]["BrandUploadAcceptedResponse"];
export type BrandDocumentKind = components["schemas"]["BrandDocumentKind"];

export type BrandUploadInput = Readonly<{
  file: File;
  title: string;
  documentKind: BrandDocumentKind;
  toneTags: string;
  safetyTags: string;
}>;

export async function listBrandDocuments(): Promise<BrandDocumentList> {
  const { data, error } = await apiClient.GET("/api/v1/brand-documents");
  if (data === undefined) {
    throw new Error(
      error === undefined ? "brand_list_failed" : "brand_api_error",
    );
  }
  return data;
}

export async function getDigitalIpProfile(): Promise<DigitalIpProfile> {
  const { data, error } = await apiClient.GET("/api/v1/digital-ip/profile");
  if (data === undefined) {
    throw new Error(
      error === undefined ? "digital_ip_profile_failed" : "brand_api_error",
    );
  }
  return data;
}

export async function uploadBrandDocument(
  input: BrandUploadInput,
): Promise<BrandUploadAccepted> {
  const body = {
    audience: "parents" as const,
    document_kind: input.documentKind,
    file: input.file.name,
    safety_tags: input.safetyTags,
    title: input.title,
    tone_tags: input.toneTags,
    visual_tags: "",
  };
  const { data, error } = await apiClient.POST("/api/v1/brand-documents", {
    body,
    bodySerializer: () => {
      const form = new FormData();
      form.set("file", input.file);
      form.set("title", input.title);
      form.set("document_kind", input.documentKind);
      form.set("audience", "parents");
      form.set("tone_tags", input.toneTags);
      form.set("safety_tags", input.safetyTags);
      form.set("visual_tags", "");
      return form;
    },
  });
  if (data === undefined) {
    throw new Error(
      error === undefined ? "brand_upload_failed" : "brand_api_error",
    );
  }
  return data;
}

export async function activateBrandVersion(
  documentId: string,
  versionId: string,
): Promise<BrandDocument> {
  const { data, error } = await apiClient.POST(
    "/api/v1/brand-documents/{document_id}/versions/{version_id}/activate",
    { params: { path: { document_id: documentId, version_id: versionId } } },
  );
  if (data === undefined) {
    throw new Error(
      error === undefined ? "brand_activate_failed" : "brand_api_error",
    );
  }
  return data;
}

export async function deactivateBrandDocument(
  documentId: string,
): Promise<BrandDocument> {
  const { data, error } = await apiClient.POST(
    "/api/v1/brand-documents/{document_id}/deactivate",
    { params: { path: { document_id: documentId } } },
  );
  if (data === undefined) {
    throw new Error(
      error === undefined ? "brand_deactivate_failed" : "brand_api_error",
    );
  }
  return data;
}

export async function retrieveBrandContext(
  query: string,
): Promise<BrandContext> {
  const { data, error } = await apiClient.POST(
    "/api/v1/brand-context/retrieve",
    {
      body: { audience: "parents", document_kinds: [], limit: 3, query },
    },
  );
  if (data === undefined) {
    throw new Error(
      error === undefined ? "brand_retrieval_failed" : "brand_api_error",
    );
  }
  return data;
}
