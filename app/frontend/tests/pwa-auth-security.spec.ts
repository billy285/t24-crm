import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';

type Role = 'super_admin' | 'admin' | 'finance' | 'sales' | 'sales_partner';

async function mockApi(page: Page, role: Role = 'super_admin') {
  const employee = { id: 41, name: '移动安全测试账号', role, status: 'active' };

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let data: unknown = {};

    if (path.endsWith('/emp-auth/login')) data = { token: 'secure-mobile-token', employee };
    else if (path.endsWith('/emp-auth/set_refresh')) data = { success: true };
    else if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/deductions-monthly/default')) data = { rate: 0.15 };
    else if (path.endsWith('/deductions-monthly')) data = [];
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path.includes('/entities/')) data = { items: [], total: 0 };

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });
  });

  return employee;
}

async function seedAuthenticatedUser(page: Page, role: Role) {
  const employee = { id: 51, name: `${role}测试账号`, role, status: 'active' };
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'seed-token');
    window.localStorage.setItem('token', 'seed-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
  await mockApi(page, role);
}

async function login(page: Page, rememberMe: boolean) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/login`);
  const remember = page.getByRole('checkbox', { name: '保持登录' });
  if (rememberMe) await remember.check();
  else await remember.uncheck();
  await page.getByPlaceholder('请输入邮箱').fill('owner@example.com');
  await page.getByPlaceholder('请输入密码').fill('password');
  await page.getByRole('button', { name: '登录' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/apps');
}

function ownerPortalPayload(partnerId: number) {
  const partner = partnerId === 1
    ? { id: 1, name: 'A Partner', partner_code: 'P001', status: 'suspended', joined_at: '2026-01-01' }
    : { id: 2, name: 'B Partner', partner_code: 'P002', status: 'active', joined_at: '2026-02-01' };
  return {
    portal_mode: 'owner_readonly',
    available_partners: [
      { id: 1, name: 'A Partner', partner_code: 'P001', status: 'suspended' },
      { id: 2, name: 'B Partner', partner_code: 'P002', status: 'active' },
    ],
    partner,
    summary: {
      active_customer_count: 0,
      cooperation_customer_count: 0,
      renewal_attention_count: 0,
      stopped_customer_count: 0,
      ledger_count: 0,
      currencies: {},
      status_updated_at: '2026-08-16T00:00:00Z',
    },
    agreements: [],
    customers: [],
    entries: [],
  };
}

test('手机登录的密码显隐与保持登录均提供完整触控区', async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/login`);

  const passwordInput = page.getByPlaceholder('请输入密码');
  const visibilityButton = page.getByRole('button', { name: '显示密码' });
  const visibilityBox = await visibilityButton.boundingBox();
  expect(visibilityBox?.width).toBeGreaterThanOrEqual(44);
  expect(visibilityBox?.height).toBeGreaterThanOrEqual(44);

  await visibilityButton.click();
  await expect(passwordInput).toHaveAttribute('type', 'text');
  await expect(page.getByRole('button', { name: '隐藏密码' })).toBeVisible();

  const rememberLabel = page.locator('label').filter({ hasText: '保持登录' });
  const rememberBox = await rememberLabel.boundingBox();
  expect(rememberBox?.height).toBeGreaterThanOrEqual(44);
});

test('未勾选保持登录时令牌和员工资料只进入当前会话，退出后全部清除', async ({ page }) => {
  await mockApi(page);
  await login(page, false);
  let observePostLogoutRefresh = false;
  let postLogoutRefreshRequests = 0;
  page.on('request', request => {
    if (observePostLogoutRefresh && new URL(request.url()).pathname.endsWith('/emp-auth/refresh')) {
      postLogoutRefreshRequests += 1;
    }
  });

  const stored = await page.evaluate(() => ({
    localToken: window.localStorage.getItem('emp_auth_token'),
    localSdkToken: window.localStorage.getItem('token'),
    localEmployee: window.localStorage.getItem('emp_auth_data'),
    sessionToken: window.sessionStorage.getItem('emp_auth_token'),
    sessionSdkToken: window.sessionStorage.getItem('token'),
    sessionEmployee: window.sessionStorage.getItem('emp_auth_data'),
  }));
  expect(stored.localToken).toBeNull();
  expect(stored.localSdkToken).toBeNull();
  expect(stored.localEmployee).toBeNull();
  expect(stored.sessionToken).toBe('secure-mobile-token');
  expect(stored.sessionSdkToken).toBe('secure-mobile-token');
  expect(stored.sessionEmployee).toContain('移动安全测试账号');

  await page.getByRole('navigation', { name: '手机主导航' }).getByRole('button', { name: '我的' }).click();
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect.poll(() => page.evaluate(() => ({
    local: window.localStorage.getItem('emp_auth_token'),
    session: window.sessionStorage.getItem('emp_auth_token'),
    localEmployee: window.localStorage.getItem('emp_auth_data'),
    sessionEmployee: window.sessionStorage.getItem('emp_auth_data'),
  }))).toEqual({ local: null, session: null, localEmployee: null, sessionEmployee: null });

  observePostLogoutRefresh = true;
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
  expect(postLogoutRefreshRequests).toBe(0);
});

test('勾选保持登录时用 HttpOnly 刷新机制且不持久化浏览器可读令牌', async ({ page }) => {
  await mockApi(page);
  await login(page, true);

  const stored = await page.evaluate(() => ({
    token: window.localStorage.getItem('emp_auth_token'),
    sdkToken: window.localStorage.getItem('token'),
    employee: window.localStorage.getItem('emp_auth_data'),
    remembered: window.localStorage.getItem('emp_auth_remembered'),
    sessionToken: window.sessionStorage.getItem('emp_auth_token'),
    sessionSdkToken: window.sessionStorage.getItem('token'),
  }));
  expect(stored.token).toBeNull();
  expect(stored.sdkToken).toBeNull();
  expect(stored.employee).toContain('移动安全测试账号');
  expect(stored.remembered).toBe('1');
  expect(stored.sessionToken).toBe('secure-mobile-token');
  expect(stored.sessionSdkToken).toBe('secure-mobile-token');
});

test('旧版本长期存储中的访问令牌会迁移到当前会话', async ({ page }) => {
  await seedAuthenticatedUser(page, 'super_admin');
  await page.goto(`${baseUrl}/apps`);
  await expect(page.getByRole('button', { name: '销售中心：线索、拨打与跟进' })).toBeVisible();

  const stored = await page.evaluate(() => ({
    localToken: window.localStorage.getItem('emp_auth_token'),
    localSdkToken: window.localStorage.getItem('token'),
    sessionToken: window.sessionStorage.getItem('emp_auth_token'),
    sessionSdkToken: window.sessionStorage.getItem('token'),
  }));
  expect(stored).toEqual({
    localToken: null,
    localSdkToken: null,
    sessionToken: 'seed-token',
    sessionSdkToken: 'seed-token',
  });
});

test('修改密码在客户端与服务端统一要求至少8个字符', async ({ page }) => {
  await seedAuthenticatedUser(page, 'super_admin');
  await page.setViewportSize({ width: 390, height: 844 });
  let changePasswordRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/emp-auth/change-password')) changePasswordRequests += 1;
  });

  await page.goto(`${baseUrl}/apps`);
  await page.getByRole('navigation', { name: '手机主导航' }).getByRole('button', { name: '我的' }).click();
  await page.getByRole('button', { name: '修改密码' }).click();
  const dialog = page.getByRole('dialog', { name: '修改密码' });
  const passwordInputs = dialog.locator('input[type="password"]');
  await passwordInputs.nth(0).fill('current-password');
  await passwordInputs.nth(1).fill('1234567');
  await passwordInputs.nth(2).fill('1234567');
  await dialog.getByRole('button', { name: '确认修改' }).click();

  await expect(page.getByText('新密码至少8个字符')).toBeVisible();
  expect(changePasswordRequests).toBe(0);
});

for (const role of ['super_admin', 'admin', 'finance'] as const) {
  test(`${role} 可以在电脑端打开月度扣点页面`, async ({ page }) => {
    await seedAuthenticatedUser(page, role);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${baseUrl}/settings/deduction`);
    await expect(page.getByRole('heading', { name: '月度扣点比例' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '无权限访问' })).toHaveCount(0);
  });
}

test('普通销售不能打开月度扣点页面', async ({ page }) => {
  await seedAuthenticatedUser(page, 'sales');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/settings/deduction`);
  await expect(page.getByRole('heading', { name: '无权限访问' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '月度扣点比例' })).toHaveCount(0);
});

test('手机端月度扣点只提示电脑处理且不加载财务配置', async ({ page }) => {
  const deductionRequests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/v1/deductions-monthly')) deductionRequests.push(path);
  });
  await seedAuthenticatedUser(page, 'super_admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/settings/deduction`);

  await expect(page.getByRole('heading', { name: '月度扣点比例设置' })).toBeVisible();
  await expect(page.getByText(/请在电脑端进入系统处理/)).toBeVisible();
  await expect(page.getByRole('button', { name: /保存默认|新增月份|导入/ })).toHaveCount(0);
  await expect(page.locator('input')).toHaveCount(0);
  expect(deductionRequests).toEqual([]);
});

test('老板以只读模式查看并切换单个合伙人门户', async ({ page }) => {
  await seedAuthenticatedUser(page, 'super_admin');
  await page.route(/\/api\/v1\/commissions\/my-dashboard/, async route => {
    const requestedId = Number(new URL(route.request().url()).searchParams.get('partner_id') || 2);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(ownerPortalPayload(requestedId)),
    });
  });

  await page.goto(`${baseUrl}/partner-portal`);
  await expect(page.getByText('老板只读视图')).toBeVisible();
  await expect(page.getByText(/不提供新增、修改或结算操作/)).toBeVisible();
  await expect(page.locator('select')).toHaveValue('2');
  await expect(page.getByText(/渠道编号 P002/)).toBeVisible();
  await page.locator('select').selectOption('1');
  await expect(page.getByText(/渠道编号 P001/)).toBeVisible();
  await expect(page.getByRole('button', { name: /^(新增|修改|结算)$/ })).toHaveCount(0);
});

test('老板切换合伙人失败时保持上一对象并明确报错', async ({ page }) => {
  await seedAuthenticatedUser(page, 'super_admin');
  await page.route(/\/api\/v1\/commissions\/my-dashboard/, async route => {
    const requestedId = Number(new URL(route.request().url()).searchParams.get('partner_id') || 2);
    if (requestedId === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '合伙人数据暂不可用' }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ownerPortalPayload(2)) });
  });

  await page.goto(`${baseUrl}/partner-portal`);
  await expect(page.locator('select')).toHaveValue('2');
  await expect(page.getByText(/渠道编号 P002/)).toBeVisible();
  await page.locator('select').selectOption('1');

  await expect(page.getByRole('alert')).toContainText('当前继续显示 B Partner 的上一次成功数据');
  await expect(page.locator('select')).toHaveValue('2');
  await expect(page.getByText(/渠道编号 P002/)).toBeVisible();
  await expect(page.getByText(/渠道编号 P001/)).toHaveCount(0);
});

test('合伙人切换期间自动刷新不会发起旧对象并发请求', async ({ page }) => {
  await seedAuthenticatedUser(page, 'super_admin');
  const requestedIds: number[] = [];
  await page.route(/\/api\/v1\/commissions\/my-dashboard/, async route => {
    const requestedId = Number(new URL(route.request().url()).searchParams.get('partner_id') || 2);
    requestedIds.push(requestedId);
    if (requestedId === 1) await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ownerPortalPayload(requestedId)) });
  });

  await page.goto(`${baseUrl}/partner-portal`);
  await expect(page.locator('select')).toHaveValue('2');
  await page.locator('select').selectOption('1');
  await page.evaluate(() => window.dispatchEvent(new Event('t24:business-data-refresh')));

  await expect(page.locator('select')).toHaveValue('1');
  await expect(page.getByText(/渠道编号 P001/)).toBeVisible();
  expect(requestedIds).toEqual([2, 1]);
});

test('管理员不能进入老板只读合伙人门户', async ({ page }) => {
  await seedAuthenticatedUser(page, 'admin');
  await page.goto(`${baseUrl}/partner-portal`);
  await expect(page.getByRole('heading', { name: '无权限访问' })).toBeVisible();
});

test('销售合伙人使用空配置启动且清除同设备遗留的内部配置缓存', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('crm_company_info', JSON.stringify({ name: '内部公司资料' }));
    window.localStorage.setItem('crm_security_config', JSON.stringify({ passwordViewRoles: ['sales_partner'] }));
    window.localStorage.setItem('crm_notification_config', JSON.stringify({ notifEmail: 'private@example.com' }));
    window.localStorage.setItem('crm_export_config', JSON.stringify({ includeNotes: true }));
  });
  await seedAuthenticatedUser(page, 'sales_partner');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.getByRole('button', { name: /我的客户与分润/ })).toBeVisible();
  await expect.poll(() => page.evaluate(() => ({
    company: window.localStorage.getItem('crm_company_info'),
    security: window.localStorage.getItem('crm_security_config'),
    notification: window.localStorage.getItem('crm_notification_config'),
    exportConfig: window.localStorage.getItem('crm_export_config'),
  }))).toEqual({ company: null, security: null, notification: null, exportConfig: null });
});

test('手机我的账户可以触发系统 PWA 安装提示', async ({ page }) => {
  await seedAuthenticatedUser(page, 'super_admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);
  await page.evaluate(() => {
    const installEvent = new Event('beforeinstallprompt', { cancelable: true });
    Object.defineProperties(installEvent, {
      prompt: {
        value: async () => {
          (window as Window & { __pwaPrompted?: number }).__pwaPrompted = 1;
        },
      },
      userChoice: { value: Promise.resolve({ outcome: 'accepted', platform: 'web' }) },
    });
    window.dispatchEvent(installEvent);
  });

  await page.getByRole('navigation', { name: '手机主导航' }).getByRole('button', { name: '我的' }).click();
  await page.getByRole('button', { name: '安装 T24 OS 到手机' }).click();
  await expect.poll(() => page.evaluate(() => (window as Window & { __pwaPrompted?: number }).__pwaPrompted || 0)).toBe(1);
});

test('manifest 与页面声明可安装且禁止搜索引擎索引', async ({ page, request }) => {
  const manifestResponse = await request.get(`${baseUrl}/manifest.webmanifest`);
  expect(manifestResponse.ok()).toBeTruthy();
  const manifest = await manifestResponse.json();
  expect(manifest).toMatchObject({
    name: 'T24 Marketing 客户管理系统',
    short_name: 'T24 OS',
    start_url: '/apps',
    display: 'standalone',
  });
  const workerResponse = await request.get(`${baseUrl}/sw.js`);
  const workerSource = await workerResponse.text();
  expect(workerSource).toContain("request.mode !== 'navigate'");
  expect(workerSource).toContain("url.pathname.startsWith('/api/')");
  expect(workerSource).not.toContain('caches.put(');

  await page.goto(`${baseUrl}/login`);
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/manifest.webmanifest');
  await expect(page.locator('meta[name="viewport"]')).toHaveAttribute('content', /viewport-fit=cover/);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
});
