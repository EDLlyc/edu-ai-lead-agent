import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const frontendRoot = resolve(repositoryRoot, "frontend");
const requireFromFrontend = createRequire(
  resolve(frontendRoot, "package.json"),
);
const { chromium } = requireFromFrontend("@playwright/test");

const apiOrigin = "http://127.0.0.1:8010";
const uiOrigin = "http://127.0.0.1:5173";
const runUrl = `${apiOrigin}/api/v1/agent-workbench/runs`;
const argumentsByName = parseArguments(process.argv.slice(2));
const casesPath = requiredArgument(argumentsByName, "--cases");
const outputDirectory = requiredArgument(argumentsByName, "--output-dir");
const observationOutput = requiredArgument(
  argumentsByName,
  "--observation-output",
);
const mode = requiredArgument(argumentsByName, "--mode");

if (mode !== "deterministic" && mode !== "live-zhipu") {
  throw new Error("capture mode is not allowlisted");
}

const caseManifest = JSON.parse(await readFile(casesPath, "utf8"));
if (
  caseManifest.schema_version !== "agent-workbench-portfolio-cases-v1" ||
  !Array.isArray(caseManifest.cases)
) {
  throw new Error("portfolio case manifest has an invalid shape");
}
const selectedCases =
  mode === "deterministic"
    ? caseManifest.cases
    : caseManifest.cases.filter(
        (portfolioCase) => portfolioCase.case_id === "multi-tool-research",
      );
if (selectedCases.length !== (mode === "deterministic" ? 3 : 1)) {
  throw new Error("portfolio browser case selection is invalid");
}

const browser = await chromium.launch({ headless: true });
const observations = [];
const overviewCases = [];
try {
  const context = await browser.newContext({
    viewport: { width: 1_600, height: 1_100 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });

  for (const portfolioCase of selectedCases) {
    validatePortfolioCase(portfolioCase);
    const page = await context.newPage();
    const workbenchPosts = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url() === runUrl) {
        workbenchPosts.push(request);
      }
    });

    try {
      const navigationResponse = await page.goto(uiOrigin, {
        waitUntil: "domcontentloaded",
      });
      if (navigationResponse === null) {
        throw new Error("Vite navigation did not return an HTTP response");
      }
      assertLoopbackServerAddress(
        await navigationResponse.serverAddr(),
        5173,
        "Vite UI",
      );
      await page
        .getByRole("heading", { name: "Agent 研究工作台" })
        .waitFor({ state: "visible" });
      const queryInput = page.getByRole("textbox", {
        name: "向受控 Agent 提问",
      });
      await queryInput.fill(portfolioCase.query);

      const apiResponsePromise = page.waitForResponse(
        (response) =>
          response.url() === runUrl && response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "运行受控分析" }).click();
      const apiResponse = await apiResponsePromise;
      if (apiResponse.status() !== 200) {
        throw new Error(
          "Workbench browser request returned a non-success status",
        );
      }
      const serverAddress = assertLoopbackServerAddress(
        await apiResponse.serverAddr(),
        8010,
        "Workbench API",
      );
      const typedResponse = await apiResponse.json();
      validateTypedResponse(typedResponse);

      const responsePath = resolve(
        outputDirectory,
        `${portfolioCase.case_id}.response.json`,
      );
      await writeFile(
        responsePath,
        `${JSON.stringify(typedResponse, null, 2)}\n`,
        "utf8",
      );

      const terminal = terminalLocator(page, typedResponse.status);
      await terminal.waitFor({ state: "visible" });
      await page.waitForFunction(
        () =>
          document.fonts === undefined || document.fonts.status === "loaded",
      );
      if (workbenchPosts.length !== 1) {
        throw new Error(
          "browser capture did not make exactly one Workbench POST",
        );
      }

      const screenshotPath = resolve(
        outputDirectory,
        `${portfolioCase.case_id}.png`,
      );
      await terminal.screenshot({
        path: screenshotPath,
        animations: "disabled",
      });
      observations.push({
        case_id: portfolioCase.case_id,
        request_count: workbenchPosts.length,
        request_url: runUrl,
        server_address: serverAddress,
      });
      overviewCases.push({
        portfolioCase,
        response: typedResponse,
        screenshotPath,
      });
    } finally {
      await page.close();
    }
  }

  await captureOverview(context, overviewCases, outputDirectory, mode);
} finally {
  await browser.close();
}

await writeFile(
  observationOutput,
  `${JSON.stringify({ cases: observations }, null, 2)}\n`,
  "utf8",
);

function parseArguments(values) {
  if (values.length % 2 !== 0) {
    throw new Error("capture arguments must be name/value pairs");
  }
  const parsed = new Map();
  for (let index = 0; index < values.length; index += 2) {
    const name = values[index];
    const value = values[index + 1];
    if (!name?.startsWith("--") || value === undefined || parsed.has(name)) {
      throw new Error("capture arguments are invalid");
    }
    parsed.set(name, value);
  }
  return parsed;
}

function requiredArgument(values, name) {
  const value = values.get(name);
  if (value === undefined || value.length === 0) {
    throw new Error(`required capture argument is missing: ${name}`);
  }
  return value;
}

function validatePortfolioCase(portfolioCase) {
  if (
    typeof portfolioCase !== "object" ||
    portfolioCase === null ||
    typeof portfolioCase.case_id !== "string" ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(portfolioCase.case_id) ||
    typeof portfolioCase.query !== "string" ||
    portfolioCase.query.length === 0 ||
    portfolioCase.query.length > 500
  ) {
    throw new Error("portfolio browser case is invalid");
  }
}

function validateTypedResponse(response) {
  if (
    typeof response !== "object" ||
    response === null ||
    typeof response.run_id !== "string" ||
    typeof response.status !== "string" ||
    typeof response.summary !== "string" ||
    !Array.isArray(response.claims) ||
    !Array.isArray(response.citations) ||
    !Array.isArray(response.steps) ||
    typeof response.metrics !== "object" ||
    response.metrics === null
  ) {
    throw new Error("Workbench browser response is not a typed run projection");
  }
}

function terminalLocator(page, status) {
  if (
    status === "completed" ||
    status === "refused" ||
    status === "budget_exhausted"
  ) {
    const domStatus =
      status === "budget_exhausted" ? "budget-exhausted" : status;
    return page.locator(`article[data-status="${domStatus}"]`);
  }
  return page.getByRole("alert");
}

function assertLoopbackServerAddress(address, expectedPort, label) {
  const ipAddress = address?.ipAddress?.replace(/^::ffff:/u, "");
  if (ipAddress !== "127.0.0.1" || address?.port !== expectedPort) {
    throw new Error(`${label} did not resolve to the exact loopback service`);
  }
  return `127.0.0.1:${expectedPort}`;
}

async function captureOverview(context, cases, outputDirectory, captureMode) {
  const page = await context.newPage();
  try {
    const cards = await Promise.all(
      cases.map(async ({ portfolioCase, response, screenshotPath }) => {
        const png = await readFile(screenshotPath);
        const tools = response.steps
          .filter((step) => step.kind === "tool_call" && step.tool_name)
          .map((step) => step.tool_name)
          .join(" → ");
        return `
          <article class="card">
            <header>
              <p>${escapeHtml(portfolioCase.case_id)}</p>
              <h2>${escapeHtml(portfolioCase.screenshot_label)}</h2>
            </header>
            <dl>
              <div><dt>TERMINAL</dt><dd>${escapeHtml(response.status)}</dd></div>
              <div><dt>TOOLS</dt><dd>${escapeHtml(tools || "none")}</dd></div>
              <div><dt>CITATIONS</dt><dd>${response.citations.length}</dd></div>
              <div><dt>STEPS</dt><dd>${response.steps.length}</dd></div>
              <div><dt>MODEL / TOOL</dt><dd>${response.metrics.model_turns} / ${response.metrics.tool_calls}</dd></div>
            </dl>
            <div class="image-frame">
              <img src="data:image/png;base64,${png.toString("base64")}" alt="" />
            </div>
          </article>`;
      }),
    );
    const authority =
      captureMode === "deterministic"
        ? "REAL LOOPBACK HTTP · DETERMINISTIC FIXTURE · CONTRACT EVIDENCE, NOT LIVE-MODEL ACCURACY"
        : "ONE AUTHORIZED REAL LOOPBACK RUN · LIVE ZHIPU · NON-DETERMINISTIC";
    await page.setContent(`<!doctype html>
      <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <style>
            :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
            * { box-sizing: border-box; }
            body { margin: 0; background: #07090a; color: #f4f4ec; }
            main { width: 1800px; padding: 70px; background: radial-gradient(circle at top right, #143b3a 0, #07090a 34%); }
            .topline { margin: 0 0 16px; color: #48e0cf; font: 700 15px ui-monospace, monospace; letter-spacing: .16em; }
            h1 { max-width: 1200px; margin: 0; font-size: 68px; line-height: .95; letter-spacing: -.055em; }
            .authority { margin: 28px 0 44px; color: #b9c2c1; font: 700 15px ui-monospace, monospace; letter-spacing: .07em; }
            .grid { display: grid; grid-template-columns: repeat(${cases.length === 1 ? 1 : 3}, minmax(0, 1fr)); gap: 24px; }
            .card { min-width: 0; border: 1px solid #36504f; background: rgba(7, 9, 10, .94); box-shadow: inset 5px 0 #48e0cf; padding: 26px; }
            .card header p { margin: 0 0 10px; color: #48e0cf; font: 700 12px ui-monospace, monospace; letter-spacing: .12em; text-transform: uppercase; }
            .card h2 { min-height: 70px; margin: 0; font-size: 28px; line-height: 1.1; letter-spacing: -.035em; }
            dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 24px 0; background: #36504f; border: 1px solid #36504f; }
            dl div { min-width: 0; background: #0d1112; padding: 12px; }
            dt { color: #8d9998; font: 700 10px ui-monospace, monospace; letter-spacing: .1em; }
            dd { margin: 7px 0 0; color: #f4f4ec; font: 700 12px ui-monospace, monospace; overflow-wrap: anywhere; }
            .image-frame { display: grid; height: ${cases.length === 1 ? 900 : 620}px; place-items: start center; overflow: hidden; border: 1px solid #273535; background: #07090a; }
            img { width: 100%; height: 100%; object-fit: contain; object-position: top center; }
          </style>
        </head>
        <body>
          <main id="real-run-overview">
            <p class="topline">AGENT RESEARCH WORKBENCH / CHECKED EVIDENCE</p>
            <h1>Real local runs.<br />Bounded, cited, inspectable.</h1>
            <p class="authority">${authority}</p>
            <section class="grid">${cards.join("")}</section>
          </main>
        </body>
      </html>`);
    await page.locator("#real-run-overview").screenshot({
      path: resolve(outputDirectory, "overview.png"),
      animations: "disabled",
    });
  } finally {
    await page.close();
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
