import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
const employee = { id: 1, name: '体验测试管理员', role: 'admin', status: 'active' };
const lead = { id: 501, business_name: 'Sample Cafe', phone: '2125550123', country: 'US', status: 'new', do_not_contact: false, is_blacklisted: false };
const deal = { id: 5, customer_id: 31, customer_name: 'Sample Cafe', product_type: 'website', package_name: '基础套餐', billing_cycle: 'monthly', deal_amount: 299, is_paid: true, needs_group: false, is_handed_over: false, is_transferred_ops: false, notes: '原备注', deal_date: '2026-10-01' };

async function fixture(page: Page, mode: 'pool' | 'workbench' | 'deals' | 'knowledge' | 'leads') {
  const reads: string[] = [], writes: { path: string; body: any; method: string }[] = [];
  let batchStatus = 'preview', handoffAttempt = 0, questionAttempt = 0;
  const receipt = { id: 'batch-test-001', filename: 'merchants.csv', status: batchStatus, summary: { pending: 1, isolated: 0, errors: 0, importable: 1 }, rows: [{ row: 2, business_name: 'Sample Cafe', phone: '+12125550123', phone_country: 'US', normalized_phone: '+12125550123', status: 'pending', reason: '', raw: { 商家名称: 'Sample Cafe', 商家电话: '+12125550123', 商家位置: '', 地区: 'New York, NY, US', 来源: 'Maps' } }] };
  await page.addInitScript(emp => { localStorage.setItem('emp_auth_token', 'mock-only'); localStorage.setItem('token', 'mock-only'); localStorage.setItem('emp_auth_data', JSON.stringify(emp)); }, mode === 'workbench' ? { ...employee, id: 27, role: 'sales' } : employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (request.method() === 'GET') reads.push(path + url.search);
    else writes.push({ path, body: request.postData() && !path.endsWith('/preview') ? request.postDataJSON() : null, method: request.method() });
    let data: any = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) data = mode === 'workbench' ? { ...employee, id: 27, role: 'sales' } : employee;
    else if (path === '/api/v1/merchant-imports/preview') data = receipt;
    else if (path.endsWith('/batch-test-001/confirm')) { batchStatus = 'committed'; data = { ...receipt, status: batchStatus }; }
    else if (path === '/api/v1/merchant-pool/stats') data = { total: 40, pending: 40, isolated: 0, converted: 0, duplicates: 0, archived: 0 };
    else if (path === '/api/v1/merchant-pool') {
      const batch = url.searchParams.has('batch_id'), skip = Number(url.searchParams.get('skip') || 0), limit = Number(url.searchParams.get('limit') || 20);
      data = { items: (batch ? [0] : Array.from({ length: 40 }, (_, i) => i)).slice(skip, skip + limit).map(i => ({ id: i + 1, business_name: i === 0 ? 'Sample Cafe' : `Pool ${i + 1}`, phone: '+12125550123', country: 'US', pool_status: 'pending', city: 'New York' })), total: batch ? 1 : 40 };
    } else if (path.endsWith('/sales-leads/assignees')) data = [{ id: 27, name: '模拟销售' }];
    else if (path.endsWith('/workbench/today')) data = { salesperson: { id: 27, name: '模拟销售' }, quota: 2, assigned_count: 2, completed_count: 1, remaining_count: 1, categories: { unfinished: 1 }, performance: { interested: 0, appointments: 0 }, items: [{ task_id: 901, task_status: 'pending', priority: 'normal', queue_category: 'new', lead }, { task_id: 902, task_status: 'completed', priority: 'normal', queue_category: 'new', lead: { ...lead, id: 502, business_name: 'Already Complete', phone: '+14155550124' } }] };
    else if (path.endsWith('/sales-intelligence/leads/501')) data = { profile: { timezone: 'America/New_York' }, config: { default_contact_start: 9, default_contact_end: 18 } };
    else if (path.endsWith('/call-history')) data = [];
    else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false };
    else if (path.endsWith('/ringcentral/calls/recent')) data = { available: false };
    else if (path === '/api/v1/entities/deals') data = { items: [deal], total: 1 };
    else if (path === '/api/v1/entities/deals/5' && request.method() === 'PUT') data = { ...deal, ...request.postDataJSON() };
    else if (path === '/api/v1/entities/service_progresses') data = { items: [{ id: 91, customer_id: 31, notes: '成交记录 #50', package_name: '基础套餐', service_stage: 'active' }, { id: 92, customer_id: 31, notes: '成交记录 #5', package_name: '基础套餐', service_stage: 'active' }], total: 2 };
    else if (path === '/api/v1/entities/customers' || path.endsWith('/customers/all')) data = { items: [{ id: 31, business_name: 'Sample Cafe', status: 'active', sales_person: employee.name }], total: 1 };
    else if (path.endsWith('/deals/5/handoff')) {
      handoffAttempt++;
      if (handoffAttempt === 1) return route.fulfill({ status: 503, json: { detail: '模拟失败，交接尚未保存' } });
      data = { ...deal, ...request.postDataJSON() };
    } else if (path === '/api/v1/sales-knowledge/articles') data = { items: [{ id: 1, category: '销售准备与开场', title: '先确认负责人', standard_answer: '先确认负责人再说明联系目的。', action_steps: [], related_links: [], tags: [], status: 'published' }], categories: ['销售准备与开场'] };
    else if (path === '/api/v1/sales-knowledge/questions') {
      questionAttempt++;
      if (mode === 'knowledge' && questionAttempt === 1) return route.fulfill({ status: 503, json: { detail: '模拟待解答读取失败' } });
      data = { items: [{ id: 11, question: '真实待解答问题', status: 'open', submitted_by_name: '模拟销售' }] };
    } else if (path.endsWith('/sales-leads/recovery/overview')) data = { items: [], summary: { recoverable: 0, watch: 0, protected: 0, extended: 0, extension_requests: 0 } };
    else if (path === '/api/v1/sales-leads') data = { items: [{ ...lead, assigned_sales_id: 27 }], total: 1 };
    return route.fulfill({ json: data });
  });
  return { reads, writes };
}

test('手机导入后明确分配本批，不包含旧商家且可关闭回到列表', async ({ page }) => {
  const api = await fixture(page, 'pool');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/merchant-pool`);
  await page.getByRole('button', { name: '导入商家数据' }).click();
  await page.getByLabel('商家导入文件').setInputFiles({ name: 'merchants.csv', mimeType: 'text/csv', buffer: Buffer.from('商家名称,商家电话,商家位置,地区,来源\nSample Cafe,+12125550123,,"New York, NY, US",Maps\n') });
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Sample Cafe', { exact: true })).toBeVisible();
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  if (process.env.T24_UI_SCREENSHOT_DIR) { await expect(dialog).toHaveCSS("opacity", "1"); await page.screenshot({ path: `${process.env.T24_UI_SCREENSHOT_DIR}/sales-phone-import.png` }); }
  await dialog.getByRole('button', { name: '确认入池 1 条' }).click();
  await dialog.getByRole('button', { name: '分配本批商家' }).click();
  await expect(page.getByRole('status').filter({ hasText: '本批导入 · merchants.csv' })).toBeVisible();
  await expect(page.getByTestId('merchant-mobile-card')).toHaveCount(1);
  expect(api.reads.some(url => url.includes('merchant-pool?') && url.includes('batch_id=batch-test-001'))).toBe(true);
  expect(api.writes.map(write => write.path)).toEqual(['/api/v1/merchant-imports/preview', '/api/v1/merchant-imports/batch-test-001/confirm']);
});

test('跨页选择保留明确计数，取消选择清除全部范围', async ({ page }) => {
  await fixture(page, 'pool'); await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(`${base}/merchant-pool`);
  await page.getByRole('checkbox', { name: '选择 Sample Cafe', exact: true }).check();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await page.getByRole('checkbox', { name: '选择 Pool 21', exact: true }).check();
  await expect(page.getByText('跨页已选 2 家商家')).toBeVisible();
  await page.getByRole('button', { name: '取消选择', exact: true }).click();
  await expect(page.getByRole('region', { name: '商家批量操作' })).toHaveCount(0);
});

test('电脑拨打队列支持未完成和搜索，当地时间与快捷回访只改草稿', async ({ page }) => {
  const api = await fixture(page, 'workbench'); await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(`${base}/sales-workbench`);
  await expect(page.getByRole('heading', { name: 'Sample Cafe', exact: true })).toBeVisible();
  const queue = page.locator('.sc-queue');
  await queue.getByRole('button', { name: '未完成', exact: true }).click();
  await expect(queue.getByText('Already Complete')).toHaveCount(0);
  await queue.getByPlaceholder('搜索商家或电话').fill('4155550124');
  await expect(queue.getByText('Sample Cafe')).toHaveCount(0);
  await queue.getByRole('button', { name: '全部', exact: true }).click();
  await expect(queue.getByText('Already Complete')).toBeVisible();
  await expect(page.locator('.sales-local-time')).toContainText('当地');
  await page.getByRole('button', { name: '待回访', exact: true }).click();
  await page.getByRole('button', { name: '1小时后', exact: true }).click();
  await expect(page.getByLabel('下次跟进 · 北京时间 *')).not.toHaveValue('');
  await expect(page.locator('.sales-followup-quick')).toContainText('商家当地');
  if (process.env.T24_UI_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.T24_UI_SCREENSHOT_DIR}/sales-desktop-queue.png` });
  expect(api.writes).toEqual([]);
  await page.getByRole('button', { name: '话术', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('销售准备与开场');
  await expect.poll(() => api.reads.some(url => url.includes('sales-knowledge/articles?') && new URL(url, base).searchParams.get('category') === '销售准备与开场')).toBe(true);
});

test('手机交接短表单失败保留、取消拦截、重试仅提交四个交接字段', async ({ page }) => {
  const api = await fixture(page, 'deals'); await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`${base}/deals`);
  await page.getByRole('button', { name: '编辑交接', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('spinbutton')).toHaveCount(0);
  await dialog.getByLabel('交接备注').fill('需要运营核对素材');
  if (process.env.T24_UI_SCREENSHOT_DIR) { await expect(dialog).toHaveCSS("opacity", "1"); await page.screenshot({ path: `${process.env.T24_UI_SCREENSHOT_DIR}/sales-phone-handoff.png` }); }
  page.once('dialog', native => native.dismiss());
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '保存交接' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('模拟失败，交接尚未保存');
  await expect(dialog.getByLabel('交接备注')).toHaveValue('需要运营核对素材');
  await dialog.getByRole('button', { name: '保存交接' }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.writes).toHaveLength(2);
  for (const write of api.writes) { expect(write.method).toBe('PATCH'); expect(write.path).toBe('/api/v1/entities/deals/5/handoff'); expect(Object.keys(write.body).sort()).toEqual(['is_handed_over', 'is_transferred_ops', 'needs_group', 'notes']); }
});

test('已有看板匹配完整成交编号并打开正确详情，不再生成', async ({ page }) => {
  const api = await fixture(page, 'deals'); await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`${base}/deals?paid=paid`);
  await page.getByRole('button', { name: '查看看板', exact: true }).click();
  await expect(page).toHaveURL(/service-board\?progress_id=92&returnTo=/);
  expect(api.writes).toEqual([]);
});

test('跟进列表时间范围写入服务器完整筛选，保留来源与查询状态', async ({ page }) => {
  const api = await fixture(page, 'leads'); await page.goto(`${base}/sales-leads?search=Sample&returnTo=${encodeURIComponent('/sales-workbench?sales_employee_id=27')}`);
  await page.getByRole('button', { name: '今天需跟进', exact: true }).click();
  await expect.poll(() => api.reads.some(url => url.includes('/sales-leads?') && url.includes('due_range=today') && url.includes('search=Sample'))).toBe(true);
  await expect(page).toHaveURL(/due_range=today/);
  await page.reload();
  await expect(page.getByRole('button', { name: '今天需跟进', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '返回拨打位置', exact: true }).click();
  await expect(page).toHaveURL(/sales-workbench\?sales_employee_id=27/);
  expect(api.writes).toEqual([]);
});

test('待解答读取失败明确显示并支持恢复', async ({ page }) => {
  const api = await fixture(page, 'knowledge'); await page.goto(`${base}/sales-knowledge`);
  await expect(page.getByRole('alert').filter({ hasText: '待解答问题暂不可用' })).toBeVisible();
  await page.getByRole('button', { name: '重新加载问题' }).click();
  await page.getByText('待解答问题', { exact: false }).first().click();
  await expect(page.getByText('真实待解答问题', { exact: true })).toBeVisible();
  expect(api.writes).toEqual([]);
});


test('完整成交金额修改明确显示前后差异，取消不提交，确认仍使用原完整编辑接口', async ({ page }) => {
  const api = await fixture(page, 'deals'); await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`${base}/deals`);
  await page.getByRole('button', { name: '编辑成交', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('spinbutton').fill('399');
  let confirmation = '';
  page.once('dialog', native => { confirmation = native.message(); return native.dismiss(); });
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  expect(confirmation).toContain('成交金额：299 → 399');
  expect(confirmation).toContain('按现有规则同步收款记录');
  expect(api.writes).toEqual([]);
  await expect(dialog.getByRole('spinbutton')).toHaveValue('399');
  page.once('dialog', native => native.accept());
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.writes).toHaveLength(1);
  expect(api.writes[0]).toMatchObject({ path: '/api/v1/entities/deals/5', method: 'PUT', body: { deal_amount: 399, is_paid: true } });
});

test('话术复制后最近使用只存ID，编辑关闭取消继续编辑，明确放弃后关闭', async ({ page, context }) => {
  const api = await fixture(page, 'knowledge'); await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: base }); await page.goto(`${base}/sales-knowledge`);
  await page.getByRole('button', { name: '复制短版话术' }).click();
  await expect(page.getByLabel('最近使用话术')).toBeVisible();
  const stored = await page.evaluate(() => Object.entries(sessionStorage).find(([key]) => key.includes('knowledge-recent'))?.[1]);
  expect(JSON.parse(stored || '[]')).toEqual([1]);
  await page.getByRole('button', { name: '编辑知识卡', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('标题', { exact: true }).fill('尚未保存的标题');
  page.once('dialog', native => native.dismiss());
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog.getByLabel('标题', { exact: true })).toHaveValue('尚未保存的标题');
  page.once('dialog', native => native.accept());
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.writes).toEqual([]);
});
