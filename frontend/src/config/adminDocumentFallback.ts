import type { IncomingMessage, ServerResponse } from "node:http";

import type { Plugin } from "vite";

import { sectionFromPath } from "../features/admin/sections";

function adminDocument(
  request: IncomingMessage,
  _response: ServerResponse,
  next: () => void,
): void {
  const url = request.url ?? "/";
  const queryStart = url.indexOf("?");
  const pathname = queryStart < 0 ? url : url.slice(0, queryStart);
  const query = queryStart < 0 ? "" : url.slice(queryStart);
  const accept = request.headers.accept;
  if (
    (request.method === "GET" || request.method === "HEAD") &&
    (accept === undefined ||
      accept.includes("text/html") ||
      accept.includes("*/*")) &&
    (pathname === "/admin" ||
      pathname === "/admin/" ||
      sectionFromPath(pathname) !== null)
  ) {
    request.url = `/admin/index.html${query}`;
  }
  next();
}

/** Runs before Vite's HTML/static middleware, in both development and built preview. */
export function adminDocumentFallback(): Plugin {
  return {
    name: "admin-document-fallback",
    configureServer(server) {
      server.middlewares.use(adminDocument);
    },
    configurePreviewServer(server) {
      server.middlewares.use(adminDocument);
    },
  };
}
