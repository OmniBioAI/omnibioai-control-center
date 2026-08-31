import { expect, type Page, type TestInfo } from '@playwright/test'

const diagnosticsByPage = new WeakMap<Page, { consoleErrors: string[]; requestFailures: string[] }>()

export const ADMIN_ROUTES = {
  overview: '/',
  regressionHealth: '/regression-health',
  deploymentHealth: '/deployment-health',
  integrationHealth: '/integration-health',
  securityPosture: '/security-posture',
  workflows: '/workflows',
  auditExplorer: '/audit-explorer',
} as const

export async function expectAuthenticatedShell(page: Page) {
  await expect(page.locator('aside[role="complementary"], aside').first()).toBeVisible()
  await expect(page.getByText('Admin Console', { exact: true }).first()).toBeVisible()
  const profile = page.locator('header button').filter({ hasText: /@/ }).first()
  await expect(profile).toBeVisible()
  await profile.click()
  await expect(page.getByRole('button', { name: /Sign out/i })).toBeVisible()
  await profile.click({ force: true })
}

export async function visitFromSidebar(page: Page, label: string, heading: string) {
  await page.getByRole('button', { name: label, exact: true }).click()
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
}

export async function certifyDeepLink(page: Page, path: string, heading: string) {
  await page.goto(path)
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
}

export function installDiagnostics(page: Page) {
  const consoleErrors: string[] = []
  const requestFailures: string[] = []
  diagnosticsByPage.set(page, { consoleErrors, requestFailures })
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('requestfailed', request => {
    const url = new URL(request.url())
    requestFailures.push(`${request.method()} ${url.pathname}: ${request.failure()?.errorText ?? 'failed'}`)
  })
}

export async function reportDiagnostics(page: Page, testInfo: TestInfo) {
  const diagnostics = diagnosticsByPage.get(page) ?? { consoleErrors: [], requestFailures: [] }
  await testInfo.attach('browser-diagnostics', {
    body: JSON.stringify(diagnostics, null, 2),
    contentType: 'application/json',
  })
  expect(diagnostics.consoleErrors, 'unexpected browser console errors').toEqual([])
  expect(diagnostics.requestFailures, 'unexpected failed browser requests').toEqual([])
}
