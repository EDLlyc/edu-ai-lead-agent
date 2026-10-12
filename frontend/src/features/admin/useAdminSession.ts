import { useCallback, useEffect, useRef, useState } from "react";

import { AdminSessionExpiredError, type AdminApi, type AdminMe } from "./api";
import { useUnsavedNavigation } from "./unsaved/context";

type Session =
  | { readonly kind: "checking" }
  | { readonly kind: "unreachable" }
  | {
      readonly kind: "anonymous";
      readonly notice: string | null;
      readonly status: "ready" | "rechecking" | "check-failed";
    }
  | {
      readonly kind: "signed-in";
      readonly me: AdminMe;
      readonly status:
        | "ready"
        | "rechecking"
        | "check-failed"
        | "logging-out"
        | "logout-failed";
    };

type AuthRequest = {
  readonly kind: "check" | "login" | "logout";
  readonly controller: AbortController;
};

/** One auth request owner; replacing it fences all obsolete success/error/finally paths. */
export function useAdminSession(api: AdminApi) {
  const [session, setSession] = useState<Session>({ kind: "checking" });
  const current = useRef<Session>(session);
  const request = useRef<AuthRequest | null>(null);
  const { clearAll } = useUnsavedNavigation();
  const transition = useCallback((next: Session) => {
    current.current = next;
    setSession(next);
  }, []);
  const invalidate = useCallback(() => {
    request.current?.controller.abort();
    request.current = null;
  }, []);
  const expire = useCallback(() => {
    invalidate();
    clearAll();
    transition({
      kind: "anonymous",
      notice: "登录已过期，请重新登录",
      status: "ready",
    });
  }, [clearAll, invalidate, transition]);

  const check = useCallback(() => {
    if (request.current !== null) return;
    const previous = current.current;
    const owner: AuthRequest = {
      kind: "check",
      controller: new AbortController(),
    };
    request.current = owner;
    // A login page may be restored after another tab signs in. Keep its form mounted
    // while checking so focus changes and network failures never erase entered fields.
    if (previous.kind === "signed-in" || previous.kind === "anonymous")
      transition({ ...previous, status: "rechecking" });
    else transition({ kind: "checking" });
    void api.me(owner.controller.signal).then(
      (me) => {
        if (request.current !== owner) return;
        request.current = null;
        if (me === null) {
          clearAll();
          transition({
            kind: "anonymous",
            notice:
              previous.kind === "signed-in"
                ? "登录已过期，请重新登录"
                : previous.kind === "anonymous"
                  ? previous.notice
                  : null,
            status: "ready",
          });
        } else {
          if (
            previous.kind === "signed-in" &&
            (previous.me.username !== me.username ||
              previous.me.role !== me.role)
          )
            clearAll();
          transition({ kind: "signed-in", me, status: "ready" });
        }
      },
      (error: unknown) => {
        if (request.current !== owner) return;
        request.current = null;
        if (error instanceof AdminSessionExpiredError) expire();
        else
          transition(
            previous.kind === "signed-in" || previous.kind === "anonymous"
              ? { ...previous, status: "check-failed" }
              : { kind: "unreachable" },
          );
      },
    );
  }, [api, clearAll, expire, transition]);

  useEffect(() => {
    // API replacement and StrictMode cleanup each invalidate their previous request owner.
    current.current = { kind: "checking" };
    check();
    const onReturn = () => {
      if (document.visibilityState !== "hidden") check();
    };
    const onSuspend = () => {
      // A pre-departure read cannot establish the session at the next restoration.
      // Never cancel a sign-in/out mutation merely because the tab loses visibility.
      if (request.current?.kind === "check") invalidate();
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") onSuspend();
      else onReturn();
    };
    window.addEventListener("focus", onReturn);
    window.addEventListener("pageshow", onReturn);
    window.addEventListener("pagehide", onSuspend);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      invalidate();
      window.removeEventListener("focus", onReturn);
      window.removeEventListener("pageshow", onReturn);
      window.removeEventListener("pagehide", onSuspend);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [check, invalidate]);

  const login = useCallback(
    async (username: string, password: string) => {
      invalidate();
      const owner: AuthRequest = {
        kind: "login",
        controller: new AbortController(),
      };
      request.current = owner;
      try {
        const me = await api.login(username, password);
        if (request.current !== owner) return;
        clearAll();
        transition({ kind: "signed-in", me, status: "ready" });
      } finally {
        if (request.current === owner) request.current = null;
      }
    },
    [api, clearAll, invalidate, transition],
  );

  const logout = useCallback(async () => {
    const previous = current.current;
    if (previous.kind !== "signed-in" || previous.status === "logging-out")
      return;
    invalidate();
    const owner: AuthRequest = {
      kind: "logout",
      controller: new AbortController(),
    };
    request.current = owner;
    transition({ ...previous, status: "logging-out" });
    try {
      await api.logout();
      if (request.current !== owner) return;
      clearAll();
      transition({ kind: "anonymous", notice: "已退出", status: "ready" });
    } catch {
      if (request.current !== owner) return;
      transition({ ...previous, status: "logout-failed" });
    } finally {
      if (request.current === owner) request.current = null;
    }
  }, [api, clearAll, invalidate, transition]);

  return { session, check, login, logout, expire };
}
