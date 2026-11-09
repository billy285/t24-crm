import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5218';
const manager = { id: 10, name: '合成时区测试主管', role: 'sales_manager', status: 'active' };
const base = { phone: '+16265550123', country: 'US', industry: '美业', state: 'CA', city: 'Los Angeles', address: '123 Synthetic St, Los Angeles, CA 90012', data_source: 'csv', collected_at: '2026-11-09T02:00:00Z', pool_status: 'pending', converted_lead_id: null, timezone: 'America/Los_Angeles', timezone_group: 'pacific', timezone_basis: 'address_state', timezone_needs_confirmation: true };
async function json(route: Route, data: unknown) { await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) }); }
async function seed(page: Page) {
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'synthetic-timezone-token');
    localStorage.setItem('token', 'synthetic-timezone-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, manager);
  await page.clock.setFixedTime(new Date('2026-01-01T17:30:00Z'));
  const records = [
    ...Array.from({ length: 21 }, (_, n) => ({ ...base, id: n + 1, business_name: `合成西部美容${n + 1}` })),
    { ...base, id: 22, business_name: '合成亚利桑那美容', state: 'AZ', city: 'Phoenix', timezone: 'America/Phoenix', timezone_group: 'mountain', timezone_basis: 'address_city' },
    { ...base, id: 23, business_name: '合成地址不足商家', state: '', city: '', timezone: null, timezone_group: 'unknown', timezone_basis: 'unknown' },
    { ...base, id: 24, business_name: '合成夏威夷美容', state: 'HI', city: 'Honolulu', timezone: 'Pacific/Honolulu', timezone_group: 'hawaii' },
  ];
  const queries: URLSearchParams[] = [];
  const writes: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (request.method() !== 'GET') { writes.push(path); return json(route, {}); }
    if (path.endsWith('/emp-auth/me')) return json(route, manager);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.endsWith('/sales-leads/assignees')) return json(route, [{ id: 11, name: '合成销售' }]);
    if (path === '/api/v1/merchant-pool/stats') return json(route, { total: records.length, pending: records.length, converted: 0, isolated: 0, duplicates: 0, archived: 0 });
    if (path === '/api/v1/merchant-pool') {
      queries.push(url.searchParams);
      const group = url.searchParams.get('timezone_group');
      const matching = records.filter(row => !group || row.timezone_group === group);
      const skip = Number(url.searchParams.get('skip') || 0), limit = Number(url.searchParams.get('limit') || 20);
      return json(route, { items: matching.slice(skip, skip + limit), total: matching.length, industry_facets: [{ value: '美业', label: '美业', count: matching.length }], facet_total: matching.length });
    }
    return json(route, { items: [], total: 0 });
  });
  return { queries, writes };
}

test('时区切换从第一页查询且清空跨页选择，保留批次行业和来源筛选', async ({ page }) => {
  const { queries, writes } = await seed(page);
  await page.setViewportSize({ width: 1093, height: 824 });
  await page.goto(`${baseUrl}/merchant-pool?batch_id=synthetic-timezone-batch`);
  await page.getByRole('navigation', { name: '行业分类' }).getByRole('button', { name: /^美业/ }).click();
  await page.getByRole('button', { name: /^更多筛选/ }).click();
  await page.getByRole('combobox', { name: '筛选资料来源', exact: true }).selectOption('csv');
  await page.getByRole('checkbox', { name: '选择 合成西部美容1', exact: true }).check();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByRole('checkbox', { name: '选择 合成西部美容21', exact: true }).check();
  await expect(page.getByRole('region', { name: '商家批量操作' })).toContainText('跨页已选 2 家商家');
  await page.getByRole('navigation', { name: '拨打时区' }).getByRole('button', { name: '山地', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看资料：合成亚利桑那美容', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: '商家批量操作' })).toHaveCount(0);
  await expect.poll(() => queries.at(-1)?.get('timezone_group')).toBe('mountain');
  expect(queries.at(-1)?.get('skip')).toBe('0');
  expect(queries.at(-1)?.get('industry')).toBe('美业');
  expect(queries.at(-1)?.get('source')).toBe('csv');
  expect(queries.at(-1)?.get('batch_id')).toBe('synthetic-timezone-batch');
  expect(writes).toEqual([]);
});

test('桌面和手机显示时区、门店钟表和推定依据，未知时区不显示假时间', async ({ page }) => {
  const { writes } = await seed(page);
  for (const width of [1440, 1093, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${baseUrl}/merchant-pool`);
    const zones = page.getByRole('navigation', { name: '拨打时区' });
    for (const label of ['东部', '中部', '山地', '西部']) await expect(zones.getByRole('button', { name: label, exact: true })).toBeVisible();
    const first = width < 768 ? page.getByTestId('merchant-mobile-card').first() : page.getByTestId('merchant-pool-desktop-table').locator('tbody tr').first();
    await expect(first).toContainText('当地 09:30');
    await expect(first).toContainText('推定');
    if ([1440, 390].includes(width)) await page.screenshot({ path: test.info().outputPath(`timezone-${width}.png`) });
    await zones.getByRole('button', { name: '山地', exact: true }).click();
    await expect(page.getByText('合成亚利桑那美容', { exact: true })).toBeVisible();
    const arizona = width < 768 ? page.getByTestId('merchant-mobile-card').first() : page.getByTestId('merchant-pool-desktop-table').locator('tbody tr').first();
    await expect(arizona).toContainText('当地 10:30');
    await page.getByRole('combobox', { name: '其他拨打时区', exact: true }).selectOption('unknown');
    await expect(page.getByText('合成地址不足商家', { exact: true })).toBeVisible();
    const unknown = width < 768 ? page.getByTestId('merchant-mobile-card').first() : page.getByTestId('merchant-pool-desktop-table').locator('tbody tr').first();
    await expect(unknown).toContainText('时区待确认');
    await expect(unknown.locator('time')).toHaveCount(0);
    const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
    expect(sizes.document).toBeLessThanOrEqual(sizes.viewport);
    expect(sizes.body).toBeLessThanOrEqual(sizes.viewport);
  }
  expect(writes).toEqual([]);
});
