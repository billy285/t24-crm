import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedAdmin(page: Page) {
  const employee = { id: 1, name: '生命周期管理员', role: 'super_admin', status: 'active' };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'lifecycle-dashboard-token');
    window.localStorage.setItem('token', 'lifecycle-dashboard-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/customer-lifecycle/overview')) return fulfillJson(route, {
      summary: { new_customers: 2, existing_customers: 0, current_active: 1, current_paused: 0, pending_stop: 0, stopped: 1, retention_3m: 50, retention_6m: null, retention_12m: null, median_tenure_months: null, average_stopped_months: 2, review_count: 1 },
      cohorts: [{ month: '2026-07', customers: 2, m1: 50, m3: null, m6: null, m12: null }],
      monthly: [{ month: '2026-08', active_at_start: 2, started: 1, stopped: 1, churn_rate: 50 }],
      stop_reasons: [{ reason: 'performance', label: '效果不满意', count: 1 }],
      customers: [
        { id: 1, customer_id: 1, business_name: '合作客户A', customer_code: 'C001', cycle_number: 1, first_payment_id: 1, started_at: '2026-08-10', status: 'active', start_source: 'payment', start_locked: true, cooperation_months: 0.3, sales_person: '负责人A', needs_review: false, closure_needed: false },
        { id: 2, customer_id: 2, business_name: '停止客户B', customer_code: 'C002', cycle_number: 1, first_payment_id: 2, started_at: '2026-06-01', ended_at: '2026-08-15', status: 'stopped', start_source: 'payment', start_locked: true, stop_reason: 'performance', stop_reason_label: '效果不满意', cooperation_months: 2.5, sales_person: '负责人B', needs_review: true, closure_needed: true },
      ],
    });
    if (path.includes('/customer-lifecycle/customers/')) return fulfillJson(route, { customer: { id: 1, business_name: '测试客户' }, cycles: [], events: [] });
    return fulfillJson(route, { items: [] });
  });
}

test('生命周期总览支持统计下钻并分离高级分析', async ({ page }) => {
  await seedAdmin(page);
  await page.goto(`${baseUrl}/customer-lifecycle`);

  await expect(page.getByRole('tab', { name: '总览' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('客户状态分布')).toBeVisible();
  await expect(page.getByText('首笔记账月份留存')).toHaveCount(0);

  await page.getByRole('button', { name: /当前合作/ }).first().click();
  await expect(page.getByRole('tab', { name: '客户明细' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('合作客户A')).toBeVisible();
  await expect(page.getByText('停止客户B')).toHaveCount(0);

  await page.getByRole('tab', { name: '总览' }).click();
  await page.getByRole('button', { name: /效果不满意/ }).click();
  await expect(page.getByText('停止客户B')).toBeVisible();
  await expect(page.getByText('合作客户A')).toHaveCount(0);

  await page.getByRole('tab', { name: '留存分析' }).click();
  await expect(page.getByText('首笔记账月份留存')).toBeVisible();
  await expect(page.getByText('月度新增与流失')).toBeVisible();

  await page.getByRole('tab', { name: /数据核对/ }).click();
  await expect(page.getByText('数据核对与业务闭环')).toBeVisible();
  await expect(page.getByText('停止后仍有未关闭项目或交付')).toBeVisible();
});
