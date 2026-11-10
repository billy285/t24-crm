import { defineConfig } from '@playwright/test';
const out = '/Users/billyli/Documents/Codex/2026-11-08/t/work/beautyos-sales-knowledge-20261110';
export default defineConfig({ testDir: '.', testMatch: ['beautyos-knowledge-pack.spec.ts', 'sales-approved-knowledge.spec.ts'], workers: 1, fullyParallel: false, timeout: 30000,
  use: { browserName: 'chromium', viewport: { width: 1093, height: 824 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  reporter: [['line'], ['json', { outputFile: `${out}/playwright-report.json` }]], outputDir: `${out}/playwright-results`,
});
