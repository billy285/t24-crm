import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 61, name: '竞态测试管理员', role: 'admin', status: 'active' };

const customers = [
  {
    id: 1,
    customer_code: 'RACE-A',
    business_name: '慢客户 A',
    contact_name: 'A 老板',
    phone: '555-1001',
    status: 'closed',
    level: 'normal',
    industry: 'restaurant',
    source: 'referral',
    country: 'US',
    state: 'CA',
    city: 'Los Angeles',
    sales_person: employee.name,
  },
  {
    id: 2,
    customer_code: 'RACE-B',
    business_name: '快客户 B',
    contact_name: 'B 老板',
    phone: '555-1002',
    status: 'closed',
    level: 'normal',
    industry: 'nail',
    source: 'referral',
    country: 'US',
    state: 'NV',
    city: 'Las Vegas',
    sales_person: employee.name,
  },
];

const serviceProgresses = [
  {
    id: 101,
    customer_id: 1,
    customer_name: '慢服务 A',
    service_type: 'social_media',
    service_stage: 'account_setup',
    progress_percent: 20,
    sales_person: employee.name,
    ops_person: employee.name,
    design_person: '',
    package_name: '基础套餐',
    package_platforms: 'Facebook',
    industry: 'restaurant',
    country: 'US',
    state: 'CA',
    city: 'Los Angeles',
    service_start_date: '2026-08-01',
    service_end_date: '2026-12-31',
    last_update_time: '2026-08-16T08:00:00Z',
    last_update_person: employee.name,
    last_work_summary: 'A 服务摘要',
    issue_status: 'none',
    issue_resolved: false,
    created_at: '2026-08-01T08:00:00Z',
  },
  {
    id: 102,
    customer_id: 2,
    customer_name: '快服务 B',
    service_type: 'social_media',
    service_stage: 'content_creation',
    progress_percent: 60,
    sales_person: employee.name,
    ops_person: employee.name,
    design_person: '',
    package_name: '进阶套餐',
    package_platforms: 'Facebook,Instagram',
    industry: 'nail',
    country: 'US',
    state: 'NV',
    city: 'Las Vegas',
    service_start_date: '2026-08-01',
    service_end_date: '2026-12-31',
    last_update_time: '2026-08-16T09:00:00Z',
    last_update_person: employee.name,
    last_work_summary: 'B 服务摘要',
    issue_status: 'none',
    issue_resolved: false,
    created_at: '2026-08-01T09:00:00Z',
  },
];

const serviceTasks = [
  {
    id: 1001,
    service_progress_id: 101,
    customer_id: 1,
    customer_name: '慢服务 A',
    task_name: 'A 慢任务不应串入',
    task_type: 'publish_content',
    platform: 'Facebook',
    assignee_name: employee.name,
    priority: 'medium',
    status: 'pending',
    due_date: '2026-08-20',
    created_at: '2026-08-16T08:00:00Z',
  },
  {
    id: 1002,
    service_progress_id: 102,
    customer_id: 2021,
    customer_name: '快服务 B',
    task_name: 'B 第一任务',
    task_type: 'publish_content',
    platform: 'Facebook',
    assignee_name: employee.name,
    priority: 'medium',
    status: 'pending',
    due_date: '2026-08-20',
    created_at: '2026-08-16T09:00:00Z',
  },
  {
    id: 1003,
    service_progress_id: 102,
    customer_id: 2022,
    customer_name: '快服务 B',
    task_name: 'B 第二任务',
    task_type: 'publish_content',
    platform: 'Instagram',
    assignee_name: employee.name,
    priority: 'high',
    status: 'pending',
    due_date: '2026-08-20',
    created_at: '2026-08-16T09:05:00Z',
  },
];

const sleep = (milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds));

async function fulfillJson(route: Route, data: unknown, status = 200) {
  try {
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  } catch {
    // A guarded request may be aborted by the page before a deliberately slow
    // mock responds. That is the expected path for these race regressions.
  }
}

function readQuery(url: URL): Record<string, unknown> {
  try {
    return JSON.parse(url.searchParams.get('query') || '{}');
  } catch {
    return {};
  }
}

async function installAuth(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'cross-object-race-token');
    window.localStorage.setItem('token', 'cross-object-race-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
}

async function navigateWithSearch(page: Page, url: string) {
  await page.evaluate(nextUrl => {
    window.history.pushState({}, '', nextUrl);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, url);
}

async function mockCustomerApis(
  page: Page,
  deductionRequests: Array<{ method: string; path: string }>,
) {
  await installAuth(page);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const query = readQuery(url);
    const customerId = Number(query.customer_id || query.id || 0);

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/deductions-monthly/ensure')) {
      deductionRequests.push({ method: request.method(), path });
      return fulfillJson(route, [{ year_month: '2026-08', rate: 0.03 }]);
    }
    if (path.endsWith('/deductions-monthly')) {
      deductionRequests.push({ method: request.method(), path });
      return fulfillJson(route, [{ year_month: '2026-08', rate: 0.03 }]);
    }
    if (/\/entities\/media_accounts\/501\/password$/.test(path)) {
      await sleep(550);
      return fulfillJson(route, { id: 501, login_password: 'A-SECRET-MUST-NOT-LEAK' });
    }
    if (/\/entities\/media_accounts\/502\/password$/.test(path)) {
      return fulfillJson(route, { id: 502, login_password: 'B-VERY-LONG-PASSWORD-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ' });
    }
    if (path.includes('/entities/media_accounts')) {
      if (customerId === 2) await sleep(220);
      const account = customerId === 1
        ? { id: 501, customer_id: 1, platform_name: 'Facebook', account_name: 'account-a', has_password: true, account_status: 'active' }
        : {
          id: 502,
          customer_id: 2,
          platform_name: 'Instagram',
          account_name: 'account-b',
          login_email: 'very-long-email-address-without-shortening-for-mobile@extremely-long-example-domain.test',
          profile_url: 'https://example.test/a-very-long-profile-url-without-natural-short-breaks/0123456789',
          notes: '这是用于验证三百六十像素手机页面不会被超长备注撑开的连续内容ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
          has_password: true,
          account_status: 'active',
        };
      return fulfillJson(route, { items: customerId ? [account] : [] });
    }
    if (path.includes('/entities/customers/') && path.endsWith('/projects')) return fulfillJson(route, { items: [] });
    if (path.includes('/customer-lifecycle/customers/')) return fulfillJson(route, { cycles: [], events: [] });
    if (path.includes('/entities/customers')) {
      const items = customerId ? customers.filter(customer => customer.id === customerId) : customers;
      return fulfillJson(route, { items });
    }
    if (path.includes('/entities/follow_ups')) {
      if (customerId === 1) await sleep(600);
      return fulfillJson(route, {
        items: customerId ? [{
          id: customerId * 10,
          customer_id: customerId,
          contact_method: 'phone',
          content: customerId === 1 ? 'A 慢跟进不应覆盖' : 'B 正确跟进内容',
          stage: 'communicating',
          close_probability: 70,
          employee_name: employee.name,
          created_at: '2026-08-16T09:00:00Z',
        }] : [],
      });
    }
    if (path.includes('/entities/payments')) return fulfillJson(route, {
      items: customerId ? [{ id: customerId * 100, customer_id: customerId, payment_date: '2026-08-10', amount: 198 }] : [],
    });
    if (path.includes('/entities/customer_contacts')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/employees')) return fulfillJson(route, { items: [employee] });
    if (path.includes('/commissions/assignment-options')) return fulfillJson(route, { items: [] });
    if (path.includes('/product-plans')) return fulfillJson(route, { business_lines: [], products: [], plans: [] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });
}

async function mockServiceApis(page: Page, progressListHandler?: (route: Route) => Promise<void>) {
  await installAuth(page);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const query = readQuery(url);
    const progressId = Number(query.service_progress_id || 0);
    const customerId = Number(query.customer_id || 0);

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (/\/entities\/service_progresses\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop());
      return fulfillJson(route, serviceProgresses.find(item => item.id === id) || {});
    }
    if (path.includes('/entities/service_progresses')) {
      if (progressListHandler) return progressListHandler(route);
      return fulfillJson(route, { items: serviceProgresses });
    }
    if (path.includes('/entities/service_tasks')) {
      if (progressId === 101) await sleep(600);
      const items = progressId ? serviceTasks.filter(task => task.service_progress_id === progressId) : serviceTasks;
      return fulfillJson(route, { items });
    }
    if (path.includes('/entities/customer_ai_copies')) {
      if (customerId === 2021) await sleep(550);
      return fulfillJson(route, {
        items: customerId === 2021
          ? [{ id: 3001, customer_id: customerId, title: '第一任务旧文案', content: '旧内容', platform: 'Facebook', content_type: 'post' }]
          : [{ id: 3002, customer_id: customerId, title: '第二任务正确文案', content: '正确内容', platform: 'Instagram', content_type: 'post' }],
      });
    }
    if (path.includes('/entities/customer_materials')) {
      if (customerId === 2021) await sleep(550);
      return fulfillJson(route, {
        items: customerId === 2021
          ? [{ id: 4001, customer_id: customerId, title: '第一任务旧素材', platform: 'Facebook', material_type: 'image' }]
          : [{ id: 4002, customer_id: customerId, title: '第二任务正确素材', platform: 'Instagram', material_type: 'image' }],
      });
    }
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: customers });
    if (path.includes('/entities/employees')) return fulfillJson(route, { detail: 'secondary service unavailable' }, 503);
    if (path.includes('/entities/subscriptions')) return fulfillJson(route, { items: [] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });
}

test('客户详情 A 慢 B 快且关闭后，旧请求不能覆盖或重新打开详情；手机扣点只 GET', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const deductionRequests: Array<{ method: string; path: string }> = [];
  await mockCustomerApis(page, deductionRequests);

  await page.goto(`${baseUrl}/customers`);
  await page.getByText('慢客户 A', { exact: true }).first().click();
  await expect(page.getByRole('heading', { name: '慢客户 A' })).toBeVisible();

  await navigateWithSearch(page, '/customers?detail=2');
  await expect(page.getByRole('heading', { name: '快客户 B' })).toBeVisible();
  await page.getByRole('tab', { name: '跟进' }).click();
  await expect(page.getByText('B 正确跟进内容')).toBeVisible();
  await sleep(700);
  await expect(page.getByRole('heading', { name: '快客户 B' })).toBeVisible();
  await expect(page.getByText('A 慢跟进不应覆盖')).toHaveCount(0);

  await expect.poll(() => deductionRequests.length).toBeGreaterThan(0);
  expect(deductionRequests.every(item => item.method === 'GET')).toBe(true);
  expect(deductionRequests.some(item => item.path.endsWith('/ensure'))).toBe(false);

  await page.getByRole('button', { name: '返回列表' }).click();
  await sleep(100);
  await expect(page.getByRole('heading', { name: '快客户 B' })).toHaveCount(0);
  await expect(page.getByText('慢客户 A', { exact: true }).first()).toBeVisible();
});

test('切换客户立即清空媒体账号，迟到的 A 密码不能显示到 B', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mockCustomerApis(page, []);

  await page.goto(`${baseUrl}/customers?detail=1&tab=media`);
  await expect(page.getByText('@account-a')).toBeVisible();
  await page.getByRole('button', { name: '查看account-a的密码' }).click();

  await navigateWithSearch(page, '/customers?detail=2&tab=media');
  await expect(page.getByText('@account-a')).toHaveCount(0);
  await expect(page.getByText('@account-b')).toBeVisible();
  await sleep(700);
  await expect(page.getByText('@account-b')).toBeVisible();
  await expect(page.getByText('A-SECRET-MUST-NOT-LEAK')).toHaveCount(0);
  await expect(page.getByText('@account-a')).toHaveCount(0);
  await page.getByRole('button', { name: '查看account-b的密码' }).click();
  await expect(page.getByText('B-VERY-LONG-PASSWORD-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ')).toBeVisible();
  const widths = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
});

test('媒体账号加载失败明确提示并可重试，不伪装成暂无数据', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mockCustomerApis(page, []);
  let attempts = 0;
  await page.route(/\/api\/v1\/entities\/media_accounts(?:\?.*)?$/, async route => {
    attempts += 1;
    if (attempts === 1) return fulfillJson(route, { detail: 'temporary unavailable' }, 503);
    return fulfillJson(route, {
      items: [{ id: 503, customer_id: 2, platform_name: 'Facebook', account_name: 'retry-success', has_password: false, account_status: 'active' }],
    });
  });

  await page.goto(`${baseUrl}/customers?detail=2&tab=media`);
  await expect(page.getByRole('alert')).toContainText('媒体账号加载失败，请重试');
  await expect(page.getByText('暂无媒体账号')).toHaveCount(0);
  await page.getByRole('button', { name: '重新加载' }).click();
  await expect(page.getByText('@retry-success')).toBeVisible();
  expect(attempts).toBe(2);
});

test('服务看板保留主请求成功数据，详情与完成弹窗都拒绝迟到的旧对象响应', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockServiceApis(page);

  await page.goto(`${baseUrl}/service-board`);
  // Employee reference data deliberately returns 503, but the successful
  // service-progress response must remain visible.
  await expect(page.getByText('慢服务 A', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('快服务 B', { exact: true }).first()).toBeVisible();

  await page.getByText('慢服务 A', { exact: true }).first().click();
  await expect(page.getByRole('heading', { name: '慢服务 A' })).toBeVisible();
  await page.getByRole('button', { name: '返回看板' }).click();
  await page.getByText('快服务 B', { exact: true }).first().click();
  await expect(page.getByRole('heading', { name: '快服务 B' })).toBeVisible();
  await page.getByRole('tab', { name: /任务清单/ }).click();
  await expect(page.getByText('B 第一任务')).toBeVisible();
  await expect(page.getByText('B 第二任务')).toBeVisible();
  await sleep(700);
  await expect(page.getByText('A 慢任务不应串入')).toHaveCount(0);

  await page.getByTestId('service-task-1002').locator('[title="标记完成"]').click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: '完成任务 - B 第一任务' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: '取消' }).click();

  await page.getByTestId('service-task-1003').locator('[title="标记完成"]').click();
  const completionDialog = page.getByRole('dialog');
  await expect(completionDialog.getByRole('heading', { name: '完成任务 - B 第二任务' })).toBeVisible();
  await expect(completionDialog.locator('select').nth(1)).toContainText('第二任务正确文案');
  await sleep(700);
  await expect(completionDialog.getByRole('heading', { name: '完成任务 - B 第二任务' })).toBeVisible();
  await expect(completionDialog.locator('select').nth(1)).toContainText('第二任务正确文案');
  await expect(completionDialog.getByText('第一任务旧文案')).toHaveCount(0);
});

test('服务看板连续刷新只采用最后一轮列表响应', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let manualRefreshPhase = false;
  let manualRefreshCount = 0;

  await mockServiceApis(page, async route => {
    const source = serviceProgresses[0];
    if (!manualRefreshPhase) {
      return fulfillJson(route, { items: [{ ...source, customer_name: '初始服务结果' }] });
    }
    manualRefreshCount += 1;
    if (manualRefreshCount === 1) {
      await sleep(600);
      return fulfillJson(route, { items: [{ ...source, customer_name: '迟到的旧刷新结果' }] });
    }
    return fulfillJson(route, { items: [{ ...source, customer_name: '最后一轮刷新结果' }] });
  });

  await page.goto(`${baseUrl}/service-board`);
  await expect(page.getByText('初始服务结果', { exact: true }).first()).toBeVisible();

  manualRefreshPhase = true;
  await page.getByRole('button', { name: '刷新' }).click();
  await expect.poll(() => manualRefreshCount).toBe(1);
  await page.getByRole('button', { name: '刷新' }).click();
  await expect.poll(() => manualRefreshCount).toBe(2);
  await expect(page.getByText('最后一轮刷新结果', { exact: true }).first()).toBeVisible();

  await sleep(750);
  await expect(page.getByText('迟到的旧刷新结果', { exact: true })).toHaveCount(0);
  await expect(page.getByText('最后一轮刷新结果', { exact: true }).first()).toBeVisible();
});

test('成交删除后的快刷新胜过删除前的慢响应，旧记录不会复活', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installAuth(page);

  const staleDeal = {
    id: 901,
    customer_id: 1,
    customer_name: '不能复活的成交记录',
    sales_name: employee.name,
    product_type: 'social_media',
    package_name: '基础套餐',
    billing_cycle: 'monthly',
    deal_amount: 198,
    deal_date: '2026-08-16',
    is_paid: true,
    is_handed_over: false,
    is_transferred_ops: false,
  };
  let currentDeals = [staleDeal];
  let racePhase = false;
  let raceListRequestCount = 0;

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/deals')) {
      if (method === 'DELETE') {
        currentDeals = [];
        return fulfillJson(route, { success: true });
      }
      const snapshot = currentDeals.map(item => ({ ...item }));
      if (racePhase) {
        raceListRequestCount += 1;
        if (raceListRequestCount === 1) await sleep(600);
      }
      return fulfillJson(route, { items: snapshot });
    }
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: customers });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });

  await page.goto(`${baseUrl}/deals`);
  await expect(page.getByRole('button', { name: staleDeal.customer_name, exact: true })).toBeVisible();

  racePhase = true;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('t24:business-data-refresh')));
  await expect.poll(() => raceListRequestCount).toBe(1);

  await page.getByRole('button', { name: `删除 ${staleDeal.customer_name} 的成交记录` }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByText('成交记录已删除')).toBeVisible();
  await expect.poll(() => raceListRequestCount).toBeGreaterThanOrEqual(2);
  await expect(page.getByText(staleDeal.customer_name, { exact: true })).toHaveCount(0);

  await sleep(750);
  await expect(page.getByText(staleDeal.customer_name, { exact: true })).toHaveCount(0);
});

test('回访删除后的快刷新胜过删除前的慢响应，旧回访不会复活', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installAuth(page);

  const callbackCustomer = { ...customers[0], id: 11, business_name: '回访竞态客户' };
  const staleCallback = {
    id: 902,
    customer_id: callbackCustomer.id,
    employee_id: employee.id,
    employee_name: employee.name,
    callback_date: '2026-08-16T10:00:00Z',
    callback_type: 'satisfaction',
    status: 'pending',
    content: '不能复活的旧回访内容',
  };
  let currentCallbacks = [staleCallback];
  let racePhase = false;
  let raceListRequestCount = 0;

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/customer_callbacks')) {
      if (method === 'DELETE') {
        currentCallbacks = [];
        return fulfillJson(route, { success: true });
      }
      const snapshot = currentCallbacks.map(item => ({ ...item }));
      if (racePhase) {
        raceListRequestCount += 1;
        if (raceListRequestCount === 1) await sleep(600);
      }
      return fulfillJson(route, { items: snapshot });
    }
    if (path.includes('/entities/employees/directory')) return fulfillJson(route, { items: [employee] });
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: [callbackCustomer] });
    if (path.includes('/entities/tasks')) return fulfillJson(route, { items: [] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });

  await page.goto(`${baseUrl}/callbacks`);
  await expect(page.getByText(staleCallback.content, { exact: true })).toBeVisible();

  racePhase = true;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('t24:business-data-refresh')));
  await expect.poll(() => raceListRequestCount).toBe(1);

  await page.getByRole('button', { name: `删除回访：${callbackCustomer.business_name}` }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByText('回访记录已删除')).toBeVisible();
  await expect.poll(() => raceListRequestCount).toBeGreaterThanOrEqual(2);
  await expect(page.getByText(staleCallback.content, { exact: true })).toHaveCount(0);

  await sleep(750);
  await expect(page.getByText(staleCallback.content, { exact: true })).toHaveCount(0);
});

test('任务完成后的快刷新胜过完成前的慢响应，旧状态不会回灌', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installAuth(page);

  const taskTitle = '不能回退的任务完成状态';
  let currentTasks = [{
    id: 903,
    title: taskTitle,
    customer_id: null,
    customer_name: '',
    assignee_id: employee.id,
    assignee_name: employee.name,
    collaborator_names: '',
    task_type: 'other',
    priority: 'medium',
    status: 'in_progress',
    notes: '',
    created_at: '2026-08-16T08:00:00Z',
    updated_at: '2026-08-16T08:00:00Z',
  }];
  let racePhase = false;
  let raceListRequestCount = 0;

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/tasks')) {
      if (method === 'PUT') {
        const payload = request.postDataJSON() || {};
        currentTasks = currentTasks.map(task => ({ ...task, ...payload }));
        return fulfillJson(route, currentTasks[0]);
      }
      const snapshot = currentTasks.map(item => ({ ...item }));
      if (racePhase) {
        raceListRequestCount += 1;
        if (raceListRequestCount === 1) await sleep(600);
      }
      return fulfillJson(route, { items: snapshot });
    }
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });

  await page.goto(`${baseUrl}/tasks`);
  const taskRow = page.locator('#task-row-903');
  await expect(taskRow.getByText(taskTitle, { exact: true })).toBeVisible();

  racePhase = true;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('t24:business-data-refresh')));
  await expect.poll(() => raceListRequestCount).toBe(1);

  await taskRow.getByRole('button', { name: '完成并记录' }).click();
  const completionDialog = page.getByRole('dialog', { name: '填写处理结果并完成' });
  await completionDialog.getByPlaceholder(/已联系客户并确认资料齐全/).fill('竞态完成结果必须保留');
  await completionDialog.getByRole('button', { name: '确认完成' }).click();
  await expect(page.getByText('任务已完成并记录结果')).toBeVisible();
  await expect.poll(() => raceListRequestCount).toBeGreaterThanOrEqual(2);
  await expect(taskRow.getByText('已完成', { exact: true })).toBeVisible();
  await expect(taskRow.getByText('竞态完成结果必须保留', { exact: true })).toBeVisible();

  await sleep(750);
  await expect(taskRow.getByText('已完成', { exact: true })).toBeVisible();
  await expect(taskRow.getByRole('button', { name: '完成并记录' })).toHaveCount(0);
});
