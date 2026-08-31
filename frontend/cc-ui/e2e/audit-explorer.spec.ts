import { test, expect } from '@playwright/test'

test('certifies authenticated Audit Explorer behavior', async ({ page }) => {
  const requests: string[] = []
  page.on('request', request => {
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      const url = new URL(request.url())
      requests.push(`${request.method()} ${url.pathname}`)
      expect(url.hostname).not.toMatch(/security-audit|mysql|redis/i)
    }
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Audit Explorer', exact: true }).click()
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

  await page.goto('/audit-explorer')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Audit Explorer', exact: true })).toBeVisible()
  expect(requests.some(request => request.includes('/audit/events/safe'))).toBe(true)
  await expect(page.getByRole('button', { name: /delete|edit|replay|acknowledge|resign|mutate|tenant override/i })).toHaveCount(0)
})
