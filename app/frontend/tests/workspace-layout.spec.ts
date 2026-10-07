import { test, expect, type Page } from '@playwright/test';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5188';
const owner = { id: 1, name: '布局测试管理员', role: 'super_admin', status: 'active' };
const customers = [
 { id: 101, business_name: '星河餐厅', customer_code: 'C101', contact_name: '张先生', phone: '555-0101', status: 'closed', sales_person: owner.name, industry: 'restaurant', level: 'normal' },
 { id: 102, business_name: '悦颜美甲', customer_code: 'C102', contact_name: '王女士', phone: '555-0102', status: 'following', sales_person: '小李', industry: 'nail', level: 'normal' },
];
async function seed(page: Page, delayDetail = false) {
 const writes: string[] = [];
 await page.addInitScript(emp => { localStorage.setItem('emp_auth_token', 'workspace-test'); localStorage.setItem('token', 'workspace-test'); localStorage.setItem('emp_auth_data', JSON.stringify(emp)); }, owner);
 await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
  const path = new URL(route.request().url()).pathname;
  if (route.request().method() !== 'GET') writes.push(path);
  let data: unknown = { items: [], total: 0 };
  if (path.endsWith('/emp-auth/me')) data = owner;
  if (path.includes('/app-config')) data = { items: {} };
  if (path === '/api/config') data = { API_BASE_URL: base };
  if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
  if (/\/entities\/customers(?:\/all)?$/.test(path)) data = { items: customers, total: 2 };
  if (path.includes('/entities/tasks')) data = { items: [{ id: 201, title: '核对官网上线资料', customer_id: 101, customer_name: '星河餐厅', assignee_name: owner.name, status: 'pending', priority: 'high', due_date: '2026-01-01', task_type: 'design' }, { id: 202, title: '确认客户反馈', customer_id: 102, customer_name: '悦颜美甲', assignee_name: '小李', status: 'waiting_client', priority: 'medium', due_date: '2026-01-02' }], total: 2 };
  if (path.includes('/entities/payments')) {
   if (delayDetail) await new Promise(resolve => setTimeout(resolve, 1500));
   data = { items: [{ id: 301, customer_id: 101, customer_name: '星河餐厅', amount_paid: 428, amount_due: 428, management_amount: 428, ads_recharge_amount: 0, outstanding_amount: 0, currency: 'USD', payment_date: '2026-10-01', income_type: 'management_fee', payment_mode: 'manual_collection', payment_method: 'zelle' }], total: 1 };
  }
  if (path.includes('/entities/deals')) data = { items: [{ id: 302, customer_id: 101, deal_amount: 428, deal_date: '2026-10-01' }], total: 1 };
  if (path.includes('/entities/subscriptions')) data = { items: [{ id: 401, customer_id: 101, customer_name: '星河餐厅', package_name: '基础服务', package_price: 198, billing_cycle: 'monthly', auto_renew: true, status: 'renewal_pending', end_date: '2026-10-01', next_payment_date: '2026-10-01', renewal_person: owner.name }], total: 1 };
  if (path.includes('/reports/profit-monthly.json')) data = [];
  if (path.includes('/commissions/dashboard')) data = { entries: [] };
  if (path.includes('/deductions-monthly')) data = [{ year_month: '2026-10', rate: 0.15 }];
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
 });
 return writes;
}
test('客户概览与筛选只读，手机首屏显示客户，关联金额完成加载后才展示', async ({ page }) => {
 await page.setViewportSize({ width: 1280, height: 900 });
 const writes = await seed(page, true);
 await page.goto(`${base}/customers`);
 const preview = page.getByRole('complementary', { name: '客户快捷概览' });
 await expect(preview.getByRole('heading', { name: '星河餐厅' })).toBeVisible();
 await page.getByRole('button', { name: '快捷查看 悦颜美甲' }).click();
 await expect(preview.getByRole('heading', { name: '悦颜美甲' })).toBeVisible();
 await page.getByRole('button', { name: '筛选', exact: true }).click();
 await expect(page.getByRole('combobox').filter({ has: page.locator('option[value="all"]') }).first()).toBeVisible();
 await page.setViewportSize({ width: 390, height: 844 });
 const client = page.getByRole('button', { name: '星河餐厅 C101' });
 await expect(client).toBeVisible();
 expect((await client.boundingBox())!.y).toBeLessThan(650);
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 await page.setViewportSize({ width: 1280, height: 900 });
 await page.getByRole('button', { name: '快捷查看 星河餐厅' }).click();
 if (process.env.T24_LAYOUT_OUTPUT) await page.screenshot({ animations: 'disabled', path: `${process.env.T24_LAYOUT_OUTPUT}/customers-layout.png` });
 await preview.getByRole('button', { name: '打开客户 360' }).click();
 await expect(page.getByText('正在核对客户的服务、收款与待办，完成后显示完整概览…')).toBeVisible();
 await expect(page.getByText('$0', { exact: true })).toHaveCount(0);
 await expect(page.getByText('$428', { exact: true }).first()).toBeVisible();
 // Existing monthly-rate initialization is preserved; no customer, task or ledger writes.
 expect(writes.filter(path => path !== '/api/v1/deductions-monthly/ensure')).toEqual([]);
});
test('运营当前事项随选择更新，打开结果表单不提交任务', async ({ page }) => {
 await page.setViewportSize({ width: 1280, height: 900 });
 const writes = await seed(page);
 await page.goto(`${base}/operations-workbench`);
 const panel = page.getByRole('complementary', { name: '当前事项' });
 await expect(panel.getByRole('heading', { name: '核对官网上线资料' })).toBeVisible();
 await page.getByRole('button', { name: '查看事项 确认客户反馈' }).click();
 await expect(panel.getByRole('heading', { name: '确认客户反馈' })).toBeVisible();
 await panel.getByRole('button', { name: '填写处理结果' }).click();
 await expect(page.getByRole('dialog')).toContainText('确认客户反馈');
 await page.getByRole('button', { name: '取消', exact: true }).click();
 await expect(page.getByRole('dialog')).toBeHidden();
 if (process.env.T24_LAYOUT_OUTPUT) await page.screenshot({ animations: 'disabled', path: `${process.env.T24_LAYOUT_OUTPUT}/operations-layout.png` });
 // Existing monthly-rate initialization is preserved; no customer, task or ledger writes.
 expect(writes.filter(path => path !== '/api/v1/deductions-monthly/ensure')).toEqual([]);
});
test('续费保留原金额与日期，危险操作按需展开，核对到账不发起支付', async ({ page }) => {
 await page.setViewportSize({ width: 1280, height: 900 });
 const writes = await seed(page);
 await page.goto(`${base}/finance?tab=subscriptions`);
 await expect(page.getByRole('button', { name: '核对到账', exact: true })).toBeVisible();
 await expect(page.getByText('$198 · 月付', { exact: false })).toBeVisible();
 await expect(page.getByText('停止此套餐的未来续费', { exact: true })).toBeHidden();
 await page.getByRole('button', { name: '更多续费操作：星河餐厅' }).click();
 await expect(page.getByRole('menuitem', { name: '停止此套餐的未来续费' })).toBeVisible();
 await page.keyboard.press('Escape');
 await page.getByRole('button', { name: '核对到账', exact: true }).click();
 const dialog = page.getByRole('dialog');
 await expect(dialog.getByRole('heading', { name: '核对实际到账' })).toBeVisible();
 await expect(dialog).toContainText('本窗口不发起扣款');
 await expect(dialog.locator('input[type=date]')).toHaveValue('2026-10-01');
 await expect(dialog).toContainText('基础服务 · $198');
 if (process.env.T24_LAYOUT_OUTPUT) await page.screenshot({ animations: 'disabled', path: `${process.env.T24_LAYOUT_OUTPUT}/finance-layout.png` });
 await dialog.getByRole('button', { name: '取消', exact: true }).click();
 for (const width of [1280, 820, 390]) {
  await page.setViewportSize({ width, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 }
 // Existing monthly-rate initialization is preserved; no customer, task or ledger writes.
 expect(writes.filter(path => path !== '/api/v1/deductions-monthly/ensure')).toEqual([]);
});
