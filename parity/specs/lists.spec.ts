import { test, expect, Page } from '@playwright/test';
import { expectChartsDrawn, expectSortsBy, pickOption, signIn, typeFilter, waitForSpinners } from './helpers';

async function open(page: Page, label: string, heading: string) {
  await signIn(page);
  await page.locator('app-sidebar').getByText(label, { exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
  await waitForSpinners(page);
}

test('audit logs paginate and filter', async ({ page }) => {
  await open(page, 'Audit Logs', 'Audit Logs');
  const rows = page.locator('table[mat-table] tbody tr');
  await expect(rows).toHaveCount(10);
  const label = page.locator('.mat-mdc-paginator-range-label');
  await expect(label).toHaveText(/1 . 10 of \d+/);
  await expectSortsBy(page, 'Action', 'table[mat-table] tbody tr td.mat-column-action');
  await page.getByRole('button', { name: 'Next page' }).click();
  await expect(label).toHaveText(/11 . \d+ of \d+/);

  await typeFilter(page, 'Search audit events', 'zzz-no-match-zzz');
  await expect(page.locator('tr.mat-mdc-row')).toHaveCount(0);
  await typeFilter(page, 'Search audit events', '');

  await page.getByLabel('Severity').click();
  await pickOption(page, 'Warning');
  await expect(rows.first()).toBeVisible();
  const n = await rows.count();
  for (let i = 0; i < n; i++) await expect(rows.nth(i)).toContainText(/warning/i);
});

test('feature flags search and toggle', async ({ page }) => {
  await open(page, 'Feature Flags', 'Feature Flags');
  const cards = page.locator('.flag-card');
  const total = await cards.count();
  expect(total).toBeGreaterThan(0);

  await page.getByLabel('Search features').fill('zzz-no-match');
  await expect(cards).toHaveCount(0);
  await expect(page.getByText('No feature flags match your search')).toBeVisible();
  await page.getByLabel('Search features').fill('');
  await expect(cards).toHaveCount(total);

  // The page does not update flag.enabled after a successful PUT (baseline bug, kept), so a second
  // click without a reload re-sends the same state. Toggle once, reload, then toggle back.
  const flagSwitch = () => page.locator('.flag-card').filter({ hasText: 'beta_export_pipeline' }).first().getByRole('switch');
  const before = await flagSwitch().getAttribute('aria-checked');
  const flipped = before === 'true' ? 'false' : 'true';
  const put = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().includes('/admin/features/'));
  await flagSwitch().click();
  expect((await put).ok()).toBeTruthy();
  await expect(flagSwitch()).toHaveAttribute('aria-checked', flipped);
  await page.reload();
  await waitForSpinners(page);
  await expect(flagSwitch()).toHaveAttribute('aria-checked', flipped);
  const putBack = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().includes('/admin/features/'));
  await flagSwitch().click();
  expect((await putBack).ok()).toBeTruthy();
  await page.reload();
  await waitForSpinners(page);
  await expect(flagSwitch()).toHaveAttribute('aria-checked', before!);
});

test('system health summary and refresh', async ({ page }) => {
  await open(page, 'System Health', 'System Health');
  for (const l of ['Healthy', 'Degraded', 'Down']) await expect(page.locator('.summary-card', { hasText: l })).toBeVisible();
  const services = page.locator('.service-card');
  const n = await services.count();
  expect(n).toBeGreaterThan(0);
  const counts = await page.locator('.summary-count').allInnerTexts();
  expect(counts.map(Number).reduce((a, b) => a + b, 0)).toBe(n);
  await page.getByRole('button', { name: /Refresh/ }).click();
  await waitForSpinners(page);
  await expect(services).toHaveCount(n);
});

test('storage quotas list and search', async ({ page }) => {
  await open(page, 'Storage Quotas', 'Storage Quotas');
  const rows = page.locator('table[mat-table] tbody tr');
  await expect(rows).toHaveCount(5);
  await expectSortsBy(page, 'User', 'table[mat-table] tbody tr .user-name');
  await typeFilter(page, 'Search users', 'james');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('James Park');
  await expect(rows.first()).toContainText(/\d+%/);
});

test('analytics renders all charts', async ({ page }) => {
  await open(page, 'Analytics', 'Analytics');
  const titles = ['Active Users Over Time', 'Storage Usage (TB)', 'Top File Types', 'User Signups (Monthly)', 'Peak Usage Hours'];
  for (const t of titles) {
    await expect(page.getByText(t, { exact: true })).toBeVisible();
  }
  await expect(page.locator('canvas')).toHaveCount(titles.length);
  // The seed has no file-type data, so the Top File Types pie stays blank on both apps.
  await expectChartsDrawn(page, titles.length - 1);
});
