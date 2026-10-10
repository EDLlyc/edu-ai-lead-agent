import {
  createContext,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
} from "react";

type UnsavedNavigation = {
  readonly register: (id: string, discard: () => void) => () => void;
  readonly isDirty: () => boolean;
  readonly requestNavigation: (action: () => void) => void;
  readonly requestDiscardFor: (id: string, action: () => void) => void;
  readonly clearAll: () => void;
};

// Isolated pages can still render without a shell (tests and embedded previews).
export const UnsavedContext = createContext<UnsavedNavigation>({
  register: () => () => undefined,
  isDirty: () => false,
  requestNavigation: (action) => action(),
  requestDiscardFor: (_id, action) => action(),
  clearAll: () => undefined,
});

export function useUnsavedNavigation() {
  return useContext(UnsavedContext);
}

/** Register only actual edits; values and secrets remain owned by the form. */
export function useUnsavedChanges(dirty: boolean, onDiscard: () => void) {
  const id = useId();
  const { register, requestDiscardFor } = useUnsavedNavigation();
  useLayoutEffect(() => {
    if (dirty) return register(id, onDiscard);
  }, [dirty, id, onDiscard, register]);
  const requestDiscard = useCallback(
    (action: () => void) => requestDiscardFor(id, action),
    [id, requestDiscardFor],
  );
  return { requestDiscard };
}
