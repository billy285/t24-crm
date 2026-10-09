import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshots = process.env.T24_UI_SCREENSHOT_DIR;
const display = '+1 (773) 743 7663';
const dialUrl = 'https://app.ringcentral.com/r/call?number=17737437663';

async function mockWorkbench(page: Page) {
  const employee = { id: 27, name: '本地电话格式测试', role: 'sales', status: 'active' };
  const writes: { path: string; method: string }[] = [];
  const dialNavigations: string[] = [];
  const record = {
    task_id: 901, task_status: 'pending', priority: 'normal', queue_category: 'new',
    lead: { id: 501, business_name: '未填写国家的历史商家', phone: '773-743-7663', country: null, city: 'Chicago', industry: '餐饮', status: 'new', do_not_contact: false, is_blacklisted: false },
  };
  await page.addInitScript(emp => {
    sessionStorage.setItem('emp_auth_token', 'phone-workbench-local-token');
    sessionStorage.setItem('token', 'phone-workbench-local-token');
    sessionStorage.setItem('emp_auth_data', JSON.stringify(emp));
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      writeText: async (text: string) => { (window as Window & { localPhoneClipboard?: string }).localPhoneClipboard = text; },
    } });
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!['GET', 'HEAD'].includes(request.method())) {
      writes.push({ path, method: request.method() });
      if (request.method() === 'POST' && path === '/api/v1/sales-leads/workbench/tasks/901/dial-started') {
        return route.fulfill({ json: { message: '仅本地拦截拨号启动标记' } });
      }
      return route.fulfill({ status: 409, json: { detail: '电话格式测试禁止业务写入' } });
    }
    let data: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/sales-leads/assignees')) data = [{ id: employee.id, name: employee.name }];
    else if (path.endsWith('/sales-leads/workbench/today')) data = {
      salesperson: { id: employee.id, name: employee.name }, quota: 1, assigned_count: 1,
      completed_count: 0, remaining_count: 1, is_target_complete: false,
      categories: { unfinished: 1, callback: 0, interested: 0, appointment: 0, new: 1, retry: 0, recycled: 0, follow_up: 0 },
      performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items: [record],
    };
    else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = { available: false, sync_status: 'waiting' };
    else if (path.endsWith('/call-history')) data = [];
    else if (path.endsWith('/dashboard/management')) data = { owner_attention: { overdue_followups: 0, high_intent_stale: 0 } };
    else if (path.endsWith('/dashboard/call-report')) data = { source: { status: 'verified' }, summary: { connected: 0 } };
    else if (path.endsWith('/sales-knowledge/articles')) data = { items: [], categories: [] };
    else if (path.includes('/app-config')) data = { items: {} };
    await route.fulfill({ json: data });
  });
  await page.route('https://app.ringcentral.com/**', route => {
    dialNavigations.push(route.request().url());
    return route.fulfill({ status: 200, contentType: 'text/html', body: '<p>本地拦截页面：没有连接电话服务或拨打电话。</p>' });
  });
  return { writes, dialNavigations };
}

for (const width of [320, 390, 480, 1440]) {
  test(`历史无国家号码展示、复制、拨号完整主号与返回草稿一致（${width}px）`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 1000 });
    const fixture = await mockWorkbench(page);
    await page.goto(`${baseUrl}/sales-workbench`);
    const surface = page.getByTestId(width < 768 ? 'sales-workbench-mobile' : 'sales-workbench-desktop');
    const number = surface.locator('.sw-phone strong');
    await expect(number).toHaveText(display);
    const size = await number.evaluate(element => ({
      width: element.clientWidth, scroll: element.scrollWidth, document: document.documentElement.scrollWidth, viewport: innerWidth,
      lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight), height: element.getBoundingClientRect().height,
    }));
    expect(size.document, '统一电话格式不能造成页面横向溢出').toBeLessThanOrEqual(size.viewport + 1);
    expect(size.scroll, '号码不能被裁剪').toBeLessThanOrEqual(size.width + 1);
    expect(size.height, '美国主号在手机上应保持单行').toBeLessThanOrEqual(size.lineHeight + 1);
    if (screenshots) {
      await page.locator('main').evaluate(element => { element.scrollTop = 0; });
      await page.screenshot({ path: `${screenshots}/local-mock-us-phone-${width}.png`, animations: 'disabled' });
    }
    await surface.getByRole('button', { name: '复制客户号码', exact: true }).click();
    await expect.poll(() => page.evaluate(() => (window as Window & { localPhoneClipboard?: string }).localPhoneClipboard)).toBe(display);
    const notes = surface.getByLabel('沟通记录', { exact: true });
    await notes.fill('拨号前尚未提交的商家沟通草稿');
    await expect(page.getByRole('status').filter({ hasText: '草稿已暂存' })).toBeVisible();
    expect(fixture.writes).toEqual([]);
    await surface.getByRole('button', { name: '拨打电话', exact: true }).click();
    await expect(page).toHaveURL(dialUrl);
    expect(fixture.dialNavigations).toEqual([dialUrl]);
    await expect.poll(() => fixture.writes).toEqual([{ path: '/api/v1/sales-leads/workbench/tasks/901/dial-started', method: 'POST' }]);
    await page.goBack();
    await expect(page).toHaveURL(`${baseUrl}/sales-workbench`);
    await expect(notes).toHaveValue('拨号前尚未提交的商家沟通草稿');
    await expect(number).toHaveText(display);
    await expect(page.getByRole('progressbar', { name: '任务完成进度', exact: true })).toHaveAttribute('aria-valuenow', '0');
    expect(fixture.writes).toEqual([{ path: '/api/v1/sales-leads/workbench/tasks/901/dial-started', method: 'POST' }]);
  });
}
