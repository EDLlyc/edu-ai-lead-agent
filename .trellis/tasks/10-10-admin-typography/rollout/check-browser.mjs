import {
  chromium,
  expect,
} from "/root/projects/edu-ai-lead-agent/frontend/node_modules/@playwright/test/index.mjs";
import { readFile, writeFile, mkdir } from "node:fs/promises";

const origin = process.env.ADMIN_REVIEW_ORIGIN ?? "http://127.0.0.1:5182";
const out = "/tmp/edu-admin-typography/browser";
await mkdir(out, { recursive: true });
const layouts = JSON.parse(
  await readFile(
    "/tmp/edu-admin-pipeline-integration/layout-fixtures.json",
    "utf8",
  ),
);
const report = {
  origin,
  pages: [],
  interactions: [],
  blockedWrites: [],
  errors: [],
};
const browser = await chromium.launch({ headless: true });
async function contextAt(width, { longNames = false, editor = false } = {}) {
  const context = await browser.newContext({
    viewport: { width, height: 960 },
    locale: "zh-CN",
  });
  await context.route("**/*", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    if (req.method() !== "GET" || url.origin !== origin) {
      report.blockedWrites.push({ path: url.pathname, method: req.method() });
      return route.abort();
    }
    if (url.pathname === "/api/v1/admin/wechat/layout-templates")
      return route.fulfill({
        json: { templates: layouts.templates, accounts: layouts.accounts },
      });
    if (
      url.pathname.startsWith("/api/v1/admin/wechat/layout-templates/") &&
      url.pathname.endsWith("/preview")
    ) {
      const id = url.pathname.split("/").at(-2);
      return route.fulfill({ json: { html: layouts.previews[id] } });
    }
    if (editor && url.pathname === "/api/v1/admin/auth/me") {
      const response = await route.fetch();
      const data = await response.json();
      return route.fulfill({ json: { ...data, role: "editor" } });
    }
    if (longNames && url.pathname === "/api/v1/admin/sources") {
      const response = await route.fetch();
      const data = await response.json();
      data.items[0].display_name =
        "全国青少年科学教育与科技创新实践活动新闻信息中心" +
        "连续长名称".repeat(8);
      return route.fulfill({ json: data });
    }
    await route.continue();
  });
  context.on("page", (page) =>
    page.on("pageerror", (error) => report.errors.push(error.message)),
  );
  return context;
}
const toggle = (page) => page.locator("button[aria-controls][aria-expanded]");
const menu = (page) => page.getByRole("navigation", { name: "后台菜单" });
const overflow = async (page) =>
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
try {
  const keys = [
    "sources",
    "keywords",
    "wechat-publish",
    "wechat-stats",
    "wechat-accounts",
    "layout-templates",
    "poster-styles",
    "models",
    "audit",
    "accounts",
    "account",
  ];
  for (const width of [320, 390, 768, 1366, 1440]) {
    const context = await contextAt(width);
    const page = await context.newPage();
    for (const key of keys) {
      if (
        width === 1440 &&
        ![
          "sources",
          "wechat-publish",
          "wechat-stats",
          "models",
          "layout-templates",
          "audit",
        ].includes(key)
      )
        continue;
      await page.goto(origin + "/admin/" + key, { waitUntil: "networkidle" });
      if (key === "wechat-publish")
        await page.getByRole("tab", { name: "发布记录", exact: true }).click();
      await expect(page.locator("#admin-section-title")).toBeVisible();
      await overflow(page);
      if (width <= 720) {
        await expect(toggle(page)).toBeVisible();
        await expect(toggle(page)).toHaveAttribute("aria-expanded", "false");
        await expect(menu(page)).toBeHidden();
      } else await expect(menu(page)).toBeVisible();
      const metrics = await page.evaluate(() => {
        const h = document.querySelector("#admin-section-title"),
          s = getComputedStyle(h);
        const firstCard = document.querySelector('[class*="cards"] > li');
        return {
          pageWidth: document.documentElement.scrollWidth,
          headingSize: s.fontSize,
          headingWeight: s.fontWeight,
          fontFamily: s.fontFamily,
          fontSynthesis: s.fontSynthesis,
          headingTop: h.getBoundingClientRect().top,
          firstCardTop: firstCard?.getBoundingClientRect().top ?? null,
        };
      });
      if (key === "models" || key === "layout-templates") {
        const details = page.locator("details");
        await expect(details).not.toHaveAttribute("open", "");
        const summary = details.locator("summary");
        await summary.focus();
        await page.keyboard.press("Enter");
        await expect(details).toHaveAttribute("open", "");
        await overflow(page);
        await page.keyboard.press("Enter");
        await expect(details).not.toHaveAttribute("open", "");
      }
      report.pages.push({ key, width, ...metrics });
      if ([390, 1440].includes(width))
        await page.screenshot({ path: `${out}/${key}-${width}.png` });
    }
    await context.close();
  }
  const context = await contextAt(390),
    page = await context.newPage();
  await page.goto(origin + "/admin/models", { waitUntil: "networkidle" });
  await expect(toggle(page)).toContainText("模型配置");
  await toggle(page).click();
  await expect(menu(page).getByRole("link")).toHaveCount(11);
  await overflow(page);
  await menu(page).getByRole("link", { name: "操作记录" }).focus();
  await page.keyboard.press("Escape");
  await expect(toggle(page)).toBeFocused();
  await expect(menu(page)).toBeHidden();
  await page.keyboard.press("Tab");
  expect(
    await page.evaluate(
      () =>
        document.activeElement.closest('nav[aria-label="后台菜单"]') === null,
    ),
  ).toBe(true);
  await toggle(page).click();
  await menu(page).getByRole("link", { name: "操作记录" }).click();
  await expect(page).toHaveURL(origin + "/admin/audit");
  await expect(menu(page)).toBeHidden();
  await expect(toggle(page)).toContainText("操作记录");
  await expect(toggle(page)).toBeFocused();
  await toggle(page).click();
  await menu(page).getByRole("link", { name: "关键词", exact: true }).click();
  const input = page.getByRole("textbox", { name: /添加/ }).first();
  await input.fill("仅在本地编辑的词");
  await toggle(page).click();
  await menu(page).getByRole("link", { name: "模型配置" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", { name: "继续编辑", exact: true }).click();
  await expect(page).toHaveURL(origin + "/admin/keywords");
  await expect(input).toHaveValue("仅在本地编辑的词");
  await expect(menu(page)).toBeVisible();
  await expect(
    menu(page).getByRole("link", { name: "模型配置" }),
  ).toBeFocused();
  await menu(page).getByRole("link", { name: "模型配置" }).click();
  await page.getByRole("button", { name: "放弃修改并继续" }).click();
  await expect(page).toHaveURL(origin + "/admin/models");
  await expect(menu(page)).toBeHidden();
  await expect(toggle(page)).toBeFocused();
  report.interactions.push(
    "all 11 mobile destinations; Escape and Tab; navigation collapse; dirty cancel retains value/focus; discard navigates/focuses toggle",
  );
  await page.setViewportSize({ width: 1366, height: 960 });
  await expect(menu(page)).toBeVisible();
  await menu(page).getByRole("link", { name: "操作记录" }).focus();
  await page.setViewportSize({ width: 390, height: 960 });
  expect(
    await page.evaluate(
      () => document.activeElement.getClientRects().length > 0,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1366, height: 960 });
  expect(
    await page.evaluate(
      () => document.activeElement.getClientRects().length > 0,
    ),
  ).toBe(true);
  report.interactions.push("desktop/mobile resize preserves visible focus");
  await page.goto(origin + "/admin/layout-templates", {
    waitUntil: "networkidle",
  });
  for (const template of layouts.templates) {
    await page.locator(`input[type="radio"][value="${template.id}"]`).check();
    const frame = page.locator(`iframe[title="排版预览：${template.name}"]`);
    await expect(frame).toBeVisible();
    await expect(frame).toHaveAttribute("sandbox", "");
    expect(await frame.getAttribute("srcdoc")).toContain(
      layouts.previews[template.id],
    );
  }
  report.interactions.push(
    "all 4 article template bodies remain unchanged and sandboxed",
  );
  await page.goto(origin + "/admin/models", { waitUntil: "networkidle" });
  // Browser 200% text-size enlargement exercises reflow in addition to 320 CSS-pixel viewport.
  await page.setViewportSize({ width: 390, height: 960 });
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
  await overflow(page);
  await page.screenshot({ path: `${out}/models-text-200.png`, fullPage: true });
  report.interactions.push("200% text resize, 390 CSS pixels");
  await context.close();
  const long = await contextAt(320, { longNames: true }),
    longPage = await long.newPage();
  await longPage.goto(origin + "/admin/sources", { waitUntil: "networkidle" });
  await overflow(longPage);
  await longPage.screenshot({
    path: `${out}/sources-long-320.png`,
    fullPage: true,
  });
  await long.close();
  const editor = await contextAt(390, { editor: true }),
    editorPage = await editor.newPage();
  await editorPage.goto(origin + "/admin/sources", {
    waitUntil: "networkidle",
  });
  await toggle(editorPage).click();
  await expect(menu(editorPage).getByRole("link")).toHaveCount(7);
  await expect(
    menu(editorPage).getByRole("link", { name: "模型配置" }),
  ).toHaveCount(0);
  report.interactions.push(
    "long source names at 320; editor role only 7 permitted destinations",
  );
  await editor.close();
  expect(report.blockedWrites).toEqual([]);
  expect(report.errors).toEqual([]);
} finally {
  await browser.close();
  await writeFile(out + "/result.json", JSON.stringify(report, null, 2) + "\n");
}
console.log(
  JSON.stringify(
    {
      pages: report.pages.length,
      interactions: report.interactions,
      errors: report.errors,
      blockedWrites: report.blockedWrites,
    },
    null,
    2,
  ),
);
