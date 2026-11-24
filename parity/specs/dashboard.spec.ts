import { test, expect } from '@playwright/test';
import { signIn, waitForSpinners } from './helpers';

test('dashboard shows the four stat cards and charts', async ({ page }) => {
  await signIn(page);
  await waitForSpinners(page);
  for (const label of ['Total Users', 'Active Documents', 'Storage Used', 'Active Sessions']) {
    await expect(page.locator('.stat-card', { hasText: label })).toBeVisible();
  }
  const totalUsers = page.locator('.stat-card', { hasText: 'Total Users' }).locator('.stat-value');
  await expect(totalUsers).toHaveText(/^\d[\d,]*$/);
  expect(Number((await totalUsers.innerText()).replace(/,/g, ''))).toBeGreaterThan(0);
  await expect(page.getByText('User Signups')).toBeVisible();
  expect(await page.locator('canvas').count()).toBeGreaterThan(0);
});
