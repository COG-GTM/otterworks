import { expect, Page, TestInfo } from '@playwright/test';
import { randomBytes } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

export const runId = `${Date.now()}`;
export const randomPassword = () => randomBytes(12).toString('base64url');

export async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(`parity-${runId}@otterworks.io`);
  await page.getByLabel('Password').fill(randomPassword());
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
}

export async function waitForSpinners(page: Page): Promise<void> {
  await expect(page.locator('mat-spinner, mat-progress-spinner')).toHaveCount(0, { timeout: 15_000 });
}

/** Full-page screenshot under report/shots/<project>/<name>.png, composed side by side later. */
export async function snap(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const dir = path.join(__dirname, '..', 'report', 'shots', testInfo.project.name);
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(800); // let chart/material animations settle
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true, animations: 'disabled', caret: 'hide' });
}

/** The list pages filter on (keyup), which Playwright's fill() does not fire. */
export async function typeFilter(page: Page, label: string, value: string): Promise<void> {
  const input = page.getByLabel(label);
  await input.fill(value);
  await input.press('End');
}
