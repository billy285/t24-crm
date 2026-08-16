import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const designer = {
  id: 20,
  name: 'Designer A',
  role: 'design',
  status: 'active',
  department: 'Design',
};
const financeEmployee = {
  id: 30,
  name: 'Finance A',
  role: 'finance',
  status: 'active',
  department: 'Finance',
};

async function fulfillJson(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
}

async function mockDesignerTaskApi(page: Page, requests: string[]) {
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'task-scope-token');
    window.localStorage.setItem('token', 'task-scope-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: designer });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    requests.push(path);

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, designer);
    if (path === '/api/v1/app-config') return fulfillJson(route, {
      items: {
        role_permissions: {
          key: 'role_permissions',
          value: {
            design: {
              pages: ['/', '/tasks'],
              buttons: ['task_edit'],
              dataScope: 'self',
              sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: false },
            },
          },
        },
      },
    });
    if (path === '/api/v1/entities/tasks') return fulfillJson(route, {
      items: [{
        id: 104,
        title: 'Designer visible task',
        assignee_id: designer.id,
        assignee_name: designer.name,
        customer_id: 9,
        customer_name: 'Scoped customer label',
        status: 'pending',
        priority: 'medium',
        task_type: 'design',
      }],
      total: 1,
      skip: 0,
      limit: 1000,
    });
    if (path.includes('/entities/customers') || path.includes('/entities/employees')) {
      return fulfillJson(route, { detail: 'sensitive collection must not be requested' }, 500);
    }
    if (path.endsWith('/entities/tasks/assignee-options')) {
      return fulfillJson(route, { detail: 'self-scope form does not need assignee options' }, 500);
    }
    return fulfillJson(route, {});
  });
}

test('self 范围 direct URL 不扩大视图且不下载客户或员工全量', async ({ page }) => {
  const requests: string[] = [];
  await mockDesignerTaskApi(page, requests);
  await page.setViewportSize({ width: 1280, height: 800 });

  await page.goto(`${baseUrl}/tasks?task_id=999&view=all`);

  await expect(page.getByText('Designer visible task')).toBeVisible();
  await expect(page.getByRole('button', { name: /全部任务/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /团队待办/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '新建任务' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '删除任务' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '编辑任务' })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get('view')).not.toBe('all');

  expect(requests.filter(path => path.includes('/entities/customers'))).toEqual([]);
  expect(requests.filter(path => path.includes('/entities/employees'))).toEqual([]);
  expect(requests.filter(path => path.endsWith('/entities/tasks/999'))).toEqual([]);

  await page.getByRole('button', { name: '编辑任务' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '编辑任务' })).toBeVisible();
  await expect(dialog.getByLabel('当前关联客户')).toHaveValue('Scoped customer label');
  await expect(dialog.getByText('仅自己范围的账号不能变更任务归属。')).toBeVisible();

  expect(requests.filter(path => path.includes('/entities/customers'))).toEqual([]);
  expect(requests.filter(path => path.includes('/entities/employees'))).toEqual([]);
  expect(requests.filter(path => path.endsWith('/entities/tasks/assignee-options'))).toEqual([]);
  expect(requests.filter(path => path === '/api/v1/entities/tasks')).toHaveLength(1);
});

test('无任务权限的财务仪表盘不请求任务且其他财务数据正常显示', async ({ page }) => {
  const requests: string[] = [];
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'finance-dashboard-token');
    window.localStorage.setItem('token', 'finance-dashboard-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: financeEmployee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    requests.push(path);

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, financeEmployee);
    if (path === '/api/v1/app-config') return fulfillJson(route, {
      items: {
        role_permissions: {
          key: 'role_permissions',
          value: {
            finance: {
              pages: ['/', '/finance', '/customers', '/settings/deduction'],
              buttons: ['payment_create', 'payment_edit', 'customer_export'],
              dataScope: 'all',
              sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: true },
            },
          },
        },
      },
    });
    if (path === '/api/v1/entities/tasks') {
      return fulfillJson(route, { detail: 'finance must not request tasks' }, 500);
    }
    if (path.includes('/entities/customers')) return fulfillJson(route, {
      items: [{
        id: 1,
        business_name: '财务测试客户',
        status: 'closed',
        created_at: now.toISOString(),
      }],
      total: 1,
    });
    if (path.includes('/entities/subscriptions')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/payments')) return fulfillJson(route, {
      items: [{
        id: 1,
        customer_id: 1,
        product_name: '基础套餐',
        amount_paid: 321,
        outstanding_amount: 0,
        payment_date: now.toISOString(),
      }],
      total: 1,
    });
    if (path.includes('/entities/company_expenses')) return fulfillJson(route, {
      items: [{ id: 1, expense_month: currentMonth, amount: 1000 }],
      total: 1,
    });
    if (path.includes('/entities/expenses')) return fulfillJson(route, {
      items: [{ id: 1, expense_month: currentMonth, amount: 20 }],
      total: 1,
    });
    if (path === '/api/v1/payroll/summary') return fulfillJson(route, { items: [], pending_count: 0 });
    return fulfillJson(route, {});
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${baseUrl}/`);

  await expect(page.getByRole('heading', { name: '财务工作台' })).toBeVisible();
  await expect(page.getByText('本月收款')).toBeVisible();
  await expect(page.getByText('$321', { exact: true })).toBeVisible();
  await expect.poll(() => requests.filter(path => path === '/api/v1/entities/tasks').length).toBe(0);
  expect(requests.some(path => path.includes('/entities/customers'))).toBe(true);
  expect(requests.some(path => path.includes('/entities/payments'))).toBe(true);
});
