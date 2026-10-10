import { useCallback, useEffect, useRef, useState } from "react";

import { useUnsavedNavigation } from "./context";

const POSITION = "eduAdminPosition";

function position(state: unknown): number | null {
  if (typeof state !== "object" || state === null || !(POSITION in state))
    return null;
  const value: unknown = state[POSITION];
  return typeof value === "number" && Number.isSafeInteger(value)
    ? value
    : null;
}

/** Track existing entries, restoring a blocked traversal with go(), never pushState(). */
export function useAdminHistory() {
  const [path, setPath] = useState(() => window.location.pathname);
  const current = useRef({
    index: position(window.history.state) ?? 0,
    path: window.location.pathname,
  });
  const restoring = useRef<null | { index: number; path: string }>(null);
  const approved = useRef<number | null>(null);
  const { isDirty, requestNavigation } = useUnsavedNavigation();

  useEffect(() => {
    if (position(window.history.state) === null) {
      window.history.replaceState(
        { [POSITION]: current.current.index },
        "",
        window.location.href,
      );
    }
    const onPopState = (event: PopStateEvent) => {
      // Entries made by the admin shell carry an index. Cross-document exits are
      // protected by the browser's beforeunload prompt instead.
      const index = position(event.state);
      if (index === null) {
        setPath(window.location.pathname);
        return;
      }
      if (restoring.current !== null && index === current.current.index) {
        const target = restoring.current;
        restoring.current = null;
        requestNavigation(() => {
          approved.current = target.index;
          window.history.go(target.index - current.current.index);
        });
        return;
      }
      if (approved.current === index || !isDirty()) {
        approved.current = null;
        current.current = { index, path: window.location.pathname };
        setPath(window.location.pathname);
        return;
      }
      if (index === current.current.index) return;
      if (restoring.current === null)
        restoring.current = { index, path: window.location.pathname };
      window.history.go(current.current.index - index);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [isDirty, requestNavigation]);

  const navigate = useCallback(
    (next: string) => {
      if (next === current.current.path) return;
      requestNavigation(() => {
        const index = current.current.index + 1;
        window.history.pushState({ [POSITION]: index }, "", next);
        current.current = { index, path: next };
        setPath(next);
      });
    },
    [requestNavigation],
  );
  return { path, navigate };
}
