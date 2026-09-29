// Capture the Lenny mock's states for the P6.0 audit (docs/design/web-gui/AUDIT.md).
// Run from the repository root after `npm install` in apps/web:
//   node docs/design/web-gui/audit/capture-mock.mjs
// Uses the installed Microsoft Edge through Playwright's msedge channel; writes JPEGs next to
// this script. The mock itself is not modified.
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.resolve(here, "../../../../apps/web/package.json"));
const { chromium } = require("@playwright/test");

const mock = pathToFileURL(path.resolve(here, "../prototype/lenny.html")).href;
const viewport = "width=device-width, initial-scale=1, viewport-fit=cover";
const log = (...args) => console.log(...args);

async function shot(page, name) {
  await page.screenshot({ path: path.join(here, `${name}.jpg`), type: "jpeg", quality: 72 });
  log("captured", name);
}

async function step(name, action) {
  try {
    await action();
  } catch (error) {
    log("step failed:", name, error.message.split("\n")[0]);
  }
}

async function open(browser, options) {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  await page.goto(mock);
  await page.evaluate((content) => {
    const meta = document.createElement("meta");
    meta.name = "viewport";
    meta.content = content;
    document.head.prepend(meta);
    localStorage.clear();
  }, viewport);
  await page.waitForTimeout(1500);
  return { context, page };
}

async function signIn(page, name = "Mei") {
  await page.fill("#user", name);
  await page.fill("#pass", "anything");
  await page.click("#signForm button[type=submit]");
  await page.waitForTimeout(2800);
}

const browser = await chromium.launch({ channel: "msedge" });
try {
  const { context, page } = await open(browser, { viewport: { width: 1440, height: 900 } });
  await shot(page, "01-signin-day");
  await step("username focus", async () => {
    await page.focus("#user");
    await page.waitForTimeout(900);
    await shot(page, "02-signin-username-focus");
  });
  await step("password focus", async () => {
    await page.fill("#user", "Mei");
    await page.focus("#pass");
    await page.waitForTimeout(900);
    await shot(page, "03-signin-password-focus");
  });
  await step("sign in", async () => {
    await page.fill("#pass", "anything");
    await page.click("#signForm button[type=submit]");
    await page.waitForTimeout(2800);
    await shot(page, "04-app-empty");
  });
  await step("account menu", async () => {
    await page.click("#uchip");
    await page.waitForTimeout(500);
    await shot(page, "05-account-menu");
    await page.keyboard.press("Escape");
  });
  await step("lenny menu", async () => {
    await page.click("#lennyBtn");
    await page.waitForTimeout(700);
    await shot(page, "06-lenny-menu");
    await page.keyboard.press("Escape");
  });
  await step("samples", async () => {
    await page.click('[data-act="samples"]');
    await page.waitForTimeout(6500);
    await shot(page, "07-swallowed-confirm-languages");
  });
  await step("target question", async () => {
    await page.click('[data-act="done"]');
    await page.waitForTimeout(1500);
    await shot(page, "08-target-language");
  });
  await step("translate", async () => {
    const chip = page.locator("[data-target]").first();
    await chip.click();
    await page.waitForTimeout(1200);
    const submit = page.locator('button[type="submit"]:has-text("Translate")');
    if (await submit.isVisible()) await submit.click();
    await page.waitForTimeout(3000);
    await shot(page, "09-bubbles-progress");
    await page.waitForTimeout(12000);
    await shot(page, "10-bubbles-done");
  });
  await step("preview compare", async () => {
    await page.locator("#bubbles button, #bubbles [role=button], #bubbles .bubble").first().click();
    await page.waitForTimeout(1500);
    await shot(page, "11-preview-compare");
  });
  await step("preview side by side", async () => {
    await page.click('[data-mode="sbs"]');
    await page.waitForTimeout(800);
    await shot(page, "12-preview-side-by-side");
    await page.click('[data-act="close"]');
    await page.waitForTimeout(800);
  });
  await step("history", async () => {
    await page.locator('[data-act="history"]').first().click();
    await page.waitForTimeout(1000);
    await shot(page, "13-your-files");
    const example = page.locator('[data-hact="example"]');
    if (await example.isVisible()) {
      await example.click();
      await page.waitForTimeout(800);
      await shot(page, "14-your-files-example-history");
    }
    await page.click('[data-hact="close"]');
    await page.waitForTimeout(600);
  });
  await step("settings", async () => {
    await page.click("#uchip");
    await page.waitForTimeout(300);
    await page.locator('#umenu [data-act="settings"]').click();
    await page.waitForTimeout(900);
    await shot(page, "15-lenny-settings");
    await page.click('[data-act="set-done"]');
    await page.waitForTimeout(500);
  });
  await step("night", async () => {
    await page.locator('[data-act="theme"]').first().click();
    await page.waitForTimeout(2200);
    await shot(page, "16-app-night");
  });
  await context.close();

  const dark = await open(browser, { viewport: { width: 1440, height: 900 }, colorScheme: "dark" });
  await shot(dark.page, "17-signin-night");
  await dark.context.close();

  const phone = await open(browser, {
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  await shot(phone.page, "18-phone-signin");
  await step("phone app", async () => {
    await signIn(phone.page);
    await shot(phone.page, "19-phone-app");
    await phone.page.click('[data-act="samples"]');
    await phone.page.waitForTimeout(6500);
    await phone.page.click('[data-act="done"]');
    await phone.page.waitForTimeout(1200);
    await phone.page.locator("[data-target]").first().click();
    await phone.page.waitForTimeout(4000);
    await shot(phone.page, "20-phone-bubbles");
  });
  await phone.context.close();
} finally {
  await browser.close();
}
