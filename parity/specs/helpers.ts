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

/** Picks a mat-select option and waits for the panel to close before the next interaction. */
export async function pickOption(page: Page, option: string): Promise<void> {
  await page.getByRole('option', { name: option }).click();
  await expect(page.getByRole('listbox')).toHaveCount(0);
}

/** Waits until at least `min` canvases have painted pixels (Chart.js rendered, not just mounted). */
export async function expectChartsDrawn(page: Page, min: number): Promise<void> {
  await expect
    .poll(() =>
      page.locator('canvas').evaluateAll((canvases) =>
        canvases.filter((c) => {
          const canvas = c as HTMLCanvasElement;
          const ctx = canvas.getContext('2d');
          if (!ctx || !canvas.width || !canvas.height) return false;
          const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          for (let i = 3; i < data.length; i += 4) if (data[i]) return true;
          return false;
        }).length,
      ),
    )
    .toBeGreaterThanOrEqual(min);
}

/** Clicks a mat-sort-header twice and checks the visible page re-orders ascending, then descending. */
export async function expectSortsBy(page: Page, header: string, cells: string): Promise<void> {
  const texts = async () => (await page.locator(cells).allInnerTexts()).map((t) => t.trim());
  const sorted = (values: string[], dir: 1 | -1) => [...values].sort((a, b) => (a < b ? -dir : a > b ? dir : 0));
  const headerCell = page.getByRole('columnheader', { name: header });
  await headerCell.click();
  await expect(headerCell).toHaveAttribute('aria-sort', 'ascending');
  await expect.poll(async () => { const v = await texts(); return v.length > 1 && v.join('|') === sorted(v, 1).join('|'); }).toBe(true);
  await headerCell.click();
  await expect(headerCell).toHaveAttribute('aria-sort', 'descending');
  await expect.poll(async () => { const v = await texts(); return v.length > 1 && v.join('|') === sorted(v, -1).join('|'); }).toBe(true);
}
