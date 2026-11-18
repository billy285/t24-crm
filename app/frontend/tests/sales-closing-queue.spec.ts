import { expect, test, type Page } from '@playwright/test';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const api = '/api/v1/sales-leads/closing-queue';
async function fixture(page: Page, role: string, stage = 'pending') {
  const employee = { id: 11, name: '管理甲', role, status: 'active' };
  const item = { lead_id: 42, business_name: '测试美甲店', phone: '+12025550192', country: 'US', stage,
    source_sales_id: 5, source_sales_name: '销售乙', closer_id: stage === 'working' ? 12 : null as number | null,
    closer_name: stage === 'working' ? '主管丙' : '', interest_note: '客户想看预约演示', note: '',
    next_follow_up_at: '2030-11-17T02:00:00Z', can_contact: true, revision: stage === 'working' ? 3 : 0 };
  const reads: URL[] = [];
  const writes: Record<string, unknown>[] = [];
  await page.addInitScript(value => {
    localStorage.setItem('emp_auth_token', 'local-closing-test');
    localStorage.setItem('token', 'local-closing-test');
    localStorage.setItem('emp_auth_data', JSON.stringify(value));
  }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === api && request.method() === 'GET') {
      reads.push(url);
      const filter = url.searchParams.get('stage');
      const search = url.searchParams.get('search') || '';
      const match = (filter === 'all' || filter === item.stage || filter === 'active' && ['pending','working'].includes(item.stage)) &&
        (!search || item.business_name.includes(search)) && (!url.searchParams.has('source_sales_id') || url.searchParams.get('source_sales_id') === '5');
      return route.fulfill({ json: { items: match ? [item] : [], total: Number(match), sources: [{ id: 5, name: '销售乙' }] } });
    }
    if (url.pathname === api + '/42' && request.method() === 'POST') {
      const body = request.postDataJSON();
      writes.push(body);
      if (body.revision !== item.revision) return route.fulfill({ status: 409, json: { detail: '资料已变化' } });
      item.revision++;
      item.closer_id = body.action === 'delegate' ? body.manager_id : employee.id;
      item.closer_name = body.action === 'delegate' ? '主管丙' : employee.name;
      item.stage = body.action === 'lost' ? 'lost' : body.action === 'pause' ? 'nurturing' : 'working';
      if (body.loss_reason) Object.assign(item, { loss_reason: body.loss_reason });
      if (body.note && body.action !== 'delegate') item.note = body.note;
      if (body.next_follow_up_at) item.next_follow_up_at = body.next_follow_up_at;
      return route.fulfill({ json: item });
    }
    if (url.pathname === api + '/42/managers') return route.fulfill({ json: [{ id: 12, name: '主管丙' }] });
    if (url.pathname.endsWith('/emp-auth/me')) return route.fulfill({ json: employee });
    if (url.pathname.includes('/app-config')) return route.fulfill({ json: { items: {} } });
    if (url.pathname.endsWith('/assignees')) return route.fulfill({ json: [] });
    if (url.pathname.endsWith('/dashboard/call-report')) return route.fulfill({ json: { employees: [], summary: { provider_calls: 0 } } });
    if (url.pathname.endsWith('/recovery/overview')) return route.fulfill({ json: { items: [], summary: {} } });
    return route.fulfill({ json: { items: [], total: 0 } });
  });
  return { reads, writes };
}

for (const [role, width] of [['super_admin', 1280], ['sales_manager', 390]] as const) {
  test(`${role} ${width}px 来源销售和阶段组合筛选、接手和回访`, async ({ page }) => {
    const { reads, writes } = await fixture(page, role);
    await page.setViewportSize({ width, height: 844 });
    await page.goto(base + '/sales-leads');
    await page.getByRole('button', { name: '意向踢单', exact: true }).click();
    await expect(page).toHaveURL(/view=closing/);
    const queue = page.getByRole('region', { name: '意向踢单名单' });
    await expect(queue.getByText('客户想看预约演示')).toBeVisible();
    await queue.getByLabel('踢单阶段').selectOption('pending');
    await queue.getByLabel('来源销售').selectOption('5');
    await queue.getByLabel('搜索踢单商家或电话').fill('测试');
    await expect.poll(() => reads.at(-1)?.searchParams.get('search')).toBe('测试');
    expect(reads.at(-1)?.searchParams.get('source_sales_id')).toBe('5');
    expect(reads.at(-1)?.searchParams.get('stage')).toBe('pending');
    await queue.getByRole('button', { name: role === 'super_admin' ? '我来跟进' : '我来接手' }).click();
    await expect(queue.getByText('当前筛选下没有商家。')).toBeVisible();
    await queue.getByLabel('踢单阶段').selectOption('working');
    await queue.getByRole('button', { name: '记录进展' }).click();
    const dialog = page.getByRole('dialog', { name: '记录踢单进展' });
    await dialog.getByLabel('本次进展与下一步').fill('周五回电确认报价');
    await dialog.getByLabel('下次跟进时间（北京时间）').fill('2030-11-22T11:00');
    await dialog.getByRole('button', { name: '保存进展' }).click();
    await expect(queue.getByText('周五回电确认报价')).toBeVisible();
    await expect(queue.getByText('来源销售 销售乙', { exact: false }).first()).toBeVisible();
    expect(writes).toEqual([{ action: 'claim', revision: 0 }, { action: 'follow_up', revision: 1, note: '周五回电确认报价', next_follow_up_at: '2030-11-22T03:00:00.000Z' }]);
    expect(await queue.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    if (process.env.T24_UI_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.T24_UI_SCREENSHOT_DIR}/closing-${width}.png` });
    await queue.getByRole('button', { name: '更多踢单操作：测试美甲店' }).click();
    await expect(page.getByRole('menuitem', { name: '登记成交' })).toBeVisible();
  });
}
test('老板接手其他主管的踢单须填写原因', async ({ page }) => {
  const { writes } = await fixture(page, 'super_admin', 'working');
  await page.goto(base + '/sales-leads?view=closing');
  await page.getByRole('button', { name: '接手踢单' }).click();
  const dialog = page.getByRole('dialog', { name: '接手踢单' });
  await expect(dialog.getByRole('button', { name: '确认接手' })).toBeDisabled();
  await dialog.getByLabel('接手原因').fill('客户希望老板参与报价');
  await dialog.getByRole('button', { name: '确认接手' }).click();
  await expect(page.getByRole('button', { name: '记录进展' })).toBeVisible();
  expect(writes).toEqual([{ action: 'take_over', note: '客户希望老板参与报价', revision: 3 }]);
});
test('一线销售访问直链时返回联系进展，也不读取团队队列', async ({ page }) => {
  const { reads } = await fixture(page, 'sales');
  await page.goto(base + '/sales-leads?view=closing');
  await expect(page.getByRole('heading', { name: '联系进展', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '意向踢单', exact: true })).toHaveCount(0);
  expect(reads).toEqual([]);
});

test('号码变化时重新校验拨号目标并留在名单中', async ({ page }) => {
  await fixture(page, 'sales_manager');
  await page.route('**/closing-queue/42/dial-target?revision=1', route => route.fulfill({
    json: { lead_id: 42, revision: 1, phone: '+12025550193', country: 'US' },
  }));
  let providerCalls = 0;
  await page.route('**/app.ringcentral.com/**', route => { providerCalls++; return route.abort(); });
  await page.goto(base + '/sales-leads?view=closing');
  await page.getByRole('button', { name: '我来接手' }).click();
  await page.getByRole('button', { name: '拨打电话' }).click();
  await expect(page.getByText('商家或号码已变化，请刷新名单后重试')).toBeVisible();
  await expect(page).toHaveURL(/view=closing/);
  expect(providerCalls).toBe(0);
});

test('手机踢单可设置暂缓提醒，恢复后再登记未成交原因', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes } = await fixture(page, 'sales_manager');
  await page.goto(base + '/sales-leads?view=closing');
  const queue = page.getByRole('region', { name: '意向踢单名单' });
  await queue.getByRole('button', { name: '我来接手' }).click();
  await queue.getByRole('button', { name: '更多踢单操作：测试美甲店' }).click();
  await page.getByRole('menuitem', { name: '暂缓跟进' }).click();
  const deferDialog = page.getByRole('dialog', { name: '暂缓跟进' });
  await deferDialog.getByLabel('暂缓原因与下次联系计划').fill('当前合同到期前联系');
  await deferDialog.getByLabel('重新提醒时间（北京时间）').fill('2030-12-01T11:00');
  await deferDialog.getByRole('button', { name: '暂缓并设置提醒' }).click();
  await queue.getByLabel('踢单阶段').selectOption('nurturing');
  await expect(queue.getByText('当前合同到期前联系')).toBeVisible();
  await expect(queue.getByRole('button', { name: '拨打电话' })).toHaveCount(0);
  await queue.getByRole('button', { name: '恢复跟进' }).click();
  await queue.getByLabel('踢单阶段').selectOption('working');
  await queue.getByRole('button', { name: '更多踢单操作：测试美甲店' }).click();
  await page.getByRole('menuitem', { name: '结束踢单' }).click();
  const lossDialog = page.getByRole('dialog', { name: '结束踢单' });
  await lossDialog.getByLabel('结束说明').fill('对方续签了当前服务商');
  await expect(lossDialog.getByRole('button', { name: '确认结束' })).toBeDisabled();
  await lossDialog.getByLabel('未成交原因').selectOption('renewed_provider');
  await lossDialog.getByRole('button', { name: '确认结束' }).click();
  await queue.getByLabel('踢单阶段').selectOption('lost');
  await expect(queue.getByText('续签其他服务商')).toBeVisible();
  expect(writes.map(item => item.action)).toEqual(['claim', 'pause', 'resume', 'lost']);
  expect(writes[1].next_follow_up_at).toBe('2030-12-01T03:00:00.000Z');
  expect(writes[3].loss_reason).toBe('renewed_provider');
});

test('老板可把接手的踢单转给可见范围内的主管', async ({ page }) => {
  const { writes } = await fixture(page, 'super_admin');
  await page.goto(base + '/sales-leads?view=closing');
  const queue = page.getByRole('region', { name: '意向踢单名单' });
  await queue.getByRole('button', { name: '我来跟进' }).click();
  await queue.getByRole('button', { name: '记录进展' }).click();
  const progress = page.getByRole('dialog', { name: '记录踢单进展' });
  await progress.getByLabel('本次进展与下一步').fill('周五和店主确认');
  await progress.getByRole('button', { name: '保存进展' }).click();
  await queue.getByRole('button', { name: '更多踢单操作：测试美甲店' }).click();
  await page.getByRole('menuitem', { name: '转给主管跟进' }).click();
  const transfer = page.getByRole('dialog', { name: '转给主管跟进' });
  await expect(transfer.getByText('上次进展：周五和店主确认')).toBeVisible();
  await transfer.getByLabel('接手主管').selectOption('12');
  await transfer.getByLabel('交接说明').fill('请继续确认商家需求');
  await transfer.getByRole('button', { name: '确认转交' }).click();
  await expect(queue.getByText('踢单人 主管丙')).toBeVisible();
  await expect(queue.getByText('周五和店主确认')).toBeVisible();
  expect(writes.at(-1)).toEqual({ action: 'delegate', revision: 2, note: '请继续确认商家需求', manager_id: 12 });
});
