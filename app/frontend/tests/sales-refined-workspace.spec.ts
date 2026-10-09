import { expect, test, type Locator, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshotDir = process.env.T24_UI_SCREENSHOT_DIR;
type Employee = { id: number; name: string; role: string; status: string };
type Write = { method: string; path: string; data: Record<string, unknown> | null };
type ProviderCall = { available: boolean; sync_status: string; connected?: boolean; duration_seconds?: number };
type FixtureTask = {
  task_id: number;
  task_status: string;
  priority: string;
  queue_category: string;
  next_action_label: string;
  lead: {
    id: number;
    business_name: string;
    contact_name: string;
    phone: string;
    country: string;
    industry: string;
    city: string;
    state: string;
    status: string;
    do_not_contact: boolean;
    is_blacklisted: boolean;
  };
};

const salesEmployee: Employee = { id: 27, name: '精简工作台销售', role: 'sales', status: 'active' };
const assignees = [{ id: 27, name: '精简工作台销售' }, { id: 28, name: '第二位销售' }];

function tasks(count = 2): FixtureTask[] {
  return Array.from({ length: count }, (_, index) => ({
    task_id: 901 + index,
    task_status: 'pending',
    priority: 'normal',
    queue_category: 'new',
    next_action_label: '确认商家需求并约定下一步',
    lead: {
      id: 501 + index,
      business_name: index === 0 ? '第一位商家' : index === 1 ? '第二位商家' : `第${index + 1}位商家`,
      contact_name: '店主',
      phone: `+1 212 555 ${String(126 + index).padStart(4, '0')}`,
      country: 'US',
      industry: '餐饮',
      city: 'New York',
      state: 'NY',
      status: 'new',
      do_not_contact: false,
      is_blacklisted: false,
    },
  }));
}

// A stale task can remain visible while protection is being refreshed. The UI
// must still refuse dial/result actions rather than rely only on queue filtering.
function protectedTasks(): FixtureTask[] {
  const records = tasks(3);
  records[1].lead = { ...records[1].lead, business_name: '明确禁止联系商家', status: 'blocked', do_not_contact: true };
  records[2].lead = { ...records[2].lead, business_name: '黑名单商家', is_blacklisted: true };
  return records;
}

async function mockWorkbench(page: Page, options: { employee?: Employee; records?: FixtureTask[]; failFirstSave?: boolean; allowSupplemental?: boolean; providerCall?: ProviderCall } = {}) {
  const employee = options.employee || salesEmployee;
  const records = options.records || tasks();
  const writes: Write[] = [];
  const rejectedWrites: Write[] = [];
  const successfulResults = new Set(records.filter(record => record.task_status === 'completed').map(record => record.task_id));
  let providerCall = options.providerCall || { available: false, sync_status: 'waiting' };
  let resultAttempts = 0;

  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'sales-refined-local-token');
    localStorage.setItem('token', 'sales-refined-local-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    let data: unknown = { items: [], total: 0 };
    let status = 200;

    if (!['GET', 'HEAD'].includes(method)) {
      const write = { method, path, data: request.postData() ? request.postDataJSON() : null };
      writes.push(write);
      const result = path.match(/^\/api\/v1\/sales-leads\/workbench\/tasks\/(\d+)\/result$/);
      const dial = path.match(/^\/api\/v1\/sales-leads\/workbench\/tasks\/(\d+)\/dial-started$/);
      const supplemental = path.match(/^\/api\/v1\/sales-leads\/(\d+)\/follow-up$/);
      if (method === 'POST' && result && records.some(record => record.task_id === Number(result[1]))) {
        resultAttempts += 1;
        if (options.failFirstSave && resultAttempts === 1) {
          status = 500;
          data = { detail: '本地模拟：结果保存失败，请重试' };
        } else {
          successfulResults.add(Number(result[1]));
          data = { message: '通话结果已记录，今日任务进度已更新' };
        }
      } else if (method === 'POST' && dial && records.some(record => record.task_id === Number(dial[1]))) {
        // Opening a dialer never marks a task completed or invents a call result.
        data = { message: '拨号意图已记录' };
      } else if (options.allowSupplemental && method === 'POST' && supplemental && records.some(record => record.lead.id === Number(supplemental[1]))) {
        // Supplemental follow-up adds contact history without repeating a task result.
        data = { message: '追加跟进已记录，不影响今日任务完成数' };
      } else {
        rejectedWrites.push(write);
        status = 409;
        data = { detail: '该测试不允许此业务写入' };
      }
    } else if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/sales-leads/assignees')) data = assignees;
    else if (path.endsWith('/sales-leads/workbench/today')) {
      const salesId = Number(url.searchParams.get('sales_employee_id') || employee.id);
      data = {
        salesperson: { id: salesId, name: assignees.find(item => item.id === salesId)?.name || employee.name },
        quota: 20,
        assigned_count: records.length,
        completed_count: successfulResults.size,
        remaining_count: records.length - successfulResults.size,
        is_target_complete: false,
        categories: { unfinished: records.length - successfulResults.size, callback: 0, interested: 0, appointment: 0, new: records.length, retry: 0, recycled: 0, follow_up: 0 },
        performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 },
        items: records.map(record => ({ ...record, task_status: successfulResults.has(record.task_id) ? 'completed' : 'pending' })),
      };
    } else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false, realtime_sync_enabled: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = providerCall;
    else if (path.endsWith('/call-history')) data = [];
    else if (path.endsWith('/sales-knowledge/articles')) data = { items: [], categories: [] };
    else if (path.endsWith('/sales-leads/automation/overview')) data = {};
    else if (path.includes('/app-config')) data = { items: {} };

    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return { writes, rejectedWrites, successfulResults, setProviderCall: (value: ProviderCall) => { providerCall = value; } };
}

function workbench(page: Page, width: number) {
  return page.getByTestId(width < 768 ? 'sales-workbench-mobile' : 'sales-workbench-desktop');
}

async function openWorkbench(page: Page, width: number, completed = 0) {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 1000 });
  await page.goto(`${baseUrl}/sales-workbench?sales_employee_id=27`);
  const surface = workbench(page, width);
  await expect(surface).toBeVisible();
  await expect(surface.getByRole('heading', { name: '今日拨打', exact: true })).toBeVisible();
  await expect(surface.getByLabel('沟通记录', { exact: true })).toBeVisible();
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', String(completed));
  return surface;
}

async function chooseTask(surface: Locator, width: number, taskId: number) {
  if (width < 768) await surface.getByRole('combobox', { name: '选择客户', exact: true }).selectOption(String(taskId));
  else await surface.locator(`[data-lead-id="${taskId - 400}"]`).click();
}

async function expectNoOverflow(page: Page) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(sizes.document).toBeLessThanOrEqual(sizes.viewport);
  expect(sizes.body).toBeLessThanOrEqual(sizes.viewport);
}

for (const width of [390, 1440]) {
  test(`切换客户、刷新与返回保留各自草稿且不计完成（${width}px）`, async ({ page }) => {
    const fixture = await mockWorkbench(page);
    const surface = await openWorkbench(page, width);
    const notes = surface.getByLabel('沟通记录', { exact: true });
    await surface.getByRole('button', { name: '有意向', exact: true }).click();
    await notes.fill('第一位商家：周五和老板确认预算');
    await surface.getByLabel(/^下次跟进/).fill('2026-10-12T10:30');
    await surface.getByRole('button', { name: '下一位客户', exact: true }).click();
    await expect(notes).toHaveValue('');
    await surface.getByRole('button', { name: '未接通', exact: true }).click();
    await notes.fill('第二位商家：午间无人接听');
    await surface.getByRole('button', { name: '上一位客户', exact: true }).click();
    await expect(notes).toHaveValue('第一位商家：周五和老板确认预算');
    await expect(surface.getByRole('button', { name: '有意向', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(surface.getByLabel(/^下次跟进/)).toHaveValue('2026-10-12T10:30');

    await page.reload();
    await expect(notes).toHaveValue('第一位商家：周五和老板确认预算');
    await chooseTask(surface, width, 902);
    await expect(notes).toHaveValue('第二位商家：午间无人接听');
    await expect(surface.getByRole('button', { name: '未接通', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await chooseTask(surface, width, 901);
    await expect(notes).toHaveValue('第一位商家：周五和老板确认预算');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
    expect(fixture.writes).toHaveLength(0);
    await expectNoOverflow(page);
  });

  test(`保存失败保留草稿，明确重试成功才推进下一位（${width}px）`, async ({ page }) => {
    const fixture = await mockWorkbench(page, { failFirstSave: true });
    const surface = await openWorkbench(page, width);
    const notes = surface.getByLabel('沟通记录', { exact: true });
    await surface.getByRole('button', { name: '待回访', exact: true }).click();
    await notes.fill('店主约定周一上午回电，讨论官网预约需求');
    await surface.getByLabel(/^下次跟进/).fill('2026-10-12T10:30');
    await surface.getByRole('button', { name: '保存并下一位', exact: true }).click();

    await expect(page.getByText('本地模拟：结果保存失败，请重试', { exact: true })).toBeVisible();
    await expect(surface.getByRole('alert')).toHaveText('保存失败，记录已保留，请重试');
    await expect(notes).toHaveValue('店主约定周一上午回电，讨论官网预约需求');
    await expect(surface.getByRole('button', { name: '待回访', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(surface.getByLabel(/^下次跟进/)).toHaveValue('2026-10-12T10:30');
    await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
    expect(fixture.successfulResults.size).toBe(0);

    await page.reload();
    await expect(notes).toHaveValue('店主约定周一上午回电，讨论官网预约需求');
    await surface.getByRole('button', { name: '保存并下一位', exact: true }).click();
    await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '1');
    await expect(surface.getByRole('heading', { name: '第二位商家', exact: true })).toBeVisible();
    await expect(notes).toHaveValue('');
    const results = fixture.writes.filter(write => write.path.endsWith('/result'));
    expect(results).toHaveLength(2);
    for (const result of results) expect(result).toMatchObject({ method: 'POST', path: '/api/v1/sales-leads/workbench/tasks/901/result', data: { outcome: 'callback', notes: '店主约定周一上午回电，讨论官网预约需求', next_follow_up_at: '2026-10-12T02:30:00.000Z' } });
    expect(fixture.rejectedWrites).toHaveLength(0);
    await chooseTask(surface, width, 901);
    await expect(notes).toHaveValue('');
    await expect(surface.getByRole('button', { name: '保存并下一位', exact: true })).toBeDisabled();
  });

  test(`禁止联系和黑名单记录不能拨打或提交结果（${width}px）`, async ({ page }) => {
    const fixture = await mockWorkbench(page, { records: protectedTasks() });
    const surface = await openWorkbench(page, width);
    for (const id of [902, 903]) {
      await chooseTask(surface, width, id);
      await expect(surface.getByRole('button', { name: '拨打电话', exact: true })).toBeDisabled();
      await expect(surface.getByLabel('沟通记录', { exact: true })).toBeDisabled();
      for (const outcome of ['未接通', '待回访', '有意向', '已预约']) {
        await expect(surface.getByRole('button', { name: outcome, exact: true })).toBeDisabled();
      }
      await expect(surface.getByRole('button', { name: '保存并下一位', exact: true })).toBeDisabled();
    }
    expect(page.url()).toBe(`${baseUrl}/sales-workbench?sales_employee_id=27`);
    expect(fixture.writes).toHaveLength(0);
    expect(fixture.successfulResults.size).toBe(0);
  });
}

test('手机全队列可切换，RingCentral 返回保留内联草稿且不虚报官方接通', async ({ page }) => {
  const fixture = await mockWorkbench(page, { records: tasks(15) });
  const surface = await openWorkbench(page, 390);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/sales-workbench-mobile-390.png` });
  const customerSelect = surface.getByRole('combobox', { name: '选择客户', exact: true });
  await expect(customerSelect.locator('option:not([disabled])')).toHaveCount(15);
  await chooseTask(surface, 390, 915);
  await expect(surface.getByRole('heading', { name: '第15位商家', exact: true })).toBeVisible();
  await surface.getByRole('button', { name: '待回访', exact: true }).click();
  await surface.getByLabel('沟通记录', { exact: true }).fill('第15位商家约定明天回电，不要丢失');
  await surface.getByLabel(/^下次跟进/).fill('2026-10-12T10:30');
  const dial = surface.getByRole('button', { name: '拨打电话', exact: true });
  const box = await dial.boundingBox();
  expect(box?.height || 0).toBeGreaterThanOrEqual(44);
  expect(box?.width || 0).toBeGreaterThanOrEqual(44);
  await page.route('https://app.ringcentral.com/**', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Locally intercepted RingCentral handoff</title>' }));
  await dial.click();
  await expect(page).toHaveURL('https://app.ringcentral.com/r/call?number=12125550140');
  await expect.poll(() => fixture.writes.filter(write => write.path.endsWith('/dial-started')).length).toBe(1);
  expect(fixture.writes.filter(write => write.path.endsWith('/result'))).toHaveLength(0);
  expect(fixture.successfulResults.size).toBe(0);

  await page.goBack();
  await expect(page).toHaveURL(`${baseUrl}/sales-workbench?sales_employee_id=27`);
  await expect(customerSelect).toHaveValue('915');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toHaveValue('第15位商家约定明天回电，不要丢失');
  await expect(surface.getByRole('button', { name: '待回访', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(surface.getByLabel(/^下次跟进/)).toHaveValue('2026-10-12T10:30');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(surface.getByText(/官方接通|RingCentral 已验证接通/)).toHaveCount(0);
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
  expect(fixture.rejectedWrites).toHaveLength(0);
  await expectNoOverflow(page);
});

test('结果必须明确选择，有意向记录缺少内容或时间时不能提交', async ({ page }) => {
  const fixture = await mockWorkbench(page);
  const surface = await openWorkbench(page, 390);
  const save = surface.getByRole('button', { name: '保存并下一位', exact: true });
  await save.click();
  await expect(surface.getByRole('alert')).toContainText('请选择');
  expect(fixture.writes).toHaveLength(0);

  await surface.getByRole('button', { name: '有意向', exact: true }).click();
  await save.click();
  await expect(surface.getByRole('alert')).toContainText('沟通');
  expect(fixture.writes).toHaveLength(0);

  await surface.getByLabel('沟通记录', { exact: true }).fill('商家希望了解预约功能，下次和老板一起确认');
  await surface.getByLabel(/^下次跟进/).fill('');
  await save.click();
  await expect(surface.getByRole('alert')).toContainText('跟进时间');
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
  expect(fixture.writes).toHaveLength(0);

  await surface.getByLabel(/^下次跟进/).fill('2026-10-12T10:30');
  await save.click();
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '1');
  expect(fixture.writes).toHaveLength(1);
  expect(fixture.writes[0]).toMatchObject({ path: '/api/v1/sales-leads/workbench/tasks/901/result', data: { outcome: 'interested', notes: '商家希望了解预约功能，下次和老板一起确认', next_follow_up_at: '2026-10-12T02:30:00.000Z' } });
  expect(fixture.rejectedWrites).toHaveLength(0);
});

test('主管切换销售或工作日时草稿隔离，切回原范围可继续', async ({ page }) => {
  const fixture = await mockWorkbench(page, { employee: { id: 1, name: '工作台主管', role: 'sales_manager', status: 'active' } });
  const surface = await openWorkbench(page, 1440);
  // These low-frequency controls can be collapsed by default but remain explicit.
  const date = surface.getByLabel('任务日期（北京时间）', { exact: true });
  const salesperson = surface.getByRole('combobox', { name: '当前销售', exact: true });
  const originalDate = await date.inputValue();
  await surface.getByLabel('沟通记录', { exact: true }).fill('销售27今天的私有草稿');
  await salesperson.selectOption('28');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toHaveValue('');
  await surface.getByLabel('沟通记录', { exact: true }).fill('销售28今天的独立草稿');
  await salesperson.selectOption('27');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toHaveValue('销售27今天的私有草稿');
  await date.fill(originalDate === '2026-10-08' ? '2026-10-07' : '2026-10-08');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toHaveValue('');
  await date.fill(originalDate);
  await expect(surface.getByLabel('沟通记录', { exact: true })).toHaveValue('销售27今天的私有草稿');
  expect(fixture.writes).toHaveLength(0);
});

test('已完成任务可追加拨号跟进，官方状态独立且禁止联系仍受保护', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
  const records = protectedTasks().map(record => ({ ...record, task_status: 'completed' }));
  const fixture = await mockWorkbench(page, {
    records,
    allowSupplemental: true,
    providerCall: { available: true, sync_status: 'verified', connected: false, duration_seconds: 61 },
  });
  const surface = await openWorkbench(page, 390, 3);
  const progress = page.getByRole('progressbar', { name: '任务完成进度' });
  await expect(surface.getByRole('button', { name: '拨打电话', exact: true })).toBeDisabled();
  await expect(surface.getByLabel('沟通记录', { exact: true })).toBeDisabled();
  await expect(surface.getByRole('button', { name: '保存并下一位', exact: true })).toBeDisabled();
  await expect(surface.getByRole('status').filter({ hasText: '官方未接通 · 1:01' })).toBeVisible();

  await surface.getByRole('button', { name: '更多客户操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '追加跟进', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '追加跟进 · 第一位商家', exact: true });
  await expect(dialog.getByRole('button', { name: '再次拨打', exact: true })).toBeEnabled();
  await dialog.getByRole('button', { name: '复制号码', exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('+12125550126');
  await dialog.getByRole('button', { name: '有意向', exact: true }).click();
  await dialog.getByLabel('沟通记录', { exact: true }).fill('追加沟通：老板约定周一确认预约方案');
  await dialog.getByLabel(/^下次跟进/).fill('2026-10-12T10:30');
  await expect(dialog.getByRole('status').filter({ hasText: '官方未接通 · 1:01' })).toBeVisible();
  await expect(dialog.getByRole('status').filter({ hasText: '官方接通' })).toHaveCount(0);
  expect(fixture.writes).toHaveLength(0);

  await page.route('https://app.ringcentral.com/**', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Locally intercepted supplemental dial</title>' }));
  await dialog.getByRole('button', { name: '再次拨打', exact: true }).click();
  await expect(page).toHaveURL('https://app.ringcentral.com/r/call?number=12125550126');
  expect(fixture.writes).toHaveLength(0);
  expect(fixture.successfulResults.size).toBe(3);

  await page.goBack();
  await expect(page).toHaveURL(`${baseUrl}/sales-workbench?sales_employee_id=27`);
  await expect(progress).toHaveAttribute('aria-valuenow', '3');
  await surface.getByRole('button', { name: '更多客户操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '追加跟进', exact: true }).click();
  await expect(dialog.getByLabel('沟通记录', { exact: true })).toHaveValue('追加沟通：老板约定周一确认预约方案');
  await expect(dialog.getByRole('button', { name: '有意向', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByLabel(/^下次跟进/)).toHaveValue('2026-10-12T10:30');
  await expect(dialog.getByRole('status').filter({ hasText: '官方未接通 · 1:01' })).toBeVisible();

  // Official status changes only when the provider's GET response changes.
  fixture.setProviderCall({ available: true, sync_status: 'verified', connected: true, duration_seconds: 123 });
  await expect(dialog.getByRole('status').filter({ hasText: '官方接通 · 2:03' })).toBeVisible({ timeout: 7000 });
  await dialog.getByRole('button', { name: '保存跟进', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(progress).toHaveAttribute('aria-valuenow', '3');
  expect(fixture.writes).toHaveLength(1);
  expect(fixture.writes[0]).toMatchObject({ method: 'POST', path: '/api/v1/sales-leads/501/follow-up', data: { outcome: 'interested', notes: '追加沟通：老板约定周一确认预约方案', next_follow_up_at: '2026-10-12T02:30:00.000Z' } });
  expect(fixture.writes.some(write => /\/result$|\/dial-started$/.test(write.path))).toBe(false);
  expect(fixture.rejectedWrites).toHaveLength(0);

  for (const taskId of [902, 903]) {
    await chooseTask(surface, 390, taskId);
    await surface.getByRole('button', { name: '更多客户操作', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: '追加跟进', exact: true })).toHaveCount(0);
    const menu = page.getByRole('menu', { name: '更多客户操作' });
    await expect(menu).toBeVisible();
    await menu.press('Escape');
    await expect(menu).toHaveCount(0);
    await expect(surface.getByRole('button', { name: '拨打电话', exact: true })).toBeDisabled();
    await expect(surface.getByLabel('沟通记录', { exact: true })).toBeDisabled();
  }
  await expect(progress).toHaveAttribute('aria-valuenow', '3');
  expect(fixture.writes).toHaveLength(1);
});

for (const role of ['sales', 'sales_manager']) {
  test(`统一销售导航遵循 ${role} 权限，首屏主操作可用`, async ({ page }) => {
    await mockWorkbench(page, { employee: { ...salesEmployee, role } });
    const surface = await openWorkbench(page, 1440);
    const nav = page.getByRole('navigation', { name: '销售中心导航', exact: true });
    for (const name of ['今日拨打', '联系进展', '知识库']) await expect(nav.getByRole('link', { name, exact: true })).toBeVisible();
    if (role === 'sales_manager') await expect(nav.getByRole('link', { name: '商家池', exact: true })).toBeVisible();
    else await expect(nav.getByRole('link', { name: '商家池', exact: true })).toHaveCount(0);
    for (const control of [surface.getByRole('button', { name: '拨打电话', exact: true }), surface.getByLabel('沟通记录', { exact: true })]) {
      await expect(control).toBeInViewport();
    }
    await expectNoOverflow(page);
    if (role === 'sales') {
      await page.setViewportSize({ width: 1093, height: 824 });
      await expect(surface.getByRole('button', { name: '拨打电话', exact: true })).toBeInViewport();
      await expect(surface.getByLabel('沟通记录', { exact: true })).toBeInViewport();
      await expectNoOverflow(page);
      if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/sales-workbench-desktop-1093.png` });
    }
  });
}
