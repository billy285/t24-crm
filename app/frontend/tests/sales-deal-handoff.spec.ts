import { expect, test, type Locator, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_HANDOFF_BASE_URL || 'http://127.0.0.1:8917';
const tokenA = 'a'.repeat(64);
const tokenB = 'b'.repeat(64);
const plan = { id: 9, product_id: 5, name: '统一基础套餐', standard_price: 499, default_currency: 'USD', default_billing_cycle: 'monthly', platform_limit: 2, scope_type: 'selected', catalog_token: tokenA, required_collection_method: 'stripe_auto', service_period_months: 1 };
const allModules = ['basic', 'contacts', 'followups', 'opportunities', 'delivery', 'renewals', 'deals', 'materials'];
type Scenario = { owner?: boolean; role?: string; modules?: string[]; emptyCatalog?: boolean; canRegister?: boolean; conflict?: boolean; lostResponse?: boolean; retryableFailure?: boolean; holdRegistration?: boolean; planOverride?: Record<string, any>; subscriptions?: Record<string, any>[]; receipt?: Record<string, any>; source?: Record<string, any> };
async function json(route: Route, data: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) }); }
async function fixture(page: Page, options: Scenario = {}) {
  const owner = options.owner === true;
  const employee = { id: owner ? 1 : options.role === 'ops' ? 7 : 2, name: owner ? '验收老板' : options.role === 'ops' ? '验收运营' : '验收销售', role: owner ? 'super_admin' : options.role || 'sales', status: 'active' };
  const modules = options.modules || (owner ? allModules : ['basic', 'deals']);
  const permissions = { access_level: 'read_only', modules: Object.fromEntries(allModules.map(key => [key, { read: modules.includes(key), write: false }])), finance_access: owner ? 'profit' : 'none', can_manage_access: owner, can_delete: false, can_export: false, can_reassign: false, sources: [], invitation_status: 'active', invitation_source: 'owner_invitation' };
  const customer = { id: 301, customer_code: 'T24-301', business_name: '成交验收餐厅', contact_name: '陈老板', phone: '+1 310 555 0111', country: 'US', industry: 'restaurant', status: 'closed', effective_permissions: permissions };
  let registered = false;
  let catalogRevision = 0;
  let registrationCount = 0;
  let accepted = false;
  let paid = false;
  let releaseRegistration = () => {};
  const registrationGate = new Promise<void>(resolve => { releaseRegistration = resolve; });
  const writes: { path: string; body: any }[] = [];
  const reads: string[] = [];
  const currentReceipt = () => ({ id: 81, lead_id: 21, customer_id: 301, engagement_id: 61, deal_id: 71, package_name: plan.name, billing_cycle: 'monthly', amount: options.planOverride?.standard_price ?? (catalogRevision > 1 ? 529 : 499), currency: 'USD', operations_owner_employee_id: 7, operations_owner_name: '验收运营', operations_status: accepted ? 'accepted' : 'pending', operations_access_status: options.role === 'ops' ? 'authorized' : 'pending', can_view_customer: owner || options.role === 'ops', can_view_history: false, history_url: null, can_finance_confirm: owner && !paid, can_operations_ack: options.role === 'ops' && !accepted, ...(owner ? { payment_status: paid ? 'paid' : 'pending' } : {}), ...(accepted ? { operations_acknowledged_at: '2026-10-16T12:00:00', operations_ack_note: '已核对并接收' } : {}), source: options.source || { customer_goal: '提升餐厅预约量', special_commitments: '每周提供一组素材', handoff_notes: '先核实商家地图资料' }, ...options.receipt });
  const leadState = () => ({ registered, can_register: !registered && options.canRegister !== false, read_only_reason: options.canRegister === false ? '当前账号不是主要负责人，不能登记成交' : undefined, lead: { id: 21, business_name: customer.business_name, contact_name: customer.contact_name, phone: customer.phone }, operations_candidates: [{ id: 7, name: '验收运营' }], contacts: [{ id: 'c1', name: '陈老板', phone: '+1 310 555 0111' }], customer_goal: '提升餐厅预约量', handoff: registered ? currentReceipt() : null, legacy_quotes: [{ id: 40, package_name: '历史套餐', final_amount: 599, currency: 'USD', status: 'approved' }], can_view_history: true, history_url: '/sales-leads?dossier=21' });
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'handoff-fixture-token'); localStorage.setItem('token', 'handoff-fixture-token'); localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname; const method = request.method();
    if (method !== 'GET') {
      const body = request.postDataJSON(); writes.push({ path, body });
      if (path === '/api/v1/sales-deal-handoffs/leads/21' && method === 'POST') {
        registrationCount += 1;
        if (options.holdRegistration) await registrationGate;
        if (options.conflict && registrationCount === 1) return json(route, { detail: '统一价格已更新，请刷新套餐后核对；本次没有登记' }, 409);
        if (options.retryableFailure && registrationCount === 1) return json(route, { detail: '登记服务暂不可用' }, 503);
        registered = true;
        if (options.lostResponse && registrationCount === 1) return route.abort('failed');
        return json(route, { registered: true, handoff: currentReceipt() });
      }
      if (path.endsWith('/operations-acknowledgment') && options.role === 'ops') { accepted = true; return json(route, { handoff: currentReceipt() }); }
      if (path.endsWith('/finance-confirmation') && owner) {
        if (body.amount_received !== 499 || body.currency !== 'USD') return json(route, { detail: '请按项目全额核对到账，订金不能确认全额' }, 400);
        paid = true; return json(route, { handoff: currentReceipt() });
      }
      return json(route, { detail: '本验收禁止其他写入' }, 403);
    }
    reads.push(path);
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path.endsWith('/sales-deal-handoffs/catalog')) { catalogRevision += 1; return json(route, { business_lines: [{ id: 3, code: 'media', name: '媒体服务' }], products: [{ id: 5, business_line_id: 3, name: '社交媒体代运营' }], plans: options.emptyCatalog ? [] : [{ ...plan, ...(catalogRevision > 1 ? { standard_price: 529, catalog_token: tokenB } : {}), ...options.planOverride }], can_manage_catalog: owner, platform_options: ['Facebook', 'Instagram', 'Google Ads'], message: options.emptyCatalog ? '暂无已发布且有效的统一价格套餐' : null }); }
    if (path.endsWith('/sales-deal-handoffs/leads/21')) return json(route, leadState());
    if (path.endsWith('/sales-deal-handoffs/customers/301')) return json(route, { items: [currentReceipt()] });
    if (path.endsWith('/sales-deal-handoffs/81')) return json(route, { registered: true, handoff: currentReceipt() });
    if (path.endsWith('/sales-deal-handoffs/queue')) {
      const status = url.searchParams.get('status'); const item = { ...currentReceipt(), business_name: customer.business_name, pending_payment: owner && !paid, pending_operations: !accepted, pending_access: owner };
      const counts = { all: 1, pending_payment: owner && !paid ? 1 : 0, pending_operations: !accepted ? 1 : 0, pending_access: owner ? 1 : 0, completed: 0 };
      return json(route, { items: status === 'pending_payment' && !owner ? [] : [item], counts, total: 1, is_owner: owner, status });
    }
    if (path.includes('/entities/customers/301/finance-access-data')) return json(route, { payments: [], expenses: [], deduction_rates: {}, refunds: [], status: { payment_count: 0, has_outstanding: false } });
    if (path.endsWith('/entities/subscriptions')) return json(route, { items: options.subscriptions || [] });
    if (path.endsWith('/entities/customers')) return json(route, { items: [customer], total: 1 });
    if (path.endsWith('/sales-leads/workbench/today')) return json(route, { salesperson: { id: employee.id, name: employee.name }, quota: 1, assigned_count: 1, completed_count: 0, remaining_count: 1, is_target_complete: false, categories: { unfinished: 1, callback: 0, interested: 1, appointment: 0, new: 0, retry: 0, recycled: 0, follow_up: 1 }, performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items: [{ task_id: 801, task_status: 'pending', lead: { id: 21, business_name: customer.business_name, contact_name: customer.contact_name, phone: customer.phone, country: 'US', industry: '餐厅', status: 'interested', do_not_contact: false, is_blacklisted: false, contact_protection: { can_contact: true, reason: '本人主要负责' } } }] });
    if (path.endsWith('/call-history')) return json(route, []);
    if (path.endsWith('/ringcentral/status')) return json(route, { configured: false, connected: false });
    if (path.endsWith('/sales-leads/assignees')) return json(route, []);
    if (path.endsWith('/sales-leads/stats')) return json(route, { total: 0, assigned: 0, unassigned: 0, blacklisted: 0, do_not_contact: 0 });
    if (path.includes('/sales-leads/dashboard/') || path.includes('/sales-leads/recovery/')) return json(route, { detail: '此验收不加载统计' }, 503);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.includes('/admin/settings')) return json(route, { backend_vars: {}, frontend_vars: {} });
    if (path.endsWith('/entities/employees')) return json(route, { items: [employee] });
    if (path.endsWith('/product-plans')) return json(route, { business_lines: [], products: [], plans: [] });
    if (path.includes('/customer-lifecycle/')) return json(route, { cycles: [], events: [] });
    return json(route, { items: [], total: 0 });
  });
  return { writes, reads, currentReceipt, releaseRegistration };
}
async function openRegistration(page: Page, action = 'deal') {
  await page.goto(`${baseUrl}/sales-leads?lead_id=21&action=${action}`);
  const dialog = page.getByRole('dialog', { name: '登记成交 · 成交验收餐厅', exact: true });
  await expect(dialog.getByLabel('统一套餐', { exact: true })).toBeVisible();
  return dialog;
}
async function fillToConfirm(dialog: Locator) {
  await dialog.getByLabel('统一套餐', { exact: true }).selectOption('9');
  await dialog.getByLabel('服务开始', { exact: true }).fill('2026-10-16');
  await expect(dialog.getByLabel('服务结束', { exact: true })).toHaveValue('2026-11-16');
  await dialog.getByLabel('Facebook', { exact: true }).check();
  await dialog.getByRole('button', { name: '下一步', exact: true }).click();
  await dialog.getByLabel('运营接收负责人', { exact: true }).selectOption('7');
  await dialog.getByLabel('特殊承诺 / 注意事项', { exact: true }).fill('每周提供一组素材');
  await dialog.getByRole('button', { name: '下一步', exact: true }).click();
  await dialog.getByLabel('成交确认说明', { exact: true }).fill('客户已确认标准套餐和服务范围');
  await dialog.getByRole('checkbox', { name: '我已核对套餐和交接内容' }).check();
}
async function noHorizontalOverflow(page: Page) { expect(await page.evaluate(() => Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) <= innerWidth)).toBe(true); }

for (const viewport of [{ width: 1093, height: 824 }, { width: 390, height: 844 }]) {
  test(`统一价登记 ${viewport.width}：只读价格、分步交接与未授权回执，无财务或权限写入`, async ({ page }) => {
    await page.setViewportSize(viewport); const { writes } = await fixture(page); const dialog = await openRegistration(page);
    await fillToConfirm(dialog); await expect(dialog.getByText('USD 499.00 · 月付', { exact: true })).toBeVisible();
    await expect(dialog.getByLabel('实际到账金额')).toHaveCount(0); await expect(dialog.getByLabel(/折扣|报价金额/)).toHaveCount(0);
    await noHorizontalOverflow(page);
    if (process.env.T24_HANDOFF_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_HANDOFF_SCREENSHOTS}/registration-confirm-${viewport.width}.png`, animations: 'disabled' });
    await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible();
    await expect(dialog.getByRole('button', { name: '查看客户与交接' })).toHaveCount(0); await expect(dialog.getByText(/指定运营负责人不会自动开放/)).toBeVisible();
    await expect(dialog.getByRole('button', { name: '核对全额收款' })).toHaveCount(0); expect(writes).toHaveLength(1);
    const body = writes[0].body; expect(body.plan_id).toBe(9); expect(body.catalog_token).toBe(tokenA); expect(body.service_start_date).toBe('2026-10-16'); expect(body.idempotency_key).toMatch(/^[a-f0-9-]{36}$/); expect(body).not.toHaveProperty('amount'); expect(body).not.toHaveProperty('currency'); expect(body).not.toHaveProperty('discount_amount'); expect(body).not.toHaveProperty('contacts');
    await noHorizontalOverflow(page);
    if (process.env.T24_HANDOFF_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_HANDOFF_SCREENSHOTS}/registration-receipt-${viewport.width}.png`, animations: 'disabled' });
  });
}

test('409价格变化保持草稿，刷新目录后由本人重新核对再登记', async ({ page }) => {
  const { writes } = await fixture(page, { conflict: true }); const dialog = await openRegistration(page); await fillToConfirm(dialog);
  await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('统一价格已更新');
  await expect(dialog.getByLabel('成交确认说明', { exact: true })).toHaveValue('客户已确认标准套餐和服务范围');
  await dialog.getByRole('button', { name: '核对登记结果', exact: true }).click(); await expect(dialog.getByLabel('成交确认说明', { exact: true })).toHaveValue('客户已确认标准套餐和服务范围');
  await dialog.getByRole('button', { name: '1. 统一套餐', exact: true }).click(); await dialog.getByRole('button', { name: '刷新已发布套餐（保留交接输入）', exact: true }).click(); await expect(dialog.getByText('USD 529.00', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '下一步', exact: true }).click(); await expect(dialog.getByLabel('特殊承诺 / 注意事项', { exact: true })).toHaveValue('每周提供一组素材'); await dialog.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '确认登记成交', exact: true })).toBeDisabled(); await dialog.getByRole('checkbox', { name: '我已核对套餐和交接内容' }).check(); await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(2); expect(writes[1].body.catalog_token).toBe(tokenB);
});

test('同一登记重试复用幂等编号', async ({ page }) => {
  const { writes } = await fixture(page, { retryableFailure: true }); const dialog = await openRegistration(page); await fillToConfirm(dialog);
  await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('登记服务暂不可用');
  await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(2); expect(writes[1].body).toEqual(writes[0].body);
});

test('丢失响应可核对已登记回执，不重复提交', async ({ page }) => {
  const { writes } = await fixture(page, { lostResponse: true }); const dialog = await openRegistration(page); await fillToConfirm(dialog); await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('输入已保留'); await dialog.getByRole('button', { name: '核对登记结果', exact: true }).click(); await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible(); expect(writes).toHaveLength(1);
});

test('未授权不能登记，旧报价入口仅展示历史，来源指向已授权档案', async ({ page }) => {
  const { writes } = await fixture(page, { canRegister: false }); await page.goto(`${baseUrl}/sales-leads?lead_id=21&action=quote`); const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('当前账号不是主要负责人，不能登记成交')).toBeVisible(); await dialog.getByText('历史报价与审核 · 1 条（只读）').click(); await expect(dialog.getByText('历史套餐 · USD 599.00')).toBeVisible(); await expect(dialog.getByRole('button', { name: /批准|驳回|提交报价/ })).toHaveCount(0);
  await expect(dialog.getByRole('link', { name: '查看售前来源与累计历史' })).toHaveAttribute('href', '/sales-leads?dossier=21'); expect(writes).toEqual([]);
});

for (const owner of [false, true]) test(`空目录只阻止登记，不合成价格；${owner ? '老板可维护' : '销售不开放维护'}`, async ({ page }) => {
  const { writes } = await fixture(page, { owner, emptyCatalog: true }); const dialog = await openRegistration(page); await expect(dialog.getByText('暂无已发布且有效的统一价格套餐')).toBeVisible(); await expect(dialog.getByRole('button', { name: '下一步', exact: true })).toBeDisabled();
  if (owner) await expect(dialog.getByRole('link', { name: '前往设置维护产品套餐' })).toHaveAttribute('href', '/settings?tab=products'); else await expect(dialog.getByRole('link', { name: '前往设置维护产品套餐' })).toHaveCount(0); expect(writes).toEqual([]);
});

test('登记草稿取消关闭保留，再确认放弃；无写入', async ({ page }) => {
  const { writes } = await fixture(page); const dialog = await openRegistration(page); await dialog.getByLabel('统一套餐', { exact: true }).selectOption('9');
  page.once('dialog', prompt => prompt.dismiss()); await dialog.getByRole('button', { name: 'Close', exact: true }).click(); await expect(dialog.getByLabel('统一套餐', { exact: true })).toHaveValue('9');
  page.once('dialog', prompt => prompt.accept()); await dialog.getByRole('button', { name: 'Close', exact: true }).click(); await expect(dialog).toHaveCount(0); expect(writes).toEqual([]);
});

test('运营delivery-only只见交付摘要，不见联系人/历史/财务；本人填备注确认接收', async ({ page }) => {
  const { writes, reads } = await fixture(page, { role: 'ops', modules: ['delivery'], receipt: { amount: undefined, currency: undefined, payment_status: undefined }, source: { customer_goal: '运营授权可见目标', special_commitments: '每周提供一组素材', handoff_notes: '先核实商家地图资料' } });
  await page.goto(`${baseUrl}/customers?detail=301`); const card = page.getByRole('region', { name: '售前承接', exact: true }); await expect(card.getByText('运营授权可见目标')).toBeVisible();
  await expect(card.getByText(/承接联系人|售前沟通记录|售前重点摘要|USD/)).toHaveCount(0); await expect(card.getByRole('link')).toHaveCount(0); await expect(card.getByRole('button', { name: '核对全额收款' })).toHaveCount(0);
  await card.getByRole('button', { name: '确认本人接收', exact: true }).click(); await card.getByLabel('接收备注').fill('已核对目标与交付承诺'); await card.getByRole('checkbox', { name: '我已查看上述交接资料' }).check(); await card.getByRole('button', { name: '确认接收', exact: true }).click(); await expect(card.getByText('运营已接收', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(1); expect(writes[0].body).toEqual({ note: '已核对目标与交付承诺' }); expect(reads.some(path => path.includes('sales-lead-dossiers'))).toBe(false);
});

test('contacts-only客户仅展示承接联系人，无交付或财务', async ({ page }) => {
  await fixture(page, { role: 'ops', modules: ['contacts'], receipt: { package_name: undefined, billing_cycle: undefined, amount: undefined, currency: undefined, payment_status: undefined, operations_status: undefined, operations_owner_employee_id: undefined, operations_owner_name: undefined, operations_access_status: undefined, can_operations_ack: false }, source: { contacts: [{ id: 'c1', name: '仅联系人授权', phone: '+1 310 555 0111' }] } });
  await page.goto(`${baseUrl}/customers?detail=301`); const card = page.getByRole('region', { name: '售前承接', exact: true }); await card.getByText('承接联系人 · 1 位').click(); await expect(card.getByText('仅联系人授权')).toBeVisible(); await expect(card.getByText('售前承接资料', { exact: true })).toBeVisible(); await expect(card.getByText(/待老板邀请|运营待接收|undefined/)).toHaveCount(0); await expect(card.getByText(/客户目标|特别承诺|交接补充|运营负责人|收款|USD/)).toHaveCount(0); await expect(card.getByRole('button', { name: '确认本人接收' })).toHaveCount(0);
});

test('老板核款必须真实金额日期凭据，订金错误保留，最终一次全额确认', async ({ page }) => {
  const { writes } = await fixture(page, { owner: true }); await page.goto(`${baseUrl}/customers?detail=301`); const card = page.getByRole('region', { name: '售前承接', exact: true }); await card.getByRole('button', { name: '核对全额收款', exact: true }).click(); await expect(card.getByLabel('实际到账日期', { exact: true })).toHaveValue('');
  await card.getByLabel('实际到账金额', { exact: true }).fill('100'); await card.getByLabel('实际到账日期', { exact: true }).fill('2026-10-15'); await card.getByLabel('交易号 / 凭据编号', { exact: true }).fill('BANK-TEST-ONLY-101'); await card.getByRole('checkbox', { name: '我已核对真实到账凭据' }).check(); await card.getByRole('button', { name: '确认全额到账', exact: true }).click(); await expect(card.getByRole('alert')).toContainText('订金不能确认全额'); await expect(card.getByLabel('实际到账金额', { exact: true })).toHaveValue('100');
  await card.getByLabel('实际到账金额', { exact: true }).fill('499'); await expect(card.getByRole('button', { name: '确认全额到账', exact: true })).toBeDisabled(); await card.getByRole('checkbox', { name: '我已核对真实到账凭据' }).check(); await card.getByRole('button', { name: '确认全额到账', exact: true }).click(); await expect(card.getByText('收款已核对', { exact: true })).toBeVisible(); await expect(card.getByRole('button', { name: '核对全额收款' })).toHaveCount(0);
  expect(writes).toHaveLength(2); expect(writes[1].body).toEqual({ amount_received: 499, payment_date: '2026-10-15', currency: 'USD', payment_method: 'bank_transfer', transaction_reference: 'BANK-TEST-ONLY-101' });
});

test('销售成交待办不显示公司核款与授权统计，查看交接不调用旧报价接口', async ({ page }) => {
  const { writes, reads } = await fixture(page); await page.goto(`${baseUrl}/sales-leads?view=handoffs`); const queue = page.getByRole('region', { name: '成交与交接待办', exact: true }); await expect(queue.getByText('成交验收餐厅', { exact: true })).toBeVisible(); await expect(queue.getByRole('button', { name: /待核款|待授权/ })).toHaveCount(0);
  await queue.getByRole('button', { name: '查看交接', exact: true }).click(); const dialog = page.getByRole('dialog', { name: '成交与交接详情' }); await expect(dialog.getByText('提升餐厅预约量', { exact: true })).toBeVisible(); await expect(dialog.getByRole('button', { name: '核对全额收款' })).toHaveCount(0); expect(reads.some(path => path.includes('/sales-deal-controls/'))).toBe(false); expect(writes).toEqual([]);
});


test('真实等待响应期间不能重复登记或关闭', async ({ page }) => {
  const data = await fixture(page, { holdRegistration: true }); const dialog = await openRegistration(page); await fillToConfirm(dialog);
  try {
    await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByRole('button', { name: '正在登记…', exact: true })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Close', exact: true }).click(); await expect(dialog).toBeVisible(); expect(data.writes).toHaveLength(1);
  } finally { data.releaseRegistration(); }
  await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible(); expect(data.writes).toHaveLength(1);
});

test('离开客户时保护接收草稿，取消保留，确认离开不触发写入', async ({ page }) => {
  const { writes } = await fixture(page, { role: 'ops', modules: ['delivery'], receipt: { amount: undefined, currency: undefined, payment_status: undefined } });
  await page.goto(`${baseUrl}/customers?detail=301`); const card = page.getByRole('region', { name: '售前承接', exact: true }); await card.getByRole('button', { name: '确认本人接收', exact: true }).click(); await card.getByLabel('接收备注').fill('尚未提交的接收备注');
  page.once('dialog', prompt => prompt.dismiss()); await page.getByRole('button', { name: '返回列表', exact: true }).click(); await expect(card.getByLabel('接收备注')).toHaveValue('尚未提交的接收备注');
  page.once('dialog', prompt => prompt.accept()); await page.getByRole('button', { name: '返回列表', exact: true }).click(); await expect(card).toHaveCount(0); expect(writes).toEqual([]);
});

test('队列查看登记回执前保护核款草稿，取消不丢失', async ({ page }) => {
  const { writes } = await fixture(page, { owner: true }); await page.goto(`${baseUrl}/sales-leads?view=handoffs`); await page.getByRole('region', { name: '成交与交接待办', exact: true }).getByRole('button', { name: '查看交接', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '成交与交接详情' }); await dialog.getByRole('button', { name: '核对全额收款', exact: true }).click(); await dialog.getByLabel('实际到账金额', { exact: true }).fill('499');
  page.once('dialog', prompt => prompt.dismiss()); await dialog.getByRole('button', { name: '查看登记回执', exact: true }).click(); await expect(dialog.getByLabel('实际到账金额', { exact: true })).toHaveValue('499');
  page.once('dialog', prompt => prompt.accept()); await dialog.getByRole('button', { name: '查看登记回执', exact: true }).click(); await expect(page.getByRole('dialog', { name: '登记成交 · 成交验收餐厅', exact: true })).toBeVisible(); expect(writes).toEqual([]);
});


test('今日拨打的登记入口留在当前工作台，读取新成交接口且不写旧报价', async ({ page }) => {
  const { writes, reads } = await fixture(page); await page.goto(`${baseUrl}/sales-workbench`); await page.getByRole('button', { name: '登记成交', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '登记成交 · 成交验收餐厅', exact: true }).getByLabel('统一套餐', { exact: true })).toBeVisible(); await expect(page).toHaveURL(/sales-workbench/);
  expect(reads).toContain('/api/v1/sales-deal-handoffs/leads/21'); expect(reads.some(path => path.includes('/sales-deal-controls/'))).toBe(false); expect(writes).toEqual([]);
});


for (const policy of ['manual', undefined]) test(`人工价或未配置策略不得使用Stripe自动优惠价：${policy || 'missing'}`, async ({ page }) => {
  const { writes } = await fixture(page, { planOverride: { required_collection_method: policy, standard_price: 399 } }); const dialog = await openRegistration(page);
  await dialog.getByLabel('统一套餐', { exact: true }).selectOption('9'); await expect(dialog.getByText('USD 399.00', { exact: true })).toBeVisible();
  const method = dialog.getByRole('combobox', { name: '约定收款方式', exact: true }); await expect(method.locator('option[value="stripe_auto"]')).toHaveCount(0); await method.selectOption('check');
  await dialog.getByLabel('服务开始', { exact: true }).fill('2026-10-16'); await expect(dialog.getByLabel('服务结束', { exact: true })).toHaveValue('2026-11-16');
  await dialog.getByRole('button', { name: '下一步', exact: true }).click(); await dialog.getByLabel('运营接收负责人', { exact: true }).selectOption('7'); await dialog.getByRole('button', { name: '下一步', exact: true }).click(); await dialog.getByLabel('成交确认说明', { exact: true }).fill('已确认人工收款统一价及服务内容'); await dialog.getByRole('checkbox', { name: '我已核对套餐和交接内容' }).check(); await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(1); expect(writes[0].body.collection_method).toBe('check'); expect(writes[0].body).not.toHaveProperty('amount');
});

test('Stripe自动订阅价固定渠道，月末与闰年服务期自动计算且不可改价', async ({ page }) => {
  await fixture(page, { planOverride: { standard_price: 198 } }); const dialog = await openRegistration(page); await dialog.getByLabel('统一套餐', { exact: true }).selectOption('9'); await expect(dialog.getByLabel('约定收款方式', { exact: true })).toHaveValue('Stripe 自动订阅（该套餐固定）'); await expect(dialog.getByLabel('约定收款方式', { exact: true })).toHaveAttribute('readonly', '');
  for (const [start, end] of [['2024-01-31', '2024-02-29'], ['2025-01-31', '2025-02-28'], ['2025-12-31', '2026-01-31']]) { await dialog.getByLabel('服务开始', { exact: true }).fill(start); await expect(dialog.getByLabel('服务结束', { exact: true })).toHaveValue(end); }
  await expect(dialog.getByLabel('服务结束', { exact: true })).toHaveAttribute('readonly', ''); await expect(dialog.getByText('USD 198.00', { exact: true })).toBeVisible();
});

test('待开始订阅不算在服，也不替代同套餐已有活跃服务', async ({ page }) => {
  const samePackage = { customer_id: 301, package_name: plan.name, billing_cycle: 'monthly', auto_renew: false };
  await fixture(page, { owner: true, subscriptions: [{ ...samePackage, id: 801, status: 'active', start_date: '2026-01-01', end_date: '2027-12-31', created_at: '2026-01-01T00:00:00Z' }, { ...samePackage, id: 802, status: 'pending', start_date: '2026-10-16', end_date: '2026-11-16', created_at: '2026-10-16T00:00:00Z' }] });
  await page.goto(`${baseUrl}/customers?detail=301`); const metric = page.getByText('在服套餐', { exact: true }).locator('..'); await expect(metric.getByText('1', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: '服务信息 (2)', exact: true }).click(); const pending = page.getByRole('region', { name: '待开始套餐', exact: true }); await expect(pending.getByText('待核款 · 未开始', { exact: true })).toBeVisible(); await expect(pending.getByText('统一基础套餐', { exact: true })).toBeVisible(); await expect(page.getByText('当前服务', { exact: true })).toBeVisible();
});

async function settingsFixture(page: Page, failPolicy: boolean) {
  await fixture(page, { owner: true });
  const writes: { method: string; path: string; body: any }[] = [];
  let saved: Record<string, any> | null = null;
  let policiesFailed = false;
  await page.route(/^https?:\/\/[^/]+\/api\/v1\/(?:product-plans(?:\/.*)?|sales-deal-handoffs\/plan-policies(?:\/.*)?)$/, async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (request.method() === 'GET') {
      if (path.endsWith('/plan-policies')) return json(route, { items: [] });
      return json(route, { business_lines: [{ id: 3, code: 'managed_service', name: '代运营服务' }], products: [{ id: 5, business_line_id: 3, business_line_code: 'managed_service', business_line_name: '代运营服务', code: 'managed', name: '代运营产品', billing_kind: 'recurring' }], plans: saved ? [saved] : [] });
    }
    const body = request.postDataJSON(); writes.push({ method: request.method(), path, body });
    if (path.includes('/plan-policies/')) {
      if (failPolicy && !policiesFailed) { policiesFailed = true; return json(route, { detail: '合成测试：策略保存暂不可用' }, 503); }
      return json(route, { plan_id: 91, collection_policy: body.collection_policy });
    }
    saved = { ...body, id: 91 };
    return json(route, saved);
  });
  await page.goto(`${baseUrl}/settings?tab=products`); await page.getByRole('button', { name: '新增套餐', exact: true }).click(); const dialog = page.getByRole('dialog', { name: '新增套餐', exact: true });
  await dialog.getByLabel('套餐名称', { exact: true }).fill('合成Stripe统一套餐'); await dialog.getByLabel('套餐代码', { exact: true }).fill('synthetic-stripe-monthly'); await dialog.getByLabel('价格状态', { exact: true }).selectOption('published'); await dialog.getByLabel('标准价格', { exact: true }).fill('198'); await dialog.getByLabel('可选平台数量', { exact: true }).fill('2'); await dialog.getByLabel('套餐允许的收款方式', { exact: true }).selectOption('stripe_auto');
  return { writes, dialog };
}

test('老板发布统一套餐先停用草稿，再存收款策略，最后发布', async ({ page }) => {
  const { writes, dialog } = await settingsFixture(page, false); await dialog.getByRole('button', { name: '保存套餐', exact: true }).click(); await expect(dialog).toHaveCount(0);
  expect(writes.map(row => `${row.method} ${row.path}`)).toEqual(['POST /api/v1/product-plans/plans', 'PUT /api/v1/sales-deal-handoffs/plan-policies/91', 'PUT /api/v1/product-plans/plans/91']);
  expect(writes[0].body).toMatchObject({ pricing_status: 'draft', is_active: false, standard_price: 198 }); expect(writes[1].body).toEqual({ collection_policy: 'stripe_auto' }); expect(writes[2].body).toMatchObject({ pricing_status: 'published', is_active: true, standard_price: 198 });
});

test('收款策略失败时不得发布优惠套餐，重试复用已创建草稿', async ({ page }) => {
  const { writes, dialog } = await settingsFixture(page, true); const failedPolicy = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/plan-policies/91') && response.status() === 503); await dialog.getByRole('button', { name: '保存套餐', exact: true }).click(); await failedPolicy;
  const retained = page.getByRole('dialog', { name: '编辑套餐', exact: true }); await expect(retained.getByLabel('套餐名称', { exact: true })).toHaveValue('合成Stripe统一套餐'); await expect(retained.getByRole('button', { name: '保存套餐', exact: true })).toBeEnabled();
  expect(writes).toHaveLength(2); expect(writes[0].body).toMatchObject({ pricing_status: 'draft', is_active: false }); expect(writes.some(row => row.body.pricing_status === 'published')).toBe(false);
  await retained.getByRole('button', { name: '保存套餐', exact: true }).click(); await expect(retained).toHaveCount(0); expect(writes.filter(row => row.method === 'POST')).toHaveLength(1); expect(writes.at(-1)?.body).toMatchObject({ pricing_status: 'published', is_active: true });
});
