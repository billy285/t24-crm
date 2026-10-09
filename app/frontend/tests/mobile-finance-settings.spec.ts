import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
if (!['localhost', '127.0.0.1'].includes(new URL(baseUrl).hostname)) throw new Error('Local mock server required');
const month = new Date().toISOString().slice(0, 7);
type Write = { path: string; method: string; body: any };

const payrollRow = {
  id: 31, employee_id: 31, employee_name: '测试员工', employee_code: 'T24-031', department: '运营部',
  payment_method: 'bank_card', payment_account_masked: '•••• 8831',
  base_salary: 5000, fixed_performance: 500, commission: 200, bonus: 0, allowance: 0, reimbursement: 0,
  absence_deduction: 0, performance_deduction: 0, salary_advance_deduction: 0, other_deduction: 0,
  payment_status: 'pending', gross_amount: 5700, deduction_amount: 0, net_amount: 5700,
};

async function json(route: Route, value: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(value) });
}

async function setup(page: Page, options: { role?: 'admin' | 'finance'; status?: 'draft' | 'confirmed' | 'paid' } = {}) {
  const employee = { id: 1, name: '财务手机测试', role: options.role || 'admin', status: 'active' };
  let status = options.status || 'draft';
  const writes: Write[] = [];
  await page.setViewportSize({ width: 320, height: 640 });
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'mobile-finance-settings-fixture');
    localStorage.setItem('token', 'mobile-finance-settings-fixture');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') {
      writes.push({ path, method: request.method(), body: request.postDataJSON() });
      if (path.endsWith('/transition') && request.postDataJSON().action === 'mark_paid') status = 'paid';
      return json(route, { message: '已保存' });
    }
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path === '/api/v1/payroll') return json(route, {
      sheet: { id: 7, month, status, currency: 'CNY' },
      items: [{ ...payrollRow, payment_status: status === 'paid' ? 'paid' : 'pending' }],
      totals: { gross: 5700, deductions: 0, net: 5700 },
    });
    if (path.endsWith('/payroll/employees')) return json(route, [{ id: 31, name: '测试员工', employee_code: 'T24-031', department: '运营部' }]);
    if (path.endsWith('/payroll/audit')) return json(route, []);
    if (path.endsWith('/deductions-monthly/default')) return json(route, { rate: 0.15 });
    if (path.endsWith('/deductions-monthly')) return json(route, [{ year_month: '2026-08', rate: 0.15, updated_at: '2026-08-31T12:00:00' }]);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.includes('/entities/')) return json(route, { items: [], total: 0 });
    return json(route, {});
  });
  return writes;
}

async function expectFits(page: Page) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, doc: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(sizes.doc).toBeLessThanOrEqual(sizes.viewport);
  expect(sizes.body).toBeLessThanOrEqual(sizes.viewport);
  const table = page.locator('table:visible').first();
  if (await table.count()) {
    const rect = await table.boundingBox();
    expect(rect?.width).toBeLessThanOrEqual(320);
  }
}

test('320px 工资列表和编辑使用原保存接口，金额字段不改算', async ({ page }) => {
  const writes = await setup(page);
  await page.goto(`${baseUrl}/payroll`);
  await expect(page.getByRole('heading', { name: '工资表与人力成本' })).toBeVisible();
  await expect(page.locator('td[data-label="实发"]')).toHaveText('¥5,700.00');
  await expectFits(page);
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '编辑工资明细' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('基本工资', { exact: true }).fill('7123.45');
  await expectFits(page);
  await dialog.getByRole('button', { name: '保存明细', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ path: `/api/v1/payroll/${month}/items/31`, method: 'PUT', body: { base_salary: 7123.45, fixed_performance: 500, commission: 200, payment_account: '' } });
});

test('手机工资发放保留日期确认和整表锁定', async ({ page }) => {
  const writes = await setup(page, { status: 'confirmed' });
  await page.goto(`${baseUrl}/payroll`);
  await page.getByRole('button', { name: '登记 1 人并锁定' }).click();
  const dialog = page.getByRole('dialog', { name: '确认整表发放完成' });
  await expect(dialog).toBeVisible();
  expect(writes).toHaveLength(0);
  await dialog.getByLabel('实际发放日期 *').fill(`${month}-15`);
  await expectFits(page);
  await dialog.getByRole('button', { name: '确认发放并锁定', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(writes).toEqual([{ path: `/api/v1/payroll/${month}/transition`, method: 'POST', body: { action: 'mark_paid', reason: null, payment_date: `${month}-15`, confirm_all_pending: true } }]);
  await expect(page.getByRole('button', { name: '编辑', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '新增员工', exact: true })).toBeDisabled();
});

test('手机财务角色不能确认工资或重新打开已发工资', async ({ page }) => {
  const writes = await setup(page, { role: 'finance', status: 'paid' });
  await page.goto(`${baseUrl}/payroll`);
  await expect(page.getByRole('heading', { name: '工资表与人力成本' })).toBeVisible();
  await expect(page.getByRole('button', { name: '编辑', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '带原因重新打开' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '确认工资表' })).toHaveCount(0);
  await expectFits(page);
  expect(writes).toHaveLength(0);
});

test('320px 管理员扣点编辑和默认设置保留原接口及百分比换算', async ({ page }) => {
  const writes = await setup(page);
  await page.goto(`${baseUrl}/settings/deduction`);
  await expect(page.getByRole('heading', { name: '月度扣点比例', exact: true })).toBeVisible();
  await expect(page.locator('td[data-label="扣点比例"]')).toHaveText('15%');
  await expectFits(page);
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '编辑月份' });
  await dialog.getByLabel('扣点比例 (%)', { exact: true }).fill('17.5');
  await expectFits(page);
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(writes[0]).toEqual({ path: '/api/v1/deductions-monthly/2026-08', method: 'PUT', body: { rate: 0.175 } });
  await page.getByLabel('默认扣点 (%)').fill('20');
  await page.getByRole('button', { name: '保存默认' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ path: '/api/v1/deductions-monthly/default', method: 'PUT', body: { rate: 0.2 } });
});

test('手机财务角色仍仅能查看扣点，不能保存删除或导入', async ({ page }) => {
  const writes = await setup(page, { role: 'finance' });
  await page.goto(`${baseUrl}/settings/deduction`);
  await expect(page.locator('td[data-label="扣点比例"]')).toHaveText('15%');
  await expect(page.getByLabel('默认扣点 (%)')).toBeDisabled();
  for (const name of ['新增月份', '保存默认', '编辑', '删除', '导入']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  await expectFits(page);
  expect(writes).toHaveLength(0);
});
