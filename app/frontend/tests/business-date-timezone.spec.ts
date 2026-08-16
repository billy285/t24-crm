import { expect, test, type Page, type Route } from '@playwright/test';

import {
  addBusinessDateDays,
  businessDateDifference,
  businessDateKey,
  businessWeekRange,
} from '../src/lib/business-date';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const fixedInstant = new Date('2026-08-16T16:30:00.000Z');
const employee = { id: 1, name: '北京时间测试管理员', role: 'super_admin', status: 'active' };
const customer = {
  id: 1,
  customer_code: 'T24-TZ001',
  business_name: '北京时间测试客户',
  contact_name: '陈老板',
  phone: '555-0100',
  status: 'closed',
  industry: 'restaurant',
  country: 'US',
  state: 'CA',
  city: 'Los Angeles',
  sales_person: employee.name,
};

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  });
}

async function mockBusinessDateApis(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'business-date-test-token');
    window.localStorage.setItem('token', 'business-date-test-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
    window.localStorage.setItem('emp_auth_remembered', '1');
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/app-config')) return fulfillJson(route, { items: {} });
    if (path.includes('/entities/customer_callbacks')) return fulfillJson(route, {
      items: [
        {
          id: 11,
          customer_id: customer.id,
          employee_id: employee.id,
          employee_name: employee.name,
          callback_date: '2026-08-17T00:00:00.000Z',
          callback_type: 'satisfaction',
          status: 'pending',
          content: '北京时间今日回访',
        },
        {
          id: 12,
          customer_id: customer.id,
          employee_id: employee.id,
          employee_name: employee.name,
          callback_date: '2026-08-16T00:00:00.000Z',
          callback_type: 'satisfaction',
          status: 'pending',
          content: '北京时间逾期回访',
        },
      ],
    });
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: [customer] });
    if (path.includes('/entities/employees')) return fulfillJson(route, { items: [employee] });
    if (path.includes('/entities/service_progresses')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/service_tasks')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/subscriptions')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/tasks')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });
}

test('北京时间日期工具在 UTC 前一日时仍返回正确日历日期', () => {
  expect(businessDateKey(fixedInstant)).toBe('2026-08-17');
  expect(addBusinessDateDays('2026-08-17', -1)).toBe('2026-08-16');
  expect(businessDateDifference('2026-08-16', '2026-08-17')).toBe(-1);
  expect(businessWeekRange(fixedInstant)).toEqual({ start: '2026-08-17', end: '2026-08-23' });
});

test('北京时间凌晨的回访默认日期、今日与逾期统计不会落到 UTC 昨日', async ({ page }) => {
  await page.clock.setFixedTime(fixedInstant);
  await mockBusinessDateApis(page);
  await page.goto(`${baseUrl}/callbacks`);

  await expect(page.getByTestId('callback-today-count')).toHaveText('1');
  await expect(page.getByTestId('callback-overdue-count')).toHaveText('1');

  await page.getByRole('button', { name: '新增回访' }).click();
  await expect(page.getByRole('dialog').getByTestId('callback-date-input')).toHaveValue('2026-08-17');
});

test('北京时间凌晨新增服务时默认开始日期为当天', async ({ page }) => {
  await page.clock.setFixedTime(fixedInstant);
  await mockBusinessDateApis(page);
  await page.goto(`${baseUrl}/service-board`);

  await page.getByRole('button', { name: '手动新增服务' }).click();
  await expect(page.getByRole('dialog').getByTestId('service-start-date-input')).toHaveValue('2026-08-17');
});
