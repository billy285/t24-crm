import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const employee = { id: 1, name: '手机测试主管', role: 'sales_manager', status: 'active' };
const common = { phone: '+12025550123', country: 'US', assigned_sales_id: 1, assigned_sales_name: employee.name, created_at: '2026-10-01T00:00:00Z', is_blacklisted: false, do_not_contact: false };
const leads = [
  { ...common, id: 31, business_name: '新商家', status: 'new' },
  { ...common, id: 32, business_name: '意向商家', status: 'interested', notes: '希望先确认服务范围', next_follow_up_at: '2026-10-12T01:00:00Z' },
  { ...common, id: 33, business_name: '已转客户商家', status: 'interested', converted_customer_id: 90 },
  { ...common, id: 34, business_name: '禁止联系商家', status: 'blocked', do_not_contact: true },
];

async function seed(page: Page) {
  const writes: string[] = [];
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'isolated-mobile');
    localStorage.setItem('token', 'isolated-mobile');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (req.method() !== 'GET') {
      writes.push(`${req.method()} ${path}`);
      return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
    }
    let data: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path === '/api/v1/sales-leads') data = { items: leads, total: leads.length };
    else if (/\/sales-leads\/\d+$/.test(path)) data = leads.find(lead => path.endsWith(`/${lead.id}`));
    else if (path.endsWith('/sales-leads/stats')) data = { total: 4, assigned: 4, unassigned: 0, do_not_contact: 1, blacklisted: 0 };
    else if (path.endsWith('/sales-leads/assignees')) data = [employee];
    else if (/sales-leads\/(dashboard|recovery)\//.test(path)) data = null;
    else if (path.endsWith('/call-history')) data = [];
    else if (path.endsWith('/readiness')) data = { lead: leads[1], quotes: [], handoff: {}, blockers: ['需要已审批报价'] };
    else if (path.endsWith('/sales-deal-controls/options')) data = { employees: [] };
    else if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    else if (path.endsWith('/sales-intelligence/views')) data = [];
    else if (path.endsWith('/sales-intelligence/leads')) data = { items: leads.map(lead => ({ ...lead, calls: 0, connected: 0, records: 0, manual_records: 0, outcomes: {}, potential: 'unknown', potential_label: '待判断', rationale: ['需要先确认需求'], profile: {} })) };
    await route.fulfill({ json: data });
  });
  return writes;
}

for (const width of [320, 360, 390, 430]) test(`${width}px 新线索卡精简空值且意向卡操作不换行溢出`, async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width, height: 844 });
  await page.goto(`${base}/sales-leads`);
  const fresh = page.getByTestId('sales-lead-mobile-card').filter({ hasText: '新商家' });
  const opportunity = page.getByTestId('sales-lead-mobile-card').filter({ hasText: '意向商家' });
  await expect(fresh).toBeVisible();
  await expect(opportunity.locator('.sl-call-numbers b').first()).toHaveText('0');
  expect(await fresh.evaluate(card => Array.from(card.childNodes).filter(node => node.nodeType === Node.TEXT_NODE && node.textContent?.trim() === '0').length)).toBe(0);
  await expect(fresh).not.toContainText(/未填写联系人|地区未采集|暂无沟通摘要|尚无联系时间/);
  await expect(fresh.locator('.slr-card-name')).toHaveCSS('min-height', '44px');
  const actions = opportunity.locator('.slr-card-actions');
  await expect(actions.getByRole('button')).toHaveCount(3);
  for (const button of await actions.getByRole('button').all()) {
    const box = await button.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    expect(box!.width).toBeGreaterThanOrEqual(44);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  }
  const ys = await actions.getByRole('button').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().top));
  expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(2);
  await expect(opportunity).toContainText('希望先确认服务范围');
  await expect(page.getByTestId('sales-lead-mobile-card').filter({ hasText: '禁止联系商家' }).getByRole('button', { name: '拨号', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writes).toEqual([]);
});

test('手机意向客户可直接跟进，失败保留草稿并从菜单打开报价', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 390, height: 520 });
  await page.goto(`${base}/sales-leads`);
  const card = page.getByTestId('sales-lead-mobile-card').filter({ hasText: '意向商家' });
  await card.getByRole('button', { name: '记录跟进：意向商家', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: '意向商家', exact: true });
  const notes = sheet.getByLabel('沟通记录 *', { exact: true });
  await notes.fill('客户约定周五再次联系');
  await expect(notes).toHaveCSS('font-size', '16px');
  await expect(sheet.getByRole('button', { name: 'Close', exact: true })).toHaveCSS('width', '44px');
  await sheet.getByRole('button', { name: '保存跟进', exact: true }).click();
  await expect(page.getByText('模拟保存失败', { exact: true })).toBeVisible();
  await expect(notes).toHaveValue('客户约定周五再次联系');
  expect(writes).toEqual(['POST /api/v1/sales-leads/32/follow-up']);
  await page.keyboard.press('Escape');
  await card.getByRole('button', { name: '更多线索操作：意向商家', exact: true }).click();
  await page.getByRole('menuitem', { name: '准备报价', exact: true }).click();
  const quote = page.getByRole('dialog', { name: '成交审核 · 意向商家', exact: true });
  await expect(quote.getByRole('button', { name: '1 报价', exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
});

test('销售进入正式客户详情保留安全内部返回路径', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/sales-leads?view=leads`);
  const card = page.getByTestId('sales-lead-mobile-card').filter({ hasText: '已转客户商家' });
  await card.getByRole('button', { name: '查看客户', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('returnTo')).toBe('/sales-leads?view=leads');
  expect(new URL(page.url()).pathname).toBe('/customers');
  expect(writes).toEqual([]);
});
