import { expect, test, type Locator, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '手机销售测试主管', role: 'sales_manager', status: 'active' };

const merchant = {
  id: 21,
  business_name: 'Golden Dragon Restaurant',
  contact_name: '陈老板',
  phone: '(626) 555-0123',
  industry: '餐厅',
  country: 'US',
  state: 'CA',
  city: 'Los Angeles',
  address: '123 Main St, Los Angeles, CA 90012',
  website: 'https://example.com/a-very-long-merchant-page-that-must-not-expand-the-mobile-layout',
  data_source: 'manual',
  collected_at: '2026-08-16T09:00:00',
  pool_status: 'pending',
};

const lead = {
  id: 31,
  business_name: 'Happy Nails & Spa',
  contact_name: '王女士',
  phone: '+1 702-555-0199',
  industry: '美甲',
  country: 'US',
  state: 'NV',
  city: 'Las Vegas',
  source: 'merchant_pool',
  status: 'follow_up',
  assigned_sales_id: 1,
  assigned_sales_name: '手机销售测试主管',
  is_blacklisted: false,
  do_not_contact: false,
  next_follow_up_at: '2026-08-17T10:30:00',
  created_at: '2026-08-16T09:00:00',
};

const protectedLead = {
  ...lead,
  id: 32,
  business_name: 'Do Not Call Test Merchant',
  phone: '+1 702-555-0100',
  status: 'blocked',
  do_not_contact: true,
  do_not_contact_reason: '商家已明确拒绝',
  next_follow_up_at: undefined,
};

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function mockSalesApis(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'mobile-sales-token');
    window.localStorage.setItem('token', 'mobile-sales-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/app-config')) return fulfillJson(route, { items: {} });
    if (path === '/api/v1/merchant-pool/stats') return fulfillJson(route, { total: 1, pending: 1, isolated: 0, converted: 0, duplicates: 0, archived: 0 });
    if (path === '/api/v1/merchant-pool') return fulfillJson(route, { items: [merchant], total: 1 });
    if (path === '/api/v1/sales-leads/stats') return fulfillJson(route, { total: 2, assigned: 2, unassigned: 0, blacklisted: 0, do_not_contact: 1 });
    if (path === '/api/v1/sales-leads/assignees') return fulfillJson(route, [{ id: 1, name: '手机销售测试主管', role: 'sales_manager' }]);
    if (path === '/api/v1/sales-leads/dashboard/management') return fulfillJson(route, {
      metrics: { assigned: 1, completed: 1, completion_rate: 100, calls: 8, connected: 5, connection_rate: 62.5, interested: 2, interest_rate: 40, appointments: 1, appointment_rate: 20, converted: 0, conversion_rate: 0 },
      source_quality: [{ source: 'merchant_pool', total: 1, usable: 1, quality_rate: 100 }],
      salespeople: [{ salesperson: '手机销售测试主管', calls: 8, connected: 5, interested: 2, appointments: 1 }],
    });
    if (path === '/api/v1/sales-leads/dashboard/performance') return fulfillJson(route, {
      period: { days: Number(url.searchParams.get('days') || 30), start_date: '2026-07-18', end_date: '2026-08-16' },
      items: [{
        rank: 1, sales_employee_id: 1, salesperson: '手机销售测试主管', score: 86, confidence: '数据充足',
        score_breakdown: { execution: 22, discipline: 18, opportunity: 17, results: 21, documentation: 8 },
        metrics: { assigned: 10, completed: 9, calls: 18, connected: 11, interested: 4, appointments: 2, conversions: 1, completion_rate: 90, connection_rate: 61, interest_rate: 36, note_quality_rate: 80, overdue_followups: 1 },
        suggestions: ['继续优先处理今日到期回访，减少逾期。'],
      }],
    });
    if (path === '/api/v1/sales-leads/recovery/overview') return fulfillJson(route, { items: [], summary: { recoverable: 0, watch: 0, protected: 0, extended: 0, extension_requests: 0 } });
    if (path === '/api/v1/sales-leads') return fulfillJson(route, { items: [lead, protectedLead], total: 2 });
    if (path.endsWith('/call-history')) return fulfillJson(route, []);
    if (path === '/api/v1/product-plans') return fulfillJson(route, { business_lines: [], products: [], plans: [] });
    if (path === '/api/v1/sales-deal-controls/options') return fulfillJson(route, { employees: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, {});
  });
}

async function expectNoDocumentOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}

async function expectTouchTarget(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box?.height || 0).toBeGreaterThanOrEqual(44);
  expect(box?.width || 0).toBeGreaterThanOrEqual(44);
}

test('390px 商家池以卡片完成补资料与待分配，不暴露手机高风险批量操作', async ({ page }) => {
  await mockSalesApis(page);
  const dangerousRequests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'DELETE' || /\/merchant-pool\/(?:import|bulk-delete)/.test(path)) {
      dangerousRequests.push(`${request.method()} ${path}`);
    }
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/merchant-pool`);

  await expect(page.getByRole('heading', { name: '待清洗商家池' })).toBeVisible();
  await expect(page.getByTestId('merchant-pool-mobile-list')).toBeVisible();
  await expect(page.getByTestId('merchant-pool-desktop-table')).toHaveCount(0);
  const card = page.getByTestId('merchant-mobile-card');
  await expect(card).toContainText('Golden Dragon Restaurant');
  await expect(card).toContainText('+1 626-555-0123');
  await expect(card).toContainText('Los Angeles, CA');
  await expect(card).toContainText('123 Main St, Los Angeles, CA 90012');
  await expect(card).toContainText('manual');
  await expect(page.getByText('批量导入、永久删除与批量资料管理请使用电脑端完成。')).toBeVisible();
  await expect(page.getByRole('button', { name: '导入商家数据' })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /批量设置行业|批量删除|永久删除/ })).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);

  const queueButton = card.getByRole('button', { name: '加入待分配' });
  await expectTouchTarget(queueButton);
  await queueButton.click();
  await expect(page.getByText('已加入 1 条待分配商家')).toBeVisible();
  await expect(page.getByRole('button', { name: '确认分配' })).toBeVisible();

  await card.getByRole('button', { name: /更多商家操作/ }).click();
  await expect(page.getByRole('menuitem', { name: '补充资料' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: /销售智能分析/ })).toHaveCount(0);
  await expect(page.getByRole('menuitem', { name: /删除/ })).toHaveCount(0);
  expect(dangerousRequests).toEqual([]);
  await expectNoDocumentOverflow(page);
});

test('390px 销售线索直接提供拨号复制跟进，并用卡片呈现绩效排行榜', async ({ page }) => {
  await mockSalesApis(page);
  const consoleErrors: string[] = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/sales-leads`);

  await expect(page.getByRole('heading', { name: '电话销售中心' })).toBeVisible();
  await expect(page.getByTestId('sales-leads-mobile-list')).toBeVisible();
  await expect(page.getByTestId('sales-leads-desktop-table')).toHaveCount(0);
  const card = page.getByTestId('sales-lead-mobile-card').filter({ hasText: 'Happy Nails & Spa' });
  await expect(card).toContainText('Happy Nails & Spa');
  await expect(card).toContainText('下一步：按计划跟进');

  const dial = card.getByRole('button', { name: 'RingCentral', exact: true });
  const copy = card.getByRole('button', { name: '复制' });
  const followUp = card.getByRole('button', { name: '记录跟进' });
  await expectTouchTarget(dial);
  await expectTouchTarget(copy);
  await expectTouchTarget(followUp);
  await expect(card.getByRole('button', { name: '选择其他拨号方式' })).toHaveCount(0);

  await expect(page.getByTestId('sales-performance-mobile-list')).toBeVisible();
  await expect(page.getByTestId('sales-performance-desktop-table')).toBeHidden();
  await expect(page.getByTestId('sales-performance-mobile-list')).toContainText('#1 手机销售测试主管');
  await expect(page.getByTestId('sales-performance-mobile-list')).toContainText('86');

  const protectedCard = page.getByTestId('sales-lead-mobile-card').filter({ hasText: 'Do Not Call Test Merchant' });
  await expect(protectedCard.getByRole('button', { name: '拨号' })).toBeDisabled();
  await expect(protectedCard.getByRole('button', { name: '复制' })).toBeDisabled();
  await expect(protectedCard.getByRole('button', { name: '查看保护' })).toBeVisible();
  await expect(page.getByRole('button', { name: /批量分配|批量重新分配|批量回收|查看并处理/ })).toHaveCount(0);

  await card.getByRole('button', { name: /更多线索操作/ }).click();
  await expect(page.getByRole('menuitem', { name: '成交审核' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: '保护与黑名单设置' })).toBeVisible();
  await page.keyboard.press('Escape');

  await page.getByRole('button', { name: '新增线索' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect.poll(async () => (await dialog.boundingBox())?.width || 0).toBeGreaterThanOrEqual(389);
  await expect.poll(async () => (await dialog.boundingBox())?.height || 0).toBeGreaterThanOrEqual(843);
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeVisible();
  await expectNoDocumentOverflow(page);
  await expect(page.locator('.vite-error-overlay, #webpack-dev-server-client-overlay')).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test('1440px 商家池与销售中心继续保留完整桌面表格', async ({ page }) => {
  await mockSalesApis(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto(`${baseUrl}/merchant-pool`);
  await expect(page.getByTestId('merchant-pool-desktop-table')).toBeVisible();
  for (const header of ['商家名称', '商家电话', '商家位置', '地区', '来源', '操作']) {
    await expect(page.getByRole('columnheader', { name: header, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('columnheader', { name: /Google评分|官网|行业|清洗结果/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'AI 分析' })).toHaveCount(0);
  await expect(page.getByTestId('merchant-pool-mobile-list')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '导入商家数据' })).toBeVisible();
  await page.getByRole('button', { name: '导入商家数据' }).click();
  await expect(page.getByRole('heading', { name: '按固定模板导入商家' })).toBeVisible();
  await expect(page.getByText('商家名称、商家电话、商家位置、地区、来源')).toBeVisible();
  await expect(page.getByRole('button', { name: '下载固定模板' })).toBeVisible();

  await page.goto(`${baseUrl}/sales-leads`);
  await expect(page.getByTestId('sales-leads-desktop-table')).toBeVisible();
  await expect(page.getByTestId('sales-leads-mobile-list')).toBeHidden();
  await expect(page.getByTestId('sales-performance-desktop-table')).toBeVisible();
  await expect(page.getByTestId('sales-performance-mobile-list')).toBeHidden();
});

test('430px 销售核心页面保持卡片布局且无横向溢出', async ({ page }) => {
  await mockSalesApis(page);
  await page.setViewportSize({ width: 430, height: 932 });

  await page.goto(`${baseUrl}/merchant-pool`);
  await expect(page.getByTestId('merchant-pool-mobile-list')).toBeVisible();
  await expectNoDocumentOverflow(page);

  await page.goto(`${baseUrl}/sales-leads`);
  await expect(page.getByTestId('sales-leads-mobile-list')).toBeVisible();
  await expectNoDocumentOverflow(page);
});

test('快速切换搜索条件时商家池和销售线索只提交最新响应', async ({ page }) => {
  await mockSalesApis(page);
  await page.setViewportSize({ width: 390, height: 844 });

  let markOldMerchantStarted: (() => void) | undefined;
  const oldMerchantStarted = new Promise<void>(resolve => { markOldMerchantStarted = resolve; });
  await page.route(/\/api\/v1\/merchant-pool\?/, async route => {
    const search = new URL(route.request().url()).searchParams.get('search');
    if (search === '旧商家') {
      markOldMerchantStarted?.();
      await new Promise(resolve => setTimeout(resolve, 350));
      return fulfillJson(route, { items: [{ ...merchant, id: 91, business_name: '旧商家慢响应' }], total: 1 });
    }
    if (search === '新商家') return fulfillJson(route, { items: [{ ...merchant, id: 92, business_name: '新商家最新结果' }], total: 1 });
    return fulfillJson(route, { items: [merchant], total: 1 });
  });

  await page.goto(`${baseUrl}/merchant-pool`);
  const merchantSearch = page.getByPlaceholder('商家、电话或网站');
  await merchantSearch.fill('旧商家');
  await oldMerchantStarted;
  await merchantSearch.fill('新商家');
  await expect(page.getByText('新商家最新结果')).toBeVisible();
  await page.waitForTimeout(450);
  await expect(page.getByText('旧商家慢响应')).toHaveCount(0);

  let markOldLeadStarted: (() => void) | undefined;
  const oldLeadStarted = new Promise<void>(resolve => { markOldLeadStarted = resolve; });
  await page.route(/\/api\/v1\/sales-leads\?/, async route => {
    const search = new URL(route.request().url()).searchParams.get('search');
    if (search === '旧线索') {
      markOldLeadStarted?.();
      await new Promise(resolve => setTimeout(resolve, 350));
      return fulfillJson(route, { items: [{ ...lead, id: 93, business_name: '旧线索慢响应' }], total: 1 });
    }
    if (search === '新线索') return fulfillJson(route, { items: [{ ...lead, id: 94, business_name: '新线索最新结果' }], total: 1 });
    return fulfillJson(route, { items: [lead], total: 1 });
  });

  await page.goto(`${baseUrl}/sales-leads`);
  const leadSearch = page.getByPlaceholder('搜索商家、联系人、电话或城市');
  await leadSearch.fill('旧线索');
  await oldLeadStarted;
  await leadSearch.fill('新线索');
  await expect(page.getByText('新线索最新结果')).toBeVisible();
  await page.waitForTimeout(450);
  await expect(page.getByText('旧线索慢响应')).toHaveCount(0);
});

test('统计接口失败时商家池仍保留成功加载的核心列表', async ({ page }) => {
  await mockSalesApis(page);
  await page.route(/\/api\/v1\/merchant-pool\/stats/, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '统计暂不可用' }) }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/merchant-pool`);

  await expect(page.getByTestId('merchant-mobile-card')).toContainText('Golden Dragon Restaurant');
  await expect(page.getByText(/统计加载失败，已保留其他可用数据/).first()).toBeVisible();
});
