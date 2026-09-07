"use strict";

// Local-only browser observation. Never edits the preview or constructs a provider.
const fs = require("node:fs/promises");
const path = require("node:path");
const http = require("node:http");
const crypto = require("node:crypto");
const { chromium } = require(path.join(process.cwd(), "frontend/node_modules/playwright"));

const sha = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const fail = (code) => { throw new Error(code); };

async function readSafe(root, relative) {
  if (!/^[a-zA-Z0-9_./-]+$/.test(relative) || relative.startsWith("/") ||
      relative.split("/").some((part) => !part || part === "." || part === "..")) {
    fail("unsafe_relative_path");
  }
  const target = path.join(root, relative);
  if (await fs.realpath(target) !== target) fail("symlink_not_allowed");
  const stat = await fs.stat(target);
  if (!stat.isFile() || stat.size > 32 * 1024 * 1024) fail("invalid_file");
  return fs.readFile(target);
}

async function main() {
  const [inputArg, outputArg] = process.argv.slice(2);
  if (!inputArg || !outputArg || process.argv.length !== 4) fail("two_paths_required");
  const root = path.resolve(inputArg);
  if (await fs.realpath(root) !== root) fail("symlink_not_allowed");
  const input = JSON.parse(await readSafe(root, "mobile-input.json"));
  if (input.schema_version !== "visual-preview-mobile-input-v1" ||
      input.copy_root !== "copy-root" || JSON.stringify(input.required_widths) !== "[320,430]") {
    fail("invalid_mobile_input");
  }
  const manifestBytes = await readSafe(root, "manifest.json");
  const manifest = JSON.parse(manifestBytes);
  for (const key of ["content_fingerprint", "body_sha256", "preview_sha256"]) {
    if (!/^[a-f0-9]{64}$/.test(input[key]) || input[key] !== manifest[key]) fail("identity_mismatch");
  }
  if (JSON.stringify(input.media_sha256_by_path) !== JSON.stringify(manifest.media_sha256_by_path)) {
    fail("media_identity_mismatch");
  }
  const previewBytes = await readSafe(root, "preview.html");
  const bodyBytes = await readSafe(root, "article-body.html");
  if (sha(previewBytes) !== input.preview_sha256 || sha(bodyBytes) !== input.body_sha256) {
    fail("html_hash_mismatch");
  }
  const body = bodyBytes.toString("utf8");
  const preview = previewBytes.toString("utf8");
  if (!preview.includes('<main id="copy-root">' + body + "</main>")) fail("body_source_mismatch");
  const resources = new Map([["/preview.html", { bytes: previewBytes, type: "text/html; charset=utf-8" }]]);
  const media = Object.entries(input.media_sha256_by_path);
  if (media.length !== 7) fail("unexpected_media_count");
  for (const [relative, checksum] of media) {
    const bytes = await readSafe(root, relative);
    if (sha(bytes) !== checksum) fail("media_hash_mismatch");
    const type = relative.endsWith(".jpg") ? "image/jpeg" : relative.endsWith(".png") ? "image/png" : null;
    if (!type) fail("unexpected_media_type");
    resources.set("/" + relative, { bytes, type });
  }
  const output = path.resolve(outputArg);
  if (output === root || output.startsWith(root + path.sep)) fail("evidence_must_be_separate");
  await fs.mkdir(output, { mode: 0o700 }); // Fresh output, never overwrite prior observations.
  const server = http.createServer((request, response) => {
    const item = request.method === "GET" ? resources.get(request.url) : undefined;
    response.writeHead(item ? 200 : 404, {
      "Content-Type": item ? item.type : "text/plain",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    response.end(item ? item.bytes : "Not found");
  });
  let browser;
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const origin = "http://127.0.0.1:" + server.address().port;
    browser = await chromium.launch({ headless: true });
    const observations = [];
    for (const width of input.required_widths) {
      const context = await browser.newContext({
        viewport: { width, height: 900 }, deviceScaleFactor: 1,
        javaScriptEnabled: false, serviceWorkers: "block",
      });
      let externalRequests = 0;
      const page = await context.newPage();
      page.on("request", (request) => {
        if (new URL(request.url()).origin !== origin) externalRequests += 1;
      });
      await context.route("**/*", async (route) => {
        if (new URL(route.request().url()).origin !== origin) await route.abort();
        else await route.continue();
      });
      await page.goto(origin + "/preview.html", { waitUntil: "load", timeout: 30000 });
      const measured = await page.evaluate((expectedBody) => {
        const template = document.createElement("template");
        template.innerHTML = expectedBody;
        const images = Array.from(document.images);
        return {
          width: window.innerWidth,
          loaded_images: images.filter((item) => item.complete && item.naturalWidth > 0).length,
          failed_images: images.filter((item) => !item.complete || item.naturalWidth === 0).length,
          horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - window.innerWidth,
            document.body.scrollWidth - window.innerWidth),
          copy_root_matches_body: document.querySelectorAll("#copy-root").length === 1 &&
            document.querySelector("#copy-root").innerHTML === template.innerHTML,
          paths: images.map((item) => new URL(item.currentSrc).pathname),
        };
      }, body);
      if (JSON.stringify([...measured.paths].sort()) !==
          JSON.stringify(media.map(([relative]) => "/" + relative).sort())) fail("loaded_media_mismatch");
      delete measured.paths;
      await page.screenshot({ path: path.join(output, "mobile-" + width + ".png"), fullPage: true });
      observations.push({ ...measured, external_requests: externalRequests });
      await context.close();
    }
    const report = {
      schema_version: "visual-preview-mobile-report-v1",
      content_fingerprint: input.content_fingerprint,
      body_sha256: input.body_sha256,
      preview_sha256: input.preview_sha256,
      media_sha256_by_path: input.media_sha256_by_path,
      observations,
    };
    await fs.writeFile(path.join(output, "mobile-report.json"), JSON.stringify(report, null, 2) + "\n",
      { mode: 0o600, flag: "wx" });
    for (const width of input.required_widths) await fs.chmod(path.join(output, "mobile-" + width + ".png"), 0o600);
    const passed = observations.every((item) => item.loaded_images === 7 && item.failed_images === 0 &&
      item.horizontal_overflow_px === 0 && item.external_requests === 0 && item.copy_root_matches_body);
    console.log(JSON.stringify({ status: passed ? "passed" : "failed", observations,
      preview_manifest_sha256: sha(manifestBytes), provider_calls: 0 }));
    if (!passed) process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch(() => {
  console.log(JSON.stringify({ status: "failed", code: "mobile_check_failed_closed", provider_calls: 0 }));
  process.exitCode = 1;
});
