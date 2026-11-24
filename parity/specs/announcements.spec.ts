import { test, expect } from '@playwright/test';
import { runId, signIn, snap, waitForSpinners } from './helpers';

test('create, publish and delete an announcement', async ({ page }, info) => {
  const title = `Parity ${info.project.name} ${runId}`;
  await signIn(page);
  await page.locator('app-sidebar').getByText('Announcements', { exact: true }).click();
  await waitForSpinners(page);

  await page.getByRole('button', { name: /New Announcement/ }).click();
  const create = page.getByRole('button', { name: /Create|Save/ }).last();
  await expect(create).toBeDisabled();
  await page.getByLabel('Title').fill(title);
  await expect(create).toBeDisabled();
  await page.getByLabel('Content').fill('Automated parity check announcement.');
  await expect(create).toBeEnabled();
  await snap(page, info, '13-announcement-form');
  await create.click();
  await expect(page.getByText('Announcement created')).toBeVisible();

  const card = page.locator('.announcement-card', { hasText: title });
  await expect(card).toBeVisible();
  await expect(card).toContainText(/draft/i);
  await card.getByRole('button', { name: 'Publish' }).click();
  await expect(page.getByText('Announcement published')).toBeVisible();
  await expect(page.locator('.announcement-card', { hasText: title })).toContainText(/published/i);

  await page.locator('.announcement-card', { hasText: title }).getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('dialog').getByRole('button').last().click();
  await expect(page.getByText('Announcement deleted')).toBeVisible();
  await expect(page.locator('.announcement-card', { hasText: title })).toHaveCount(0);
});
