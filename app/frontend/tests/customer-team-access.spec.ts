import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const admin = { id: 1, name: 'Team Admin', role: 'admin', status: 'active' };
const customers = [
  { id: 101, customer_code: 'T24-101', business_name: 'Alpha Cafe', contact_name: 'Amy', phone: '555-0101', status: 'following', level: 'normal', industry: 'restaurant', state: 'CA', sales_person: 'Sales Owner', sales_employee_id: 31 },
  { id: 102, customer_code: 'T24-102', business_name: 'Beta Spa', contact_name: 'Beth', phone: '555-0102', status: 'following', level: 'normal', industry: 'spa', state: 'NV', sales_person: 'Sales Owner', sales_employee_id: 31 },
];
const employees = [
  { id: 31, name: 'Sales Owner', employee_code: 'S031', role: 'sales', department: 'Sales', status: 'active' },
  { id: 41, name: 'Operations Member', employee_code: 'O041', role: 'ops', department: 'Operations', status: 'active' },
];

async function json(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function mockCustomerTeamApis(page: Page, bulkPayloads: unknown[]) {
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'customer-team-token');
    window.localStorage.setItem('token', 'customer-team-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: admin });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return json(route, admin);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path === '/api/v1/entities/employees/directory') return json(route, { items: employees, total: employees.length });
    if (path === '/api/v1/entities/customers/access/bulk-update') {
      bulkPayloads.push(route.request().postDataJSON());
      return json(route, { customer_count: 2, member_count: 1, updated_grants: 2 });
    }
    if (path === '/api/v1/entities/customers/101/access') return json(route, {
      customer_id: 101,
      members: [{ ...employees[1], employee_id: 41, access_level: 'read_only' }],
    });
    if (path === '/api/v1/entities/customers' || path === '/api/v1/entities/customers/all') return json(route, { items: customers, total: customers.length });
    if (path.includes('/product-plans')) return json(route, { business_lines: [], products: [], plans: [] });
    if (path.includes('/entities/')) return json(route, { items: [], total: 0 });
    return json(route, {});
  });
}

test('管理员可为多位客户批量添加团队成员并逐人设置只读或读写', async ({ page }) => {
  const bulkPayloads: unknown[] = [];
  await mockCustomerTeamApis(page, bulkPayloads);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/customers`);

  await expect(page.getByRole('heading', { name: '客户管理' })).toBeVisible();
  await page.getByRole('checkbox', { name: '选择客户 Alpha Cafe' }).check();
  await page.getByRole('checkbox', { name: '选择客户 Beta Spa' }).check();
  await expect(page.getByText('已选择 2 位客户')).toBeVisible();
  await page.getByRole('button', { name: '批量管理团队成员' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '批量管理 2 位客户的团队成员' })).toBeVisible();
  await dialog.getByRole('button', { name: /Operations Member/ }).click();
  await dialog.locator('select').selectOption('read_only');
  await dialog.getByRole('button', { name: '批量添加 / 更新' }).click();

  expect(bulkPayloads).toEqual([{
    customer_ids: [101, 102],
    operation: 'upsert',
    members: [{ employee_id: 41, access_level: 'read_only' }],
  }]);
  await expect(page.getByText('已为 2 位客户更新团队成员')).toBeVisible();
});
