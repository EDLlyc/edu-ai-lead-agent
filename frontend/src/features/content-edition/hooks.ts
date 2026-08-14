import { useQuery } from "@tanstack/react-query";

import { getContentEdition, type ContentEditionViewModel } from "./api";

export const contentEditionKeys = {
  all: ["content-editions"] as const,
  date: (businessDate: string, profile: string) =>
    [...contentEditionKeys.all, businessDate, profile] as const,
};

export function useContentEdition(businessDate: string, profile = "preview") {
  return useQuery({
    queryKey: contentEditionKeys.date(businessDate, profile),
    queryFn: ({ signal }) => getContentEdition(businessDate, profile, signal),
    refetchInterval: (query) =>
      shouldPollContentEdition(query.state.data) ? 5_000 : false,
  });
}

export function shouldPollContentEdition(
  edition: ContentEditionViewModel | undefined,
): boolean {
  return (
    edition?.slotModeEnabled === true &&
    edition.slots.some(
      (slot) => slot.enabled && ["missing", "preparing"].includes(slot.state),
    )
  );
}
