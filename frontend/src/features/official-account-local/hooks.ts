import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createFixtureArticleRun,
  createLiveArticleRun,
  getOfficialAccountCapabilities,
  getOfficialAccountRun,
  listOfficialAccountRuns,
  retryOfficialAccountRun,
  submitOfficialAccountManualReview,
  type OfficialAccountRunSummaryViewModel,
  type OfficialAccountStatus,
} from "./api";

export const officialAccountLocalKeys = {
  all: ["official-account-local"] as const,
  capabilities: () =>
    [...officialAccountLocalKeys.all, "capabilities"] as const,
  list: () => [...officialAccountLocalKeys.all, "list"] as const,
  detail: (id: string) =>
    [...officialAccountLocalKeys.all, "detail", id] as const,
} as const;

export function useOfficialAccountCapabilities() {
  return useQuery({
    queryKey: officialAccountLocalKeys.capabilities(),
    queryFn: ({ signal }) => getOfficialAccountCapabilities(signal),
  });
}

export function useOfficialAccountRuns() {
  return useQuery({
    queryKey: officialAccountLocalKeys.list(),
    queryFn: ({ signal }) => listOfficialAccountRuns(signal),
    refetchInterval: (query) =>
      query.state.data?.some((run) =>
        shouldPollOfficialAccountRun(run.status),
      ) === true
        ? 2_500
        : false,
  });
}

export function useOfficialAccountRun(runId: string | null) {
  return useQuery({
    queryKey: officialAccountLocalKeys.detail(runId ?? ""),
    queryFn: ({ signal }) => getOfficialAccountRun(runId ?? "", signal),
    enabled: runId !== null && runId.length > 0,
    refetchInterval: (query) =>
      shouldPollOfficialAccountRun(query.state.data?.summary.status)
        ? 2_500
        : false,
  });
}

export function useCreateFixtureArticleRun() {
  return useRunMutation(createFixtureArticleRun);
}

export function useCreateLiveArticleRun() {
  return useRunMutation(createLiveArticleRun);
}

export function useRetryOfficialAccountRun() {
  return useRunMutation(retryOfficialAccountRun);
}

export function useOfficialAccountManualReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: submitOfficialAccountManualReview,
    onSuccess: async (_review, input) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: officialAccountLocalKeys.list() }),
        client.invalidateQueries({
          queryKey: officialAccountLocalKeys.detail(input.runId),
        }),
      ]);
    },
  });
}

export function shouldPollOfficialAccountRun(
  status: OfficialAccountStatus | undefined,
): boolean {
  return status === "queued" || status === "running";
}

function useRunMutation<TInput>(
  mutationFn: (input: TInput) => Promise<OfficialAccountRunSummaryViewModel>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () =>
      client.invalidateQueries({ queryKey: officialAccountLocalKeys.all }),
  });
}
