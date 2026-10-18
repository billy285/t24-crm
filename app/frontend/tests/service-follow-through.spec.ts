import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_FOLLOW_THROUGH_BASE_URL || 'http://127.0.0.1:8921';
const serviceBase = '/api/v1/service-follow-through';
const coverage = { webhook_configured: true, linked_subscriptions: 1, unconnected_subscriptions: 2, note: '仅覆盖已关联成交后的通知，未收到通知不等于扣款正常。' };
const summary = { handoff_id: 81, customer_id: 301, business_name: '开工验收餐厅', package_name: '基础版 · 月付', selected_platforms: ['Facebook', 'Instagram'], operations_owner_name: '验收运营', operations_status: 'accepted', service_start_date: '2026-10-18', service_end_date: '2026-11-18', initialized: true, can_edit: true, status: 'in_progress', completed_count: 0, total_count: 2, first_delivery_due_date: '2026-10-23', revision: 1, href: '/operations-workbench?view=kickoffs&handoff=81' };
const steps = [{ key: 'platform_authorization', title: '确认平台授权', status: 'pending', due_date: '2026-10-23', note: '', evidence: '' }, { key: 'first_delivery', title: '安排首次交付', status: 'pending', due_date: '2026-10-23', note: '', evidence: '' }];
async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }); }
async function fixture(page: Page, options: { role?: string; readOnly?: boolean; initialized?: boolean; failList?: boolean; empty?: boolean; conflict?: boolean; maliciousHref?: boolean } = {}) {
  const role = options.role || 'super_admin'; const employee = { id: role === 'super_admin' ? 1 : 7, name: role === 'super_admin' ? '验收老板' : '验收运营', role, status: 'active' };
  const reads: string[] = []; const writes: { path: string; method: string; body: any }[] = []; let conflicts = 0; let failList = options.failList; let detail: any = { ...summary, initialized: options.initialized !== false, can_edit: options.readOnly !== true, read_only_reason: options.readOnly ? '当前只有交付查看权限，不能修改清单。' : undefined, status: options.initialized === false ? 'missing' : summary.status, items: options.initialized === false ? [] : steps.map(item => ({ ...item })), audit: [] };
  await page.addInitScript(value => { localStorage.setItem('emp_auth_token', 'follow-through-fixture'); localStorage.setItem('token', 'follow-through-fixture'); localStorage.setItem('emp_auth_data', JSON.stringify(value)); }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (request.method() !== 'GET') {
      const body = request.postData() ? request.postDataJSON() : {}; writes.push({ path, method: request.method(), body });
      if (path === `${serviceBase}/kickoffs/81/initialize`) { detail = { ...detail, initialized: true, status: 'in_progress', first_delivery_due_date: body.first_delivery_due_date, items: steps.map(item => ({ ...item, due_date: body.first_delivery_due_date })), audit: [{ id: 1, action: 'initialize', actor_name: employee.name, created_at: '2026-10-18T03:00:00Z' }] }; return json(route, { kickoff: detail }); }
      if (path === `${serviceBase}/kickoffs/81/items/platform_authorization`) {
        if (options.conflict && conflicts++ === 0) { detail.revision = 2; return json(route, { detail: '记录已被其他人更新，请重新读取后核对。' }, 409); }
        detail = { ...detail, revision: detail.revision + 1, completed_count: body.status === 'completed' ? 1 : 0, items: detail.items.map((item: any) => item.key === 'platform_authorization' ? { ...item, ...body, updated_by_name: employee.name } : item), audit: [{ id: 2, item_key: 'platform_authorization', action: 'update', actor_name: employee.name, created_at: '2026-10-18T03:00:00Z' }] }; return json(route, { kickoff: detail });
      }
      return json(route, { detail: '本验收禁止其他写入' }, 403);
    }
    reads.push(path);
    if (path.endsWith('/emp-auth/me')) return json(route, employee);
    if (path === `${serviceBase}/owner-overview`) return json(route, { counts: { pending_receipt: 1, pending_access: 1, pending_operations: 0, kickoff_missing: 0, kickoff_overdue: 0, renewal_attention: 1, renewal_unconnected: 2, total_actions: 5 }, items: [{ id: 'receipt-81', kind: 'pending_receipt', title: '核对客户收款', business_name: summary.business_name, waiting_days: 3, severity: 'high', href: options.maliciousHref ? 'https://example.com/untrusted' : '/sales-leads?view=handoffs&status=pending_payment' }, { id: 'renewal-81', kind: 'renewal_attention', title: '续费扣款失败待核对', business_name: summary.business_name, href: '/operations-workbench?view=renewals&status=attention' }], coverage, generated_at: '2026-10-18T03:00:00Z' });
    if (path === `${serviceBase}/kickoffs`) { if (failList) { failList = false; return json(route, { detail: '开工记录暂时无法读取' }, 503); } return json(route, { items: options.empty ? [] : [detail], counts: { all: 1, missing: detail.initialized ? 0 : 1, in_progress: 1, overdue: 0, completed: 0 } }); }
    if (path === `${serviceBase}/kickoffs/81`) return json(route, { kickoff: detail });
    if (path === `${serviceBase}/renewals`) return json(route, { items: options.empty ? [] : [{ id: 'renewal-81', handoff_id: 81, customer_id: 301, business_name: summary.business_name, package_name: summary.package_name, billing_cycle: 'monthly', due_date: '2026-11-18', connection_status: 'linked', status: 'payment_failed', status_label: '扣款失败，待老板核对', latest_event_at: '2026-10-18T03:00:00Z', signals: [{ kind: 'invoice.payment_failed', status: 'failed', label: '续费扣款失败', invoice_id: 'in_synthetic_81', subscription_id: 'sub_synthetic_81', event_at: '2026-10-18T03:00:00Z', amount: 198, currency: 'USD' }], href: '/sales-leads?view=handoffs' }], counts: { all: 1, attention: 1, unconnected: 2, upcoming: 0 }, coverage });
    if (path.endsWith('/management-decisions/owner-cockpit')) return json(route, { detail: '仅测试独立异常模块' }, 503);
    if (path.includes('/app-config')) return json(route, { items: {} });
    if (path.includes('/admin/settings')) return json(route, { backend_vars: {}, frontend_vars: {} });
    return json(route, { items: [], total: 0 });
  });
  return { reads, writes, getDetail: () => detail };
}
async function overflow(page: Page) { expect(await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= innerWidth)).toBe(true); }

for (const width of [1093, 390]) {
  test(`老板异常总览 ${width}：有重点、可直达、核款仍由老板完成`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); const { writes } = await fixture(page); await page.goto(baseUrl);
    const panel = page.getByRole('region', { name: '老板异常总览' }); await expect(panel.getByText('核对客户收款', { exact: true })).toBeVisible(); await expect(panel.getByText('已等待 3 天', { exact: false })).toBeVisible();
    await panel.getByRole('button', { name: '续费待核对 1', exact: true }).click(); await expect(page).toHaveURL(/view=renewals/); await expect(page.getByText('扣款失败，待老板核对')).toBeVisible(); await overflow(page); expect(writes).toEqual([]);
    if (process.env.T24_FOLLOW_THROUGH_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_FOLLOW_THROUGH_SCREENSHOTS}/renewal-owner-${width}.png`, animations: 'disabled' });
  });
  test(`运营清单 ${width}：本人交付编辑、保存依据，不出现收款或财务`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 }); const { writes, reads } = await fixture(page, { role: 'ops' }); await page.goto(`${baseUrl}/operations-workbench?view=kickoffs&handoff=81`);
    await expect(page.getByText('已完成 0/2 项')).toBeVisible(); await expect(page.getByRole('button', { name: '续费提醒' })).toHaveCount(0); await expect(page.getByText(/到账|利润|税额/)).toHaveCount(0);
    await page.getByRole('button', { name: '更新进度：确认平台授权', exact: true }).click(); const dialog = page.getByRole('dialog'); await dialog.getByLabel('进度状态').selectOption('completed'); await dialog.getByLabel('完成日期').fill('2026-10-18'); await dialog.getByLabel('进度说明').fill('已收到客户平台授权'); await dialog.getByLabel('依据 / 资料位置').fill('客户授权回执 #81'); await overflow(page);
    if (process.env.T24_FOLLOW_THROUGH_SCREENSHOTS) await page.screenshot({ path: `${process.env.T24_FOLLOW_THROUGH_SCREENSHOTS}/kickoff-editor-${width}.png`, animations: 'disabled' });
    await dialog.getByRole('button', { name: '保存进度', exact: true }).click(); await expect(dialog).toHaveCount(0); await expect(page.getByText('已完成 1/2 项')).toBeVisible(); await expect(page.getByText('依据：客户授权回执 #81')).toBeVisible(); expect(writes).toHaveLength(1); expect(writes[0].body.revision).toBe(1); expect(writes[0].body.status).toBe('completed'); expect(reads.some(path => path.endsWith('/renewals') || path.endsWith('/owner-overview'))).toBe(false); await overflow(page);
  });
}

test('只读运营无建立或更新入口，直接打开续费地址也不请求财务接口', async ({ page }) => {
  const { writes, reads } = await fixture(page, { role: 'ops', readOnly: true }); await page.goto(`${baseUrl}/operations-workbench?view=kickoffs&handoff=81`); await expect(page.getByText('当前只有交付查看权限，不能修改清单。')).toBeVisible(); await expect(page.getByRole('button', { name: /更新进度|建立开工清单/ })).toHaveCount(0); await page.goto(`${baseUrl}/operations-workbench?view=renewals`); await expect(page.getByText('续费付款信息仅老板可见。')).toBeVisible(); expect(reads).not.toContain(`${serviceBase}/renewals`); expect(writes).toEqual([]);
});
test('未建立清单只读读取不写入，指定运营选好首交日期才建立', async ({ page }) => {
  const { writes } = await fixture(page, { role: 'ops', initialized: false }); await page.goto(`${baseUrl}/operations-workbench?view=kickoffs&handoff=81`); await expect(page.getByRole('button', { name: '建立开工清单', exact: true })).toBeDisabled(); expect(writes).toEqual([]); await page.getByLabel('首次交付计划日期').fill('2026-10-23'); await page.getByRole('button', { name: '建立开工清单', exact: true }).click(); await expect(page.getByText('已完成 0/2 项')).toBeVisible(); expect(writes).toHaveLength(1); expect(writes[0].body).toEqual({ first_delivery_due_date: '2026-10-23' });
});
test('记录冲突保留输入，读取新版本后重新核对保存', async ({ page }) => {
  const { writes } = await fixture(page, { role: 'ops', conflict: true }); await page.goto(`${baseUrl}/operations-workbench?view=kickoffs&handoff=81`); await page.getByRole('button', { name: '更新进度：确认平台授权', exact: true }).click(); const dialog = page.getByRole('dialog'); await dialog.getByLabel('进度状态').selectOption('blocked'); await dialog.getByLabel('进度说明').fill('等待客户补充授权'); await dialog.getByRole('button', { name: '保存进度', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('记录已被其他人更新'); await expect(dialog.getByLabel('进度说明')).toHaveValue('等待客户补充授权'); await dialog.getByRole('button', { name: '刷新记录（保留输入）' }).click(); await expect(dialog.getByLabel('进度说明')).toHaveValue('等待客户补充授权'); await dialog.getByRole('button', { name: '保存进度', exact: true }).click(); await expect(dialog).toHaveCount(0); expect(writes[1].body.revision).toBe(2);
});
test('关闭编辑弹窗可直接操作，没有写入，重新打开保留草稿', async ({ page }) => {
  const { writes } = await fixture(page, { role: 'ops' }); await page.goto(`${baseUrl}/operations-workbench?view=kickoffs&handoff=81`); await page.getByRole('button', { name: '更新进度：确认平台授权', exact: true }).click(); await page.getByLabel('进度说明').fill('尚未保存的补充'); await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click(); await expect(page.getByRole('dialog')).toHaveCount(0); await page.getByRole('button', { name: '更新进度：确认平台授权', exact: true }).click(); await expect(page.getByLabel('进度说明')).toHaveValue('尚未保存的补充'); expect(writes).toEqual([]);
});
test('读取失败不显示正常空态，可重试；空记录明确覆盖未确认', async ({ page }) => {
  await fixture(page, { role: 'ops', failList: true }); await page.goto(`${baseUrl}/operations-workbench?view=kickoffs`); await expect(page.getByRole('alert')).toContainText('开工记录暂时无法读取'); await expect(page.getByText('当前分类暂无开工清单')).toHaveCount(0); await page.getByRole('button', { name: '刷新记录', exact: true }).click(); await expect(page.getByText('开工验收餐厅', { exact: true })).toBeVisible();
});
test('续费通知依据只读，保留回到来源地址，数据未覆盖不宣称全部正常', async ({ page }) => {
  const { writes } = await fixture(page); await page.goto(`${baseUrl}/operations-workbench?view=renewals&returnTo=%2F`); await expect(page.getByText('仅覆盖已关联成交后的通知，未收到通知不等于扣款正常。')).toBeVisible(); await page.getByText('查看通知依据 · 1 条').click(); await expect(page.getByText('账单 in_synthetic_81')).toBeVisible(); await expect(page.getByText('USD 198.00 · 通知金额，待老板核对')).toBeVisible(); await page.getByRole('button', { name: '返回来源页面', exact: true }).click(); await expect(page).toHaveURL(baseUrl + '/'); expect(writes).toEqual([]);
});
test('老板总览拒绝外部跳转地址', async ({ page }) => { await fixture(page, { maliciousHref: true }); await page.goto(baseUrl); await expect(page.getByRole('region', { name: '老板异常总览' }).getByRole('button', { name: /先处理 核对客户收款/ })).toBeDisabled(); });

test('提醒随重新聚焦读取最新数据；开工编辑不被后台刷新覆盖', async ({ page }) => {
  const { reads } = await fixture(page); await page.goto(baseUrl); await expect(page.getByRole('region', { name: '老板异常总览' })).toBeVisible(); const before = reads.filter(path => path.endsWith('/owner-overview')).length; await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await expect.poll(() => reads.filter(path => path.endsWith('/owner-overview')).length).toBeGreaterThan(before);
  await page.goto(`${baseUrl}/operations-workbench?view=renewals`); await expect(page.getByText('扣款失败，待老板核对')).toBeVisible(); const renewalsBefore = reads.filter(path => path.endsWith('/renewals')).length; await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await expect.poll(() => reads.filter(path => path.endsWith('/renewals')).length).toBeGreaterThan(renewalsBefore);
  await page.goto(`${baseUrl}/operations-workbench?view=kickoffs&handoff=81`); await page.getByRole('button', { name: '更新进度：确认平台授权', exact: true }).click(); await page.getByLabel('进度说明').fill('未提交的开工草稿'); const detailBefore = reads.filter(path => path.endsWith('/kickoffs/81')).length; await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await expect(page.getByLabel('进度说明')).toHaveValue('未提交的开工草稿'); expect(reads.filter(path => path.endsWith('/kickoffs/81')).length).toBe(detailBefore);
});
