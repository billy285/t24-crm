import { expect, test, type Page } from '@playwright/test';
import { BUSINESS_DATA_REFRESH_EVENT } from '../src/lib/data-refresh';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshotDir = process.env.T24_MOBILE_NAV_SCREENSHOT_DIR;
type Role = 'admin' | 'sales' | 'sales_manager' | 'finance' | 'sales_partner';

function taskBatch(assigned = 0, completed = 0, quota = 20) {
  return {
    salesperson: { id: 11, name: '手机销售测试' }, quota, assigned_count: assigned, completed_count: completed,
    remaining_count: assigned - completed, is_target_complete: completed >= quota,
    performance: { callbacks_due: 0 }, categories: { callback: 0 },
    items: Array.from({ length: assigned }, (_, index) => ({ task_id: index + 1, task_status: index < completed ? 'completed' : 'pending', lead: { id: index + 1, business_name: `模拟商家${index + 1}`, phone: '+12125550123', country: 'US', status: 'new' } })),
  };
}

async function seed(page: Page, role: Role, options: { batch?: unknown; salesStatus?: number; managerMetrics?: unknown; homeEntitiesStatus?: number } = {}) {
  const employee = { id: 11, name: '手机销售测试', role, status: 'active' };
  const requests: { method: string; path: string }[] = [];
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'mobile-sales-navigation-fixture');
    localStorage.setItem('token', 'mobile-sales-navigation-fixture');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    requests.push({ method: request.method(), path });
    if (request.method() !== 'GET') return route.fulfill({ status: 400, contentType: 'application/json', body: '{"detail":"导航测试禁止业务写入"}' });
    if (path.endsWith('/sales-leads/workbench/today') && options.salesStatus) return route.fulfill({ status: options.salesStatus, contentType: 'application/json', body: '{"detail":"模拟读取失败"}' });
    if (path.includes('/entities/') && options.homeEntitiesStatus) return route.fulfill({ status: options.homeEntitiesStatus, contentType: 'application/json', body: '{"detail":"模拟首页读取失败"}' });
    const data = path.endsWith('/emp-auth/me') ? employee
      : path.endsWith('/sales-leads/workbench/today') ? { target_date: url.searchParams.get('target_date'), ...(options.batch ?? taskBatch()) as object }
      : path.endsWith('/sales-leads/dashboard/management') ? { metrics: options.managerMetrics ?? { assigned: 0, completed: 0 }, source_quality: [], salespeople: [] }
      : path.endsWith('/sales-leads/dashboard/call-report') ? { period: { days: 7, start_date: '2026-10-04', end_date: '2026-10-10' }, source: { status: 'verified', provider: 'ringcentral', label: '模拟通话数据' }, summary: { provider_calls: 0, connected: 0, not_connected: 0, crm_records: 0, interested: 0, appointments: 0, conversions: 0 }, result_breakdown: [], daily: [], employees: [], recent_calls: [] }
      : path.endsWith('/sales-leads/dashboard/performance') ? { period: { days: 30, start_date: '2026-09-10', end_date: '2026-10-10' }, items: [] }
      : path.endsWith('/sales-leads/assignees') ? [{ id: 11, name: '手机销售测试', role: 'sales' }]
      : path.endsWith('/sales-leads/recovery/overview') ? { items: [], summary: { recoverable: 0, watch: 0, protected: 0, extended: 0, extension_requests: 0 } }
      : path.endsWith('/commissions/my-dashboard') ? { partner: { id: 1, name: '模拟合作渠道', status: 'active', partner_code: 'MOCK', joined_at: '2026-10-10' }, summary: { active_customer_count: 0, cooperation_customer_count: 0, renewal_attention_count: 0, stopped_customer_count: 0, ledger_count: 0, currencies: {} }, customers: [], entries: [], agreements: [] }
      : path.endsWith('/merchant-pool/stats') ? { total: 0, pending: 0, isolated: 0, converted: 0, archived: 0 }
      : path.includes('/app-config') ? { items: {} }
      : { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return requests;
}

const bottomNav = (page: Page) => page.getByRole('navigation', { name: '手机主导航' });
const salesRoutes = [
  ['/sales-workbench', '拨打', '今日拨打'], ['/sales-leads', '跟进', '联系进展'],
  ['/merchant-pool', '商家', '商家池'], ['/sales-knowledge', '', '知识库'],
] as const;

for (const width of [320, 390, 430]) {
  test(`销售四页只保留专用底栏，当前位置与菜单准确且无横向溢出（${width}px）`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await seed(page, 'admin');
    for (const [path, current, menuLabel] of salesRoutes) {
      await page.goto(`${baseUrl}${path}`);
      const nav = bottomNav(page);
      await expect(nav).toBeVisible();
      await expect(nav.getByRole('button')).toHaveCount(5);
      for (const label of ['首页', '拨打', '跟进', '商家', '我的']) await expect(nav.getByRole('button', { name: label, exact: true })).toBeVisible();
      await expect(nav.locator('[aria-current="page"]')).toHaveCount(current ? 1 : 0);
      if (current) await expect(nav.getByRole('button', { name: current, exact: true })).toHaveAttribute('aria-current', 'page');
      await expect(page.locator('.sales-center-mobile-navigation')).toHaveCount(0);
      await page.getByRole('button', { name: '打开销售中心功能菜单', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: /销售中心/ });
      for (const label of ['今日拨打', '商家池', '联系进展', '知识库']) await expect(dialog.getByRole('button', { name: label, exact: true })).toBeVisible();
      await expect(dialog.locator('[aria-current="page"]')).toHaveCount(1);
      await expect(dialog.getByRole('button', { name: menuLabel, exact: true })).toHaveAttribute('aria-current', 'page');
      if (screenshotDir && width === 390 && path === '/sales-knowledge') await page.screenshot({ path: `${screenshotDir}/local-mock-sales-module-menu-390.png`, fullPage: true });
      await page.keyboard.press('Escape');
      await expect(dialog).toBeHidden();
      const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
      expect(widths.document).toBeLessThanOrEqual(widths.viewport);
    }
    expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-knowledge-navigation-${width}.png`, fullPage: true });
  });
}

test('销售底栏切换到对应位置，打开我的时其他项不再宣称当前页面', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await seed(page, 'sales_manager');
  await page.goto(`${baseUrl}/sales-workbench`);
  await bottomNav(page).getByRole('button', { name: '跟进', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-leads$/);
  await expect(bottomNav(page).getByRole('button', { name: '跟进', exact: true })).toHaveAttribute('aria-current', 'page');
  await bottomNav(page).getByRole('button', { name: '商家', exact: true }).click();
  await expect(page).toHaveURL(/\/merchant-pool$/);
  await bottomNav(page).getByRole('button', { name: '拨打', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-workbench$/);
  await bottomNav(page).getByRole('button', { name: '我的', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '我的账户' })).toBeVisible();
  const nav = page.locator('nav[aria-label="手机主导航"]');
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  await expect(nav.locator('button[aria-label="我的"]')).toHaveAttribute('aria-current', 'page');
  await page.keyboard.press('Escape');
  await expect(bottomNav(page).getByRole('button', { name: '拨打', exact: true })).toHaveAttribute('aria-current', 'page');
  await bottomNav(page).getByRole('button', { name: '首页', exact: true }).click();
  await expect(page).toHaveURL(/\/apps$/);
  await expect(bottomNav(page).getByRole('button', { name: '今日', exact: true })).toBeVisible();
  await expect(bottomNav(page).getByRole('button', { name: '拨打', exact: true })).toHaveCount(0);
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
});

test('普通销售不出现无权商家入口，知识库仍可由菜单直接进入', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await seed(page, 'sales');
  await page.goto(`${baseUrl}/sales-leads`);
  await expect(bottomNav(page).getByRole('button')).toHaveCount(4);
  await expect(bottomNav(page).getByRole('button', { name: '商家', exact: true })).toHaveCount(0);
  await expect(bottomNav(page).getByRole('button', { name: '跟进', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('button', { name: '打开销售中心功能菜单' }).click();
  const dialog = page.getByRole('dialog', { name: /销售中心/ });
  await expect(dialog.getByRole('button', { name: '商家池', exact: true })).toHaveCount(0);
  await dialog.getByRole('button', { name: '知识库', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-knowledge$/);
  await expect(bottomNav(page).locator('[aria-current="page"]')).toHaveCount(0);
  expect(requests.some(request => request.path.startsWith('/api/v1/merchant-pool'))).toBe(false);
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
});

for (const role of ['finance', 'sales_partner'] as const) {
  test(`${role} 首页与业务页保留原底栏，我的打开时只有一个当前项`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await seed(page, role);
    await page.goto(`${baseUrl}${role === 'finance' ? '/finance' : '/partner-portal'}`);
    await expect(bottomNav(page).getByRole('button')).toHaveCount(role === 'sales_partner' ? 3 : 5);
    await expect(bottomNav(page).getByRole('button', { name: role === 'sales_partner' ? '客户与分润' : '待办', exact: true })).toHaveAttribute('aria-current', 'page');
    await bottomNav(page).getByRole('button', { name: '我的', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '我的账户' })).toBeVisible();
    await expect(page.locator('nav[aria-label="手机主导航"] [aria-current="page"]')).toHaveCount(1);
  });
}

for (const scenario of [
  { name: '零目标的空批次', batch: taskBatch(0, 0, 0), title: '等待今日销售任务' },
  { name: '尚无已分配任务', batch: taskBatch(0, 0, 20), title: '等待今日销售任务' },
  { name: '零目标但有历史完成数', batch: taskBatch(2, 2, 0), title: '等待今日销售任务' },
  { name: '返回成功但没有任务字段', batch: {}, title: '销售任务数据待更新' },
  { name: '销售读取失败且其他首页请求成功', salesStatus: 503, title: '销售任务数据待更新' },
  { name: '确有已分配完成证据', batch: taskBatch(2, 2, 20), title: '今日已分配任务已完成' },
  { name: '仍有待拨打任务', batch: taskBatch(4, 1, 20), title: '今天还有 3 条销售任务' },
] as const) {
  test(`销售首页正确区分${scenario.name}，读取或重新加载不生成任务`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const requests = await seed(page, 'sales', scenario);
    await page.goto(`${baseUrl}/apps`);
    await expect(page.getByRole('heading', { name: scenario.title, exact: true })).toBeVisible();
    if (scenario.title !== '今日已分配任务已完成') await expect(page.getByRole('heading', { name: /已完成/ })).toHaveCount(0);
    if ('salesStatus' in scenario) {
      await page.getByRole('button', { name: '重新加载', exact: true }).click();
      await expect(page.getByRole('heading', { name: scenario.title, exact: true })).toBeVisible();
    }
    expect(requests.some(request => /prepare|run-cycle/.test(request.path))).toBe(false);
    expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
    if (screenshotDir && scenario.name === '仍有待拨打任务') await page.screenshot({ path: `${screenshotDir}/local-mock-sales-home-390.png`, fullPage: true });
  });
}

test('后台刷新全部失败时清除原绿色完成卡，恢复后仍只读取最新任务', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const options = { batch: taskBatch(2, 2, 20), salesStatus: 0, homeEntitiesStatus: 0 };
  const requests = await seed(page, 'sales', options);
  await page.goto(`${baseUrl}/apps`);
  await expect(page.getByRole('heading', { name: '今日已分配任务已完成', exact: true })).toBeVisible();
  options.salesStatus = 503;
  options.homeEntitiesStatus = 503;
  await page.evaluate(event => window.dispatchEvent(new CustomEvent(event)), BUSINESS_DATA_REFRESH_EVENT);
  await expect(page.getByRole('heading', { name: '销售任务数据待更新', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '今日已分配任务已完成', exact: true })).toHaveCount(0);
  options.salesStatus = 0;
  options.homeEntitiesStatus = 0;
  options.batch = taskBatch(3, 1, 20);
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('heading', { name: '今天还有 2 条销售任务', exact: true })).toBeVisible();
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
});

test('销售首页快捷名称与模块菜单一致且仍按权限显示', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await seed(page, 'admin');
  await page.goto(`${baseUrl}/apps`);
  const sales = page.getByRole('region', { name: '销售中心', exact: true });
  for (const label of ['今日拨打', '商家池', '联系进展', '知识库']) await expect(sales.getByRole('button', { name: `打开${label}`, exact: true })).toBeVisible();
  await sales.getByRole('button', { name: '打开联系进展', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-leads$/);
});

test('销售首页今日任务先于应用入口，全部功能收起且展开后仍可进入知识库', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await seed(page, 'sales', { batch: taskBatch(4, 1, 20) });
  await page.goto(`${baseUrl}/apps`);
  const today = page.getByRole('region', { name: '今天先处理' });
  await expect(today.getByRole('heading', { name: '今天还有 3 条销售任务' })).toBeVisible();
  const appOrder = await today.evaluate(element => Boolean(element.compareDocumentPosition(document.querySelector('[aria-label="工作应用"]')!) & Node.DOCUMENT_POSITION_FOLLOWING));
  expect(appOrder).toBe(true);
  const summary = page.locator('summary').filter({ hasText: '全部功能' });
  await expect(summary).toBeVisible();
  await expect(page.getByRole('button', { name: '打开知识库', exact: true })).toBeHidden();
  await summary.click();
  await expect(page.getByRole('button', { name: '打开商家池', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '打开知识库', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-knowledge$/);
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
});
