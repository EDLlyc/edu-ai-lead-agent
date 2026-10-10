import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import styles from "./Admin.module.css";
import type { AdminSection } from "./sections";

// Keep this breakpoint aligned with the shell's mobile layout in Admin.module.css.
const MOBILE_MENU_QUERY = "(max-width: 720px)";
function subscribeMobileMenu(onChange: () => void) {
  const query = window.matchMedia?.(MOBILE_MENU_QUERY);
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}
function isMobileMenu() {
  return window.matchMedia?.(MOBILE_MENU_QUERY).matches ?? false;
}

export function AdminNavigation({
  sections,
  current,
  path,
  navigate,
}: {
  readonly sections: readonly AdminSection[];
  readonly current: AdminSection | undefined;
  readonly path: string;
  readonly navigate: (path: string) => void;
}) {
  const mobile = useSyncExternalStore(
    subscribeMobileMenu,
    isMobileMenu,
    () => false,
  );
  const [disclosure, setDisclosure] = useState({ path, expanded: false });
  // Reset during the route render, never before the unsaved-navigation guard accepts it.
  // Remembering only an open path would reopen an old menu on browser Back.
  if (disclosure.path !== path) setDisclosure({ path, expanded: false });
  const expanded = disclosure.path === path && disclosure.expanded;
  const toggle = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLElement>(null);
  const wasExpanded = useRef(false);
  const menuId = useId();

  useLayoutEffect(() => {
    const active = document.activeElement;
    if (
      mobile &&
      !expanded &&
      (wasExpanded.current || menu.current?.contains(active))
    ) {
      toggle.current?.focus();
    } else if (!mobile && active === toggle.current) {
      menu.current
        ?.querySelector<HTMLAnchorElement>('[aria-current="page"]')
        ?.focus();
    }
    wasExpanded.current = expanded;
  }, [mobile, expanded]);

  return (
    <div
      className={styles.navigation}
      onKeyDown={(event) => {
        if (event.key === "Escape" && mobile && expanded) {
          event.preventDefault();
          setDisclosure({ path, expanded: false });
          toggle.current?.focus();
        }
      }}
    >
      <button
        ref={toggle}
        className={styles.menuToggle}
        type="button"
        hidden={!mobile}
        aria-expanded={expanded}
        aria-controls={menuId}
        onClick={() => setDisclosure({ path, expanded: !expanded })}
      >
        <span className={styles.menuCurrent}>
          <span>{current?.group ?? "运营后台"}</span>
          <strong>{current?.title ?? "后台菜单"}</strong>
        </span>
        <span className={styles.menuToggleAction}>
          {expanded ? "收起菜单" : "切换页面"}
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            aria-hidden="true"
            data-expanded={expanded}
          >
            <path
              d="m4 6 4 4 4-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
        </span>
      </button>
      <nav
        ref={menu}
        id={menuId}
        className={styles.menu}
        aria-label="后台菜单"
        hidden={mobile && !expanded}
      >
        {groupSections(sections).map(([group, items]) => (
          <div className={styles.menuGroup} key={group}>
            <p>{group}</p>
            <ul>
              {items.map((section) => (
                <li key={section.key}>
                  <a
                    href={`/admin/${section.key}`}
                    aria-current={
                      section.key === current?.key ? "page" : undefined
                    }
                    onClick={(event) => {
                      if (
                        event.metaKey ||
                        event.ctrlKey ||
                        event.shiftKey ||
                        event.altKey ||
                        event.button !== 0
                      )
                        return;
                      event.preventDefault();
                      const destination = `/admin/${section.key}`;
                      if (destination === path)
                        setDisclosure({ path, expanded: false });
                      navigate(destination);
                    }}
                  >
                    {section.title}
                    {section.plan === null ? null : <small>待上线</small>}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );
}

function groupSections(
  sections: readonly AdminSection[],
): readonly (readonly [string, readonly AdminSection[]])[] {
  const groups = new Map<string, AdminSection[]>();
  for (const section of sections) {
    const items = groups.get(section.group) ?? [];
    items.push(section);
    groups.set(section.group, items);
  }
  return [...groups.entries()];
}
