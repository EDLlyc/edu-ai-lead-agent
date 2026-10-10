import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminSessionExpiredError } from "../api";
import type { PublishJob, WeChatApi } from "./api";

export type PublicationTab = "drafts" | "jobs" | "published";
export const PUBLICATION_PAGE_SIZE = 20;

type PageData =
  | {
      readonly tab: "drafts";
      readonly page: Awaited<ReturnType<WeChatApi["drafts"]>>;
    }
  | {
      readonly tab: "published";
      readonly page: Awaited<ReturnType<WeChatApi["published"]>>;
    }
  | { readonly tab: "jobs"; readonly page: null };

type Snapshot = {
  readonly requestContext: {
    readonly api: WeChatApi;
    readonly key: string;
  };
  readonly revision: number;
  readonly data: PageData | null;
  readonly jobs: readonly PublishJob[] | null;
  readonly error: string | null;
};

/** Keep a response and its actions bound to the account, view and page that requested it. */
export function usePublicationPage({
  api,
  accountId,
  tab,
  onSessionExpired,
}: {
  readonly api: WeChatApi;
  readonly accountId: string | null;
  readonly tab: PublicationTab;
  readonly onSessionExpired: () => void;
}) {
  const context = `${accountId ?? ""}/${tab}`;
  const [cursor, setCursor] = useState({ context, offset: 0 });
  const offset = cursor.context === context ? cursor.offset : 0;
  const [revision, setRevision] = useState(0);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const key = `${context}/${offset}`;
  // A -> B -> A is a new visit even if B has not returned a response yet.
  // Same-context refreshes retain this identity but change revision, so their
  // content can remain visible while actions wait for the new response.
  const requestContext = useMemo(() => ({ api, key }), [api, key]);

  useEffect(() => {
    if (accountId === null) return;
    let cancelled = false;
    const load = async (): Promise<PageData> => {
      if (tab === "drafts") {
        return { tab, page: await api.drafts(accountId, offset) };
      }
      if (tab === "published") {
        return { tab, page: await api.published(accountId, offset) };
      }
      return { tab, page: null };
    };
    void Promise.all([load(), api.jobs(accountId)]).then(
      ([data, jobs]) => {
        if (cancelled) return;
        if (data.page !== null && offset > 0 && offset >= data.page.total) {
          // A deletion can remove the last page between requests. Load the new last page.
          setSnapshot(null);
          setCursor({
            context,
            offset:
              Math.max(
                0,
                Math.ceil(data.page.total / PUBLICATION_PAGE_SIZE) - 1,
              ) * PUBLICATION_PAGE_SIZE,
          });
          return;
        }
        setSnapshot({ requestContext, revision, data, jobs, error: null });
      },
      (error: unknown) => {
        if (cancelled) return;
        if (error instanceof AdminSessionExpiredError) {
          onSessionExpired();
          return;
        }
        setSnapshot((previous) => ({
          requestContext,
          revision,
          data:
            previous?.requestContext === requestContext ? previous.data : null,
          jobs:
            previous?.requestContext === requestContext ? previous.jobs : null,
          error: error instanceof Error ? error.message : "读取失败，请重试",
        }));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [
    accountId,
    api,
    context,
    offset,
    onSessionExpired,
    requestContext,
    revision,
    tab,
  ]);

  const current = snapshot?.requestContext === requestContext ? snapshot : null;
  const loading = accountId === null || current?.revision !== revision;
  const error = loading ? null : (current?.error ?? null);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  return {
    offset,
    data: current?.data ?? null,
    jobs: current?.jobs ?? null,
    loading,
    error,
    ready:
      !loading && error === null && current !== null && current.data !== null,
    changePage: (nextOffset: number) => {
      setCursor({ context, offset: Math.max(0, nextOffset) });
    },
    refresh,
  };
}
