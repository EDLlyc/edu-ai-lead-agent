import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateBrandVersion,
  deactivateBrandDocument,
  getDigitalIpProfile,
  listBrandDocuments,
  retrieveBrandContext,
  uploadBrandDocument,
} from "./api";

export const brandKnowledgeKeys = {
  all: ["brand-knowledge"] as const,
  documents: () => [...brandKnowledgeKeys.all, "documents"] as const,
  profile: () => [...brandKnowledgeKeys.all, "digital-ip-profile"] as const,
} as const;

export function useDigitalIpProfile() {
  return useQuery({
    queryKey: brandKnowledgeKeys.profile(),
    queryFn: getDigitalIpProfile,
  });
}

export function useBrandDocuments() {
  return useQuery({
    queryKey: brandKnowledgeKeys.documents(),
    queryFn: listBrandDocuments,
    refetchInterval: (query) => {
      const documents = query.state.data?.items ?? [];
      const hasActiveJob = documents.some((document) =>
        document.versions.some((version) =>
          ["queued", "running", "retry_scheduled"].includes(
            version.ingestion_job_status ?? "",
          ),
        ),
      );
      return hasActiveJob ? 2_500 : false;
    },
  });
}

export function useUploadBrandDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadBrandDocument,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: brandKnowledgeKeys.all });
    },
  });
}

export function useActivateBrandVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      documentId,
      versionId,
    }: Readonly<{ documentId: string; versionId: string }>) =>
      activateBrandVersion(documentId, versionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: brandKnowledgeKeys.all });
    },
  });
}

export function useDeactivateBrandDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deactivateBrandDocument,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: brandKnowledgeKeys.all });
    },
  });
}

export function useRetrieveBrandContext() {
  return useMutation({ mutationFn: retrieveBrandContext });
}
