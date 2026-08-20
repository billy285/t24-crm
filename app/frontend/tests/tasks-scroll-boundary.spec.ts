import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 61, name: '滚动边界管理员', role: 'admin', status: 'active' };

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function installTaskMocks(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'tasks-scroll-token');
    window.localStorage.setItem('token', 'tasks-scroll-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  const tasks = Array.from({ length: 20 }, (_, index) => ({
    id: 1000 + index,
    title: `滚动边界任务 ${index + 1}`,
    customer_id: null,
    customer_name: '',
    assignee_id: employee.id,
    assignee_name: employee.name,
    collaborator_names: '',
    task_type: 'other',
    priority: index % 3 === 0 ? 'high' : 'medium',
    status: index % 2 === 0 ? 'pending' : 'completed',
    notes: `任务说明 ${index + 1}`,
    due_date: '2026-08-30',
    created_at: '2026-08-20T08:00:00Z',
    updated_at: '2026-08-20T08:00:00Z',
  }));

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/tasks')) return fulfillJson(route, { items: tasks });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });
}

test('任务列表只在内容区滚动，不会把浏览器页面撑成空白长页', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installTaskMocks(page);
  await page.goto(`${baseUrl}/tasks`);

  await expect(page.getByText('显示 1-20 条 / 共 20 条')).toBeVisible();
  await expect(page.getByRole('button', { name: '编辑任务' })).toHaveCount(20);

  const dimensions = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>('.app-main');
    return {
      documentHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      mainClientHeight: main?.clientHeight || 0,
      mainScrollHeight: main?.scrollHeight || 0,
    };
  });

  expect(dimensions.mainScrollHeight).toBeGreaterThan(dimensions.mainClientHeight);
  expect(dimensions.documentHeight).toBeLessThanOrEqual(dimensions.viewportHeight + 1);

  await page.locator('.app-main').evaluate(element => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(page.getByText('1 / 1 页')).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});
