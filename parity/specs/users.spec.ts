import { test, expect, Page } from '@playwright/test';
import { pickOption, signIn, snap, typeFilter, waitForSpinners } from './helpers';

async function openUsers(page: Page) {
  await signIn(page);
  await page.locator('app-sidebar').getByText('Users', { exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'User Management' })).toBeVisible();
  await waitForSpinners(page);
}

const rows = (page: Page) => page.locator('tr.table-row');
const rangeLabel = (page: Page) => page.locator('.mat-mdc-paginator-range-label');

test('users list paginates', async ({ page }) => {
  await openUsers(page);
  await expect(rows(page)).toHaveCount(5);
  const label = await rangeLabel(page).innerText();
  const total = Number(label.split('of')[1].trim());
  expect(total).toBeGreaterThan(5);
  await page.getByRole('button', { name: 'Next page' }).click();
  await expect(rangeLabel(page)).toHaveText(new RegExp(`6 . ${Math.min(10, total)} of ${total}`));
  const last = page.getByRole('button', { name: 'Last page' });
  if (await last.isEnabled()) await last.click();
  await expect(page.getByRole('button', { name: 'Next page' })).toBeDisabled();
  await page.getByRole('button', { name: 'First page' }).click();
  await expect(rangeLabel(page)).toHaveText(new RegExp(`1 . 5 of ${total}`));
});

test('users search, role and status filters', async ({ page }) => {
  await openUsers(page);
  await typeFilter(page, 'Search users', 'carol');
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText('Carol Chen');
  await typeFilter(page, 'Search users', 'no-such-user-zzz');
  await expect(rows(page)).toHaveCount(0);
  await typeFilter(page, 'Search users', '');

  await page.getByRole('combobox', { name: 'Role' }).click();
  await pickOption(page, 'Viewer');
  const viewerCount = await rows(page).count();
  for (let i = 0; i < viewerCount; i++) await expect(rows(page).nth(i)).toContainText(/viewer/i);

  await page.getByRole('combobox', { name: 'Role' }).click();
  await pickOption(page, 'All Roles');
  await page.getByRole('combobox', { name: 'Status' }).click();
  await pickOption(page, 'Suspended');
  const suspended = await rows(page).count();
  for (let i = 0; i < suspended; i++) await expect(rows(page).nth(i)).toContainText(/suspended/i);
});

test('user detail, suspend and restore', async ({ page }, info) => {
  await openUsers(page);
  await typeFilter(page, 'Search users', 'grace.lee');
  await rows(page).first().click();
  await expect(page).toHaveURL(/\/users\/[\w-]+$/);
  await expect(page.getByRole('heading', { level: 1, name: 'User Details' })).toBeVisible();
  await waitForSpinners(page);
  await expect(page.getByRole('heading', { level: 2, name: 'Grace Lee' })).toBeVisible();
  await expect(page.getByText('grace.lee@otterworks.io')).toBeVisible();
  await snap(page, info, '05-user-detail');

  const suspend = page.getByRole('button', { name: /Suspend/ });
  const restore = page.getByRole('button', { name: /Restore/ });
  if (await restore.isVisible()) {
    await restore.click();
    await expect(suspend).toBeVisible();
  }
  await suspend.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
  await expect(suspend).toBeVisible();

  await suspend.click();
  await page.getByRole('dialog').getByRole('button').last().click();
  await expect(page.getByText('User suspended')).toBeVisible();
  await expect(restore).toBeVisible();
  await restore.click();
  await expect(page.getByText('User restored')).toBeVisible();
  await expect(suspend).toBeVisible();

  await page.locator('.page-header').getByRole('button').click();
  await expect(page).toHaveURL(/\/users$/);
});

// Baseline behaviour (kept): a 404 from GET /admin/users/:id leaves the page loading;
// the "User not found" branch is only reached when the API returns an empty body.
test('unknown user never renders a profile', async ({ page }) => {
  await signIn(page);
  await page.goto('/users/00000000-0000-0000-0000-00000000dead');
  await expect(page.getByRole('heading', { level: 1, name: 'User Details' })).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
  await page.locator('.page-header').getByRole('button').click();
  await expect(page).toHaveURL(/\/users$/);
});
