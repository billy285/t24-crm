import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';

const customers = [
  {
    id: 1,
    customer_code: 'CONTENT-A',
    business_name: '素材客户 A',
    contact_name: 'A 老板',
    phone: '555-2001',
    status: 'closed',
    level: 'normal',
    industry: 'restaurant',
    source: 'referral',
    country: 'US',
    state: 'CA',
    city: 'Los Angeles',
    sales_person: '权限测试管理员',
  },
  {
    id: 2,
    customer_code: 'CONTENT-B',
    business_name: '素材客户 B',
    contact_name: 'B 老板',
    phone: '555-2002',
    status: 'closed',
    level: 'normal',
    industry: 'nail',
    source: 'referral',
    country: 'US',
    state: 'NV',
    city: 'Las Vegas',
    sales_person: '权限测试管理员',
  },
];

const materialFor = (customerId: number) => ({
  id: 4100 + customerId,
  customer_id: customerId,
  title: customerId === 1 ? 'A 迟到素材' : 'B 正确素材',
  source_type: 'external_link',
  file_url: `https://example.test/customer-${customerId}.jpg`,
  material_type: 'image',
  platform: customerId === 1 ? 'facebook' : 'instagram',
  usage_status: 'unused',
  approval_status: 'pending',
  copyright_status: 'client_provided',
  created_at: '2026-08-16T09:00:00Z',
});

const menuItemFor = (customerId: number) => ({
  id: 4200 + customerId,
  customer_id: customerId,
  name: customerId === 1 ? 'A 迟到项目' : 'B 正确项目',
  item_type: 'service',
  status: 'active',
  suitable_platforms: '["instagram"]',
  updated_at: '2026-08-16T09:00:00Z',
});

const aiCopyFor = (customerId: number) => ({
  id: 4300 + customerId,
  customer_id: customerId,
  title: customerId === 1 ? 'A 迟到文案' : 'B 正确文案',
  content: customerId === 1 ? 'A 旧内容不得串入' : 'B 当前客户正确内容',
  platform: customerId === 1 ? 'facebook' : 'instagram',
  content_type: 'weekly_update',
  language: 'zh_en',
  tone: 'friendly',
  status: 'draft',
  is_ai_generated: true,
  generated_by: '权限测试管理员',
  created_at: '2026-08-16T09:00:00Z',
});

const sleep = (milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds));

async function fulfillJson(route: Route, data: unknown, status = 200) {
  try {
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  } catch {
    // Slow A responses may be invalidated or aborted after switching to B.
  }
}

function readQuery(url: URL): Record<string, unknown> {
  try {
    return JSON.parse(url.searchParams.get('query') || '{}');
  } catch {
    return {};
  }
}

type TestRole = 'admin' | 'ops' | 'finance' | 'sales';

async function installAuth(page: Page, role: TestRole) {
  const employee = { id: 71, name: '权限测试管理员', role, status: 'active' };
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'customer-content-security-token');
    window.localStorage.setItem('token', 'customer-content-security-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
  return employee;
}

async function navigateWithSearch(page: Page, url: string) {
  await page.evaluate(nextUrl => {
    window.history.pushState({}, '', nextUrl);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, url);
}

async function mockCustomerContentApis(
  page: Page,
  role: TestRole,
  mutations: Array<{ method: string; path: string }>,
  options: { slowCustomerA?: boolean; failServiceSections?: boolean } = {},
) {
  const employee = await installAuth(page, role);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const query = readQuery(url);
    const customerId = Number(query.customer_id || query.id || 0);
    const method = request.method();

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (options.failServiceSections && (path.includes('/entities/service_progresses') || path.includes('/entities/service_tasks'))) {
      return fulfillJson(route, { detail: 'service-board permission required' }, 403);
    }
    if (path.includes('/entities/customer_materials')) {
      if (method !== 'GET') {
        mutations.push({ method, path });
        return fulfillJson(route, materialFor(customerId || 2));
      }
      if (options.slowCustomerA && customerId === 1) await sleep(600);
      return fulfillJson(route, { items: customerId ? [materialFor(customerId)] : [] });
    }
    if (path.includes('/entities/customer_menu_items')) {
      if (method !== 'GET') {
        mutations.push({ method, path });
        return fulfillJson(route, menuItemFor(customerId || 2));
      }
      if (options.slowCustomerA && customerId === 1) await sleep(600);
      return fulfillJson(route, { items: customerId ? [menuItemFor(customerId)] : [] });
    }
    if (path.includes('/entities/customer_ai_copies')) {
      if (method !== 'GET') {
        mutations.push({ method, path });
        return fulfillJson(route, aiCopyFor(customerId || 2));
      }
      if (options.slowCustomerA && customerId === 1) await sleep(600);
      const items = customerId ? [aiCopyFor(customerId)] : [];
      return fulfillJson(route, { items, total: items.length });
    }
    if (path.includes('/entities/customers/') && path.endsWith('/projects')) return fulfillJson(route, { items: [] });
    if (path.includes('/customer-lifecycle/customers/')) return fulfillJson(route, { cycles: [], events: [] });
    if (path.includes('/entities/customers')) {
      const items = customerId ? customers.filter(customer => customer.id === customerId) : customers;
      return fulfillJson(route, { items });
    }
    if (path.includes('/entities/follow_ups')) return fulfillJson(route, {
      items: customerId === 2 ? [{
        id: 9202,
        customer_id: 2,
        contact_method: 'phone',
        content: 'B 客户跟进成功保留',
        stage: 'communicating',
        close_probability: 70,
        employee_name: employee.name,
        created_at: '2026-08-16T09:00:00Z',
      }] : [],
    });
    if (path.includes('/entities/payments')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/customer_contacts')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/employees')) return fulfillJson(route, { items: [employee] });
    if (path.includes('/deductions-monthly')) return fulfillJson(route, []);
    if (path.includes('/commissions/assignment-options')) return fulfillJson(route, { items: [] });
    if (path.includes('/product-plans')) return fulfillJson(route, { business_lines: [], products: [], plans: [] });
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [] });
    return fulfillJson(route, {});
  });
}

test('素材、项目和 AI 文案在 A 慢 B 快切换后只显示当前客户', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const mutations: Array<{ method: string; path: string }> = [];
  await mockCustomerContentApis(page, 'admin', mutations, { slowCustomerA: true });

  await page.goto(`${baseUrl}/customers?detail=1&tab=materials`);
  await page.waitForRequest(request => request.url().includes('/entities/customer_materials') && request.url().includes('%22customer_id%22%3A1'));
  await navigateWithSearch(page, '/customers?detail=2&tab=materials');
  await expect(page.getByText('B 正确素材', { exact: true })).toBeVisible();
  await expect(page.getByText('B 正确项目', { exact: true }).first()).toBeVisible();
  await sleep(750);
  await expect(page.getByText('A 迟到素材', { exact: true })).toHaveCount(0);
  await expect(page.getByText('A 迟到项目', { exact: true })).toHaveCount(0);

  await navigateWithSearch(page, '/customers?detail=1&tab=ai_copy');
  await page.waitForRequest(request => request.url().includes('/entities/customer_ai_copies') && request.url().includes('%22customer_id%22%3A1'));
  await navigateWithSearch(page, '/customers?detail=2&tab=ai_copy');
  await expect(page.getByText('B 当前客户正确内容', { exact: true })).toBeVisible();
  await sleep(750);
  await expect(page.getByText('A 旧内容不得串入', { exact: true })).toHaveCount(0);
  expect(mutations).toEqual([]);
});

test('切换客户会关闭旧素材和旧文案的编辑删除状态，不能触发旧实体写请求', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const mutations: Array<{ method: string; path: string }> = [];
  await mockCustomerContentApis(page, 'admin', mutations);

  await page.goto(`${baseUrl}/customers?detail=1&tab=materials`);
  await expect(page.getByText('A 迟到素材', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑素材：A 迟到素材' }).click();
  await expect(page.getByText('编辑素材', { exact: true })).toBeVisible();
  await navigateWithSearch(page, '/customers?detail=2&tab=materials');
  await expect(page.getByText('编辑素材', { exact: true })).toHaveCount(0);

  await navigateWithSearch(page, '/customers?detail=1&tab=materials');
  await expect(page.getByText('A 迟到素材', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '删除素材：A 迟到素材' }).click();
  await expect(page.getByRole('alertdialog').getByText('确认删除素材')).toBeVisible();
  await navigateWithSearch(page, '/customers?detail=2&tab=materials');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);

  await navigateWithSearch(page, '/customers?detail=1&tab=ai_copy');
  const oldCopy = page.getByTestId('customer-ai-copy-4301');
  await expect(oldCopy).toBeVisible();
  const oldSave = oldCopy.getByRole('button', { name: '保存', exact: true });
  await oldCopy.locator('textarea').fill('只属于 A 的未保存修改');
  await navigateWithSearch(page, '/customers?detail=2&tab=ai_copy');
  await expect(oldCopy).toHaveCount(0);
  await oldSave.click({ timeout: 200 }).catch(() => undefined);
  await expect(page.getByText('B 当前客户正确内容', { exact: true })).toBeVisible();
  expect(mutations.some(item => item.path.includes('/4301'))).toBe(false);
});

test('finance 只能读取，ops 可新增编辑但看不到删除动作', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const mutations: Array<{ method: string; path: string }> = [];
  await mockCustomerContentApis(page, 'finance', mutations);

  await page.goto(`${baseUrl}/customers?detail=2&tab=materials`);
  await expect(page.getByText('B 正确素材', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '上传素材' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '添加链接' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '新增项目' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '编辑素材：B 正确素材' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '删除素材：B 正确素材' })).toHaveCount(0);

  await navigateWithSearch(page, '/customers?detail=2&tab=ai_copy');
  const financeCopy = page.getByTestId('customer-ai-copy-4302');
  await expect(financeCopy).toBeVisible();
  await expect(page.getByText('AI文案生成', { exact: true })).toHaveCount(0);
  await expect(financeCopy.locator('input')).toHaveAttribute('readonly', '');
  await expect(financeCopy.locator('textarea')).toHaveAttribute('readonly', '');
  await expect(financeCopy.getByRole('button', { name: '保存', exact: true })).toHaveCount(0);
  await expect(financeCopy.getByRole('button', { name: /删除AI文案/ })).toHaveCount(0);
  expect(mutations).toEqual([]);
});

test('ops 的素材和 AI 文案写按钮遵循 task_create/task_edit，删除保持隐藏', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const mutations: Array<{ method: string; path: string }> = [];
  await mockCustomerContentApis(page, 'ops', mutations);

  await page.goto(`${baseUrl}/customers?detail=2&tab=materials`);
  await expect(page.getByText('B 正确素材', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '上传素材' })).toBeVisible();
  await expect(page.getByRole('button', { name: '编辑素材：B 正确素材' })).toBeVisible();
  await expect(page.getByRole('button', { name: '删除素材：B 正确素材' })).toHaveCount(0);

  await navigateWithSearch(page, '/customers?detail=2&tab=ai_copy');
  const opsCopy = page.getByTestId('customer-ai-copy-4302');
  await expect(page.getByText('AI文案生成', { exact: true })).toBeVisible();
  await expect(opsCopy.getByRole('button', { name: '保存', exact: true })).toBeVisible();
  await expect(opsCopy.getByRole('button', { name: /删除AI文案/ })).toHaveCount(0);
  expect(mutations).toEqual([]);
});

test('sales 客户详情在服务进度和任务 403 时仍保留其它成功关联资料', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const mutations: Array<{ method: string; path: string }> = [];
  await mockCustomerContentApis(page, 'sales', mutations, { failServiceSections: true });

  await page.goto(`${baseUrl}/customers?detail=2`);
  await expect(page.getByRole('heading', { name: '素材客户 B' })).toBeVisible();
  await expect(page.getByText('B 客户跟进成功保留', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/加载客户详情失败/)).toHaveCount(0);
  expect(mutations).toEqual([]);
});
