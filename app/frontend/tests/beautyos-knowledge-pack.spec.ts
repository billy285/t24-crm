import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5187';
const phone = '您好，我们先了解门店预约现在怎样安排，再看是否适合演示。';
const outward = '这是可以直接发给客户的完整答复，只介绍已经核实的使用流程。';
const internal = 'INTERNAL_REVIEW_ONLY：业务规则需要由主管核对，不能发给客户。';
const base = { category: '首拨核验', customer_question: '预约现在怎么管理？', standard_answer: outward, phone_answer: phone, action_steps: ['INTERNAL_ACTION_ONLY'], demo_steps: ['使用合成客户演示预约'], followup_question: '现在主要用电话还是系统？', next_action: '约定演示时间', escalation_rule: 'INTERNAL_ESCALATION_ONLY', internal_notes: internal, related_links: [], tags: ['预约'], product_scope: 'beautyos', store_types: ['通用'], availability: 'ready', high_frequency: true, revision: 1, published_revision: 1, status: 'published', is_sensitive: false, sort_order: 10, published_by_name: '合成主管', published_at: '2026-11-10T12:00:00Z' };

async function setup(page: Page, options: { role?: 'sales' | 'sales_manager'; lostInstallResponse?: boolean; conflict?: boolean } = {}) {
  const emp = { id: 27, name: '合成知识库验收', role: options.role || 'sales_manager', status: 'active' };
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'synthetic-beautyos-knowledge');
    localStorage.setItem('token', 'synthetic-beautyos-knowledge');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, emp);
  const originals = [
    { ...base, id: 101, title: '合成门店首拨开场' },
    { ...base, id: 102, title: '合成医美经营需求', store_types: ['医美经营'], high_frequency: false, availability: 'pending_confirmation' },
    { ...base, id: 103, title: '合成内部资料', is_sensitive: true, high_frequency: false },
    { ...base, id: 5, title: '合成代运营付款说明', product_scope: 'managed_service', high_frequency: false },
  ];
  const pack = Array.from({ length: 60 }, (_, i) => ({ ...base, key: `synthetic-pack-${i}`, id: i + 201, title: `合成美业场景${i + 1}`, high_frequency: i < 20 }));
  const writes: { path: string; method: string; data: any }[] = [], reads: URLSearchParams[] = [];
  let installed = false, currentRevision = 1;
  const hash = 'a'.repeat(64);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    if (req.method() !== 'GET') writes.push({ path, method: req.method(), data: req.postDataJSON() });
    if (path.endsWith('/emp-auth/me')) return json(emp);
    if (path.includes('/app-config')) return json({ items: {} });
    if (path === '/api/v1/sales-knowledge/articles' && req.method() === 'GET') {
      reads.push(url.searchParams);
      let items = [...originals.map(a => ({ ...a, revision: a.id === 101 ? currentRevision : a.revision })), ...(installed ? pack : [])];
      const scope = url.searchParams.get('product_scope'), group = url.searchParams.get('category'), search = url.searchParams.get('query'), store = url.searchParams.get('store_type');
      if (scope) items = items.filter(a => a.product_scope === scope);
      if (url.searchParams.get('high_frequency') === 'true') items = items.filter(a => a.high_frequency);
      if (store) items = items.filter(a => a.store_types.includes('通用') || a.store_types.includes(store));
      const categories = [...new Set(items.map(a => a.category))];
      if (group) items = items.filter(a => a.category === group);
      if (search) items = items.filter(a => `${a.title} ${a.customer_question}`.includes(search));
      return json({ items, categories, total: items.length });
    }
    if (path === '/api/v1/sales-knowledge/beautyos-pack/preview') return json({ pack_id: 'synthetic', version: 'v1', manifest_hash: hash, total: 60, high_frequency_count: 20, existing_count: installed ? 60 : 0, new_count: installed ? 0 : 60, items: pack.map(a => ({ ...a, status: 'draft' })) });
    if (path === '/api/v1/sales-knowledge/beautyos-pack/install') {
      expect(req.postDataJSON()).toEqual({ manifest_hash: hash, publish_now: true });
      installed = true;
      if (options.lostInstallResponse) return json({ detail: '合成响应丢失，请重新预览核对结果' }, 500);
      return json({ installed_count: 60, skipped_count: 0, total: 60, items: pack });
    }
    if (path === '/api/v1/sales-knowledge/articles/101' && req.method() === 'PUT' && options.conflict) {
      currentRevision = 2;
      return json({ detail: '其他主管已更新' }, 409);
    }
    if (path.endsWith('/sales-knowledge/questions')) return json({ items: [] });
    return json({ items: [], total: 0 });
  });
  return { writes, reads };
}

for (const width of [855, 390]) test(`${width}px 对外复制独立短版且不包含内部提醒`, async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
  await page.setViewportSize({ width, height: 824 });
  const api = await setup(page, { role: 'sales' });
  await page.goto(`${baseUrl}/sales-knowledge`);
  await expect(page.getByRole('combobox', { name: '筛选适用产品' })).toHaveValue('beautyos');
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(3);
  expect(api.reads.at(-1)?.get('include_general')).toBe('false');
  await expect(page.getByRole('button', { name: /合成代运营付款说明/ })).toHaveCount(0);
  await page.getByRole('button', { name: /合成门店首拨开场/ }).click();
  const detail = width < 768 ? page.getByRole('dialog') : page.locator('.knowledge-v4-detail');
  await detail.getByRole('button', { name: '复制短版话术' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(phone);
  await detail.getByRole('tab', { name: '完整答复', exact: true }).click();
  await detail.getByRole('button', { name: '复制完整答复' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(outward);
  expect(await page.evaluate(() => navigator.clipboard.readText())).not.toContain('INTERNAL');
  await expect(detail.getByText('现在主要用电话还是系统？', { exact: true })).toBeVisible();
  if (width < 768) await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '新销售必读 20 条', exact: true }).click();
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(1);
  expect(api.reads.at(-1)?.get('high_frequency')).toBe('true');
  await page.getByRole('button', { name: '新销售必读 20 条', exact: true }).click();
  await page.getByRole('combobox', { name: '筛选门店类型' }).selectOption('医美经营');
  await expect(page.getByRole('button', { name: /合成医美经营需求/ })).toBeVisible();
  expect(api.reads.at(-1)?.get('store_type')).toBe('医美经营');
  await page.getByRole('button', { name: /合成内部资料/ }).click();
  const internalDetail = width < 768 ? page.getByRole('dialog') : page.locator('.knowledge-v4-detail');
  await expect(internalDetail.getByText(/这张卡属于内部信息/)).toBeVisible();
  await expect(internalDetail.getByRole('button', { name: '复制完整答复' })).toBeDisabled();
  expect(api.writes).toEqual([]);
  const sizes = await page.evaluate(() => ({ width: innerWidth, doc: document.documentElement.scrollWidth }));
  expect(sizes.doc).toBeLessThanOrEqual(sizes.width);
  await page.screenshot({ path: test.info().outputPath(`knowledge-${width}.png`), animations: 'disabled' });
});

test('话术包只预览不写入，明确添加后保留原卡且阻止重复添加', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`${baseUrl}/sales-knowledge`);
  await page.getByRole('button', { name: '美业 OS 话术包', exact: true }).click();
  const pack = page.getByRole('dialog', { name: '美业 OS 销售话术包' });
  await expect(pack.getByText('本次新增 60 条', { exact: true })).toBeVisible();
  expect(api.writes.filter(w => w.path.endsWith('/install'))).toHaveLength(0);
  await pack.getByRole('button', { name: '添加并发布 60 条话术' }).click();
  await expect(pack.getByRole('status')).toContainText('已添加并发布 60 条');
  await expect(pack.getByRole('button', { name: '话术已全部添加' })).toBeDisabled();
  await pack.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(63);
  await expect(page.getByRole('button', { name: /合成门店首拨开场/ })).toBeVisible();
  expect(api.writes.filter(w => w.path.endsWith('/install'))).toHaveLength(1);
});

test('添加响应丢失后重新预览核对已存在数量，不盲目重复发布', async ({ page }) => {
  const api = await setup(page, { lostInstallResponse: true });
  await page.goto(`${baseUrl}/sales-knowledge`);
  await page.getByRole('button', { name: '美业 OS 话术包', exact: true }).click();
  const pack = page.getByRole('dialog', { name: '美业 OS 销售话术包' });
  await pack.getByRole('button', { name: '添加并发布 60 条话术' }).click();
  await expect(pack.getByRole('alert')).toBeVisible();
  await pack.getByRole('button', { name: '重新预览' }).click();
  await expect(pack.getByText('已存在 60 条', { exact: true })).toBeVisible();
  await expect(pack.getByRole('button', { name: '话术已全部添加' })).toBeDisabled();
  expect(api.writes.filter(w => w.path.endsWith('/install'))).toHaveLength(1);
});

test('主管编辑遇到修订冲突保留输入，读取最新内容不自动覆盖', async ({ page }) => {
  const api = await setup(page, { conflict: true });
  await page.goto(`${baseUrl}/sales-knowledge`);
  await page.getByRole('button', { name: '编辑知识卡', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '编辑知识卡' });
  await editor.getByLabel('标题', { exact: true }).fill('保留本次草稿');
  await editor.getByLabel('完整对外答复', { exact: true }).fill('本次客户答复修改必须保留。');
  await editor.getByRole('button', { name: '保存知识卡' }).click();
  await expect(editor.getByRole('alert')).toContainText('当前输入已保留');
  await expect(editor.getByLabel('标题', { exact: true })).toHaveValue('保留本次草稿');
  await editor.getByRole('button', { name: '查看最新版本' }).click();
  await expect(editor.getByText(/最新修订 2/)).toBeVisible();
  await expect(editor.getByLabel('完整对外答复', { exact: true })).toHaveValue('本次客户答复修改必须保留。');
  expect(api.writes.find(w => w.method === 'PUT')?.data.expected_revision).toBe(1);
});
