import { defineConfig } from '@playwright/test';
const output = '/Users/billyli/Documents/Codex/2026-11-08/t/work/merchant-pool-filter-state-20261110';
export default defineConfig({
  testDir: '.', testMatch: ['merchant-pool-filter-state.spec.ts', 'merchant-timezone.spec.ts', 'prospect-verification.spec.ts'],
  workers: 1, fullyParallel: false, timeout: 30000,
  use: { browserName: 'chromium', viewport: { width: 1093, height: 824 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  reporter: [['line'], ['json', { outputFile: `${output}/playwright-report.json` }]],
  outputDir: `${output}/playwright-results`,
});
