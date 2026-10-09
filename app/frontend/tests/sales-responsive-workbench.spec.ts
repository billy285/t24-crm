import { expect, test, type Locator, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshotDir = process.env.T24_UI_SCREENSHOT_DIR;
const employee = { id: 27, name: '响应式销售主管', role: 'sales_manager', status: 'active' };
const longName = '纽约国际餐饮集团皇后区预约体验中心 · InternationalRestaurantAndHospitalityManagementCompanyWithAReallyLongName';
const nextName = '下一位商家 · Pacific Kitchen Downtown';
const viewports = [
  { width: 1024, height: 600 },
  { width: 1093, height: 824 },
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];

async function mockWorkbench(page: Page) {
  const writes: { path: string; data: Record<string, unknown> | null }[] = [];
  const rejected: string[] = [];
  const completed = new Set<number>();
  const records = Array.from({ length: 20 }, (_, index) => ({
    task_id: 901 + index,
    task_status: 'pending',
    priority: 'normal',
    queue_category: 'new',
    next_action_label: '确认预约需求并约定下一次沟通',
    lead: {
      id: 501 + index,
      business_name: index === 0 ? longName : index === 1 ? nextName : `响应式商家 ${index + 1}`,
      contact_name: '商家负责人',
      phone: '+1 (212) 555-0126',
      country: 'US',
      industry: '餐饮',
      city: 'New York',
      state: 'NY',
      status: 'new',
      do_not_contact: false,
      is_blacklisted: false,
    },
  }));
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'responsive-workbench-local-token');
    localStorage.setItem('token', 'responsive-workbench-local-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let status = 200;
    let data: unknown = { items: [], total: 0 };
    if (!['GET', 'HEAD'].includes(request.method())) {
      const payload = request.postData() ? request.postDataJSON() : null;
      writes.push({ path, data: payload });
      if (request.method() === 'POST' && path === '/api/v1/sales-leads/workbench/tasks/901/result') {
        completed.add(901);
        data = { message: '通话结果已记录，今日任务进度已更新' };
      } else {
        rejected.push(path);
        status = 409;
        data = { detail: '响应式测试不允许该业务写入' };
      }
    } else if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/sales-leads/assignees')) data = [{ id: employee.id, name: employee.name }];
    else if (path.endsWith('/sales-leads/workbench/today')) data = {
      salesperson: { id: employee.id, name: employee.name }, quota: 20, assigned_count: 20,
      completed_count: completed.size, remaining_count: 20 - completed.size, is_target_complete: false,
      categories: { unfinished: 20 - completed.size, callback: 0, interested: 0, appointment: 0, new: 20, retry: 0, recycled: 0, follow_up: 0 },
      performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 },
      items: records.map(record => ({ ...record, task_status: completed.has(record.task_id) ? 'completed' : 'pending' })),
    };
    else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false, realtime_sync_enabled: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = { available: false, sync_status: 'waiting' };
    else if (path.endsWith('/call-history')) data = [];
    else if (path.endsWith('/sales-knowledge/articles')) data = { items: [], categories: [] };
    else if (path.endsWith('/sales-leads/automation/overview')) data = {};
    else if (path.includes('/app-config')) data = { items: {} };
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return { writes, rejected };
}

async function expectNoHorizontalOverflow(page: Page, surface: Locator) {
  const size = await surface.evaluate(element => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    surfaceClient: element.clientWidth,
    surfaceScroll: element.scrollWidth,
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: innerHeight,
  }));
  expect(size.document, '文档不能产生横向滚动').toBeLessThanOrEqual(size.viewport + 1);
  expect(size.body, 'body不能产生横向滚动').toBeLessThanOrEqual(size.viewport + 1);
  expect(size.surfaceScroll, '隐藏溢出不能掩盖工作台内部布局挤出').toBeLessThanOrEqual(size.surfaceClient + 1);
  expect(size.documentHeight, '工作区滚动应留在main，不能产生外层空白滚动').toBeLessThanOrEqual(size.viewportHeight + 1);
}

async function expectReachable(control: Locator) {
  // Standard nearest-edge scrolling honors the page's scroll margins. Keep the
  // hit check so a sticky header/footer cannot hide a merely "visible" field.
  await control.evaluate(element => element.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' }));
  await expect(control).toBeInViewport({ ratio: 1 });
  await expect.poll(() => control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (target && (target === element || element.contains(target))) return 'reachable';
    return JSON.stringify({
      control: element.getAttribute('aria-label') || element.textContent?.trim().slice(0, 60) || element.id,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      blocker: target ? `${target.tagName}.${target.className} ${target.textContent?.trim().slice(0, 90)}` : 'none',
    });
  }), { message: '操作中心点不能被固定导航或其他控件遮挡', timeout: 2000, intervals: [50, 100, 250] }).toBe('reachable');
}

async function runLayout(page: Page, viewport: { width: number; height: number }, expanded = false, suffix = '') {
  await page.setViewportSize(viewport);
  const fixture = await mockWorkbench(page);
  await page.goto(`${baseUrl}/sales-workbench?sales_employee_id=${employee.id}`);
  const surface = page.getByTestId(viewport.width < 768 ? 'sales-workbench-mobile' : 'sales-workbench-desktop');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toBeVisible();
  const initialMainWidth = (await page.locator('main').boundingBox())?.width || 0;
  if (expanded) {
    await page.getByRole('button', { name: '展开功能导航', exact: true }).click();
    await expect(page.getByRole('button', { name: '收起功能导航', exact: true })).toBeVisible();
    expect((await page.locator('main').boundingBox())?.width || 0, '窄桌面浮层导航不能挤压主工作区').toBeGreaterThanOrEqual(initialMainWidth - 1);
  }
  await page.locator('main').evaluate(element => { element.scrollTop = 0; });
  const title = surface.getByRole('heading', { name: '今日拨打', exact: true });
  const date = surface.getByLabel('任务日期（北京时间）', { exact: true });
  const salesperson = surface.getByRole('combobox', { name: '当前销售', exact: true });
  for (const control of [title, date, salesperson, surface.getByRole('button', { name: '更多工作台功能', exact: true })]) {
    await expect(control, '起始工具栏必须完整可见').toBeInViewport({ ratio: 1 });
  }
  await expectNoHorizontalOverflow(page, surface);
  const notes = surface.getByLabel('沟通记录', { exact: true });
  const noteSize = await notes.boundingBox();
  const minimum = viewport.width < 768 ? 280 : viewport.width < 900 ? 360 : 400;
  expect(noteSize?.width || 0, '主沟通输入必须保有可读写宽度').toBeGreaterThanOrEqual(minimum);
  await expect(surface.getByRole('heading', { name: longName, exact: true })).toBeVisible();
  const longHeading = await surface.getByRole('heading', { name: longName, exact: true }).boundingBox();
  expect(longHeading?.x || 0).toBeGreaterThanOrEqual(0);
  expect((longHeading?.x || 0) + (longHeading?.width || 0)).toBeLessThanOrEqual(viewport.width + 1);
  const phone = surface.locator('.sw-phone strong');
  await expect(phone).toHaveText('+1 (212) 555-0126');
  expect((await phone.boundingBox())?.height || 0, '标准主号不能被旧客户卡片列宽挤成多行').toBeLessThanOrEqual(32);
  if (screenshotDir) {
    await page.locator('main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `${screenshotDir}/workbench-${viewport.width}x${viewport.height}${expanded ? '-expanded' : ''}${suffix}.png` });
  }
  if (expanded) {
    // The modal navigation intentionally protects the covered workspace. Close
    // it before asserting the call/record actions, as a real user would do.
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: '展开功能导航', exact: true })).toBeVisible();
  }
  const picker = surface.getByRole('combobox', { name: '选择客户', exact: true });
  if (await picker.isVisible()) await expect(picker.locator('option:not([disabled])')).toHaveCount(20);
  else await expect(surface.getByRole('complementary', { name: '今日客户队列', exact: true })).toBeVisible();

  const next = surface.getByRole('button', { name: '下一位客户', exact: true });
  const previous = surface.getByRole('button', { name: '上一位客户', exact: true });
  await expectReachable(next);
  await next.click();
  await expect(surface.getByRole('heading', { name: nextName, exact: true })).toBeVisible();
  await expectReachable(previous);
  await previous.click();
  await expect(surface.getByRole('heading', { name: longName, exact: true })).toBeVisible();
  expect(fixture.writes).toHaveLength(0);

  await expectReachable(notes);
  await notes.fill('商家希望接入官网预约，周一与负责人确认预算和执行计划');
  await surface.getByRole('button', { name: '有意向', exact: true }).click();
  await surface.getByLabel(/^下次跟进/).fill('2026-10-12T10:30');
  await surface.locator('summary').filter({ hasText: /^更多信息$/ }).click();
  const need = surface.getByLabel('真实需求', { exact: true });
  await expectReachable(need);
  await need.fill('可查看所有门店时段、预约到店服务与活动优惠');
  const save = surface.getByRole('button', { name: '保存并下一位', exact: true });
  await expectReachable(save);
  await expectNoHorizontalOverflow(page, surface);
  await save.click();
  await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '1');
  await expect(surface.getByRole('heading', { name: nextName, exact: true })).toBeVisible();
  await expect(notes).toHaveValue('');
  expect(fixture.writes).toHaveLength(1);
  expect(fixture.writes[0]).toMatchObject({ path: '/api/v1/sales-leads/workbench/tasks/901/result', data: { outcome: 'interested', notes: '商家希望接入官网预约，周一与负责人确认预算和执行计划', next_follow_up_at: '2026-10-12T02:30:00.000Z', contact_details: { need_summary: '可查看所有门店时段、预约到店服务与活动优惠' } } });
  expect(fixture.rejected).toHaveLength(0);
  // The successful save was already verified. Let its transient notification
  // finish before testing the next record's scroll geometry. A pointer left on
  // the just-clicked save button may now hover the toast and pause its timer.
  await page.mouse.move(0, 0);
  await expect(page.getByText('通话结果已记录，今日任务进度已更新', { exact: true })).toBeHidden({ timeout: 6000 });
  await surface.getByRole('button', { name: '待回访', exact: true }).click();
  await expectReachable(surface.getByLabel(/^下次跟进/));
  await expectReachable(save);
  await expectNoHorizontalOverflow(page, surface);
}

for (const viewport of viewports) {
  test(`工作台在 ${viewport.width}x${viewport.height} 保持可写、可切换与完整滚动流程`, async ({ page }) => {
    await runLayout(page, viewport);
  });
}

test('1093x824 展开功能导航后主记录仍保持合理宽度与操作可达', async ({ page }) => {
  await runLayout(page, { width: 1093, height: 824 }, true);
});

test('1280x720 浏览器200%放大的640x360等效CSS视口仍可完成记录', async ({ page }) => {
  // Browser zoom reduces the available CSS viewport. This exercises reflow at
  // that equivalent size, rather than CSS zoom or deviceScaleFactor pixel density.
  await runLayout(page, { width: 640, height: 360 }, false, '-zoom-equivalent');
});

test('展开导航在窄桌面浮层和宽桌面并排之间切换，搜索Escape与工作区均可恢复', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const fixture = await mockWorkbench(page);
  await page.goto(`${baseUrl}/sales-workbench?sales_employee_id=${employee.id}`);
  const surface = page.getByTestId('sales-workbench-desktop');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toBeVisible();
  const main = page.locator('main');
  const narrowWidth = (await main.boundingBox())?.width || 0;
  await page.getByRole('button', { name: '展开功能导航', exact: true }).click();
  await expect(page.getByRole('button', { name: '收起功能导航', exact: true })).toBeVisible();
  expect((await main.boundingBox())?.width || 0).toBeGreaterThanOrEqual(narrowWidth - 1);
  const search = page.getByRole('textbox', { name: /查找.*功能/ });
  await search.fill('拨打');
  await search.press('Escape');
  await expect(search).toHaveValue('');
  await expect(page.getByRole('button', { name: '收起功能导航', exact: true })).toBeVisible();

  await page.setViewportSize({ width: 1366, height: 768 });
  const sidebar = page.getByRole('complementary', { name: '业务导航', exact: true });
  await expect.poll(async () => (await sidebar.boundingBox())?.width || 0).toBeGreaterThanOrEqual(250);
  expect((await main.boundingBox())?.x || 0).toBeGreaterThanOrEqual(250);
  await expectNoHorizontalOverflow(page, surface);
  await expectReachable(surface.getByRole('button', { name: '下一位客户', exact: true }));
  await surface.getByRole('button', { name: '下一位客户', exact: true }).click();
  await expect(surface.getByRole('heading', { name: nextName, exact: true })).toBeVisible();
  expect((await surface.getByLabel('沟通记录', { exact: true }).boundingBox())?.width || 0).toBeGreaterThanOrEqual(400);

  await page.setViewportSize({ width: 1280, height: 720 });
  await expect.poll(async () => (await sidebar.boundingBox())?.width || 0).toBeLessThanOrEqual(80);
  await expect(page.getByRole('button', { name: '关闭业务导航', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: '展开功能导航', exact: true })).toBeVisible();
  await expectReachable(surface.getByRole('button', { name: '上一位客户', exact: true }));
  await surface.getByRole('button', { name: '上一位客户', exact: true }).click();
  await expect(surface.getByRole('heading', { name: longName, exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page, surface);
  expect(fixture.writes).toHaveLength(0);
});
