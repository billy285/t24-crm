import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5187';
const manager = { id: 10, name: '合成核验主管', role: 'sales_manager', status: 'active' };
const originalName = '店名待核验｜NY 美甲招聘联系点（联系号2125550123）';
const source = { source_url: 'https://example.com/public-hiring/482', source_date: '2024-07-10', verification_type: 'recruitment_contact', source_label: '中文招聘待核验', imported_at: '2026-11-10T09:50:00Z' };
const initialQuality = () => ({ revision: 0, status: 'pending', verified_at: null as string | null, verified_by_id: null as number | null, verified_by_name: null as string | null, method: null as string | null, notes: '', corrected_fields: { business_name: null, address: null, contact_name: null, chinese_service: 'unknown' } });
type Write = { path: string; method: string; body: any };
async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }); }

async function seed(page: Page, options: { conflict?: boolean; readOnly?: boolean; many?: boolean } = {}) {
  await page.addInitScript(emp => { localStorage.setItem('token', 'synthetic-quality-token'); localStorage.setItem('emp_auth_token', 'synthetic-quality-token'); localStorage.setItem('emp_auth_data', JSON.stringify(emp)); }, manager);
  const base = { phone: '+12125550123', country: 'US', industry: '美业', state: 'NY', city: null, address: '街道地址待核验（中文招聘来源）', data_source: 'csv', collected_at: '2026-11-10T09:50:00Z', pool_status: 'pending', converted_lead_id: null as number | null, timezone: 'America/New_York', timezone_group: 'eastern', timezone_basis: 'address_state', timezone_needs_confirmation: true };
  const records = options.many ? Array.from({ length: 23 }, (_, n) => ({ ...base, id: n + 1, business_name: `合成核验联系点${n + 1}`, prospect_quality: { ...initialQuality(), status: n === 21 ? 'valid' : n === 22 ? 'invalid_phone' : 'pending', revision: n >= 21 ? 1 : 0 }, prospect_source: { ...source } })) : [{ ...base, id: 1, business_name: originalName, prospect_quality: initialQuality(), prospect_source: { ...source } }];
  const history = new Map<number, any[]>();
  const writes: Write[] = [], queries: URLSearchParams[] = [], qualityReads: number[] = [], previews: string[] = [];
  let conflicted = false;
  const view = (record: typeof records[number]) => ({ entity_kind: 'pool', entity_id: record.id, prospect_quality: record.prospect_quality, prospect_source: record.prospect_source, effective_fields: { business_name: record.business_name, address: record.address, contact_name: (record as any).contact_name || '', chinese_service: record.prospect_quality.corrected_fields.chinese_service }, can_edit: !options.readOnly, read_only_reason: options.readOnly ? '该商家已离开待分配池，请在线索中核验' : null, contact_protection: { can_contact: true }, history: history.get(record.id) || [] });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    if (path.startsWith('/api/v1/sales-pool-dispatch/') && method === 'POST') {
      const body = request.postDataJSON(); writes.push({ path, method, body });
      const selected = records.filter(r => body.merchant_ids.includes(r.id));
      if (path.endsWith('/preview')) return json(route, { target_date: '2026-11-10', plan_sha256: 'a'.repeat(64), assigned_count: selected.length, unassigned_count: 0, policy: '按剩余容量均衡安排', assignments: selected.map(r => ({ merchant_id: r.id, business_name: r.business_name, sales_employee_id: 11, salesperson: '合成销售', timezone_group: 'eastern', queue_reason: '建议联系时段内', completeness: 1, quality_status: r.prospect_quality.status })), unassigned: [], employees: [{ sales_employee_id: 11, salesperson: '合成销售', quota: 100, today_tasks: 0, existing_pending_load: 0, reserved_existing: 0, remaining: 100, assigned_count: selected.length, timezones: { eastern: selected.length } }] });
      if (path.endsWith('/confirm') && body.plan_sha256 === 'a'.repeat(64)) {
        selected.forEach(r => { r.pool_status = 'converted'; r.converted_lead_id = r.id + 100; });
        return json(route, { assigned_count: selected.length, created_tasks: selected.length });
      }
      return json(route, { detail: '派单预览已变化，请重新核对' }, 409);
    }
    if (path === '/api/v1/merchant-imports/preview' && method === 'POST') {
      const body = request.postData() || ''; previews.push(body); writes.push({ path, method, body });
      const industry = body.match(/name="default_industry"\r?\n\r?\n([^\r\n]+)/)?.[1];
      return json(route, { id: 'synthetic-source-import', filename: 'source.csv', status: 'preview', row_count: 1, created_at: '2026-11-10T10:00:00Z', import_defaults: industry ? { industry } : {}, template_headers: ['商家名称', '商家电话', '商家位置', '地区', '来源', '来源URL', '来源日期', '核验类型'], summary: { pending: 1, isolated: 0, errors: 0, importable: 1 }, rows: [{ row: 2, business_name: '合成导入联系点', phone: '+12125550123', normalized_phone: '+12125550123', phone_country: 'US', phone_status: 'valid', status: 'pending', reason: '待人工核对；尚未分配销售', warnings: [], raw: { 商家名称: '合成导入联系点', 商家电话: '+12125550123', 商家位置: '街道地址待核验', 地区: 'NY, US', 来源: '中文招聘', 来源URL: source.source_url, 来源日期: source.source_date, 核验类型: '招聘联系点' }, source_metadata: { source_url: source.source_url, source_date: source.source_date, verification_type: 'recruitment_contact' } }] });
    }
    const verification = path.match(/^\/api\/v1\/prospect-verification\/pool\/(\d+)$/);
    if (verification) {
      const record = records.find(r => r.id === Number(verification[1]));
      if (!record) return json(route, { detail: '模拟记录不存在' }, 404);
      if (method === 'GET') { qualityReads.push(record.id); return json(route, view(record)); }
      const body = request.postDataJSON(); writes.push({ path, method, body });
      if (method !== 'PATCH' || options.readOnly) return json(route, { detail: '只读记录不能保存' }, 409);
      if (options.conflict && !conflicted) {
        conflicted = true; record.prospect_quality = { ...initialQuality(), revision: 1, status: 'pending', notes: '他人刚确认了联系地区', verified_by_id: 99, verified_by_name: '其他核验员' };
        return json(route, { detail: '核验已被其他人更新，请读取最新记录后再保存；本次输入未写入' }, 409);
      }
      if (body.expected_revision !== record.prospect_quality.revision) return json(route, { detail: '版本冲突，请读取最新记录' }, 409);
      const revision = record.prospect_quality.revision + 1;
      record.prospect_quality = { ...record.prospect_quality, revision, status: body.status, notes: body.notes, method: body.method, verified_at: '2026-11-10T10:00:00Z', verified_by_id: manager.id, verified_by_name: manager.name, corrected_fields: { ...record.prospect_quality.corrected_fields, ...body.corrected_fields } };
      for (const key of ['business_name', 'address', 'contact_name']) if (body.corrected_fields[key]) (record as any)[key] = body.corrected_fields[key];
      history.set(record.id, [{ revision, created_at: '2026-11-10T10:00:00Z', actor: { name: manager.name }, after: { status: body.status, notes: body.notes } }, ...(history.get(record.id) || [])]);
      return json(route, view(record));
    }
    if (method !== 'GET') { writes.push({ path, method, body: request.postData() }); return json(route, { detail: '本测试禁止其他业务写入' }, 400); }
    if (path.endsWith('/emp-auth/me')) return json(route, manager);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.endsWith('/sales-leads/assignees')) return json(route, [{ id: 11, name: '合成销售' }]);
    if (path === '/api/v1/merchant-pool/stats') return json(route, { total: records.length, pending: records.filter(r => r.pool_status === 'pending').length, converted: records.filter(r => r.pool_status === 'converted').length, isolated: 0, duplicates: 0, archived: 0 });
    if (path === '/api/v1/merchant-imports') return json(route, { items: [] });
    if (path === '/api/v1/merchant-pool') {
      queries.push(url.searchParams);
      const scope = records.filter(r => (!url.searchParams.get('pool_status') || r.pool_status === url.searchParams.get('pool_status')) && (!url.searchParams.get('source') || r.data_source === url.searchParams.get('source')) && (!url.searchParams.get('industry') || r.industry === url.searchParams.get('industry')));
      const qualityFacets = { pending: 0, valid: 0, invalid_phone: 0, not_target: 0, closed: 0 };
      scope.forEach(r => { qualityFacets[r.prospect_quality.status as keyof typeof qualityFacets]++; });
      const selected = url.searchParams.get('quality_status'); const matching = scope.filter(r => !selected || r.prospect_quality.status === selected);
      const skip = Number(url.searchParams.get('skip') || 0), limit = Number(url.searchParams.get('limit') || 20);
      return json(route, { items: matching.slice(skip, skip + limit), total: matching.length, skip, limit, industry_facets: [{ value: '美业', label: '美业', count: matching.length }], facet_total: matching.length, quality_facets: qualityFacets });
    }
    return json(route, { items: [], total: 0 });
  });
  return { records, writes, queries, qualityReads, previews };
}
async function openRecord(page: Page, name = originalName) {
  await page.getByRole('button', { name: `查看资料：${name}`, exact: true }).click();
  const section = page.getByRole('region', { name: '首拨核验', exact: true });
  await expect(section).toContainText('招聘联系点 · 店名及地址待确认');
  await section.getByRole('button', { name: '核验门店资料', exact: true }).click();
  await expect(section.getByLabel('首拨核验结果', { exact: true })).toBeVisible();
  return section;
}
async function noOverflow(page: Page) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(sizes.document).toBeLessThanOrEqual(sizes.viewport); expect(sizes.body).toBeLessThanOrEqual(sizes.viewport);
}

test('池首拨待核验保存为有效，刷新后保留来源、原核验人与修订历史', async ({ page }) => {
  const state = await seed(page); await page.goto(`${baseUrl}/merchant-pool`); const section = await openRecord(page);
  await section.getByLabel('首拨核验结果', { exact: true }).selectOption('valid');
  await section.getByLabel('核验实际店名', { exact: true }).fill('合成美容店 Synthetic Nails');
  await section.getByLabel('核验实际地址', { exact: true }).fill('123 Synthetic Ave, New York, NY');
  await section.getByLabel('核验联系人', { exact: true }).fill('合成店长');
  await section.getByLabel('核验中文服务', { exact: true }).selectOption('yes');
  await section.getByLabel('首拨核验依据', { exact: true }).fill('已接通公开电话，店长确认店名、地址与中文服务。');
  await section.getByRole('button', { name: '保存核验', exact: true }).click();
  await expect(section).toContainText('核验结果已保存');
  const patch = state.writes.filter(x => x.method === 'PATCH'); expect(patch).toHaveLength(1);
  expect(patch[0].body).toMatchObject({ expected_revision: 0, status: 'valid', method: 'call', corrected_fields: { chinese_service: 'yes', business_name: '合成美容店 Synthetic Nails' } });
  await page.reload(); const persisted = await openRecord(page, '合成美容店 Synthetic Nails');
  await expect(persisted.getByLabel('首拨核验结果', { exact: true })).toHaveValue('valid');
  await expect(persisted.getByLabel('核验实际地址', { exact: true })).toHaveValue('123 Synthetic Ave, New York, NY');
  await expect(persisted).toContainText('来源日期 2024-07-10'); await expect(persisted).toContainText(`最近核验：${manager.name}`);
  await persisted.getByText('核验修改历史（1）', { exact: true }).click(); await expect(persisted).toContainText('已接通公开电话，店长确认店名、地址与中文服务。');
  expect(state.writes.every(x => x.path === '/api/v1/prospect-verification/pool/1')).toBeTruthy();
});

test('409保留全部输入，显式读取最新修订后才能再次保存', async ({ page }) => {
  const state = await seed(page, { conflict: true }); await page.goto(`${baseUrl}/merchant-pool`); const section = await openRecord(page);
  await section.getByLabel('首拨核验结果', { exact: true }).selectOption('valid'); await section.getByLabel('核验实际店名', { exact: true }).fill('本次保留店名'); await section.getByLabel('首拨核验依据', { exact: true }).fill('本次输入必须保留，等待核对他人修订。');
  const beforeReads = state.qualityReads.length; await section.getByRole('button', { name: '保存核验', exact: true }).click();
  await expect(section.getByRole('alert')).toContainText('核验已被其他人更新'); await expect(section.getByLabel('核验实际店名', { exact: true })).toHaveValue('本次保留店名'); await expect(section.getByLabel('首拨核验依据', { exact: true })).toHaveValue('本次输入必须保留，等待核对他人修订。');
  await expect(section.getByRole('button', { name: '保存核验', exact: true })).toBeDisabled(); expect(state.qualityReads.length).toBe(beforeReads); expect(state.writes.filter(x => x.method === 'PATCH')).toHaveLength(1);
  await section.getByRole('button', { name: '读取最新记录', exact: true }).click(); await expect(section).toContainText('已读取最新记录并保留本次输入');
  await expect(section.getByLabel('首拨核验依据', { exact: true })).toHaveValue('本次输入必须保留，等待核对他人修订。'); await expect(section.getByLabel('首拨核验结果', { exact: true })).toHaveValue('valid');
  await section.getByRole('button', { name: '保存核验', exact: true }).click(); await expect(section).toContainText('核验结果已保存');
  expect(state.writes.filter(x => x.method === 'PATCH').map(x => x.body.expected_revision)).toEqual([0, 1]);
});

test('服务端只读核验资料可读，字段与保存全部禁用且不发送PATCH', async ({ page }) => {
  const state = await seed(page, { readOnly: true }); await page.goto(`${baseUrl}/merchant-pool`); const section = await openRecord(page);
  await expect(section).toContainText('该商家已离开待分配池'); await expect(section.getByLabel('首拨核验结果', { exact: true })).toBeDisabled(); await expect(section.getByLabel('首拨核验依据', { exact: true })).toBeDisabled(); await expect(section.getByRole('button', { name: '保存核验', exact: true })).toBeDisabled(); expect(state.writes).toEqual([]);
});

for (const width of [320, 390, 1093]) test(`${width}px来源身份、日期和核验表单无横向溢出`, async ({ page }) => {
  await seed(page); await page.setViewportSize({ width, height: 900 }); await page.goto(`${baseUrl}/merchant-pool`); await noOverflow(page); const section = await openRecord(page);
  await expect(section).toContainText('招聘联系点 · 店名及地址待确认'); await expect(section).toContainText('来源日期 2024-07-10'); await expect(section.getByRole('link', { name: '查看原始来源', exact: true })).toHaveAttribute('href', source.source_url); await expect(section).toContainText('招聘广告日期不代表当前营业状态'); await noOverflow(page);
  const bounds = await section.boundingBox(); expect(bounds).not.toBeNull(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
  await page.screenshot({ path: test.info().outputPath(`prospect-verification-${width}.png`), fullPage: true, animations: 'disabled' });
});

test('quality_status使用服务端facets并清除跨页选择、回第一页、保留行业来源批次', async ({ page }) => {
  const state = await seed(page, { many: true }); await page.goto(`${baseUrl}/merchant-pool?batch_id=synthetic-quality-batch`);
  await page.getByRole('navigation', { name: '行业分类' }).getByRole('button', { name: /^美业/ }).click(); await page.getByRole('button', { name: /^更多筛选/ }).click(); await page.getByRole('combobox', { name: '筛选资料来源', exact: true }).selectOption('csv');
  await page.getByRole('checkbox', { name: '选择 合成核验联系点1', exact: true }).check(); await page.getByRole('button', { name: '下一页', exact: true }).click(); await page.getByRole('checkbox', { name: '选择 合成核验联系点21', exact: true }).check(); await expect(page.getByRole('region', { name: '商家批量操作' })).toContainText('跨页已选 2 家商家');
  const quality = page.getByRole('combobox', { name: '筛选首拨核验', exact: true }); await expect(quality.locator('option[value="pending"]')).toHaveText('待核验 21'); await expect(quality.locator('option[value="valid"]')).toHaveText('有效门店 1'); await quality.selectOption('valid');
  await expect(page.getByRole('button', { name: '查看资料：合成核验联系点22', exact: true })).toBeVisible(); await expect(page.getByRole('region', { name: '商家批量操作' })).toHaveCount(0); await expect.poll(() => state.queries.at(-1)?.get('quality_status')).toBe('valid');
  const query = state.queries.at(-1)!; expect(query.get('skip')).toBe('0'); expect(query.get('industry')).toBe('美业'); expect(query.get('source')).toBe('csv'); expect(query.get('batch_id')).toBe('synthetic-quality-batch'); await expect(page.locator('.mp-quality-summary')).toContainText('待核验 21'); await expect(page.locator('.mp-quality-summary')).toContainText('有效门店 1'); expect(state.writes).toEqual([]);
});

test('导入默认行业随preview发送，扩展来源可审阅且确认前不提交入池', async ({ page }) => {
  const state = await seed(page); await page.goto(`${baseUrl}/merchant-pool`); await page.getByRole('button', { name: '导入商家数据', exact: true }).click(); const dialog = page.getByRole('dialog', { name: '按固定模板导入商家', exact: true });
  await dialog.getByLabel('导入默认行业', { exact: true }).selectOption('美业');
  const csv = `商家名称,商家电话,商家位置,地区,来源,来源URL,来源日期,核验类型\r\n合成导入联系点,+12125550123,街道地址待核验,"NY, US",中文招聘,${source.source_url},${source.source_date},招聘联系点\r\n`;
  await page.getByLabel('商家导入文件', { exact: true }).setInputFiles({ name: 'source.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await expect(dialog).toContainText('本批默认行业：美业'); await expect(dialog).toContainText('资料日期：2024-07-10'); await expect(dialog).toContainText('招聘联系点 · 人工待核验'); await expect(dialog.getByRole('link', { name: '原始来源资料', exact: true })).toHaveAttribute('href', source.source_url);
  expect(state.previews).toHaveLength(1); expect(state.previews[0]).toMatch(/name="default_industry"\r?\n\r?\n美业/); expect(state.previews[0]).toContain(csv); expect(state.writes.map(x => x.path)).toEqual(['/api/v1/merchant-imports/preview']);
});

test('320px均衡派单预览不改变商家，明确确认后才提交计划并清除选择', async ({ page }) => {
  const state = await seed(page); await page.setViewportSize({ width: 320, height: 900 }); await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('button', { name: `分配：${originalName}`, exact: true }).click();
  await page.getByRole('region', { name: '商家批量操作' }).getByRole('button', { name: '均衡派单', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '按剩余容量均衡派单', exact: true });
  await expect(dialog).toBeVisible(); await expect(dialog.getByRole('button', { name: /^确认分配0条/ })).toBeDisabled();
  await dialog.getByRole('checkbox', { name: '合成销售', exact: true }).check(); await dialog.getByRole('button', { name: '生成派单预览', exact: true }).click();
  await expect(dialog).toContainText('本次安排 1 条'); await expect(dialog).toContainText('确认时将重新核对权限');
  expect(state.records[0].pool_status).toBe('pending'); expect(state.writes.map(x => x.path)).toEqual(['/api/v1/sales-pool-dispatch/preview']);
  await noOverflow(page); const bounds = await dialog.boundingBox(); expect(bounds).not.toBeNull(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
  await page.screenshot({ path: test.info().outputPath('dispatch-preview-320.png'), fullPage: true, animations: 'disabled' });
  const dialogWidths = await dialog.evaluate(node => ({ content: node.scrollWidth, visible: node.clientWidth }));
  expect(dialogWidths.content, '派单对话框本身不可横向溢出；宽表格应只在自己的容器滚动').toBeLessThanOrEqual(dialogWidths.visible);
  await dialog.getByRole('button', { name: '确认分配1条并创建今日任务', exact: true }).click();
  await expect(dialog).toHaveCount(0); await expect(page.getByRole('region', { name: '商家批量操作' })).toHaveCount(0);
  expect(state.writes.map(x => x.path)).toEqual(['/api/v1/sales-pool-dispatch/preview', '/api/v1/sales-pool-dispatch/confirm']);
  expect(state.writes[1].body).toEqual({ merchant_ids: [1], sales_ids: [11], plan_sha256: 'a'.repeat(64) }); expect(state.records[0].pool_status).toBe('converted');
  await expect(page.getByRole('button', { name: `查看资料：${originalName}`, exact: true })).toHaveCount(0);
});
