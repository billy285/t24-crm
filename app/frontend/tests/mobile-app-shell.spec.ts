import { expect, test, type Page } from '@playwright/test';

const baseUrl = 'http://127.0.0.1:5173';

type TestRole = 'admin' | 'sales' | 'sales_manager' | 'sales_partner' | 'ops' | 'design' | 'finance';

const standardApps = [
  { label: '经营中心', accessibleName: '经营中心：经营、现金与里程碑', path: '/' },
  { label: '销售中心', accessibleName: '销售中心：线索、拨打与跟进', path: '/sales-workbench' },
  { label: '客户中心', accessibleName: '客户中心：客户 360 与生命周期', path: '/customers' },
  { label: '任务交付', accessibleName: '任务交付：任务、服务与回访', path: '/operations-workbench' },
  { label: '财务结算', accessibleName: '财务结算：收款、续费与分润', path: '/finance' },
  { label: '组织设置', accessibleName: '组织设置：员工、权限与系统', path: '/employees' },
] as const;

const partnerApp = {
  label: '我的客户与分润',
  accessibleName: '我的客户与分润：客户合作、续费与分润状态',
  path: '/partner-portal',
} as const;

const allApps = [...standardApps, partnerApp];

const roleVisibleApps: Record<TestRole, readonly string[]> = {
  admin: standardApps.map(app => app.label),
  sales: ['销售中心'],
  sales_manager: ['销售中心'],
  ops: ['客户中心', '任务交付'],
  design: ['经营中心', '任务交付'],
  finance: ['经营中心', '客户中心', '任务交付', '财务结算'],
  sales_partner: ['我的客户与分润'],
};

async function mockAuthenticatedApi(page: Page, role: TestRole) {
  const employee = {
    id: role === 'admin' ? 1 : role.length + 10,
    name: `${role} 测试账号`,
    role,
    status: 'active',
  };

  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'mobile-app-shell-token');
    window.localStorage.setItem('token', 'mobile-app-shell-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};

    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path.includes('/entities/')) data = { items: [], total: 0 };

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });
  });
}

async function mockMobileLoginApi(page: Page, role: TestRole = 'admin') {
  const employee = {
    id: 91,
    name: '手机登录测试账号',
    role,
    status: 'active',
  };

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};

    if (path.endsWith('/emp-auth/login')) data = { token: 'mobile-login-token', employee };
    else if (path.endsWith('/emp-auth/set_refresh')) data = { success: true };
    else if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path.includes('/entities/')) data = { items: [], total: 0 };

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });
  });
}

function appRegion(page: Page) {
  return page.getByRole('region', { name: '工作应用' });
}

async function expectNoDocumentOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));

  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}

test('管理员在 360px 与 390px 均看到六个应用且页面无横向溢出', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');

  for (const viewport of [
    { width: 360, height: 800 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`${baseUrl}/apps`);

    await expect(page.getByRole('heading', { name: 'T24 OS' })).toBeVisible();
    await expect(appRegion(page).getByRole('button')).toHaveCount(6);
    for (const app of standardApps) {
      await expect(appRegion(page).getByRole('button', { name: app.accessibleName })).toBeVisible();
    }
    await expect(page.getByRole('navigation', { name: '手机主导航' })).toBeVisible();
    await expectNoDocumentOverflow(page);
  }
});

for (const role of ['sales', 'sales_manager', 'ops', 'design', 'finance', 'sales_partner'] as const) {
  test(`${role} 只显示有权限的手机应用入口`, async ({ page }) => {
    await mockAuthenticatedApi(page, role);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/apps`);

    const visibleLabels = roleVisibleApps[role];
    await expect(appRegion(page).getByRole('button')).toHaveCount(visibleLabels.length);

    for (const app of allApps) {
      const card = appRegion(page).getByRole('button', { name: app.accessibleName });
      if (visibleLabels.includes(app.label)) {
        await expect(card).toBeVisible();
      } else {
        await expect(card).toHaveCount(0);
      }
    }

    if (role === 'sales_partner') {
      const bottomNav = page.getByRole('navigation', { name: '手机主导航' });
      await expect(bottomNav.getByRole('button')).toHaveCount(3);
      await expect(bottomNav.getByRole('button', { name: '客户与分润' })).toBeVisible();
      await expect(bottomNav.getByRole('button', { name: '今日' })).toHaveCount(0);
      await expect(bottomNav.getByRole('button', { name: '待办' })).toHaveCount(0);
    }
  });
}

test('销售手机底栏的今日与待办进入不同工作位置', async ({ page }) => {
  await mockAuthenticatedApi(page, 'sales');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await page.getByRole('navigation', { name: '手机主导航' }).getByRole('button', { name: '今日' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/sales-workbench');
  await page.goto(`${baseUrl}/apps`);
  await page.getByRole('navigation', { name: '手机主导航' }).getByRole('button', { name: '待办' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/sales-leads');
});

test('管理员应用卡进入各自已有业务路径', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });

  for (const app of standardApps) {
    await page.goto(`${baseUrl}/apps`);
    await appRegion(page).getByRole('button', { name: app.accessibleName }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe(app.path);
  }
});

test('手机内页可从当前 App 功能菜单进入二级页面', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/finance`);

  await page.getByRole('button', { name: '打开财务结算功能菜单' }).click();
  await expect(page.getByRole('heading', { name: /财务结算/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /财务管理/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /人民币利润预估/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /渠道与分润/ })).toBeVisible();
  await page.getByRole('button', { name: /工资表/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/payroll');
});

test('1440px 桌面保留侧栏并隐藏手机底栏', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.locator('aside.app-sidebar')).toBeVisible();
  await expect(page.locator('nav.app-sidebar-nav')).toBeVisible();
  const mobileBottomNav = page.locator('nav[aria-label="手机主导航"]');
  await expect(mobileBottomNav).toHaveCount(1);
  await expect(mobileBottomNav).toBeHidden();
  await expect(page.locator('.mobile-app-home')).toHaveCSS('max-width', '512px');
});

test('无 returnTo 的任务详情始终有固定返回入口', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/tasks?task_id=99&view=system`);

  await expect(page.getByRole('navigation', { name: '手机主导航' })).toHaveCount(0);
  await page.getByRole('button', { name: '返回上一工作位置' }).click();
  await expect.poll(() => {
    const current = new URL(page.url());
    return { pathname: current.pathname, view: current.searchParams.get('view'), taskId: current.searchParams.get('task_id') };
  }).toEqual({ pathname: '/tasks', view: 'system', taskId: null });
});

test('手机登录后完整保留客户详情深链接参数', async ({ page }) => {
  await mockMobileLoginApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const returnTo = '/tasks?task_id=12&view=system';
  await page.goto(`${baseUrl}/customers?detail=27&tab=renewals&returnTo=${encodeURIComponent(returnTo)}`);

  await page.getByPlaceholder('请输入邮箱').fill('admin@example.com');
  await page.getByPlaceholder('请输入密码').fill('password');
  await page.getByRole('button', { name: '登录' }).click();

  await expect.poll(() => {
    const current = new URL(page.url());
    return {
      pathname: current.pathname,
      detail: current.searchParams.get('detail'),
      tab: current.searchParams.get('tab'),
      returnTo: current.searchParams.get('returnTo'),
    };
  }).toEqual({ pathname: '/customers', detail: '27', tab: 'renewals', returnTo });

  await page.getByRole('button', { name: '返回上一工作位置' }).click();
  await expect.poll(() => {
    const current = new URL(page.url());
    return { pathname: current.pathname, taskId: current.searchParams.get('task_id'), view: current.searchParams.get('view') };
  }).toEqual({ pathname: '/tasks', taskId: '12', view: 'system' });
});

test('手机登录拒绝外部重定向并回到应用中心', async ({ page }) => {
  await mockMobileLoginApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/login`);
  await page.evaluate(() => {
    window.history.replaceState({
      ...(window.history.state || {}),
      usr: { from: { pathname: '//evil.example' } },
    }, '', '/login');
  });
  await page.reload();

  await page.getByPlaceholder('请输入邮箱').fill('admin@example.com');
  await page.getByPlaceholder('请输入密码').fill('password');
  await page.getByRole('button', { name: '登录' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/apps');
});

test('销售深链登录无权财务页时不挂载财务数据页面', async ({ page }) => {
  const financeRequests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.includes('/finance/')) financeRequests.push(path);
  });
  await mockMobileLoginApi(page, 'sales');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/finance`);

  await page.getByPlaceholder('请输入邮箱').fill('sales@example.com');
  await page.getByPlaceholder('请输入密码').fill('password');
  await page.getByRole('button', { name: '登录' }).click();

  await expect(page.getByRole('heading', { name: '无权限访问' })).toBeVisible();
  expect(financeRequests).toEqual([]);
});
