import { test, expect } from '@playwright/test'
import { ADMIN_ROUTES, installDiagnostics, reportDiagnostics } from './helpers/admin'

test('rejects an anonymous deep link', async ({ page, baseURL }, testInfo) => {
  installDiagnostics(page)
  await page.goto(`${baseURL}${ADMIN_ROUTES.integrationHealth}`)
  await expect(page.getByText('Ecosystem Management Console')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Integration Health' })).toHaveCount(0)
  await reportDiagnostics(page, testInfo)
})

test('serves the Storage page shell without exposing Storage data anonymously', async ({ page, baseURL }) => {
  const pageResponse = await page.goto(`${baseURL}${ADMIN_ROUTES.storage}`)
  expect(pageResponse?.status()).toBe(200)
  expect(pageResponse?.headers()['content-type']).toContain('text/html')
  await expect(page.getByText('Ecosystem Management Console')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Storage & Backup' })).toHaveCount(0)

  const apiResponse = await page.request.get(`${baseURL}/storage/overview`)
  expect(apiResponse.status()).toBe(401)
  expect(apiResponse.headers()['content-type']).toContain('application/json')
})
