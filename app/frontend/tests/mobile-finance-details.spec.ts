import { expect, test, type Locator, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
if (!['127.0.0.1', 'localhost'].includes(new URL(baseUrl).hostname)) throw new Error('Finance detail tests require a local mock server');
const screenshotDir = process.env.T24_FINANCE_DETAILS_SCREENSHOT_DIR;
const tabs = [
  ['monthly_detail', '按月明细'], ['customer_profit', '客户利润'], ['refunds', '退款记录'],
  ['ad_funds', '投流月结'], ['customer_expense', '客户支出'], ['company_expense', '运营支出'], ['charts', '数据分析'],
] as const;
type Request = { method: string; path: string };
type Options = { missingAmount?: boolean; failedSource?: boolean; failedAudit?: boolean; role?: string };

async function fixture(page: Page, options: Options = {}) {
  await page.clock.install({ time: new Date('2026-10-10T12:00:00+08:00') });
  const employee = { id: 71, name: '手机明细模拟财务', role: options.role || 'finance', status: 'active' };
  const customers = [
    { id: 1, business_name: '模拟亏损客户甲', status: 'active' },
    { id: 2, business_name: '模拟盈利客户乙', status: 'active' },
    { id: 3, business_name: '模拟待结算客户丙', status: 'active' },
  ];
  const payment = (id: number, customerId: number, paid: number, management: number, ads: number, date: string, fee = 0) => ({
    id, customer_id: customerId, customer_name: customers[customerId - 1].business_name,
    amount_paid: paid, amount_due: paid + (id === 1 ? 50 : 0), outstanding_amount: id === 1 ? 50 : 0,
    management_amount: management, ads_recharge_amount: ads, stripe_fee_amount: fee, currency: 'USD',
    income_type: ads && management ? 'mixed_management_ads' : ads ? 'ads_fee' : management ? 'management_fee' : 'website_fee',
    payment_mode: 'manual_collection', payment_method: 'zelle', payment_date: date, product_name: '模拟服务',
  });
  const payments = [payment(1, 1, 1000, 600, 400, '2026-10-05', 30), payment(2, 2, 200, 200, 0, '2026-10-06'), payment(3, 3, 200, 0, 200, '2026-10-07'), payment(4, 2, 80, 0, 0, '2026-09-15')];
  const expense = (id: number, customerId: number, amount: number, currency: string, month: string, type = 'website_fee') => ({
    id, customer_id: customerId, customer_name: customers[customerId - 1].business_name, amount, currency,
    expense_type: type, expense_month: month, payment_date: `${month}-02`, notes: `模拟客户成本编号${id}`,
  });
  const expenses = [expense(1, 1, 700, 'USD', '2026-10'), expense(2, 1, 1000, 'CNY', '2026-10', 'design_fee'), expense(3, 2, 50, 'USD', '2026-10'), expense(4, 1, 999, 'USD', '2026-10', 'ads_fee'), expense(5, 2, 15, 'USD', '2026-09')];
  const companyExpenses: Record<string, unknown>[] = [
    { id: 1, amount: 30, currency: 'USD', category: 'software', expense_month: '2026-10', expense_date: '2026-10-02', notes: '模拟美元运营成本' },
    { id: 2, amount: 200, currency: 'CNY', category: 'salary', expense_month: '2026-10', expense_date: '2026-10-03', notes: '模拟人民币运营成本' },
    ...Array.from({ length: 22 }, (_, index) => ({ id: 10 + index, amount: 1, currency: 'CNY', category: 'software', expense_month: '2026-10', expense_date: '2026-10-04', notes: `模拟运营尾行${String(index + 1).padStart(2, '0')}` })),
    { id: 99, amount: 5, currency: 'USD', category: 'software', expense_month: '2026-09', expense_date: '2026-09-02', notes: '模拟九月运营成本' },
  ];
  if (options.missingAmount) companyExpenses.splice(2, 0, { id: 100, currency: 'CNY', category: 'software', expense_month: '2026-10', notes: '模拟金额未填写' });
  const refunds = [
    { id: 11, payment_id: 1, customer_id: 1, customer_name: customers[0].business_name, refund_amount: 100, currency: 'USD', stripe_fee_refunded_amount: 2, status: 'completed', refund_date: '2026-10-08', reason: '模拟已完成退款', provider_refund_id: 'mock-refund-completed' },
    { id: 12, payment_id: 1, customer_id: 1, customer_name: customers[0].business_name, refund_amount: 50, currency: 'USD', stripe_fee_refunded_amount: 0, status: 'pending', refund_date: '2026-10-09', reason: '模拟处理中退款' },
    { id: 13, payment_id: 1, customer_id: 1, customer_name: customers[0].business_name, refund_amount: 60, currency: 'USD', stripe_fee_refunded_amount: 0, status: 'failed', refund_date: '2026-10-09', reason: '模拟失败退款' },
    { id: 14, payment_id: 2, customer_id: 2, customer_name: customers[1].business_name, refund_amount: 90, currency: 'CNY', stripe_fee_refunded_amount: 0, status: 'failed', refund_date: '2026-10-09', reason: '模拟人民币退款' },
  ];
  const settlements = [
    { id: 21, customer_id: 1, customer_name: customers[0].business_name, year_month: '2026-10', currency: 'USD', status: 'closed', opening_balance: 10, funds_received: 360, actual_ad_spend: 300, customer_refund_amount: 0, recognized_spread_amount: 50, adjustment_amount: 0, closing_balance: 20, notes: '模拟美元已结算' },
    { id: 22, customer_id: 2, customer_name: customers[1].business_name, year_month: '2026-10', currency: 'CNY', status: 'closed', opening_balance: 100, funds_received: 1000, actual_ad_spend: 200, customer_refund_amount: 0, recognized_spread_amount: 100, adjustment_amount: 0, closing_balance: 800, notes: '模拟人民币已结算' },
    { id: 23, customer_id: 1, customer_name: customers[0].business_name, year_month: '2026-09', currency: 'USD', status: 'draft', opening_balance: 0, funds_received: 75, actual_ad_spend: 25, customer_refund_amount: 0, recognized_spread_amount: 10, adjustment_amount: 0, closing_balance: 40, notes: '模拟草稿月结' },
  ];
  const entries = [
    { id: 31, customer_id: 1, service_month: '2026-10', commission_amount: 20, currency: 'USD', status: 'confirmed' },
    { id: 32, customer_id: 1, service_month: '2026-10', commission_amount: 999, currency: 'USD', status: 'draft' },
    { id: 33, customer_id: 1, service_month: '2026-10', commission_amount: 500, currency: 'CNY', status: 'confirmed' },
  ];
  const entities: Record<string, unknown[]> = { customers, payments, expenses, company_expenses: companyExpenses, subscriptions: [], deals: [] };
  const requests: Request[] = [];
  const state = { failedSource: !!options.failedSource, failedAudit: !!options.failedAudit };
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'local-finance-details-fixture');
    localStorage.setItem('token', 'local-finance-details-fixture');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    requests.push({ method: req.method(), path });
    if (req.method() !== 'GET') return route.fulfill({ status: 409, json: { detail: '浏览模拟数据禁止写入' } });
    const entity = path.match(/\/entities\/([^/]+)(?:\/|$)/)?.[1];
    if (state.failedSource && entity === 'company_expenses') return route.fulfill({ status: 400, json: { detail: '模拟运营支出读取失败' } });
    if (state.failedAudit && path.includes('/reports/profit-monthly.json')) return route.fulfill({ status: 400, json: { detail: '模拟审计报表读取失败' } });
    const data = path.endsWith('/emp-auth/me') ? employee
      : path === '/api/v1/app-config' ? { items: {} }
      : path.includes('/app-config/') ? { value: {} }
      : path.includes('/reports/profit-monthly.json') ? [{ year_month: '2026-10', revenue: 9999, profit: -777 }]
      : path.startsWith('/api/v1/deductions-monthly') ? [{ year_month: '2026-10', rate: 0.1 }, { year_month: '2026-09', rate: 0.1 }]
      : path.endsWith('/finance/refunds') ? { items: refunds }
      : path.endsWith('/finance/ad-fund-settlements') ? { items: settlements }
      : path.endsWith('/commissions/dashboard') ? { entries }
      : path.endsWith('/product-plans') ? { business_lines: [], products: [], plans: [] }
      : entity ? { items: entities[entity] || [], total: (entities[entity] || []).length }
      : { items: [], total: 0 };
    return route.fulfill({ json: data });
  });
  return { requests, state };
}

const detailsRegion = (page: Page) => page.getByRole('region', { name: '手机财务明细', exact: true });
const record = (page: Page, text: string) => detailsRegion(page).locator('.mfd-record').filter({ hasText: text });
async function openRecord(row: Locator) { await row.locator(':scope > summary').click(); await expect(row).toHaveAttribute('open', ''); }
async function openMonthlyRecord(page: Page, month: string) {
  await detailsRegion(page).getByRole('button', { name: `打开${month}明细`, exact: true }).click();
  const detail = detailsRegion(page).getByRole('region', { name: `${month}月度账目详情`, exact: true });
  await expect(detail).toBeVisible();
  for (const group of await detail.locator('.mfd-monthly-group').all()) {
    if (!await group.evaluate(el => (el as HTMLDetailsElement).open)) await group.locator(':scope > summary').click();
  }
  return detail;
}
async function expectField(row: Locator, label: string, value: string) {
  await expect(row.locator('dl > div').filter({ has: row.page().getByText(label, { exact: true }) }).locator('dd')).toHaveText(value);
}
function readOnly(requests: Request[]) {
  expect(requests.filter(req => req.method !== 'GET')).toEqual([]);
  expect(requests.some(req => /deductions-monthly\/ensure|reconciliation\/run/.test(req.path))).toBe(false);
}
async function noOverflow(page: Page) {
  const geometry = await page.evaluate(() => ({ viewport: innerWidth, html: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(geometry.html).toBeLessThanOrEqual(geometry.viewport);
  expect(geometry.body).toBeLessThanOrEqual(geometry.viewport);
}

for (const width of [320, 390, 430]) {
  test(`${width}px七个财务深链接显示真实明细且浏览无写入`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const { requests } = await fixture(page);
    for (const [tab, title] of tabs) {
      await page.goto(`${baseUrl}/finance?tab=${tab}`);
      const region = detailsRegion(page);
      await expect(region.getByRole('heading', { name: title, exact: true, level: 1 })).toBeVisible();
      await expect(region.locator('.mfd-record').first()).toBeVisible();
      await expect(region.getByRole('button', { name: '本月', exact: true })).toHaveAttribute('aria-pressed', 'true');
      if (tab === 'monthly_detail') await openMonthlyRecord(page, '2026-10');
      else await openRecord(region.locator('.mfd-record').first());
      await noOverflow(page);
      if (screenshotDir && width === 390 && ['monthly_detail', 'refunds', 'company_expense'].includes(tab)) await page.screenshot({ path: `${screenshotDir}/local-mock-${tab}-${width}.png`, fullPage: true });
    }
    readOnly(requests);
  });
}

test('月度明细保留退款、投流、手续费和佣金原口径，搜索不替代汇总', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=monthly_detail`);
  const row = await openMonthlyRecord(page, '2026-10');
  for (const [label, value] of [
    ['月份', '2026-10'], ['关账状态', '未关账'],
    ['总收款 · USD', '$1,400'], ['退款 · USD', '$100'], ['净收款 · USD', '$1,300'],
    ['服务收入 · USD', '$790'], ['管理费收入 · USD', '$740'], ['投流客户资金 · USD', '$560'],
    ['确认投流差价 · USD', '$50'], ['广告实支 · USD', '$300'], ['投流结余 · USD', '$20'],
    ['管理费扣点率', '10.0%'], ['Stripe 手续费 · USD', '$28'], ['管理费扣点 · USD', '$74'], ['总扣点 · USD', '$74'],
    ['客户成本 · USD', '$750'], ['运营支出 · USD', '$30'], ['渠道佣金 · USD', '$20'], ['总成本 · USD', '$828'], ['经营利润 · USD', '$-112'],
  ]) await expectField(row, label, value);
  await expect(row.locator('dt')).toHaveCount(20);
  await row.getByRole('button', { name: '返回按月明细', exact: true }).click();
  await expect(detailsRegion(page).getByRole('button', { name: '打开2026-10明细', exact: true })).toBeFocused();
  const summaries = detailsRegion(page).locator('.mfd-summaries');
  const before = await summaries.innerText();
  await detailsRegion(page).getByRole('searchbox', { name: '搜索当前明细' }).fill('不存在的模拟记录');
  await expect(detailsRegion(page).getByText('没有匹配的明细', { exact: true })).toBeVisible();
  expect(await summaries.innerText()).toBe(before);
  expect(before).toContain('$-112');
  expect(before).not.toContain('$-777');
  readOnly(requests);
});

test('客户负利润与人民币成本分开，未完成退款和草稿佣金不计入利润', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=customer_profit`);
  const row = record(page, '模拟亏损客户甲');
  await openRecord(row);
  await expect(row.getByText('亏损预警', { exact: true }).first()).toBeVisible();
  for (const [label, value] of [
    ['服务收入 · USD', '$590'], ['管理费扣点 · USD', '$54'], ['Stripe 手续费 · USD', '$28'],
    ['渠道佣金 · USD', '$20'], ['客户成本 · USD', '$700'], ['客户成本 · CNY', '¥1,000'],
    ['客户利润 · USD', '$-212'], ['欠款 · USD', '$50'],
  ]) await expectField(row, label, value);
  await expect(record(page, '模拟盈利客户乙').locator('summary')).toContainText('$130');
  readOnly(requests);
});

test('退款逐条显示完成、处理中、失败和原币种，凭证展开可读', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=refunds`);
  const region = detailsRegion(page);
  await expect(region.getByText('共 4 条', { exact: true })).toBeVisible();
  for (const [index, state, amount] of [[0, '已完成', '$100'], [1, '处理中', '$50'], [2, '失败', '$60'], [3, '失败', '¥90']] as const) {
    const row = region.locator('.mfd-record').nth(index);
    await expect(row.locator(':scope > summary')).toContainText(state);
    await expect(row.locator(':scope > summary')).toContainText(amount);
    await openRecord(row);
  }
  await expectField(region.locator('.mfd-record').first(), '退款凭证', 'mock-refund-completed');
  await expectField(region.locator('.mfd-record').nth(3), '币种', 'CNY');
  await noOverflow(page);
  readOnly(requests);
});

test('投流显示未结资金、原币种月结和草稿，全部时间不把草稿确认收益', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=ad_funds`);
  const region = detailsRegion(page);
  await expect(region.getByRole('heading', { name: '待月结', exact: true })).toBeVisible();
  await expect(record(page, '模拟待结算客户丙').locator('summary')).toContainText('$200');
  const cny = record(page, '模拟人民币已结算');
  await openRecord(cny);
  await expectField(cny, '币种', 'CNY');
  await expectField(cny, '确认差价 · CNY', '¥100');
  await region.getByRole('button', { name: '全部', exact: true }).click();
  const draft = record(page, '模拟草稿月结');
  await openRecord(draft);
  await expectField(draft, '状态', '草稿');
  await expectField(draft, '结余 · USD', '$40');
  readOnly(requests);
});

test('客户成本保留人民币和历史投流明细，历史投流不重复计入美元成本', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=customer_expense`);
  const region = detailsRegion(page);
  await expect(region.locator('.mfd-summaries')).toContainText('$750');
  const legacy = record(page, '模拟客户成本编号4');
  await openRecord(legacy);
  await expectField(legacy, '计入口径', '历史归档，不重复计入利润');
  await expect(legacy.getByRole('button', { name: '编辑客户支出', exact: true })).toHaveCount(0);
  await expect(legacy.getByRole('button', { name: '删除记录', exact: true })).toHaveCount(0);
  const cny = record(page, '模拟客户成本编号2');
  await openRecord(cny);
  await expectField(cny, '金额 · CNY', '¥1,000');
  readOnly(requests);
});

test('超过20笔运营支出末条可达，搜索和加载不改变美元人民币分列合计', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=company_expense`);
  const region = detailsRegion(page);
  await expect(region.getByText('共 24 条', { exact: true })).toBeVisible();
  await expect(region.getByText('已显示 20 条', { exact: true })).toBeVisible();
  const before = await region.locator('.mfd-summaries').innerText();
  expect(before).toContain('$30');
  expect(before).toContain('¥222');
  await region.getByRole('button', { name: /^加载更多/ }).click();
  await expect(region.getByText('已显示 24 条', { exact: true })).toBeVisible();
  const tail = record(page, '模拟运营尾行22');
  await openRecord(tail);
  await expectField(tail, '金额 · CNY', '¥1');
  expect(await region.locator('.mfd-summaries').innerText()).toBe(before);
  await region.getByRole('searchbox', { name: '搜索当前明细' }).fill('模拟运营尾行22');
  await expect(region.getByText('找到 1 条', { exact: true })).toBeVisible();
  expect(await region.locator('.mfd-summaries').innerText()).toBe(before);
  await noOverflow(page);
  readOnly(requests);
});

test('缺失金额逐条标记待补充，汇总待核对而非伪装准确零', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const { requests } = await fixture(page, { missingAmount: true });
  await page.goto(`${baseUrl}/finance?tab=company_expense`);
  const region = detailsRegion(page);
  await expect(region.getByText('共 25 条', { exact: true })).toBeVisible();
  await expect(region.getByText('1 条记录的金额待补充，当前汇总需核对。', { exact: true })).toBeVisible();
  await expect(region.locator('.mfd-summaries').getByText('待核对', { exact: true })).toHaveCount(2);
  await region.getByRole('searchbox', { name: '搜索当前明细' }).fill('模拟金额未填写');
  const missing = region.locator('.mfd-record');
  await openRecord(missing);
  await expectField(missing, '金额 · CNY', '待补充');
  await expect(region.locator('.mfd-summaries').getByText('待核对', { exact: true })).toHaveCount(2);
  readOnly(requests);
});

test('月份与全部筛选沿用真实日期范围，切换重置加载数且不污染旧流水视图', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=company_expense`);
  const region = detailsRegion(page);
  await region.getByRole('button', { name: /^加载更多/ }).click();
  await expect(region.getByText('已显示 24 条', { exact: true })).toBeVisible();
  await region.getByRole('button', { name: '上月', exact: true }).click();
  await expect(region.getByText('共 1 条', { exact: true })).toBeVisible();
  await expect(record(page, '模拟九月运营成本').locator('summary')).toContainText('$5');
  await region.getByRole('button', { name: '全部', exact: true }).click();
  await expect(region.getByText('共 25 条', { exact: true })).toBeVisible();
  await expect(region.getByText('已显示 20 条', { exact: true })).toBeVisible();
  await region.getByLabel('账目月份', { exact: true }).fill('2026-09');
  await expect(region.getByText('共 1 条', { exact: true })).toBeVisible();
  await page.goto(`${baseUrl}/finance?tab=monthly_detail`);
  const september = await openMonthlyRecord(page, '2026-09');
  await expectField(september, '经营利润 · USD', '$60');
  await page.goto(`${baseUrl}/finance?tab=income`);
  const ledger = page.getByRole('region', { name: '流水列表' });
  await expect(ledger.getByText('已显示 15 / 共 30 条', { exact: true })).toBeVisible();
  await expect(ledger.getByText('模拟待结算客户丙', { exact: true })).toBeVisible();
  await expect(ledger.getByText('模拟九月运营成本', { exact: true })).toHaveCount(0);
  readOnly(requests);
});

test('月份输入聚焦时可见，键盘选择与月度列表返回保留月份', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const { requests } = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=monthly_detail`);
  const region = detailsRegion(page);
  const input = region.getByLabel('账目月份', { exact: true });
  await input.focus();
  await expect(input).toBeFocused();
  await expect(input).toHaveCSS('opacity', '1');
  await input.press('ArrowUp');
  await expect(input).toHaveCSS('opacity', '1');
  await input.fill('2026-09');
  await expect(region.getByRole('button', { name: '打开2026-09明细', exact: true })).toBeVisible();
  await expect(region.getByRole('button', { name: '打开2026-10明细', exact: true })).toHaveCount(0);
  const detail = await openMonthlyRecord(page, '2026-09');
  await expectField(detail, '经营利润 · USD', '$60');
  await detail.getByRole('button', { name: '返回按月明细', exact: true }).click();
  await expect(input).toHaveValue('2026-09');
  const bounds = await region.locator('.mobile-finance-date-filter').evaluate(el => {
    const controls = Array.from(el.children).map(child => child.getBoundingClientRect());
    return controls.map(rect => ({ top: rect.top, bottom: rect.bottom }));
  });
  expect(bounds[0].top).toBe(bounds[1].top);
  expect(bounds[0].bottom).toBe(bounds[1].bottom);
  await noOverflow(page);
  readOnly(requests);
});

test('数据分析沿用月度美元趋势与原币种支出分类，审计失败不能伪装已核对', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page, { failedAudit: true });
  await page.goto(`${baseUrl}/finance?tab=charts`);
  const trend = record(page, '经营趋势 · USD');
  await openRecord(trend);
  await expectField(trend, '经营利润 · USD', '$-112');
  const region = detailsRegion(page);
  await expect(region.locator('.mfd-summaries')).toContainText('$30');
  await expect(region.locator('.mfd-summaries')).toContainText('¥222');
  await region.getByText('口径说明', { exact: true }).click();
  await expect(region.getByText(/月度审计报告暂时无法读取/)).toBeVisible();
  await expect(region.getByText('月度审计统一口径', { exact: true })).toHaveCount(0);
  readOnly(requests);
});

test('首次读取失败不显示假零，重新加载恢复；后台失败保留旧值并明确提示', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests, state } = await fixture(page, { failedSource: true });
  await page.goto(`${baseUrl}/finance?tab=company_expense`);
  const region = detailsRegion(page);
  await expect(region.getByRole('alert')).toContainText('数据暂时无法加载');
  await expect(region.locator('.mfd-summaries')).toHaveCount(0);
  await expect(region.locator('.mfd-record')).toHaveCount(0);
  state.failedSource = false;
  await region.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(region.getByText('共 24 条', { exact: true })).toBeVisible();
  const before = await region.locator('.mfd-summaries').innerText();
  state.failedSource = true;
  await page.clock.runFor(30_100);
  await expect(region.getByRole('alert')).toContainText('当前显示上次同步数据');
  expect(await region.locator('.mfd-summaries').innerText()).toBe(before);
  readOnly(requests);
});

test('销售角色没有财务页面权限时七项深链接均不可越权读取', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { requests } = await fixture(page, { role: 'sales' });
  for (const [tab] of tabs) {
    await page.goto(`${baseUrl}/finance?tab=${tab}`);
    await expect(detailsRegion(page)).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible();
  }
  expect(requests.filter(req => /entities\/(payments|expenses|company_expenses)|finance\/(refunds|ad-fund-settlements)|profit-monthly/.test(req.path))).toEqual([]);
  readOnly(requests);
});
