import { createServer, type Server } from "node:http";
import { readFileSync, writeFileSync } from "node:fs";
import { extname, relative, resolve } from "node:path";

import { expect, test } from "@playwright/test";

const fixtureDirectory = process.env.EDITOR_HANDOFF_FIXTURE_DIR;
const browserReportPath = process.env.EDITOR_HANDOFF_BROWSER_REPORT;

test.skip(
  fixtureDirectory === undefined,
  "Set EDITOR_HANDOFF_FIXTURE_DIR to a verified local handoff artifact.",
);

test("editor handoff fixture is copy-exact, image-complete and mobile-safe", async ({
  page,
}) => {
  const root = resolve(fixtureDirectory!);
  const bodyHtml = readFileSync(resolve(root, "article-body.html"), "utf8");
  const manifest = JSON.parse(
    readFileSync(resolve(root, "manifest.json"), "utf8"),
  ) as {
    fingerprint: string;
    media: readonly Readonly<{ role: "body" | "context" | "cover" }>[];
  };
  const expectedInlineImages = manifest.media.filter(
    (item) => item.role !== "cover",
  ).length;
  const server = await startFixtureServer(root);
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("fixture server did not bind an IP port");
  }
  const origin = `http://127.0.0.1:${address.port}`;
  const externalRequests: string[] = [];
  const observations: Array<{
    viewport: number;
    imageCount: number;
    documentScrollWidth: number;
    documentClientWidth: number;
  }> = [];

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {
      externalRequests.push(url.href);
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });

  try {
    for (const viewport of [320, 430] as const) {
      await page.setViewportSize({ width: viewport, height: 900 });
      await page.goto(`${origin}/preview.html`, { waitUntil: "networkidle" });

      const images = page.locator("#copy-root img");
      await expect(images).toHaveCount(expectedInlineImages);
      expect(
        await images.evaluateAll((nodes) =>
          nodes.every(
            (node) =>
              node instanceof HTMLImageElement &&
              node.complete &&
              node.naturalWidth > 0 &&
              node.naturalHeight > 0,
          ),
        ),
      ).toBe(true);

      const copyBody = await page.locator("#copy-root").innerHTML();
      const canonicalBody = await page.evaluate(
        (value) =>
          new DOMParser().parseFromString(value, "text/html").body.innerHTML,
        bodyHtml,
      );
      expect(copyBody).toBe(canonicalBody);

      const dimensions = await page.evaluate(() => ({
        documentScrollWidth: document.documentElement.scrollWidth,
        documentClientWidth: document.documentElement.clientWidth,
      }));
      expect(dimensions.documentScrollWidth).toBeLessThanOrEqual(
        dimensions.documentClientWidth,
      );
      observations.push({
        viewport,
        imageCount: await images.count(),
        ...dimensions,
      });
    }
  } finally {
    server.closeAllConnections();
    await new Promise<void>((done, reject) =>
      server.close((error) => (error === undefined ? done() : reject(error))),
    );
  }

  expect(externalRequests).toEqual([]);
  if (browserReportPath !== undefined) {
    writeFileSync(
      browserReportPath,
      `${JSON.stringify(
        {
          status: "passed",
          fixture_fingerprint: manifest.fingerprint,
          viewports: observations,
          external_requests: 0,
          copy_root_matches_body: true,
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
  }
});

async function startFixtureServer(root: string): Promise<Server> {
  const contentTypes: Readonly<Record<string, string>> = {
    ".html": "text/html; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
  };
  const server = createServer((request, response) => {
    try {
      const pathname = decodeURIComponent(
        new URL(request.url ?? "/", "http://127.0.0.1").pathname,
      );
      const candidate = resolve(root, `.${pathname}`);
      const safeRelative = relative(root, candidate);
      if (safeRelative.startsWith("..") || safeRelative === "") {
        response.writeHead(404).end();
        return;
      }
      const body = readFileSync(candidate);
      response.writeHead(200, {
        "Cache-Control": "no-store",
        Connection: "close",
        "Content-Type":
          contentTypes[extname(candidate)] ?? "application/octet-stream",
        "X-Content-Type-Options": "nosniff",
      });
      response.end(body);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise<void>((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  return server;
}
