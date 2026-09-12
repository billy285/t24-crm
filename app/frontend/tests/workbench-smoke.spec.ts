import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '测试管理员', role: 'admin', status: 'active' };
const customer = {
  id: 1,
  customer_code: 'T24-001',
  business_name: '测试客户',
  contact_name: '客户老板',
  phone: '555-0100',
  status: 'closed',
  level: 'normal',
  industry: 'restaurant',
  country: 'US',
  state: 'CA',
  city: 'Los Angeles',
  sales_person: '测试销售',
};

async function mockAuthenticatedApi(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'workbench-smoke-token');
    window.localStorage.setItem('token', 'workbench-smoke-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let data: any = {};

    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.includes('/management-decisions/owner-cockpit')) data = {
      as_of: new Date().toISOString(), decision_state: 'healthy', decisions: [], period: { month: '2026-08' },
      finance: { USD: { profit: 1000, service_revenue: 2000, channel_commission: 0, net_receipts: 2000, ads_client_funds: 0 }, currency_policy: '美元与人民币分别核算', company_cost_cny: 0 },
      customers: { active_projects: 1, at_risk_projects: 0, stopped_this_month: 0, business_lines: [] },
      execution: { system_tasks: 0, overdue_tasks: 0, completed_this_month: 0, open_tasks: 0 },
      quality: { open: 0, in_progress: 0, open_task_count: 0 },
      delivery: { overdue_service_tasks: 0, overdue_callbacks: 0, active_service_records: 1, unresolved_service_issues: 0 },
      automation: { last_run: null, schedule: { enabled: true, next_run_at: null } },
    };
    else if (path.includes('/sales-leads/workbench/today')) data = {
      salesperson: { id: 1, name: '测试销售' }, quota: 100, assigned_count: 1, completed_count: 0,
      remaining_count: 1, is_target_complete: false,
      categories: { unfinished: 1, callback: 0, interested: 0, appointment: 0, new: 1, retry: 0, recycled: 0, follow_up: 0 },
      performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 },
      items: [{ task_id: 1, task_status: 'pending', priority: 'high', next_action_label: '完成本次联系并记录结果', lead: { id: 1, business_name: '测试商家线索', phone: '555-0200', status: 'new', next_follow_up_at: '2026-07-01T09:00:00Z', do_not_contact: false, is_blacklisted: false } }],
    };
    else if (path.includes('/sales-leads/automation/overview')) data = {
      counts: { eligible: 10, assigned: 1, protected: 0, cooling: 0, blocked: 0, closed: 0 }, total: 11, reusable: 10,
      active_sales: 1, daily_capacity: 100, estimated_pool_days: 1,
      rules: { unstarted_release_hours: 24, same_sales_no_answer_attempts: 2, no_answer_cooldown_days: 7, soft_reject_cooldown_days: 60, existing_provider_cooldown_days: 90 },
    };
    else if (path.includes('/sales-leads/assignees')) data = [{ id: 1, name: '测试销售' }];
    else if (path.includes('/ringcentral/status')) data = { configured: false, connected: false };
    else if (path.includes('/entities/customers')) data = { items: [customer] };
    else if (path.includes('/customer-lifecycle/customers/1')) data = { cycles: [{ status: 'active' }], events: [] };
    else if (path.includes('/entities/tasks')) data = { items: [{ id: 7, title: '确认本周服务进度', customer_id: 1, customer_name: '测试客户', assignee_name: '测试管理员', status: 'pending', priority: 'high', due_date: new Date().toISOString().slice(0, 10) }] };
    else if (path.includes('/entities/customer_callbacks')) data = { items: [] };
    else if (path.includes('/entities/service_progresses')) data = { items: [] };
    else if (path.includes('/app-config')) data = { items: [] };
    else if (path.includes('/entities/')) data = { items: [] };

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
}

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedApi(page);
});

test('老板、销售、运营工作台保持角色化入口', async ({ page }) => {
  await page.goto(`${baseUrl}/`);
  await expect(page.getByText('今天先看结果，再看风险，最后确认谁来处理')).toBeVisible();

  await page.goto(`${baseUrl}/sales-workbench`);
  await expect(page.getByRole('heading', { name: '销售今日工作台' })).toBeVisible();
  await expect(page.getByText('测试商家线索')).toBeVisible();
  await expect(page.getByRole('button', { name: '逾期跟进 (1)' })).toBeVisible();
  await expect(page.getByRole('button', { name: '返回今日工作台' })).toBeVisible();
  await expect(page.getByText('拨号辅助、线索循环与个人复盘')).toBeVisible();

  await page.goto(`${baseUrl}/operations-workbench`);
  await expect(page.getByRole('heading', { name: '运营今日工作台' })).toBeVisible();
  await expect(page.getByText('确认本周服务进度')).toBeVisible();
  await expect(page.getByRole('button', { name: '完成任务' })).toBeVisible();
});

test('财务双层导航直达明细，收起后保留页内切换', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/finance`);
  const sidebar = page.getByRole('navigation', { name: '财务与结算功能', exact: true });
  await expect(sidebar.getByRole('link', { name: '老板总览', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(sidebar.getByRole('link', { name: '套餐续费', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '按月明细', exact: true })).toBeVisible();
  await expect(page.getByText('常用财务流程')).toBeHidden();
  await sidebar.getByRole('link', { name: '收入管理', exact: true }).click();
  await expect(page).toHaveURL(/tab=income/);
  await expect(sidebar.getByRole('link', { name: '收入管理', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.reload();
  await expect(sidebar.getByRole('link', { name: '收入管理', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('button', { name: '收起功能导航', exact: true }).click();
  await expect(sidebar).toBeHidden();
  await expect(page.getByText('常用财务流程')).toBeVisible();
  await expect(page.getByRole('tab', { name: /收入管理/ })).toHaveAttribute('data-state', 'active');
  await expect(page.getByLabel('更多财务明细')).toBeVisible();
  await page.getByRole('button', { name: '展开功能导航', exact: true }).click();
  await expect(sidebar).toBeVisible();
});

test('客户详情默认进入客户 360 并提供直接动作', async ({ page }) => {
  await page.goto(`${baseUrl}/customers?detail=1`);
  await expect(page.getByRole('heading', { name: '测试客户' })).toBeVisible();
  await expect(page.getByRole('tab', { name: '客户 360' })).toHaveAttribute('data-state', 'active');
  await expect(page.getByText('下一步动作')).toBeVisible();
  await expect(page.getByRole('button', { name: '新增跟进' }).first()).toBeVisible();
  await expect(page.locator('select:visible').filter({ hasText: '更多资料与工具' })).toBeVisible();
});

test('关键角色页面在手机宽度保持可操作且无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ['/sales-workbench', '/operations-workbench', '/finance', '/customers?detail=1']) {
    await page.goto(`${baseUrl}${path}`);
    await expect(page.locator('main')).toBeVisible();
    const widths = await page.evaluate(() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    expect(widths.document).toBeLessThanOrEqual(widths.viewport);
    expect(widths.body).toBeLessThanOrEqual(widths.viewport);
  }
  await expect(page.getByRole('tab', { name: '客户 360' })).toBeVisible();
});
