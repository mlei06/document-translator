import { test, expect, type Page } from '@playwright/test'
test.beforeEach(async ({ page }, info) => {
  await page.setExtraHTTPHeaders({ 'X-Test-Client': info.testId })
})
async function signIn(page: Page, name = 'Alice') {
  const keys = await (
    await page.request.get(`/test/credentials?scope=${encodeURIComponent(test.info().testId)}`)
  ).json()
  await page.goto('/')
  await page.getByRole('button', { name: 'Use an access key', exact: true }).click()
  await page.getByLabel('Access key', { exact: true }).fill(keys[name])
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: `Account: ${name}` })).toBeVisible()
}
const sample = (name: string) => ({
  name,
  mimeType: 'text/plain',
  buffer: Buffer.from('Hello world. This document contains English text and 中文内容。'),
})

test('saved Chinese default translates dropped files without asking again', async ({ page }) => {
  await signIn(page)
  await page.getByRole('button', { name: 'Lenny', exact: true }).click()
  await page.getByRole('menuitem', { name: /settings/i }).click()
  await page.getByLabel('Default language', { exact: true }).selectOption('zh')
  await page.getByRole('button', { name: 'Done', exact: true }).click()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Lenny', exact: true })).toBeVisible()
  const submissions: Record<string, unknown>[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/translations') && request.method() === 'POST')
      submissions.push(request.postDataJSON())
  })
  const files = await page.evaluateHandle(() => {
    const data = new DataTransfer()
    data.items.add(
      new File(
        ['Hello world. This document should translate automatically.'],
        'default-chinese.txt',
        { type: 'text/plain' },
      ),
    )
    return data
  })
  await page
    .locator('#stage')
    .dispatchEvent('drop', { dataTransfer: files, clientX: 500, clientY: 450 })
  await expect(page.getByRole('group', { name: 'Translate into' })).toHaveCount(0)
  await expect(page.locator('#speech')).not.toContainText('What language')
  await expect.poll(() => submissions.length).toBe(1)
  expect(submissions[0]?.target).toBe('zh')
  await expect(
    page.getByRole('button', { name: 'Download default-chinese.txt', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Lenny', exact: true }).click()
  await page.getByRole('menuitem', { name: /settings/i }).click()
  await page.getByLabel('Default language', { exact: true }).selectOption('')
  await page.getByRole('button', { name: 'Done', exact: true }).click()
  await page.locator('#picker').setInputFiles(sample('ask-again.txt'))
  await expect(page.getByRole('group', { name: 'Translate into' })).toBeVisible()
  expect(submissions).toHaveLength(1)
  await page.getByRole('button', { name: 'Translate to Japanese', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(2)
  expect(submissions[1]?.target).toBe('ja')
})

test('unfinished orb asks for patience, ready orb downloads and small x dismisses', async ({
  page,
}, info) => {
  await signIn(page)
  await page.locator('#picker').setInputFiles(sample('patience.txt'))
  await page.getByRole('button', { name: 'Translate to Chinese', exact: true }).click()
  const bubble = page.getByRole('article', { name: 'patience.txt' })
  await bubble.getByRole('button', { name: 'Check progress for patience.txt' }).click()
  await expect(page.locator('#speech')).toContainText('Please wait')
  await expect(page.locator('#lennyBtn .lenny')).toHaveClass(/annoyed/)
  await page.screenshot({ path: info.outputPath('annoyed-lenny.png'), animations: 'disabled' })
  await expect(bubble.locator('.row-actions')).toHaveCount(0)
  await expect(page.locator('.translation-bubbles')).toHaveCSS('overflow', 'visible')
  const download = page.waitForEvent('download')
  await bubble.getByRole('button', { name: 'Download patience.txt', exact: true }).click()
  expect((await download).suggestedFilename()).toContain('patience')
  await expect(page.locator('#lennyBtn .lenny')).not.toHaveClass(/annoyed/)
  await bubble.hover()
  await bubble.getByRole('button', { name: 'Dismiss patience.txt' }).click()
  await expect(bubble).toHaveCount(0)
})

test('meadow stays anchored with a full tummy and file icons', async ({ page }, info) => {
  await signIn(page)
  await page
    .locator('#picker')
    .setInputFiles(Array.from({ length: 12 }, (_, i) => sample(`notes-${i}.txt`)))
  const before = await page.locator('#lennyBtn').boundingBox()
  await page.mouse.move(600, 500)
  await page.mouse.wheel(0, 800)
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  expect(await page.locator('#lennyBtn').boundingBox()).toEqual(before)
  await expect(page.locator('#tummy')).toContainText('12')
  await expect(page.locator('.tummy-files')).not.toBeVisible()
  await page.screenshot({ path: info.outputPath('restored-tummy.png'), animations: 'disabled' })
  await page.locator('#tummy').click()
  await expect(page.getByRole('region', { name: 'Uploads' })).toBeVisible()
  await expect(page.locator('.tummy-files .ficon')).toHaveCount(12)
  await page.screenshot({ path: info.outputPath('expanded-tummy.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(page.locator('.tummy-files')).not.toBeVisible()
  await expect(page.locator('#tummy')).toBeFocused()
  await page.getByRole('button', { name: 'Translate to Chinese', exact: true }).click()
  await expect(page.locator('.bubble-open[data-ready]')).toHaveCount(12)
  await page.screenshot({ path: info.outputPath('restored-bubbles.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 1024, height: 720 })
  const firstPageIds = await page
    .locator('.translation-bubble:visible')
    .evaluateAll((els) => els.map((el) => el.getAttribute('data-job-id')))
  await page.getByRole('button', { name: 'Next bubbles' }).click()
  const nextPageIds = await page
    .locator('.translation-bubble:visible')
    .evaluateAll((els) => els.map((el) => el.getAttribute('data-job-id')))
  expect(new Set([...firstPageIds, ...nextPageIds]).size).toBe(12)
  await page.setViewportSize({ width: 375, height: 812 })
  await expect(page.locator('.translation-bubbles')).toHaveCSS('flex-wrap', 'nowrap')
  await expect(page.locator('.translation-bubbles')).toHaveCSS('scrollbar-width', 'none')
  const strip = await page.locator('.translation-bubbles').boundingBox()
  const mascot = await page.locator('#lennyBtn').boundingBox()
  expect(strip!.y).toBeGreaterThan(mascot!.y + mascot!.height)
  await page.locator('.bubble-open').last().focus()
  await expect(page.locator('.bubble-open').last()).toBeInViewport()
  await page.locator('.bubble-open').first().focus()
  await page.screenshot({ path: info.outputPath('restored-mobile.png'), animations: 'disabled' })
  await expect(page.locator('#lennyBtn')).toBeInViewport()
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  // Visual stress fixture: identical source uploads share one real History grant.
  // Real download/delete authorization is covered by the lifecycle test below.
  await page.route('**/v1/history?*', (route) =>
    route.fulfill({
      json: {
        items: Array.from({ length: 12 }, (_, i) => ({
          id: `layout-${i}`,
          original_name: `${i + 1}-${['Sales-deck.pptx', 'A-long-vendor-agreement-with-regional-details.docx', 'Pricing.xlsx', 'Manual.pdf'][i % 4]}`,
          source: 'en',
          target: 'zh',
          status: 'succeeded',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          available: i !== 11,
        })),
        next_cursor: null,
      },
    }),
  )
  await page.getByRole('button', { name: 'Open History', exact: true }).click()
  await expect(page.locator('.history-entries li')).toHaveCount(12)
  await page.screenshot({ path: info.outputPath('history-mobile.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 1440, height: 900 })
  const historyRows = await page
    .locator('.history-entries li')
    .evaluateAll((rows) => rows.map((row) => row.getBoundingClientRect().height))
  expect(Math.max(...historyRows)).toBeLessThan(90)
  await page.screenshot({ path: info.outputPath('history-desktop.png'), animations: 'disabled' })
  await expect(
    page
      .locator('.history-actions button')
      .filter({ has: page.locator('svg') })
      .last(),
  ).toBeEnabled()
  await expect(
    page.getByRole('button', { name: 'Download 12-Manual.pdf', exact: true }),
  ).toBeDisabled()
  await page.getByRole('button', { name: 'Remove from History', exact: true }).first().click()
  await expect(page.locator('.history-confirm')).toHaveCount(1)
  await page.getByRole('button', { name: 'Keep entry', exact: true }).click()
  await page.getByRole('button', { name: 'Close History', exact: true }).click()
})

test('Lenny eats dropped files and keeps a working sample menu', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await signIn(page)
  const files = await page.evaluateHandle(() => {
    const data = new DataTransfer()
    data.items.add(
      new File(['Hello world. A document to translate.'], 'feeding.txt', { type: 'text/plain' }),
    )
    return data
  })
  await page
    .locator('#stage')
    .dispatchEvent('dragover', { dataTransfer: files, clientX: 500, clientY: 450 })
  await expect(page.locator('body')).toHaveClass(/dragging/)
  await expect(page.locator('#speech')).toContainText('Drop it in')
  await page
    .locator('#stage')
    .dispatchEvent('drop', { dataTransfer: files, clientX: 500, clientY: 450 })
  await expect(page.locator('.flycard')).toBeVisible()
  await expect(page.locator('.flycard')).toHaveCount(0)
  await expect(page.locator('#tummy')).toContainText('1 in my tummy')
  await expect(page.locator('body')).not.toHaveClass(/dragging/)
  await page.getByRole('button', { name: 'Lenny', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Feed me sample files' }).click()
  await expect(page.locator('#tummy')).toContainText('6 in my tummy')
  await page.locator('#tummy').click()
  await expect(
    page.locator('.tummy-files').getByRole('img', { name: 'PowerPoint', exact: true }),
  ).toBeVisible()
})
test('email registration and password sessions remain usable without translation settings', async ({
  page,
}) => {
  const email = `browser-${Date.now()}@example.com`
  await page.goto('/')
  await page.getByRole('button', { name: 'Create an account', exact: true }).click()
  await page.locator('#display-name').fill('Email User')
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill('Browser-test-password-2026')
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Account: Email User' })).toBeVisible()
  await page.getByRole('button', { name: 'Account: Email User' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill('Browser-test-password-2026')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Account: Email User' })).toBeVisible()
  await page.locator('#picker').setInputFiles(sample('email-account.txt'))
  await page.getByRole('button', { name: 'Translate to English', exact: true }).click()
  await expect(page.locator('.bubble-open[data-ready]')).toBeVisible()
})
test('logout fences pending uploads before a replacement account signs in', async ({ page }) => {
  await signIn(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/v1/documents?staging=true', async (route) => {
    await gate
    await route.continue().catch(() => {})
  })
  let submissions = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/translations')) submissions++
  })
  await page.locator('#picker').setInputFiles(sample('alice-pending.txt'))
  await page.getByRole('button', { name: 'Translate to English', exact: true }).click()
  await page.getByRole('button', { name: 'Account: Alice' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  release()
  await signIn(page, 'Bob')
  await page.getByRole('button', { name: 'History', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('No translations yet.')
  expect(submissions).toBe(0)
})
test('only Lenny follows the pointer', async ({ page }) => {
  await signIn(page)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  for (const x of [10, 1270]) {
    await page.mouse.move(x, 360)
    await expect
      .poll(async () => {
        const transform = await page.locator('#lennyBtn .l-face').getAttribute('transform')
        const offset = Number(transform?.match(/translate\(([-\d.]+)/)?.[1])
        return x < 640 ? offset < 0 : offset > 0
      })
      .toBe(true)
    for (const selector of ['.w-ground', '#motes', '#wClouds'])
      await expect(page.locator(selector)).toHaveCSS('transform', 'none')
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
  const still = await page.locator('#lennyBtn .l-face').getAttribute('transform')
  await page.mouse.move(10, 100)
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
  await expect(page.locator('#lennyBtn .l-face')).toHaveAttribute('transform', still!)
})
test('slow uploads pin one target, early files start independently and later drops form a new draft', async ({
  page,
}) => {
  await signIn(page)
  let release!: () => void
  const gate = new Promise<void>((r) => {
    release = r
  })
  await page.route('**/v1/documents?staging=true', async (route) => {
    if (route.request().postData()?.includes('slow.txt')) await gate
    await route.continue()
  })
  const submissions: Record<string, unknown>[] = []
  const previews: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/preview')) previews.push(request.url())
    if (request.url().endsWith('/translations') && request.method() === 'POST')
      submissions.push(request.postDataJSON())
  })
  await page.locator('#picker').setInputFiles([sample('fast.txt'), sample('slow.txt')])
  await page.getByRole('button', { name: 'Translate to English', exact: true }).click()
  await page.locator('#tummy').click()
  await expect(page.getByRole('region', { name: 'Uploads' })).toContainText('To English')
  await page.keyboard.press('Escape')
  await expect.poll(() => submissions.length).toBe(1)
  await page.locator('#picker').setInputFiles(sample('later.txt'))
  await expect(
    page.getByRole('button', { name: 'Translate to Japanese', exact: true }),
  ).toBeVisible()
  release()
  await expect.poll(() => submissions.length).toBe(2)
  expect(
    submissions.every(
      (s) => s.target === 'en' && s.selection_policy === 'website_auto' && !('source' in s),
    ),
  ).toBeTruthy()
  await page.getByRole('button', { name: 'Translate to Japanese', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(3)
  expect(submissions[2]?.target).toBe('ja')
  await expect(page.locator('.bubble-open[data-ready]')).toHaveCount(3)
  await page.screenshot({
    path: test.info().outputPath('ready-results.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await expect(page.locator('select[aria-label^="Source language"]')).toHaveCount(0)
  await expect(page.getByText('Checking layout', { exact: true })).toHaveCount(0)
  expect(previews).toEqual([])
})
test('direct download, private history, cancellation and dismissal use the real service', async ({
  page,
}) => {
  await signIn(page)
  await page.locator('#picker').setInputFiles(sample('private.txt'))
  await page.getByRole('button', { name: 'Translate to Chinese', exact: true }).click()
  const bubble = page.getByRole('article', { name: 'private.txt' })
  await expect(bubble.getByRole('button', { name: /^Download / })).toBeVisible()
  const downloaded = page.waitForEvent('download')
  await bubble.getByRole('button', { name: /^Download / }).click()
  expect((await downloaded).suggestedFilename()).toContain('.txt')
  await expect(page.locator('#preview')).toHaveCount(0)
  await bubble.getByRole('button', { name: /^Dismiss / }).click()
  await expect(bubble).toHaveCount(0)
  await page.getByRole('button', { name: 'History', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('private.txt')
  await expect(page.getByRole('dialog').getByRole('button', { name: /^Download / })).toBeVisible()
  const owned = await (await page.request.get('/v1/history')).json()
  const bobContext = await page.context().browser()!.newContext()
  const bobPage = await bobContext.newPage()
  await signIn(bobPage, 'Bob')
  const denied = await bobPage.request.get(`/v1/history/${owned.items[0].id}/file`)
  expect(denied.status()).toBe(404)
  await bobContext.close()
  await page.getByRole('button', { name: 'Remove from History' }).click()
  await page.getByRole('button', { name: 'Remove entry', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toContainText('private.txt')
  await page.getByRole('button', { name: 'Close History' }).click()
  await page.getByRole('button', { name: 'Account: Alice' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await signIn(page, 'Bob')
  await page.getByRole('button', { name: 'History', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toContainText('private.txt')
})
test('upload failure retries only that file and cancellation prevents admission', async ({
  page,
}) => {
  await signIn(page)
  let failed = false
  await page.route('**/v1/documents?staging=true', async (route) => {
    if (!failed && route.request().postData()?.includes('retry.txt')) {
      failed = true
      await route.abort()
      return
    }
    await route.continue()
  })
  await page.locator('#picker').setInputFiles([sample('retry.txt'), sample('good.txt')])
  await expect(page.getByRole('region', { name: 'Uploads' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Failed')
  await page.getByRole('button', { name: 'Retry retry.txt', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Translate to Spanish', exact: true }).click()
  await expect(page.locator('.bubble-open[data-ready]')).toHaveCount(2)
  let release!: () => void
  const gate = new Promise<void>((r) => {
    release = r
  })
  await page.route('**/v1/documents?staging=true', async (route) => {
    await gate
    await route.continue().catch(() => {})
  })
  await page.locator('#picker').setInputFiles(sample('cancel.txt'))
  await page.locator('#tummy').click()
  await page.getByRole('button', { name: 'Cancel cancel.txt', exact: true }).click()
  release()
  await expect(page.getByRole('article', { name: 'cancel.txt' })).toHaveCount(0)
})
test('responsive themes preserve anchored meadow, readable controls and keyboard access', async ({
  page,
}, info) => {
  await signIn(page)
  for (const width of [1440, 768, 375, 320])
    for (const theme of ['light', 'dark']) {
      await page.setViewportSize({ width, height: width === 768 ? 450 : 900 })
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t
      }, theme)
      await page
        .locator('#picker')
        .setInputFiles(sample(`A-long-document-name-with-details-${width}-${theme}.txt`))
      await expect(
        page.getByRole('button', { name: 'Translate to English', exact: true }),
      ).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({
        path: info.outputPath(`${width}-${theme}.png`),
        fullPage: true,
        animations: 'disabled',
      })
      await page.locator('#tummy').click()
      await expect(page.getByRole('region', { name: 'Uploads' })).toBeInViewport({ ratio: 1 })
      await page.screenshot({
        path: info.outputPath(`${width}-${theme}-files.png`),
        animations: 'disabled',
      })
      await page.keyboard.press('Escape')
    }
  await page.evaluate(() => {
    document.documentElement.style.zoom = '2'
  })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Open History', exact: true }).focus()
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe('BODY')
  await expect(page.locator(':focus')).toBeVisible()
  expect(
    await page
      .locator(':focus')
      .evaluate((element) => parseFloat(getComputedStyle(element).outlineWidth)),
  ).toBeGreaterThan(0)
  const focusBox = await page.locator(':focus').boundingBox()
  expect(focusBox!.x).toBeGreaterThanOrEqual(0)
  expect(focusBox!.x + focusBox!.width).toBeLessThanOrEqual(320)
  await page.screenshot({
    path: info.outputPath('200-percent-keyboard.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.locator('#tummy').click()
  await expect(page.getByRole('region', { name: 'Uploads' })).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: info.outputPath('200-percent-files.png'), animations: 'disabled' })
  expect((await page.locator('.tummy-files li > b').first().boundingBox())!.width).toBeGreaterThan(
    100,
  )
  await page.keyboard.press('Escape')
  for (const selector of ['.w-ground', '#motes', '#wClouds'])
    await expect(page.locator(selector)).toHaveCSS('transform', 'none')
})
