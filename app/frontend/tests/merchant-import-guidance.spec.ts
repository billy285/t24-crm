import { expect, test, type Page } from '@playwright/test';
import { MERCHANT_IMPORT_HEADERS, merchantImportRepairAdvice } from '../src/lib/merchant-import';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshotDir = process.env.T24_PHONE_IMPORT_SCREENSHOT_DIR;

test('隔离修复建议区分完整号码、国家、遮罩、装饰及重复，不替用户猜号码', () => {
  const row = { status: 'no_phone', reason: '电话号码含有无法识别的字符', phone_country: 'US' };
  expect(merchantImportRepairAdvice({ ...row, phone: '**2025550123 ext 009**' })).toContain('删除原文件电话两端的 **');
  expect(merchantImportRepairAdvice({ ...row, phone: '**202***0123**' })).toContain('缺失数字不能推测');
  expect(merchantImportRepairAdvice({ ...row, phone: '2025550123', phone_country: null })).toContain('写明国家');
  expect(merchantImportRepairAdvice({ ...row, phone: '**2025550123**', phone_country: null })).toContain('写明国家');
  expect(merchantImportRepairAdvice({ ...row, phone: '**2025550123**', phone_country: null })).not.toContain('缺失数字');
  expect(merchantImportRepairAdvice({ ...row, phone: '2025550123 / 2125550123' })).toContain('一行只保留一个');
  expect(merchantImportRepairAdvice({ status: 'duplicate', reason: '同一批次重复', duplicate_row: 2 })).toContain('原第 2 行');
  expect(merchantImportRepairAdvice({ status: 'existing_customer', reason: '已关联客户' })).toContain('继续客户跟进');
  expect(merchantImportRepairAdvice({ status: 'pending', reason: '可分配' })).toBeNull();
});

test('格式错误给出原文件修复方法，五列模板不混入诊断字段', () => {
  expect(MERCHANT_IMPORT_HEADERS).toEqual(['商家名称', '商家电话', '商家位置', '地区', '来源']);
  expect(merchantImportRepairAdvice({ status: 'error', reason: '必须正好填写5列' })).toContain('同一个单元格');
  expect(merchantImportRepairAdvice({ status: 'error', reason: '商家名称为空或超过200字' })).toContain('200 字');
  expect(merchantImportRepairAdvice({ status: 'error', reason: '来源不能超过50字' })).toContain('50 字');
});

const originalCsv = '商家名称,商家电话,商家位置,地区,来源\r\nValid Sample,+1 (212) 555-0123 ext 009,1 Main St,"New York, NY, US",Maps\r\nDecorated Sample,**(202) 555-0123**,2 Main St,"New York, NY, US",Maps\r\nUnknown Sample,2025550123,3 Main St,,Maps\r\nMasked Sample,**202***0123**,4 Main St,"New York, NY, US",Maps\r\nDuplicate Sample,+12125550123,1 Main St,"New York, NY, US",Maps\r\nFive Column Error,,,,Maps,extra\r\n';

async function mockPreview(page: Page) {
  const employee = { id: 10, name: '导入指导测试主管', role: 'sales_manager', status: 'active' };
  const base = { warnings: [] as string[], raw: { 商家位置: '1 Main St', 地区: 'New York, NY, US', 来源: 'Maps' } };
  const receipt = {
    id: 'guidance-only-preview', filename: 'guidance.csv', status: 'preview', row_count: 6, created_at: '2026-10-10T10:00:00Z',
    summary: { pending: 1, isolated: 4, errors: 1, importable: 5 },
    rows: [
      { ...base, row: 2, business_name: 'Valid Sample', phone: '+1 (212) 555-0123 ext 009', phone_country: 'US', phone_status: 'valid', normalized_phone: '+12125550123', status: 'pending', reason: '待人工核对；尚未分配销售' },
      { ...base, row: 3, business_name: 'Decorated Sample', phone: '**(202) 555-0123**', phone_country: 'US', phone_status: 'invalid', status: 'no_phone', reason: '电话号码含有无法识别的字符' },
      { ...base, row: 4, business_name: 'Unknown Sample', phone: '2025550123', phone_country: null, phone_status: 'needs_country', status: 'no_phone', reason: '本地号码需要明确国家或地区；也可填写以 + 开头的国际号码', warnings: ['地区未明确国家，未默认填写美国'], raw: { 商家位置: '3 Main St', 地区: '', 来源: 'Maps' } },
      { ...base, row: 5, business_name: 'Masked Sample', phone: '**202***0123**', phone_country: 'US', phone_status: 'invalid', status: 'no_phone', reason: '电话号码含有无法识别的字符' },
      { ...base, row: 6, business_name: 'Duplicate Sample', phone: '+12125550123', phone_country: 'US', phone_status: 'valid', normalized_phone: '+12125550123', status: 'duplicate', reason: '同批重复', duplicate_row: 2 },
      { ...base, row: 7, business_name: 'Five Column Error', phone: '', status: 'error', reason: '必须正好填写5列' },
    ],
  };
  const writes: { path: string; body: string | null }[] = [];
  await page.addInitScript(emp => {
    localStorage.setItem('emp_auth_token', 'mock-guidance-token');
    localStorage.setItem('token', 'mock-guidance-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postData() });
      if (path !== '/api/v1/merchant-imports/preview') return route.fulfill({ status: 400, body: '{"detail":"测试禁止提交入池及业务写入"}', contentType: 'application/json' });
    }
    const data = path.endsWith('/emp-auth/me') ? employee
      : path === '/api/v1/merchant-imports/preview' ? receipt
      : path.endsWith('/sales-leads/assignees') ? []
      : path.endsWith('/merchant-pool/stats') ? { total: 0, pending: 0, isolated: 0, converted: 0, archived: 0 }
      : { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('button', { name: '导入商家数据' }).click();
  return { writes, dialog: page.getByRole('dialog', { name: '按固定模板导入商家' }) };
}

for (const width of [1024, 1440]) {
  test(`导入标准可展开、原文件不重写、逐行建议保持服务器隔离结果（${width}px）`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes, dialog } = await mockPreview(page);
    await expect(dialog.getByRole('table', { name: '商家导入填写示例' })).not.toBeVisible();
    await dialog.locator('summary').filter({ hasText: '填写标准与示例' }).click();
    await expect(dialog.getByRole('table', { name: '商家导入填写示例' })).toBeVisible();
    await expect(dialog.getByText(/Toronto, ON, CA/)).toBeVisible();
    await expect(dialog.getByText(/不默认美国/)).toBeVisible();
    const downloadPromise = page.waitForEvent('download');
    await dialog.getByRole('button', { name: '下载固定模板' }).click();
    const stream = await (await downloadPromise).createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks).toString('utf8')).toBe(`\uFEFF${MERCHANT_IMPORT_HEADERS.join(',')}\r\n`);
    await dialog.locator('summary').filter({ hasText: '填写标准与示例' }).click();
    await page.getByLabel('商家导入文件').setInputFiles({ name: 'guidance.csv', mimeType: 'text/csv', buffer: Buffer.from(originalCsv) });
    const result = dialog.getByRole('region', { name: '商家导入批次结果' });
    const decorated = result.getByRole('row').filter({ hasText: 'Decorated Sample' });
    await expect(decorated).toContainText('**(202) 555-0123**');
    await expect(decorated).toContainText('电话待补齐');
    await expect(decorated).toContainText('删除原文件电话两端的 **');
    await expect(decorated).not.toContainText('+1 (202)');
    await expect(result.getByRole('row').filter({ hasText: 'Valid Sample' })).toContainText('+1 (212) 555 0123 分机 009');
    await expect(result.getByRole('row').filter({ hasText: 'Masked Sample' })).toContainText('缺失数字不能推测');
    await dialog.getByRole('button', { name: '格式错误', exact: true }).click();
    await expect(result.getByRole('row').filter({ hasText: 'Five Column Error' })).toContainText('同一个单元格');
    await expect(result.getByText('Decorated Sample', { exact: true })).toHaveCount(0);
    await dialog.getByRole('button', { name: '隔离行', exact: true }).click();
    await expect(result.getByRole('row').filter({ hasText: 'Unknown Sample' })).toContainText('在“地区”列写明国家');
    await expect(result.getByRole('row').filter({ hasText: 'Duplicate Sample' })).toContainText('原第 2 行');
    await expect(result.getByText(/重新上传时只保留模板五列/)).toBeVisible();
    expect(writes.map(write => write.path)).toEqual(['/api/v1/merchant-imports/preview']);
    expect(writes[0].body).toContain(originalCsv);
    const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(widths.document).toBeLessThanOrEqual(widths.viewport);
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/import-guidance-${width}.png`, fullPage: true });
  });
}
