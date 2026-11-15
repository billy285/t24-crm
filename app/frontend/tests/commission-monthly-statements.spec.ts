import { test, expect, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5187';
const owner = { id: 1, name: '结算验收', role: 'super_admin', status: 'active' };
const partners = [
  { id: 7, partner_code: 'A007', name: '西区合作渠道', partner_type: 'partner', status: 'active', joined_at: '2026-01-01' },
  { id: 9, partner_code: 'A009', name: '美业合作渠道', partner_type: 'agency', status: 'active', joined_at: '2026-01-01' },
];
const ledgerEntry = {
  entry_id: 124, customer_id: 8, customer_name: '海岸美业测试店', payment_id: 960, refund_id: null, entry_type: 'renewal',
  source_month: '2026-09', eligible_service_amount: 198, commission_amount: 39.6, contract_rate: 0.2, due_date: '2026-11-15',
};
async function prepare(page: Page, width: number, simulate: 'normal' | 'conflict' | 'lost-reply' | 'review' | 'never-scanned' = 'normal') {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'local-commission-test');
    localStorage.setItem('token', 'local-commission-test');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, owner);
  let current = { id: 144, month: '2026-10', partner_id: 7, partner_name: partners[0].name, currency: 'USD',
    issue_date: '2026-11-01', due_date: '2026-11-15', status: 'ready', revision: 'test-10-a',
    entry_count: 1, total_amount: 39.6, deferred_count: 1, deferred_amount: 99, issues: [] as string[],
    payout_reference: '', paid_at: '',
    entries: [ledgerEntry],
    deferred_entries: [{ ...ledgerEntry, entry_id: 125, entry_type: 'first_order', source_month: '2026-10', commission_amount: 99, contract_rate: 0.5, due_date: '2026-12-15' }],
  };
  if (simulate === 'review') current = { ...current, status: 'needs_review', issues: ['合同暂停，需核对渠道协议。'] };
  const settlements: { payout_reference: string; expected_total: number; expected_entry_count: number; revision: string }[] = [];
  const requests: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    let data: unknown = { items: [] };
    if (path === '/api/config') data = { API_BASE_URL: base };
    if (path.endsWith('/emp-auth/me')) data = owner;
    if (path.endsWith('/commissions/dashboard')) data = { summary: { partner_count: partners.length, active_partner_count: 2, pending_count: 0, currencies: {}, quality: { issue_count: 0 } }, entries: [], attributions: [], agreements: [], quality_issues: [], partners };
    if (path.endsWith('/commissions/options')) data = { employees: [], customers: [], products: [], engagements: [], business_lines: [] };
    if (path.endsWith('/commissions/statements')) {
      requests.push(url.search);
      const month = url.searchParams.get('month');
      const exists = month === '2026-10' && url.searchParams.get('partner_id') !== '9';
      data = { month, items: exists ? [current] : [], issues: [], schedule: { last_completed_date: simulate === 'never-scanned' ? null : '2026-11-15' } };
    }
    if (path.endsWith('/statements/144')) data = current;
    if (path.endsWith('/statements/144/settle')) {
      const payload = route.request().postDataJSON();
      settlements.push(payload);
      if (simulate === 'conflict' && settlements.length === 1) {
        current = { ...current, revision: 'test-10-b', total_amount: 42, entries: [{ ...ledgerEntry, commission_amount: 42 }] };
        return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({detail:'金额已更新'}) });
      }
      if (payload.expected_total !== current.total_amount || payload.revision !== current.revision) throw new Error('未重新核对当前单据');
      current = { ...current, status: 'paid', payout_reference: payload.payout_reference, paid_at: '2026-11-15T01:10:00Z' };
      if (simulate === 'lost-reply') return route.abort('failed');
      data = current;
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(base + '/commissions?view=statements&month=2026-10');
  await expect(page.getByRole('region', { name: '渠道月结单' })).toBeVisible();
  return { settlements, requests };
}

for (const width of [1093, 390]) test('月结单核对与付款 ' + width, async ({ page }) => {
  const { settlements, requests } = await prepare(page, width);
  const sheet = page.getByRole('button', { name: /查看 西区合作渠道 USD 月结单/ });
  await expect(sheet).toHaveText(/待登记付款/);
  await expect(page.getByText('最近自动核算 2026-11-15')).toBeVisible();
  await page.getByLabel('结算渠道').selectOption('9');
  await expect(page.getByText('该账期及渠道暂无月结单。')).toBeVisible();
  await page.getByLabel('结算渠道').selectOption('7');
  await page.getByLabel('结算月份').fill('2026-08');
  await expect(page.getByText('该账期及渠道暂无月结单。')).toBeVisible();
  await page.getByLabel('结算月份').fill('2026-10');
  await expect(sheet).toBeVisible();
  expect(requests.some(q => q.includes('month=2026-08') && q.includes('partner_id=7'))).toBe(true);
  if (process.env.T24_STATEMENT_SHOTS) await page.screenshot({ path: process.env.T24_STATEMENT_SHOTS + '/statement-list-' + width + '.png' });
  await sheet.click();
  const detail = page.getByRole('dialog', { name: '月结单详情' });
  await expect(detail).toContainText('来源月份 2026-09');
  await detail.getByText('顺延明细 · 1 笔').click();
  await expect(detail.getByText(/来源月份 2026-10/)).toBeVisible();
  const confirm = detail.getByRole('button', { name: '登记付款并结清整单' });
  await expect(confirm).toBeDisabled();
  await detail.getByLabel('实际付款流水号或凭证编号').fill('  TEST-PAID-100  ');
  await confirm.dblclick();
  await expect(detail.getByText('TEST-PAID-100', { exact: true })).toBeVisible();
  await expect(detail.getByText('已结清', { exact: true })).toBeVisible();
  await expect(confirm).toHaveCount(0);
  expect(settlements).toEqual([{ payout_reference: 'TEST-PAID-100', expected_total: 39.6, expected_entry_count: 1, revision: 'test-10-a' }]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.T24_STATEMENT_SHOTS) await page.screenshot({ path: process.env.T24_STATEMENT_SHOTS + '/statement-paid-' + width + '.png' });
  await detail.getByRole('button', { name: '关闭', exact: true }).first().click();
  await expect(sheet).toContainText('已结清');
  await page.reload();
  await sheet.click();
  await expect(page.getByRole('dialog').getByText('TEST-PAID-100', { exact: true })).toBeVisible();
});

test('月结单变更重新核对后才可确认', async ({ page }) => {
  const { settlements } = await prepare(page, 1093, 'conflict');
  await page.getByRole('button', { name: /查看 西区合作渠道 USD 月结单/ }).click();
  const detail = page.getByRole('dialog');
  await detail.getByLabel('实际付款流水号或凭证编号').fill('TEST-ADJUSTED');
  const confirm = detail.getByRole('button', { name: '登记付款并结清整单' });
  await confirm.click();
  await expect(detail).toContainText('金额已更新');
  await expect(detail.locator('dd').first()).toContainText('42.00');
  await expect(confirm).toBeEnabled();
  expect(settlements).toHaveLength(1);
  await confirm.click();
  await expect(detail.getByText('已结清', { exact: true })).toBeVisible();
  expect(settlements[1]).toMatchObject({ expected_total: 42, revision: 'test-10-b' });
});

test('已入账但回执中断可读回真实状态', async ({ page }) => {
  const { settlements } = await prepare(page, 390, 'lost-reply');
  await page.getByRole('button', { name: /查看 西区合作渠道 USD 月结单/ }).click();
  const detail = page.getByRole('dialog');
  await detail.getByLabel('实际付款流水号或凭证编号').fill('TEST-CONNECTION');
  await detail.getByRole('button', { name: '登记付款并结清整单' }).click();
  await expect(detail.getByText('已结清', { exact: true })).toBeVisible();
  await expect(detail.getByText('TEST-CONNECTION', { exact: true })).toBeVisible();
  expect(settlements).toHaveLength(1);
});

test('需核对的月单列出原因并停止付款', async ({ page }) => {
  const { settlements } = await prepare(page, 390, 'review');
  const sheet = page.getByRole('button', { name: /查看 西区合作渠道 USD 月结单/ });
  await expect(sheet).toContainText('合同暂停，需核对渠道协议。');
  await sheet.click();
  const detail = page.getByRole('dialog');
  await expect(detail.getByText('合同暂停，需核对渠道协议。')).toBeVisible();
  await expect(detail.getByRole('button', { name: '登记付款并结清整单' })).toHaveCount(0);
  expect(settlements).toHaveLength(0);
});

test('没有自动核算记录时展示真实状态', async ({ page }) => {
  await prepare(page, 390, 'never-scanned');
  await page.getByLabel('结算渠道').selectOption('9');
  await expect(page.getByText('该账期及渠道暂无月结单。')).toBeVisible();
  await expect(page.getByText('尚无自动核算完成记录')).toBeVisible();
});
