import styles from "./Admin.module.css";
import { companionEntryUrl } from "./companionNavigation";
import { useUnsavedNavigation } from "./unsaved/context";

export function ExhibitEntryLink() {
  const href = companionEntryUrl(
    import.meta.env.VITE_EXHIBIT_ENTRY_URL,
    window.location.href,
  );
  const { requestNavigation } = useUnsavedNavigation();
  if (href === null) return null;
  return (
    <a
      className={styles.companionLink}
      href={href}
      onClick={(event) => {
        // New tabs/windows leave this document and its in-memory edits intact.
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        event.preventDefault();
        requestNavigation(() => window.location.assign(href));
      }}
    >
      返回展厅
    </a>
  );
}
