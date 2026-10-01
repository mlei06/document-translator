const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("../../web/node_modules/@playwright/test");
const { pathToFileURL } = require("node:url");
const path = require("node:path");
const fs = require("node:fs");
const screenshots = path.resolve(
  __dirname,
  "../../../data/desktop-ui-verification",
);
let browser;
before(async () => {
  fs.mkdirSync(screenshots, { recursive: true });
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
});

async function preview(t, options = {}) {
  const page = await browser.newPage({
    viewport: { width: 980, height: 720 },
    ...options,
  });
  t.after(() => page.close());
  page.setDefaultTimeout(15000);
  await page.addInitScript(() => {
    window.fixture = {
      events: {},
      calls: [],
      picks: [],
      recent: [],
      cursors: {},
      counter: 0,
    };
    window.__TAURI__ = {
      event: {
        listen: async (name, callback) => {
          window.fixture.events[name] = callback;
        },
      },
      core: {
        invoke: async (command, args) => {
          const f = window.fixture;
          f.calls.push({ command, ...args });
          if (command === "default_export_directory") return "D:\\Downloads";
          if (command === "pick") return f.picks.shift() || [];
          if (command === "inspect_paths") {
            if (f.holdInspection)
              await new Promise((resolve) => {
                f.releaseInspection = resolve;
              });
            return args.paths.map((p) => ({
              path: p,
              kind: p.endsWith("Folder.v2") ? "folder" : "file",
              error: null,
            }));
          }
          if (command === "get_shortcuts") return ["en"];
          if (command !== "api") return null;
          if (args.path === "/v1/desktop/recent") return f.recent;
          if (args.path === "/v1/desktop/offline")
            return { state: "Not installed" };
          if (args.path === "/v1/desktop/discover") {
            const cursor = String(++f.counter);
            f.cursors[cursor] = [...args.body.paths];
            return { cursor };
          }
          if (args.path.startsWith("/v1/desktop/discover/")) {
            const p = f.cursors[args.path.split("/").pop()]?.shift();
            return args.method === "DELETE" || !p
              ? { done: true }
              : { path: p, name: p.split("\\").pop(), relative: null };
          }
          if (args.path === "/v1/desktop/submit")
            return { id: args.body.submission_id, status: "queued" };
          if (args.path.endsWith("/export"))
            return { path: "C:\\Exports\\report.zh.docx" };
          return {};
        },
      },
    };
  });
  await page.goto(
    pathToFileURL(path.resolve(__dirname, "../ui/index.html")).href,
  );
  return page;
}
async function drop(page, paths) {
  await page.evaluate(
    (paths) =>
      window.fixture.events["tauri://drag-drop"]({ payload: { paths } }),
    paths,
  );
}

test("drop feedback, named selections, validation and removal", async (t) => {
  const page = await preview(t);
  await page.evaluate(() =>
    window.fixture.events["tauri://drag-enter"]?.({ payload: {} }),
  );
  assert.equal(
    await page
      .locator("body")
      .evaluate((el) => el.classList.contains("dragging")),
    true,
  );
  await drop(page, [
    "C:\\Docs\\report.docx",
    "C:\\Docs\\Folder.v2",
    "C:\\Docs\\photo.png",
  ]);
  await page
    .getByRole("button", { name: "Remove report.docx", exact: true })
    .waitFor();
  assert.match(
    await page.locator("#selection").innerText(),
    /2 files and 1 folder/,
  );
  assert.match(
    await page.locator("#draft-list").innerText(),
    /Unsupported file type/,
  );
  await page
    .getByRole("button", { name: "Remove report.docx", exact: true })
    .click();
  assert.equal(
    await page
      .getByRole("button", { name: "Remove report.docx", exact: true })
      .count(),
    0,
  );
  assert.equal(
    await page
      .locator("body")
      .evaluate((el) => el.classList.contains("dragging")),
    false,
  );
});

test("destination cancel/reset and separate batches preserve the clicked target", async (t) => {
  const page = await preview(t);
  await page.evaluate(() => window.fixture.picks.push(["C:\\Exports"], []));
  await page
    .getByRole("button", { name: "Change folder", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Change folder", exact: true })
    .click();
  assert.equal(
    await page.locator("#destination-path").innerText(),
    "C:\\Exports",
  );
  await drop(page, ["C:\\Docs\\report.docx"]);
  await page
    .getByRole("button", { name: "Translate to Chinese", exact: true })
    .click();
  await page.waitForFunction(() =>
    window.fixture.calls.some((c) => c.path === "/v1/desktop/submit"),
  );
  await page
    .getByRole("button", { name: "Use Downloads", exact: true })
    .click();
  await drop(page, ["C:\\Docs\\next.txt"]);
  await page
    .getByRole("button", { name: "Translate to Japanese", exact: true })
    .click();
  await page.waitForFunction(
    () =>
      window.fixture.calls.filter((c) => c.path === "/v1/desktop/submit")
        .length === 2,
  );
  const requests = await page.evaluate(() =>
    window.fixture.calls
      .filter((c) => c.path === "/v1/desktop/submit")
      .map((c) => c.body),
  );
  assert.deepEqual(
    requests.map((r) => [r.target, r.destination]),
    [
      ["zh", "C:\\Exports"],
      ["ja", "D:\\Downloads"],
    ],
  );
});

test("activity progress, export recovery, overflow and polling preserve focus", async (t) => {
  const page = await preview(t);
  await page.evaluate(async () => {
    window.fixture.recent = [
      {
        id: "active",
        name: "report.docx",
        status: "running",
        target: "zh",
        progress: { phase: "translate", done: 2, total: 10 },
      },
      {
        id: "saved",
        name: "slides.pptx",
        status: "succeeded",
        target: "ja",
        output: "C:\\slides.ja.pptx",
      },
      { id: "saving", name: "notes.txt", status: "succeeded", target: "es" },
      {
        id: "error",
        name: "budget.xlsx",
        path: "C:\\budget.xlsx",
        status: "succeeded",
        target: "zh",
        error: "Permission denied",
      },
    ];
    await refresh();
  });
  assert.equal(
    await page.getByRole("button", { name: "Save file notes.txt" }).count(),
    0,
  );
  assert.match(await page.locator('[data-id="saving"]').innerText(), /Saving/);
  assert.equal(
    await page.locator('[data-id="active"] progress').getAttribute("value"),
    "2",
  );
  await page
    .getByRole("button", { name: "More actions for slides.pptx" })
    .click();
  await page
    .getByRole("button", { name: "Show in folder slides.pptx" })
    .focus();
  await page.evaluate(async () => {
    window.fixture.recent[1].output = "C:\\Updated location\\slides.ja.pptx";
    await refresh();
  });
  assert.equal(
    await page.evaluate(() =>
      document.activeElement.getAttribute("aria-label"),
    ),
    "Show in folder slides.pptx",
  );
  await page.keyboard.press("Escape");
  assert.equal(
    await page
      .getByRole("button", { name: "Show in folder slides.pptx" })
      .isVisible(),
    false,
  );
  await page.screenshot({
    path: path.join(screenshots, "activity.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Retry save budget.xlsx" }).click();
  assert.equal(
    await page.evaluate(
      () =>
        window.fixture.calls.filter((c) => c.path === "/v1/desktop/submit")
          .length,
    ),
    0,
  );
});

test("narrow, dark and scaled layouts keep controls inside the viewport", async (t) => {
  const page = await preview(t, {
    viewport: { width: 375, height: 500 },
    colorScheme: "dark",
    reducedMotion: "reduce",
  });
  await drop(page, [
    "C:\\Very long folder name\\A document with a very long filename that must wrap correctly.docx",
  ]);
  await page
    .getByRole("button", { name: "Translate to Chinese", exact: true })
    .waitFor();
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.screenshot({
    path: path.join(screenshots, "narrow-dark.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 980, height: 720 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
});

test("clear during path inspection cannot resurrect a removed draft", async (t) => {
  const page = await preview(t);
  await page.evaluate(() => {
    window.fixture.holdInspection = true;
    void window.fixture.events["tauri://drag-drop"]({
      payload: { paths: ["C:\\Docs\\report.docx"] },
    });
  });
  await page
    .getByRole("button", { name: "Remove report.docx", exact: true })
    .waitFor();
  assert.equal(
    await page
      .getByRole("button", { name: "Translate to English", exact: true })
      .isEnabled(),
    false,
  );
  await page.getByRole("button", { name: "Clear all", exact: true }).click();
  await page.evaluate(() => window.fixture.releaseInspection());
  assert.equal(await page.locator("#draft-section").isVisible(), false);
  assert.equal(
    await page
      .getByRole("button", { name: "Translate to English", exact: true })
      .isEnabled(),
    false,
  );
  await page.evaluate(() => {
    window.fixture.holdInspection = false;
  });
  await drop(page, ["C:\\Docs\\photo.png", "C:\\Docs\\photo.png"]);
  assert.equal(
    await page
      .getByRole("button", { name: "Remove photo.png", exact: true })
      .count(),
    1,
  );
  assert.equal(
    await page
      .getByRole("button", { name: "Translate to English", exact: true })
      .isEnabled(),
    false,
  );
});

test("four selected documents keep language actions in view at the default size", async (t) => {
  const page = await preview(t);
  await drop(page, [
    "C:\\Docs\\Report.docx",
    "C:\\Docs\\Slides.pptx",
    "C:\\Docs\\Budget.xlsx",
    "C:\\Docs\\Notes.pdf",
  ]);
  const box = await page
    .getByRole("button", { name: "Translate to Chinese", exact: true })
    .boundingBox();
  assert.ok(box.y + box.height <= 720);
  await page.screenshot({
    path: path.join(screenshots, "selected.png"),
    fullPage: true,
  });
});

test("dropped documents export to Downloads independently of their source folder", async (t) => {
  const page = await preview(t);
  assert.equal(
    await page.locator("#destination-path").innerText(),
    "D:\\Downloads",
  );
  await drop(page, ["C:\\Documents\\report.docx"]);
  await page
    .getByRole("button", { name: "Translate to Chinese", exact: true })
    .click();
  await page.waitForFunction(() =>
    window.fixture.calls.some((c) => c.path === "/v1/desktop/submit"),
  );
  const body = await page.evaluate(
    () =>
      window.fixture.calls.find((c) => c.path === "/v1/desktop/submit").body,
  );
  assert.equal(body.destination, "D:\\Downloads");
  assert.equal(body.relative, undefined);
});
