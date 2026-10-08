import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5190';
const screenshotDir = process.env.T24_REVIEW_SCREENSHOT_DIR;
const manager = { id: 10, name: '商家核对测试主管', role: 'sales_manager', status: 'active' };
const salesperson = { id: 11, name: '核对测试销售', role: 'sales', status: 'active' };
const originalAddress = '123 Main St, Suite 205, Los Angeles, CA 90012 · 商家导入的完整街道地址';
const originalSource = 'Google Maps 原始采集';
const pendingMerchant = {
  id: 21, business_name: 'Golden Dragon Restaurant', contact_name: '陈老板',
  phone: '(626) 555-0123', industry: '餐厅', country: 'US', state: 'CA', city: 'Los Angeles',
  address: originalAddress, website: 'https://example.com/golden-dragon', data_source: originalSource,
  collected_at: '2026-10-08T09:00:00Z', pool_status: 'pending', isolation_reason: null,
  converted_lead_id: null,
};
type Merchant = Omit<typeof pendingMerchant, 'isolation_reason' | 'converted_lead_id'> & {
  isolation_reason: string | null; converted_lead_id: number | null;
};
type Write = { method: string; path: string; body: unknown };

async function json(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedPool(page: Page, employee = manager) {
  await page.addInitScript(({ emp }) => {
    localStorage.setItem('emp_auth_token', 'merchant-review-test-token');
    localStorage.setItem('token', 'merchant-review-test-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
  const records: Merchant[] = [
    { ...pendingMerchant },
    { ...pendingMerchant, id: 22, business_name: 'Sunset Nails', phone: '(626) 555-0144', industry: '美甲', city: 'Pasadena' },
    { ...pendingMerchant, id: 23, business_name: '已转入销售的商家', phone: '(626) 555-0177', pool_status: 'converted', converted_lead_id: 91, isolation_reason: '已人工确认并转入独立电话销售线索库' },
    { ...pendingMerchant, id: 24, business_name: '缺电话待补商家', phone: '', pool_status: 'no_phone', isolation_reason: '未提供可用电话，暂不进入线索库' },
    { ...pendingMerchant, id: 25, business_name: '已归档历史商家', phone: '(626) 555-0188', pool_status: 'archived', isolation_reason: '管理员归档：测试管理员' },
  ];
  const writes: Write[] = [];
  const listQueries: string[] = [];

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() !== 'GET') {
      writes.push({ method: request.method(), path, body: request.postDataJSON() });
      if (path === '/api/v1/merchant-pool/bulk-convert-to-lead' && request.method() === 'POST') {
        const payload = request.postDataJSON() as { merchant_ids: number[]; assigned_sales_id: number };
        const selected = records.filter(record => payload.merchant_ids.includes(record.id));
        if (payload.assigned_sales_id !== salesperson.id || selected.length !== payload.merchant_ids.length || selected.some(record => record.pool_status !== 'pending')) {
          return json(route, { detail: '模拟后端拒绝非法分配' }, 400);
        }
        selected.forEach(record => { record.pool_status = 'converted'; record.converted_lead_id = record.id + 1000; });
        return json(route, { converted_count: selected.length, assigned_sales_id: salesperson.id, assigned_sales_name: salesperson.name, lead_ids: selected.map(record => record.converted_lead_id) });
      }
      return json(route, { detail: '此测试不允许其他写请求' }, 400);
    }
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path === '/api/v1/sales-leads/assignees') return json(route, [salesperson]);
    if (path === '/api/v1/merchant-pool/stats') return json(route, {
      total: records.filter(record => record.pool_status !== 'archived').length,
      pending: records.filter(record => record.pool_status === 'pending').length,
      converted: records.filter(record => record.pool_status === 'converted').length,
      isolated: records.filter(record => ['no_phone', 'duplicate', 'existing_customer', 'closed'].includes(record.pool_status)).length,
      duplicates: 0, archived: records.filter(record => record.pool_status === 'archived').length,
    });
    if (path === '/api/v1/merchant-pool') {
      listQueries.push(url.search);
      const status = url.searchParams.get('pool_status');
      const search = (url.searchParams.get('search') || '').toLowerCase();
      const matching = records.filter(record => (status ? record.pool_status === status : record.pool_status !== 'archived')
        && (!search || `${record.business_name} ${record.phone} ${record.website}`.toLowerCase().includes(search)));
      const skip = Number(url.searchParams.get('skip') || 0);
      const limit = Number(url.searchParams.get('limit') || 20);
      return json(route, { items: matching.slice(skip, skip + limit), total: matching.length, skip, limit });
    }
    return json(route, { items: [], total: 0 });
  });
  return { writes, listQueries };
}

async function noOverflow(page: Page) {
  const widths = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}

test('待核对为默认工作视图，切换视图查询真实状态且全部记录排除归档', async ({ page }) => {
  const { writes, listQueries } = await seedPool(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  const views = page.getByRole('navigation', { name: '商家工作视图' });
  await expect(views.getByRole('button', { name: /^待核对\s*2$/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '查看资料：已转入销售的商家', exact: true })).toHaveCount(0);
  expect(listQueries.length).toBeGreaterThan(0);
  expect(listQueries.every(query => new URLSearchParams(query).get('pool_status') === 'pending')).toBeTruthy();

  await views.getByRole('button', { name: /^已转线索\s*1$/ }).click();
  await expect(page.getByRole('button', { name: '查看资料：已转入销售的商家', exact: true })).toBeVisible();
  expect(new URLSearchParams(listQueries.at(-1)).get('pool_status')).toBe('converted');
  await expect(page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true })).toHaveCount(0);
  await views.getByRole('button', { name: /^全部记录\s*4$/ }).click();
  await expect(page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true })).toBeVisible();
  await expect(page.getByText('缺电话待补商家', { exact: true })).toBeVisible();
  await expect(page.getByText('已归档历史商家', { exact: true })).toHaveCount(0);
  expect(new URLSearchParams(listQueries.at(-1)).get('pool_status')).toBeNull();
  expect(writes).toEqual([]);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-review-desktop.png`, fullPage: true, animations: 'disabled' });
});

test('核对与加入队列不写数据库，取消分配不转换，确认后才提交原分配字段并刷新计数', async ({ page }) => {
  const { writes } = await seedPool(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true }).click();
  const detail = page.getByRole('complementary', { name: '商家资料核对' });
  await expect(detail.getByText(originalAddress, { exact: true })).toBeVisible();
  await expect(detail.getByText(originalSource, { exact: true })).toBeVisible();
  const queue = detail.getByRole('button', { name: '加入待分配', exact: true });
  await expect(queue).toBeDisabled();
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-review-panel-desktop.png`, fullPage: true, animations: 'disabled' });
  await detail.getByRole('checkbox', { name: '已核对名称、电话和地区', exact: true }).check();
  await expect(queue).toBeEnabled();
  await queue.click();
  const batch = page.getByRole('region', { name: '商家批量操作' });
  await expect(batch).toBeVisible();
  await expect(batch).toContainText('1');
  await expect(batch.getByRole('button', { name: '确认分配', exact: true })).toBeDisabled();
  expect(writes).toEqual([]);
  await expect(page.getByRole('navigation', { name: '商家工作视图' }).getByRole('button', { name: /^待核对\s*2$/ })).toBeVisible();

  await batch.getByLabel(/^选择销售负责人/).selectOption(String(salesperson.id));
  page.once('dialog', dialog => dialog.dismiss());
  await batch.getByRole('button', { name: '确认分配', exact: true }).click();
  expect(writes).toEqual([]);
  await expect(batch).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/merchant-pool/bulk-convert-to-lead' && response.request().method() === 'POST'),
    batch.getByRole('button', { name: '确认分配', exact: true }).click(),
  ]);
  await expect(page.getByRole('navigation', { name: '商家工作视图' }).getByRole('button', { name: /^待核对\s*1$/ })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '商家工作视图' }).getByRole('button', { name: /^已转线索\s*2$/ })).toBeVisible();
  await expect(page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true })).toHaveCount(0);
  expect(writes).toEqual([{ method: 'POST', path: '/api/v1/merchant-pool/bulk-convert-to-lead', body: { merchant_ids: [pendingMerchant.id], assigned_sales_id: salesperson.id } }]);
});

test('已转线索详情只读，不能通过核对重新保存或分配', async ({ page }) => {
  const { writes } = await seedPool(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('navigation', { name: '商家工作视图' }).getByRole('button', { name: /^已转线索\s*1$/ }).click();
  await page.getByRole('button', { name: '查看资料：已转入销售的商家', exact: true }).click();
  const detail = page.getByRole('complementary', { name: '商家资料核对' });
  await expect(detail).toBeVisible();
  await expect(detail.getByRole('checkbox')).toHaveCount(0);
  await expect(detail.getByRole('button', { name: /加入待分配|编辑|补充资料|保存/ })).toHaveCount(0);
  await expect(detail.getByRole('button', { name: '累计档案', exact: true })).toBeVisible();
  expect(writes).toEqual([]);
});

test('390px 工作列表精简地址与来源，打开核对后完整显示且不产生写入', async ({ page }) => {
  const { writes } = await seedPool(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await expect(page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true })).toBeVisible();
  await expect(page.getByText(originalAddress, { exact: true })).not.toBeVisible();
  await expect(page.getByText(originalSource, { exact: true })).not.toBeVisible();
  await noOverflow(page);
  await page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true }).click();
  const detail = page.getByRole('dialog');
  await expect(detail.getByRole('heading', { name: '核对商家资料', exact: true })).toBeVisible();
  await expect(detail.getByText(originalAddress, { exact: true })).toBeVisible();
  await expect(detail.getByText(originalSource, { exact: true })).toBeVisible();
  await expect(detail.getByRole('button', { name: '加入待分配', exact: true })).toBeDisabled();
  await noOverflow(page);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-review-mobile.png`, fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(detail).toBeHidden();
  expect(writes).toEqual([]);
});

test('普通销售没有商家池权限，不显示核对复选框或分配操作', async ({ page }) => {
  const { writes } = await seedPool(page, salesperson);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '已核对名称、电话和地区', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /加入待分配|确认分配/ })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('管理员可查看归档和保留删除菜单，隔离商家补资料打开取消均不写入', async ({ page }) => {
  const { writes } = await seedPool(page, { ...manager, role: 'admin' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('button', { name: /^更多筛选/ }).click();
  const status = page.getByLabel(/^清洗状态/);
  await status.selectOption('archived');
  await page.getByRole('button', { name: '查看资料：已归档历史商家', exact: true }).click();
  let detail = page.getByRole('complementary', { name: '商家资料核对' });
  await expect(detail.getByText('已归档历史商家', { exact: true })).toBeVisible();
  await expect(detail.getByRole('checkbox')).toHaveCount(0);
  await expect(detail.getByRole('button', { name: /补充资料|加入待分配|保存/ })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: '选择 已归档历史商家', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '更多商家操作：已归档历史商家', exact: true }).click();
  await expect(page.getByRole('menuitem', { name: '永久删除', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  expect(writes).toEqual([]);

  await status.selectOption('no_phone');
  await page.getByRole('button', { name: '查看资料：缺电话待补商家', exact: true }).click();
  detail = page.getByRole('complementary', { name: '商家资料核对' });
  await expect(detail.getByText('未提供可用电话，暂不进入线索库', { exact: true })).toBeVisible();
  await expect(detail.getByRole('checkbox')).toHaveCount(0);
  await expect(detail.getByRole('button', { name: '加入待分配', exact: true })).toHaveCount(0);
  await detail.getByRole('button', { name: '补充资料', exact: true }).click();
  const editor = page.getByRole('dialog');
  await expect(editor.getByRole('heading', { name: '补充商家资料并重新清洗', exact: true })).toBeVisible();
  await expect(editor.getByRole('textbox').first()).toHaveValue('缺电话待补商家');
  await editor.getByRole('button', { name: '取消', exact: true }).click();
  await expect(editor).toBeHidden();
  expect(writes).toEqual([]);
});

test('320、768、1024px 工作视图和详情无横向溢出，平板表格无需横向滚动', async ({ page }) => {
  const { writes } = await seedPool(page);
  const tableFits = async () => {
    const wrapper = page.getByTestId('merchant-pool-desktop-table');
    await expect(wrapper).toBeVisible();
    const sizes = await wrapper.evaluate(element => {
      const table = element.querySelector('table');
      return {
        container: element.clientWidth, containerScroll: element.scrollWidth,
        table: table?.getBoundingClientRect().width || 0,
        tableClient: table?.clientWidth || 0, tableScroll: table?.scrollWidth || 0,
      };
    });
    expect(sizes.table).toBeGreaterThan(0);
    expect(sizes.containerScroll).toBeLessThanOrEqual(sizes.container + 1);
    expect(sizes.table).toBeLessThanOrEqual(sizes.container + 1);
    expect(sizes.tableScroll).toBeLessThanOrEqual(sizes.tableClient + 1);
  };
  for (const width of [768, 1024, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${baseUrl}/merchant-pool`);
    const views = page.getByRole('navigation', { name: '商家工作视图' });
    for (const name of [/^待核对\s*2$/, /^已转线索\s*1$/, /^全部记录\s*4$/]) {
      const button = views.getByRole('button', { name });
      await expect(button).toBeVisible();
      const box = await button.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    }
    await noOverflow(page);
    if (width >= 768) await tableFits();
    await page.getByRole('button', { name: '核对资料：Golden Dragon Restaurant', exact: true }).click();
    const detail = width < 768 ? page.getByRole('dialog') : page.getByRole('complementary', { name: '商家资料核对' });
    await expect(detail.getByText(originalAddress, { exact: true })).toBeVisible();
    await noOverflow(page);
    if (width >= 768) {
      await tableFits();
      const detailBox = await detail.boundingBox();
      const tableBox = await page.getByTestId('merchant-pool-desktop-table').boundingBox();
      expect(detailBox).not.toBeNull();
      expect(tableBox).not.toBeNull();
      expect(detailBox!.y).toBeLessThanOrEqual(tableBox!.y);
    }
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-review-${width}px.png`, fullPage: true, animations: 'disabled' });
  }
  expect(writes).toEqual([]);
});

test('长列表仅在内容区滚动，分页后不出现外层空白页', async ({ page }) => {
  const { writes } = await seedPool(page);
  const records = Array.from({ length: 20 }, (_, index) => ({
    ...pendingMerchant, id: 10001 + index, business_name: `长列表核对商家${index + 1}`,
  }));
  await page.route('**/api/v1/merchant-pool?*', route => {
    const query = new URL(route.request().url()).searchParams;
    const skip = Number(query.get('skip') || 0);
    const limit = Number(query.get('limit') || 20);
    return json(route, { items: records.slice(skip, skip + limit), total: records.length, skip, limit });
  });
  await page.route('**/api/v1/merchant-pool/stats', route => json(route, {
    total: 20, pending: 20, converted: 0, isolated: 0, duplicates: 0, archived: 0,
  }));

  const assertScrollBoundary = async (tailAllowance: number) => {
    const main = page.getByRole('main');
    const pagination = page.locator('.mp-list-pagination');
    await expect(pagination).toContainText('显示 1–20 条 / 共 20 条');
    await main.evaluate(element => { element.scrollTop = element.scrollHeight; });
    await expect.poll(() => main.evaluate(element => Math.abs(element.scrollHeight - element.clientHeight - element.scrollTop))).toBeLessThanOrEqual(2);
    const geometry = await pagination.evaluate(element => {
      const main = element.closest('main')!;
      const mainBox = main.getBoundingClientRect();
      const pageBox = element.getBoundingClientRect();
      return {
        viewport: innerHeight,
        documentHeight: document.documentElement.scrollHeight,
        bodyHeight: document.body.scrollHeight,
        mainTop: mainBox.top,
        mainBottom: mainBox.bottom,
        paginationTop: pageBox.top,
        paginationBottom: pageBox.bottom,
        mainClientHeight: main.clientHeight,
        mainScrollHeight: main.scrollHeight,
        tailGap: mainBox.bottom - pageBox.bottom,
      };
    });
    // A full page must really scroll inside main. Its clipped accessibility
    // labels must not create another scrollable page outside the app shell.
    expect(geometry.mainScrollHeight).toBeGreaterThan(geometry.mainClientHeight + 100);
    expect(geometry.documentHeight, JSON.stringify(geometry)).toBeLessThanOrEqual(geometry.viewport + 1);
    expect(geometry.bodyHeight).toBeLessThanOrEqual(geometry.viewport + 1);
    expect(geometry.paginationTop).toBeGreaterThanOrEqual(geometry.mainTop - 1);
    expect(geometry.paginationBottom).toBeLessThanOrEqual(geometry.mainBottom + 1);
    expect(geometry.tailGap).toBeGreaterThanOrEqual(-1);
    expect(geometry.tailGap).toBeLessThanOrEqual(tailAllowance);
  };

  await page.setViewportSize({ width: 1093, height: 824 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await expect(page.getByTestId('merchant-pool-desktop-table').locator('tbody tr')).toHaveCount(20);
  await assertScrollBoundary(48);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-scroll-desktop-collapsed.png`, fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '展开功能导航', exact: true }).click();
  await expect(page.getByRole('button', { name: '收起功能导航', exact: true })).toBeVisible();
  await assertScrollBoundary(48);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-scroll-desktop-expanded.png`, fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '收起功能导航', exact: true }).click();
  await assertScrollBoundary(48);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('merchant-mobile-card')).toHaveCount(20);
  // Mobile keeps room for its fixed navigation and safe-area padding.
  await assertScrollBoundary(224);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/merchant-scroll-mobile.png`, fullPage: true, animations: 'disabled' });
  expect(writes).toEqual([]);
});


test('分配末页最后一条后回到有效页，不显示倒置范围或空末页', async ({ page }) => {
  await seedPool(page);
  const records = Array.from({ length: 21 }, (_, index) => ({ ...pendingMerchant, id: index + 21, business_name: `分页核对商家${index + 1}`, pool_status: 'pending' }));
  const skips: number[] = [];
  await page.route('**/api/v1/merchant-pool?*', route => {
    const query = new URL(route.request().url()).searchParams;
    const pending = records.filter(record => record.pool_status === 'pending');
    const skip = Number(query.get('skip') || 0);
    skips.push(skip);
    return json(route, { items: pending.slice(skip, skip + Number(query.get('limit') || 20)), total: pending.length });
  });
  await page.route('**/api/v1/merchant-pool/stats', route => json(route, { total: 21, pending: records.filter(record => record.pool_status === 'pending').length, converted: records.filter(record => record.pool_status === 'converted').length, isolated: 0, duplicates: 0, archived: 0 }));
  await page.route('**/api/v1/merchant-pool/bulk-convert-to-lead', route => {
    const body = route.request().postDataJSON();
    expect(body).toEqual({ merchant_ids: [41], assigned_sales_id: salesperson.id });
    records.find(record => record.id === 41)!.pool_status = 'converted';
    return json(route, { converted_count: 1, assigned_sales_name: salesperson.name });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByRole('checkbox', { name: '选择 分页核对商家21', exact: true }).check();
  const batch = page.getByRole('region', { name: '商家批量操作' });
  await batch.getByLabel(/^选择销售负责人/).selectOption(String(salesperson.id));
  page.once('dialog', dialog => dialog.accept());
  await batch.getByRole('button', { name: '确认分配', exact: true }).click();
  await expect(page.getByRole('button', { name: '核对资料：分页核对商家1', exact: true })).toBeVisible();
  await expect(page.getByText('显示 1–20 条 / 共 20 条', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  expect(skips).toContain(20);
  expect(skips.at(-1)).toBe(0);
});
