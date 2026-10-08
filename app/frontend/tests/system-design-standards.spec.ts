import { expect, test, type Locator, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5188';
const employee = { id: 1, name: '统一样式测试管理员', role: 'super_admin', status: 'active' };
const customer = { id: 101, business_name: '字号核对餐厅', customer_code: 'C101', contact_name: '陈老板', phone: '555-0101', status: 'closed', sales_person: employee.name, industry: 'restaurant' };
const merchant = { id: 21, business_name: '布局核对商家', contact_name: '陈老板', phone: '555-0102', industry: '餐厅', country: 'US', city: 'Los Angeles', state: 'CA', address: '123 Main St', pool_status: 'pending', data_source: 'manual', converted_lead_id: null, isolation_reason: null };
const lead = { id: 31, business_name: '中文跟进布局核对商家', phone: '555-0103', contact_name: '张老板', industry: '餐饮', city: 'Los Angeles', state: 'CA', status: 'interested', assigned_sales_id: 1, assigned_sales_name: employee.name, next_follow_up_at: '2026-10-01T09:30:00', last_contact_at: '2026-09-30T09:30:00', created_at: '2026-09-01', do_not_contact: false, is_blacklisted: false };

async function seed(page: Page) {
  const writes: string[] = [];
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'design-standards-local-test');
    localStorage.setItem('token', 'design-standards-local-test');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') writes.push(path);
    let data: unknown = { items: [], total: 0 };
    if (path === '/api/config') data = { API_BASE_URL: base };
    else if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    else if (/\/entities\/customers(?:\/all)?$/.test(path)) data = { items: [customer], total: 1 };
    else if (path.includes('/entities/employees')) data = { items: [employee], total: 1 };
    else if (path.includes('/entities/deals')) data = { items: [{ id: 201, customer_id: 101, customer_name: customer.business_name, sales_name: employee.name, package_name: '基础服务', product_type: 'social_media', billing_cycle: 'monthly', deal_amount: 428, deal_date: '2026-10-01', is_paid: true, is_handed_over: false, is_transferred_ops: false }], total: 1 };
    else if (path.includes('/entities/payments')) data = { items: [{ id: 301, customer_id: 101, customer_name: customer.business_name, amount_paid: 428, amount_due: 428, outstanding_amount: 0, management_amount: 428, currency: 'USD', payment_date: '2026-10-01', income_type: 'management_fee', payment_mode: 'manual_collection', payment_method: 'zelle' }], total: 1 };
    else if (path.includes('/entities/tasks')) data = { items: [{ id: 401, title: '核对上线资料与下一步', customer_id: 101, customer_name: customer.business_name, assignee_name: employee.name, task_type: 'follow_up', status: 'pending', priority: 'high', due_date: '2026-10-01', notes: '下一步：向客户核对平台资料' }], total: 1 };
    else if (path === '/api/v1/merchant-pool') data = { items: [merchant], total: 1, skip: 0, limit: 20 };
    else if (path === '/api/v1/merchant-pool/stats') data = { total: 1, pending: 1, converted: 0, isolated: 0, duplicates: 0, archived: 0 };
    else if (path === '/api/v1/sales-leads') data = { items: [lead], total: 1 };
    else if (path === '/api/v1/sales-leads/stats') data = { total: 1, assigned: 1, unassigned: 0, blacklisted: 0, do_not_contact: 0 };
    else if (path === '/api/v1/sales-leads/assignees') data = [employee];
    else if (path === '/api/v1/sales-intelligence/leads') data = { items: [{ ...lead, calls: 3, connected: 2, records: 2, manual_records: 0, outcomes: { interested: 1, callback: 1 }, potential: 'priority', potential_label: '优先推进', rationale: ['需要继续联系'], first_interest_record_number: 2, first_interest_call_number: 3, overdue: true, turned_positive: false, profile: { next_step: '核对预算并约定下一次联系' } }] };
    else if (/sales-leads\/(?:dashboard|recovery)\//.test(path)) data = null;
    else if (path.includes('/reports/profit-monthly.json')) data = [];
    else if (path.includes('/deductions-monthly')) data = [{ year_month: '2026-10', rate: 0.15 }];
    else if (path.endsWith('/commissions/dashboard')) data = { summary: { partner_count: 0, active_partner_count: 0, pending_count: 0, currencies: {}, accounting_rule: '实收记收入，佣金独立核算', quality: { issue_count: 0, high_count: 0, coverage_rate: 100, covered_count: 0, examined_count: 0 } }, partners: [], agreements: [], attributions: [], quality_issues: [], entries: [] };
    else if (path.endsWith('/commissions/options')) data = { employees: [], customers: [], products: [], engagements: [], business_lines: [] };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return writes;
}

async function styles(locator: Locator) {
  return locator.evaluate(async element => {
    // Portal opening scales its hit area briefly. Measure the settled target, not an animation frame.
    const animations = new Set<Animation>();
    for (let ancestor: Element | null = element; ancestor; ancestor = ancestor.parentElement) {
      for (const animation of ancestor.getAnimations()) {
        if (animation.effect?.getTiming().iterations !== Infinity) animations.add(animation);
      }
    }
    await Promise.all([...animations].map(animation => animation.finished.catch(() => undefined)));
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    return { size: style.fontSize, line: style.lineHeight, height: box.height, minHeight: style.minHeight, paddingTop: style.paddingTop, paddingBottom: style.paddingBottom, variant: style.fontVariantNumeric };
  });
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

const routes = [
  ['/sales-leads', '销售线索'], ['/merchant-pool', '商家公海'], ['/employees', '员工管理'],
  ['/customers', '客户中心'], ['/deals', '成交管理'], ['/finance', '财务结算'], ['/commissions', '渠道与分润'],
];

test('桌面各业务页面共用标题、表格正文与表头尺度，保持页面无横向溢出', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const [path] of routes) {
    await page.goto(`${base}${path}`);
    const heading = page.locator('main .app-page h1, .app-page-title h2, .sc-section-heading h2, .customer-360-hero-copy h2, .commission-heading h1').first();
    await expect(heading, `${path}桌面主标题`).toBeVisible();
    await expect.poll(async () => (await styles(heading)).size).toBe('28px');
    expect((await styles(heading)).line).toBe('36px');
    const table = page.locator('.app-page table:visible').first();
    if (await table.count()) {
      const head = table.locator('th').first();
      if (await head.count()) expect((await styles(head)).size).toBe('12px');
      const cell = table.locator('tbody td').first();
      if (await cell.count()) {
        const measured = await styles(cell);
        expect(measured.size).toBe('14px');
        expect(measured.line).toBe('22px');
      }
    }
    await noOverflow(page);
  }
  expect(writes.filter(path => path !== '/api/v1/deductions-monthly/ensure')).toEqual([]);
});

test('手机标题24/32，页面输入至少44px且16px字号，保留可见操作与无横向溢出', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [path] of routes) {
    await page.goto(`${base}${path}`);
    const heading = page.locator('main .app-page h1, .app-page-title h2, .sc-section-heading h2, .customer-360-hero-copy h2, .commission-heading h1').first();
    await expect(heading, `${path}手机主标题`).toBeVisible();
    expect((await styles(heading)).size).toBe('24px');
    expect((await styles(heading)).line).toBe('32px');
    for (const input of await page.locator('.app-page .t24-input:visible, .app-page .t24-native-select:visible').all()) {
      const measured = await styles(input);
      expect(measured.size).toBe('16px');
      expect(measured.height).toBeGreaterThanOrEqual(44);
    }
    for (const button of await page.locator('.app-page .t24-button:visible:not(.t24-button-link)').all()) expect((await styles(button)).height).toBeGreaterThanOrEqual(44);
    await noOverflow(page);
  }
  expect(writes.filter(path => path !== '/api/v1/deductions-monthly/ensure')).toEqual([]);
});

test('销售累计结果标签可读，截止与下一步14/22，操作36px且紧凑模式保留信息层次', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/sales-leads`);
  const table = page.getByTestId('sales-leads-desktop-table');
  await expect(table.getByText('有意向 1', { exact: true })).toBeVisible();
  const badge = table.getByText('有意向 1', { exact: true });
  expect(await styles(badge)).toMatchObject({ size: '12px', line: '18px' });
  expect(await styles(table.locator('.sl-next-step strong'))).toMatchObject({ size: '14px', line: '22px' });
  expect(await styles(table.getByText('核对预算并约定下一次联系', { exact: true }))).toMatchObject({ size: '14px', line: '22px' });
  expect((await styles(table.getByRole('button', { name: '档案', exact: true }))).height).toBeGreaterThanOrEqual(36);
  const cell = table.locator('tbody td').last();
  expect((await styles(cell)).paddingTop).toBe('12px');
  await page.getByRole('button', { name: '紧凑', exact: true }).click();
  expect((await styles(cell)).paddingTop).toBe('8px');
  await expect(table.getByText('核对预算并约定下一次联系', { exact: true })).toBeVisible();
  await expect(table.getByRole('button', { name: '档案', exact: true })).toBeVisible();
  expect(writes).toEqual([]);
});

test('商家表单与菜单portal继承同一尺度，桌面和手机均可取消且不提交', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/merchant-pool`);
  await page.getByRole('button', { name: `更多商家操作：${merchant.business_name}` }).click();
  const item = page.getByRole('menuitem', { name: '归档记录' });
  await expect(item).toBeVisible();
  expect((await styles(item)).size).toBe('14px');
  expect((await styles(item)).minHeight).toBe('36px');
  expect((await styles(item)).height).toBeGreaterThanOrEqual(36);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: `核对资料：${merchant.business_name}`, exact: true }).click();
  await page.getByRole('button', { name: '补充资料', exact: true }).click();
  const dialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '补充商家资料并重新清洗' }) });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(element => !!element.closest('.t24-system'))).toBe(false);
  expect(await styles(dialog.getByRole('heading', { name: '补充商家资料并重新清洗' }))).toMatchObject({ size: '20px', line: '28px' });
  expect(await styles(dialog.locator('.t24-input').first())).toMatchObject({ size: '14px', height: 40 });
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: `核对资料：${merchant.business_name}`, exact: true }).click();
  const review = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '核对商家资料', exact: true }) });
  await expect(review).toBeVisible();
  await review.getByRole('button', { name: '补充资料', exact: true }).click();
  await expect(dialog).toBeVisible();
  expect(await styles(dialog.locator('.t24-input').first())).toMatchObject({ size: '16px', height: 44 });
  expect((await styles(dialog.getByRole('button', { name: '取消', exact: true }))).height).toBeGreaterThanOrEqual(44);
  await noOverflow(page);
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('成交金额与付款状态原样保留，状态至少12px，金额采用等宽数字且无写入', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/deals`);
  const amount = page.getByRole('cell', { name: '$428', exact: true });
  await expect(amount).toBeVisible();
  expect((await styles(amount)).size).toBe('14px');
  expect((await styles(amount)).variant).toContain('tabular-nums');
  const paid = page.getByRole('cell', { name: '已付', exact: true }).locator('.t24-badge');
  await expect(paid).toBeVisible();
  expect(await styles(paid)).toMatchObject({ size: '12px', line: '18px' });
  expect((await styles(paid)).height).toBeGreaterThanOrEqual(24);
  expect(writes).toEqual([]);
});
