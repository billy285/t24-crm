import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname } from 'node:path';
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from '@playwright/test';

const baseUrl = process.env.T24_HANDOFF_BASE_URL || 'http://127.0.0.1:8917';
const accountFile = process.env.T24_HANDOFF_E2E_ACCOUNTS || '';
type SyntheticState = { synthetic_only: boolean; base_url: string; database: string; accounts: Record<string, { email: string; password: string; role: string }> };

/** Real login and session checks; credentials never enter test output or screenshots. */
async function login(request: APIRequestContext, state: SyntheticState, actor: string) {
  const account = state.accounts[actor];
  const response = await request.post(`${state.base_url}/api/v1/emp-auth/login`, { data: { email: account.email, password: account.password } });
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(typeof data.token).toBe('string');
  return data as { token: string; employee: { id: number; role: string; name: string } };
}
async function openRole(browser: Browser, state: SyntheticState, session: Awaited<ReturnType<typeof login>>, url: string) {
  const context = await browser.newContext({ viewport: { width: 1093, height: 824 } });
  await context.addInitScript(auth => {
    localStorage.setItem('emp_auth_token', auth.token); localStorage.setItem('token', auth.token); localStorage.setItem('emp_auth_data', JSON.stringify(auth.employee));
  }, session);
  const page = await context.newPage();
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const original = new URL(route.request().url());
    if (original.pathname === '/api/config') return route.fulfill({ json: { API_BASE_URL: baseUrl } });
    // Every business/auth response comes from the disposable local API. Never fall through to production.
    const response = await route.fetch({ url: `${state.base_url}${original.pathname}${original.search}` });
    await route.fulfill({ response });
  });
  await page.goto(`${baseUrl}${url}`);
  return { context, page };
}

test('真实隔离API：销售固定价登记→老板邀请→运营本人接收→老板真实全额核款', async ({ browser, request }) => {
  test.skip(!accountFile || !existsSync(accountFile), '需显式提供仅含合成数据的隔离 API 账号文件');
  test.setTimeout(90000);
  const state = JSON.parse(readFileSync(accountFile, 'utf8')) as SyntheticState;
  expect(state.synthetic_only).toBe(true); expect(state.base_url).toBe('http://127.0.0.1:4719'); expect(basename(dirname(state.database))).toMatch(/^t24-handoff-browser-/); expect(basename(state.database)).toBe('sale.db');
  const contexts: BrowserContext[] = [];
  try {
    const sales = await login(request, state, '11'); const owner = await login(request, state, '1'); const ops = await login(request, state, '13');
    const headers = (session: typeof sales) => ({ Authorization: `Bearer ${session.token}` });
    const fresh = await request.get(`${state.base_url}/api/v1/sales-deal-handoffs/leads/1`, { headers: headers(sales) }); expect(fresh.status()).toBe(200); expect((await fresh.json()).registered).toBe(false);
    const salesBrowser = await openRole(browser, state, sales, '/sales-leads?lead_id=1&action=deal'); contexts.push(salesBrowser.context); const salesPage = salesBrowser.page;
    const dialog = salesPage.getByRole('dialog', { name: '登记成交 · Synthetic Merchant', exact: true }); await dialog.getByLabel('统一套餐', { exact: true }).selectOption('1');
    await expect(dialog.getByText('USD 198.00', { exact: true })).toBeVisible(); await dialog.getByLabel('服务开始', { exact: true }).fill('2026-10-16'); await expect(dialog.getByLabel('服务结束', { exact: true })).toHaveValue('2026-11-16'); await dialog.getByLabel('Google Business Profile', { exact: true }).check();
    await dialog.getByRole('button', { name: '下一步', exact: true }).click(); await expect(dialog.getByText('老板 · 决策人', { exact: true })).toBeVisible(); await dialog.getByLabel('运营接收负责人', { exact: true }).selectOption('13'); await dialog.getByLabel('特殊承诺 / 注意事项', { exact: true }).fill('每周向商家确认交付进度'); await dialog.getByRole('button', { name: '下一步', exact: true }).click(); await dialog.getByLabel('成交确认说明', { exact: true }).fill('合成商家已确认统一套餐及服务范围'); await dialog.getByRole('checkbox', { name: '我已核对套餐和交接内容' }).check();
    const registeredResponse = salesPage.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/sales-deal-handoffs/leads/1' && response.request().method() === 'POST'); await dialog.getByRole('button', { name: '确认登记成交', exact: true }).click(); const registration = await registeredResponse; expect(registration.status()).toBe(200); const registered = (await registration.json()).handoff;
    await expect(dialog.getByText('成交已登记', { exact: true })).toBeVisible(); await expect(dialog.getByRole('button', { name: '查看客户与交接' })).toHaveCount(0); expect(registered).not.toHaveProperty('payment_status'); expect(registered.can_view_customer).toBe(false); expect(registered.operations_access_status).toBe('pending');
    const deniedAck = await request.post(`${state.base_url}/api/v1/sales-deal-handoffs/${registered.id}/operations-acknowledgment`, { headers: headers(ops), data: { note: '未授权前不得接收' } }); expect(deniedAck.status()).toBe(403);
    const grant = await request.put(`${state.base_url}/api/v1/entities/customers/${registered.customer_id}/access`, { headers: headers(owner), data: { members: [{ employee_id: 13, access_level: 'read_only', scopes: { basic: 'none', contacts: 'none', followups: 'none', opportunities: 'none', delivery: 'read_only', renewals: 'none', deals: 'none', materials: 'none' }, finance_access: 'none', can_delete: false, can_export: false, can_reassign: false }] } }); expect(grant.status()).toBe(200);
    const opsBrowser = await openRole(browser, state, ops, `/customers?detail=${registered.customer_id}`); contexts.push(opsBrowser.context); const opsCard = opsBrowser.page.getByRole('region', { name: '售前承接', exact: true });
    await expect(opsCard.getByText('需要增加预约', { exact: true })).toBeVisible(); await expect(opsCard.getByText('2026-10-16 至 2026-11-16', { exact: true })).toBeVisible(); await expect(opsCard.getByText(/承接联系人|售前沟通记录|售前重点摘要|USD|收款已核对|收款待核对/)).toHaveCount(0); await expect(opsCard.getByRole('button', { name: '核对全额收款' })).toHaveCount(0);
    await opsCard.getByRole('button', { name: '确认本人接收', exact: true }).click(); await opsCard.getByLabel('接收备注').fill('本人已核对目标与承诺，确认接收'); await opsCard.getByRole('checkbox', { name: '我已查看上述交接资料' }).check(); await opsCard.getByRole('button', { name: '确认接收', exact: true }).click(); await expect(opsCard.getByText('运营已接收', { exact: true })).toBeVisible();
    const ownerBrowser = await openRole(browser, state, owner, `/customers?detail=${registered.customer_id}`); contexts.push(ownerBrowser.context); const ownerCard = ownerBrowser.page.getByRole('region', { name: '售前承接', exact: true }); await expect(ownerBrowser.page.getByText('在服套餐', { exact: true }).locator('..').getByText('0', { exact: true })).toBeVisible(); await ownerCard.getByRole('button', { name: '核对全额收款', exact: true }).click(); await expect(ownerCard.getByLabel('实际到账日期', { exact: true })).toHaveValue(''); await ownerCard.getByLabel('实际到账金额', { exact: true }).fill('198'); await ownerCard.getByLabel('实际到账日期', { exact: true }).fill('2026-10-16'); await ownerCard.getByLabel('实际收款方式', { exact: true }).selectOption('stripe'); await ownerCard.getByLabel('交易号 / 凭据编号', { exact: true }).fill('SYNTHETIC-UI-RECEIPT-001'); await ownerCard.getByRole('checkbox', { name: '我已核对真实到账凭据' }).check(); await ownerCard.getByRole('button', { name: '确认全额到账', exact: true }).click(); await expect(ownerCard.getByText('收款已核对', { exact: true })).toBeVisible(); await expect(ownerCard.getByRole('button', { name: '核对全额收款' })).toHaveCount(0); await expect(ownerBrowser.page.getByText('在服套餐', { exact: true }).locator('..').getByText('1', { exact: true })).toBeVisible();
    const final = await request.get(`${state.base_url}/api/v1/sales-deal-handoffs/${registered.id}`, { headers: headers(owner) }); expect(final.status()).toBe(200); const finalReceipt = (await final.json()).handoff; expect(finalReceipt.payment_status).toBe('paid'); expect(finalReceipt.operations_status).toBe('accepted'); expect(finalReceipt.can_finance_confirm).toBe(false);
    if (process.env.T24_HANDOFF_E2E_EVIDENCE) writeFileSync(process.env.T24_HANDOFF_E2E_EVIDENCE, JSON.stringify({ synthetic_only: true, backend: state.base_url, registered: true, handoff_id: registered.id, customer_id: registered.customer_id, no_automatic_invitation: true, uninvited_ack_status: deniedAck.status(), delivery_only_hidden: ['contacts', 'history', 'finance'], payment_status: finalReceipt.payment_status, operations_status: finalReceipt.operations_status, finance_reconfirm_available: finalReceipt.can_finance_confirm }, null, 2));
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
