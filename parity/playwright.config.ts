import { defineConfig, devices } from '@playwright/test';

// The same specs run against the baseline (default branch, :4000) and the upgraded app (:4200).
// Both apps proxy /api to the same admin-service, so specs run serially and clean up after themselves.
export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['json', { outputFile: 'report/results.json' }]],
  use: {
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'baseline', use: { baseURL: process.env.BASELINE_URL || 'http://localhost:4000' } },
    { name: 'upgraded', use: { baseURL: process.env.UPGRADED_URL || 'http://localhost:4200' } },
  ],
});
