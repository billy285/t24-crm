import { expect, test, type Page } from '@playwright/test';
import { formatPhoneNumber, parsePhoneNumber, phoneMatchKey, phoneSearchMatches } from '../src/lib/phone-format';
import { getCustomerDialTarget } from '../src/lib/phone-dial';
import * as XLSX from 'xlsx';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5193';
const employee = { id: 1, name: 'Phone fixture admin', role: 'admin', status: 'active' };
const customers = [
  { id: 1, business_name: 'International fixture', contact_name: 'Owner', phone: '+86 138 0013 8000', country: 'CN', status: 'closed', industry: 'restaurant', level: 'normal' },
  { id: 2, business_name: 'Legacy fixture', contact_name: 'Owner', phone: 'old phone', country: 'US', status: '已合作', industry: 'restaurant', level: 'normal' },
  { id: 3, business_name: 'Unknown country fixture', contact_name: 'Owner', phone: '2025550123', country: 'unknown', status: 'closed', industry: 'restaurant', level: 'normal' },
];

test('标准号码保留国际国家码、原文与分机，搜索不受展示标点影响', () => {
  expect(parsePhoneNumber('+1 (202) 555-0123 ext. 009')).toMatchObject({ raw: '+1 (202) 555-0123 ext. 009', e164: '+12025550123', extension: '009', status: 'valid' });
  expect(phoneMatchKey('020 7946 0018', 'UK')).toBe('+442079460018');
  expect(phoneMatchKey('+86 13800138000')).toBe('+8613800138000');
  expect(formatPhoneNumber('2025550123 ext 9', 'US')).toBe('+1 (202) 555 0123 分机 9');
  expect(phoneSearchMatches('+1 (202) 555-0123', '2025550123')).toBe(true);
  expect(phoneSearchMatches('+44 20 7946 0018', '2079460018')).toBe(true);
  expect(getCustomerDialTarget('+86 13800138000')).toEqual({ dialNumber: '8613800138000', displayNumber: '+8613800138000' });
  expect(getCustomerDialTarget('+12025550123 ext 99')).toEqual({ dialNumber: '12025550123', displayNumber: '+12025550123' });
});

test('未知国家、短号、多号码及不合法文本不会得到拨号目标', () => {
  for (const raw of ['2025550123', '12025550123', '+12025550123 / +12125550123', '+12025550123 ext 1 ext 2', 'call +12025550123']) {
    expect(getCustomerDialTarget(raw, 'unknown')).toBeNull();
  }
  expect(getCustomerDialTarget('2025550123', 'US')).not.toBeNull();
  expect(parsePhoneNumber('2025550123').status).toBe('needs_country');
  expect(parsePhoneNumber('2025550123 / 2125550123', 'US').status).toBe('ambiguous');
  expect(formatPhoneNumber('legacy invalid')).toBe('legacy invalid');
});

async function mockPhoneApi(page: Page, writes: { path: string; data: any }[]) {
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'phone-fixture-token');
    localStorage.setItem('token', 'phone-fixture-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let data: any = { items: [], total: 0 };
    if (!['GET', 'HEAD'].includes(request.method())) {
      const payload = request.postDataJSON();
      writes.push({ path, data: payload });
      data = payload.customer || payload;
    } else if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path === '/api/v1/app-config') data = { items: [] };
    else if (path.endsWith('/projects')) data = { items: [] };
    else if (path.includes('/entities/customers')) {
      const query = JSON.parse(url.searchParams.get('query') || '{}');
      const id = query.id;
      data = { items: id ? customers.filter(customer => customer.id === Number(id)) : customers, total: customers.length };
    } else if (path.includes('/entities/employees')) data = { items: [employee], total: 1 };
    else if (path.includes('/product-plans')) data = { business_lines: [], products: [], plans: [] };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
}

for (const width of [390, 1440]) {
  test(`客户号码展示搜索与非法拨号保护（${width}px）`, async ({ page }) => {
    const writes: { path: string; data: any }[] = [];
    await page.setViewportSize({ width, height: 900 });
    await mockPhoneApi(page, writes);
    await page.goto(`${baseUrl}/customers`);
    await expect(page.getByText('International fixture', { exact: true }).filter({ visible: true }).first()).toBeVisible();
    const search = page.getByPlaceholder('搜索编号、名称、联系人、电话...');
    await search.fill('13800138000');
    await expect(page.getByText('International fixture', { exact: true }).filter({ visible: true }).first()).toBeVisible();
    await expect(page.getByText('Legacy fixture', { exact: true })).toHaveCount(0);
    await search.fill('Unknown country fixture');
    await page.getByText('Unknown country fixture', { exact: true }).filter({ visible: true }).first().click();
    await page.getByRole('button', { name: '网页拨号', exact: true }).click();
    await expect(page.getByText('本地号码需要明确国家或地区；也可填写以 + 开头的国际号码', { exact: true }).first()).toBeVisible();
    expect(page.url()).toContain('/customers');
    expect(writes).toHaveLength(0);
  });
}

test('客户历史状态仅做展示兼容，编辑未改号码仍保留原值', async ({ page }) => {
  const writes: { path: string; data: any }[] = [];
  await mockPhoneApi(page, writes);
  await page.goto(`${baseUrl}/customers`);
  await page.getByRole('button', { name: '更多客户操作：Legacy fixture' }).click();
  await page.getByRole('menuitem', { name: '编辑客户', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '编辑客户' });
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect.poll(() => writes.filter(write => write.path.endsWith('/2/with-projects')).length).toBe(1);
  const saved = writes.find(write => write.path.endsWith('/2/with-projects'))!.data.customer;
  expect(saved.phone).toBe('old phone');
  expect(saved.status).toBe('已合作');
  expect(writes.some(write => /payments|expenses|deals/.test(write.path))).toBe(false);
});

test('客户导入按标准号码识别重复，未知国家与多号码列入错误预览', async ({ page }) => {
  const writes: { path: string; data: any }[] = [];
  await mockPhoneApi(page, writes);
  await page.goto(`${baseUrl}/customers`);
  await page.locator('summary').filter({ hasText: '更多工具' }).click();
  await page.getByRole('button', { name: '导入', exact: true }).click();
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([
    ['商家名称', '联系人', '电话', '国家'],
    ['Duplicate international', 'Owner', '+86 (138) 0013-8000', 'CN'],
    ['Unknown national', 'Owner', '2025550123', ''],
    ['Multiple numbers', 'Owner', '2025550123 / 2125550123', 'US'],
    ['Valid raw retained', 'Owner', ' 202-555-0144 ext 009 ', 'US'],
  ]), 'fixture');
  await page.locator('input[type="file"]').setInputFiles({ name: 'phone-fixture.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: XLSX.write(workbook, { type: 'buffer', bookType: 'xlsx' }) });
  const dialog = page.getByRole('dialog', { name: '数据预览与校验' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('row').filter({ hasText: 'Duplicate international' })).toContainText('已存在');
  await expect(dialog.getByRole('row').filter({ hasText: 'Unknown national' })).toContainText('需要明确国家');
  await expect(dialog.getByRole('row').filter({ hasText: 'Multiple numbers' })).toContainText('请只填写一个电话号码');
  await expect(dialog.getByRole('row').filter({ hasText: 'Valid raw retained' })).toContainText('+1 (202) 555 0144 分机 009');
  expect(writes).toHaveLength(0);
  await dialog.getByRole('button', { name: '确认导入 1 条数据', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '导入完成', exact: true })).toBeVisible();
  const imports = writes.filter(write => write.path === '/api/v1/entities/customers');
  expect(imports).toHaveLength(1);
  expect(imports[0].data.phone).toBe(' 202-555-0144 ext 009 ');
  expect(writes.some(write => /payments|expenses|deals/.test(write.path))).toBe(false);
});

test('网页拨号传入完整国际主号而不拼接分机', async ({ page }) => {
  const writes: { path: string; data: any }[] = [];
  await mockPhoneApi(page, writes);
  await page.route('https://app.ringcentral.com/r/call**', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<p>Local intercepted dial fixture</p>' }));
  await page.goto(`${baseUrl}/customers`);
  await page.getByText('International fixture', { exact: true }).filter({ visible: true }).first().click();
  await page.getByRole('button', { name: '网页拨号', exact: true }).click();
  await expect(page).toHaveURL('https://app.ringcentral.com/r/call?number=8613800138000');
  expect(writes).toHaveLength(0);
});
