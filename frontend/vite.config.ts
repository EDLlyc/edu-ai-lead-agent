import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, normalize, resolve, sep } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

import { adminDocumentFallback } from "./src/config/adminDocumentFallback";

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

// The 运营后台 talks to the API through this origin, so its session cookie stays same-origin
// (SameSite=Strict, no credentialed CORS on the API).
const adminApiProxy = {
  "^/api/v1/admin(?:/|$)": {
    target: process.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
    changeOrigin: false,
  },
};

// `vite build --mode admin` builds the 运营后台 alone into dist-admin/ (page at /admin/, files at /assets/).
export default defineConfig(({ mode }) => ({
  ...(mode === "admin"
    ? {
        // Only the explicitly recognized admin documents have a fallback. In particular,
        // missing assets and unproxied API routes must retain their real 404 response.
        appType: "mpa" as const,
        base: "/",
        build: {
          outDir: "dist-admin",
          emptyOutDir: true,
          rollupOptions: {
            input: fileURLToPath(
              new URL("./admin/index.html", import.meta.url),
            ),
          },
        },
      }
    : {}),
  envDir: "..",
  plugins: [react(), servePreviewAssets(), adminDocumentFallback()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: adminApiProxy,
  },
  preview: {
    host: "127.0.0.1",
    proxy: adminApiProxy,
  },
  test: {
    environment: "jsdom",
    // e2e/ holds Playwright specs (`npm run test:e2e`), not unit tests.
    exclude: [...configDefaults.exclude, "e2e/**"],
    setupFiles: "./src/test/setup.ts",
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
    },
  },
}));
