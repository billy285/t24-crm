import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const owner = { id: 1, name: '安全设置测试老板', role: 'super_admin', status: 'active' };

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedOwner(page: Page, appConfigItems: Record<string, unknown> = {}) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'security-settings-token');
    window.localStorage.setItem('token', 'security-settings-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: owner });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, owner);
    if (path === '/api/v1/admin/settings') return fulfillJson(route, { backend_vars: {}, frontend_vars: {} });
    if (path === '/api/v1/admin/ai-settings') return fulfillJson(route, {
      enabled: false,
      provider: 'openai',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-5.4-mini',
      api_key_set: false,
      api_key_preview: '',
      source: 'default',
      updated_at: null,
    });
    if (path === '/api/v1/app-config') return fulfillJson(route, { items: appConfigItems });
    if (path.includes('/app-config/')) return fulfillJson(route, {});
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, {});
  });
}

test('安全设置只展示真实执行边界并把敏感权限交给唯一配置入口', async ({ page }) => {
  await seedOwner(page);
  await page.goto(`${baseUrl}/settings`);
  await page.getByRole('tab', { name: '安全设置' }).click();

  await expect(page.getByRole('heading', { name: '安全边界与执行状态' })).toBeVisible();
  await expect(page.getByText('强制开启', { exact: true })).toBeVisible();
  await expect(page.getByText('逐页面执行', { exact: true })).toBeVisible();
  await expect(page.getByText('未全局启用', { exact: true })).toBeVisible();
  await expect(page.getByText('删除数据仅标记为已删除，不真正移除')).toHaveCount(0);
  await expect(page.getByRole('switch')).toHaveCount(0);

  await page.getByRole('button', { name: '前往权限管理' }).click();
  await expect(page).toHaveURL(/\/permissions$/);
  await expect(page.getByRole('heading', { name: '权限设置' })).toBeVisible();
  await page.getByRole('tab', { name: '按钮权限' }).click();
  await expect(page.getByRole('tabpanel').getByText('敏感信息', { exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: '敏感信息' }).click();
  await expect(page.getByText('查看媒体账号密码', { exact: true })).toBeVisible();
});

test('工资表等敏感服务端配置不会进入浏览器缓存', async ({ page }) => {
  await seedOwner(page, {
    payroll_sheets_v1: {
      key: 'payroll_sheets_v1',
      value: { secret_marker: 'must-not-reach-local-storage' },
    },
  });
  await page.goto(`${baseUrl}/settings`);
  await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => JSON.stringify(Object.values(window.localStorage)))).not.toContain('must-not-reach-local-storage');
});
