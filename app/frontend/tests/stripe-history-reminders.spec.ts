import { expect, test, type Page, type Route } from '@playwright/test';

const web = process.env.T24_RECONCILIATION_BASE_URL || 'http://127.0.0.1:8921';
const base = '/api/v1/stripe-history-reconciliation';
const exception = { id: 72, kind: 'exception', customer_name: '已核账异常验收餐厅', package_name: '品牌官网', title: '已核账凭据发生变化，请核对原调整流程', href: '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=72', observed_at: '2026-10-19T01:01:00Z' };
const reminders = { counts: { pending_review: 2, needs_refresh: 1, exception: 1, total: 4 }, items: [{ id: 71, kind: 'pending_review', customer_name: '补查验收餐厅', package_name: '基础版', title: '续费收款待老板核对', href: '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=71', observed_at: '2026-10-19T01:01:00Z' }], exception_items: [exception], exception_has_more: false, daily_scan: { enabled: true, timezone: 'Asia/Shanghai', daily_time: '09:00', next_scheduled_at: '2026-10-20T01:00:00Z', last_completed_at: '2026-10-19T01:01:00Z', last_run_at: '2026-10-19T01:00:00Z', last_run_status: 'completed', last_discovered_reviews: 5, active_bindings: 18, covered_bindings: 18, catchup_bindings: 0, retry_bindings: 0, running_bindings: 0, last_error_code: null, covered_through: '2026-10-20T00:00:00Z', window_start: '2026-10-18T00:00:00Z', window_end: '2026-10-20T00:00:00Z' }, auto_accounting: false };

async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }); }
async function fixture(page: Page, options: { role?: string; failFirst?: boolean; revoked?: boolean; payload?: any } = {}) {
  const role = options.role || 'super_admin'; const employee = { id: role === 'super_admin' ? 1 : 7, name: '提醒验收账号', role, status: 'active' };
  let payload = structuredClone(options.payload || reminders); let calls = 0;
  const reads: string[] = []; const writes: string[] = [];
  await page.addInitScript(value => { localStorage.setItem('emp_auth_token', 'reminder-fixture'); localStorage.setItem('token', 'reminder-fixture'); localStorage.setItem('emp_auth_data', JSON.stringify(value)); }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') { writes.push(path); return json(route, { detail: '提醒验收禁止任何写入' }, 403); }
    reads.push(path);
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path === `${base}/reminders`) { calls += 1; if (options.revoked && calls > 1) return json(route, { detail: '当前账号无权读取财务提醒' }, 403); if (options.failFirst && calls === 1) return json(route, { detail: '提醒读取失败，请重试' }, 503); return json(route, payload); }
    if (path === '/api/v1/service-follow-through/owner-overview') return json(route, { counts: { total_actions: 0 }, items: [], generated_at: '2026-10-19T01:00:00Z' });
    if (path.endsWith('/management-decisions/owner-cockpit')) return json(route, { detail: '验收只读取独立提醒' }, 503);
    if (path === `${base}/overview`) return json(route, { configured: true, provider_status: 'configured', pilot: { limit: 5, enabled_bindings: 18, validated_bindings: 3, bulk_enabled: true, can_activate_bulk: false }, counts: { bindings: 18, pending_review: 2, needs_refresh: 1, exceptions: 1 }, bindings: [], invoice_reviews: [] });
    if (path === `${base}/invoice-reviews`) return json(route, { items: [], counts: {}, total: 0 });
    if (/\/invoice-reviews\/7[12]$/.test(path)) return json(route, { review: { id: Number(path.slice(-2)), binding_id: 1, customer_id: 301, customer_name: exception.customer_name, package_name: exception.package_name, stripe_invoice_id: 'in_syntheticReminder', status: 'confirmed', currency: 'USD', revision: 1, payment_date: '2026-10-18', service_amount: 99, gross_amount: 99, fee_amount: 3.17, net_amount: 95.83, tax_amount: 0, issues: [], lines: [], existing_payment_candidates: [], accounting_preview: null, can_confirm: false, can_create_payment: false, can_link_existing: false, payment_id: 90 } });
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.includes('/admin/settings')) return json(route, { backend_vars: {}, frontend_vars: {} });
    return json(route, { items: [], total: 0 });
  });
  return { reads, writes, update: (value: any) => { payload = structuredClone(value); } };
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= innerWidth)).toBe(true); }

for (const width of [1093, 390]) {
  test(`老板首屏 ${width}：待核数、异常和补查结果可见，点击只读去处理`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); const { writes } = await fixture(page); await page.goto(web);
    const panel = page.getByRole('region', { name: 'Stripe 待核提醒', exact: true });
    await expect(panel.getByRole('button', { name: 'Stripe 待核收款 3', exact: true })).toBeVisible(); await expect(panel.getByRole('button', { name: '异常 1', exact: true })).toBeVisible();
    await expect(panel.getByText('最近补查已完成', { exact: true })).toBeVisible(); await expect(panel.getByText('发现新账单 5 笔', { exact: true })).toBeVisible();
    expect((await panel.boundingBox())!.y).toBeLessThan(844); await noOverflow(page);
    await panel.getByRole('button', { name: 'Stripe 待核收款 3', exact: true }).click(); await expect(page).toHaveURL(/stripe_status=unverified/); expect(writes).toEqual([]);
  });
  test(`对账页 ${width}：补查首屏明确每天09点且不代替核款`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); const { writes } = await fixture(page); await page.goto(`${web}/finance?tab=stripe_reconciliation`);
    const panel = page.getByRole('region', { name: 'Stripe 每日补查', exact: true }); await expect(panel.getByText('每日 09:00（北京时间）补查', { exact: true })).toBeVisible();
    await panel.getByText('查看补查进度与待核事项').click(); await expect(panel.getByText('补查只生成待核对账单；实际到账、税费和是否入账仍由你逐笔核对。', { exact: true })).toBeVisible(); await noOverflow(page); expect(writes).toEqual([]);
  });
}

test('已入账凭据变化异常独立展开，不跳旧exception筛选，直接打开原账详情', async ({ page }) => {
  const { writes } = await fixture(page, { payload: { ...reminders, items: [], exception_has_more: true } }); await page.goto(`${web}/finance?tab=stripe_reconciliation`);
  const panel = page.getByRole('region', { name: 'Stripe 每日补查', exact: true }); await panel.getByRole('button', { name: '异常 1', exact: true }).click();
  const list = panel.getByRole('region', { name: 'Stripe 异常清单', exact: true }); await expect(list.getByText('先处理最近 20 条异常，其余事项仍保留。', { exact: true })).toBeVisible();
  await list.getByRole('button', { name: /已核账异常验收餐厅/ }).click(); await expect(page).toHaveURL(/stripe_review=72/); await expect(page.getByRole('dialog').getByText('账单 in_syntheticReminder')).toBeVisible(); expect(writes).toEqual([]);
});
test('读取失败不是零异常，重试成功；重新聚焦后待核数字同步变化', async ({ page }) => {
  const fixtureData = await fixture(page, { failFirst: true }); await page.goto(web); const panel = page.getByRole('region', { name: 'Stripe 待核提醒', exact: true });
  await expect(panel.getByText('提醒读取失败，请重试', { exact: true })).toBeVisible(); await expect(panel.getByText('最近补查已完成', { exact: true })).toHaveCount(0);
  await panel.getByRole('button', { name: '刷新 Stripe 待核提醒', exact: true }).click(); await expect(panel.getByRole('button', { name: 'Stripe 待核收款 3', exact: true })).toBeVisible();
  fixtureData.update({ ...reminders, counts: { pending_review: 0, needs_refresh: 0, exception: 0, total: 0 }, exception_items: [] }); await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(panel.getByRole('button', { name: 'Stripe 待核收款 0', exact: true })).toBeVisible(); expect(fixtureData.writes).toEqual([]);
});
test('权限撤销清空旧数据，普通员工不出现提醒也不请求此接口', async ({ page }) => {
  await fixture(page, { revoked: true }); await page.goto(web); const panel = page.getByRole('region', { name: 'Stripe 待核提醒', exact: true }); await panel.getByRole('button', { name: '异常 1', exact: true }).click(); await expect(panel.getByText(exception.customer_name, { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '刷新 Stripe 待核提醒', exact: true }).click(); await expect(panel.getByText('当前账号无权读取财务提醒', { exact: true })).toBeVisible(); await expect(panel.getByText(exception.customer_name, { exact: true })).toHaveCount(0);
  const context = await page.context().browser()!.newContext(); const staff = await context.newPage(); const staffData = await fixture(staff, { role: 'ops' }); await staff.goto(web); await expect(staff.getByRole('region', { name: 'Stripe 待核提醒', exact: true })).toHaveCount(0); await staff.goto(`${web}/finance?tab=stripe_reconciliation`); expect(staffData.reads).not.toContain(`${base}/reminders`); expect(staffData.writes).toEqual([]); await context.close();
});
for (const [status, label] of [['disabled', '每日补查未启用'], ['no_bindings', '暂无已关联服务可补查'], ['never', '等待首次补查'], ['partial', '补查尚未完成'], ['retrying', '补查待重试']] as const) {
  test(`补查${status}明确显示未完整覆盖，不默认零发现`, async ({ page }) => {
    await fixture(page, { payload: { ...reminders, daily_scan: { ...reminders.daily_scan, enabled: status !== 'disabled', last_run_status: status, active_bindings: status === 'no_bindings' ? 0 : 18, covered_bindings: 0, catchup_bindings: status === 'never' ? 0 : 2, retry_bindings: status === 'retrying' ? 1 : 0, last_completed_at: null, last_discovered_reviews: null } } });
    await page.goto(`${web}/finance?tab=stripe_reconciliation`); const panel = page.getByRole('region', { name: 'Stripe 每日补查', exact: true }); await expect(panel.getByText(label, { exact: true })).toBeVisible(); await expect(panel.getByText('新账单数待确认', { exact: true })).toBeVisible(); await expect(panel.getByText('发现新账单 0 笔', { exact: true })).toHaveCount(0);
  });
}
