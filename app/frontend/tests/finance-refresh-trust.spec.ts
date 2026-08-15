import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const owner = { id: 1, name: '财务可信度测试老板', role: 'super_admin', status: 'active' };

const sleep = (milliseconds: number) => new Promise(resolve => setTimeout(resolve, milliseconds));

async function fulfillJson(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
}

async function installFinanceApi(page: Page) {
  let paymentRequests = 0;
  let commissionRequests = 0;
  let failCommissionRefresh = false;

  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'finance-refresh-token');
    window.localStorage.setItem('token', 'finance-refresh-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: owner });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, owner);
    if (path === '/api/v1/app-config') return fulfillJson(route, { items: {} });
    if (path.startsWith('/api/v1/app-config/')) return fulfillJson(route, { value: {} });
    if (path.includes('/reports/profit-monthly.json')) return fulfillJson(route, []);
    if (path.includes('/entities/payments')) {
      paymentRequests += 1;
      const currentRequest = paymentRequests;
      if (currentRequest === 1) await sleep(800);
      const name = currentRequest === 1 ? '旧慢财务快照' : '新快财务快照';
      return fulfillJson(route, {
        items: [{
          id: currentRequest,
          customer_id: 91,
          customer_name: name,
          amount_due: 198,
          amount_paid: 198,
          management_amount: 198,
          ads_recharge_amount: 0,
          outstanding_amount: 0,
          currency: 'USD',
          income_type: 'management_fee',
          payment_mode: 'manual_collection',
          payment_method: 'zelle',
          payment_date: '2026-08-01',
        }],
        total: 1,
      });
    }
    if (path === '/api/v1/commissions/dashboard') {
      commissionRequests += 1;
      if (failCommissionRefresh) {
        return fulfillJson(route, { detail: '佣金摘要暂时不可用' }, 503);
      }
      return fulfillJson(route, { entries: [] });
    }
    if (path === '/api/v1/product-plans') return fulfillJson(route, { business_lines: [], products: [], plans: [] });
    if (path.startsWith('/api/v1/deductions-monthly')) return fulfillJson(route, [{ year_month: '2026-08', rate: 0.15 }]);
    if (path.startsWith('/api/v1/finance/')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/customers')) return fulfillJson(route, { items: [{ id: 91, business_name: '财务客户' }] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, {});
  });

  return {
    get paymentRequests() { return paymentRequests; },
    get commissionRequests() { return commissionRequests; },
    failCommissionRefresh() { failCommissionRefresh = true; },
  };
}

test('财务只提交最新一轮快照，刷新失败时明确标注旧数据且保留已核对结果', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const api = await installFinanceApi(page);
  await page.goto(`${baseUrl}/finance?tab=income`);

  await expect.poll(() => api.paymentRequests).toBe(1);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('t24:business-data-refresh')));
  await expect.poll(() => api.paymentRequests).toBeGreaterThanOrEqual(2);
  await expect(page.getByText('新快财务快照')).toBeVisible();

  await page.waitForTimeout(900);
  await expect(page.getByText('旧慢财务快照')).toHaveCount(0);
  await expect(page.getByText('新快财务快照')).toBeVisible();

  await expect.poll(() => api.commissionRequests).toBeGreaterThanOrEqual(2);
  api.failCommissionRefresh();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('t24:business-data-refresh')));

  const staleAlert = page.getByRole('alert');
  await expect(staleAlert).toContainText('本次刷新未完成，当前显示上一次核对成功的财务快照。', { timeout: 10_000 });
  await expect(staleAlert).toContainText('佣金摘要暂时不可用');
  await expect(page.getByText('新快财务快照')).toBeVisible();
  await expect(page.getByText('旧慢财务快照')).toHaveCount(0);
});
