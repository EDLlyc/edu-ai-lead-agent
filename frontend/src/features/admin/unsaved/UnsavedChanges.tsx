import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import styles from "../Admin.module.css";
import { UnsavedContext } from "./context";

export function UnsavedChangesProvider({
  children,
}: {
  readonly children: ReactNode;
}) {
  const edits = useRef(new Map<string, () => void>());
  const pending = useRef<{ action: () => void; id: string | null } | null>(
    null,
  );
  const [showPrompt, setShowPrompt] = useState(false);
  const content = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  const discard = useRef<HTMLButtonElement>(null);

  const beforeUnload = useCallback((event: BeforeUnloadEvent) => {
    if (edits.current.size === 0) return;
    event.preventDefault();
    event.returnValue = "";
  }, []);
  const register = useCallback(
    (id: string, reset: () => void) => {
      edits.current.set(id, reset);
      window.addEventListener("beforeunload", beforeUnload);
      return () => {
        edits.current.delete(id);
        if (edits.current.size === 0)
          window.removeEventListener("beforeunload", beforeUnload);
      };
    },
    [beforeUnload],
  );
  const clearAll = useCallback(() => {
    edits.current.clear();
    window.removeEventListener("beforeunload", beforeUnload);
    pending.current = null;
    setShowPrompt(false);
  }, [beforeUnload]);
  const isDirty = useCallback(() => edits.current.size > 0, []);
  const requestNavigation = useCallback((action: () => void) => {
    if (pending.current !== null) return;
    if (edits.current.size === 0) {
      action();
      return;
    }
    pending.current = { action, id: null };
    setShowPrompt(true);
  }, []);
  const requestDiscardFor = useCallback((id: string, action: () => void) => {
    if (pending.current !== null) return;
    if (!edits.current.has(id)) {
      action();
      return;
    }
    pending.current = { action, id };
    setShowPrompt(true);
  }, []);
  const stay = useCallback(() => {
    pending.current = null;
    setShowPrompt(false);
  }, []);

  useLayoutEffect(
    () => () => window.removeEventListener("beforeunload", beforeUnload),
    [beforeUnload],
  );
  useLayoutEffect(() => {
    if (!showPrompt) return;
    const previous = document.activeElement;
    const background = content.current;
    if (background !== null) background.inert = true;
    keep.current?.focus();
    return () => {
      if (background !== null) background.inert = false;
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, [showPrompt]);

  const value = useMemo(
    () => ({
      register,
      isDirty,
      requestNavigation,
      requestDiscardFor,
      clearAll,
    }),
    [register, isDirty, requestNavigation, requestDiscardFor, clearAll],
  );
  return (
    <UnsavedContext value={value}>
      <div ref={content}>{children}</div>
      {!showPrompt ? null : (
        <div className={styles.unsavedOverlay}>
          <div
            ref={dialog}
            className={styles.unsavedDialog}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="unsaved-title"
            aria-describedby="unsaved-description"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                stay();
              }
              if (event.key === "Tab") {
                event.preventDefault();
                (document.activeElement === keep.current
                  ? discard.current
                  : keep.current
                )?.focus();
              }
            }}
          >
            <h2 id="unsaved-title">有未保存的修改</h2>
            <p id="unsaved-description">
              离开会丢弃尚未保存的内容。你也可以继续编辑并保存。
            </p>
            <div className={styles.actions}>
              <button
                ref={keep}
                type="button"
                className={styles.primary}
                onClick={stay}
              >
                继续编辑
              </button>
              <button
                ref={discard}
                type="button"
                onClick={() => {
                  const navigation = pending.current;
                  if (navigation === null) return;
                  const ids =
                    navigation.id === null
                      ? [...edits.current.keys()]
                      : [navigation.id];
                  const resets = ids.flatMap((id) => {
                    const reset = edits.current.get(id);
                    edits.current.delete(id);
                    return reset === undefined ? [] : [reset];
                  });
                  if (edits.current.size === 0)
                    window.removeEventListener("beforeunload", beforeUnload);
                  pending.current = null;
                  setShowPrompt(false);
                  for (const reset of resets) reset();
                  navigation.action();
                }}
              >
                放弃修改并继续
              </button>
            </div>
          </div>
        </div>
      )}
    </UnsavedContext>
  );
}
