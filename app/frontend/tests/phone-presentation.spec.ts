import { expect, test, type Page } from '@playwright/test';
import { formatPhoneNumber, getPhoneCopyValue, parsePhoneNumber, parsePhoneNumberForDisplay, phoneMatchKey } from '../src/lib/phone-format';
import { getCustomerDialTarget, getCustomerDialValidation } from '../src/lib/phone-dial';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';

test('历史成对装饰只兼容展示与拨号，严格导入校验和匹配键保持原规则', () => {
  const raw = '  **(202) 555-0123 ext 009**  ';
  expect(parsePhoneNumberForDisplay(raw, 'US')).toMatchObject({ raw, e164: '+12025550123', extension: '009', country: 'US', isValid: true, hasPresentationDecoration: true });
  expect(formatPhoneNumber(raw, 'US')).toBe('+1 (202) 555-0123 分机 009');
  expect(getPhoneCopyValue(raw, 'US')).toBe(formatPhoneNumber(raw, 'US'));
  expect(getCustomerDialTarget(raw, 'US')).toEqual({ dialNumber: '12025550123', displayNumber: '+12025550123' });
  expect(getCustomerDialValidation(raw, 'US').extension).toBe('009');
  expect(parsePhoneNumber(raw, 'US').isValid).toBe(false);
  expect(phoneMatchKey(raw, 'US')).toBeNull();
});

test('明确国家的有效北美号码统一显示，国际号码和分机不被改造', () => {
  expect(formatPhoneNumber('4165550123', 'CA')).toBe('+1 (416) 555-0123');
  expect(formatPhoneNumber('2025550123', 'US')).toBe('+1 (202) 555-0123');
  const raw = '**+44 20 7946 0018 ext 004**';
  expect(formatPhoneNumber(raw, 'US')).toBe('+44 20 7946 0018 分机 004');
  expect(getPhoneCopyValue(raw, 'US')).toBe('+44 20 7946 0018 分机 004');
  expect(getCustomerDialTarget(raw, 'US')).toEqual({ dialNumber: '442079460018', displayNumber: '+442079460018' });
  expect(parsePhoneNumberForDisplay(raw, 'US').country).toBe('GB');
  expect(formatPhoneNumber('**+86 13800138000**')).toBe('+86 138 0013 8000');
});

test('未知国家、遮罩、多号码、字母和不成对装饰不生成复制或拨号目标', () => {
  for (const [raw, country] of [
    ['2025550123', null], ['**2025550123**', null], ['**2025550123**', 'unknown'],
    ['**202***0123**', 'US'], ['**+12025550123 / +12125550123**', 'US'],
    ['**call +12025550123**', 'US'], ['*+12025550123*', null], ['**+12025550123*', null],
    ['****+12025550123****', null], ['**+12025550123** ext 009', null],
    ['**+12025550123 ext 1 ext 2**', null], ['**123**', 'US'],
  ] as const) {
    expect(formatPhoneNumber(raw, country)).toBe(raw);
    expect(getPhoneCopyValue(raw, country)).toBeNull();
    expect(getCustomerDialTarget(raw, country)).toBeNull();
  }
  expect(parsePhoneNumber('2025550123').status).toBe('needs_country');
});

async function mockPool(page: Page) {
  const employee = { id: 10, name: '只读电话测试主管', role: 'sales_manager', status: 'active' };
  const writes: string[] = [];
  const merchant = { id: 21, business_name: '历史装饰号码商家', phone: ' **(202) 555-0123 ext 009** ', country: 'US', state: 'NY', city: 'New York', address: '1 Main St', pool_status: 'pending', data_source: 'mock', industry: '餐厅' };
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'mock-phone-readonly');
    localStorage.setItem('token', 'mock-phone-readonly');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    if (request.method() !== 'GET') {
      writes.push(request.url());
      return route.fulfill({ status: 400, contentType: 'application/json', body: '{"detail":"本用例禁止写入"}' });
    }
    const path = new URL(request.url()).pathname;
    const data = path.endsWith('/emp-auth/me') ? employee
      : path.endsWith('/sales-leads/assignees') ? []
      : path.endsWith('/merchant-pool/stats') ? { total: 1, pending: 1, converted: 0, isolated: 0, archived: 0 }
      : path === '/api/v1/merchant-pool' ? { items: [merchant], total: 1 }
      : { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return writes;
}

for (const width of [390, 1440]) {
  test(`商家池规范展示与原始电话可追溯，不产生保存或拨号（${width}px）`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const writes = await mockPool(page);
    await page.goto(`${baseUrl}/merchant-pool`);
    await expect(page.getByText('+1 (202) 555-0123 分机 009', { exact: true }).filter({ visible: true }).first()).toBeVisible();
    await page.getByRole('button', { name: '查看资料：历史装饰号码商家', exact: true }).click();
    await page.locator('summary').filter({ hasText: '更多采集资料' }).click();
    await expect(page.getByText('原始电话', { exact: true })).toBeVisible();
    await expect(page.getByText('**(202) 555-0123 ext 009**', { exact: true })).toBeVisible();
    expect(writes).toEqual([]);
    expect(page.url()).toContain('/merchant-pool');
    const widthState = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(widthState.document).toBeLessThanOrEqual(widthState.viewport);
  });
}
