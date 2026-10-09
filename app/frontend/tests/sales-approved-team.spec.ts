import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshots = process.env.T24_UI_SCREENSHOT_DIR;
const employees = [{ id: 11, name: '示例销售甲' }, { id: 12, name: '示例销售乙' }];
const businessDate = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

async function mockTeam(page: Page, options: { role?: string; failedEmployee?: number; providerStatus?: string; wrongProviderDate?: boolean } = {}) {
  const user = { id: options.role === 'sales' ? 11 : 1, name: options.role === 'sales' ? '示例销售甲' : '示例主管', role: options.role || 'sales_manager', status: 'active' };
  const reads: string[] = [];
  const writes: string[] = [];
  let failedEmployee = options.failedEmployee;
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'approved-team-local-token');
    localStorage.setItem('token', 'approved-team-local-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, user);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (!['GET', 'HEAD'].includes(request.method())) {
      writes.push(path);
      return route.fulfill({ status: 409, json: { detail: '团队布局测试不允许业务写入' } });
    }
    reads.push(url.pathname + url.search);
    let data: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = user;
    else if (path.endsWith('/sales-leads/assignees')) data = employees;
    else if (path.endsWith('/sales-leads/workbench/today')) {
      const id = Number(url.searchParams.get('sales_employee_id') || 11);
      if (id === failedEmployee) return route.fulfill({ status: 503, json: { detail: '该销售任务读取失败' } });
      const employee = employees.find(value => value.id === id)!;
      const completed = id === 11 ? 4 : 7;
      const assigned = id === 11 ? 6 : 10;
      data = {
        target_date: url.searchParams.get('target_date'), salesperson: employee,
        quota: id === 11 ? 20 : 25, completed_count: id === 11 ? 4 : 7, remaining_count: id === 11 ? 2 : 3,
        assigned_count: id === 11 ? 6 : 10, is_target_complete: false,
        categories: { unfinished: 2, callback: 0, interested: 0, appointment: 0, new: 2 },
        // This deliberately differs from the complete provider report. It must not be used as its substitute.
        performance: { attempted: 100, connected: 99, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 99 },
        items: Array.from({ length: assigned }, (_, index) => ({ task_id: id * 100 + index, task_status: index < completed ? 'completed' : 'pending', priority: 'normal', queue_category: 'follow_up', lead: {
          id: id * 10 + index, business_name: index === completed ? `${employee.name}的示例商家` : `${employee.name}商家${index + 1}`, phone: '+1 415 555 2671', country: 'US', industry: '餐饮', city: 'San Francisco', state: 'CA',
          status: 'interested', next_follow_up_at: `${businessDate()}T07:30:00Z`, do_not_contact: false, is_blacklisted: false,
        } })),
      };
    } else if (path.endsWith('/sales-leads/dashboard/management')) data = { target_date: url.searchParams.get('target_date'), owner_attention: { overdue_followups: 8, high_intent_stale: 5 } };
    else if (path.endsWith('/merchant-pool/stats')) data = { pending: 24 };
    else if (path.endsWith('/sales-leads/dashboard/call-report')) data = {
      period: { start_date: options.wrongProviderDate ? '2000-01-01' : businessDate(), end_date: businessDate() },
      source: { status: options.providerStatus || 'verified' }, summary: { connected: 3 },
    };
    else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false, realtime_sync_enabled: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = { available: false, sync_status: 'waiting' };
    else if (path.endsWith('/call-history')) data = [{ id: 1, outcome: 'interested', outcome_label: '有意向', called_at: `${businessDate()}T00:30:00Z`, notes: '希望了解服务套餐，约定下午继续沟通' }];
    else if (path.includes('/app-config')) data = { items: {} };
    await route.fulfill({ json: data });
  });
  return { reads, writes, recover: () => { failedEmployee = undefined; } };
}

function metric(page: Page, name: string) {
  return page.getByRole('region', { name: '团队任务概况' }).locator('div').filter({ has: page.getByText(name, { exact: true }) }).locator('strong');
}

for (const role of ['sales_manager', 'admin']) {
  test(`${role} 默认团队层级读取真实字段，打开销售任务不生成任务`, async ({ page }) => {
    const fixture = await mockTeam(page, { role });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${base}/sales-workbench`);
    await expect(page.getByRole('heading', { name: '团队今日任务', exact: true })).toBeVisible();
    await expect(metric(page, '今日已记录')).toHaveText('11');
    await expect(metric(page, '官方接通')).toHaveText('3');
    await expect(metric(page, '逾期回访')).toHaveText('8');
    const row = page.getByRole('row').filter({ hasText: '示例销售甲' });
    await expect(row.getByRole('cell').nth(1)).toHaveText('20');
    await expect(row.getByRole('cell').nth(2)).toHaveText('4');
    await expect(row.getByRole('cell').nth(3)).toHaveText('2');
    expect(fixture.writes).toEqual([]);
    if (screenshots && role === 'sales_manager') await page.screenshot({ path: `${screenshots}/05-team-today-local-1440.png` });
    await page.getByRole('button', { name: '查看任务：示例销售甲', exact: true }).click();
    await expect(page.getByRole('heading', { name: '今日拨打', exact: true })).toBeVisible();
    await expect(page.getByLabel('沟通记录', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '示例销售甲的示例商家' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: '主管任务视角' }).getByRole('button', { name: '团队', exact: true })).toBeEnabled();
    expect(fixture.writes).toEqual([]);
    expect(fixture.reads.some(url => url.includes('sales_employee_id=11'))).toBe(true);
    if (screenshots && role === 'sales_manager') await page.screenshot({ path: `${screenshots}/01-today-calls-local-1440.png` });
  });
}

test('单人读取失败不伪装为零或完整团队合计，明确重试后恢复', async ({ page }) => {
  const fixture = await mockTeam(page, { failedEmployee: 12 });
  await page.goto(`${base}/sales-workbench`);
  await expect(metric(page, '今日已记录')).toHaveText('待确认');
  await expect(page.getByRole('alert').filter({ hasText: '部分任务数据暂不可用' })).toBeVisible();
  const failedRow = page.getByRole('row').filter({ hasText: '示例销售乙' });
  await expect(failedRow.getByRole('cell').nth(1)).toHaveText('待确认');
  await expect(failedRow.getByRole('cell').nth(2)).toHaveText('待确认');
  fixture.recover();
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await expect(metric(page, '今日已记录')).toHaveText('11');
  await expect(page.getByRole('alert').filter({ hasText: '部分任务数据暂不可用' })).toHaveCount(0);
  expect(fixture.writes).toEqual([]);
});

for (const option of [{ providerStatus: 'waiting_provider_data' }, { wrongProviderDate: true }]) {
  test(`官方统计未核验或日期不符保持待确认：${JSON.stringify(option)}`, async ({ page }) => {
    const fixture = await mockTeam(page, option);
    await page.goto(`${base}/sales-workbench`);
    await expect(metric(page, '今日已记录')).toHaveText('11');
    await expect(metric(page, '官方接通')).toHaveText('待确认');
    expect(fixture.writes).toEqual([]);
  });
}

test('历史任务不冒用今日官方接通，也不生成历史任务', async ({ page }) => {
  const fixture = await mockTeam(page);
  await page.goto(`${base}/sales-workbench`);
  await expect(metric(page, '官方接通')).toHaveText('3');
  await page.getByLabel('任务日期（北京时间）').fill('2020-03-20');
  await expect(page.getByRole('heading', { name: '团队任务', exact: true })).toBeVisible();
  await expect(metric(page, '当日已记录')).toHaveText('11');
  await expect(metric(page, '官方接通')).toHaveText('待确认');
  expect(fixture.writes).toEqual([]);
});

test('销售默认个人任务，不读取团队管理接口', async ({ page }) => {
  const fixture = await mockTeam(page, { role: 'sales' });
  await page.goto(`${base}/sales-workbench`);
  await expect(page.getByLabel('沟通记录', { exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '主管任务视角' })).toHaveCount(0);
  expect(fixture.reads.some(url => /dashboard\/(?:management|call-report)|merchant-pool\/stats/.test(url))).toBe(false);
  expect(fixture.writes).toEqual([]);
});

test('390px团队界面保持外层无横纵溢出，所有销售任务可触达', async ({ page }) => {
  const fixture = await mockTeam(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/sales-workbench`);
  await expect(metric(page, '今日已记录')).toHaveText('11');
  if (screenshots) await page.screenshot({ path: `${screenshots}/05-team-today-local-390-top.png` });
  const sizes = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight }));
  expect(sizes.scrollWidth).toBeLessThanOrEqual(sizes.width + 1);
  expect(sizes.scrollHeight).toBeLessThanOrEqual(sizes.height + 1);
  const button = page.getByRole('button', { name: '查看任务：示例销售乙', exact: true });
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeInViewport();
  const mobileRow = page.getByRole('listitem').filter({ hasText: '示例销售乙' });
  await expect(mobileRow.getByText('示例销售乙', { exact: true })).toBeInViewport();
  await expect(mobileRow.getByText('25', { exact: true })).toBeVisible();
  await expect(mobileRow.getByText('7', { exact: true })).toBeVisible();
  await expect(mobileRow.getByText('3', { exact: true })).toBeVisible();
  expect(await mobileRow.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
  if (screenshots) await page.screenshot({ path: `${screenshots}/05-team-today-local-390.png` });
  await button.click();
  await expect(page.getByRole('heading', { name: '示例销售乙的示例商家' })).toBeVisible();
  await expect(page.getByLabel('沟通记录', { exact: true })).toBeVisible();
  expect(fixture.writes).toEqual([]);
});

test('销售记录首屏保持拨打次级与明确保存主级，编辑草稿不计入任务', async ({ page }) => {
  const fixture = await mockTeam(page, { role: 'sales' });
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.goto(`${base}/sales-workbench`);
  await page.getByRole('button', { name: '有意向', exact: true }).click();
  await page.getByLabel('沟通记录', { exact: true }).fill('客户希望先了解服务范围，下次沟通确认具体需求。');
  await page.getByLabel(/^下次跟进/).fill(`${businessDate()}T15:30`);
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '4');
  await expect(page.getByRole('button', { name: '保存并下一位', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: '保存并下一位', exact: true })).toBeInViewport();
  await page.getByLabel('沟通记录', { exact: true }).blur();
  expect(fixture.writes).toEqual([]);
  if (screenshots) await page.screenshot({ path: `${screenshots}/01-today-calls-sales-local-1440.png` });
});
