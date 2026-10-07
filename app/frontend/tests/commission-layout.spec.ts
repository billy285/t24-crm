import { test, expect, type Page } from '@playwright/test';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5187';
const employee = { id: 1, name: '测试管理员', role: 'super_admin', status: 'active' };
async function seed(page: Page, populated = false) {
 await page.setViewportSize({ width: 1280, height: 900 });
 await page.addInitScript(emp => { localStorage.setItem('emp_auth_token', 'layout-test-token'); localStorage.setItem('token', 'layout-test-token'); localStorage.setItem('emp_auth_data', JSON.stringify(emp)); }, employee);
 const writes: string[] = [];
 await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
  const path = new URL(route.request().url()).pathname;
  if (route.request().method() !== 'GET') writes.push(path);
  let data: unknown = { items: [] };
  if (path === '/api/config') data = { API_BASE_URL: base };
  if (path.endsWith('/emp-auth/me')) data = employee;
  if (path.endsWith('/commissions/dashboard')) data = { summary: { partner_count: 3, active_partner_count: 2, pending_count: populated ? 1 : 0, currencies: { USD: { confirmed_expense: 10, payable: 5, paid: 5 } }, accounting_rule: '实收记收入，佣金独立核算', quality: { issue_count: 3, high_count: 3, coverage_rate: 98.2, covered_count: 70, examined_count: 71 } }, partners: [{ id: 7, partner_code: 'P007', name: '测试渠道', partner_type: 'partner', status: 'active', joined_at: '2026-01-01' }], agreements: [], attributions: [], quality_issues: [{ key: 'q1', severity: 'high', title: '待补归属', description: '需要核对', customer_id: 1 }], entries: populated ? [{ id: 1, partner_name: '测试渠道', customer_id: 1, customer_name: '测试客户', payment_id: 1, entry_type: 'first_order', status: 'pending_confirmation', service_month: '2026-10', occurred_at: '2026-10-01', currency: 'USD', gross_receipt_amount: 100, eligible_service_amount: 100, contract_rate: 0.1, inactivity_months: 0, activity_multiplier: 1, commission_amount: 10 }] : [] };
  if (path.endsWith('/commissions/options')) data = { employees: [], customers: [{ id: 1, name: '测试客户' }], products: [], engagements: [], business_lines: [] };
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
 });
 await page.goto(`${base}/commissions`);
 await expect(page.getByRole('heading', { name: '渠道与分润', exact: true })).toBeVisible();
 return writes;
}
test('empty ledger preserves management, filters, rules and amounts', async ({ page }) => {
 const writes = await seed(page);
 await expect(page.getByText('暂无佣金记录', { exact: true })).toBeVisible();
 await expect(page.locator('.commission-page table:visible')).toHaveCount(0);
 await expect(page.getByLabel('搜索渠道、客户或收款编号')).toHaveCount(0);
 await page.getByRole('button', { name: '筛选', exact: true }).click();
 await page.getByLabel('搜索渠道、客户或收款编号').fill('不存在');
 await expect(page.getByText('没有匹配的佣金记录', { exact: true })).toBeVisible();
 await page.getByRole('button', { name: '清除筛选' }).click();
 await page.getByText('财务汇总与记账规则', { exact: true }).click();
 await expect(page.getByText('已确认 $10.00', { exact: true })).toBeVisible();
 await page.getByRole('button', { name: '渠道管理' }).click();
 await page.getByRole('menuitem', { name: '渠道与协议' }).click();
 await expect(page.getByText('测试渠道', { exact: true })).toBeVisible();
 await page.getByRole('button', { name: '新增渠道', exact: true }).click();
 await expect(page.getByRole('dialog')).toBeVisible();
 await page.getByRole('button', { name: '取消', exact: true }).click();
 await page.getByRole('button', { name: '返回台账' }).click();
 await page.getByRole('button', { name: '查看待办' }).click();
 await expect(page.getByText('待补归属', { exact: true })).toBeVisible();
 await page.getByRole('button', { name: '设置归属', exact: true }).click();
 await expect(page.getByRole('dialog')).toBeVisible();
 expect(writes).toEqual([]);
});
test('populated ledger preserves transitions and settlement export', async ({ page }) => {
 const writes = await seed(page, true);
 await expect(page.getByRole('button', { name: '确认', exact: true })).toBeVisible();
 await expect(page.getByRole('button', { name: '作废', exact: true })).toBeVisible();
 await page.getByRole('button', { name: '月度结算', exact: true }).click();
 await expect(page.getByLabel('结算月份')).toBeVisible();
 await expect(page.getByRole('button', { name: '导出结算 CSV' })).toBeEnabled();
 await expect(page.getByRole('button', { name: '确认', exact: true })).toBeHidden();
 await page.getByRole('button', { name: '佣金记录', exact: true }).click();
 await expect(page.getByRole('button', { name: '确认', exact: true })).toBeVisible();
 expect(writes).toEqual([]);
});
test('navigation expands and page fits tablet and desktop', async ({ page }) => {
 await seed(page);
 await page.getByRole('button', { name: '展开功能导航' }).click();
 await expect(page.getByRole('button', { name: '收起功能导航' })).toBeVisible();
 await page.getByRole('button', { name: '收起功能导航' }).click();
 for (const width of [1280, 820]) {
  await page.setViewportSize({ width, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '查看待办' })).toBeVisible();
 }
 await page.setViewportSize({ width: 1280, height: 900 });
 if (process.env.T24_LAYOUT_SCREENSHOT) await page.screenshot({ path: process.env.T24_LAYOUT_SCREENSHOT });
});
