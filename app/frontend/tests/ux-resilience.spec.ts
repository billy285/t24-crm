import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '体验测试管理员', role: 'admin', status: 'active' };

async function seedAuth(page: Page, emp = employee) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'ux-resilience-token');
    window.localStorage.setItem('token', 'ux-resilience-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp });
}

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

function salesWorkbenchPayload() {
  return {
    salesperson: { id: 1, name: '体验测试销售' },
    quota: 100,
    assigned_count: 1,
    completed_count: 0,
    remaining_count: 1,
    is_target_complete: false,
    categories: { unfinished: 1, callback: 0, interested: 0, appointment: 0, new: 1, retry: 0, recycled: 0, follow_up: 0 },
    performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 },
    items: [{ task_id: 1, task_status: 'pending', priority: 'high', lead: { id: 1, business_name: '待联系测试商家', phone: '555-0200', status: 'new', do_not_contact: false, is_blacklisted: false, next_follow_up_at: undefined as string | undefined } }],
  };
}

test('销售任务加载完成前不显示假零值，并使用北京时间业务日', async ({ page }) => {
  await seedAuth(page);
  await page.clock.install({ time: new Date('2026-08-15T16:30:00Z') });
  let requestedDate = '';

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/sales-leads/workbench/today')) {
      requestedDate = url.searchParams.get('target_date') || '';
      await new Promise(resolve => setTimeout(resolve, 900));
      return fulfillJson(route, salesWorkbenchPayload());
    }
    if (path.includes('/sales-leads/assignees')) return fulfillJson(route, [{ id: 1, name: '体验测试销售' }]);
    if (path.includes('/sales-leads/automation/overview')) return fulfillJson(route, null);
    if (path.includes('/ringcentral/status')) return fulfillJson(route, { configured: false, connected: false });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/sales-workbench`);
  await expect(page.getByRole('heading', { name: '销售今日工作台' })).toBeVisible();
  await expect(page.getByText('—/—')).toBeVisible();
  await expect(page.getByText('0/100')).toHaveCount(0);
  await expect(page.getByLabel('任务日期（北京时间）')).toHaveValue('2026-08-16');
  await expect(page.getByText('待联系测试商家')).toBeVisible();
  expect(requestedDate).toBe('2026-08-16');
});

test('390px 客户页首屏保留搜索、新增和客户卡片，批量工具仅在电脑端', async ({ page }) => {
  await seedAuth(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: [{ id: 1, customer_code: 'T24-001', business_name: '首屏测试客户', contact_name: '陈老板', phone: '555-0100', status: 'following', level: 'normal', industry: 'restaurant', state: 'CA', sales_person: '测试销售' }] });
    if (path.includes('/entities/employees')) return fulfillJson(route, { items: [] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/customers`);
  await expect(page.getByPlaceholder('搜索编号、名称、联系人、电话...')).toBeVisible();
  await expect(page.getByRole('button', { name: '管理' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /筛选/ })).toBeVisible();
  await expect(page.getByRole('button', { name: '新增客户' })).toBeVisible();
  await expect(page.getByText('批量导入、敏感数据导出、列设置和快捷编辑请在电脑端处理。')).toBeVisible();
  const customerCardTitle = page.getByRole('button', { name: /首屏测试客户/ }).first();
  await expect(customerCardTitle).toBeVisible();
  const cardBox = await customerCardTitle.boundingBox();
  expect(cardBox?.y || 9999).toBeLessThan(844);

  await expect(page.getByText('客户管理工具')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '列设置' })).toHaveCount(0);
});

test('员工危险操作使用文字菜单和对应确认语义', async ({ page }) => {
  await seedAuth(page);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/employees')) return fulfillJson(route, { items: [{ id: 2, employee_code: 'EMP002', name: '员工操作测试', role: 'sales', department: 'sales', status: 'active', login_username: 'employee-test' }] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/employees`);
  await page.getByRole('button', { name: '更多员工操作：员工操作测试' }).click();
  await expect(page.getByRole('menuitem', { name: '客户交接' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: '停用账号' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: '删除员工' })).toBeVisible();
  await page.getByRole('menuitem', { name: '停用账号' }).click();
  await expect(page.getByRole('alertdialog')).toContainText('停用后该员工将无法登录');
  await expect(page.getByRole('button', { name: '确认停用' })).toBeVisible();
});

test('财务快照与老板驾驶舱使用同一审计收入、成本和利润', async ({ page }) => {
  await seedAuth(page);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/reports/profit-monthly.json')) return fulfillJson(route, [{ revenue_gross: 1000, gross_receipts: 1200, refund_amount: 200, net_receipts: 1000, ads_client_funds: 300, deduction_amount: 100, stripe_platform_fee: 20, channel_commission: 30, cost: 200, profit: 700 }]);
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/finance`);
  await expect(page.getByText('$700')).toHaveCount(2);
  await expect(page.getByText(/月度审计统一口径/)).toHaveCount(4);
  await expect(page.getByText('审计总成本 USD').locator('../..')).toContainText('$200');
  await expect(page.getByText('净实收现金 USD').locator('..')).toContainText('$1,000');
});

test('主管没有可用销售时结束加载并给出明确下一步', async ({ page }) => {
  await seedAuth(page, { id: 9, name: '空名单主管', role: 'sales_manager', status: 'active' });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, { id: 9, name: '空名单主管', role: 'sales_manager', status: 'active' });
    if (path.includes('/sales-leads/assignees')) return fulfillJson(route, []);
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/sales-workbench`);
  await expect(page.getByText('暂无可用销售人员', { exact: true })).toBeVisible();
  await expect(page.getByText('请先在员工管理中新增或启用销售员工。')).toBeVisible();
  await expect(page.getByText('—/—')).toBeVisible();
  await expect(page.getByText('正在加载今日任务')).toHaveCount(0);
});

test('快速切换销售时较慢的旧请求不能覆盖新结果', async ({ page }) => {
  await seedAuth(page);
  const requestedSales: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/sales-leads/assignees')) return fulfillJson(route, [{ id: 1, name: '旧销售' }, { id: 2, name: '新销售' }]);
    if (path.includes('/sales-leads/workbench/today')) {
      const id = url.searchParams.get('sales_employee_id') || '';
      requestedSales.push(id);
      await new Promise(resolve => setTimeout(resolve, id === '1' ? 900 : 50));
      const payload = salesWorkbenchPayload();
      payload.salesperson = { id: Number(id), name: id === '1' ? '旧销售' : '新销售' };
      payload.items[0].task_id = Number(id);
      payload.items[0].lead.id = Number(id);
      payload.items[0].lead.business_name = id === '1' ? '旧请求商家' : '新选择商家';
      return fulfillJson(route, payload);
    }
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/sales-workbench`);
  await expect.poll(() => requestedSales.includes('1')).toBeTruthy();
  await page.locator('select').first().selectOption('2');
  await expect(page.getByText('新选择商家')).toBeVisible();
  await page.waitForTimeout(1000);
  await expect(page.getByText('新选择商家')).toBeVisible();
  await expect(page.getByText('旧请求商家')).toHaveCount(0);
});

test('无时区 UTC 时间按北京时间显示并跨日判断逾期', async ({ page }) => {
  await seedAuth(page);
  await page.clock.install({ time: new Date('2026-08-16T16:30:00Z') });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/sales-leads/assignees')) return fulfillJson(route, [{ id: 1, name: '体验测试销售' }]);
    if (path.includes('/sales-leads/workbench/today')) {
      const payload = salesWorkbenchPayload();
      payload.items[0].lead.next_follow_up_at = '2026-08-16T16:45:00';
      return fulfillJson(route, payload);
    }
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/sales-workbench`);
  await expect(page.getByText('2026-08-17 00:45（北京时间）')).toBeVisible();
  await expect(page.getByText('跟进已逾期')).toHaveCount(0);
});

test('员工首次加载失败不显示零员工或空名单', async ({ page }) => {
  await seedAuth(page);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/employees')) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '暂时不可用' }) });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, { items: [] });
  });

  await page.goto(`${baseUrl}/employees`);
  await expect(page.getByText('员工资料尚未加载')).toBeVisible();
  await expect(page.getByText('暂无员工')).toHaveCount(0);
  await expect(page.getByText('总员工').locator('..')).toContainText('—');
});
