import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5190';
const manager = { id: 10, name: '行业分配测试主管', role: 'sales_manager', status: 'active' };
const salesperson = { id: 11, name: '餐厅测试销售', role: 'sales', status: 'active' };
const originalAddress = '819 N Broadway, Los Angeles, CA 90012';

type Merchant = {
  id: number; business_name: string; phone: string; industry: string | null;
  country: string; state: string; city: string; address: string; data_source: string;
  collected_at: string; pool_status: string; converted_lead_id: number | null;
};
type Write = { path: string; body: unknown };

function category(value: string | null) {
  if (!value?.trim()) return '__unclassified__';
  if (['餐饮', '餐厅', 'Chinese Restaurant', 'Restaurant'].includes(value)) return '餐厅';
  if (['美甲', '美容', '美业', '按摩'].includes(value)) return '美业';
  return value;
}

async function json(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedPool(page: Page, employee = manager) {
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'merchant-industry-test-token');
    localStorage.setItem('token', 'merchant-industry-test-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  const base: Merchant = {
    id: 1, business_name: '餐厅商家1', phone: '2136250811', industry: '餐饮',
    country: 'US', state: 'California', city: 'Los Angeles', address: originalAddress,
    data_source: 'https://example.com/restaurant', collected_at: '2026-10-14T02:00:00Z',
    pool_status: 'pending', converted_lead_id: null,
  };
  const records: Merchant[] = [
    ...Array.from({ length: 21 }, (_, index) => ({ ...base, id: index + 1, business_name: `餐厅商家${index + 1}`, industry: index % 2 ? 'Chinese Restaurant' : '餐饮' })),
    { ...base, id: 22, business_name: '美甲商家', industry: '美甲', state: 'NY', city: 'New York' },
    { ...base, id: 23, business_name: '美容商家', industry: '美容' },
    { ...base, id: 24, business_name: '待分类商家', industry: null },
    { ...base, id: 25, business_name: '已归档餐厅', pool_status: 'archived' },
    { ...base, id: 26, business_name: '已转线索餐厅', pool_status: 'converted', converted_lead_id: 10026 },
  ];
  const writes: Write[] = [];
  const listQueries: URLSearchParams[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() !== 'GET') {
      const body = request.postDataJSON();
      writes.push({ path, body });
      if (path === '/api/v1/merchant-pool/bulk-update-industry') {
        const { merchant_ids: ids, industry } = body as { merchant_ids: number[]; industry: string };
        const selected = records.filter(record => ids.includes(record.id));
        if (selected.length !== ids.length || selected.some(record => ['converted', 'archived'].includes(record.pool_status))) return json(route, { detail: '不允许修改终态记录' }, 400);
        selected.forEach(record => { record.industry = category(industry); });
        return json(route, { updated_count: selected.length, industry: category(industry) });
      }
      if (path === '/api/v1/merchant-pool/bulk-convert-to-lead') {
        const { merchant_ids: ids, assigned_sales_id: salesId } = body as { merchant_ids: number[]; assigned_sales_id: number };
        const selected = records.filter(record => ids.includes(record.id));
        if (salesId !== salesperson.id || selected.length !== ids.length || selected.some(record => record.pool_status !== 'pending')) return json(route, { detail: '不允许分配非待分配记录' }, 400);
        selected.forEach(record => { record.pool_status = 'converted'; record.converted_lead_id = record.id + 10000; });
        return json(route, { converted_count: selected.length, assigned_sales_id: salesperson.id, assigned_sales_name: salesperson.name });
      }
      return json(route, { detail: '此测试禁止其他写入' }, 400);
    }
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path === '/api/v1/sales-leads/assignees') return json(route, [salesperson]);
    if (path === '/api/v1/merchant-pool/stats') return json(route, {
      total: records.filter(record => record.pool_status !== 'archived').length,
      pending: records.filter(record => record.pool_status === 'pending').length,
      converted: records.filter(record => record.pool_status === 'converted').length,
      isolated: 0, duplicates: 0, archived: 1,
    });
    if (path === '/api/v1/merchant-pool') {
      listQueries.push(url.searchParams);
      const status = url.searchParams.get('pool_status');
      const search = (url.searchParams.get('search') || '').toLowerCase();
      const scope = records.filter(record => (status ? record.pool_status === status : record.pool_status !== 'archived')
        && (!search || `${record.business_name} ${record.phone}`.toLowerCase().includes(search)));
      const totals = new Map<string, number>();
      scope.forEach(record => totals.set(category(record.industry), (totals.get(category(record.industry)) || 0) + 1));
      const industryFacets = [...totals].map(([value, count]) => ({ value, count, label: value === '__unclassified__' ? '待分类' : value }));
      const industry = url.searchParams.get('industry');
      const matching = scope.filter(record => !industry || category(record.industry) === category(industry));
      const skip = Number(url.searchParams.get('skip') || 0);
      const limit = Number(url.searchParams.get('limit') || 20);
      return json(route, { items: matching.slice(skip, skip + limit).map(record => ({ ...record, industry: category(record.industry) === '__unclassified__' ? null : category(record.industry) })), total: matching.length, skip, limit, industry_facets: industryFacets, facet_total: scope.length });
    }
    return json(route, { items: [], total: 0 });
  });
  return { records, writes, listQueries };
}

async function noOverflow(page: Page) {
  const widths = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}

test('列表使用商家电话、州缩写与统一行业，点击名称保留完整地址和地区', async ({ page }) => {
  const { writes } = await seedPool(page);
  for (const width of [1440, 1093, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${baseUrl}/merchant-pool`);
    await expect(page.getByRole('navigation', { name: '行业分类' }).getByRole('button', { name: /^餐厅\s*21$/ })).toBeVisible();
    if (width >= 768) {
      const table = page.getByTestId('merchant-pool-desktop-table');
      await expect(table.getByRole('columnheader', { name: '商家电话', exact: true })).toBeVisible();
      await expect(table.getByRole('columnheader', { name: '行业', exact: true })).toBeVisible();
      const firstRow = table.locator('tbody tr').first();
      await expect(firstRow.locator('.mp-region-column')).toHaveText('CA');
      await expect(firstRow.locator('.mp-industry-column')).toHaveText('餐厅');
      await expect(firstRow).not.toContainText('Los Angeles');
    } else {
      await expect(page.getByTestId('merchant-mobile-card').first()).toContainText('餐厅');
      await expect(page.getByTestId('merchant-mobile-card').first()).toContainText('CA');
    }
    await noOverflow(page);
    await page.getByRole('button', { name: '查看资料：餐厅商家1', exact: true }).click();
    const detail = width >= 768 ? page.getByRole('complementary', { name: '商家资料' }) : page.getByRole('dialog');
    await expect(detail.getByText(originalAddress, { exact: true })).toBeVisible();
    await expect(detail).toContainText('Los Angeles, CA');
    await noOverflow(page);
  }
  expect(writes).toEqual([]);
});

test('行业总数覆盖分页数据，同业跨页选择保留，切换行业清空已选防止混合分配', async ({ page }) => {
  const { writes, listQueries } = await seedPool(page);
  await page.setViewportSize({ width: 1093, height: 824 });
  await page.goto(`${baseUrl}/merchant-pool`);
  const facets = page.getByRole('navigation', { name: '行业分类' });
  await expect(page.getByTestId('merchant-pool-desktop-table').locator('tbody tr')).toHaveCount(20);
  await expect(facets.getByRole('button', { name: /^全部行业\s*24$/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(facets.getByRole('button', { name: /^餐厅\s*21$/ })).toBeVisible();
  await expect(facets.getByRole('button', { name: /^美业\s*2$/ })).toBeVisible();
  await expect(facets.getByRole('button', { name: /^待分类\s*1$/ })).toBeVisible();

  await facets.getByRole('button', { name: /^餐厅\s*21$/ }).click();
  await expect(facets.getByRole('button', { name: /^餐厅\s*21$/ })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => listQueries.at(-1)?.get('industry')).toBe('餐厅');
  await page.getByRole('checkbox', { name: '选择 餐厅商家1', exact: true }).check();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看资料：餐厅商家21', exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: '选择 餐厅商家21', exact: true }).check();
  const batch = page.getByRole('region', { name: '商家批量操作' });
  await expect(batch).toContainText('跨页已选 2 家商家');
  await batch.getByLabel(/^选择销售负责人/).selectOption(String(salesperson.id));

  await facets.getByRole('button', { name: /^美业\s*2$/ }).click();
  await expect(page.getByRole('button', { name: '查看资料：美甲商家', exact: true })).toBeVisible();
  await expect(batch).toHaveCount(0);
  await expect.poll(() => listQueries.at(-1)?.get('industry')).toBe('美业');
  await expect.poll(() => listQueries.at(-1)?.get('skip')).toBe('0');
  await expect(page.getByTestId('merchant-pool-desktop-table').locator('tbody tr').first().locator('.mp-region-column')).toHaveText('NY');
  await expect(page.getByTestId('merchant-pool-desktop-table').locator('tbody tr').first().locator('.mp-industry-column')).toHaveText('美业');

  await facets.getByRole('button', { name: /^待分类\s*1$/ }).click();
  await expect(page.getByRole('button', { name: '查看资料：待分类商家', exact: true })).toBeVisible();
  await expect.poll(() => listQueries.at(-1)?.get('industry')).toBe('__unclassified__');
  await expect(page.getByTestId('merchant-pool-desktop-table').locator('tbody tr').first().locator('.mp-industry-column')).toHaveText('待分类');
  expect(writes).toEqual([]);
});

test('只对明确所选商家批量分类，刷新计数后可独立分配，不写客户或财务', async ({ page }) => {
  const { writes, records } = await seedPool(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  const facets = page.getByRole('navigation', { name: '行业分类' });
  await facets.getByRole('button', { name: /^待分类\s*1$/ }).click();
  await page.getByRole('checkbox', { name: '选择 待分类商家', exact: true }).check();
  const batch = page.getByRole('region', { name: '商家批量操作' });
  await batch.getByRole('button', { name: '设置行业', exact: true }).click();
  const classifier = page.getByRole('dialog', { name: '批量设置行业' });
  await expect(classifier).toBeVisible();
  await classifier.getByLabel('商家行业', { exact: true }).selectOption('美业');
  await classifier.getByRole('button', { name: '保存行业', exact: true }).click();
  await expect(batch).toHaveCount(0);
  await expect(facets.getByRole('button', { name: /^美业\s*3$/ })).toBeVisible();
  expect(records.find(record => record.id === 24)?.industry).toBe('美业');
  expect(records.find(record => record.id === 1)?.industry).toBe('餐饮');
  expect(writes).toEqual([{ path: '/api/v1/merchant-pool/bulk-update-industry', body: { merchant_ids: [24], industry: '美业' } }]);

  await facets.getByRole('button', { name: /^美业\s*3$/ }).click();
  await page.getByRole('checkbox', { name: '选择 待分类商家', exact: true }).check();
  await batch.getByLabel(/^选择销售负责人/).selectOption(String(salesperson.id));
  page.once('dialog', dialog => dialog.accept());
  await batch.getByRole('button', { name: '确认分配', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看资料：待分类商家', exact: true })).toHaveCount(0);
  await expect(facets.getByRole('button', { name: /^美业\s*2$/ })).toBeVisible();
  expect(writes).toEqual([
    { path: '/api/v1/merchant-pool/bulk-update-industry', body: { merchant_ids: [24], industry: '美业' } },
    { path: '/api/v1/merchant-pool/bulk-convert-to-lead', body: { merchant_ids: [24], assigned_sales_id: salesperson.id } },
  ]);
});

test('普通销售无法进入商家池查看或批量分类、分配', async ({ page }) => {
  const { writes, listQueries } = await seedPool(page, salesperson);
  await page.goto(`${baseUrl}/merchant-pool`);
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '行业分类' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /查看资料：|设置行业|确认分配/ })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(listQueries).toEqual([]);
});
