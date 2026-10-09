import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
if (!['127.0.0.1', 'localhost'].includes(new URL(baseUrl).hostname)) throw new Error('Financial editing tests require a local fixture server');
const screenshotDir = process.env.T24_FINANCE_EDITING_SCREENSHOT_DIR;

async function fixture(page: Page, options: { closed?: boolean; width?: number; restricted?: boolean; stripeFee?: number; currency?: string; rejectSave?: boolean; admin?: boolean; subscriptions?: boolean } = {}) {
  await page.setViewportSize({ width: options.width || 390, height: 844 });
  await page.clock.install({ time: new Date('2026-08-05T12:00:00+08:00') });
  const employee = { id: 89, name: '财务编辑模拟账号', role: options.restricted ? 'sales' : options.admin ? 'admin' : 'finance', status: 'active' };
  await page.addInitScript(({ employee, restricted }) => {
    localStorage.setItem('emp_auth_token', 'local-finance-editing');
    localStorage.setItem('token', 'local-finance-editing');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
    if (restricted) localStorage.setItem('crm_role_permissions', JSON.stringify({ sales: { pages: ['/finance'], buttons: [], dataScope: 'self' } }));
  }, { employee, restricted: options.restricted });
  const entities: Record<string, any[]> = {
    customers: [{ id: 9, business_name: '编辑测试商家', status: 'active' }],
    payments: [{ id: 91, customer_id: 9, customer_name: '编辑测试商家', product_name: 'Google Ads', income_type: 'management_fee', amount_due: 398, amount_paid: 298, management_amount: 298, ads_recharge_amount: 0, currency: 'USD', payment_mode: 'manual_collection', payment_method: 'zelle', billing_cycle: 'monthly', payment_date: '2026-08-01', notes: '原收款备注' }],
    expenses: [{ id: 92, customer_id: 9, customer_name: '编辑测试商家', expense_type: 'website_fee', expense_category: 'customer', currency: 'CNY', amount: 80, expense_month: '2026-08', notes: '原客户成本备注' }],
    company_expenses: [{ id: 93, category: 'software', category_name: '软件订阅', currency: 'CNY', amount: 166, expense_month: '2026-08', expense_date: '2026-08-02', notes: '原运营支出备注' }],
    subscriptions: [],
  };
  if (options.subscriptions) entities.subscriptions = [
    { id: 101, customer_id: 9, customer_name: '编辑测试商家', package_name: '模拟待核对套餐', package_price: 298, billing_cycle: 'monthly', auto_renew: true, status: 'renewal_pending', start_date: '2026-07-01', end_date: '2026-08-01', next_payment_date: '2026-08-01', renewal_person: '模拟负责人' },
    ...Array.from({ length: 20 }, (_, index) => ({ id: 102 + index, customer_id: 9, customer_name: '编辑测试商家', package_name: `模拟正常套餐${String(index + 1).padStart(2, '0')}`, package_price: 200 + index, billing_cycle: 'monthly', auto_renew: true, status: 'active', start_date: '2026-08-01', end_date: '2026-09-30', next_payment_date: '2026-09-30', renewal_person: '模拟负责人' })),
  ];
  const settlements = [{ id: 94, customer_id: 9, customer_name: '编辑测试商家', year_month: '2026-08', currency: 'USD', opening_balance: 0, funds_received: 200, actual_ad_spend: 50, customer_refund_amount: 0, recognized_spread_amount: 10, adjustment_amount: 0, closing_balance: 140, status: 'draft', notes: '原月结备注' }];
  if (options.currency) entities.payments[0].currency = options.currency;
  if (options.stripeFee !== undefined) Object.assign(entities.payments[0], { payment_mode: 'subscription_auto', payment_method: 'stripe', stripe_fee_amount: options.stripeFee, net_amount: 298 - options.stripeFee });
  const writes: Array<{ method: string; path: string; data: any }> = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (req.method() !== 'GET') {
      const data = req.postDataJSON();
      writes.push({ method: req.method(), path, data });
      if (options.rejectSave && path === '/api/v1/entities/payments/91') return route.fulfill({ status: 409, json: { detail: '记录已变更，请刷新后重试' } });
      const match = path.match(/\/entities\/([^/]+)\/(\d+)$/);
      if (match && entities[match[1]]) entities[match[1]] = entities[match[1]].map(row => row.id === Number(match[2]) ? { ...row, ...data } : row);
      return route.fulfill({ json: { id: Number(match?.[2] || 99), ...data } });
    }
    const entity = path.match(/\/entities\/([^/]+)/)?.[1];
    const data = path.endsWith('/emp-auth/me') ? employee
      : path === '/api/v1/app-config' ? { items: {} }
      : path.endsWith('/app-config/export_config') ? { value: { financeClosedMonths: options.closed ? ['2026-08'] : [] } }
      : path.includes('/app-config/') ? { value: {} }
      : path.includes('/reports/profit-monthly.json') ? []
      : path.startsWith('/api/v1/deductions-monthly') ? [{ year_month: '2026-08', rate: 0.15 }]
      : path.endsWith('/finance/ad-fund-settlements') ? { items: settlements }
      : path.endsWith('/finance/refunds') ? { items: [] }
      : path.endsWith('/commissions/dashboard') ? { entries: [] }
      : path.endsWith('/product-plans') ? { business_lines: [], products: [], plans: [] }
      : entity ? { items: entities[entity] || [], total: (entities[entity] || []).length }
      : { items: [], total: 0 };
    return route.fulfill({ json: data });
  });
  return writes;
}

async function assertDialogFits(page: Page) {
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const geometry = await dialog.evaluate(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth, rect: el.getBoundingClientRect().toJSON(), viewport: innerWidth, height: innerHeight }));
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
  expect(geometry.rect.x).toBeGreaterThanOrEqual(-1);
  expect(geometry.rect.x + geometry.rect.width).toBeLessThanOrEqual(geometry.viewport + 1);
  expect(geometry.rect.height).toBeLessThanOrEqual(geometry.height + 1);
}

for (const width of [320, 390, 430]) {
  test(`${width}px编辑收款保留原金额和收款结构，保存后刷新`, async ({ page }) => {
    const writes = await fixture(page, { width });
    await page.goto(`${baseUrl}/finance?tab=income`);
    await page.getByLabel('查看账目：编辑测试商家', { exact: true }).first().click();
    await page.getByRole('button', { name: '编辑收款记录：编辑测试商家', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '编辑收款记录', exact: true })).toBeVisible();
    await assertDialogFits(page);
    if (screenshotDir && width === 390) await page.screenshot({ path: `${screenshotDir}/local-mock-edit-payment-390.png`, animations: 'disabled' });
    await dialog.locator('textarea').fill('手机核对已更新');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const updated = writes.find(r => r.path === '/api/v1/entities/payments/91');
    expect(updated).toMatchObject({ method: 'PUT', data: { amount_due: 398, amount_paid: 298, management_amount: 298, ads_recharge_amount: 0, currency: 'USD', notes: '手机核对已更新', product_name: 'Google Ads' } });
    expect(writes.filter(r => !/operation_logs|operation-logs/.test(r.path))).toHaveLength(1);
  });
}

for (const [tab, button, path, amount] of [
  ['customer_expense', '编辑客户支出', '/api/v1/entities/expenses/92', 80],
  ['company_expense', '编辑运营支出', '/api/v1/entities/company_expenses/93', 166],
] as const) {
  test(`${tab}编辑保持人民币币种与账期`, async ({ page }) => {
    const writes = await fixture(page, { width: 320 });
    await page.goto(`${baseUrl}/finance?tab=${tab}`);
    await page.locator('details').first().locator('summary').click();
    await page.getByRole('button', { name: button, exact: true }).click();
    await assertDialogFits(page);
    const dialog = page.getByRole('dialog');
    await dialog.locator('textarea').fill('手机更新成本备注');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect(writes.find(r => r.path === path)).toMatchObject({ method: 'PUT', data: { currency: 'CNY', amount, expense_month: '2026-08', notes: '手机更新成本备注' } });
  });
}

test('投流月结编辑沿用现有接口和草稿状态', async ({ page }) => {
  const writes = await fixture(page, { width: 320 });
  await page.goto(`${baseUrl}/finance?tab=ad_funds`);
  await page.locator('details').first().locator('summary').click();
  await page.getByRole('button', { name: '编辑投流月结', exact: true }).click();
  await assertDialogFits(page);
  const dialog = page.getByRole('dialog');
  await dialog.locator('textarea').fill('手机核对月结');
  await dialog.getByRole('button', { name: '保存月结', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes.find(r => r.path === '/api/v1/finance/ad-fund-settlements/94')).toMatchObject({ method: 'PUT', data: { actual_ad_spend: 50, recognized_spread_amount: 10, currency: 'USD', status: 'draft', notes: '手机核对月结' } });
});

test('已关账记录不允许手机绕过锁定', async ({ page }) => {
  const writes = await fixture(page, { closed: true });
  await page.goto(`${baseUrl}/finance?tab=income`);
  await page.getByLabel('查看账目：编辑测试商家', { exact: true }).first().click();
  await expect(page.getByRole('button', { name: '编辑收款记录：编辑测试商家', exact: true })).toBeDisabled();
  expect(writes).toEqual([]);
});

test('非财务角色不能打开财务编辑入口', async ({ page }) => {
  const writes = await fixture(page, { restricted: true });
  await page.goto(`${baseUrl}/finance?tab=income`);
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^编辑收款记录：/ })).toHaveCount(0);
  expect(writes).toEqual([]);
});

for (const stripeFee of [0, 7.25]) {
  test(`仅修改备注保留已入账手续费${stripeFee}与人民币币种`, async ({ page }) => {
    const writes = await fixture(page, { stripeFee, currency: 'CNY' });
    await page.goto(`${baseUrl}/finance?tab=income`);
    await page.getByLabel('查看账目：编辑测试商家', { exact: true }).first().click();
    await page.getByRole('button', { name: '编辑收款记录：编辑测试商家', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('本笔币种：人民币 CNY', { exact: true })).toBeVisible();
    await dialog.locator('textarea').fill('保留原始入账金额');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect(writes.find(r => r.path === '/api/v1/entities/payments/91')).toMatchObject({ data: { currency: 'CNY', amount_paid: 298, stripe_fee_amount: stripeFee, net_amount: 298 - stripeFee, notes: '保留原始入账金额' } });
  });
}

test('保存被拒绝保留已输入内容，不伪报成功', async ({ page }) => {
  await fixture(page, { rejectSave: true });
  await page.goto(`${baseUrl}/finance?tab=income`);
  await page.getByLabel('查看账目：编辑测试商家', { exact: true }).first().click();
  await page.getByRole('button', { name: '编辑收款记录：编辑测试商家', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('textarea').fill('仍需保留的修改');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.getByText(/保存失败.*记录已变更/)).toBeVisible();
  await expect(dialog.locator('textarea')).toHaveValue('仍需保留的修改');
});

test('手机记录退款仅提交原退款接口，金额校验与状态保持', async ({ page }) => {
  const writes = await fixture(page, { width: 320 });
  await page.goto(`${baseUrl}/finance?tab=income`);
  await page.getByLabel('查看账目：编辑测试商家', { exact: true }).first().click();
  await page.getByRole('button', { name: '记录退款', exact: true }).click();
  await assertDialogFits(page);
  const dialog = page.getByRole('dialog');
  await dialog.locator('input[type="number"]').first().fill('10');
  await dialog.getByRole('button', { name: '确认退款入账', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes.find(r => r.path === '/api/v1/finance/refunds')).toMatchObject({ method: 'POST', data: { payment_id: 91, refund_amount: 10, provider: 'manual', status: 'completed', stripe_fee_refunded_amount: 0 } });
});

test('月度关账明确确认之后才保存原月份配置', async ({ page }) => {
  const writes = await fixture(page, { admin: true });
  await page.goto(`${baseUrl}/finance?tab=monthly_detail`);
  await page.locator('.mfd-record').first().locator(':scope > summary').click();
  await page.getByRole('button', { name: '确认关账', exact: true }).click();
  expect(writes).toEqual([]);
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toContainText('2026-08');
  await dialog.getByRole('button', { name: '确认', exact: true }).click();
  await expect.poll(() => writes.some(r => r.path.endsWith('/app-config/export_config'))).toBe(true);
  expect(writes.find(r => r.path.endsWith('/app-config/export_config'))?.data.value.financeClosedMonths).toContain('2026-08');
});

test('财务角色可读月度状态但不能改管理员关账配置', async ({ page }) => {
  const writes = await fixture(page);
  await page.goto(`${baseUrl}/finance?tab=monthly_detail`);
  await page.locator('.mfd-record').first().locator(':scope > summary').click();
  await expect(page.getByRole('button', { name: /确认关账|重新打开月份/ })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('手机全部套餐超过15笔完整可达，搜索末项不写入', async ({ page }) => {
  const writes = await fixture(page, { subscriptions: true, width: 320 });
  await page.goto(`${baseUrl}/finance?tab=subscriptions`);
  await expect(page.getByRole('heading', { name: '续费风险列表', exact: true })).toBeVisible();
  await expect(page.locator('article')).toHaveCount(1);
  await page.getByRole('button', { name: '全部套餐', exact: true }).click();
  await expect(page.getByRole('heading', { name: '全部套餐', exact: true })).toBeVisible();
  await expect(page.locator('article')).toHaveCount(21);
  const tail = page.locator('article').last();
  await tail.scrollIntoViewIfNeeded();
  await expect(tail.getByText('模拟待核对套餐', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索续费套餐', exact: true }).fill('模拟正常套餐20');
  await expect(page.locator('article')).toHaveCount(1);
  await expect(page.locator('article').getByText('模拟正常套餐20', { exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  const widths = await page.evaluate(() => ({ viewport: innerWidth, html: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(widths.html).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
});

test('手机打开核对到账及取消均不产生收款或续费写入', async ({ page }) => {
  const writes = await fixture(page, { subscriptions: true });
  await page.goto(`${baseUrl}/finance?tab=subscriptions`);
  const row = page.locator('article').filter({ hasText: '模拟待核对套餐' });
  await row.locator(':scope > details > summary').click();
  await row.getByRole('button', { name: '核对到账', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '核对实际到账', exact: true })).toBeVisible();
  await assertDialogFits(page);
  expect(writes).toEqual([]);
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('手机切换手动续费只更新原套餐，不生成payment', async ({ page }) => {
  const writes = await fixture(page, { subscriptions: true });
  await page.goto(`${baseUrl}/finance?tab=subscriptions`);
  const row = page.locator('article').filter({ hasText: '模拟待核对套餐' });
  await row.locator(':scope > details > summary').click();
  await row.getByRole('button', { name: '切换手动收款', exact: true }).click();
  await expect.poll(() => writes.some(write => write.path === '/api/v1/entities/subscriptions/101')).toBe(true);
  const businessWrites = writes.filter(write => !/operation_logs|operation-logs/.test(write.path));
  expect(businessWrites).toHaveLength(1);
  expect(businessWrites[0]).toMatchObject({ method: 'PUT', path: '/api/v1/entities/subscriptions/101', data: { auto_renew: false, next_payment_date: '2026-08-01T00:00:00.000Z', status: 'expired', renewal_result: 'manual_collection_enabled' } });
  await expect(row.getByText('手动收款记录', { exact: true })).toBeVisible();
  expect(writes.filter(write => /entities\/payments/.test(write.path))).toEqual([]);
});

test('手机停止未来续费只更新原套餐并保留原收款', async ({ page }) => {
  const writes = await fixture(page, { subscriptions: true });
  await page.goto(`${baseUrl}/finance?tab=subscriptions`);
  const row = page.locator('article').filter({ hasText: '模拟待核对套餐' });
  await row.locator(':scope > details > summary').click();
  await row.getByRole('button', { name: '停止未来续费', exact: true }).click();
  await expect.poll(() => writes.some(write => write.path === '/api/v1/entities/subscriptions/101')).toBe(true);
  const businessWrites = writes.filter(write => !/operation_logs|operation-logs/.test(write.path));
  expect(businessWrites).toHaveLength(1);
  expect(businessWrites[0]).toMatchObject({ method: 'PUT', path: '/api/v1/entities/subscriptions/101', data: { auto_renew: false, next_payment_date: null, status: 'stopped', renewal_result: 'subscription_stopped' } });
  expect(writes.filter(write => /entities\/payments/.test(write.path) || write.method === 'DELETE')).toEqual([]);
  await page.goto(`${baseUrl}/finance?tab=income`);
  await expect(page.getByRole('region', { name: '流水列表' }).getByText('编辑测试商家', { exact: true }).first()).toBeVisible();
  await page.getByLabel('查看账目：编辑测试商家', { exact: true }).first().click();
  await expect(page.getByRole('button', { name: '编辑收款记录：编辑测试商家', exact: true })).toBeVisible();
  expect(writes.filter(write => /entities\/payments/.test(write.path) || write.method === 'DELETE')).toEqual([]);
});
