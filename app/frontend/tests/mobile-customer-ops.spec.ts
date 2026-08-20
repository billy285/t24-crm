import { expect, test, type Locator, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '移动测试管理员', role: 'admin', status: 'active' };
const localDateKey = (date: Date) => [
  date.getFullYear(),
  String(date.getMonth() + 1).padStart(2, '0'),
  String(date.getDate()).padStart(2, '0'),
].join('-');
const today = localDateKey(new Date());
const yesterday = localDateKey(new Date(Date.now() - 24 * 60 * 60 * 1000));

const customer = {
  id: 1,
  customer_code: 'T24-M001',
  business_name: '移动测试客户',
  contact_name: '陈老板',
  phone: '555-0100',
  wechat: 'mobile-test',
  status: 'closed',
  level: 'normal',
  industry: 'restaurant',
  source: 'referral',
  country: 'US',
  state: 'CA',
  city: 'Los Angeles',
  sales_person: employee.name,
  sales_employee_id: employee.id,
};

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function assertTouchTarget(locator: Locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  const css = await locator.evaluate(element => {
    const style = window.getComputedStyle(element);
    return {
      width: Number.parseFloat(style.width) || 0,
      minWidth: Number.parseFloat(style.minWidth) || 0,
      height: Number.parseFloat(style.height) || 0,
      minHeight: Number.parseFloat(style.minHeight) || 0,
    };
  });
  expect(Math.max(box?.width || 0, css.width, css.minWidth)).toBeGreaterThanOrEqual(44);
  expect(Math.max(box?.height || 0, css.height, css.minHeight)).toBeGreaterThanOrEqual(44);
}

async function expectNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}

async function mockMobileApi(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'mobile-customer-ops-token');
    window.localStorage.setItem('token', 'mobile-customer-ops-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path.includes('/entities/customer_contacts')) return fulfillJson(route, {
      items: [{ id: 31, customer_id: 1, contact_name: '王经理', contact_phone: '555-0111', contact_role: 'manager', notes: '日常对接' }],
    });
    if (path.includes('/entities/follow_ups')) return fulfillJson(route, {
      items: [{ id: 41, customer_id: 1, contact_method: 'phone', content: '确认下周素材', stage: 'communicating', close_probability: 70, employee_name: employee.name, created_at: `${today}T09:00:00Z` }],
    });
    if (path.includes('/entities/media_accounts')) return fulfillJson(route, {
      items: [{ id: 51, customer_id: 1, platform_name: 'Facebook', account_name: 'mobile-store', login_email: 'ops@example.com', has_password: true, profile_url: 'https://example.com/mobile-store', account_status: 'active' }],
    });
    if (path.includes('/entities/customer_callbacks')) return fulfillJson(route, {
      items: [{ id: 61, customer_id: 1, employee_id: 1, employee_name: employee.name, callback_date: `${today}T10:00:00Z`, callback_type: 'satisfaction', status: 'pending', content: '确认本周交付结果' }],
    });
    if (path.includes('/entities/service_progresses')) return fulfillJson(route, {
      items: [{
        id: 71,
        customer_id: 1,
        customer_name: customer.business_name,
        service_type: 'social_media',
        service_stage: 'account_setup',
        progress_percent: 40,
        sales_person: employee.name,
        ops_person: employee.name,
        design_person: '',
        package_name: '基础套餐',
        package_platforms: 'Facebook,Instagram',
        industry: customer.industry,
        country: customer.country,
        state: customer.state,
        city: customer.city,
        service_start_date: today,
        service_end_date: '',
        last_update_time: `${today}T09:00:00Z`,
        last_update_person: employee.name,
        last_work_summary: '完成账号资料核对',
        issue_status: 'none',
        issue_description: '',
        issue_found_date: '',
        issue_owner: '',
        issue_resolved: false,
        issue_resolved_date: '',
        notes: '',
        created_at: `${today}T08:00:00Z`,
      }],
    });
    if (path.includes('/entities/service_tasks')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/tasks')) return fulfillJson(route, {
      items: [
        { id: 81, title: '今日跟进测试', customer_id: 1, customer_name: customer.business_name, assignee_name: employee.name, status: 'pending', priority: 'high', task_type: 'follow_up', due_date: today, created_at: `${today}T08:00:00Z` },
        { id: 82, title: '逾期素材测试', customer_id: 1, customer_name: customer.business_name, assignee_name: employee.name, status: 'pending', priority: 'medium', task_type: 'content', due_date: yesterday, created_at: `${yesterday}T08:00:00Z` },
      ],
    });
    if (path.includes('/entities/employees')) return fulfillJson(route, { items: [employee] });
    if (path.includes('/entities/customers/1/projects')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: [customer] });
    if (path.includes('/customer-lifecycle/customers/1')) return fulfillJson(route, { cycles: [], events: [] });
    if (path.includes('/product-plans')) return fulfillJson(route, { business_lines: [], products: [], plans: [] });
    if (path.includes('/commissions/assignment-options')) return fulfillJson(route, { items: [] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockMobileApi(page);
});

test('客户详情手机端保留六个生命周期主标签，更多资料和行操作仍可达', async ({ page }) => {
  await page.goto(`${baseUrl}/customers?detail=1`);
  await expect(page.getByRole('heading', { name: customer.business_name })).toBeVisible();

  const mobileNavigation = page.getByRole('tablist', { name: '客户手机主导航' });
  await expect(mobileNavigation.getByRole('tab', { name: '客户 360' })).toBeVisible();
  await expect(mobileNavigation.getByRole('tab', { name: '时间线' })).toBeVisible();
  await expect(mobileNavigation.getByRole('tab', { name: '客户商机' })).toBeVisible();
  await expect(mobileNavigation.getByRole('tab', { name: '服务信息' })).toBeVisible();
  await expect(mobileNavigation.getByRole('tab', { name: '财务信息' })).toBeVisible();
  await expect(mobileNavigation.getByRole('tab', { name: '续费信息' })).toBeVisible();

  const more = page.getByLabel('更多资料与工具');
  await expect(more).toBeVisible();
  await more.selectOption('contacts');
  await expect(page.getByText('联系人信息')).toBeVisible();
  await assertTouchTarget(page.getByRole('button', { name: '编辑联系人：王经理' }));

  await more.selectOption('followups');
  await expect(page.getByText('确认下周素材')).toBeVisible();
  await assertTouchTarget(page.getByRole('button', { name: '编辑跟进记录' }));

  await more.selectOption('media');
  await expect(page.getByText('@mobile-store')).toBeVisible();
  await assertTouchTarget(page.getByRole('button', { name: '编辑媒体账号：mobile-store' }));
  await expectNoHorizontalOverflow(page);
});

test('新增客户手机表单单列分区，底部保存操作保持可达', async ({ page }) => {
  await page.goto(`${baseUrl}/customers`);
  await expect(page.getByText('批量导入、敏感数据导出、列设置和快捷编辑请在电脑端处理。')).toBeVisible();
  await expect(page.getByRole('button', { name: /导入|导出|列设置|快捷编辑|管理/ })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /导入客户|导出 Excel|导出 CSV|列设置|快捷编辑/ })).toHaveCount(0);
  await page.getByRole('button', { name: '新增客户' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '新增客户' })).toBeVisible();
  await expect(dialog.getByText('基本与联系信息')).toBeVisible();
  await expect(dialog.getByText('地区与客户归类')).toBeVisible();
  await expect(dialog.getByText('合作项目与归属')).toBeVisible();
  await expect(dialog.getByText('平台与补充资料')).toBeVisible();

  const columnCount = await dialog.getByTestId('customer-form-grid').evaluate(element => (
    window.getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length
  ));
  expect(columnCount).toBe(1);
  await expect(dialog.getByTestId('customer-form-actions')).toBeVisible();
  await assertTouchTarget(dialog.getByRole('button', { name: '保存', exact: true }));
  await expectNoHorizontalOverflow(page);
});

test('任务手机首屏聚焦我的、今日、逾期，并以卡片提供可触达操作', async ({ page }) => {
  await page.goto(`${baseUrl}/tasks`);
  const focusGroup = page.getByRole('group', { name: '手机任务重点' });
  await expect(focusGroup).toBeVisible();
  await expect(focusGroup.getByRole('button', { name: /我的/ })).toBeVisible();
  await expect(focusGroup.getByRole('button', { name: /今日/ })).toBeVisible();
  await expect(focusGroup.getByRole('button', { name: /逾期/ })).toBeVisible();

  await focusGroup.getByRole('button', { name: /今日/ }).click();
  await expect(page.getByText('今日跟进测试')).toBeVisible();
  await expect(page.getByText('逾期素材测试')).toHaveCount(0);
  await assertTouchTarget(page.getByRole('button', { name: '开始处理' }));
  await assertTouchTarget(page.getByRole('button', { name: '编辑任务' }));
  await expectNoHorizontalOverflow(page);
});

test('回访和服务看板手机卡片的核心操作至少为 44px', async ({ page }) => {
  await page.goto(`${baseUrl}/callbacks`);
  await expect(page.getByText('确认本周交付结果')).toBeVisible();
  await assertTouchTarget(page.getByRole('button', { name: `完成回访：${customer.business_name}` }));
  await assertTouchTarget(page.getByRole('button', { name: `编辑回访：${customer.business_name}` }));
  await expectNoHorizontalOverflow(page);

  await page.goto(`${baseUrl}/service-board`);
  await expect(page.getByText(customer.business_name).first()).toBeVisible();
  await assertTouchTarget(page.getByRole('button', { name: '编辑', exact: true }).first());
  await assertTouchTarget(page.getByRole('button', { name: '更新摘要', exact: true }).first());
  await expectNoHorizontalOverflow(page);
});

test('快速重复点击未接只更新一次并只生成一条明日回访', async ({ page }) => {
  let updateCount = 0;
  let nextCallbackCount = 0;
  await page.route(/\/api\/v1\/entities\/customer_callbacks(?:\/61)?$/, async route => {
    const method = route.request().method();
    if (method === 'PUT') {
      updateCount += 1;
      await new Promise(resolve => setTimeout(resolve, 150));
      return fulfillJson(route, { id: 61, customer_id: 1, employee_id: 1, employee_name: employee.name, callback_date: `${today}T10:00:00Z`, callback_type: 'satisfaction', status: 'no_answer', content: '确认本周交付结果' });
    }
    if (method === 'POST') {
      nextCallbackCount += 1;
      return fulfillJson(route, { id: 62, ...route.request().postDataJSON() });
    }
    return fulfillJson(route, { items: [{ id: 61, customer_id: 1, employee_id: 1, employee_name: employee.name, callback_date: `${today}T10:00:00Z`, callback_type: 'satisfaction', status: 'pending', content: '确认本周交付结果' }] });
  });

  await page.goto(`${baseUrl}/callbacks`);
  const noAnswer = page.getByRole('button', { name: `标记未接：${customer.business_name}` });
  await expect(noAnswer).toBeVisible();
  await noAnswer.evaluate(element => {
    (element as HTMLButtonElement).click();
    (element as HTMLButtonElement).click();
  });

  await expect(page.getByText('已标记为未接通，并自动安排明日回访')).toBeVisible();
  expect(updateCount).toBe(1);
  expect(nextCallbackCount).toBe(1);
});

test('成交手机版保留编辑交接与生成看板闭环但不挂载删除和套餐管理', async ({ page }) => {
  await page.route(/\/api\/v1\/entities\/deals/, route => fulfillJson(route, {
    items: [{
      id: 91,
      customer_id: 1,
      customer_name: customer.business_name,
      sales_name: employee.name,
      product_type: 'social_media',
      package_name: '基础套餐',
      billing_cycle: 'monthly',
      deal_amount: 198,
      deal_date: today,
      is_paid: true,
      is_handed_over: false,
      is_transferred_ops: false,
      needs_group: true,
    }],
  }));

  await page.goto(`${baseUrl}/deals`);
  await expect(page.getByRole('heading', { name: '成交管理' })).toBeVisible();
  const generateBoard = page.getByRole('button', { name: '生成看板' });
  const editHandoff = page.getByRole('button', { name: '编辑交接' });
  await assertTouchTarget(generateBoard);
  await assertTouchTarget(editHandoff);
  await expect(page.locator('table')).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /删除成交|管理套餐/ })).toHaveCount(0);

  await editHandoff.click();
  const dialog = page.getByRole('dialog', { name: '编辑成交记录' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText('生成服务看板')).toBeVisible();
  await expect(dialog.getByRole('button', { name: '管理套餐' })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test('430px 客户与交付核心页面保持工整且无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });

  for (const [path, text] of [
    ['/customers?detail=1', customer.business_name],
    ['/tasks', '今日跟进测试'],
    ['/callbacks', '确认本周交付结果'],
    ['/service-board', customer.business_name],
  ] as const) {
    await page.goto(`${baseUrl}${path}`);
    await expect(page.getByText(text).first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});
