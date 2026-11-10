import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.', testMatch: ['prospect-verification.spec.ts', 'merchant-timezone.spec.ts', 'merchant-import-guidance.spec.ts'],
  fullyParallel: false, workers: 1, timeout: 30000,
  use: { browserName: 'chromium', viewport: { width: 1093, height: 900 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  reporter: [['line'], ['json', { outputFile: '/Users/billyli/Documents/Codex/2026-11-08/t/work/sales-center-five-improvements/frontend-quality-report.json' }]],
  outputDir: '/Users/billyli/Documents/Codex/2026-11-08/t/work/sales-center-five-improvements/frontend-quality-results',
});
