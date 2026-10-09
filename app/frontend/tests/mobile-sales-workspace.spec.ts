import { expect, test, type Locator, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshots = process.env.T24_UI_SCREENSHOT_DIR;
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const sales = { id: 27, name: '模拟销售甲', role: 'sales', status: 'active' };
type Write = { path: string; body: Record<string, unknown> };

// Every API is local. No real dialer, task generation or production writes are allowed.
async function fixture(page: Page, options: { manager?: boolean; failFirst?: boolean; holdSave?: boolean; protected?: boolean; empty?: boolean; failRead?: boolean } = {}) {
  const user = options.manager ? { ...sales, id: 1, role: 'sales_manager' } : sales;
  const tasks = options.empty ? [] : Array.from({ length: 22 }, (_, index) => ({
    task_id: 901 + index, task_status: 'pending', priority: 'normal', queue_category: 'new',
    lead: { id: 501 + index, business_name: index === 0 ? '示例商家甲' : index === 1 ? '示例商家乙' : `示例商家 ${index + 1}`, phone: `+1 202 555 ${String(123 + index).padStart(4, '0')}`, country: 'US', city: index === 1 ? 'Seattle' : 'Queens', industry: '餐饮', status: 'new', do_not_contact: Boolean(options.protected && index === 0), is_blacklisted: false, next_follow_up_at: '' },
  }));
  const writes: Write[] = [];
  const reads: string[] = [];
  let attempts = 0;
  let releaseSave: (() => void) | undefined;
  await page.addInitScript(user => {
    localStorage.setItem('emp_auth_token', 'mobile-sales-local-token');
    localStorage.setItem('token', 'mobile-sales-local-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(user));
  }, user);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (!['GET', 'HEAD'].includes(request.method())) {
      const body = request.postDataJSON();
      writes.push({ path, body });
      const taskId = path.match(/\/workbench\/tasks\/(\d+)\/result$/)?.[1];
      const task = taskId && tasks.find(item => item.task_id === Number(taskId));
      if (!task || task.task_status !== 'pending' || task.lead.do_not_contact) return route.fulfill({ status: 409, json: { detail: '测试禁止额外业务写入' } });
      attempts++;
      if (options.failFirst && attempts === 1) return route.fulfill({ status: 503, json: { detail: '模拟断网' } });
      if (options.holdSave) await new Promise<void>(resolve => { releaseSave = resolve; });
      task.task_status = 'completed';
      task.lead.status = body.outcome === 'interested' ? 'interested' : body.outcome === 'callback' ? 'follow_up' : 'contacted';
      task.lead.next_follow_up_at = body.next_follow_up_at || '';
      return route.fulfill({ json: { task_id: task.task_id, lead_id: task.lead.id, lead: task.lead, message: '通话结果已记录' } });
    }
    reads.push(path + url.search);
    let data: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = user;
    else if (path.endsWith('/sales-leads/assignees')) data = [{ id: 27, name: sales.name }, { id: 28, name: '模拟销售乙' }];
    else if (path.endsWith('/sales-leads/workbench/today')) {
      if (options.failRead) return route.fulfill({ status: 503, json: { detail: '模拟读取失败' } });
      const completed = tasks.filter(task => task.task_status === 'completed').length;
      const id = options.manager ? Number(url.searchParams.get('sales_employee_id') || 27) : 27;
      data = { salesperson: { id, name: id === 28 ? '模拟销售乙' : sales.name }, quota: 30, assigned_count: tasks.length, completed_count: completed, remaining_count: tasks.length - completed, is_target_complete: false, categories: { unfinished: tasks.length - completed, callback: 0, interested: 0, appointment: 0, new: tasks.length, retry: 0, recycled: 0, follow_up: 0 }, performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items: tasks };
    } else if (path.endsWith('/call-history')) data = [{ id: 71, outcome_label: '未接通', notes: '上次午间未接通，晚些时候联系', called_at: '2026-10-09T04:00:00Z' }];
    else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = { available: true, sync_status: 'waiting' };
    else if (path.endsWith('/dashboard/management')) data = { owner_attention: { overdue_followups: 0, high_intent_stale: 0 } };
    else if (path.endsWith('/dashboard/call-report')) data = { source: { status: 'verified' }, summary: { connected: 0 } };
    else if (path.endsWith('/sales-knowledge/articles')) data = { items: [], categories: [] };
    else if (path.includes('/app-config')) data = { items: {} };
    await route.fulfill({ json: data });
  });
  return { writes, reads, release: () => releaseSave?.(), tasks };
}

async function open(page: Page, width: number, height = 844) {
  await page.setViewportSize({ width, height });
  await page.goto(`${base}/sales-workbench?sales_employee_id=27`);
  await expect(page.getByLabel('沟通记录', { exact: true })).toBeVisible();
}
async function reachable(control: Locator) {
  await control.evaluate(element => element.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' }));
  await expect(control).toBeInViewport({ ratio: 1 });
  await expect.poll(() => control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const top = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return top === element || Boolean(top && element.contains(top));
  }), { message: '控件中心不能被保存条或底部导航遮挡' }).toBe(true);
}
async function geometry(page: Page) {
  const sizes = await page.evaluate(() => ({ w: innerWidth, h: innerHeight, documentW: document.documentElement.scrollWidth, documentH: document.documentElement.scrollHeight, mainW: document.querySelector('main')!.clientWidth, mainScrollW: document.querySelector('main')!.scrollWidth }));
  expect(sizes.documentW).toBeLessThanOrEqual(sizes.w + 1);
  expect(sizes.mainScrollW).toBeLessThanOrEqual(sizes.mainW + 1);
  expect(sizes.documentH).toBeLessThanOrEqual(sizes.h + 1);
}
async function choose(page: Page, id: number) {
  await page.getByRole('button', { name: '打开客户队列', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: '客户队列', exact: true });
  await sheet.locator(`[data-task-id="${id}"]`).click();
  await expect(sheet).toBeHidden();
}

for (const viewport of [{ width: 320, height: 844 }, { width: 360, height: 800 }, { width: 390, height: 844 }, { width: 430, height: 932 }, { width: 390, height: 520 }]) {
  test(`手机 ${viewport.width}x${viewport.height} 首屏简洁且记录、动态字段和保存无遮挡`, async ({ page }) => {
    const data = await fixture(page);
    await open(page, viewport.width, viewport.height);
    await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText(today());
    await expect(page.getByRole('button', { name: '打开客户队列', exact: true })).toBeInViewport({ ratio: 1 });
    const phone = page.locator('.sw-phone strong');
    expect((await phone.boundingBox())!.height).toBeLessThanOrEqual(32);
    const notes = page.getByLabel('沟通记录', { exact: true });
    if (viewport.height > 520) expect((await notes.boundingBox())!.y, '常规手机首屏必须看到记录输入').toBeLessThan(viewport.height - 180);
    for (const name of ['打开客户队列', '上一位客户', '下一位客户', '更多客户操作', '复制客户号码', '拨打电话']) {
      const box = await page.getByRole('button', { name, exact: true }).boundingBox();
      // Browser geometry may report 43.99998 for a computed 44 CSS pixels.
      expect(Math.round(box!.width), `${name}触控宽度`).toBeGreaterThanOrEqual(44);
      expect(Math.round(box!.height), `${name}触控高度`).toBeGreaterThanOrEqual(44);
    }
    if (screenshots) await page.screenshot({ path: `${screenshots}/mobile-workbench-${viewport.width}x${viewport.height}-initial.png` });
    await test.info().attach('initial-layout-geometry', { contentType: 'application/json', body: JSON.stringify(await page.evaluate(() => {
      const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect().toJSON();
      return { main: rect('main'), footer: rect('.sw-current .sc-record-footer'), notes: rect('.sw-notes'), nav: rect('.mobile-bottom-nav'), mainPadding: getComputedStyle(document.querySelector('main')!).padding, stickyBottom: getComputedStyle(document.querySelector('.sc-record-footer')!).bottom };
    })) });
    await reachable(notes);
    await notes.fill('手机记录：客户计划升级官网预约，约定下次确认预算');
    expect(await notes.evaluate(element => getComputedStyle(element).fontSize)).toBe('16px');
    await reachable(page.getByRole('button', { name: '有意向', exact: true }));
    await page.getByRole('button', { name: '有意向', exact: true }).click();
    const followup = page.getByLabel(/^下次跟进/);
    await reachable(followup);
    await followup.fill('2026-10-15T10:30');
    await page.locator('summary').filter({ hasText: /^更多信息$/ }).click();
    const need = page.getByLabel('真实需求', { exact: true });
    await reachable(need);
    await need.fill('官网接收预约');
    const nextStep = page.getByLabel('下一步', { exact: true });
    await reachable(nextStep);
    await nextStep.fill('下次电话确认预算');
    const save = page.getByRole('button', { name: '保存并下一位', exact: true });
    await expect(save).toHaveCount(1);
    await reachable(save);
    await geometry(page);
    if (screenshots) await page.screenshot({ path: `${screenshots}/mobile-workbench-${viewport.width}x${viewport.height}-record.png` });
    await save.click();
    await expect(page.getByRole('heading', { name: '示例商家乙', exact: true })).toBeVisible();
    await expect(notes).toHaveValue('');
    expect(data.writes).toHaveLength(1);
    expect(data.writes[0]).toMatchObject({ path: '/api/v1/sales-leads/workbench/tasks/901/result', body: { outcome: 'interested', notes: '手机记录：客户计划升级官网预约，约定下次确认预算', next_follow_up_at: '2026-10-15T02:30:00.000Z', contact_details: { need_summary: '官网接收预约' } } });
    await expect(page.getByRole('status', { name: '上次保存结果' })).toContainText('示例商家甲');
    await expect(page.getByRole('status', { name: '上次保存结果' }).getByRole('button', { name: '准备报价', exact: true })).toBeVisible();
    await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '1');
  });
}

test('队列按客户、号码、城市本地搜索，22项均可到达且切换不计完成', async ({ page }) => {
  const data = await fixture(page);
  await open(page, 320);
  const notes = page.getByLabel('沟通记录', { exact: true });
  await notes.fill('示例商家甲尚未保存');
  await page.getByRole('button', { name: '打开客户队列', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: '客户队列', exact: true });
  await expect(sheet.locator('[data-task-id]')).toHaveCount(22);
  await expect(sheet.locator('[data-task-id="901"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(sheet).toBeInViewport({ ratio: 1 });
  if (screenshots) await page.screenshot({ path: `${screenshots}/mobile-queue-320.png` });
  const search = sheet.getByLabel('搜索客户队列', { exact: true });
  for (const query of ['示例商家乙', '5550124', 'Seattle']) {
    await search.fill(query);
    await expect(sheet.locator('[data-task-id]')).toHaveCount(1);
    await expect(sheet.locator('[data-task-id="902"]')).toBeVisible();
  }
  await search.fill('不存在的商家');
  await expect(sheet.getByText('没有匹配的客户', { exact: true })).toBeVisible();
  await search.fill('');
  const last = sheet.locator('[data-task-id="922"]');
  await reachable(last);
  expect((await last.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await last.click();
  await expect(page.getByRole('heading', { name: '示例商家 22', exact: true })).toBeVisible();
  await notes.fill('最后一位未保存');
  await choose(page, 901);
  await expect(notes).toHaveValue('示例商家甲尚未保存');
  await page.reload();
  await expect(notes).toHaveValue('示例商家甲尚未保存');
  expect(data.writes).toEqual([]);
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
});

test('保存失败保留草稿并可重试，正在保存时不能切客户或更改范围', async ({ page }) => {
  const data = await fixture(page, { failFirst: true, holdSave: true, manager: true });
  await open(page, 390, 520);
  const notes = page.getByLabel('沟通记录', { exact: true });
  await notes.fill('断网也不能丢的记录');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await page.getByRole('button', { name: '保存并下一位', exact: true }).click();
  await expect(page.getByText('保存失败，记录已保留，请重试', { exact: true })).toBeVisible();
  await expect(notes).toHaveValue('断网也不能丢的记录');
  await page.getByRole('button', { name: '保存并下一位', exact: true }).click();
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '打开客户队列', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '下一位客户', exact: true })).toBeDisabled();
  data.release();
  await expect(page.getByRole('heading', { name: '示例商家乙', exact: true })).toBeVisible();
  expect(data.writes).toHaveLength(2);
  expect(data.writes[0].body).toEqual(data.writes[1].body);
});

test('历史日期与主管销售范围清晰可改，只读取目标日期且草稿隔离', async ({ page }) => {
  const data = await fixture(page, { manager: true });
  await open(page, 390);
  await page.getByLabel('沟通记录', { exact: true }).fill('今天销售甲的草稿');
  await page.getByRole('button', { name: '调整任务范围', exact: true }).click();
  const scope = page.getByRole('dialog', { name: '任务范围', exact: true });
  await scope.getByLabel('任务日期（北京时间）', { exact: true }).fill('2026-09-01');
  await scope.getByRole('combobox', { name: '当前销售', exact: true }).selectOption('28');
  await scope.getByRole('button', { name: '返回工作台', exact: true }).click();
  await expect(page.getByRole('heading', { name: '拨打记录', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText('2026-09-01');
  await expect(page.getByRole('button', { name: '调整任务范围', exact: true })).toContainText('模拟销售乙');
  await expect(page.getByLabel('沟通记录', { exact: true })).toHaveValue('');
  await expect.poll(() => data.reads.some(path => path.includes('target_date=2026-09-01') && path.includes('sales_employee_id=28'))).toBe(true);
  expect(data.writes).toEqual([]);
});

test('禁止联系仍禁拨和禁保存，历史证据可看且销售不能切别人范围', async ({ page }) => {
  const data = await fixture(page, { protected: true });
  await open(page, 390);
  await expect(page.getByLabel('沟通记录', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '拨打电话', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '保存并下一位', exact: true })).toBeDisabled();
  await expect(page.getByLabel('最近联系', { exact: true })).toContainText('上次午间未接通');
  await page.getByRole('button', { name: '更多客户操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '历史联系', exact: true }).click();
  await expect(page.getByRole('dialog').getByText('上次午间未接通，晚些时候联系', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '调整任务范围', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '任务范围', exact: true }).getByRole('combobox', { name: '当前销售', exact: true })).toHaveCount(0);
  expect(data.writes).toEqual([]);
});

for (const kind of ['empty', 'failRead'] as const) {
  test(`手机${kind === 'empty' ? '无任务' : '读取失败'}有明确恢复入口且不自动生成任务`, async ({ page }) => {
    const data = await fixture(page, { [kind]: true });
    await page.setViewportSize({ width: 320, height: 520 });
    await page.goto(`${base}/sales-workbench?sales_employee_id=27`);
    if (kind === 'empty') await expect(page.getByRole('heading', { name: '当前队列暂无任务', exact: true })).toBeVisible();
    else await expect(page.getByRole('button', { name: '重新加载', exact: true })).toBeVisible();
    await geometry(page);
    expect(data.writes).toEqual([]);
  });
}

test('1440桌面保持双栏和可见日期/销售工具，768窄桌面保留原生选择', async ({ page }) => {
  const data = await fixture(page, { manager: true });
  await open(page, 1440, 900);
  await expect(page.getByRole('complementary', { name: '今日客户队列', exact: true })).toBeVisible();
  await expect(page.getByLabel('任务日期（北京时间）', { exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole('combobox', { name: '当前销售', exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole('button', { name: '打开客户队列', exact: true })).toHaveCount(0);
  await geometry(page);
  if (screenshots) await page.screenshot({ path: `${screenshots}/desktop-workbench-1440.png` });
  await page.setViewportSize({ width: 768, height: 1024 });
  await expect(page.getByRole('combobox', { name: '选择客户', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: '选择客户', exact: true }).selectOption('922');
  await expect(page.getByRole('heading', { name: '示例商家 22', exact: true })).toBeVisible();
  expect(data.writes).toEqual([]);
});
