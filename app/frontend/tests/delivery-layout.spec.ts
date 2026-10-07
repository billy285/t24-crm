import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5188';
const admin = { id: 1, name: '交付布局管理员', role: 'super_admin', status: 'active' };
const customer = { id: 101, business_name: '星河餐厅', customer_code: 'C101', contact_name: '张先生', phone: '555-0101', status: 'closed', country: 'US', state: 'CA', sales_person: admin.name, industry: 'restaurant' };

async function seed(page: Page) {
  const writes: string[] = [];
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'delivery-layout-test');
    localStorage.setItem('token', 'delivery-layout-test');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, admin);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET') writes.push(path);
    let data: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = admin;
    if (path.includes('/app-config')) data = { items: {} };
    if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    if (path.includes('/entities/customers')) data = { items: [customer], total: 1 };
    if (path.includes('/entities/employees')) data = { items: [admin], total: 1 };
    if (path.includes('/entities/deals')) data = { items: [{ id: 201, customer_id: 101, customer_name: '星河餐厅', sales_name: admin.name, product_type: 'social_media', package_name: '基础服务', billing_cycle: 'monthly', deal_amount: 428, deal_date: '2026-10-01', is_paid: true, is_handed_over: false, is_transferred_ops: false }], total: 1 };
    if (path.includes('/entities/subscriptions')) data = { items: [{ id: 301, customer_id: 101, customer_name: '星河餐厅', product_type: 'social_media', package_name: '基础服务', package_price: 428, billing_cycle: 'monthly', status: 'active', auto_renew: false, start_date: '2026-10-01', end_date: '2026-11-01' }], total: 1 };
    if (path.includes('/entities/payments')) data = { items: [{ id: 401, customer_id: 101, amount_paid: 400, amount_due: 428, outstanding_amount: 28, payment_date: '2026-10-01' }], total: 1 };
    if (path.includes('/entities/tasks')) data = { items: [{ id: 501, title: '核对上线资料', customer_id: 101, customer_name: '星河餐厅', assignee_name: admin.name, task_type: 'follow_up', status: 'pending', priority: 'medium', due_date: '2026-10-09' }], total: 1 };
    if (path.includes('/entities/customer_callbacks')) data = { items: [{ id: 601, customer_id: 101, employee_id: 1, employee_name: admin.name, callback_date: '2026-10-09', callback_type: 'satisfaction', status: 'pending', content: '确认本周服务进度' }], total: 1 };
    if (path.includes('/entities/service_progresses')) data = { items: [{ id: 701, customer_id: 101, customer_name: '星河餐厅', service_type: 'social_media', service_stage: 'account_setup', progress_percent: 40, package_name: '基础服务', sales_person: admin.name, ops_person: admin.name, last_work_summary: '已核对平台信息，待客户确认资料', last_update_time: '2026-10-07', service_end_date: '2026-11-01', issue_status: 'none' }], total: 1 };
    if (path.includes('/customer-lifecycle/overview')) data = {
      summary: { new_customers: 1, existing_customers: 0, current_active: 1, current_paused: 0, pending_stop: 0, stopped: 0, review_count: 0, retention_3m: null, retention_6m: null, retention_12m: null, median_tenure_months: null, average_stopped_months: null },
      monthly: [], cohorts: [], stop_reasons: [],
      customers: [{ id: 101, customer_id: 101, business_name: '星河餐厅', customer_code: 'C101', cycle_number: 1, first_payment_id: 401, started_at: '2026-10-01', status: 'active', cooperation_months: 0.3, sales_person: admin.name, needs_review: false, closure_needed: false }],
    };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return writes;
}

test('成交客户切换列展示保留尾款和原始收款金额，且不提交账目', async ({ page }) => {
  const writes = await seed(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/sales`);
  await expect(page.getByRole('columnheader', { name: '尾款', exact: true })).toBeVisible();
  await expect(page.getByText('$28', { exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '最近收款', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '展开全部列' }).click();
  await expect(page.getByRole('columnheader', { name: '最近收款', exact: true })).toBeVisible();
  await expect(page.getByText('$400', { exact: true })).toBeVisible();
  await expect(page.getByText('$428', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '简洁视图' }).click();
  await expect(page.getByText('$28', { exact: true })).toBeVisible();
  expect(writes).toEqual([]);
});

test('交付和记录页面在电脑与手机均可阅读，切换布局不产生业务写入', async ({ page }) => {
  const writes = await seed(page);
  const routes = [
    ['/tasks', '任务协作', 'tasks'], ['/service-board', '新客户交付进度看板', 'service-board'],
    ['/callbacks', '电话回访', 'callbacks'], ['/sales', '成交客户管理', 'active-customers'],
    ['/deals', '成交管理', 'deals'], ['/customer-lifecycle', '客户生命周期', 'lifecycle'],
  ];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    for (const [path, title, file] of routes) {
      await page.goto(`${base}${path}`);
      await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
      await expect(page.locator('.calm-delivery-page')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (process.env.T24_LAYOUT_OUTPUT) {
        await page.screenshot({ animations: 'disabled', path: `${process.env.T24_LAYOUT_OUTPUT}/${file}-${width}.png` });
      }
    }
  }
  expect(writes).toEqual([]);
});
