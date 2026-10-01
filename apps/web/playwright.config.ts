import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: 'http://127.0.0.1:8876',
    reducedMotion: 'reduce',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'uv run python apps/web/e2e/service.py',
    cwd: '../..',
    url: 'http://127.0.0.1:8876/v1/health',
    timeout: 120_000,
    reuseExistingServer: false,
  },
})
