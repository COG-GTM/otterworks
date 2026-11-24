import { test, expect } from '@playwright/test';
import { signIn, snap, waitForSpinners } from './helpers';

const pages = [
  { label: 'Dashboard', path: '/', heading: 'Dashboard', shot: '03-dashboard' },
  { label: 'Users', path: '/users', heading: 'User Management', shot: '04-users' },
  { label: 'Audit Logs', path: '/audit', heading: 'Audit Logs', shot: '06-audit' },
  { label: 'Feature Flags', path: '/features', heading: 'Feature Flags', shot: '07-features' },
  { label: 'System Health', path: '/health', heading: 'System Health', shot: '08-health' },
  { label: 'Announcements', path: '/announcements', heading: 'Announcements', shot: '09-announcements' },
  { label: 'Storage Quotas', path: '/quotas', heading: 'Storage Quotas', shot: '10-quotas' },
  { label: 'Incidents', path: '/incidents', heading: 'Incident Response', shot: '11-incidents' },
  { label: 'Analytics', path: '/analytics', heading: 'Analytics', shot: '12-analytics' },
];

test('sidebar lists every section and navigates to each page', async ({ page }, info) => {
  await signIn(page);
  const nav = page.locator('app-sidebar');
  for (const p of pages) {
    await expect(nav.getByText(p.label, { exact: true })).toBeVisible();
  }
  for (const p of pages) {
    await nav.getByText(p.label, { exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${p.path === '/' ? '/' : p.path}$`));
    await expect(page.getByRole('heading', { level: 1, name: p.heading })).toBeVisible();
    await waitForSpinners(page);
    await snap(page, info, p.shot);
  }
});

test('sidebar collapses and expands', async ({ page }) => {
  await signIn(page);
  const nav = page.locator('app-sidebar');
  await expect(nav.getByText('Audit Logs', { exact: true })).toBeVisible();
  await nav.getByRole('button').first().click();
  await expect(nav.getByText('Audit Logs', { exact: true })).toBeHidden();
  await nav.getByRole('button').first().click();
  await expect(nav.getByText('Audit Logs', { exact: true })).toBeVisible();
});

test('unknown route redirects to dashboard', async ({ page }) => {
  await signIn(page);
  await page.goto('/does-not-exist');
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
});
