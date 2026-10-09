import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshots = process.env.T24_UI_SCREENSHOT_DIR;
const day = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
type Employee = { id: number; name: string; role: string; status: string };
type Lead = { id: number; business_name: string; phone: string; country: string; status: string; do_not_contact: boolean; is_blacklisted: boolean; converted_customer_id?: number; next_follow_up_at?: string };
type Task = { task_id: number; task_status: string; priority: string; queue_category: string; lead: Lead };
const employee: Employee = { id: 27, name: '模拟销售甲', role: 'sales', status: 'active' };
const records = (salesId = 27): Task[] => [0, 1].map(index => ({
  task_id: 901 + index, task_status: 'pending', priority: 'normal', queue_category: 'new',
  lead: { id: (salesId === 27 ? 501 : 601) + index, business_name: `${salesId === 27 ? '甲' : '乙'}商家${index + 1}`, phone: '+1 202 555 0123', country: 'US', status: 'new', do_not_contact: false, is_blacklisted: false },
}));

async function fixture(page: Page, options: { user?: Employee; empty?: boolean; failRead?: boolean; failFirstSave?: boolean; failReadAfterSave?: boolean; protected?: boolean } = {}) {
  let user = options.user || employee;
  const data = new Map([[27, options.empty ? [] : records()], [28, records(28)]]);
  if (options.protected) {
    data.get(27)![0].lead.do_not_contact = true;
    data.get(27)![1].lead.converted_customer_id = 800;
  }
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const reads: string[] = [];
  let failRead = options.failRead || false;
  let lastSalesId = 27;
  let attempts = 0;
  await page.addInitScript(value => {
    localStorage.setItem('emp_auth_token', 'sales-nine-local-token');
    localStorage.setItem('token', 'sales-nine-local-token');
    if (!localStorage.getItem('emp_auth_data')) localStorage.setItem('emp_auth_data', JSON.stringify(value));
  }, user);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (!['GET', 'HEAD'].includes(request.method())) {
      writes.push({ path, body: request.postDataJSON() });
      if (path.endsWith('/emp-auth/login')) return route.fulfill({ json: { token: 'sales-nine-local-token', employee: user } });
      if (path.endsWith('/emp-auth/logout') || path.endsWith('/emp-auth/set_refresh')) return route.fulfill({ json: {} });
      const result = path.match(/\/workbench\/tasks\/(\d+)\/result$/);
      const task = result && data.get(lastSalesId)?.find(item => item.task_id === Number(result[1]));
      if (!task || task.task_status !== 'pending' || task.lead.do_not_contact || task.lead.converted_customer_id) return route.fulfill({ status: 409, json: { detail: '本地测试拒绝额外写入' } });
      attempts++;
      if (options.failFirstSave && attempts === 1) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
      const body = request.postDataJSON();
      task.task_status = 'completed';
      task.lead.status = ({ callback: 'follow_up', interested: 'interested', appointment: 'appointment', do_not_contact: 'blocked' } as Record<string, string>)[body.outcome] || 'contacted';
      task.lead.do_not_contact = body.outcome === 'do_not_contact';
      task.lead.next_follow_up_at = body.next_follow_up_at;
      if (options.failReadAfterSave) failRead = true;
      return route.fulfill({ json: { message: '通话结果已记录', task_id: task.task_id, lead_id: task.lead.id, lead: task.lead, status: task.lead.status, next_follow_up_at: task.lead.next_follow_up_at } });
    }
    reads.push(path + url.search);
    let response: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) response = user;
    else if (path.endsWith('/sales-leads/assignees')) response = [{ id: 27, name: '模拟销售甲' }, { id: 28, name: '模拟销售乙' }];
    else if (path.endsWith('/sales-leads/workbench/today')) {
      if (failRead) return route.fulfill({ status: 503, json: { detail: '模拟任务读取失败' } });
      const salesId = user.role === 'sales' ? user.id : Number(url.searchParams.get('sales_employee_id') || 27);
      lastSalesId = salesId;
      const tasks = data.get(salesId) || [];
      const completed = tasks.filter(task => task.task_status === 'completed').length;
      response = { salesperson: { id: salesId, name: '模拟销售' }, target_date: url.searchParams.get('target_date'), quota: 20, assigned_count: tasks.length, completed_count: completed, remaining_count: tasks.length - completed, is_target_complete: false,
        categories: { unfinished: tasks.length - completed, callback: 0, interested: 0, appointment: 0, new: tasks.length }, performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items: tasks };
    } else if (path.endsWith('/dashboard/management')) response = { target_date: url.searchParams.get('target_date'), owner_attention: { overdue_followups: 0, high_intent_stale: 0 } };
    else if (path.endsWith('/merchant-pool/stats')) response = { pending: 0 };
    else if (path.endsWith('/dashboard/call-report')) response = { period: { start_date: day(), end_date: day() }, source: { status: 'verified' }, summary: { connected: 0 } };
    else if (path.endsWith('/ringcentral/status')) response = { configured: false, connected: false };
    else if (path.endsWith('/ringcentral/calls/recent')) response = { available: false, sync_status: 'waiting' };
    else if (path.endsWith('/call-history')) response = [];
    else if (path.includes('/app-config')) response = { items: {} };
    else if (path.endsWith('/sales-knowledge/articles')) response = { items: [], categories: [] };
    await route.fulfill({ json: response });
  });
  return {
    writes, reads, recover: () => { failRead = false; },
    setUser: async (value: Employee) => { user = value; await page.evaluate(value => localStorage.setItem('emp_auth_data', JSON.stringify(value)), value); },
    changeLead: (id: number) => { data.get(27)![0].lead = { ...data.get(27)![0].lead, id, business_name: '重新分配后的商家' }; },
  };
}

async function open(page: Page, width = 1440, query = '?sales_employee_id=27') {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 1000 });
  await page.goto(`${base}/sales-workbench${query}`);
  await expect(page.getByLabel('沟通记录', { exact: true })).toBeVisible();
}
const notes = (page: Page) => page.getByLabel('沟通记录', { exact: true });
const save = (page: Page) => page.getByRole('button', { name: '保存并下一位', exact: true });
const key = (leadId = 501, userId = 27, salesId = 27) => `t24:sales-call-draft:v2:${userId}:${salesId}:${leadId}:${day()}:task:901`;

for (const width of [390, 1440]) {
  test(`切换、刷新及离开路由恢复正确客户的本地草稿（${width}）`, async ({ page }) => {
    const data = await fixture(page);
    await open(page, width);
    await notes(page).fill('甲商家1尚未提交的沟通');
    await page.getByRole('button', { name: '下一位客户', exact: true }).click();
    await notes(page).fill('甲商家2尚未提交的沟通');
    await expect(page.getByRole('status').filter({ hasText: '草稿已暂存' })).toBeVisible();
    if (screenshots) {
      await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
      await page.screenshot({ path: `${screenshots}/workbench-draft-local-${width}.png` });
      if (width === 1440) {
        await page.setViewportSize({ width: 1093, height: 824 });
        await page.screenshot({ path: `${screenshots}/workbench-draft-local-1093.png` });
        await page.setViewportSize({ width, height: 1000 });
      }
    }
    await page.reload();
    await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
    await expect(notes(page)).toHaveValue('甲商家2尚未提交的沟通');
    await expect(page.getByRole('status').filter({ hasText: '已恢复草稿' })).toBeVisible();
    await page.getByRole('navigation', { name: '销售中心导航' }).getByRole('link', { name: '知识库', exact: true }).click();
    await expect(page).toHaveURL(/sales-knowledge/);
    await page.getByRole('navigation', { name: '销售中心导航' }).getByRole('link', { name: '今日拨打', exact: true }).click();
    await expect(notes(page)).toHaveValue('甲商家2尚未提交的沟通');
    await page.getByRole('button', { name: '上一位客户', exact: true }).click();
    await expect(notes(page)).toHaveValue('甲商家1尚未提交的沟通');
    expect(data.writes).toEqual([]);
    await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
  });
}

test('登录用户、销售与lead分别隔离，task编号相同也不会串稿', async ({ page }) => {
  const data = await fixture(page, { user: { ...employee, id: 1, role: 'sales_manager' } });
  await open(page);
  await notes(page).fill('主管1为销售甲商家1记录的草稿');
  await page.getByRole('combobox', { name: '当前销售', exact: true }).selectOption('28');
  await expect(notes(page)).toHaveValue('');
  await notes(page).fill('主管1为销售乙的草稿');
  await page.getByRole('combobox', { name: '当前销售', exact: true }).selectOption('27');
  await expect(notes(page)).toHaveValue('主管1为销售甲商家1记录的草稿');
  data.changeLead(777);
  await page.reload();
  await expect(page.getByRole('heading', { name: '重新分配后的商家', exact: true })).toBeVisible();
  await expect(notes(page)).toHaveValue('');
  await notes(page).fill('主管1为新lead777的草稿');
  await data.setUser({ ...employee, id: 40, role: 'sales_manager' });
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  expect(data.writes).toEqual([]);
});

test('合法旧版草稿保留并迁移，超过一天仍须显式保存或丢弃', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(date => sessionStorage.setItem(`t24:sales-call-draft:v1:27:27:${date}:901`, JSON.stringify({ updatedAt: Date.now() - 3 * 86400000, values: { outcome: 'callback', notes: '三天前尚未提交的约定', nextFollowUpAt: '2026-10-15T10:30' } })), day());
  await open(page);
  await expect(notes(page)).toHaveValue('三天前尚未提交的约定');
  await expect(page.getByRole('status').filter({ hasText: '已恢复草稿' })).toBeVisible();
  expect(await page.evaluate(key => Boolean(sessionStorage.getItem(key)), key())).toBe(true);
  expect(data.writes).toEqual([]);
});

for (const raw of ['{broken', JSON.stringify({ version: 2, updatedAt: Date.now(), values: { outcome: 'interested', notes: { injected: 'invalid' }, nextFollowUpAt: '' } })]) {
  test(`损坏草稿不会崩溃、自动提交或删除原证据：${raw.slice(0, 15)}`, async ({ page }) => {
    const data = await fixture(page);
    await page.addInitScript(({ key, raw }) => sessionStorage.setItem(key, raw), { key: key(), raw });
    await open(page);
    await expect(notes(page)).toHaveValue('');
    await expect(page.getByRole('alert').filter({ hasText: '暂存草稿无法读取' })).toBeVisible();
    expect(await page.evaluate(key => sessionStorage.getItem(key), key())).toBe(raw);
    expect(data.writes).toEqual([]);
  });
}

test('浏览器暂存拒绝时明确提示风险，切换仍保留内存且成功保存不被存储错误误报', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const get = Storage.prototype.getItem;
    const set = Storage.prototype.setItem;
    const remove = Storage.prototype.removeItem;
    Storage.prototype.getItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return get.call(this, key); };
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return set.call(this, key, value); };
    Storage.prototype.removeItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return remove.call(this, key); };
  });
  await open(page, 390);
  await notes(page).fill('仅在当前页面保留');
  await expect(page.getByRole('status').filter({ hasText: '本次页面保留' })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: '刷新会丢失' })).toBeVisible();
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await page.getByRole('button', { name: '上一位客户', exact: true }).click();
  await expect(notes(page)).toHaveValue('仅在当前页面保留');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await save(page).click();
  await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
  await expect(page.getByRole('status', { name: '上次保存结果' })).toContainText('已保存');
  expect(data.writes).toHaveLength(1);
  await expect(page.getByText('保存失败，记录已保留，请重试', { exact: true })).toHaveCount(0);
});

test('丢弃草稿必须确认，取消不丢失且只清除当前商家', async ({ page }) => {
  const data = await fixture(page);
  await open(page, 390);
  await notes(page).fill('甲商家1待保存');
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await notes(page).fill('甲商家2待保存');
  await page.getByRole('button', { name: '上一位客户', exact: true }).click();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '丢弃草稿', exact: true }).click();
  await expect(notes(page)).toHaveValue('甲商家1待保存');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '丢弃草稿', exact: true }).click();
  await expect(notes(page)).toHaveValue('');
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await expect(notes(page)).toHaveValue('甲商家2待保存');
  expect(data.writes).toEqual([]);
});

test('显式退出会清除内存兜底，同账号重新登录也不会恢复已退出页面的内存草稿', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const get = Storage.prototype.getItem;
    const set = Storage.prototype.setItem;
    Storage.prototype.getItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return get.call(this, key); };
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return set.call(this, key, value); };
  });
  await open(page);
  await notes(page).fill('退出后不得恢复的内存草稿');
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByPlaceholder('请输入邮箱', { exact: true }).fill('sales@example.test');
  await page.getByPlaceholder('请输入密码', { exact: true }).fill('mock-password-only');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.getByRole('navigation', { name: '销售中心导航' }).getByRole('link', { name: '今日拨打', exact: true }).click();
  await expect(notes(page)).toHaveValue('');
  expect(data.writes.filter(write => /\/result$|\/prepare/.test(write.path))).toEqual([]);
});

test('浏览器拒绝删除但允许读写时，成功保存和确认丢弃后都不会再生旧草稿', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const remove = Storage.prototype.removeItem;
    Storage.prototype.removeItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return remove.call(this, key); };
  });
  await open(page);
  await notes(page).fill('删除失败也不应再生');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '丢弃草稿', exact: true }).click();
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await notes(page).fill('已成功提交不可再生');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await save(page).click();
  await expect.poll(() => page.evaluate(key => JSON.parse(sessionStorage.getItem(key) || '{}').cleared === true, key())).toBe(true);
  await page.locator('[data-lead-id="501"]').click();
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  expect(data.writes).toHaveLength(1);
});

test('保存已成功但浏览器删除和覆写都拒绝时，明确警示而不误报失败或重复提交', async ({ page }) => {
  const data = await fixture(page);
  await open(page);
  await notes(page).fill('业务保存成功但浏览器清除失败');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await page.evaluate(() => {
    const set = Storage.prototype.setItem;
    const remove = Storage.prototype.removeItem;
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('t24:sales-call-draft:')) throw new DOMException('Blocked', 'SecurityError'); return set.call(this, key, value); };
    Storage.prototype.removeItem = function(key) { if (key.startsWith('t24:sales-call-draft:')) throw new DOMException('Blocked', 'SecurityError'); return remove.call(this, key); };
  });
  await save(page).click();
  await expect(page.getByText('记录已保存；浏览器暂存无法清除，刷新可能恢复旧草稿，请勿重复提交', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
  await expect(page.getByText('保存失败，记录已保留，请重试', { exact: true })).toHaveCount(0);
  await page.locator('[data-lead-id="501"]').click();
  await expect(notes(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  expect(data.writes).toHaveLength(1);
});

test('保存失败保留，成功后下一位与回访入口对应已保存的lead且不生成重复任务', async ({ page }) => {
  const data = await fixture(page, { failFirstSave: true });
  await open(page, 390);
  await page.getByRole('button', { name: '待回访', exact: true }).click();
  await notes(page).fill('约定下周回电');
  await page.getByLabel(/^下次跟进/).fill('2026-10-15T10:30');
  await save(page).click();
  await expect(page.getByRole('alert').filter({ hasText: '保存失败，记录已保留' })).toBeVisible();
  await page.reload();
  await expect(notes(page)).toHaveValue('约定下周回电');
  await save(page).click();
  await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
  const receipt = page.getByRole('status', { name: '上次保存结果' });
  await expect(receipt).toContainText('已保存 · 甲商家1');
  if (screenshots) {
    await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `${screenshots}/workbench-save-local-390.png` });
  }
  expect(await page.evaluate(key => sessionStorage.getItem(key), key())).toBeNull();
  await page.route(`${base}/sales-leads?lead_id=501&action=followup`, route => route.fulfill({ contentType: 'text/html', body: '<title>本地跟进入口</title>' }));
  await receipt.getByRole('button', { name: '查看跟进', exact: true }).click();
  await expect(page).toHaveURL(`${base}/sales-leads?lead_id=501&action=followup`);
  expect(data.writes.map(write => write.path)).toEqual(['/api/v1/sales-leads/workbench/tasks/901/result', '/api/v1/sales-leads/workbench/tasks/901/result']);
});

test('有意向成功后报价入口对应已保存客户，报价导航不产生业务写入', async ({ page }) => {
  const data = await fixture(page);
  await open(page);
  await page.getByRole('button', { name: '有意向', exact: true }).click();
  await notes(page).fill('已讨论服务范围');
  await page.getByLabel(/^下次跟进/).fill('2026-10-15T10:30');
  await save(page).click();
  const receipt = page.getByRole('status', { name: '上次保存结果' });
  await expect(receipt).toContainText('甲商家1');
  if (screenshots) {
    await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `${screenshots}/workbench-save-local-1440.png` });
  }
  await page.route(`${base}/sales-leads?lead_id=501&action=quote`, route => route.fulfill({ contentType: 'text/html', body: '<title>本地报价入口</title>' }));
  await receipt.getByRole('button', { name: '准备报价', exact: true }).click();
  await expect(page).toHaveURL(`${base}/sales-leads?lead_id=501&action=quote`);
  expect(data.writes).toHaveLength(1);
  expect(data.writes[0].body).toMatchObject({ outcome: 'interested', notes: '已讨论服务范围', next_follow_up_at: '2026-10-15T02:30:00.000Z' });
});

test('保存已经成功而队列刷新失败时不会误报保存失败或允许重复完成', async ({ page }) => {
  const data = await fixture(page, { failReadAfterSave: true });
  await open(page);
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await save(page).click();
  await expect(page.getByRole('status', { name: '上次保存结果' })).toContainText('已保存');
  await expect(page.getByRole('alert').filter({ hasText: '今日任务暂时无法更新' })).toBeVisible();
  await page.locator('[data-lead-id="501"]').click();
  await expect(save(page)).toBeDisabled();
  await expect(notes(page)).toHaveValue('');
  expect(data.writes).toHaveLength(1);
});

test('禁联或转客户的历史草稿不恢复，也没有报价或重复结果入口', async ({ page }) => {
  const data = await fixture(page, { protected: true });
  await page.addInitScript(key => sessionStorage.setItem(key, JSON.stringify({ version: 2, updatedAt: Date.now(), values: { outcome: 'interested', notes: '应保留但不能恢复的草稿', nextFollowUpAt: '' } })), key());
  await open(page);
  await expect(notes(page)).toHaveValue('');
  await expect(notes(page)).toBeDisabled();
  await expect(save(page)).toBeDisabled();
  await expect(page.getByRole('button', { name: '拨打电话', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await expect(notes(page)).toBeDisabled();
  await expect(page.getByRole('button', { name: '准备报价', exact: true })).toHaveCount(0);
  expect(data.writes).toEqual([]);
});

test('空任务与读取失败分别呈现，只有明确操作才能生成任务', async ({ page }) => {
  const data = await fixture(page, { empty: true, failRead: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/sales-workbench`);
  await expect(page.getByRole('heading', { name: '今日任务暂不可用' })).toBeVisible();
  await expect(page.getByRole('button', { name: '生成今日任务', exact: true })).toHaveCount(0);
  data.recover();
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('heading', { name: '当前队列暂无任务', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '生成今日任务', exact: true })).toBeEnabled();
  expect(data.writes).toEqual([]);
  expect(data.reads.some(path => /dashboard\/management|merchant-pool\/stats/.test(path))).toBe(false);
});

test('主管仍默认只读团队，明确打开个人任务后使用实际销售草稿范围', async ({ page }) => {
  const data = await fixture(page, { user: { ...employee, id: 1, role: 'sales_manager' } });
  await page.goto(`${base}/sales-workbench`);
  await expect(page.getByRole('heading', { name: '团队今日任务', exact: true })).toBeVisible();
  await expect(notes(page)).toHaveCount(0);
  await page.getByRole('button', { name: '查看任务：模拟销售乙', exact: true }).click();
  await expect(page.getByRole('heading', { name: '乙商家1', exact: true })).toBeVisible();
  await notes(page).fill('仅主管1和销售28的客户范围');
  expect(data.writes).toEqual([]);
});
