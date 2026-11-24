import { test, expect } from '@playwright/test';
import { randomPassword, runId, signIn, snap } from './helpers';

test.describe('auth', () => {
  test('login page renders and validates empty submit', async ({ page }, info) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: 'OtterWorks Admin' })).toBeVisible();
    await expect(page.getByText('Sign in to the admin dashboard')).toBeVisible();
    await expect(page.getByAltText('OtterWorks logo')).toBeVisible();
    await snap(page, info, '01-login');

    await page.getByRole('button', { name: 'Sign In' }).click();
    await expect(page.getByText('Please enter both email and password.')).toBeVisible();
    await snap(page, info, '02-login-validation');

    await page.getByLabel('Email').fill(`only-email-${runId}@otterworks.io`);
    await expect(page.getByText('Please enter both email and password.')).toBeHidden();
    await page.getByRole('button', { name: 'Sign In' }).click();
    await expect(page.getByText('Please enter both email and password.')).toBeVisible();
  });

  test('password visibility toggle', async ({ page }) => {
    await page.goto('/login');
    const pwd = page.getByLabel('Password');
    await pwd.fill(randomPassword());
    await expect(pwd).toHaveAttribute('type', 'password');
    await page.locator('mat-form-field', { hasText: 'Password' }).getByRole('button').click();
    await expect(pwd).toHaveAttribute('type', 'text');
  });

  test('protected routes redirect to login when signed out', async ({ page }) => {
    await page.goto('/users');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();
  });

  test('sign in, persist across reload, and sign out', async ({ page }) => {
    await signIn(page);
    await expect(page.getByText('Admin User')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

    await page.goto('/login');
    await expect(page).toHaveURL(/\/$/);

    await page.getByRole('button', { name: 'User menu' }).click();
    await page.getByRole('menuitem', { name: /Logout|Sign out/i }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto('/audit');
    await expect(page).toHaveURL(/\/login$/);
  });
});
