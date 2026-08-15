import { expect, test } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';

test('operation log helper downgrades client business events to attributed user notes', async ({ page }) => {
  const employee = { id: 63, name: 'Audit Test Admin', role: 'admin', status: 'active' };
  const capturedPayloads: Record<string, unknown>[] = [];
  await page.addInitScript(({ emp }) => {
    window.sessionStorage.setItem('emp_auth_token', 'audit-test-token');
    window.sessionStorage.setItem('token', 'audit-test-token');
    window.sessionStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/entities/operation_logs') {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      capturedPayloads.push(payload);
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: capturedPayloads.length, ...payload }),
      });
    }
    if (path.endsWith('/emp-auth/me')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(employee) });
    }
    if (path.includes('/app-config')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: {} }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) });
  });

  await page.goto(`${baseUrl}/customers`);
  await expect(page.getByRole('heading', { name: '客户管理' })).toBeVisible();
  await page.evaluate(async () => {
    const helperPath = performance.getEntriesByType('resource')
      .map(entry => entry.name)
      .find(url => /(?:\/src\/lib\/operation-log-helper\.ts|\/assets\/operation-log-helper-[^/]+\.js)(?:\?|$)/.test(url));
    if (!helperPath) throw new Error('Operation log helper module was not loaded');
    const helperModule = await import(/* @vite-ignore */ helperPath);
    const logOperation = helperModule.logOperation
      || Object.values(helperModule).find(value => typeof value === 'function');
    if (typeof logOperation !== 'function') throw new Error('Operation log helper export was not found');
    await logOperation({
      customerId: 701,
      actionType: 'edit_customer',
      actionDetail: 'safe business detail',
      operatorName: 'Browser Forged Operator',
    });
    await logOperation({
      actionType: 'close_finance_month',
      actionDetail: '2026-08',
      operatorName: 'Browser Forged Operator',
    });
  });

  expect(capturedPayloads).toEqual([
    {
      customer_id: 701,
      action_type: 'user_note',
      action_detail: '用户备注（非系统审计）｜关联操作：编辑客户｜safe business detail',
    },
    {
      customer_id: null,
      action_type: 'user_note',
      action_detail: '用户备注（非系统审计）｜关联操作：月度关账｜2026-08',
    },
  ]);
});

test('explicit password-view revocation removes the eye even when legacy security config allows admin', async ({ page }) => {
  const employee = { id: 64, name: 'Revoked Admin', role: 'admin', status: 'active' };
  const customer = {
    id: 901,
    customer_code: 'AUDIT-901',
    business_name: 'Revocation Customer',
    contact_name: 'Owner',
    phone: '555-0901',
    status: 'closed',
    level: 'normal',
    industry: 'restaurant',
    country: 'US',
    state: 'CA',
    city: 'Los Angeles',
  };
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'revoked-admin-token');
    window.localStorage.setItem('token', 'revoked-admin-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
    window.localStorage.setItem('crm_role_permissions', JSON.stringify({
      admin: { sensitiveFields: { viewPassword: false } },
    }));
    window.localStorage.setItem('crm_security_config', JSON.stringify({
      passwordViewRoles: ['admin', 'super_admin'],
    }));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = { items: [] };
    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/app-config')) data = { items: {} };
    else if (path.includes('/entities/media_accounts')) data = {
      items: [{
        id: 501,
        customer_id: 901,
        platform_name: 'Facebook',
        account_name: 'revoked-account',
        has_password: true,
        account_status: 'active',
      }],
    };
    else if (path.endsWith('/entities/customers/901/projects')) data = { items: [] };
    else if (path.includes('/entities/customers')) data = { items: [customer] };
    else if (path.includes('/customer-lifecycle/customers/901')) data = { cycles: [], events: [] };
    else if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });
  });

  await page.goto(`${baseUrl}/customers?detail=901&tab=media`);
  await expect(page.getByText('@revoked-account')).toBeVisible();
  await expect(page.getByText('密码: ••••••••')).toBeVisible();
  await expect(page.getByRole('button', { name: '查看revoked-account的密码' })).toHaveCount(0);
});
