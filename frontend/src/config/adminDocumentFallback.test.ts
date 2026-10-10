// @vitest-environment node
import { createServer as createHttpServer, type Server } from "node:http";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import type { Server as TcpServer } from "node:net";
import { fileURLToPath } from "node:url";

import { createServer, preview } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { ADMIN_SECTIONS } from "../features/admin/sections";

const configFile = fileURLToPath(
  new URL("../../vite.config.ts", import.meta.url),
);
const html = "<!doctype html><html><body>admin-entry-fixture</body></html>";

function address(server: TcpServer): string {
  const value = server.address();
  if (value === null || typeof value === "string")
    throw new Error("no TCP listener");
  return `http://127.0.0.1:${value.port}`;
}

async function close(server: TcpServer): Promise<void> {
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
}

describe.each(["dev", "preview"] as const)(
  "admin %s document routing",
  (kind) => {
    let root: string;
    let url: string;
    let dispose: () => Promise<void>;
    let upstream: Server;
    const proxied: string[] = [];

    beforeAll(async () => {
      root = await mkdtemp(resolve(tmpdir(), "admin-routing-"));
      const contentRoot = kind === "dev" ? root : resolve(root, "dist-admin");
      await mkdir(resolve(contentRoot, "admin"), { recursive: true });
      await mkdir(resolve(contentRoot, "assets"), { recursive: true });
      await writeFile(resolve(contentRoot, "admin/index.html"), html);
      await writeFile(
        resolve(contentRoot, "assets/test.css"),
        ":root{color:red}",
      );
      upstream = createHttpServer((request, response) => {
        proxied.push(request.url ?? "");
        response.writeHead(401, { "Content-Type": "application/json" });
        response.end('{"error":"unauthorized-fixture"}');
      });
      await new Promise<void>((resolveListening) =>
        upstream.listen(0, "127.0.0.1", resolveListening),
      );
      const proxy = {
        // The key must match the real config so merging does not introduce a broader route.
        "^/api/v1/admin(?:/|$)": {
          target: address(upstream),
          changeOrigin: false,
        },
      };
      const config = {
        configFile,
        root,
        envDir: root,
        mode: "admin",
        logLevel: "silent" as const,
      };
      if (kind === "dev") {
        const server = await createServer({
          ...config,
          optimizeDeps: { noDiscovery: true, include: [] },
          server: {
            port: 0,
            host: "127.0.0.1",
            hmr: false,
            watch: null,
            proxy,
          },
        });
        await server.listen();
        if (server.httpServer === null) throw new Error("no dev server");
        url = address(server.httpServer);
        dispose = () => server.close();
      } else {
        const server = await preview({
          ...config,
          preview: { port: 0, host: "127.0.0.1", proxy },
        });
        url = address(server.httpServer);
        dispose = () => close(server.httpServer);
      }
    }, 20_000);

    afterAll(async () => {
      await dispose?.();
      if (upstream !== undefined) await close(upstream);
      if (root !== undefined) await rm(root, { recursive: true, force: true });
    });

    it("serves hard navigation and reloads for every real section", async () => {
      for (const path of [
        "/admin",
        "/admin/",
        ...ADMIN_SECTIONS.map(({ key }) => `/admin/${key}`),
      ]) {
        for (let reload = 0; reload < 2; reload += 1) {
          const response = await fetch(`${url}${path}?view=test`, {
            headers: { Accept: "text/html" },
          });
          expect(response.status, path).toBe(200);
          expect(response.headers.get("Content-Type")).toContain("text/html");
          expect(await response.text()).toContain("admin-entry-fixture");
        }
      }
      const head = await fetch(`${url}/admin/sources/`, {
        method: "HEAD",
        headers: { Accept: "text/html" },
      });
      expect(head.status).toBe(200);
      expect(await head.text()).toBe("");
    });

    it("preserves asset serving and missing asset/API 404s", async () => {
      const css = await fetch(`${url}/assets/test.css`, {
        headers: { Accept: "text/css" },
      });
      expect(css.status).toBe(200);
      expect(await css.text()).toBe(":root{color:red}");
      for (const path of [
        "/assets/missing.js",
        "/admin/missing.js",
        "/admin/assets/missing.css",
        "/admin/missing-route",
        "/api/v1/private",
        "/api/v1/admin-extra",
        "/elsewhere",
      ]) {
        const response = await fetch(`${url}${path}`, {
          headers: { Accept: "text/html" },
        });
        expect(response.status, path).toBe(404);
        expect(await response.text()).not.toContain("admin-entry-fixture");
      }
      const json = await fetch(`${url}/admin/sources`, {
        headers: { Accept: "application/json" },
      });
      expect(json.status).toBe(404);
      const post = await fetch(`${url}/admin/sources`, {
        method: "POST",
        headers: { Accept: "text/html" },
      });
      expect(post.status).toBe(404);
    });

    it("proxies only the admin API and keeps its non-HTML response", async () => {
      const response = await fetch(`${url}/api/v1/admin/auth/me`);
      expect(response.status).toBe(401);
      expect(response.headers.get("Content-Type")).toBe("application/json");
      expect(await response.json()).toEqual({ error: "unauthorized-fixture" });
      expect(proxied).toEqual(["/api/v1/admin/auth/me"]);
    });
  },
);
