import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname } from 'node:path';
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from '@playwright/test';

const web = process.env.T24_RECONCILIATION_BASE_URL || 'http://127.0.0.1:8921';
const accountFile = process.env.T24_RECONCILIATION_E2E_ACCOUNTS || '';
const base = '/api/v1/stripe-history-reconciliation';
type SyntheticState = { synthetic_only: boolean; provider_synthetic_only: boolean; base_url: string; database: string; accounts: Record<string, { email: string; password: string; role: string }> };
async function login(request: APIRequestContext, state: SyntheticState, actor: string) {
  const account = state.accounts[actor];
  const response = await request.post(`${state.base_url}/api/v1/emp-auth/login`, { data: { email: account.email, password: account.password } });
  expect(response.status(), '合成账号登录').toBe(200);
  const session = await response.json(); expect(typeof session.token).toBe('string');
  return session as { token: string; employee: { id: number; name: string; role: string } };
}
async function open(browser: Browser, state: SyntheticState, session: Awaited<ReturnType<typeof login>>, path: string, width = 1093) {
  const context = await browser.newContext({ viewport: { width, height: 844 } });
  await context.addInitScript(auth => { localStorage.setItem('emp_auth_token', auth.token); localStorage.setItem('token', auth.token); localStorage.setItem('emp_auth_data', JSON.stringify(auth.employee)); }, session);
  const page = await context.newPage(); const writes: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/config') return route.fulfill({ json: { API_BASE_URL: web } });
    if (route.request().method() !== 'GET') writes.push(url.pathname);
    const response = await route.fetch({ url: `${state.base_url}${url.pathname}${url.search}` });
    return route.fulfill({ response });
  });
  await page.goto(`${web}${path}`); return { context, page, writes };
}
async function preview(page: Page, identity: number) {
  await page.getByLabel('CRM 客户服务', { exact: true }).selectOption(String(identity));
  await page.getByLabel('Stripe 订阅编号', { exact: true }).fill(`sub_history${identity}`);
  await page.getByLabel('账单创建起始日期', { exact: true }).fill('2026-09-01');
  await page.getByRole('button', { name: '预览关联，不保存', exact: true }).click();
  const panel = page.getByRole('region', { name: `关联预览 Synthetic History ${identity}`, exact: true });
  await expect(panel.getByText('仅预览 · 尚未保存')).toBeVisible();
  return panel;
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= innerWidth)).toBe(true); }

test('真实隔离 API：手选关联→同区间去重试点→老板开放批量→逐笔核款，保留原财务与分润口径', async ({ browser, request }) => {
  test.skip(!accountFile || !existsSync(accountFile), '需显式提供仅含合成账号及假 Stripe 凭据的隔离 API 文件'); test.setTimeout(120000);
  const state = JSON.parse(readFileSync(accountFile, 'utf8')) as SyntheticState;
  expect(state.synthetic_only).toBe(true); expect(state.provider_synthetic_only).toBe(true);
  expect(state.base_url).toBe('http://127.0.0.1:4723');
  expect(basename(dirname(state.database))).toMatch(/^t24-stripe-history-browser-/); expect(basename(state.database)).toBe('sale.db');
  const contexts: BrowserContext[] = [];
  const owner = await login(request, state, '1'); const sales = await login(request, state, '11'); const ops = await login(request, state, '13');
  const headers = (actor = owner) => ({ Authorization: `Bearer ${actor.token}` });
  const get = (path: string, actor = owner) => request.get(`${state.base_url}${path}`, { headers: headers(actor) });
  const post = (path: string, data: unknown) => request.post(`${state.base_url}${base}${path}`, { headers: headers(), data });
  const ledger = async () => { const response = await get('/api/v1/entities/payments'); expect(response.status()).toBe(200); return (await response.json()).items; };
  const saveBinding = async (identity: number) => {
    const response = await post('/bindings/preview', { crm_subscription_id: identity, stripe_subscription_id: `sub_history${identity}`, sync_from: '2026-09-01', income_type: 'management_fee' });
    expect(response.status()).toBe(200); const result = await response.json(); expect(result.can_confirm).toBe(true);
    const confirmed = await post('/bindings', { token: result.token, owner_verified: true, accepted_warning_codes: result.warnings.map((item: { code: string }) => item.code) });
    expect(confirmed.status()).toBe(200); return (await confirmed.json()).binding;
  };
  const sync = async (id: number) => { const response = await post(`/bindings/${id}/sync`, { date_start: '2026-10-01', date_end: '2026-10-19' }); expect(response.status()).toBe(200); return response.json(); };
  try {
    expect(await ledger()).toHaveLength(0);
    for (const actor of [sales, ops]) for (const path of ['/overview', '/crm-services', '/stripe-subscriptions', '/invoice-reviews']) expect((await get(base + path, actor)).status()).toBe(403);
    const ownerUi = await open(browser, state, owner, '/finance?tab=stripe_reconciliation&stripe_view=mapping'); contexts.push(ownerUi.context);
    const panel = await preview(ownerUi.page, 100);
    expect((await (await get(base + '/overview')).json()).bindings).toHaveLength(0);
    expect(await ledger()).toHaveLength(0);
    for (const checkbox of await panel.getByRole('checkbox').all()) await checkbox.check();
    await noOverflow(ownerUi.page);
    if (process.env.T24_RECONCILIATION_SCREENSHOTS) await ownerUi.page.screenshot({ path: `${process.env.T24_RECONCILIATION_SCREENSHOTS}/isolated-mapping-preview-1093.png`, animations: 'disabled' });
    await panel.getByRole('button', { name: '确认建立关联', exact: true }).click();
    await expect(ownerUi.page.getByText('关联已保存；账单同步后仍需你逐笔核对。')).toBeVisible();
    const first = (await (await get(base + '/overview')).json()).bindings[0];
    const second = await saveBinding(101); const third = await saveBinding(102);
    await ownerUi.page.getByRole('button', { name: '对账总览', exact: true }).click();
    await expect(ownerUi.page.getByRole('button', { name: '启用批量关联', exact: true })).toBeDisabled();
    const firstRow = ownerUi.page.locator('.shr-binding').filter({ hasText: 'Synthetic History 100' });
    await firstRow.getByRole('button', { name: '同步账单', exact: true }).click();
    let dialog = ownerUi.page.getByRole('dialog');
    await dialog.getByLabel('同步开始日期', { exact: true }).fill('2026-10-01');
    await dialog.getByLabel('同步结束日期（不含）', { exact: true }).fill('2026-10-19');
    await dialog.getByRole('button', { name: '读取本区间账单', exact: true }).click();
    await expect(dialog.getByText('本页已读取 1 笔')).toBeVisible();
    await dialog.getByRole('button', { name: '再次同步本区间（去重核验）', exact: true }).click();
    await expect(dialog.getByRole('button', { name: '再次同步本区间（去重核验）', exact: true })).toBeEnabled();
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    const observed = (await (await get(base + '/overview')).json()).bindings.find((item: { id: number }) => item.id === first.id);
    expect(observed.pilot_evidence.successful_sync_count).toBe(2); expect(observed.pilot_evidence.repeat_dedupe_verified).toBe(true); expect(observed.pilot_evidence.cash_evidence_verified).toBe(true);
    expect(await ledger()).toHaveLength(0);
    await firstRow.getByRole('button', { name: '核对并验证试点', exact: true }).click();
    dialog = ownerUi.page.getByRole('dialog'); await dialog.getByLabel('试点核对说明', { exact: true }).fill('隔离验收：同区间去重与到账凭据一致');
    await dialog.getByRole('checkbox', { name: /我已亲自核对客户归属/ }).check();
    await dialog.getByRole('button', { name: '确认试点验证通过', exact: true }).click(); await expect(dialog).toHaveCount(0);
    for (const binding of [second, third]) {
      const firstPage = await sync(binding.id); const repeat = await sync(binding.id); expect(firstPage.items[0].id).toBe(repeat.items[0].id);
      const validated = await post(`/bindings/${binding.id}/validate-pilot`, { revision: repeat.binding.revision, owner_verified: true, verification_note: '隔离验收：两个相同区间读取去重与完整到账证据一致' }); expect(validated.status()).toBe(200);
    }
    expect(await ledger()).toHaveLength(0);
    await ownerUi.page.getByRole('button', { name: '刷新概览', exact: true }).click();
    await ownerUi.page.getByRole('button', { name: '启用批量关联', exact: true }).click(); dialog = ownerUi.page.getByRole('dialog');
    await dialog.getByLabel('试点核对说明', { exact: true }).fill('隔离验收：三家独立服务试点已逐项确认'); await dialog.getByRole('checkbox', { name: /我已核对至少 3 个试点/ }).check();
    await dialog.getByRole('button', { name: '确认启用批量关联', exact: true }).click(); await expect(ownerUi.page.getByText('批量关联已启用，仍逐项核对与确认')).toBeVisible();
    await ownerUi.page.getByRole('button', { name: '关联客户服务', exact: true }).click();
    const bulkPreview = await preview(ownerUi.page, 103); await bulkPreview.getByRole('button', { name: '加入批量待确认', exact: true }).click();
    const cart = ownerUi.page.getByRole('region', { name: '批量关联待确认清单', exact: true });
    expect((await (await get(base + '/overview')).json()).bindings).toHaveLength(3); expect(await ledger()).toHaveLength(0);
    for (const checkbox of await cart.getByRole('checkbox').all()) await checkbox.check();
    await cart.getByRole('button', { name: '确认关联这一项', exact: true }).click(); await expect(cart.getByText('关联已保存，账单仍须单独核对。')).toBeVisible();
    expect((await (await get(base + '/overview')).json()).bindings).toHaveLength(4); expect(await ledger()).toHaveLength(0);
    const reviewsResponse = await get(base + '/invoice-reviews?status=all'); const rows = (await reviewsResponse.json()).items;
    const reviewId = rows.find((row: { stripe_invoice_id: string }) => row.stripe_invoice_id === 'in_history100').id;
    const detail = (await (await get(`${base}/invoice-reviews/${reviewId}`)).json()).review;
    expect(detail.can_create_payment).toBe(true); expect(detail.tax_amount).toBe(17.33); expect(detail.fee_amount).toBe(6.5); expect(detail.net_amount).toBe(208.83); expect(detail.accounting_preview.stripe_fee_amount).toBe(6.04);
    await ownerUi.page.goto(`${web}/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=${reviewId}`);
    dialog = ownerUi.page.getByRole('dialog'); await expect(dialog.getByText('账单 in_history100', { exact: true })).toBeVisible();
    await expect(dialog.getByRole('button', { name: '确认并记账', exact: true })).toBeDisabled();
    await expect(dialog.getByText('USD 17.33', { exact: true })).toBeVisible(); await expect(dialog.getByText('USD 6.50', { exact: true })).toBeVisible(); await expect(dialog.getByText('USD 6.04', { exact: true })).toBeVisible();
    expect(await ledger()).toHaveLength(0); await ownerUi.page.setViewportSize({ width: 390, height: 844 }); await noOverflow(ownerUi.page);
    if (process.env.T24_RECONCILIATION_SCREENSHOTS) await ownerUi.page.screenshot({ path: `${process.env.T24_RECONCILIATION_SCREENSHOTS}/isolated-receipt-review-390.png`, animations: 'disabled' });
    await dialog.getByRole('radio', { name: '核对后手动新增一笔收入', exact: true }).check(); await dialog.getByLabel('老板核对说明', { exact: true }).fill('隔离验收：真实到账、税费、服务期间和原账均已核对');
    await dialog.getByRole('checkbox', { name: /我已核对真实到账、客户归属、税费/ }).check(); await dialog.getByRole('button', { name: '确认并记账', exact: true }).click();
    await expect(dialog.getByText(/该账单已由老板确认记账。 收款 #/)).toBeVisible();
    const payments = await ledger(); expect(payments).toHaveLength(1); const payment = payments[0]; expect(Number(payment.amount_paid)).toBe(198); expect(Number(payment.management_amount)).toBe(198); expect(Number(payment.ads_recharge_amount)).toBe(0); expect(Number(payment.stripe_fee_amount)).toBe(6.04); expect(Number(payment.net_amount)).toBe(191.96); expect(payment.transaction_reference).toBe('in_history100');
    const replay = await post(`/invoice-reviews/${reviewId}/confirm`, { revision: detail.revision, action: 'create_payment', owner_verified: true, verification_note: '隔离验收：重试核对完全相同的已处理凭据' }); expect(replay.status()).toBe(200); expect((await replay.json()).idempotent_replay).toBe(true); expect(await ledger()).toHaveLength(1);
    const opsUi = await open(browser, state, ops, '/finance?tab=stripe_reconciliation'); contexts.push(opsUi.context); await expect(opsUi.page.getByText(/无权限访问|Stripe 对账仅老板可见/)).toBeVisible(); await expect(opsUi.page.getByText('USD 17.33', { exact: true })).toHaveCount(0); expect(opsUi.writes.filter(path => path.startsWith(base))).toEqual([]);
    expect((await get(`${base}/invoice-reviews/${reviewId}`, sales)).status()).toBe(403); expect((await get(`${base}/invoice-reviews/${reviewId}`, ops)).status()).toBe(403);
    if (process.env.T24_RECONCILIATION_E2E_EVIDENCE) writeFileSync(process.env.T24_RECONCILIATION_E2E_EVIDENCE, JSON.stringify({ synthetic_only: true, provider_synthetic_only: true, backend: state.base_url, owner_manual_mapping: true, preview_does_not_bind: true, identical_sync_dedupe_verified: true, distinct_pilots: 3, pilot_validation_without_posting: true, explicit_bulk_activation: true, cart_requires_each_confirmation: true, bindings_after_cart: 4, formal_payments_before_owner_confirmation: 0, formal_payments_after_owner_confirmation: 1, original_service_base: 198, original_fee: 6.04, original_net: 191.96, actual_tax: 17.33, actual_fee: 6.5, actual_net: 208.83, repeat_confirmation_idempotent: true, ordinary_roles_denied: true, widths: [1093, 390] }, null, 2));
  } finally { await Promise.allSettled(contexts.map(context => context.close())); }
});
