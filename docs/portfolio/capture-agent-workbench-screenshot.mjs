import { mkdtemp, mkdir, readFile, readdir, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repositoryRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const frontendRoot = resolve(repositoryRoot, "frontend");
const requireFromFrontend = createRequire(
  resolve(frontendRoot, "package.json"),
);
const { chromium } = requireFromFrontend("@playwright/test");
const { build } = await import(
  pathToFileURL(requireFromFrontend.resolve("vite")).href
);

const screenshotEntry = resolve(
  frontendRoot,
  "src/features/agent-workbench/screenshot.html",
);
const screenshotTarget = resolve(
  repositoryRoot,
  "docs/portfolio/assets/agent-workbench-trace.png",
);
const temporaryOutput = await mkdtemp(
  join(tmpdir(), "agent-workbench-screenshot-"),
);

try {
  await build({
    configFile: resolve(frontendRoot, "vite.config.ts"),
    root: frontendRoot,
    base: "./",
    logLevel: "warn",
    build: {
      outDir: temporaryOutput,
      emptyOutDir: true,
      rollupOptions: { input: screenshotEntry },
    },
  });

  const outputFiles = await readdir(temporaryOutput, {
    recursive: true,
    withFileTypes: true,
  });
  const outputHtml = outputFiles.find(
    (entry) => entry.isFile() && entry.name === "screenshot.html",
  );
  if (outputHtml === undefined) {
    throw new Error("built screenshot entry was not found");
  }

  const htmlPath = resolve(outputHtml.parentPath, outputHtml.name);
  await mkdir(dirname(screenshotTarget), { recursive: true });

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1_600, height: 1_400 },
      deviceScaleFactor: 1,
      colorScheme: "dark",
      reducedMotion: "reduce",
    });
    await context.route("http://agent-workbench.local/**", async (route) => {
      const pathname = decodeURIComponent(
        new URL(route.request().url()).pathname,
      );
      const candidate = resolve(temporaryOutput, `.${pathname}`);
      if (
        candidate !== temporaryOutput &&
        !candidate.startsWith(`${temporaryOutput}${sep}`)
      ) {
        await route.abort("blockedbyclient");
        return;
      }

      const contentTypes = {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
      };
      const contentType =
        contentTypes[extname(candidate)] ?? "application/octet-stream";
      await route.fulfill({
        status: 200,
        contentType,
        body: await readFile(candidate),
      });
    });

    const page = await context.newPage();
    const htmlRoute = relative(temporaryOutput, htmlPath).split(sep).join("/");
    await page.goto(`http://agent-workbench.local/${htmlRoute}`, {
      waitUntil: "networkidle",
    });
    await page.getByRole("heading", { name: "分析已完成" }).waitFor();
    await page.locator("#agent-workbench-screenshot").screenshot({
      path: screenshotTarget,
      animations: "disabled",
    });
  } finally {
    await browser.close();
  }
} finally {
  await rm(temporaryOutput, { recursive: true, force: true });
}
