import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs/promises';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const employee = { id: 1, name: '测试管理员', role: 'super_admin', status: 'active' };
const lead = { id: 31, business_name: 'Garden Follow-up', phone: '+12025550123', country: 'US', status: 'interested', assigned_sales_id: 11, assigned_sales_name: '测试销售', next_follow_up_at: '2026-10-12T01:00:00Z', created_at: '2026-10-01T00:00:00Z', do_not_contact: false, is_blacklisted: false, converted_customer_id: null };
async function seed(page: Page, options: { failSave?: boolean; returnedLead?: Partial<typeof lead>; failRemove?: boolean; singleLeadPatch?: Partial<typeof lead>; readinessPatch?: Partial<typeof lead> } = {}) {
  const writes: { path: string; data: any }[] = [], reads: string[] = [];
  let user = { ...employee }, current = { ...lead, ...options.returnedLead };
  await page.addInitScript(({ emp, failRemove }) => {
    localStorage.setItem('emp_auth_token', 'isolated-test'); localStorage.setItem('token', 'isolated-test'); localStorage.setItem('emp_auth_data', JSON.stringify(emp));
    if (failRemove) { const original = Storage.prototype.removeItem; Storage.prototype.removeItem = function(key) { if (key.startsWith('t24.sales-followup.')) throw new Error('storage remove blocked'); return original.call(this, key); }; }
  }, { emp: employee, failRemove: !!options.failRemove });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    if (req.method() !== 'GET') writes.push({ path, data: req.postDataJSON() }); else reads.push(path);
    let data: any = { items: [], total: 0 };
    if (path === '/api/config') data = { API_BASE_URL: base };
    else if (path.endsWith('/emp-auth/me')) data = user;
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path === '/api/v1/sales-leads') data = { items: [current], total: 1 };
    else if (path === '/api/v1/sales-leads/31') data = { ...current, ...options.singleLeadPatch };
    else if (/sales-leads\/(dashboard|reports|recovery)\//.test(path) || path.endsWith('/performance')) data = null;
    else if (path.endsWith('/sales-leads/stats')) data = { total: 1, assigned: 1, unassigned: 0 };
    else if (path.endsWith('/sales-leads/assignees')) data = [{ id: 11, name: '测试销售', role: 'sales' }];
    else if (path.endsWith('/call-history')) data = [];
    else if (path.endsWith('/follow-up')) {
      if (options.failSave) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
      const payload = req.postDataJSON(); current = { ...current, status: payload.outcome, next_follow_up_at: payload.next_follow_up_at };
      data = { status: current.status, next_follow_up_at: current.next_follow_up_at, lead: current };
    } else if (path.endsWith('/readiness')) data = { lead: { ...current, ...options.readinessPatch }, quotes: [], handoff: {}, blockers: ['需要已审批报价', '需要交接资料'] };
    else if (path.endsWith('/sales-deal-controls/options')) data = { employees: [] };
    else if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    else if (path.endsWith('/sales-intelligence/views')) data = [];
    else if (path.endsWith('/sales-intelligence/leads')) data = { items: [] };
    await route.fulfill({ json: data });
  });
  return { writes, reads, setUser: (id: number) => { user = { ...user, id }; }, setOwner: (id: number) => { current = { ...current, assigned_sales_id: id }; } };
}
async function followup(page: Page) {
  await page.getByRole('button', { name: `记录跟进：${lead.business_name}`, exact: true }).click();
  const sheet = page.getByRole('dialog', { name: lead.business_name, exact: true });
  await expect(sheet).toBeVisible(); return sheet;
}
const notes = (sheet: ReturnType<Page['getByRole']>) => sheet.getByLabel('沟通记录 *', { exact: true });

test('回访草稿跨关闭、刷新和路由恢复，成功保存仅写一次并清空', async ({ page }) => {
  const data = await seed(page); await page.goto(`${base}/sales-leads`);
  const sheet = await followup(page); await notes(sheet).fill('客户希望先确认预算');
  await expect(sheet.getByRole('status')).toContainText('草稿已暂存'); await page.keyboard.press('Escape'); await expect(sheet).toBeHidden();
  await page.reload(); await followup(page); await expect(notes(sheet)).toHaveValue('客户希望先确认预算');
  await page.keyboard.press('Escape'); await page.goto(`${base}/merchant-pool`); await page.goto(`${base}/sales-leads`);
  await followup(page); await expect(notes(sheet)).toHaveValue('客户希望先确认预算');
  await sheet.getByRole('button', { name: '保存跟进', exact: true }).click(); await expect(notes(sheet)).toHaveValue('');
  expect(data.writes).toHaveLength(1); expect(data.writes[0].path).toBe('/api/v1/sales-leads/31/follow-up');
  await page.keyboard.press('Escape'); await page.reload(); await followup(page); await expect(notes(sheet)).toHaveValue('');
});
for (const scope of ['user', 'owner'] as const) test(`切换${scope}不恢复其他归属草稿`, async ({ page }) => {
  const data = await seed(page); await page.goto(`${base}/sales-leads`); const sheet = await followup(page);
  await notes(sheet).fill('只属于最初账号与销售的记录'); await expect(sheet.getByRole('status')).toContainText('草稿已暂存'); await page.keyboard.press('Escape');
  if (scope === 'user') data.setUser(2); else data.setOwner(12);
  await page.reload(); await followup(page); await expect(notes(sheet)).toHaveValue(''); expect(data.writes).toHaveLength(0);
});
test('保存并准备报价只保存跟进，分步交接切换保留输入', async ({ page }) => {
  const data = await seed(page); await page.goto(`${base}/sales-leads`); const sheet = await followup(page);
  await notes(sheet).fill('客户有意向，先准备方案'); await sheet.getByRole('button', { name: '保存并准备报价', exact: true }).click();
  const deal = page.getByRole('dialog', { name: `成交审核 · ${lead.business_name}` }); await expect(deal).toBeVisible();
  expect(data.writes).toHaveLength(1); expect(data.reads).toContain('/api/v1/sales-deal-controls/31/readiness');
  await expect(deal.getByLabel('客户目标')).toBeHidden(); await deal.getByRole('button', { name: '2 交接', exact: true }).click();
  await deal.getByLabel('客户目标').fill('增加官网预约'); await deal.getByRole('button', { name: '1 报价', exact: true }).click();
  await deal.getByRole('button', { name: '2 交接', exact: true }).click(); await expect(deal.getByLabel('客户目标')).toHaveValue('增加官网预约');
  expect(data.writes).toHaveLength(1);
  page.once('dialog', dialog => dialog.dismiss()); await page.keyboard.press('Escape'); await expect(deal).toBeVisible();
  page.once('dialog', dialog => dialog.accept()); await page.keyboard.press('Escape'); await expect(deal).toBeHidden();
});
test('跟进保存失败仍保留草稿，不能进入报价', async ({ page }) => {
  const data = await seed(page, { failSave: true }); await page.goto(`${base}/sales-leads`); const sheet = await followup(page);
  await notes(sheet).fill('失败也要保留'); await sheet.getByRole('button', { name: '保存并准备报价', exact: true }).click();
  await expect(page.getByText('模拟保存失败', { exact: true })).toBeVisible(); await expect(notes(sheet)).toHaveValue('失败也要保留');
  expect(data.reads.some(path => path.endsWith('/readiness'))).toBe(false); await page.keyboard.press('Escape');
  await page.reload(); await followup(page); await expect(notes(sheet)).toHaveValue('失败也要保留'); expect(data.writes).toHaveLength(1);
});
test('明确丢弃需确认，存储删除失败也不在当前页面复活草稿', async ({ page }) => {
  const data = await seed(page, { failRemove: true }); await page.goto(`${base}/sales-leads`); const sheet = await followup(page);
  await notes(sheet).fill('本次草稿'); await expect(sheet.getByRole('status')).toContainText('草稿已暂存');
  page.once('dialog', dialog => dialog.dismiss()); await sheet.getByRole('button', { name: '清空跟进草稿', exact: true }).click(); await expect(notes(sheet)).toHaveValue('本次草稿');
  page.once('dialog', dialog => dialog.accept()); await sheet.getByRole('button', { name: '清空跟进草稿', exact: true }).click(); await expect(notes(sheet)).toHaveValue('');
  await page.keyboard.press('Escape'); await followup(page); await expect(notes(sheet)).toHaveValue(''); await page.keyboard.press('Escape'); await page.reload(); await followup(page); await expect(notes(sheet)).toHaveValue(''); expect(data.writes).toHaveLength(0);
});
for (const condition of ['converted', 'protected', 'mismatch'] as const) test(`报价直达入口拒绝${condition}线索`, async ({ page }) => {
  const patch = condition === 'converted' ? { converted_customer_id: 90 } : condition === 'protected' ? { do_not_contact: true } : { id: 32 };
  const data = await seed(page, { returnedLead: patch as any }); await page.goto(`${base}/sales-leads?lead_id=31&action=quote`);
  await expect(page.getByText(condition === 'converted' ? '已转为正式客户，请在客户中心继续处理' : condition === 'protected' ? '该商家已停止联系' : '该商机无法读取，请检查归属权限', { exact: true })).toBeVisible();
  expect(data.writes).toHaveLength(0); expect(data.reads.some(path => path.endsWith('/readiness'))).toBe(false);
});
for (const width of [390, 1093, 1920]) test(`跟进直达在${width}px有清晰的记录和报价入口`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); const data = await seed(page);
  await page.goto(`${base}/sales-leads?lead_id=31&action=followup`); const sheet = page.getByRole('dialog', { name: lead.business_name, exact: true });
  await expect(notes(sheet)).toBeVisible(); await notes(sheet).fill('已明确下一步'); await expect(sheet.getByRole('status')).toContainText('草稿已暂存');
  await expect.poll(async () => { const bounds = await sheet.boundingBox(); return !!bounds && bounds.x >= -1 && bounds.x + bounds.width <= width + 1; }).toBe(true);
  const box = await notes(sheet).boundingBox(); expect(box?.height).toBeGreaterThan(150);
  await expect(sheet.getByRole('button', { name: '保存并准备报价', exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.T24_UI_SCREENSHOT_DIR) { await fs.mkdir(process.env.T24_UI_SCREENSHOT_DIR, { recursive: true }); await page.screenshot({ path: `${process.env.T24_UI_SCREENSHOT_DIR}/followup-${width}.png`, animations: 'disabled' }); }
  expect(data.writes).toHaveLength(0);
});
test('全额支付和订金必须明确填写正数实收，不能自动回填报价', async ({ page }) => {
  const data = await seed(page); await page.goto(`${base}/sales-leads?lead_id=31&action=quote`);
  const deal = page.getByRole('dialog', { name: `成交审核 · ${lead.business_name}` }); await expect(deal.getByRole('button', { name: '3 收款确认', exact: true })).toBeVisible();
  await deal.getByRole('button', { name: '3 收款确认', exact: true }).click();
  const status = deal.getByLabel('收款状态', { exact: true }), amount = deal.getByLabel('实收金额', { exact: true }), save = deal.getByRole('button', { name: '保存收款状态', exact: true });
  await status.selectOption('paid'); await save.click(); await expect(page.getByText('请填写已核对的实收金额，不能以报价代替到账', { exact: true })).toBeVisible(); expect(data.writes).toHaveLength(0);
  await amount.fill('0'); await save.click(); expect(data.writes).toHaveLength(0);
  await status.selectOption('deposit_paid'); await save.click(); expect(data.writes).toHaveLength(0);
  await amount.fill('125.50'); await save.click(); await expect.poll(() => data.writes.length).toBe(1);
  expect(data.writes[0]).toMatchObject({ path: '/api/v1/sales-deal-controls/31/handoff/finance-confirmation', data: { payment_status: 'deposit_paid', amount_received: 125.5 } });
});

for (const boundary of ['converted', 'do_not_contact', 'is_blacklisted'] as const) test(`审核读取发现${boundary}时资料只读且无法提交`, async ({ page }) => {
  const data = await seed(page, boundary === 'converted' ? { readinessPatch: { converted_customer_id: 90 } } : { singleLeadPatch: { [boundary]: true } });
  await page.goto(`${base}/sales-leads`); await page.getByRole('button', { name: '准备报价', exact: true }).click();
  const deal = page.getByRole('dialog', { name: `成交审核 · ${lead.business_name}` });
  await expect(deal.getByRole('status')).toContainText('售前资料只读');
  await expect(deal.getByLabel('原报价 *', { exact: true })).toBeDisabled();
  await deal.getByRole('button', { name: '2 交接', exact: true }).click();
  await expect(deal.getByLabel('客户目标')).toBeDisabled();
  await expect(deal.getByRole('button', { name: '保存成交交接清单', exact: true })).toBeDisabled();
  await deal.getByRole('button', { name: '3 收款确认', exact: true }).click();
  await expect(deal.getByRole('button', { name: '保存收款状态', exact: true })).toBeDisabled();
  expect(data.writes).toHaveLength(0);
});
