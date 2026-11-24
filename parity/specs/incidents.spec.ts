import { test, expect } from '@playwright/test';
import { pickOption, runId, signIn, snap, waitForSpinners } from './helpers';

// Submitting would launch a real Devin session, so only the form and its validation are checked.
test('incident form validation', async ({ page }, info) => {
  await signIn(page);
  await page.locator('app-sidebar').getByText('Incidents', { exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Incident Response' })).toBeVisible();
  await waitForSpinners(page);

  await page.getByRole('button', { name: /Report Incident|New Incident/ }).first().click();
  await expect(page.getByText('Report New Incident')).toBeVisible();
  const submit = page.getByRole('button', { name: /Create Incident & Launch Devin/ });
  await expect(submit).toBeDisabled();
  await page.getByLabel('Incident Title').fill(`Parity incident ${runId}`);
  await expect(submit).toBeDisabled();
  await page.getByLabel('Description').fill('Form validation check only.');
  await expect(submit).toBeEnabled();
  await page.getByLabel('Severity').click();
  await pickOption(page, 'High');
  await snap(page, info, '14-incident-form');
});
