import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5215';
const cookieName = 'emp_refresh_token';
const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
};
const cookie = (value: string) => `${cookieName}=${value}; HttpOnly; SameSite=Lax; Path=/${value ? '' : '; Max-Age=0'}`;
async function reply(route: Route, data: unknown, setCookie?: string) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data), headers: setCookie ? { 'Set-Cookie': setCookie } : {} });
}
async function fixturePage(context: BrowserContext, fallback = false) {
  const page = await context.newPage();
  if (fallback) await page.addInitScript(() => Object.defineProperty(navigator, 'locks', { value: undefined, configurable: true }));
  await page.route('**/auth-cookie-fixture', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Isolated Cookie fixture</title>' }));
  await page.goto(`${baseUrl}/auth-cookie-fixture`);
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path);
    (window as any).cookieFixture = {
      api: await load('/src/lib/api.ts'), auth: await load('/src/lib/auth-storage.ts'),
    };
  });
  return page;
}
async function intent(page: Page, token?: string) {
  await page.evaluate(value => {
    const { auth, api } = (window as any).cookieFixture;
    auth.beginAuthSession();
    if (value) { auth.storeToken(value, 'session'); api.refreshClientAuth(); }
  }, token);
}
async function startControl(page: Page, path: string, bearer?: string, result = 'result') {
  await page.evaluate(({ endpoint, token, name }) => {
    const { api } = (window as any).cookieFixture;
    (window as any)[name] = undefined;
    void api.client.apiCall.invoke({
      url: `/api/v1/emp-auth/${endpoint}`, method: 'POST',
      options: { withCredentials: true, headers: token ? { Authorization: `Bearer ${token}` } : {} },
    }).then(() => { (window as any)[name] = 'ok'; }, (error: Error) => { (window as any)[name] = error.name; });
  }, { endpoint: path, token: bearer, name: result });
}
async function result(page: Page, name = 'result') {
  await expect.poll(() => page.evaluate(key => (window as any)[key], name)).toBeDefined();
  return page.evaluate(key => (window as any)[key], name);
}
async function assertCookieB(context: BrowserContext) {
  const saved = (await context.cookies(baseUrl)).find(item => item.name === cookieName);
  expect(saved?.value).toBe('synthetic-B');
  expect(saved?.httpOnly).toBe(true);
}

// The real Chromium cookie jar processes Set-Cookie. No production host or
// account is used; only the actual API modules, SDK, and browser cookie transport.
for (const previous of ['logout', 'set_refresh'] as const) {
  test(`跨标签迟到 ${previous} Cookie 响应先落地，再建立最后销售 B 的 Cookie`, async ({ context }) => {
    const held = deferred(); const events: string[] = [];
    await context.addCookies([{ name: cookieName, value: 'synthetic-A', url: baseUrl, httpOnly: true }]);
    await context.route('**/api/v1/emp-auth/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const isB = request.headers().authorization === 'Bearer synthetic-B';
      events.push(isB ? 'B' : 'A');
      if (!isB) { await held.promise; await reply(route, {}, cookie(path.endsWith('/logout') ? '' : 'synthetic-A')); }
      else await reply(route, {}, cookie('synthetic-B'));
    });
    const first = await fixturePage(context); await intent(first, 'synthetic-A');
    await startControl(first, previous, 'synthetic-A'); await expect.poll(() => events).toEqual(['A']);
    const second = await fixturePage(context);
    expect(await second.evaluate(() => Boolean(navigator.locks))).toBe(true);
    await intent(second); await startControl(second, 'set_refresh', 'synthetic-B');
    await second.waitForTimeout(120); expect(events).toEqual(['A']);
    held.resolve();
    expect(await result(first)).toBe(previous === 'logout' ? 'ok' : 'AuthSessionChangedError');
    expect(await result(second)).toBe('ok'); expect(events).toEqual(['A', 'B']);
    await assertCookieB(context);
  });
}

test('迟到 refresh 保持锁到原生 Cookie 已处理，无法覆盖随后销售 B', async ({ context }) => {
  const held = deferred(); const events: string[] = [];
  await context.route('**/api/v1/emp-auth/**', async route => {
    const refresh = new URL(route.request().url()).pathname.endsWith('/refresh');
    events.push(refresh ? 'A-refresh' : 'B-cookie');
    if (refresh) { await held.promise; await reply(route, { access_token: 'synthetic-late-A' }, cookie('synthetic-A')); }
    else await reply(route, {}, cookie('synthetic-B'));
  });
  const first = await fixturePage(context); await intent(first, 'synthetic-A');
  await first.evaluate(() => {
    void (window as any).cookieFixture.api.refreshAccessToken().then((token: string | null) => { (window as any).refreshResult = token === null ? 'discarded' : token; });
  });
  await expect.poll(() => events).toEqual(['A-refresh']);
  const second = await fixturePage(context); await intent(second); await startControl(second, 'set_refresh', 'synthetic-B');
  await second.waitForTimeout(120); expect(events).toEqual(['A-refresh']); held.resolve();
  expect(await result(first, 'refreshResult')).toBe('discarded'); expect(await result(second)).toBe('ok');
  expect(events).toEqual(['A-refresh', 'B-cookie']); await assertCookieB(context);
});

test('无 Web Locks 时本标签队列跳过过期 Cookie 请求，并保留最终 B Cookie', async ({ context }) => {
  const held = deferred(); const events: string[] = [];
  await context.route('**/api/v1/emp-auth/**', async route => {
    const bearer = route.request().headers().authorization;
    events.push(bearer || '');
    if (events.length === 1) await held.promise;
    await reply(route, {}, cookie(bearer === 'Bearer synthetic-B' ? 'synthetic-B' : 'synthetic-A'));
  });
  const page = await fixturePage(context, true); await intent(page, 'synthetic-A');
  await startControl(page, 'set_refresh', 'synthetic-A', 'first'); await expect.poll(() => events.length).toBe(1);
  await startControl(page, 'logout', 'synthetic-A', 'obsolete');
  await intent(page); await startControl(page, 'set_refresh', 'synthetic-B', 'last');
  held.resolve();
  expect(await result(page, 'first')).toBe('AuthSessionChangedError');
  expect(await result(page, 'obsolete')).toBe('AuthSessionChangedError'); expect(await result(page, 'last')).toBe('ok');
  expect(events).toEqual(['Bearer synthetic-A', 'Bearer synthetic-B']); await assertCookieB(context);
});

test('最后点击销售 B 登录优先于先返回 A；真实 Cookie 与本地身份均为 B', async ({ page, context }) => {
  const a = deferred(); const b = deferred(); const loginStarts: string[] = []; const cookieWrites: string[] = [];
  const employeeA = { id: 101, name: 'Synthetic Sales A', role: 'sales', status: 'active' };
  const employeeB = { ...employeeA, id: 102, name: 'Synthetic Sales B' };
  await context.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path.endsWith('/emp-auth/refresh')) return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
    if (path.endsWith('/emp-auth/login')) {
      const isA = request.postDataJSON().email === 'a@example.invalid'; loginStarts.push(isA ? 'A' : 'B');
      await (isA ? a : b).promise;
      return reply(route, { token: isA ? 'synthetic-A' : 'synthetic-B', employee: isA ? employeeA : employeeB });
    }
    if (path.endsWith('/emp-auth/set_refresh')) {
      const isA = request.headers().authorization === 'Bearer synthetic-A'; cookieWrites.push(isA ? 'A' : 'B');
      return reply(route, {}, cookie(isA ? 'synthetic-A' : 'synthetic-B'));
    }
    return reply(route, path.endsWith('/emp-auth/me') ? employeeB : path.includes('/app-config') ? { items: {} } : { items: [], total: 0 });
  });
  await page.goto(`${baseUrl}/login`); await page.getByPlaceholder('请输入邮箱').fill('a@example.invalid');
  await page.getByPlaceholder('请输入密码').fill('synthetic-password'); await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect.poll(() => loginStarts).toEqual(['A']);
  const second = await context.newPage(); await second.goto(`${baseUrl}/login`);
  await second.getByPlaceholder('请输入邮箱').fill('b@example.invalid'); await second.getByPlaceholder('请输入密码').fill('synthetic-password');
  await second.getByRole('button', { name: '登录', exact: true }).click(); await expect.poll(() => loginStarts).toEqual(['A', 'B']);
  a.resolve(); await expect(page.getByText('登录账号已切换，请重新加载当前页面。', { exact: true })).toBeVisible();
  expect(cookieWrites).toEqual([]); b.resolve(); await expect(second.locator('.t24-system')).toBeVisible();
  expect(cookieWrites).toEqual(['B']); await assertCookieB(context);
  expect(await second.evaluate(() => sessionStorage.getItem('emp_auth_token'))).toBe('synthetic-B');
  expect(await second.evaluate(() => JSON.parse(localStorage.getItem('emp_auth_data') || '{}').id)).toBe(102);
});
