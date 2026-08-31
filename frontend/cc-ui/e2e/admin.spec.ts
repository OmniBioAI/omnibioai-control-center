import { test, expect } from '@playwright/test'
import { ADMIN_ROUTES, certifyDeepLink, expectAuthenticatedShell, installDiagnostics, reportDiagnostics, visitFromSidebar } from './helpers/admin'

test.beforeEach(async ({ page }, testInfo) => {
  testInfo.annotations.push({ type: 'safety', description: 'Read-only browser certification; no mutation controls are clicked.' })
  installDiagnostics(page)
  await page.goto(ADMIN_ROUTES.overview)
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
})

test.afterEach(async ({ page }, testInfo) => {
  // Setup/login traffic is in a separate project. No request headers,
  // cookies, tokens, or request bodies are recorded here.
  await reportDiagnostics(page, testInfo)
})

test('certifies the authenticated landing page and stable sidebar entries', async ({ page }) => {
  await expectAuthenticatedShell(page)
  for (const [label, heading] of [
    ['Health', 'Health Dashboard'],
    ['Regression Health', 'Regression Health'],
    ['Deployment Health', 'Deployment Health'],
    ['Integration Health', 'Integration Health'],
    ['Security Posture', 'Security Posture'],
    ['Workflows', 'Workflows'],
  ] as const) {
    await visitFromSidebar(page, label, heading)
  }
})

test('certifies Integration Health user-visible data and availability', async ({ page }) => {
  await visitFromSidebar(page, 'Integration Health', 'Integration Health')
  await expect(page.getByRole('heading', { name: 'Readiness Summary' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Evidence / Data Sources' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Biological / Data Integrations' })).toBeVisible()
  await expect(page.getByText('Integration Health unavailable.')).toHaveCount(0)
  await expect(page.locator('table').last()).toBeVisible()
  const shown = page.getByText(/^\d+ of \d+ shown$/).first()
  await expect(shown).toBeVisible()
  const count = Number((await shown.textContent())?.match(/of (\d+)/)?.[1] ?? 0)
  expect(count, 'integration inventory must be populated').toBeGreaterThan(0)
})

test('certifies supported direct links and hard refreshes with the session intact', async ({ page }) => {
  for (const [path, heading] of [
    [ADMIN_ROUTES.overview, 'Overview'],
    [ADMIN_ROUTES.regressionHealth, 'Regression Health'],
    [ADMIN_ROUTES.deploymentHealth, 'Deployment Health'],
    [ADMIN_ROUTES.integrationHealth, 'Integration Health'],
    [ADMIN_ROUTES.securityPosture, 'Security Posture'],
    [ADMIN_ROUTES.workflows, 'Workflows'],
    [ADMIN_ROUTES.auditExplorer, 'Audit Explorer'],
  ] as const) {
    await certifyDeepLink(page, path, heading)
  }
})

test('certifies read-only Workflow Operations entry without executing a run', async ({ page }) => {
  await visitFromSidebar(page, 'Workflows', 'Workflows')
  await expect(page.getByText(/No workflow (runs recorded yet|registered yet)|Permission denied|Loading workflows/).first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Workflows', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^(Run|Execute|Launch|Delete|Disable|Enable)(\s|$)/i })).toHaveCount(0)
})

test('preserves Workflows through browser Back and Forward history', async ({ page }) => {
  await page.goto(ADMIN_ROUTES.workflows)
  await expect(page.getByRole('heading', { name: 'Workflows', exact: true })).toBeVisible()
  await page.goto(ADMIN_ROUTES.auditExplorer)
  await expect(page.getByRole('heading', { name: 'Audit Explorer', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Workflows', exact: true })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Audit Explorer', exact: true })).toBeVisible()
})

test('certifies populated Audit Explorer, detail, filtering, and deep-link refresh', async ({ page }) => {
  const requests: string[] = []
  page.on('request', request => {
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      const url = new URL(request.url())
      requests.push(`${request.method()} ${url.pathname}`)
      expect(url.hostname).not.toMatch(/security-audit|mysql|redis/i)
    }
  })

  await page.goto(ADMIN_ROUTES.auditExplorer)
  await expect(page.getByRole('heading', { name: 'Audit Explorer', exact: true })).toBeVisible()
  await expect(page.getByText('AVAILABLE', { exact: true })).toBeVisible()
  await expect(page.getByText('UNKNOWN', { exact: true }).first()).toBeVisible()
  await expect(page.locator('table tbody tr')).not.toHaveCount(0)
  await expect(page.locator('table tbody tr').first().locator('td').nth(7)).toHaveText(/valid|invalid|unsigned|unknown/i)
  await expect(page.getByRole('button', { name: /Next/ })).toBeVisible()
  await page.getByRole('button', { name: /Next/ }).click()
  await expect(page.getByText(/Page 2 of/)).toBeVisible()

  await page.getByRole('button', { name: 'View', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Event detail', exact: true })).toBeVisible()
  await expect(page.getByText(/Raw context and signing material are never available/)).toBeVisible()

  const waitForSafe200 = () => page.waitForResponse(response => response.url().includes('/audit/events/safe') && response.status() === 200)
  await Promise.all([waitForSafe200(), page.getByLabel('Decision').fill('allow')])
  await Promise.all([waitForSafe200(), page.getByLabel('Integrity').selectOption('valid')])
  await Promise.all([waitForSafe200(), page.getByLabel('Organization').selectOption({ index: 1 })])
  await Promise.all([waitForSafe200(), page.getByRole('button', { name: 'Clear', exact: true }).click()])

  await Promise.all([waitForSafe200(), page.getByLabel('Event type').fill(`no-such-event-${Date.now()}`)])
  await expect(page.getByText('AVAILABLE · 0 matching events', { exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Audit Explorer', exact: true })).toBeVisible()
  expect(requests.some(request => request.includes('/audit/events/safe'))).toBe(true)
  expect(await page.getByRole('button', { name: /delete|edit|replay|acknowledge|resign|mutate|tenant override/i }).count()).toBe(0)
})
