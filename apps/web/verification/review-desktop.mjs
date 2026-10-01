// Isolated browser visual fixture. This does not certify the native bridge.
import { chromium, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
const browser = await chromium.launch()
const page = await browser.newPage()
await page.addInitScript(() => {
  window.fixture = {
    calls: [],
    submitCount: 0,
    discovered: 0,
    records: [
      {
        id: 'done',
        name: 'Annual report with a long descriptive filename.docx',
        status: 'succeeded',
        output: 'C:/test/report.docx',
        target: 'zh',
        path: 'C:/test/report.docx',
      },
      {
        id: 'failed',
        name: 'Meeting notes.docx',
        status: 'failed',
        error: 'Translation service unavailable',
        path: 'C:/test/Meeting notes.docx',
        target: 'ja',
        destination: null,
      },
    ],
  }
  window.__TAURI__ = {
    core: {
      invoke: async (command, args) => {
        window.fixture.calls.push({ command, ...args })
        if (command === 'get_shortcuts') return ['en', 'zh']
        if (command === 'pick') return ['C:/test/folder']
        if (command === 'api' && args.path === '/v1/desktop/recent')
          return structuredClone(window.fixture.records)
        if (command === 'api' && args.path.endsWith('/dismiss')) {
          window.fixture.records = window.fixture.records.filter(
            (item) => !args.path.includes(`/${item.id}/`),
          )
          return { dismissed: true }
        }
        if (command === 'api' && args.path === '/v1/desktop/submit') {
          window.fixture.submitCount++
          if (window.fixture.submitCount === 1)
            throw JSON.stringify({ code: 'queue_full', message: 'Queue full', retryable: true })
          const result = {
            id: `accepted-${window.fixture.submitCount}`,
            name: args.body.relative || 'Meeting notes.docx',
            path: args.body.path,
            target: args.body.target,
            status: 'queued',
            destination: args.body.destination,
          }
          window.fixture.records.push(result)
          return structuredClone(result)
        }
        if (command === 'api' && args.path === '/v1/desktop/discover')
          return { cursor: 'folder-cursor' }
        if (command === 'api' && args.path === '/v1/desktop/discover/folder-cursor') {
          if (args.method === 'DELETE') return { cancelled: true }
          window.fixture.discovered++
          if (window.fixture.discovered > 1)
            await new Promise((resolve) => setTimeout(resolve, 1500))
          return {
            done: false,
            path: 'C:/test/folder/report.docx',
            relative: `report-${window.fixture.discovered}.docx`,
          }
        }
        if (command === 'api' && args.path === '/v1/desktop/offline')
          return { state: 'Not installed' }
        return []
      },
    },
    event: { listen: async () => {} },
  }
})
for (const colorScheme of ['light', 'dark']) {
  await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 900, height: 1000 })
  await page.goto(new URL('../../desktop/ui/index.html', import.meta.url).href)
  await page.locator('.item').first().waitFor()
  await expect(
    page.getByRole('button', { name: 'Retry Meeting notes.docx', exact: true }),
  ).toBeVisible()
  await page.screenshot({
    path: fileURLToPath(new URL(`screenshots/desktop-review-${colorScheme}.png`, import.meta.url)),
    fullPage: true,
  })
}
// Exercise per-file recovery, native-call arguments, polling focus and streamed cancellation.
await page.getByRole('button', { name: 'Retry Meeting notes.docx', exact: true }).click()
await expect.poll(() => page.evaluate(() => window.fixture.submitCount), { timeout: 15000 }).toBe(2)
const submissions = await page.evaluate(() =>
  window.fixture.calls.filter((call) => call.path === '/v1/desktop/submit'),
)
expect(submissions[0].body.submission_id).toBe(submissions[1].body.submission_id)
expect(submissions[0].body.target).toBe('ja')
expect(submissions[0].body.submission_id).not.toBe('failed')
await expect(page.locator('[data-id="failed"]')).toHaveCount(0)
const open = page.getByRole('button', {
  name: 'Open file Annual report with a long descriptive filename.docx',
  exact: true,
})
await open.focus()
await page.waitForTimeout(2200)
await expect(open).toBeFocused()
await page
  .getByRole('button', {
    name: 'Dismiss Annual report with a long descriptive filename.docx',
    exact: true,
  })
  .click()
await expect(page.locator('[data-id="done"]')).toHaveCount(0)
await page.getByRole('button', { name: 'Choose folders', exact: true }).click()
await page.getByRole('button', { name: 'Spanish', exact: true }).click()
await expect.poll(() => page.evaluate(() => window.fixture.discovered)).toBeGreaterThan(1)
await page.getByRole('button', { name: 'Stop adding files to Spanish batch', exact: true }).click()
await expect(page.locator('#discoveries')).toBeEmpty({ timeout: 10000 })
const finalCalls = await page.evaluate(() => window.fixture.calls)
expect(
  finalCalls.some(
    (call) => call.method === 'DELETE' && call.path === '/v1/desktop/discover/folder-cursor',
  ),
).toBe(true)
expect(
  finalCalls.filter((call) => call.path === '/v1/desktop/submit' && call.body.target === 'es'),
).toHaveLength(1)
await page.setViewportSize({ width: 375, height: 850 })
expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
  true,
)
await page.screenshot({
  path: fileURLToPath(new URL('screenshots/desktop-review-narrow.png', import.meta.url)),
  fullPage: true,
})
await browser.close()
console.log(
  'Desktop UI fixture checks passed: recovery, stable backpressure identity, dismissal, discovery cancellation, keyboard focus and layout.',
)
