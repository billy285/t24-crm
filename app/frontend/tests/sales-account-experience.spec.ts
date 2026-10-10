import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5215';
const catalog = { business_lines: [{ id: 1, code: 'managed-service', name: '代运营' }], products: [{ id: 1, business_line_id: 1, name: '商家代运营', default_currency: 'USD' }], plans: [{ id: 1, product_id: 1, name: '公开季度套餐', standard_price: 398, default_currency: 'USD', default_billing_cycle: 'quarterly', platform_limit: 2, scope_type: 'platforms' }] };

async function setup(page: Page, id = 11, options: { catalogFail?: boolean; primaryFail?: boolean } = {}) {
  let employee = { id, role: 'sales', status: 'active', name: `模拟销售${id}` };
  let catalogFail = !!options.catalogFail, primaryFail = !!options.primaryFail, auxiliaryFail = false;
  const reads: string[] = [], writes: { path: string; body: any }[] = [];
  const lead = () => ({ id: employee.id === 11 ? 101 : 102, business_name: employee.id === 11 ? '甲商家' : '乙商家', assigned_sales_id: employee.id, status: 'interested', phone: '+12125550123', country: 'US', created_at: '2026-10-01', is_blacklisted: false, do_not_contact: false });
  await page.addInitScript(emp => { localStorage.setItem('emp_auth_token', 'synthetic-account-test'); localStorage.setItem('token', 'synthetic-account-test'); if (!localStorage.getItem('emp_auth_data')) localStorage.setItem('emp_auth_data', JSON.stringify(emp)); }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const r = route.request(), u = new URL(r.url()), path = u.pathname;
    if (r.method() === 'GET') reads.push(path + u.search);
    else writes.push({ path, body: r.postData() ? r.postDataJSON() : null });
    const ok = (data: any) => route.fulfill({ json: data });
    const unavailable = () => route.fulfill({ status: 503, json: { detail: '模拟暂时不可用' } });
    if (path.includes('/emp-auth/me')) return ok(employee);
    if (path.includes('/app-config')) return ok({ items: {}, value: {} });
    if (path.includes('/emp-auth/')) return ok({});
    if (path === '/api/v1/product-plans') return route.fulfill({ status: 403, json: { detail: '完整套餐管理目录禁止销售访问' } });
    if (path === '/api/v1/sales-deal-controls/catalog') return catalogFail ? unavailable() : ok(catalog);
    if (path === '/api/v1/sales-deal-controls/options') return ok({ employees: [{ id: 30, name: '运营负责人', role: 'operations' }] });
    if (path.endsWith('/readiness')) return ok({ lead: lead(), quotes: [], handoff: {}, blockers: ['需要一张已审批的报价单'] });
    if (path.endsWith('/quotes')) return ok({ id: 4, ...r.postDataJSON(), status: 'submitted' });
    if (path === '/api/v1/sales-leads') return primaryFail ? unavailable() : ok({ items: [lead()], total: 1 });
    if (/\/sales-leads\/10[12]$/.test(path)) return ok(lead());
    if (path.endsWith('/sales-leads/stats')) return auxiliaryFail ? unavailable() : ok({ total: 1, assigned: 1, unassigned: 0, blacklisted: 0, do_not_contact: 0 });
    if (path.endsWith('/dashboard/call-report')) return auxiliaryFail ? unavailable() : ok({ period: { days: 7, start_date: '2026-10-01', end_date: '2026-10-11' }, source: { status: 'verified', label: '真实记录', provider: 'RingCentral' }, summary: { provider_calls: 0, connected: 0, not_connected: 0, connection_rate: 0, total_talk_seconds: 0, average_talk_seconds: 0, crm_records: 0, linked_records: 0, link_rate: 0, interested: 0, appointments: 0, conversions: 0, assigned: 1, completed: 0, completion_rate: 0 }, recent_calls: [], employees: [], daily: [], result_breakdown: [] });
    if (path.endsWith('/workbench/today')) return primaryFail ? unavailable() : ok({ salesperson: { id: employee.id, name: employee.name }, quota: 20, completed_count: 0, assigned_count: 1, remaining_count: 1, categories: { unfinished: 1, interested: 1 }, performance: { interested: 1, appointments: 0 }, items: [{ task_id: employee.id * 100, task_status: 'pending', priority: 'normal', queue_category: 'interested', lead: lead() }] });
    if (path.endsWith('/recovery/my-alerts') || path.endsWith('/dashboard/performance')) return auxiliaryFail ? unavailable() : ok({ items: [] });
    if (path.endsWith('/ringcentral/status')) return auxiliaryFail ? unavailable() : ok({ configured: false, connected: false });
    if (path.includes('/sales-intelligence/leads')) return ok(path.endsWith('/leads') ? { items: [] } : { profile: { timezone: 'America/New_York' }, config: { default_contact_start: 9, default_contact_end: 18 } });
    if (path.endsWith('/call-history')) return ok([]);
    return ok({ items: [], total: 0 });
  });
  return { reads, writes, setCatalogFailure: (value: boolean) => { catalogFail = value; }, failRefresh: () => { primaryFail = true; auxiliaryFail = true; }, recover: () => { primaryFail = false; auxiliaryFail = false; }, switchUser: (next: number) => { employee = { ...employee, id: next, name: `模拟销售${next}` }; return employee; } };
}
const errors = (page: Page) => page.locator('[data-sonner-toast][data-type="error"]');
async function refresh(page: Page) { await page.evaluate(() => window.dispatchEvent(new CustomEvent('t24:business-data-refresh'))); }

for (const width of [390, 1440]) for (const id of [11, 12]) test(`销售${id}首次打开不请求管理目录，报价按需读取公开字段（${width}）`, async ({ page }) => {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  const f = await setup(page, id);
  await page.goto(base + '/sales-leads');
  await expect(page.getByRole('button', { name: id === 11 ? '甲商家' : '乙商家', exact: true })).toBeVisible();
  expect(f.reads.some(path => path.includes('product-plans') || path.includes('sales-deal-controls/catalog') || path.includes('sales-deal-controls/options'))).toBe(false);
  await expect(errors(page)).toHaveCount(0);
  if (width < 768) {
    await page.getByRole('button', { name: `更多线索操作：${id === 11 ? '甲商家' : '乙商家'}` }).click();
    await page.getByRole('menuitem', { name: '准备报价', exact: true }).click();
  } else await page.getByRole('button', { name: '准备报价', exact: true }).click();
  await expect(page.locator('#slr-quoteForm-business_line_id')).toBeEnabled();
  await page.locator('#slr-quoteForm-business_line_id').selectOption('1');
  await page.locator('#slr-quoteForm-product_id').selectOption('1');
  await page.locator('#slr-quoteForm-product_plan_id').selectOption('1');
  await expect(page.locator('#slr-quoteForm-list_amount')).toHaveValue('398');
  await expect(page.locator('#slr-quoteForm-billing_cycle')).toHaveValue('quarterly');
  await expect(page.locator('#slr-quoteForm-currency')).toHaveValue('USD');
  await page.getByLabel('Google Business Profile', { exact: true }).check();
  await page.getByLabel('Google Ads', { exact: true }).check();
  await expect(page.getByLabel('Facebook', { exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '提交报价审批', exact: true }).click();
  await expect.poll(() => f.writes.filter(row => row.path.endsWith('/quotes')).length).toBe(1);
  const quote = f.writes.find(row => row.path.endsWith('/quotes'))!;
  expect(quote.path).toContain(`/sales-deal-controls/${id === 11 ? 101 : 102}/quotes`);
  expect(quote.body).toMatchObject({ business_line_id: 1, product_id: 1, product_plan_id: 1, list_amount: 398, currency: 'USD', billing_cycle: 'quarterly', selected_platforms: ['Google Business Profile', 'Google Ads'] });
  expect(f.reads.some(path => path.includes('product-plans'))).toBe(false);
});

test('套餐失败留在成交弹窗，可重试，不会误提交或反复弹窗', async ({ page }) => {
  const f = await setup(page, 11, { catalogFail: true });
  await page.goto(base + '/sales-leads');
  await page.getByRole('button', { name: '准备报价', exact: true }).click();
  await expect(page.getByText('在售套餐暂时无法读取，请重试后继续。', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: '提交报价审批', exact: true })).toBeDisabled();
  await expect(errors(page)).toHaveCount(0);
  f.setCatalogFailure(false);
  await page.getByRole('button', { name: '重新加载成交选项', exact: true }).click();
  await expect(page.locator('#slr-quoteForm-business_line_id')).toBeEnabled();
  await expect(page.getByText('在售套餐暂时无法读取，请重试后继续。', { exact: false })).toHaveCount(0);
  expect(f.writes.filter(row => row.path.endsWith('/quotes'))).toHaveLength(0);
});

test('线索后台连续失败保留上次数据和部分成功结果，不重复toast', async ({ page }) => {
  const f = await setup(page);
  await page.goto(base + '/sales-leads');
  await expect(page.getByRole('button', { name: '准备报价', exact: true })).toBeVisible();
  f.failRefresh();
  for (let i = 0; i < 3; i++) {
    const before = f.reads.filter(path => path.startsWith('/api/v1/sales-leads?')).length;
    await refresh(page);
    await expect.poll(() => f.reads.filter(path => path.startsWith('/api/v1/sales-leads?')).length).toBeGreaterThan(before);
    await expect(page.getByRole('button', { name: '重新加载列表', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '准备报价', exact: true })).toBeVisible();
    await expect(errors(page)).toHaveCount(0);
    await page.waitForTimeout(80);
  }
  await expect(page.getByRole('status').filter({ hasText: '部分数据未能更新' })).toHaveCount(1);
  f.recover();
  await page.getByRole('button', { name: '重试更新', exact: true }).click();
  await expect(page.getByRole('button', { name: '重新加载列表', exact: true })).toHaveCount(0);
  await expect(page.getByRole('status').filter({ hasText: '部分数据未能更新' })).toHaveCount(0);
});

test('工作台首轮和重复失败用同一页面状态，不弹重复错误', async ({ page }) => {
  const f = await setup(page, 11, { primaryFail: true });
  await page.goto(base + '/sales-workbench');
  await expect(page.getByText('今日任务暂不可用', { exact: true })).toBeVisible();
  for (let i = 0; i < 3; i++) {
    const before = f.reads.filter(path => path.includes('/workbench/today')).length;
    await refresh(page);
    await expect.poll(() => f.reads.filter(path => path.includes('/workbench/today')).length).toBeGreaterThan(before);
    await expect(errors(page)).toHaveCount(0);
    await page.waitForTimeout(80);
  }
  await expect(page.getByRole('alert').filter({ hasText: '今日任务暂时无法更新' })).toHaveCount(1);
});

test('工作台刷新失败保留客户与上次辅助数据，重试恢复状态', async ({ page }) => {
  const f = await setup(page);
  await page.goto(base + '/sales-workbench');
  await expect(page.getByRole('heading', { name: '甲商家', exact: true })).toBeVisible();
  f.failRefresh(); await refresh(page);
  await expect(page.getByText('今日任务暂时无法更新，保留上次读取的任务', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: '甲商家', exact: true })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: '保护提醒' })).toHaveCount(1);
  await expect(errors(page)).toHaveCount(0);
  f.recover(); await page.getByRole('button', { name: '重试更新', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '保护提醒' })).toHaveCount(0);
});

test('换销售后不沿用上一销售线索或成交弹窗草稿', async ({ page }) => {
  const f = await setup(page);
  await page.goto(base + '/sales-leads');
  await page.getByRole('button', { name: '准备报价', exact: true }).click();
  await page.locator('#slr-quoteForm-special_terms').fill('甲销售未提交草稿');
  const next = f.switchUser(12);
  await page.evaluate(emp => { localStorage.setItem('emp_auth_data', JSON.stringify(emp)); }, next);
  await page.reload();
  await expect(page.getByRole('button', { name: '准备报价', exact: true })).toBeVisible();
  await expect(page.getByText('甲商家', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '准备报价', exact: true }).click();
  await expect(page.getByRole('heading', { name: '成交审核 · 乙商家', exact: true })).toBeVisible();
  await expect(page.locator('#slr-quoteForm-special_terms')).toHaveValue('');
  expect(f.writes.filter(row => row.path.endsWith('/quotes'))).toHaveLength(0);
});
