import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';

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
  sales: ['销售中心', '客户中心'],
  sales_manager: ['销售中心', '客户中心'],
  ops: ['客户中心', '任务交付'],
  design: ['任务交付'],
  finance: ['经营中心', '客户中心', '财务结算'],
  sales_partner: ['我的客户与分润'],
};

type HomeFixtures = {
  tasks?: unknown[];
  customers?: unknown[];
  subscriptions?: unknown[];
  payments?: unknown[];
  salesWorkbench?: unknown;
  salesManagement?: unknown;
  partnerDashboard?: unknown;
};

async function mockAuthenticatedApi(page: Page, role: TestRole, fixtures: HomeFixtures = {}) {
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
    else if (path.endsWith('/sales-leads/workbench/today')) data = fixtures.salesWorkbench || {};
    else if (path.endsWith('/sales-leads/dashboard/management')) data = fixtures.salesManagement || {};
    else if (path.endsWith('/commissions/my-dashboard')) data = fixtures.partnerDashboard || {};
    else if (path.endsWith('/entities/tasks')) data = { items: fixtures.tasks || [], total: (fixtures.tasks || []).length };
    else if (path.endsWith('/entities/customers')) data = { items: fixtures.customers || [], total: (fixtures.customers || []).length };
    else if (path.includes('/entities/subscriptions')) data = { items: fixtures.subscriptions || [], total: (fixtures.subscriptions || []).length };
    else if (path.includes('/entities/payments')) data = { items: fixtures.payments || [], total: (fixtures.payments || []).length };
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

test('管理员在 360px、390px 与 430px 看到六个核心应用且页面无横向溢出', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');

  for (const viewport of [
    { width: 360, height: 800 },
    { width: 390, height: 844 },
    { width: 430, height: 932 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`${baseUrl}/apps`);

    await expect(page.getByRole('heading', { name: '管理工作台' })).toBeVisible();
    await expect(page.getByText(/当前账号.*admin 测试账号.*管理员/)).toBeVisible();
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

test('财务手机底栏的今日与待办进入两个真实可用页面', async ({ page }) => {
  await mockAuthenticatedApi(page, 'finance');
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto(`${baseUrl}/apps`);

  const bottomNav = page.getByRole('navigation', { name: '手机主导航' });
  await bottomNav.getByRole('button', { name: '今日' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/');
  await page.goto(`${baseUrl}/apps`);
  await bottomNav.getByRole('button', { name: '待办' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/finance');
  await expect(page.getByRole('heading', { name: '财务工作台' })).toBeVisible();
});

test('手机业务内页共享深色摘要头、圆角卡片和安全底部留白', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });

  for (const [path, heading] of [
    ['/employees', '员工管理'],
    ['/tasks', '任务协作'],
  ] as const) {
    await page.goto(`${baseUrl}${path}`);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    const pageTitle = page.locator('.app-page-title').first();
    await expect(pageTitle).toHaveCSS('border-radius', '28px');
    await expect(pageTitle).toHaveCSS('background-color', 'rgb(2, 6, 23)');
    await expect(page.locator('.app-page').first()).toHaveCSS('padding-bottom', '92px');
    await expectNoDocumentOverflow(page);
  }
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

test('管理员手机工作台按真实业务分类展示全部功能并可直接进入', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.getByRole('heading', { name: '全部功能' })).toBeVisible();
  const salesFunctions = page.getByRole('region', { name: '销售中心' });
  await expect(salesFunctions.getByRole('button')).toHaveCount(4);
  await expect(salesFunctions.getByRole('button', { name: '打开销售工作台' })).toBeVisible();
  await expect(salesFunctions.getByRole('button', { name: '打开商家池' })).toBeVisible();
  await expect(salesFunctions.getByRole('button', { name: '打开电话销售' })).toBeVisible();
  await expect(salesFunctions.getByRole('button', { name: '打开销售知识' })).toBeVisible();

  await salesFunctions.getByRole('button', { name: '打开电话销售' }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/sales-leads');

  await page.goto(`${baseUrl}/apps`);
  const financeFunctions = page.getByRole('region', { name: '财务结算' });
  await expect(financeFunctions.getByRole('button', { name: '打开财务管理' })).toBeVisible();
  await expect(financeFunctions.getByRole('button', { name: '打开利润预估' })).toBeVisible();
  await expectNoDocumentOverflow(page);
});

test('手机内页可从当前 App 功能菜单进入二级页面', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/finance`);

  await page.getByRole('button', { name: '打开财务结算功能菜单' }).click();
  await expect(page.getByRole('heading', { name: /财务结算/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /财务管理/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /人民币利润预估/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /渠道与分润/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /工资表/ })).toHaveCount(0);
  await page.getByRole('button', { name: /人民币利润预估/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/rmb-profit');
});

test('手机业务页面切换时复用同一个应用外壳', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/finance`);

  await page.locator('.app-shell').evaluate(element => {
    (window as typeof window & { __t24AppShell?: Element }).__t24AppShell = element;
  });
  await page.getByRole('button', { name: '打开财务结算功能菜单' }).click();
  await page.getByRole('button', { name: /人民币利润预估/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/rmb-profit');

  const reused = await page.locator('.app-shell').evaluate(element => (
    (window as typeof window & { __t24AppShell?: Element }).__t24AppShell === element
  ));
  expect(reused).toBe(true);
});

test('手机直接进入受控管理页时仍保留所属 App 导航', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto(`${baseUrl}/settings`);
  await expect(page.getByRole('heading', { name: '全局设置请在电脑端处理' })).toBeVisible();
  await page.getByRole('button', { name: '打开组织设置功能菜单' }).click();
  await expect(page.getByRole('button', { name: /员工管理/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /系统设置/ })).toBeVisible();

  await page.goto(`${baseUrl}/payroll`);
  await expect(page.getByRole('heading', { name: '工资处理请在电脑端完成' })).toBeVisible();
  await page.getByRole('button', { name: '打开财务结算功能菜单' }).click();
  await expect(page.getByRole('button', { name: /财务管理/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /工资表/ })).toBeVisible();
  await expectNoDocumentOverflow(page);
});

test('1440px 网页 App 使用独立应用外壳，不再叠加后台侧栏', async ({ page }) => {
  await mockAuthenticatedApi(page, 'admin');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.locator('aside.app-sidebar')).toHaveCount(0);
  await expect(page.locator('header.app-topbar')).toBeHidden();
  const mobileBottomNav = page.locator('nav[aria-label="手机主导航"]');
  await expect(mobileBottomNav).toHaveCount(1);
  await expect(mobileBottomNav).toBeHidden();
  await expect(page.locator('.mobile-app-home')).toHaveCSS('max-width', '768px');
  await page.getByRole('button', { name: '打开我的账户' }).click();
  await expect(page.getByRole('dialog', { name: '我的账户' })).toBeVisible();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
});

test('财务角色在桌面侧栏可以发现月度扣点比例入口', async ({ page }) => {
  await mockAuthenticatedApi(page, 'finance');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/finance`);

  const sidebar = page.locator('nav.app-sidebar-nav');
  const financeSectionToggle = sidebar.getByRole('button', { name: /(展开|收起)财务与结算/ });
  if (await financeSectionToggle.getAttribute('aria-label') === '展开财务与结算') await financeSectionToggle.click();
  const link = sidebar.getByRole('link', { name: '月度扣点比例' });
  await expect(link).toBeVisible();
  await link.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/settings/deduction');
  await expect(page.getByRole('heading', { name: '月度扣点比例' })).toBeVisible();
});

test('销售账号首页直接显示真实剩余任务、回访数量与下一位客户', async ({ page }) => {
  await mockAuthenticatedApi(page, 'sales', {
    salesWorkbench: {
      remaining_count: 4,
      performance: { callbacks_due: 2 },
      items: [{ task_id: 8, task_status: 'pending', lead: { business_name: '测试美甲店' } }],
    },
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.getByRole('heading', { name: '我的销售工作台' })).toBeVisible();
  await expect(page.getByText('今天还有 4 条销售任务')).toBeVisible();
  await expect(page.getByText(/2 条客户需要回访/)).toBeVisible();
  await expect(page.getByText('下一位：测试美甲店')).toBeVisible();
  await expect(page.getByRole('button', { name: '查看待办，6 项未处理' })).toBeVisible();
});

test('运营账号首页只汇总自己的逾期任务并提供继续处理入口', async ({ page }) => {
  await mockAuthenticatedApi(page, 'ops', {
    tasks: [
      { id: 11, title: '补充客户月报', assignee_name: 'ops 测试账号', customer_name: 'A 客户', status: 'pending', due_date: '2020-01-01', updated_at: '2026-08-19' },
      { id: 12, title: '其他人的任务', assignee_name: '另一位员工', status: 'pending', due_date: '2020-01-01' },
    ],
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.getByRole('heading', { name: '我的运营工作台' })).toBeVisible();
  await expect(page.getByText('1 项运营任务已逾期')).toBeVisible();
  await expect(page.getByRole('region', { name: '今天先处理' }).getByText('补充客户月报')).toBeVisible();
  await expect(page.getByText('其他人的任务')).toHaveCount(0);
});

test('财务账号首页汇总待收款与续费风险', async ({ page }) => {
  await mockAuthenticatedApi(page, 'finance', {
    subscriptions: [
      { id: 1, customer_id: 1, package_name: '基础版', status: 'expiring_soon' },
      { id: 2, customer_id: 2, package_name: '高级版', status: 'active' },
    ],
    payments: [{ id: 1, outstanding_amount: 300 }, { id: 2, outstanding_amount: 0 }],
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.getByRole('heading', { name: '财务今日工作台' })).toBeVisible();
  await expect(page.getByText('2 项财务事项需要核对')).toBeVisible();
  await expect(page.getByText('1 笔待收款 · 1 个续费风险')).toBeVisible();
});

test('销售合伙人首页显示客户续费与分润状态', async ({ page }) => {
  await mockAuthenticatedApi(page, 'sales_partner', {
    partnerDashboard: {
      summary: {
        renewal_attention_count: 3,
        currencies: { USD: { payable: 2 } },
      },
    },
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/apps`);

  await expect(page.getByRole('heading', { name: '客户与分润工作台' })).toBeVisible();
  await expect(page.getByText('3 位合作客户需要关注')).toBeVisible();
  await expect(page.getByText('当前有 2 笔分润进入可结算状态。')).toBeVisible();
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
