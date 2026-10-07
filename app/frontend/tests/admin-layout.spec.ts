import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const output = process.env.T24_LAYOUT_OUTPUT;
const owner = { id: 1, name: '布局测试管理员', role: 'super_admin', status: 'active' };
const staff = { id: 2, name: '陈安', role: 'ops', status: 'active', department: 'ops', phone: '4155550123', email: 'staff@example.com', employee_code: 'T002', login_username: 'chenan', notes: '负责客户交付与服务回访' };

async function seed(page: Page, writes: string[]) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'admin-layout-test');
    localStorage.setItem('token', 'admin-layout-test');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, owner);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') writes.push(`${request.method()} ${path}`);
    let data: unknown = {};
    if (path.endsWith('/emp-auth/me')) data = owner;
    else if (path === '/api/v1/admin/settings') data = { backend_vars: {}, frontend_vars: {} };
    else if (path === '/api/v1/admin/ai-settings') data = { enabled: false, provider: 'openai', model: 'gpt-5.4-mini', base_url: 'https://api.openai.com/v1', api_key_set: false };
    else if (path === '/api/v1/app-config') data = { items: {} };
    else if (path.includes('/entities/employees')) data = { items: [owner, staff], total: 2 };
    else if (path.includes('/entities/')) data = { items: [], total: 0 };
    else if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
}

test('分类设置导航保持可用，切换角色不会保存权限草稿', async ({ page }) => {
  const writes: string[] = [];
  await seed(page, writes);
  await page.goto(`${baseUrl}/settings`);
  await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible();
  await expect(page.getByRole('tablist', { name: '系统设置分类' })).toBeVisible();
  await page.getByRole('tab', { name: '公司信息', exact: true }).click();
  if (output) await page.screenshot({ path: `${output}/settings-layout.png`, animations: 'disabled' });
  await page.getByRole('tab', { name: '提醒规则', exact: true }).click();
  await expect(page.getByRole('tabpanel')).toContainText('提醒');
  expect(writes).toEqual([]);

  await page.goto(`${baseUrl}/permissions`);
  const role = page.getByLabel('当前配置角色');
  await expect(role).toHaveValue('sales');
  await page.getByRole('tab', { name: '按钮权限' }).click();
  const customerGroup = page.locator('details').filter({ has: page.locator('summary').filter({ hasText: '客户管理' }) });
  await customerGroup.locator('summary').click();
  const create = customerGroup.getByRole('switch', { name: '新增客户', exact: true });
  const original = await create.getAttribute('aria-checked');
  await create.click();
  await expect(page.getByText('有未保存的权限调整')).toBeVisible();
  await role.selectOption('ops');
  await role.selectOption('sales');
  await expect(create).toHaveAttribute('aria-checked', original === 'true' ? 'false' : 'true');
  await expect(page.getByRole('button', { name: '保存权限配置' })).toBeEnabled();
  expect(writes).toEqual([]);
  if (output) await page.screenshot({ path: `${output}/permissions-layout.png`, animations: 'disabled' });
});

test('员工目录与手机概览保持查询操作，不显示账号管理入口', async ({ page }) => {
  const writes: string[] = [];
  await seed(page, writes);
  await page.goto(`${baseUrl}/employees`);
  await expect(page.getByRole('cell', { name: '陈安', exact: true })).toBeVisible();
  if (output) await page.screenshot({ path: `${output}/employees-layout.png`, animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('employee-mobile-cards')).toBeVisible();
  await expect(page.getByRole('button', { name: '添加员工' })).toHaveCount(0);
  const card = page.getByTestId('employee-mobile-cards').locator('article').filter({ hasText: '陈安' });
  await card.getByRole('button', { name: '查看概览' }).click();
  await expect(page.getByText('负责客户交付与服务回访', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /重置密码|办理离职|客户交接/ })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(writes).toEqual([]);
  if (output) await page.screenshot({ path: `${output}/employee-mobile-layout.png`, animations: 'disabled' });
});
