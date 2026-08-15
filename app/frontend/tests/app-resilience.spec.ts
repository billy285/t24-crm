import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '恢复测试管理员', role: 'super_admin', status: 'active' };

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedAdmin(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'resilience-token');
    window.localStorage.setItem('token', 'resilience-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/app-config')) return fulfillJson(route, { items: {} });
    if (path.endsWith('/company-roadmap/overview')) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'simulated upstream outage' }) });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, {});
  });
}

test('懒加载页面文件暂时失败时显示恢复页而不是白屏，并可重新加载', async ({ page }) => {
  await seedAdmin(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const roadmapChunk = /\/(?:src\/pages\/CompanyRoadmap\.tsx|assets\/CompanyRoadmap-[^/]+\.js)(?:\?|$)/;
  await page.route(roadmapChunk, route => route.fulfill({ status: 404, contentType: 'text/plain', body: 'simulated stale chunk' }));

  await page.goto(`${baseUrl}/company-roadmap`);
  await expect(page.getByRole('heading', { name: '当前页面没有正常加载' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('button', { name: '重新加载系统' })).toBeVisible();
  await expect(page.locator('body')).not.toHaveText(/^\s*$/);

  await page.unroute(roadmapChunk);
  await Promise.all([
    page.waitForEvent('load'),
    page.getByRole('button', { name: '重新加载系统' }).click(),
  ]);
  await expect(page.getByRole('heading', { name: '当前页面没有正常加载' })).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByText('公司战略数据暂时无法读取。')).toBeVisible();
});
