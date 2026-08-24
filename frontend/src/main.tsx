import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Application } from "@/app/Application";
import { AppProviders } from "@/app/providers";
import "@/styles/tokens.css";
import "@/styles/globals.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Application root element was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <Application />
    </AppProviders>
  </StrictMode>,
);
