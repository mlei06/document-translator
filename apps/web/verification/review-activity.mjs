// Explicit native-command fixture, not a packaged Explorer integration check.
import { chromium, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
const browser = await chromium.launch()
const page = await browser.newPage()
await page.addInitScript(() => {
  window.fixture = {
    calls: [],
    groups: [
      {
        id: 'batch-1',
        target: 'zh',
        enumerating: true,
        cancelled: false,
        errors: [
          { path: 'C:/Documents/locked.docx', error: 'The original document could not be opened.' },
        ],
        jobs: [
          { id: 'one', path: 'C:/Documents/Annual report.docx', status: 'running' },
          {
            id: 'two',
            path: 'C:/Documents/Minutes.docx',
            status: 'succeeded',
            output: 'C:/Documents/Minutes.zh.docx',
          },
        ],
      },
    ],
  }
  window.__TAURI__ = {
    core: {
      invoke: async (command, args) => {
        window.fixture.calls.push({ command, ...args })
        if (command === 'activity_state') return structuredClone(window.fixture.groups)
        if (command === 'cancel_activity') {
          const group = window.fixture.groups.find((group) => group.id === args.group)
          group.cancelled = true
          group.enumerating = false
          group.jobs = group.jobs.map((job) =>
            job.status === 'running' ? { ...job, status: 'cancelled' } : job,
          )
        }
      },
    },
  }
})
for (const colorScheme of ['light', 'dark']) {
  await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 560, height: 700 })
  await page.goto(new URL('../../desktop/ui/activity.html', import.meta.url).href)
  await expect(
    page.getByText('Finding files. 2 accepted, 1 translated, 1 active, 1 need attention.', {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByText('Needs attention: The original document could not be opened.'),
  ).toBeVisible()
  const cancel = page.getByRole('button', { name: 'Cancel Chinese batch', exact: true })
  await cancel.focus()
  await page.waitForTimeout(1200)
  await expect(cancel).toBeFocused()
  for (const [label, folder] of [
    ['Open file', false],
    ['Show in folder', true],
  ]) {
    const action = page.getByRole('button', { name: label, exact: true })
    await action.focus()
    await page.waitForTimeout(1200)
    await expect(action).toBeFocused()
    await action.click()
    expect(
      await page.evaluate(
        (folder) =>
          window.fixture.calls.some(
            (call) =>
              call.command === 'open_export' &&
              call.path === 'C:/Documents/Minutes.zh.docx' &&
              call.folder === folder,
          ),
        folder,
      ),
    ).toBe(true)
  }
  await page.screenshot({
    path: fileURLToPath(
      new URL(`screenshots/desktop-activity-${colorScheme}.png`, import.meta.url),
    ),
    fullPage: true,
  })
}
await page.getByRole('button', { name: 'Cancel Chinese batch', exact: true }).click()
await expect(
  page.getByText('Cancelled. 2 accepted, 1 translated, 0 active, 1 need attention, 1 cancelled.', {
    exact: true,
  }),
).toBeVisible()
expect(
  await page.evaluate(() =>
    window.fixture.calls.some(
      (call) => call.command === 'cancel_activity' && call.group === 'batch-1',
    ),
  ),
).toBe(true)
await page.getByRole('button', { name: 'Open Lenny', exact: true }).click()
expect(
  await page.evaluate(() => window.fixture.calls.some((call) => call.command === 'open_main')),
).toBe(true)
await page.setViewportSize({ width: 375, height: 700 })
expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
  true,
)
await browser.close()
console.log(
  'Explorer activity UI fixture passed: counts, per-file errors, cancellation, direct export actions, main-window command, focus and narrow layout.',
)
