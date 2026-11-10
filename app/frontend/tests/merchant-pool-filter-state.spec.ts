import { expect, test, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5187';
const manager = { id: 10, name: '合成筛选测试主管', role: 'sales_manager', status: 'active' };
const record = { id: 1, business_name: '合成中部门店', phone: '+12145550123', country: 'US', industry: '美业', state: 'TX', city: 'Dallas', data_source: 'csv', collected_at: '2026-11-09T02:00:00Z', pool_status: 'pending', timezone: 'America/Chicago', timezone_group: 'central', timezone_basis: 'address_city', timezone_needs_confirmation: true, prospect_quality: { status: 'pending', revision: 0 } };
async function json(route: Route, data: unknown) { await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) }); }

for (const width of [855, 390]) test(`筛选失败清除旧列表并在当前时区重试 ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 824 });
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'synthetic-filter-state-token');
    localStorage.setItem('token', 'synthetic-filter-state-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, manager);
  let releaseFailure!: () => void;
  const failureGate = new Promise<void>(resolve => { releaseFailure = resolve; });
  let easternAttempts = 0;
  const queries: URLSearchParams[] = [], writes: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (request.method() !== 'GET') { writes.push(path); return json(route, {}); }
    if (path.endsWith('/emp-auth/me')) return json(route, manager);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.endsWith('/sales-leads/assignees')) return json(route, [{ id: 11, name: '合成销售' }]);
    if (path === '/api/v1/merchant-pool/stats') return json(route, { total: 5274, pending: 5069, converted: 205, isolated: 0, duplicates: 0, archived: 0 });
    if (path === '/api/v1/merchant-pool') {
      queries.push(url.searchParams);
      const eastern = url.searchParams.get('timezone_group') === 'eastern';
      if (eastern && ++easternAttempts === 1) { await failureGate; return route.abort('failed'); }
      const item = eastern ? { ...record, id: 2, business_name: '合成东部门店', state: 'NY', city: 'New York', timezone: 'America/New_York', timezone_group: 'eastern' } : record;
      const total = eastern ? 3535 : 152;
      return json(route, { items: [item], total, industry_facets: [{ value: '美业', label: '美业', count: total }], facet_total: total, quality_facets: { pending: total, valid: 0, invalid: 0 } });
    }
    return json(route, { items: [], total: 0 });
  });
  await page.goto(`${baseUrl}/merchant-pool`);
  const zones = page.getByRole('navigation', { name: '拨打时区' });
  await zones.getByRole('button', { name: '中部', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看资料：合成中部门店', exact: true })).toBeVisible();
  const industry = page.getByRole('navigation', { name: '行业分类' });
  await expect(industry.getByRole('button', { name: /^美业/ })).toContainText('152');
  await zones.getByRole('button', { name: '东部', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看资料：合成中部门店', exact: true })).toHaveCount(0);
  await expect(industry.getByRole('button', { name: /^美业/ })).not.toContainText('152');
  releaseFailure();
  await expect(page.getByRole('alert').filter({ hasText: '当前筛选加载失败' })).toBeVisible();
  await expect(page.getByText('当前筛选数量暂不可用', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '查看资料：合成中部门店', exact: true })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath(`filter-failure-${width}.png`) });
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看资料：合成东部门店', exact: true })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: '当前筛选加载失败' })).toHaveCount(0);
  await expect(industry.getByRole('button', { name: /^美业/ })).toContainText('3535');
  expect(queries.at(-1)?.get('timezone_group')).toBe('eastern');
  expect(queries.at(-1)?.get('skip')).toBe('0');
  expect(writes).toEqual([]);
  await page.screenshot({ path: test.info().outputPath(`filter-recovered-${width}.png`) });
});
