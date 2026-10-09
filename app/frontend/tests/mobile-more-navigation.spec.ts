import { expect, test, type Locator, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
if (!['127.0.0.1', 'localhost'].includes(new URL(baseUrl).hostname)) throw new Error('More navigation tests require a local fixture server');
const screenshotDir = process.env.T24_MORE_SCREENSHOT_DIR;
type Role = 'admin' | 'sales' | 'sales_partner';

async function installApi(page: Page, role: Role) {
  const employee = { id: 41, name: '更多导航模拟账号', role, status: 'active' };
  const requests: { method: string; path: string }[] = [];
  await page.addInitScript(emp => {
    sessionStorage.setItem('emp_auth_token', 'mobile-more-local-fixture');
    sessionStorage.setItem('token', 'mobile-more-local-fixture');
    sessionStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ method: request.method(), path });
    if (request.method() !== 'GET') return route.fulfill({ status: 409, json: { detail: '导航测试禁止业务写入' } });
    const data = path.endsWith('/emp-auth/me') ? employee
      : path === '/api/v1/app-config' ? { items: {} }
      : path.startsWith('/api/v1/app-config/') ? { value: {} }
      : path.endsWith('/reports/rmb-profit-estimate') ? { definition: '本地模拟计算口径', usd_definition: '本地模拟美元口径', payroll_note: '本地模拟工资说明', start_date: '2026-01-01', end_date: '2026-10-10', fallback_exchange_rate: 6.7, rows: [], quarterly: [], yearly: [], summary: { period: '模拟期间', month_count: 0, usd_operating_balance: 0, usd_converted_cny: 0, cny_operating_income: 0, cny_actual_expense: 0, estimated_profit_cny: 0, profitable_months: 0, loss_months: 0, break_even_months: 0 } }
      : path.includes('/reports/profit-monthly.json') ? []
      : path.startsWith('/api/v1/deductions-monthly') ? []
      : path.endsWith('/ringcentral/status') ? { configured: false, connected: false }
      : path.endsWith('/commissions/dashboard') ? { entries: [] }
      : path.endsWith('/commissions/my-dashboard') ? { partner: { id: 1, name: '模拟渠道' }, summary: { currencies: {} }, customers: [], entries: [], agreements: [] }
      : path.endsWith('/product-plans') ? { business_lines: [], products: [], plans: [] }
      : { items: [], total: 0 };
    return route.fulfill({ json: data });
  });
  return requests;
}

const more = (page: Page) => page.getByRole('region', { name: '更多功能', exact: true });
const bottom = (page: Page) => page.getByRole('navigation', { name: '手机主导航', exact: true });
const groupLink = (page: Page, label: string) => more(page).getByRole('link', { name: `${label}，查看全部功能`, exact: true });
const leafLink = (page: Page, label: string) => more(page).getByRole('link', { name: `打开${label}`, exact: true });
const groups = ['销售中心', '客户中心', '任务交付', '财务结算', '渠道分润', '经营中心', '组织设置'];

async function expectNoOverflow(page: Page) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(sizes.document).toBeLessThanOrEqual(sizes.viewport);
  expect(sizes.body).toBeLessThanOrEqual(sizes.viewport);
}

async function expectTouchable(target: Locator) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(44);
  const hit = await target.evaluate(element => {
    const box = element.getBoundingClientRect();
    const point = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return Boolean(point && (point === element || element.contains(point)));
  });
  expect(hit).toBe(true);
}

function expectReadOnly(requests: { method: string; path: string }[]) {
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
  expect(requests.some(request => /deductions-monthly\/ensure|workbench\/prepare/.test(request.path))).toBe(false);
}

for (const { width, height } of [{ width: 320, height: 844 }, { width: 390, height: 844 }, { width: 430, height: 844 }, { width: 320, height: 568 }]) {
  test(`${width}px管理员全部分组与财务末项可点击，无溢出或底栏遮挡（高度 ${height}px）`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const requests = await installApi(page, 'admin');
    await page.goto(`${baseUrl}/more`);
    await expect(more(page).getByRole('heading', { name: '更多', level: 1, exact: true })).toBeVisible();
    await expect(bottom(page).getByRole('button', { name: '更多', exact: true })).toHaveAttribute('aria-current', 'page');
    for (const label of groups) await expectTouchable(groupLink(page, label));
    if (height === 568) expect(await page.locator('.app-main').evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    await expectNoOverflow(page);
    await groupLink(page, '财务结算').click();
    await expect(page).toHaveURL(/\/more\?group=finance$/);
    await expect(more(page).getByRole('heading', { name: '财务结算', level: 1, exact: true })).toBeVisible();
    await expectTouchable(leafLink(page, '人民币利润预估'));
    if (height === 568) expect(await page.locator('.app-main').evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    await leafLink(page, '人民币利润预估').click();
    await expect(page).toHaveURL(/\/rmb-profit$/);
    await expect(page.getByRole('heading', { name: '人民币利润预估', exact: true })).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(/\/more\?group=finance$/);
    await expectTouchable(more(page).getByRole('button', { name: '返回全部功能', exact: true }));
    await more(page).getByRole('button', { name: '返回全部功能', exact: true }).click();
    await expect(page).toHaveURL(/\/more$/);
    await expectNoOverflow(page);
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-more-groups-${width}${height === 568 ? 'x568' : ''}.png`, fullPage: true });
    expectReadOnly(requests);
  });
}

test('分组、真实财务入口和浏览器返回保留导航层级', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, 'admin');
  await page.goto(`${baseUrl}/apps`);
  await bottom(page).getByRole('button', { name: '更多', exact: true }).click();
  await expect(page).toHaveURL(/\/more$/);
  await groupLink(page, '财务结算').click();
  await leafLink(page, '应收欠款').click();
  await expect(page).toHaveURL(/\/finance\?tab=receivables$/);
  await expect(page.getByRole('region', { name: '应收列表', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/more\?group=finance$/);
  await expect(leafLink(page, '应收欠款')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/more$/);
  await expect(groupLink(page, '财务结算')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/apps$/);
  expectReadOnly(requests);
});

test('叶页顶部返回和分组返回不制造重复历史或再次进入叶页', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, 'admin');
  await page.goto(`${baseUrl}/apps`);
  await bottom(page).getByRole('button', { name: '更多', exact: true }).click();
  await groupLink(page, '销售中心').click();
  await leafLink(page, '知识库').click();
  await expect(page).toHaveURL(/\/sales-knowledge$/);
  await page.getByRole('button', { name: '返回功能列表', exact: true }).click();
  await expect(page).toHaveURL(/\/more\?group=sales$/);
  await more(page).getByRole('button', { name: '返回全部功能', exact: true }).click();
  await expect(page).toHaveURL(/\/more$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/apps$/);
  expectReadOnly(requests);
});

test('财务十一项均可在手机查看，明细入口保持只读', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, 'admin');
  const supported = [
    ['财务总览', '', '最近流水'], ['收入管理', 'income', '本月流水'],
    ['套餐续费', 'subscriptions', '续费风险列表'], ['应收欠款', 'receivables', '待收款客户'],
    ['按月明细', 'monthly_detail', '按月明细'], ['客户利润', 'customer_profit', '客户利润'],
    ['退款记录', 'refunds', '退款记录'], ['投流月结', 'ad_funds', '投流月结'],
    ['客户支出', 'customer_expense', '客户支出'], ['运营支出', 'company_expense', '运营支出'],
    ['数据分析', 'charts', '数据分析'],
  ];
  for (const [label, tab, heading] of supported) {
    await page.goto(`${baseUrl}/more?group=finance`);
    const link = leafLink(page, label);
    await expect(link).toHaveAttribute('href', tab ? `/finance?tab=${tab}` : '/finance');
    await link.click();
    await expect.poll(() => new URL(page.url()).pathname).toBe('/finance');
    expect(new URL(page.url()).searchParams.get('tab') || '').toBe(tab);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  expectReadOnly(requests);
});

test('普通销售只见销售与客户功能，不出现商家池或财务入口', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, 'sales');
  await page.goto(`${baseUrl}/more`);
  await expect(groupLink(page, '销售中心')).toBeVisible();
  await expect(groupLink(page, '客户中心')).toBeVisible();
  for (const label of groups.filter(label => !['销售中心', '客户中心'].includes(label))) await expect(groupLink(page, label)).toHaveCount(0);
  await groupLink(page, '销售中心').click();
  for (const label of ['今日拨打', '联系进展', '知识库']) await expect(leafLink(page, label)).toBeVisible();
  await expect(leafLink(page, '商家池')).toHaveCount(0);
  await leafLink(page, '知识库').click();
  await expect(page).toHaveURL(/\/sales-knowledge$/);
  expect(requests.some(request => /merchant-pool|\/finance|\/entities\/payments/.test(request.path))).toBe(false);
  expectReadOnly(requests);
});

test('销售合作渠道只见自己的客户分润，显式财务分组也不扩大权限', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  const requests = await installApi(page, 'sales_partner');
  await page.goto(`${baseUrl}/more`);
  await expect(groupLink(page, '渠道分润')).toBeVisible();
  for (const label of groups.filter(label => label !== '渠道分润')) await expect(groupLink(page, label)).toHaveCount(0);
  await expect(bottom(page).getByRole('button')).toHaveCount(3);
  await groupLink(page, '渠道分润').click();
  await expect(leafLink(page, '我的客户与分润')).toHaveAttribute('href', '/partner-portal');
  await expect(leafLink(page, '渠道与分润')).toHaveCount(0);
  await page.goto(`${baseUrl}/more?group=finance`);
  await expect(leafLink(page, '收入管理')).toHaveCount(0);
  await expect(leafLink(page, '月度扣点比例')).toHaveCount(0);
  await expectNoOverflow(page);
  expect(requests.some(request => /\/entities\/payments|deductions-monthly|\/commissions\/dashboard/.test(request.path))).toBe(false);
  expectReadOnly(requests);
});

test('账户仍可访问，电脑端设置保留说明并不能从手机直接打开', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await installApi(page, 'admin');
  await page.goto(`${baseUrl}/more`);
  const account = more(page).getByRole('button', { name: '查看账户与设置', exact: true });
  await expectTouchable(account);
  await account.click();
  await expect(page.getByRole('dialog', { name: '我的账户', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await groupLink(page, '组织设置').click();
  await expect(leafLink(page, '员工管理')).toHaveAttribute('href', '/employees');
  for (const label of ['系统设置', '权限设置']) {
    await expect(more(page).getByText(label, { exact: true })).toBeVisible();
    await expect(leafLink(page, label)).toHaveCount(0);
  }
  await expect(more(page).getByText('电脑端', { exact: true })).toHaveCount(2);
  await page.goto(`${baseUrl}/more?group=finance`);
  await expect(more(page).getByText('月度扣点比例', { exact: true })).toBeVisible();
  await expect(leafLink(page, '月度扣点比例')).toHaveAttribute('href', '/settings/deduction');
  await expect(more(page).getByText('工资表', { exact: true })).toBeVisible();
  await expect(leafLink(page, '工资表')).toHaveAttribute('href', '/payroll');
  expect(requests.some(request => /\/settings|\/permissions/.test(request.path))).toBe(false);
  expectReadOnly(requests);
});
