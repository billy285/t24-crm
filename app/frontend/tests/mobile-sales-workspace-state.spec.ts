import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5196';
const screenshots = process.env.T24_UI_SCREENSHOT_DIR;
const day = '2026-10-10';
const historicalDay = '2026-09-01';
const sales = { id: 27, name: '工作位置销售甲', role: 'sales', status: 'active' };
const manager = { id: 1, name: '工作位置主管', role: 'sales_manager', status: 'active' };
type Employee = typeof sales;

// Only authentication and its logout note are allowed to write. Customer data and providers
// are local fixtures, so navigation cannot generate tasks or dial a real number.
async function fixture(page: Page, initialUser: Employee = sales) {
  let user = initialUser;
  const businessWrites: string[] = [];
  const logoutNotes: Record<string, unknown>[] = [];
  const workbenchReads: URL[] = [];
  let assignees = [{ id: 27, name: sales.name }, { id: 28, name: '工作位置销售乙' }];
  const records = [
    { task_id: 901, task_status: 'pending', lead: { id: 501, business_name: '位置商家甲', city: 'Queens', next_follow_up_at: '2026-09-01T02:00:00Z' } },
    { task_id: 902, task_status: 'pending', lead: { id: 502, business_name: '位置商家乙', city: 'Seattle', next_follow_up_at: '2026-09-02T02:00:00Z' } },
    { task_id: 903, task_status: 'pending', lead: { id: 503, business_name: '位置商家丙', city: 'Boston', next_follow_up_at: '2027-01-01T02:00:00Z' } },
    { task_id: 904, task_status: 'completed', lead: { id: 504, business_name: '已完成商家', city: 'Seattle', next_follow_up_at: '2026-09-01T02:00:00Z' } },
  ].map(record => ({ ...record, priority: 'normal', queue_category: 'new', lead: { ...record.lead, phone: '+1 202 555 0123', country: 'US', industry: '餐饮', status: 'new', do_not_contact: false, is_blacklisted: false } }));
  await page.clock.install({ time: new Date(`${day}T02:00:00Z`) });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(employee => {
    // Do not reseed auth after logout or on a later navigation.
    if (sessionStorage.getItem('local-workspace-fixture-initialized')) return;
    sessionStorage.setItem('local-workspace-fixture-initialized', '1');
    sessionStorage.setItem('emp_auth_token', 'workspace-state-local-token');
    sessionStorage.setItem('token', 'workspace-state-local-token');
    sessionStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, initialUser);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (!['GET', 'HEAD'].includes(request.method())) {
      if (path.endsWith('/emp-auth/login')) return route.fulfill({ json: { token: 'workspace-state-new-token', employee: user } });
      if (path.includes('/emp-auth/')) return route.fulfill({ json: { success: true } });
      if (path.endsWith('/entities/operation_logs') && request.method() === 'POST') {
        const note = request.postDataJSON();
        if (note?.action_type === 'user_note' && note?.action_detail === `用户备注（非系统审计）｜关联操作：退出登录｜员工退出登录: ${user.name}`) {
          logoutNotes.push(note);
          return route.fulfill({ json: { id: 81 } });
        }
      }
      businessWrites.push(`${request.method()} ${path}`);
      return route.fulfill({ status: 409, json: { detail: '本地测试禁止业务写入' } });
    }
    let data: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = user;
    else if (path.endsWith('/sales-leads/assignees')) data = assignees;
    else if (path.endsWith('/sales-leads/workbench/today')) {
      workbenchReads.push(url);
      const id = ['admin', 'super_admin', 'sales_manager'].includes(user.role) ? Number(url.searchParams.get('sales_employee_id') || 27) : user.id;
      data = { salesperson: { id, name: id === 28 ? '工作位置销售乙' : user.role === 'sales' ? user.name : sales.name }, quota: 30, assigned_count: 4, completed_count: 1, remaining_count: 3, is_target_complete: false, categories: { unfinished: 3, callback: 0, interested: 0, appointment: 0, new: 4, retry: 0, recycled: 0, follow_up: 0 }, performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items: records };
    } else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = { available: false, sync_status: 'waiting' };
    else if (path.endsWith('/dashboard/management')) data = { owner_attention: { overdue_followups: 0, high_intent_stale: 0 } };
    else if (path.endsWith('/dashboard/call-report')) data = { source: { status: 'verified' }, summary: { connected: 0 } };
    else if (path.endsWith('/sales-knowledge/articles')) data = { items: [], categories: [] };
    else if (path.includes('/app-config')) data = { items: {} };
    await route.fulfill({ json: data });
  });
  return { businessWrites, logoutNotes, workbenchReads, setUser: (employee: Employee) => { user = employee; }, setAssignees: (records: typeof assignees) => { assignees = records; } };
}

async function open(page: Page, query = '') {
  await page.goto(`${base}/sales-workbench${query}`);
  await expect(page.getByRole('button', { name: '打开客户队列', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '位置商家甲', exact: true })).toBeVisible();
}
async function queue(page: Page) {
  await page.getByRole('button', { name: '打开客户队列', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '客户队列', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
async function scope(page: Page, date: string, salesId?: string) {
  await page.getByRole('button', { name: '调整任务范围', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '任务范围', exact: true });
  const dateInput = dialog.getByLabel('任务日期（北京时间）', { exact: true });
  if (await dateInput.inputValue() !== date) await dateInput.fill(date);
  if (salesId) {
    const salesperson = dialog.getByRole('combobox', { name: '当前销售', exact: true });
    // A real native selection changes only when its value changes. Avoid
    // injecting a synthetic same-value change while a date request is pending.
    if (await salesperson.inputValue() !== salesId) await salesperson.selectOption(salesId);
  }
  await dialog.getByRole('button', { name: '返回工作台', exact: true }).click();
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(date);
  await expect(page.getByRole('progressbar', { name: '任务完成进度', exact: true })).toHaveAttribute('aria-valuenow', '1');
}
async function leave(page: Page) {
  await page.getByRole('button', { name: '打开销售中心功能菜单', exact: true }).click();
  await page.getByRole('dialog', { name: /销售中心/ }).getByRole('button', { name: '知识库', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-knowledge$/);
}
async function returnToWork(page: Page) {
  await page.getByRole('navigation', { name: '手机主导航', exact: true }).getByRole('button', { name: '拨打', exact: true }).click();
  await expect(page).toHaveURL(/\/sales-workbench$/);
  await expect(page.getByRole('button', { name: '打开客户队列', exact: true })).toBeVisible();
}
async function saveOverdueQuery(page: Page) {
  const dialog = await queue(page);
  await dialog.getByRole('button', { name: '逾期 2', exact: true }).click();
  await expect(dialog.locator('[data-task-id]')).toHaveCount(2);
  await dialog.getByLabel('搜索客户队列', { exact: true }).fill('Seattle');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(1);
  await dialog.locator('[data-task-id="902"]').click();
  await expect(page.getByRole('heading', { name: '位置商家乙', exact: true })).toBeVisible();
}

test('主管跨模块回来保留历史日期、销售、逾期筛选、搜索和当前客户，范围变化隔离搜索', async ({ page }) => {
  const data = await fixture(page, manager);
  await open(page, '?sales_employee_id=27');
  await scope(page, historicalDay, '28');
  await saveOverdueQuery(page);
  let dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('Seattle');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
  await leave(page);
  await returnToWork(page);
  await expect(page.getByRole('heading', { name: '拨打记录', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '位置商家乙', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText('工作位置销售乙');
  dialog = await queue(page);
  await expect(dialog.getByRole('button', { name: '逾期 2', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('Seattle');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(1);
  await expect(dialog.locator('[data-task-id="902"]')).toHaveAttribute('aria-pressed', 'true');
  if (screenshots) {
    await expect(dialog).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: `${screenshots}/local-mock-sales-restored-history-query.png`, animations: 'disabled' });
  }
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
  await scope(page, historicalDay, '27');
  dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
  await scope(page, historicalDay, '28');
  dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('Seattle');
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
  await scope(page, '2026-09-02', '28');
  dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
  await scope(page, historicalDay, '28');
  dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('Seattle');
  const clear = dialog.getByRole('button', { name: '清空队列搜索', exact: true });
  const box = await clear.boundingBox();
  expect(Math.round(box!.width)).toBeGreaterThanOrEqual(44);
  expect(Math.round(box!.height)).toBeGreaterThanOrEqual(44);
  await clear.click();
  await expect(dialog.locator('[data-task-id]')).toHaveCount(2);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
  await expect(dialog.locator('[data-task-id="903"]')).toHaveCount(0);
  await expect(dialog.locator('[data-task-id="904"]')).toHaveCount(0);
  expect(data.workbenchReads.some(url => url.searchParams.get('target_date') === historicalDay && url.searchParams.get('sales_employee_id') === '28')).toBe(true);
  expect(data.businessWrites).toEqual([]);
});

test('显式客户深链接的销售、日期和客户优先于旧工作位置及筛选', async ({ page }) => {
  const data = await fixture(page, manager);
  await open(page, '?sales_employee_id=27');
  await scope(page, historicalDay, '28');
  await saveOverdueQuery(page);
  await page.goto(`${base}/sales-workbench?sales_employee_id=27&target_date=2026-10-08&lead_id=503`);
  await expect(page.getByRole('heading', { name: '位置商家丙', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText('2026-10-08');
  const dialog = await queue(page);
  await expect(dialog.getByRole('button', { name: '全部', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(4);
  await expect(dialog.locator('[data-task-id="903"]')).toHaveAttribute('aria-pressed', 'true');
  expect(data.workbenchReads.at(-1)?.searchParams.get('sales_employee_id')).toBe('27');
  expect(data.businessWrites).toEqual([]);
});

test('跨日离开后返回默认今日与全部，不打断正在编辑的历史记录', async ({ page }) => {
  const data = await fixture(page);
  await open(page);
  await scope(page, historicalDay);
  await saveOverdueQuery(page);
  const notes = page.getByLabel('沟通记录', { exact: true });
  await notes.fill('仍在填写的历史联系记录');
  await page.clock.setSystemTime(new Date('2026-10-11T02:00:00Z'));
  await expect(notes).toHaveValue('仍在填写的历史联系记录');
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(historicalDay);
  await leave(page);
  await returnToWork(page);
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText('2026-10-11');
  const dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
  await expect(dialog.getByRole('button', { name: '全部', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(4);
  expect(data.workbenchReads.at(-1)?.searchParams.get('target_date')).toBe('2026-10-11');
  expect(data.businessWrites).toEqual([]);
});

for (const nextUser of [{ ...sales, id: 29, name: '另一位销售' }, { ...sales, id: manager.id, name: '角色已改为销售' }]) {
  test(`当前员工或角色变化不恢复主管旧工作范围：${nextUser.name}`, async ({ page }) => {
    const data = await fixture(page, manager);
    await open(page, '?sales_employee_id=27');
    await scope(page, historicalDay, '28');
    await saveOverdueQuery(page);
    data.setUser(nextUser);
    await page.evaluate(employee => { sessionStorage.setItem('emp_auth_data', JSON.stringify(employee)); }, nextUser);
    data.workbenchReads.length = 0;
    await open(page);
    await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(day);
    await page.getByRole('button', { name: '调整任务范围', exact: true }).click();
    const range = page.getByRole('dialog', { name: '任务范围', exact: true });
    await expect(range.getByRole('combobox', { name: '当前销售', exact: true })).toHaveCount(0);
    await range.getByRole('button', { name: '返回工作台', exact: true }).click();
    const dialog = await queue(page);
    await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
    await expect(dialog.locator('[data-task-id]')).toHaveCount(4);
    expect(data.workbenchReads.every(url => !url.searchParams.has('sales_employee_id'))).toBe(true);
    expect(data.businessWrites).toEqual([]);
  });
}

for (const denyWrites of [false, true]) {
  test(`离开工作台后真实退出并重新登录清除旧位置${denyWrites ? '，存储拒绝写入仍清内存' : ''}`, async ({ page }) => {
    const data = await fixture(page);
    await open(page);
    await scope(page, historicalDay);
    await saveOverdueQuery(page);
    if (denyWrites) await page.evaluate(() => {
      const originalSet = Storage.prototype.setItem;
      const originalRemove = Storage.prototype.removeItem;
      Storage.prototype.setItem = function(key, value) {
        if (key.startsWith('t24:sales-workspace-')) throw new DOMException('拒绝工作位置写入', 'SecurityError');
        return originalSet.call(this, key, value);
      };
      Storage.prototype.removeItem = function(key) {
        if (key.startsWith('t24:sales-workspace-')) throw new DOMException('拒绝工作位置删除', 'SecurityError');
        return originalRemove.call(this, key);
      };
    });
    await leave(page);
    await returnToWork(page);
    let dialog = await queue(page);
    await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('Seattle');
    await expect(dialog.locator('[data-task-id]')).toHaveCount(1);
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toBeHidden();
    await page.getByRole('navigation', { name: '手机主导航', exact: true }).getByRole('button', { name: '首页', exact: true }).click();
    await expect(page).toHaveURL(/\/apps$/);
    await page.getByRole('button', { name: '打开我的账户', exact: true }).click();
    await page.getByRole('dialog', { name: '我的账户', exact: true }).getByRole('button', { name: '退出登录', exact: true }).click();
    await page.getByPlaceholder('请输入邮箱').fill('local@example.com');
    await page.getByPlaceholder('请输入密码').fill('local-password');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page.getByRole('button', { name: '打开我的账户', exact: true })).toBeVisible();
    await page.getByRole('navigation', { name: '手机主导航', exact: true }).getByRole('button', { name: '今日', exact: true }).click();
    await expect(page.getByRole('heading', { name: '位置商家甲', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(day);
    dialog = await queue(page);
    await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
    await expect(dialog.getByRole('button', { name: '全部', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(dialog.locator('[data-task-id]')).toHaveCount(4);
    expect(data.logoutNotes).toEqual([{ action_type: 'user_note', action_detail: `用户备注（非系统审计）｜关联操作：退出登录｜员工退出登录: ${sales.name}` }]);
    expect(data.businessWrites).toEqual([]);
  });
}

for (const invalid of ['broken-json', 'invalid-date', 'future-timestamp'] as const) {
  test(`损坏工作位置安全回到今日实际任务：${invalid}`, async ({ page }) => {
    const data = await fixture(page);
    await page.addInitScript(({ kind, today }) => {
      const value = { version: 1, updatedAt: Date.now(), userId: 27, role: 'sales', savedOn: today, view: { date: '2026-99-99', selectedSalesId: '', filter: 'overdue', teamView: false } };
      if (kind === 'future-timestamp') { value.updatedAt = Date.now() + 86400000; value.view.date = '2026-09-01'; }
      sessionStorage.setItem('t24:sales-workspace-view:v1:27:sales', kind === 'broken-json' ? '{invalid' : JSON.stringify(value));
    }, { kind: invalid, today: day });
    await open(page);
    await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(day);
    const dialog = await queue(page);
    await expect(dialog.getByRole('button', { name: '全部', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(dialog.locator('[data-task-id]')).toHaveCount(4);
    expect(data.businessWrites).toEqual([]);
  });
}

test('已保存销售不再获授权时先核实当前销售清单再读取任务', async ({ page }) => {
  const data = await fixture(page, manager);
  await open(page, '?sales_employee_id=27');
  await scope(page, historicalDay, '28');
  await saveOverdueQuery(page);
  await leave(page);
  data.setAssignees([{ id: 27, name: sales.name }]);
  data.workbenchReads.length = 0;
  await returnToWork(page);
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(sales.name);
  const dialog = await queue(page);
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(2);
  expect(data.workbenchReads.length).toBeGreaterThan(0);
  expect(data.workbenchReads.every(url => url.searchParams.get('sales_employee_id') === '27')).toBe(true);
  expect(data.businessWrites).toEqual([]);
});

test('浏览器拒绝工作位置读写时仍可导航并在当前页面会话恢复筛选搜索', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const originalGet = Storage.prototype.getItem;
    const originalSet = Storage.prototype.setItem;
    Storage.prototype.getItem = function(key) {
      if (key.startsWith('t24:sales-workspace-')) throw new DOMException('拒绝工作位置读取', 'SecurityError');
      return originalGet.call(this, key);
    };
    Storage.prototype.setItem = function(key, value) {
      if (key.startsWith('t24:sales-workspace-')) throw new DOMException('拒绝工作位置写入', 'SecurityError');
      return originalSet.call(this, key, value);
    };
  });
  await open(page);
  await saveOverdueQuery(page);
  await leave(page);
  await returnToWork(page);
  const dialog = await queue(page);
  await expect(dialog.getByRole('button', { name: '逾期 2', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByLabel('搜索客户队列')).toHaveValue('Seattle');
  await expect(dialog.locator('[data-task-id]')).toHaveCount(1);
  await expect(dialog.locator('[data-task-id="902"]')).toHaveAttribute('aria-pressed', 'true');
  expect(data.businessWrites).toEqual([]);
});
