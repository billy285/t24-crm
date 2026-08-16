import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const opsEmployee = {
  id: 41,
  name: 'Operations A',
  role: 'ops',
  status: 'active',
  department: 'Operations',
};

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function mockOpsApi(page: Page, employeeRequests: string[]) {
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'employee-directory-token');
    window.localStorage.setItem('token', 'employee-directory-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: opsEmployee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, opsEmployee);
    if (path === '/api/v1/app-config') return fulfillJson(route, {
      items: {
        role_permissions: {
          key: 'role_permissions',
          value: {
            ops: {
              pages: ['/customers', '/callbacks', '/service-board', '/tasks'],
              buttons: ['customer_edit', 'task_create', 'task_edit'],
              dataScope: 'all',
              sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: false },
            },
          },
        },
      },
    });
    if (path.includes('/entities/employees')) {
      employeeRequests.push(path);
      if (path !== '/api/v1/entities/employees/directory') {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'non-admin page requested full employee records' }),
        });
      }
      return fulfillJson(route, { items: [opsEmployee], total: 1, skip: 0, limit: 200 });
    }
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    if (path.includes('/product-plans')) return fulfillJson(route, { business_lines: [], products: [], plans: [] });
    return fulfillJson(route, {});
  });
}

test('非管理员业务页面只使用最小员工目录', async ({ page }) => {
  const employeeRequests: string[] = [];
  await mockOpsApi(page, employeeRequests);

  for (const path of ['/customers', '/callbacks', '/service-board']) {
    const previousCount = employeeRequests.length;
    await page.goto(`${baseUrl}${path}`);
    await expect(page.locator('main')).toBeVisible();
    await expect.poll(() => employeeRequests.length).toBeGreaterThan(previousCount);
  }

  expect(employeeRequests.length).toBeGreaterThanOrEqual(3);
  expect(new Set(employeeRequests)).toEqual(new Set(['/api/v1/entities/employees/directory']));
});
