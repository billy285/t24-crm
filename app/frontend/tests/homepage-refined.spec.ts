import { expect, test, type Locator, type Page } from '@playwright/test';
import { BUSINESS_DATA_REFRESH_EVENT } from '../src/lib/data-refresh';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5196';
const screenshotDir = process.env.T24_HOMEPAGE_SCREENSHOT_DIR;
type Role = 'admin' | 'super_admin' | 'sales' | 'sales_manager' | 'ops' | 'design' | 'finance' | 'sales_partner';
type Entity = 'tasks' | 'customers' | 'subscriptions' | 'payments';
type FixtureOptions = { entities?: Partial<Record<Entity, unknown[]>>; failures?: Entity[] };

const standardApps = [
  ['经营中心：经营、现金与里程碑', '/'],
  ['销售中心：线索、拨打与跟进', '/sales-workbench'],
  ['客户中心：客户 360 与生命周期', '/customers'],
  ['任务交付：任务、服务与回访', '/operations-workbench'],
  ['财务结算：收款、续费与分润', '/finance'],
  ['组织设置：员工、权限与系统', '/employees'],
] as const;

function riskFixtures(): Record<Entity, unknown[]> {
  const today = new Date().toISOString().slice(0, 10);
  return {
    tasks: [
      ...Array.from({ length: 7 }, (_, index) => ({ id: 101 + index, title: `模拟逾期任务 ${index + 1}`, customer_name: `模拟任务商家 ${index + 1}`, status: 'pending', due_date: '2020-01-01', updated_at: today })),
      { id: 201, title: '模拟已完成任务', status: 'completed', due_date: '2020-01-01' },
      { id: 202, title: '模拟已取消任务', status: 'cancelled', due_date: '2020-01-01' },
      { id: 203, title: '模拟未来任务', status: 'pending', due_date: '2100-01-01' },
    ],
    customers: Array.from({ length: 5 }, (_, index) => ({ id: 301 + index, business_name: `模拟客户 ${index + 1}`, status: 'active', updated_at: today })),
    subscriptions: [
      ...Array.from({ length: 4 }, (_, index) => ({ id: 401 + index, customer_id: 301 + index, package_name: `模拟续费套餐 ${index + 1}`, status: index === 0 ? 'expired' : index === 1 ? 'renewal_pending' : 'expiring_soon' })),
      { id: 405, customer_id: 305, package_name: '模拟正常套餐', status: 'active' },
    ],
    payments: [
      ...Array.from({ length: 3 }, (_, index) => ({ id: 501 + index, customer_id: 301 + index, product_name: `模拟收款套餐 ${index + 1}`, amount_due: 300 + index, amount_paid: 100, outstanding_amount: 200 + index, payment_date: today, currency: 'USD' })),
      { id: 504, customer_id: 304, amount_due: 100, amount_paid: 100, outstanding_amount: 0, payment_date: today, currency: 'USD' },
    ],
  };
}

async function seed(page: Page, role: Role, options: FixtureOptions = {}) {
  const employee = { id: 11, name: '首页模拟账号', role, status: 'active' };
  const requests: { method: string; path: string }[] = [];
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'homepage-refined-fixture');
    localStorage.setItem('token', 'homepage-refined-fixture');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    requests.push({ method: request.method(), path });
    if (request.method() !== 'GET') return route.fulfill({ status: 400, contentType: 'application/json', body: '{"detail":"首页测试禁止业务写入"}' });
    const entity = path.match(/\/entities\/(tasks|customers|subscriptions|payments)(?:\/|$)/)?.[1] as Entity | undefined;
    if (entity && options.failures?.includes(entity)) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"模拟首页读取失败"}' });
    const data = path.endsWith('/emp-auth/me') ? employee
      : entity ? { items: options.entities?.[entity] || [], total: options.entities?.[entity]?.length || 0 }
      : path.endsWith('/sales-leads/workbench/today') ? { quota: 20, assigned_count: 4, completed_count: 1, remaining_count: 3, performance: { callbacks_due: 2 }, items: [{ task_id: 1, task_status: 'pending', lead: { business_name: '模拟销售商家' } }] }
      : path.endsWith('/sales-leads/dashboard/management') ? { metrics: { assigned: 4, completed: 1 }, source_quality: [], salespeople: [] }
      : path.endsWith('/commissions/my-dashboard') ? { summary: { renewal_attention_count: 2, currencies: { USD: { payable: 1 } } }, customers: [], entries: [], agreements: [] }
      : path.includes('/app-config') ? { items: {} }
      : path.endsWith('/deductions-monthly/default') ? { rate: 0.15 }
      : { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return requests;
}

const home = (page: Page) => page.locator('.homepage-refined');
const today = (page: Page) => page.getByRole('region', { name: '今日重点', exact: true });
const apps = (page: Page) => page.getByRole('region', { name: '工作应用', exact: true });
const priority = (page: Page, name: string) => today(page).getByRole('group', { name, exact: true });
const functionsSummary = (page: Page) => home(page).locator('summary').filter({ hasText: '全部功能' });
const expectReadOnly = (requests: { method: string; path: string }[]) => {
  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
  expect(requests.some(request => /prepare|run-cycle/.test(request.path))).toBe(false);
};

async function expectCounts(page: Page, expected: { overdue: string; renewal: string; receivables: string }) {
  await expect(priority(page, '逾期任务').getByText(expected.overdue, { exact: true })).toBeVisible();
  await expect(priority(page, '续费风险').getByText(expected.renewal, { exact: true })).toBeVisible();
  await expect(priority(page, '待收款').getByText(expected.receivables, { exact: true })).toBeVisible();
}

async function expectNoOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport);
}

async function expectReachableControl(page: Page, control: Locator) {
  await control.scrollIntoViewIfNeeded();
  const hit = await control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const topmost = document.elementFromPoint(x, y);
    const nav = document.querySelector<HTMLElement>('nav[aria-label="手机主导航"]');
    const navRect = nav?.getBoundingClientRect();
    return { width: rect.width, height: rect.height, bottom: rect.bottom, viewportHeight: innerHeight, navTop: navRect && navRect.height > 0 ? navRect.top : null, reachable: Boolean(topmost && (topmost === element || element.contains(topmost))) };
  });
  expect(hit.width).toBeGreaterThanOrEqual(44);
  expect(hit.height).toBeGreaterThanOrEqual(44);
  expect(hit.bottom).toBeLessThanOrEqual(hit.navTop ?? hit.viewportHeight);
  expect(hit.reachable).toBe(true);
}

for (const width of [320, 390, 430, 768, 1024, 1093, 1440, 1920]) {
  test(`首页在 ${width}px 保留工作优先顺序、三列应用与可达末项（本地模拟）`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 900 : 960 });
    const requests = await seed(page, 'admin', { entities: riskFixtures() });
    await page.goto(`${baseUrl}/apps`);
    await expect(home(page)).toBeVisible();
    await expect(home(page).getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(home(page).getByRole('heading', { name: '今日工作', level: 1, exact: true })).toBeVisible();
    await expectCounts(page, { overdue: '7', renewal: '4', receivables: '3' });
    const order = await today(page).evaluate(element => {
      const recent = document.querySelector('[aria-label="继续处理"]');
      const workApps = document.querySelector('[aria-label="工作应用"]');
      const functions = document.querySelector('details[aria-labelledby="mobile-functions-heading"]');
      const follows = (a: Element | null, b: Element | null) => Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
      return follows(element, recent) && follows(recent, workApps) && follows(workApps, functions);
    });
    expect(order).toBe(true);
    await expect(apps(page).getByRole('heading', { name: '常用应用', exact: true })).toBeVisible();
    await expect(apps(page).getByRole('button')).toHaveCount(6);
    const cardRows = await apps(page).getByRole('button').evaluateAll(elements => elements.map(element => {
      const rect = element.getBoundingClientRect();
      return { x: Math.round(rect.x), y: Math.round(rect.y), width: rect.width, height: rect.height, font: parseFloat(getComputedStyle(element.querySelector('span:last-child') || element).fontSize) };
    }));
    expect(new Set(cardRows.map(card => card.y)).size).toBe(2);
    expect(new Set(cardRows.map(card => card.x)).size).toBe(3);
    for (const card of cardRows) {
      expect(card.width).toBeGreaterThanOrEqual(44);
      expect(card.height).toBeGreaterThanOrEqual(44);
      expect(card.font).toBeGreaterThanOrEqual(12);
    }
    const controls = await home(page).getByRole('button').evaluateAll(elements => elements.map(element => {
      const rect = element.getBoundingClientRect();
      return { name: element.getAttribute('aria-label') || element.textContent, width: rect.width, height: rect.height, font: parseFloat(getComputedStyle(element).fontSize) };
    }));
    for (const control of controls) {
      expect(control.width, String(control.name)).toBeGreaterThanOrEqual(44);
      expect(control.height, String(control.name)).toBeGreaterThanOrEqual(44);
      expect(control.font, String(control.name)).toBeGreaterThanOrEqual(12);
    }
    const summaryBounds = await (width < 768 ? home(page).getByRole('button', { name: '全部功能', exact: true }) : functionsSummary(page)).boundingBox();
    expect(summaryBounds!.height).toBeGreaterThanOrEqual(44);
    await expect(page.getByRole('button', { name: '打开知识库', exact: true })).toBeHidden();
    await expectNoOverflow(page);
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-homepage-admin-${width}.png`, fullPage: true });
    if (width < 768) {
      await home(page).getByRole('button', { name: '全部功能', exact: true }).click();
      await expect(page).toHaveURL(/\/more$/);
      await expectReachableControl(page, page.getByRole('link', { name: '组织设置，查看全部功能', exact: true }));
    } else {
      await functionsSummary(page).click();
      const lastFunction = page.getByRole('region', { name: '组织设置', exact: true }).getByRole('button').last();
      await expect(lastFunction).toHaveAccessibleName('打开员工管理');
      await expectReachableControl(page, lastFunction);
    }
    await expectNoOverflow(page);
    expectReadOnly(requests);
  });
}

for (const role of ['admin', 'super_admin'] as const) {
  test(`${role} 首页风险数字来自读取结果，入口导航到原业务路径`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const requests = await seed(page, role, { entities: riskFixtures() });
    await page.goto(`${baseUrl}/apps`);
    await expectCounts(page, { overdue: '7', renewal: '4', receivables: '3' });
    await expect(page.getByRole('button', { name: '查看待办，14 项未处理', exact: true })).toBeVisible();
    await priority(page, '逾期任务').getByRole('button', { name: '查看任务', exact: true }).click();
    const taskLocation = new URL(page.url());
    expect(taskLocation.pathname).toBe('/tasks');
    expect(taskLocation.searchParams.get('view')).toBe('team');
    expect(taskLocation.searchParams.get('quick')).toBe('overdue');
    await expect(page.getByRole('heading', { name: '任务协作', exact: true })).toBeVisible();
    await expect(page.getByText('模拟逾期任务 1', { exact: true })).toBeVisible();
    await expect(page.getByText('模拟未来任务', { exact: true })).toHaveCount(0);
    await expect(page.getByText('模拟已完成任务', { exact: true })).toHaveCount(0);
    await expect(page.getByText('模拟已取消任务', { exact: true })).toHaveCount(0);
    for (const [name, path] of standardApps) {
      await page.goto(`${baseUrl}/apps`);
      await apps(page).getByRole('button', { name, exact: true }).click();
      await expect.poll(() => new URL(page.url()).pathname).toBe(path);
    }
    expectReadOnly(requests);
  });
}

test('已成功读取的零风险行隐藏，只保留中性提醒', async ({ page }) => {
  const requests = await seed(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  await expect(today(page).getByText('暂无待处理提醒', { exact: true })).toBeVisible();
  await expect(today(page).getByRole('group')).toHaveCount(0);
  await expect(today(page).getByText('待更新', { exact: true })).toHaveCount(0);
  await expect(today(page).getByRole('heading', { name: /已完成|状态正常/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '查看待办', exact: true })).toBeVisible();
  expectReadOnly(requests);
});

test('部分失败保留有效计数，将失败来源显示为待更新而非零', async ({ page }) => {
  const requests = await seed(page, 'admin', { entities: riskFixtures(), failures: ['subscriptions'] });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  await expectCounts(page, { overdue: '7', renewal: '待更新', receivables: '3' });
  await expect(priority(page, '续费风险').getByText('0', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('部分首页数字暂未更新');
  await expect(today(page).getByText('暂无待处理提醒', { exact: true })).toHaveCount(0);
  await expectReachableControl(page, page.getByRole('button', { name: '重新加载', exact: true }));
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-homepage-partial-failure-390.png`, fullPage: true });
  expectReadOnly(requests);
});

test('全部来源失败时首页说明数据待更新，应用入口仍能使用', async ({ page }) => {
  const requests = await seed(page, 'admin', { failures: ['tasks', 'customers', 'subscriptions', 'payments'] });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  await expect(page.getByRole('status')).toContainText('首页数字暂时无法更新');
  await expect(today(page).getByText('暂无待处理提醒', { exact: true })).toHaveCount(0);
  await expect(today(page).getByText('0', { exact: true })).toHaveCount(0);
  await expect(today(page).getByRole('heading', { name: /已完成|状态正常/ })).toHaveCount(0);
  await expect(apps(page).getByRole('button')).toHaveCount(6);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-homepage-all-failed-390.png`, fullPage: true });
  await apps(page).getByRole('button', { name: standardApps[2][0], exact: true }).click();
  await expect(page).toHaveURL(/\/customers$/);
  expectReadOnly(requests);
});

test('成功来源为零而另一来源失败时，只显示待更新项', async ({ page }) => {
  const requests = await seed(page, 'admin', { failures: ['subscriptions'] });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  await expect(page.getByRole('status')).toContainText('部分首页数字暂未更新');
  await expect(today(page).getByRole('group')).toHaveCount(1);
  await expect(priority(page, '续费风险').getByText('待更新', { exact: true })).toBeVisible();
  await expect(priority(page, '逾期任务')).toHaveCount(0);
  await expect(priority(page, '待收款')).toHaveCount(0);
  await expect(today(page).getByText('暂无待处理提醒', { exact: true })).toHaveCount(0);
  expectReadOnly(requests);
});

test('后台读取失败会清除先前正常状态，恢复后使用新计数', async ({ page }) => {
  const options: FixtureOptions = { failures: [] };
  const requests = await seed(page, 'admin', options);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  await expect(today(page).getByText('暂无待处理提醒', { exact: true })).toBeVisible();
  options.failures = ['tasks', 'customers', 'subscriptions', 'payments'];
  await page.evaluate(event => window.dispatchEvent(new CustomEvent(event)), BUSINESS_DATA_REFRESH_EVENT);
  await expect(page.getByRole('status')).toContainText('首页数字暂时无法更新');
  await expect(today(page).getByText('暂无待处理提醒', { exact: true })).toHaveCount(0);
  options.failures = [];
  options.entities = riskFixtures();
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expectCounts(page, { overdue: '7', renewal: '4', receivables: '3' });
  expectReadOnly(requests);
});

test('继续处理的全部最近事项都能返回对应记录并保留安全返回地址', async ({ page }) => {
  const requests = await seed(page, 'admin', { entities: riskFixtures() });
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [title, path, parameter, id] of [
    ['模拟逾期任务 1', '/tasks', 'task_id', '101'],
    ['模拟逾期任务 2', '/tasks', 'task_id', '102'],
    ['模拟客户 1', '/customers', 'detail', '301'],
  ] as const) {
    await page.goto(`${baseUrl}/apps`);
    const recent = page.getByRole('region', { name: '继续处理', exact: true });
    await expect(recent).toBeVisible();
    if (title !== '模拟逾期任务 1') await recent.locator('summary').filter({ hasText: '更多最近事项' }).click();
    await recent.getByRole('button', { name: new RegExp(title) }).click();
    const current = new URL(page.url());
    expect(current.origin).toBe(new URL(baseUrl).origin);
    expect(current.pathname).toBe(path);
    expect(current.searchParams.get(parameter)).toBe(id);
    expect(current.searchParams.get('returnTo')).toBe('/apps');
  }
  expectReadOnly(requests);
});

test('账户与通知入口保留可用行为且不写业务数据', async ({ page }) => {
  const requests = await seed(page, 'admin', { entities: riskFixtures() });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  const profile = page.getByRole('button', { name: '打开我的账户', exact: true });
  await expectReachableControl(page, profile);
  await profile.click();
  await expect(page.getByRole('dialog', { name: '我的账户' })).toBeVisible();
  await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  const notifications = page.getByRole('button', { name: '查看待办，14 项未处理', exact: true });
  await expectReachableControl(page, notifications);
  await notifications.click();
  await expect(page).toHaveURL(/\/tasks(?:\?.*)?$/);
  await expect(page.getByRole('heading', { name: '任务协作', exact: true })).toBeVisible();
  expectReadOnly(requests);
});

for (const scenario of [
  { name: '续费', action: '查看续费', tab: 'subscriptions', heading: '续费风险列表', content: '模拟续费套餐 1' },
  { name: '待收款', action: '查看收款', tab: 'receivables', heading: '待收款客户', content: '模拟客户 1' },
] as const) {
  test(`首页${scenario.name}入口打开对应手机只读列表与真实模拟记录`, async ({ page }) => {
    const requests = await seed(page, 'admin', { entities: riskFixtures() });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/apps`);
    await today(page).getByRole('button', { name: scenario.action, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/finance\\?tab=${scenario.tab}$`));
    await expect(page.getByRole('heading', { name: scenario.heading, exact: true })).toBeVisible();
    await expect(page.getByText(scenario.content, { exact: true }).first()).toBeVisible();
    if (scenario.name === '续费') {
      await expect(page.getByRole('button', { name: '续费', exact: true })).toHaveAttribute('aria-current', 'page');
      await expect(page.getByText('模拟续费套餐 4', { exact: true })).toBeVisible();
      await expect(page.getByText('模拟正常套餐', { exact: true })).toHaveCount(0);
    }
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/local-mock-homepage-finance-${scenario.tab}-390.png`, fullPage: true });
    expectReadOnly(requests);
  });
}
