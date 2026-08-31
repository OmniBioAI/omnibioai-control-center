import { test as setup, expect } from '@playwright/test'
import fs from 'node:fs/promises'

const authFile = 'e2e/.auth/admin.json'

setup('authenticate through the Admin Console login form', async ({ page, context }) => {
  const username = process.env.ADMIN_E2E_USERNAME
  const password = process.env.ADMIN_E2E_PASSWORD
  if (!username || !password) {
    throw new Error('Authenticated certification requires ADMIN_E2E_USERNAME and ADMIN_E2E_PASSWORD; no credentials were printed or persisted.')
  }

  await fs.mkdir('e2e/.auth', { recursive: true, mode: 0o700 })
  await page.goto('/')
  await expect(page.getByText('Ecosystem Management Console')).toBeVisible()
  await page.locator('input[type="email"]').fill(username)
  await page.locator('input[type="password"]').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await context.storageState({ path: authFile })
  await fs.chmod(authFile, 0o600)
})
