import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5196';
const screenshotDir = process.env.T24_MOBILE_FINANCE_SCREENSHOT_DIR;
type Options = { noCustomerAccess?: boolean; missingCustomer?: boolean; nextMonth?: boolean };

async function installApi(page: Page, options: Options = {}) {
  const employee = { id: 12, name: '手机财务模拟账号', role: 'finance', status: 'active' };
  const customers = Array.from({ length: 37 }, (_, index) => ({ id: index + 1, business_name: `模拟客户${String(index + 1).padStart(3, '0')}`, customer_code: `C${index + 1}`, status: 'active', sales_person: '模拟负责人' }));
  const payments: Record<string, unknown>[] = customers.map((customer, index) => ({
    id: index + 1, customer_id: customer.id, customer_name: customer.business_name,
    amount_due: 110 + index, amount_paid: 100 + index, outstanding_amount: 10,
    management_amount: 100 + index, ads_recharge_amount: 0, currency: 'USD',
    income_type: 'management_fee', payment_mode: 'manual_collection', payment_method: 'zelle',
    payment_date: `2026-08-${String(index % 28 + 1).padStart(2, '0')}`,
  }));
  if (options.nextMonth) payments.push(...Array.from({ length: 20 }, (_, index) => ({ ...payments[index], id: 100 + index, customer_name: `九月模拟客户${index + 1}`, payment_date: '2026-09-01' })));
  if (options.missingCustomer) payments.unshift(
    { ...payments[0], id: 901, customer_id: null, customer_name: '模拟未关联客户', outstanding_amount: 1 },
    { ...payments[0], id: 902, customer_id: -2, customer_name: '模拟无效客户', outstanding_amount: 1 },
  );
  const records = {
    customers, payments,
    subscriptions: [
      { id: 1, customer_id: 1, customer_name: customers[0].business_name, package_name: '模拟待续费套餐', status: 'renewal_pending', end_date: '2026-08-01' },
      { id: 2, customer_id: null, customer_name: '模拟未关联续费', package_name: '未关联套餐', status: 'renewal_pending' },
    ],
    expenses: [1, 2].map(id => ({ id, customer_id: id, customer_name: `模拟客户成本${id}`, amount: 5, currency: 'USD', expense_type: 'website_fee', expense_month: '2026-08', payment_date: '2026-08-02' })),
    company_expenses: [1, 2].map(id => ({ id, amount: 3, currency: 'USD', category: 'software', expense_month: '2026-08', expense_date: '2026-08-03' })),
  };
  const requests: { method: string; path: string }[] = [];
  await page.clock.install({ time: new Date('2026-08-05T12:00:00+08:00') });
  await page.addInitScript(({ employee, noCustomerAccess }) => {
    localStorage.setItem('emp_auth_token', 'mobile-finance-fixture');
    localStorage.setItem('token', 'mobile-finance-fixture');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
    if (noCustomerAccess) localStorage.setItem('crm_role_permissions', JSON.stringify({ finance: { pages: ['/finance'] } }));
  }, { employee, noCustomerAccess: options.noCustomerAccess });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ method: request.method(), path });
    if (request.method() !== 'GET') return route.fulfill({ status: 400, contentType: 'application/json', body: '{"detail":"测试仅允许读取"}' });
    const entity = path.match(/\/entities\/(customers|payments|subscriptions|expenses|company_expenses)(?:\/|$)/)?.[1] as keyof typeof records | undefined;
    const data = path.endsWith('/emp-auth/me') ? employee
      : path === '/api/v1/app-config' ? { items: {} }
      : path.startsWith('/api/v1/app-config/') ? { value: {} }
      : path.includes('/reports/profit-monthly.json') ? []
      : path.startsWith('/api/v1/deductions-monthly') ? [{ year_month: '2026-08', rate: 0.15 }, { year_month: '2026-09', rate: 0.15 }]
      : path === '/api/v1/commissions/dashboard' ? { entries: [] }
      : path === '/api/v1/product-plans' ? { business_lines: [], products: [], plans: [] }
      : path.endsWith('/projects') ? { items: [], total: 0 }
      : entity ? { items: records[entity], total: records[entity].length }
      : { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return requests;
}

function expectReadOnly(requests: { method: string; path: string }[]) {
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
  expect(requests.some(request => /deductions-monthly\/ensure/.test(request.path))).toBe(false);
}
async function expectNoOverflow(page: Page) {
  const widths = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}
const summarySnapshot = (page: Page) => Promise.all(['本月实收', '本月总成本', '待收款', '人民币支出'].map(label => page.getByText(label, { exact: true }).locator('..').innerText()));

for (const width of [320, 390]) {
  test(`${width}px流水完整可达且加载不改变完整合计`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const requests = await installApi(page);
    await page.goto(`${baseUrl}/finance?tab=income`);
    const ledger = page.getByRole('region', { name: '流水列表', exact: true });
    await expect(ledger.getByText('已显示 15 / 共 41 条', { exact: true })).toBeVisible();
    const before = await summarySnapshot(page);
    await expect(ledger.getByText('模拟客户001', { exact: true })).toHaveCount(0);
    await ledger.getByRole('button', { name: '加载更多流水', exact: true }).click();
    await expect(ledger.getByText('已显示 30 / 共 41 条', { exact: true })).toBeVisible();
    await ledger.getByRole('button', { name: '加载更多流水', exact: true }).click();
    await expect(ledger.getByText('已显示 41 / 共 41 条', { exact: true })).toBeVisible();
    await expect(ledger.getByText('模拟客户001', { exact: true })).toBeVisible();
    await expect(ledger.getByText('模拟客户成本1', { exact: true })).toBeVisible();
    await expect(ledger.getByRole('button', { name: '加载更多流水', exact: true })).toHaveCount(0);
    expect(await summarySnapshot(page)).toEqual(before);
    await expectNoOverflow(page);
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-finance-ledger-complete-${width}.png`, fullPage: true });
    expectReadOnly(requests);
  });
  test(`${width}px全部应收可达，37笔合计始终370`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const requests = await installApi(page);
    await page.goto(`${baseUrl}/finance?tab=receivables`);
    const receivables = page.getByRole('region', { name: '应收列表', exact: true });
    await expect(receivables.getByText('已显示 15 / 共 37 条', { exact: true })).toBeVisible();
    await expect(receivables.getByText('合计 $370', { exact: true })).toBeVisible();
    await expect(receivables.getByText('模拟客户037', { exact: true })).toHaveCount(0);
    const before = await summarySnapshot(page);
    for (let index = 0; index < 2; index += 1) await receivables.getByRole('button', { name: '加载更多应收', exact: true }).click();
    await expect(receivables.getByText('已显示 37 / 共 37 条', { exact: true })).toBeVisible();
    await expect(receivables.getByText('模拟客户037', { exact: true })).toBeVisible();
    await expect(receivables.getByText('合计 $370', { exact: true })).toBeVisible();
    await expect(receivables.getByRole('button', { name: '加载更多应收', exact: true })).toHaveCount(0);
    expect(await summarySnapshot(page)).toEqual(before);
    await expectNoOverflow(page);
    expectReadOnly(requests);
  });
}

test('查看全部更新真实流水地址，视图切换后从首批开始', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page);
  await page.goto(`${baseUrl}/finance`);
  const ledger = page.getByRole('region', { name: '流水列表', exact: true });
  await expect(ledger.getByText('已显示 5 / 共 41 条', { exact: true })).toBeVisible();
  await ledger.getByRole('button', { name: '查看全部流水', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('tab')).toBe('income');
  await expect(ledger.getByText('已显示 15 / 共 41 条', { exact: true })).toBeVisible();
  await ledger.getByRole('button', { name: '加载更多流水', exact: true }).click();
  await expect(ledger.getByText('已显示 30 / 共 41 条', { exact: true })).toBeVisible();
  const views = page.getByRole('navigation', { name: '财务手机视图', exact: true });
  await views.getByRole('button', { name: /应收/ }).click();
  await expect(page.getByRole('region', { name: '应收列表' }).getByText('已显示 15 / 共 37 条', { exact: true })).toBeVisible();
  await views.getByRole('button', { name: '流水', exact: true }).click();
  await expect(ledger.getByText('已显示 15 / 共 41 条', { exact: true })).toBeVisible();
  expectReadOnly(requests);
});

test('应收与续费详情只读取并保留财务视图与额外查询参数', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page);
  for (const tab of ['receivables', 'subscriptions']) {
    await page.goto(`${baseUrl}/finance?tab=${tab}&context=mobile-fixture`);
    await page.getByRole('button', { name: '查看客户详情：模拟客户001', exact: true }).click();
    const url = new URL(page.url());
    expect(url.pathname).toBe('/customers');
    expect(url.searchParams.get('detail')).toBe('1');
    expect(url.searchParams.get('tab')).toBe('overview');
    expect(url.searchParams.get('from')).toBe('finance');
    expect(url.searchParams.get('returnTo')).toBe(`/finance?tab=${tab}&context=mobile-fixture`);
    await expect(page.getByRole('heading', { name: '模拟客户001', exact: true })).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: '返回财务管理', exact: true }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get('tab')).toBe(tab);
    await expect(page.getByRole('heading', { name: tab === 'receivables' ? '待收款客户' : '续费风险列表', exact: true })).toBeVisible();
  }
  expectReadOnly(requests);
});

test('没有有效客户id不造链接，320px卡片无溢出', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const requests = await installApi(page, { missingCustomer: true });
  await page.goto(`${baseUrl}/finance?tab=receivables`);
  for (const name of ['模拟未关联客户', '模拟无效客户']) {
    await expect(page.getByRole('region', { name: '应收列表' }).getByText(name, { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: `查看客户详情：${name}`, exact: true })).toHaveCount(0);
  }
  await expectNoOverflow(page);
  await page.goto(`${baseUrl}/finance?tab=subscriptions`);
  await expect(page.getByText('模拟未关联续费', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '查看客户详情：模拟未关联续费', exact: true })).toHaveCount(0);
  await expectNoOverflow(page);
  expectReadOnly(requests);
});

test('无客户页面权限时保留风险数值且不提供详情跳转', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, { noCustomerAccess: true });
  for (const tab of ['subscriptions', 'receivables']) {
    await page.goto(`${baseUrl}/finance?tab=${tab}`);
    await expect(page.getByRole('heading', { name: tab === 'subscriptions' ? '续费风险列表' : '待收款客户', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /^查看客户详情：/ })).toHaveCount(0);
  }
  await expect(page.getByRole('region', { name: '应收列表' }).getByText('合计 $370', { exact: true })).toBeVisible();
  expectReadOnly(requests);
});

test('月份变化重置首批显示，不沿用上月展开数', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, { nextMonth: true });
  await page.goto(`${baseUrl}/finance?tab=income`);
  const ledger = page.getByRole('region', { name: '流水列表', exact: true });
  await expect(ledger.getByText('已显示 15 / 共 41 条', { exact: true })).toBeVisible();
  await ledger.getByRole('button', { name: '加载更多流水', exact: true }).click();
  await expect(ledger.getByText('已显示 30 / 共 41 条', { exact: true })).toBeVisible();
  await page.clock.setSystemTime(new Date('2026-09-05T12:00:00+08:00'));
  await page.clock.runFor(60_001);
  await expect(ledger.getByText('已显示 15 / 共 20 条', { exact: true })).toBeVisible();
  await ledger.getByRole('button', { name: '加载更多流水', exact: true }).click();
  await expect(ledger.getByText('已显示 20 / 共 20 条', { exact: true })).toBeVisible();
  expectReadOnly(requests);
});
