import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: 'embedded-theme.spec.ts',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: 'line',
  outputDir: '/tmp/n11a-control-playwright-results',
  use: {
    baseURL: 'http://127.0.0.1:4304',
    ...devices['Desktop Chrome'],
    headless: true,
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'VITE_APP_MODE=control npm run dev -- --host 127.0.0.1 --port 4304',
    url: 'http://127.0.0.1:4304',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
