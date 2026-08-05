import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, normalize, resolve, sep } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const previewRoot = fileURLToPath(
  new URL("../output/preview", import.meta.url),
);

function servePreviewAssets() {
  const contentTypes: Readonly<Record<string, string>> = {
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
  };

  function middleware(
    req: IncomingMessage,
    res: ServerResponse,
    next: () => void,
  ) {
    let requestPath: string;
    try {
      requestPath = decodeURIComponent(
        (req.url ?? "/").split("?", 1)[0] ?? "/",
      );
    } catch {
      next();
      return;
    }
    const root = resolve(previewRoot);
    const candidate = resolve(root, `.${normalize(requestPath)}`);
    if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
      next();
      return;
    }
    if (!existsSync(candidate) || !statSync(candidate).isFile()) {
      next();
      return;
    }
    res.statusCode = 200;
    res.setHeader(
      "Content-Type",
      contentTypes[extname(candidate).toLowerCase()] ??
        "application/octet-stream",
    );
    res.setHeader("Cache-Control", "no-store");
    createReadStream(candidate).pipe(res);
  }

  return {
    name: "serve-local-preview-assets",
    configureServer(server: {
      middlewares: { use: (path: string, handler: typeof middleware) => void };
    }) {
      server.middlewares.use("/preview", middleware);
    },
    configurePreviewServer(server: {
      middlewares: { use: (path: string, handler: typeof middleware) => void };
    }) {
      server.middlewares.use("/preview", middleware);
    },
  };
}

export default defineConfig({
  envDir: "..",
  plugins: [react(), servePreviewAssets()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
    },
  },
});
