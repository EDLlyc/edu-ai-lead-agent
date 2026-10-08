import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import styles from "@/app/Application.module.css";
import { AdminApp } from "@/features/admin/AdminApp";
import "@/styles/tokens.css";
import "@/styles/globals.css";

// Production entry of the 运营后台 alone (`npm run build:admin`): none of the internal
// development console pages are bundled, and the page only talks to /api/v1/admin.
const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Admin root element was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <div className={styles.standalonePage}>
      <main className={styles.standaloneMain}>
        <AdminApp />
      </main>
    </div>
  </StrictMode>,
);
