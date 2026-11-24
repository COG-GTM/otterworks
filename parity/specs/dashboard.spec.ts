import { test, expect } from '@playwright/test';
import { expectChartsDrawn, signIn, waitForSpinners } from './helpers';

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
  await expect(page.getByText('Document Activity')).toBeVisible();
  await expectChartsDrawn(page, 2);
});
