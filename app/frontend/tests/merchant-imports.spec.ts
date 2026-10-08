import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5190';
const employee = { id: 10, name: '导入测试主管', role: 'sales_manager', status: 'active' };
const csv = '商家名称,商家电话,商家位置,地区,来源\nSample Cafe,212-555-0123 ext 9,1 Main St,"New York, NY, US",Maps\nBad Phone,123,2 Main St,,Maps\n';
const receipt = {
  id: 'test-import-batch-001', filename: 'merchants.csv', status: 'preview', row_count: 2, created_at: '2026-10-09T10:00:00Z',
  summary: { pending: 1, isolated: 1, errors: 0, importable: 2 },
  rows: [
    { row: 2, business_name: 'Sample Cafe', phone: '212-555-0123 ext 9', phone_country: 'US', normalized_phone: '+12125550123', status: 'pending', reason: '待人工核对；尚未分配销售', warnings: [], raw: { 商家名称: 'Sample Cafe', 商家电话: '212-555-0123 ext 9', 商家位置: '1 Main St', 地区: 'New York, NY, US', 来源: 'Maps' } },
    { row: 3, business_name: 'Bad Phone', phone: '123', status: 'no_phone', reason: '电话不完整，请补齐后再分配', warnings: ['地区未明确国家，未默认填写美国'], raw: { 商家名称: 'Bad Phone', 商家电话: '123', 商家位置: '2 Main St', 地区: '', 来源: 'Maps' } },
  ],
};

async function mockImports(page: Page, scenario: 'normal' | 'duplicate' | 'lost-response' | 'revert-conflict' = 'normal') {
  const writes: string[] = [];
  let status = scenario === 'duplicate' ? 'committed' : 'preview';
  await page.addInitScript(emp => {
    localStorage.setItem('token', 'mock-import-token');
    localStorage.setItem('emp_auth_token', 'mock-import-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() !== 'GET') writes.push(path);
    let data: unknown = {};
    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path === '/api/v1/merchant-imports/preview') data = { ...receipt, status, duplicate_upload: scenario === 'duplicate' };
    else if (path.endsWith('/merchant-imports/test-import-batch-001/confirm')) {
      status = 'committed';
      if (scenario === 'lost-response') return route.abort('failed');
      data = { ...receipt, status };
    } else if (path.endsWith('/merchant-imports/test-import-batch-001/revert')) {
      if (scenario === 'revert-conflict') return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { message: '批次已有记录被修改或转为线索，整批未撤销', rows: [2] } }) });
      status = 'reverted'; data = { ...receipt, status };
    } else if (path.endsWith('/errors.csv')) return route.fulfill({ status: 200, contentType: 'text/csv', headers: { 'Content-Disposition': 'attachment; filename="issues.csv"' }, body: '\uFEFF原始行号,商家名称,原因\r\n3,Bad Phone,电话不完整\r\n' });
    else if (path === '/api/v1/merchant-imports/test-import-batch-001') data = { ...receipt, status };
    else if (path === '/api/v1/merchant-imports') data = { items: [] };
    else if (path === '/api/v1/merchant-pool/stats') data = { total: status === 'committed' ? 2 : 0, pending: status === 'committed' ? 1 : 0, isolated: status === 'committed' ? 1 : 0, converted: 0, duplicates: 0, archived: 0 };
    else if (path === '/api/v1/merchant-pool' || path.includes('/entities/') || path.includes('/app-config')) data = { items: [], total: 0 };
    else if (path.endsWith('/assignees')) data = [{ id: 11, name: '测试销售' }];
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.setViewportSize({ width: 1024, height: 820 });
  await page.goto(`${baseUrl}/merchant-pool`);
  await page.getByRole('button', { name: '导入商家数据' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '按固定模板导入商家' })).toBeVisible();
  return { writes, dialog };
}

async function upload(page: Page) {
  await page.getByLabel('商家导入文件').setInputFiles({ name: 'merchants.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
}

test('预检先展示原行号、电话隔离与结果，确认前不调用商家或财务写接口', async ({ page }) => {
  const { writes, dialog } = await mockImports(page);
  await expect(dialog.getByText('商家名称、商家电话、商家位置、地区、来源')).toBeVisible();
  await upload(page);
  const result = dialog.getByRole('region', { name: '商家导入批次结果' });
  await expect(result.getByText('Sample Cafe', { exact: true })).toBeVisible();
  await expect(result.getByText('Bad Phone', { exact: true })).toBeVisible();
  await expect(result.getByText(/分机 9/)).toBeVisible();
  await expect(result.getByText('电话待补齐', { exact: true })).toBeVisible();
  expect(writes).toEqual(['/api/v1/merchant-imports/preview']);
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '下载问题行' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('商家导入问题行');
  await dialog.getByRole('button', { name: '确认入池 2 条' }).click();
  await expect(result.getByText('已入池', { exact: true })).toBeVisible();
  await expect(result.getByText(/仍需人工核对并选择销售负责人/)).toBeVisible();
  expect(writes).toEqual(['/api/v1/merchant-imports/preview', '/api/v1/merchant-imports/test-import-batch-001/confirm']);
  await expect(dialog.getByRole('button', { name: '确认入池 2 条' })).toHaveCount(0);
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
});

test('重复上传打开原已入池批次且不再次显示提交按钮', async ({ page }) => {
  const { writes, dialog } = await mockImports(page, 'duplicate');
  await upload(page);
  await expect(dialog.getByRole('status').filter({ hasText: '这份文件已有导入批次' })).toBeVisible();
  await expect(dialog.getByText('批次 test-import-batch-001')).toBeVisible();
  await expect(dialog.getByRole('button', { name: /确认入池/ })).toHaveCount(0);
  expect(writes).toEqual(['/api/v1/merchant-imports/preview']);
});

test('确认响应丢失时读取服务器批次结果，不重复提交商家', async ({ page }) => {
  const { writes, dialog } = await mockImports(page, 'lost-response');
  await upload(page);
  await dialog.getByRole('button', { name: '确认入池 2 条' }).click();
  await expect(dialog.getByRole('region', { name: '商家导入批次结果' }).getByText('已入池', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('alert')).toHaveCount(0);
  expect(writes.filter(path => path.endsWith('/confirm'))).toHaveLength(1);
  expect(writes.every(path => path.startsWith('/api/v1/merchant-imports/'))).toBeTruthy();
});

test('撤销可取消且有后续修改时保持原入池结果和明确错误', async ({ page }) => {
  const { writes, dialog } = await mockImports(page, 'revert-conflict');
  await upload(page);
  await dialog.getByRole('button', { name: '确认入池 2 条' }).click();
  await expect(dialog.getByRole('button', { name: '撤销本批导入' })).toBeVisible();
  page.once('dialog', browserDialog => browserDialog.dismiss());
  await dialog.getByRole('button', { name: '撤销本批导入' }).click();
  expect(writes.filter(path => path.endsWith('/revert'))).toHaveLength(0);
  page.once('dialog', browserDialog => browserDialog.accept());
  await dialog.getByRole('button', { name: '撤销本批导入' }).click();
  await expect(dialog.getByRole('alert')).toContainText('整批未撤销');
  await expect(dialog.getByRole('region', { name: '商家导入批次结果' }).getByText('已入池', { exact: true })).toBeVisible();
  expect(writes.filter(path => path.endsWith('/revert'))).toHaveLength(1);
});
