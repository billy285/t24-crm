import { expect, test, type Page, type Route } from '@playwright/test';

const web = process.env.T24_RECONCILIATION_BASE_URL || 'http://127.0.0.1:8921';
const base = '/api/v1/stripe-history-reconciliation';
const service = { customer_id: 301, customer_name: '历史对账验收餐厅', crm_subscription_id: 51, package_name: '基础版', amount: 198, currency: 'USD', billing_cycle: 'monthly', status: 'active' };
const candidate = { subscription_id: 'sub_historyA1', customer_id: 'cus_historyA1', customer_name: 'Synthetic Restaurant', email: 'synthetic@example.test', status: 'active', currency: 'USD', amount: 198, billing_cycle: 'monthly', price_id: 'price_syntheticA1', items_count: 1 };
const binding = { id: 41, customer_id: 301, customer_name: service.customer_name, crm_subscription_id: 51, package_name: service.package_name, stripe_subscription_id: candidate.subscription_id, stripe_customer_id: candidate.customer_id, currency: 'USD', amount: 198, billing_cycle: 'monthly', sync_from: '2026-10-01', status: 'active', revision: 1, needs_refresh: false, pilot_validated: false, pilot_evidence: { successful_sync_count: 2, repeat_dedupe_verified: true, cash_evidence_verified: true, invoice_count: 1, last_date_start: '2026-10-01', last_date_end: '2026-10-19' } };
const review = { id: 71, binding_id: 41, customer_id: 301, customer_name: service.customer_name, package_name: '基础版', stripe_invoice_id: 'in_syntheticA1', status: 'pending_review', issues: [], service_amount: 198, tax_amount: 15.84, gross_amount: 213.84, fee_amount: 6.5, net_amount: 207.34, currency: 'USD', payment_date: '2026-10-18', coverage_start: '2026-10-01', coverage_end: '2026-11-01', revision: 1, lines: [{ description: '基础版服务', amount: 198, currency: 'USD', period_start: '2026-10-01', period_end: '2026-11-01' }], existing_payment_candidates: [] as any[], accounting_preview: { amount_due: 198, amount_paid: 198, management_amount: 198, ads_recharge_amount: 0, stripe_fee_amount: 6.04, net_amount: 191.96 }, can_confirm: true, can_create_payment: true, can_link_existing: false };
type Scenario = { role?: string; configured?: boolean; warnings?: boolean; duplicate?: boolean; closed?: boolean; loadFail?: boolean; confirmFail?: boolean; revoked?: boolean; bulk?: boolean; pilotReady?: boolean; previewBlocked?: boolean; reviewOverride?: Record<string, unknown> };
async function json(route: Route, value: unknown, status = 200) { return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }); }
async function fixture(page: Page, options: Scenario = {}) {
  const role = options.role || 'super_admin'; const employee = { id: role === 'super_admin' ? 1 : 7, name: role === 'super_admin' ? '验收老板' : '验收运营', role, status: 'active' };
  const reads: string[] = []; const writes: { path: string; body: any }[] = []; let overviewCalls = 0; let previewCalls = 0; let finalized = false; let validated = false; let bulk = options.bulk || false; let confirmFailures = 0;
  const detail = () => ({ ...review, ...(options.duplicate ? { existing_payment_candidates: [{ id: 90, customer_name: service.customer_name, product_name: '基础版', amount_paid: 198, payment_date: '2026-10-18', currency: 'USD', transaction_reference: 'pi_existingA1', coverage_start: '2026-10-01', coverage_end: '2026-11-01' }], can_create_payment: false, can_link_existing: true } : {}), ...(options.closed ? { status: 'exception', can_confirm: false, can_create_payment: false, can_link_existing: false, read_only_reason: '该月份已经关账，不能在此确认记账。', issues: [{ code: 'month_closed', message: '该月份已经关账，不能在此确认记账。' }] } : {}), ...(options.reviewOverride || {}), ...(finalized ? { status: options.duplicate ? 'linked_existing' : 'confirmed', payment_id: 90, can_confirm: false, can_create_payment: false, can_link_existing: false } : {}) });
  const pilot = () => ({ limit: 5, enabled_bindings: 1, validated_bindings: validated || options.pilotReady ? 3 : 0, bulk_enabled: bulk, can_activate_bulk: !bulk && (validated || options.pilotReady) });
  await page.addInitScript(value => { localStorage.setItem('emp_auth_token', 'reconciliation-fixture'); localStorage.setItem('token', 'reconciliation-fixture'); localStorage.setItem('emp_auth_data', JSON.stringify(value)); }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') {
      const body = request.postData() ? request.postDataJSON() : {}; writes.push({ path, body });
      if (path === `${base}/bindings/preview`) { previewCalls += 1; return json(route, { token: `preview_${previewCalls}`, expires_at: '2026-10-18T12:30:00Z', crm_service: service, stripe_subscription: { ...candidate, subscription_id: body.stripe_subscription_id }, warnings: options.warnings ? [{ code: 'name_differs', message: '客户名称不同，请核实归属；名称与金额不会自动建立关联。' }] : [], can_confirm: !options.previewBlocked, pilot: pilot() }); }
      if (path === `${base}/bindings`) return json(route, { binding });
      if (path === `${base}/bindings/41/sync`) return json(route, { items: [detail()], has_more: false, next_cursor: null, scope: { date_start: body.date_start, date_end: body.date_end }, binding });
      if (path === `${base}/bindings/41/validate-pilot`) { validated = true; return json(route, { binding: { ...binding, pilot_validated: true } }); }
      if (path === `${base}/pilot/bulk-activation`) { bulk = true; return json(route, { pilot: pilot() }); }
      if (path === `${base}/invoice-reviews/71/refresh`) { if (options.revoked) return json(route, { detail: '当前账号无权读取财务资料' }, 403); return json(route, { review: detail() }); }
      if (path === `${base}/invoice-reviews/71/confirm`) { if (options.confirmFail && confirmFailures++ === 0) return json(route, { detail: '凭据已变化，请重新读取后核对。' }, 409); finalized = true; return json(route, { review: detail(), payment_id: 90, idempotent_replay: false }); }
      return json(route, { detail: '本验收禁止其他写入' }, 403);
    }
    reads.push(path);
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path === `${base}/overview`) { overviewCalls += 1; if (options.loadFail && overviewCalls === 1) return json(route, { detail: '对账概览读取失败' }, 503); return json(route, { configured: options.configured !== false, provider_status: options.configured === false ? 'not_configured' : 'configured', pilot: pilot(), counts: { bindings: 1, pending_review: finalized ? 0 : 1, needs_refresh: 0, exceptions: options.closed ? 1 : 0, confirmed: finalized && !options.duplicate ? 1 : 0, linked_existing: finalized && options.duplicate ? 1 : 0 }, bindings: [{ ...binding, pilot_validated: validated }], invoice_reviews: [detail()], scope_note: '只覆盖选定历史区间，尚未读取不等于已入账。' }); }
    if (path === `${base}/crm-services`) return json(route, { items: [service], total: 1 });
    if (path === `${base}/stripe-subscriptions`) return json(route, { items: [candidate], has_more: false, next_cursor: null, read_only: true });
    if (path === `${base}/invoice-reviews`) return json(route, { items: [detail()], counts: { all: 1, pending_review: 1, needs_refresh: 0, exception: options.closed ? 1 : 0, confirmed: finalized ? 1 : 0, linked_existing: 0 }, total: 1 });
    if (path === `${base}/invoice-reviews/71`) { if (options.revoked && reads.filter(value => value === path).length > 1) return json(route, { detail: '当前账号无权读取财务资料' }, 403); return json(route, { review: detail() }); }
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.includes('/admin/settings')) return json(route, { backend_vars: {}, frontend_vars: {} });
    return json(route, { items: [], total: 0 });
  });
  return { reads, writes };
}
async function mapping(page: Page) { await page.goto(`${web}/finance?tab=stripe_reconciliation&stripe_view=mapping`); await page.getByLabel('CRM 客户服务', { exact: true }).selectOption('51'); await page.getByLabel('Stripe 订阅编号', { exact: true }).fill('sub_historyA1'); await page.getByRole('button', { name: '预览关联，不保存', exact: true }).click(); return page.getByRole('region', { name: `关联预览 ${service.customer_name}`, exact: true }); }
async function reviewDialog(page: Page) { await page.goto(`${web}/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=71`); const dialog = page.getByRole('dialog'); await expect(dialog.getByText('账单 in_syntheticA1', { exact: true })).toBeVisible(); return dialog; }
async function noOverflow(page: Page) { expect(await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= innerWidth)).toBe(true); }

for (const width of [1093, 390]) {
  test(`关联预览 ${width}：不触发旧账本读取，不自动保存，警告与老板确认必选`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); const { reads, writes } = await fixture(page, { warnings: true }); const panel = await mapping(page); await expect(panel.getByText('仅预览 · 尚未保存')).toBeVisible(); await expect(panel.getByRole('button', { name: '确认建立关联', exact: true })).toBeDisabled(); await panel.getByRole('checkbox', { name: '客户名称不同，请核实归属；名称与金额不会自动建立关联。' }).check(); await panel.getByRole('checkbox', { name: /我已核对客户归属/ }).check(); await expect(panel.getByRole('button', { name: '确认建立关联', exact: true })).toBeEnabled(); expect(writes.map(item => item.path)).toEqual([`${base}/bindings/preview`]); expect(reads.some(path => path.includes('/entities/payments') || path.includes('/entities/subscriptions') || path.includes('/private'))).toBe(false); await noOverflow(page);
    if (process.env.T24_RECONCILIATION_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_RECONCILIATION_SCREENSHOTS}/mapping-preview-${width}.png`, animations: 'disabled' });
    await panel.getByRole('button', { name: '确认建立关联', exact: true }).click(); await expect(page.getByText('关联已保存；账单同步后仍需你逐笔核对。')).toBeVisible(); expect(writes[1].body).toEqual({ token: 'preview_1', owner_verified: true, accepted_warning_codes: ['name_differs'] }); expect(writes.some(item => item.path.endsWith('/confirm'))).toBe(false);
  });
  test(`逐笔核款 ${width}：平台税费与原口径分开，人工选择并确认才记账`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); const { writes } = await fixture(page); const dialog = await reviewDialog(page); await expect(dialog.getByText('USD 213.84', { exact: true })).toBeVisible(); await expect(dialog.getByText('USD 6.50', { exact: true })).toBeVisible(); await expect(dialog.getByText('USD 6.04', { exact: true })).toBeVisible(); await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toBeDisabled(); expect(writes).toEqual([]); await dialog.getByRole('radio', { name: '核对后手动新增一笔收入', exact: true }).check(); await dialog.getByLabel('老板核对说明', { exact: true }).fill('已核对真实到账及本服务期间'); await dialog.getByRole('checkbox', { name: /我已核对真实到账、客户归属、税费/ }).check(); await noOverflow(page);
    if (process.env.T24_RECONCILIATION_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_RECONCILIATION_SCREENSHOTS}/receipt-review-${width}.png`, animations: 'disabled' });
    await dialog.getByRole('button', { name: '确认并记账', exact: true }).click(); await expect(dialog.getByText('该账单已由老板确认记账。 收款 #90')).toBeVisible(); expect(writes).toHaveLength(1); expect(writes[0].body).toEqual({ revision: 1, action: 'create_payment', owner_verified: true, verification_note: '已核对真实到账及本服务期间' }); await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toHaveCount(0);
  });
}
test('普通运营直接访问对账页无接口请求、无公司财务泄漏', async ({ page }) => { const { reads, writes } = await fixture(page, { role: 'ops' }); await page.goto(`${web}/finance?tab=stripe_reconciliation`); await expect(page.getByText(/无权限访问|Stripe 对账仅老板可见/)).toBeVisible(); expect(reads.some(path => path.startsWith(base))).toBe(false); expect(writes).toEqual([]); });
test('存在原账候选只能选择关联原收款，不能再新增收入', async ({ page }) => { const { writes } = await fixture(page, { duplicate: true }); const dialog = await reviewDialog(page); await expect(dialog.getByRole('radio', { name: '核对后手动新增一笔收入' })).toHaveCount(0); await dialog.getByRole('radio', { name: /收款 #90/ }).check(); await dialog.getByLabel('老板核对说明', { exact: true }).fill('已核对原收款编号和服务期间'); await dialog.getByRole('checkbox', { name: /我已核对真实到账、客户归属、服务期间及所选原收款记录/ }).check(); await dialog.getByRole('button', { name: '确认关联原收款', exact: true }).click(); await expect(dialog.getByText('已关联原收款记录，没有新增重复收入。 收款 #90')).toBeVisible(); expect(writes[0].body.action).toBe('link_existing'); expect(writes[0].body.existing_payment_id).toBe(90); });
test('关账月份保持只读，异常不会被前端提交绕过', async ({ page }) => { const { writes } = await fixture(page, { closed: true }); const dialog = await reviewDialog(page); await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toBeDisabled(); await expect(dialog.getByRole('radio', { name: /新增一笔收入/ })).toHaveCount(0); expect(writes).toEqual([]); });
test('连接未就绪仍可看本地范围，但不读取或确认 Stripe', async ({ page }) => { const { writes } = await fixture(page, { configured: false }); await page.goto(`${web}/finance?tab=stripe_reconciliation&stripe_view=mapping`); await expect(page.getByText('Stripe 只读连接尚未就绪')).toBeVisible(); await expect(page.getByRole('button', { name: '读取订阅', exact: true })).toBeDisabled(); await page.getByLabel('CRM 客户服务', { exact: true }).selectOption('51'); await page.getByLabel('Stripe 订阅编号', { exact: true }).fill('sub_historyA1'); await expect(page.getByRole('button', { name: '预览关联，不保存', exact: true })).toBeDisabled(); expect(writes).toEqual([]); });
test('证据变化或丢失响应后须先核对处理结果，再重新确认', async ({ page }) => { const { writes } = await fixture(page, { confirmFail: true }); const dialog = await reviewDialog(page); await dialog.getByRole('radio', { name: '核对后手动新增一笔收入', exact: true }).check(); await dialog.getByLabel('老板核对说明').fill('已核对真实到账与原账'); await dialog.getByRole('checkbox', { name: /我已核对真实到账、客户归属、税费/ }).check(); await dialog.getByRole('button', { name: '确认并记账', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('凭据已变化'); await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toBeDisabled(); await dialog.getByRole('button', { name: '核对处理结果', exact: true }).click(); await expect(dialog.getByLabel('老板核对说明')).toHaveValue('已核对真实到账与原账'); await expect(dialog.getByRole('checkbox', { name: /我已核对真实到账、客户归属、税费/ })).not.toBeChecked(); expect(writes).toHaveLength(1); });
test('撤销权限重新读取清空旧核款资料和操作入口', async ({ page }) => { await fixture(page, { revoked: true }); const dialog = await reviewDialog(page); await dialog.getByRole('button', { name: '重新读取记录', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('当前账号无权'); await expect(dialog.getByText('账单 in_syntheticA1', { exact: true })).toHaveCount(0); await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toHaveCount(0); });
test('首次同步和同区间再同步只更新待核对证据，无正式入账请求', async ({ page }) => { const { writes } = await fixture(page); await page.goto(`${web}/finance?tab=stripe_reconciliation`); await page.getByRole('button', { name: '同步账单', exact: true }).click(); const dialog = page.getByRole('dialog'); await dialog.getByLabel('同步开始日期').fill('2026-10-01'); await dialog.getByRole('button', { name: '读取本区间账单', exact: true }).click(); await expect(dialog.getByText('本页已读取 1 笔 · 尚未记账')).toBeVisible(); await dialog.getByRole('button', { name: '再次同步本区间（去重核验）', exact: true }).click(); expect(writes).toHaveLength(2); expect(writes[0].body).toEqual(writes[1].body); expect(writes.every(item => item.path.endsWith('/sync'))).toBe(true); });
test('试点不足锁批量，证据验证后仍由老板明确启用', async ({ page }) => { const { writes } = await fixture(page); await page.goto(`${web}/finance?tab=stripe_reconciliation`); await expect(page.getByRole('button', { name: '启用批量关联', exact: true })).toBeDisabled(); await page.getByRole('button', { name: '核对并验证试点', exact: true }).click(); let dialog = page.getByRole('dialog'); await dialog.getByLabel('试点核对说明').fill('已核对同步区间去重与到账凭据'); await dialog.getByRole('checkbox', { name: /我已亲自核对客户归属/ }).check(); await dialog.getByRole('button', { name: '确认试点验证通过', exact: true }).click(); await page.getByRole('button', { name: '启用批量关联', exact: true }).click(); dialog = page.getByRole('dialog'); await expect(dialog.getByRole('button', { name: '确认启用批量关联', exact: true })).toBeDisabled(); await dialog.getByLabel('试点核对说明').fill('三个独立试点已验证一致'); await dialog.getByRole('checkbox', { name: /我已核对至少 3 个试点/ }).check(); await dialog.getByRole('button', { name: '确认启用批量关联', exact: true }).click(); await expect(page.getByText('批量关联已启用，仍逐项核对与确认')).toBeVisible(); expect(writes.map(item => item.path)).toEqual([`${base}/bindings/41/validate-pilot`, `${base}/pilot/bulk-activation`]); });
test('批量待确认手选预览，不自动配对或保存，每项仍需老板确认', async ({ page }) => { const { writes } = await fixture(page, { bulk: true }); const panel = await mapping(page); await panel.getByRole('button', { name: '加入批量待确认', exact: true }).click(); const cart = page.getByRole('region', { name: '批量关联待确认清单' }); await expect(cart.getByRole('button', { name: '确认关联这一项', exact: true })).toBeDisabled(); expect(writes.map(item => item.path)).toEqual([`${base}/bindings/preview`]); await cart.getByRole('checkbox', { name: /我已核对客户归属/ }).check(); await cart.getByRole('button', { name: '确认关联这一项', exact: true }).click(); await expect(cart.getByText('关联已保存，账单仍须单独核对。')).toBeVisible(); expect(writes.map(item => item.path)).toEqual([`${base}/bindings/preview`, `${base}/bindings`]); });
test('关闭核款弹窗没有提交，错误概览可重试且不显示假健康', async ({ page }) => { const { writes } = await fixture(page, { loadFail: true }); await page.goto(`${web}/finance?tab=stripe_reconciliation`); await expect(page.getByRole('alert')).toContainText('对账概览读取失败'); await page.getByRole('button', { name: '刷新概览', exact: true }).click(); await page.getByRole('button', { name: /待核对 1/ }).click(); await page.getByRole('button', { name: /历史对账验收餐厅/ }).click(); await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click(); await expect(page.getByRole('dialog')).toHaveCount(0); expect(writes).toEqual([]); });
test('总览数量和点入范围一致：待核对包含待刷新，已入账包含关联原账', async ({ page }) => {
  await fixture(page);
  const items = ['pending_review', 'needs_refresh', 'confirmed', 'linked_existing'].map((status, index) => ({ ...review, id: 71 + index, status, customer_name: `状态范围验收 ${status}` }));
  await page.route(/\/api\/v1\/stripe-history-reconciliation\/(?:overview|invoice-reviews)(?:\?.*)?$/, async route => {
    const url = new URL(route.request().url());
    const counts = { all: 4, bindings: 1, pending_review: 1, needs_refresh: 1, exception: 0, confirmed: 1, linked_existing: 1 };
    return json(route, url.pathname.endsWith('/overview') ? { configured: true, provider_status: 'configured', pilot: { limit: 5, enabled_bindings: 1, validated_bindings: 0, bulk_enabled: false, can_activate_bulk: false }, counts, bindings: [binding], invoice_reviews: items } : { items, counts, total: 4 });
  });
  await page.goto(`${web}/finance?tab=stripe_reconciliation`);
  await page.locator('.shr-metrics').getByRole('button', { name: /待核对 2/ }).click();
  await expect(page.getByRole('button', { name: /状态范围验收 pending_review/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /状态范围验收 needs_refresh/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /状态范围验收 confirmed/ })).toHaveCount(0);
  await page.getByRole('button', { name: '对账总览', exact: true }).click();
  await page.locator('.shr-metrics').getByRole('button', { name: /已入账 2/ }).click();
  await expect(page.getByRole('button', { name: /状态范围验收 confirmed/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /状态范围验收 linked_existing/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /状态范围验收 pending_review/ })).toHaveCount(0);
});
for (const width of [1093, 390]) {
  test(`未付账单 ${width}：金额标为待核验，不能把账单总额或平台净额当作到账`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const { writes } = await fixture(page, { reviewOverride: { status: 'exception', service_amount: 399, tax_amount: 0, gross_amount: 399, fee_amount: 3.19, net_amount: 395.81, payment_date: null, issues: [{ code: 'not_paid', message: '账单尚未付清' }, { code: 'cash_unverified', message: '缺少实际扣款凭据' }], can_confirm: false, can_create_payment: false, accounting_preview: null } });
    const dialog = await reviewDialog(page);
    const warning = dialog.getByText('尚未确认实际到账，以下为账单或平台记录金额，不能作为已收款依据。', { exact: true });
    await expect(warning).toBeVisible(); await expect(dialog.getByText('账单总额', { exact: true })).toBeVisible();
    await expect(dialog.getByText('平台手续费（待核验）', { exact: true })).toBeVisible(); await expect(dialog.getByText('平台净额（待核验）', { exact: true })).toBeVisible();
    await expect(dialog.getByText('USD 399.00', { exact: true })).toHaveCount(2); await expect(dialog.getByText('USD 3.19', { exact: true })).toBeVisible(); await expect(dialog.getByText('USD 395.81', { exact: true })).toBeVisible();
    await expect(dialog.getByText('客户支付总额', { exact: true })).toHaveCount(0); await expect(dialog.getByText('平台净到账', { exact: true })).toHaveCount(0); await expect(dialog.getByText('平台实际手续费', { exact: true })).toHaveCount(0);
    expect(await warning.evaluate(element => Boolean(element.compareDocumentPosition(element.parentElement!.querySelector('.shr-evidence-grid')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toBeDisabled(); expect(writes).toEqual([]); await noOverflow(page);
    if (process.env.T24_RECONCILIATION_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_RECONCILIATION_SCREENSHOTS}/unpaid-cash-labels-${width}.png`, animations: 'disabled' });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click(); await expect(dialog).toHaveCount(0); expect(writes).toEqual([]);
  });
}
for (const override of [{ status: 'needs_refresh' }, { needs_refresh: true }, { payment_date: null }, { issues: [{ code: 'fee_unverified', message: '手续费凭据待核实' }] }]) {
  test(`未完整现金依据标待核验：${JSON.stringify(override)}`, async ({ page }) => {
    const { writes } = await fixture(page, { reviewOverride: { ...override, can_confirm: false, can_create_payment: false } });
    const dialog = await reviewDialog(page); await expect(dialog.getByText('平台净额（待核验）', { exact: true })).toBeVisible();
    await expect(dialog.getByText('尚未确认实际到账，以下为账单或平台记录金额，不能作为已收款依据。', { exact: true })).toBeVisible();
    expect(writes).toEqual([]);
  });
}
for (const reason of ['现有分润归属或服务区间需核对；不会重新建立首月或猜测归属', '该月份已经关账，不能在此确认记账。']) {
  test(`完整现金证据被原规则阻断仍保留实际手续费和净到账：${reason}`, async ({ page }) => {
    const { writes } = await fixture(page, { reviewOverride: { can_confirm: false, can_create_payment: false, read_only_reason: reason } });
    const dialog = await reviewDialog(page); await expect(dialog.getByText('Stripe 到账依据', { exact: true })).toBeVisible();
    await expect(dialog.getByText('账单总额', { exact: true })).toBeVisible(); await expect(dialog.getByText('平台实际手续费', { exact: true })).toBeVisible(); await expect(dialog.getByText('平台净到账', { exact: true })).toBeVisible();
    await expect(dialog.getByText('平台净额（待核验）', { exact: true })).toHaveCount(0); await expect(dialog.getByText('尚未确认实际到账，以下为账单或平台记录金额，不能作为已收款依据。', { exact: true })).toHaveCount(0);
    await expect(dialog.getByText(reason, { exact: true })).toBeVisible(); await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toBeDisabled(); expect(writes).toEqual([]);
  });
}
