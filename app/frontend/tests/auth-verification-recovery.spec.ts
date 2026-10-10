import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 101, name: '验证恢复测试销售', role: 'sales', status: 'active' };

async function seed(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.sessionStorage.setItem('emp_auth_token', 'synthetic-recovery-token');
    window.sessionStorage.setItem('token', 'synthetic-recovery-token');
    window.sessionStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
}

for (const width of [390, 1440]) {
  test(`${width}px 临时身份验证故障保持凭证并提供重新验证`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); await seed(page);
    let available = false;
    let meCalls = 0;
    let loginCalls = 0;
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/emp-auth/me')) {
        meCalls++;
        return route.fulfill({ status: available ? 200 : 503, contentType: 'application/json', body: JSON.stringify(available ? employee : { detail: 'Synthetic temporary failure' }) });
      }
      if (path.endsWith('/emp-auth/login')) loginCalls++;
      const data = path.includes('/app-config') ? { items: {} } : path.includes('/entities/') ? { items: [], total: 0 } : {};
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    });
    await page.goto(`${baseUrl}/more`);
    await expect(page.getByRole('heading', { name: '暂时无法验证登录' })).toBeVisible();
    expect(meCalls).toBe(2);
    await expect(page.getByPlaceholder('请输入密码')).toHaveCount(0);
    expect(await page.evaluate(() => window.sessionStorage.getItem('emp_auth_token'))).toBe('synthetic-recovery-token');
    available = true;
    await page.getByRole('button', { name: '重新验证' }).click();
    await expect(page.getByRole('heading', { name: '暂时无法验证登录' })).toHaveCount(0);
    await expect(page.locator('.t24-system')).toBeVisible();
    expect(loginCalls).toBe(0); expect(meCalls).toBe(3);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test('身份已确认失效时回到登录界面，而不是临时故障恢复卡', async ({ page }) => {
  await seed(page);
  await page.route(/^https?:\/\/[^/]+\/api\//, route => route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic revoked session' }) }));
  await page.goto(`${baseUrl}/more`);
  await expect(page.getByPlaceholder('请输入密码')).toBeVisible();
  await expect(page.getByRole('heading', { name: '暂时无法验证登录' })).toHaveCount(0);
  expect(await page.evaluate(() => window.sessionStorage.getItem('emp_auth_token'))).toBeNull();
});

test('另一个标签登录销售 B 后，迟到的销售 A 登录响应不会覆盖 B', async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let releaseA: () => void = () => {};
  const pendingA = new Promise<void>(resolve => { releaseA = resolve; });
  let aStarted = false;
  let aRefreshCookieWrites = 0;
  const employeeB = { ...employee, id: 102, name: '验证恢复测试销售 B' };
  await context.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/emp-auth/refresh')) return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
    if (path.endsWith('/emp-auth/login')) {
      const isA = request.postDataJSON().email === 'a@example.invalid';
      if (isA) { aStarted = true; await pendingA; }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ token: isA ? 'synthetic-A' : 'synthetic-B', employee: isA ? employee : employeeB }) });
    }
    if (path.endsWith('/emp-auth/set_refresh') && request.headers().authorization === 'Bearer synthetic-A') aRefreshCookieWrites++;
    const data = path.endsWith('/emp-auth/me') ? employeeB : path.includes('/app-config') ? { items: {} } : path.includes('/entities/') ? { items: [], total: 0 } : {};
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(`${baseUrl}/login`);
  await page.getByPlaceholder('请输入邮箱').fill('a@example.invalid');
  await page.getByPlaceholder('请输入密码').fill('synthetic-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect.poll(() => aStarted).toBe(true);
  const second = await context.newPage();
  await second.setViewportSize({ width: 390, height: 844 }); await second.goto(`${baseUrl}/login`);
  await second.getByPlaceholder('请输入邮箱').fill('b@example.invalid');
  await second.getByPlaceholder('请输入密码').fill('synthetic-password');
  await second.getByRole('button', { name: '登录', exact: true }).click();
  await expect(second.locator('.t24-system')).toBeVisible();
  releaseA();
  await expect(page.getByText('登录账号已切换，请重新加载当前页面。', { exact: true })).toBeVisible();
  expect(aRefreshCookieWrites).toBe(0);
  expect(await second.evaluate(() => window.sessionStorage.getItem('emp_auth_token'))).toBe('synthetic-B');
  expect(await second.evaluate(() => JSON.parse(window.localStorage.getItem('emp_auth_data') || '{}').id)).toBe(102);
  await second.close();
});

test('修改密码成功立即撤销本地登录并明确要求重新登录', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const admin = { ...employee, id: 303, role: 'super_admin' };
  await page.addInitScript(({ emp }) => {
    sessionStorage.setItem('emp_auth_token', 'synthetic-password-change-token');
    sessionStorage.setItem('token', 'synthetic-password-change-token');
    sessionStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: admin });
  let changed = false;
  let logoutBearer = '';
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/change-password')) changed = true;
    if (path.endsWith('/logout')) logoutBearer = request.headers().authorization || '';
    const data = path.endsWith('/emp-auth/me') ? admin : path.includes('/app-config') ? { items: {} } : path.includes('/entities/') ? { items: [], total: 0 } : { success: true };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(`${baseUrl}/more`);
  await page.getByRole('button', { name: '查看账户与设置', exact: true }).click();
  await page.getByRole('button', { name: '修改密码', exact: true }).click();
  await page.getByRole('dialog').locator('input').nth(0).fill('synthetic-old-password');
  await page.getByPlaceholder('至少8个字符').fill('synthetic-new-password');
  await page.getByRole('dialog').locator('input').nth(2).fill('synthetic-new-password');
  await page.getByRole('button', { name: '确认修改', exact: true }).click();
  await expect(page.getByPlaceholder('请输入密码')).toBeVisible();
  await expect(page.getByText('密码已修改，请使用新密码重新登录', { exact: true })).toBeVisible();
  expect(changed).toBe(true);
  await expect.poll(() => logoutBearer).toBe('Bearer synthetic-password-change-token');
  expect(await page.evaluate(() => sessionStorage.getItem('emp_auth_token'))).toBeNull();
});
