import { test, expect } from '@playwright/test'
import { ADMIN_ROUTES, installDiagnostics, reportDiagnostics } from './helpers/admin'

test('rejects an anonymous deep link', async ({ page, baseURL }, testInfo) => {
  installDiagnostics(page)
  await page.goto(`${baseURL}${ADMIN_ROUTES.integrationHealth}`)
  await expect(page.getByText('Ecosystem Management Console')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Integration Health' })).toHaveCount(0)
  await reportDiagnostics(page, testInfo)
})
