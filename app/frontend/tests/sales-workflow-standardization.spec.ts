import { test, expect, type Page } from '@playwright/test';
import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '../src/lib/business-date';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const employee = { id: 1, name: '测试管理员', role: 'super_admin', status: 'active' };
const lead = { id: 31, business_name: '统一流程餐厅', phone: '(212) 555-0123 ext. 9', country: 'US', contact_name: '陈老板', industry: '餐厅', status: 'interested', assigned_sales_id: 11, assigned_sales_name: '测试销售', next_follow_up_at: '2026-10-10T02:30:00Z', created_at:'2026-10-01T00:00:00Z', is_blacklisted:false, do_not_contact:false, do_not_contact_reason: '' };
async function seed(page: Page, options: { failReadiness?: boolean; failList?: boolean; failFollowUp?: boolean } = {}) {
  const writes: { path:string; method:string; data:any }[] = [];
  let currentLead = { ...lead };
  await page.addInitScript(emp => { localStorage.setItem('emp_auth_token','local-test');localStorage.setItem('token','local-test');localStorage.setItem('emp_auth_data',JSON.stringify(emp)); }, employee);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request=route.request(), url=new URL(request.url()), path=url.pathname;
    if (request.method() !== 'GET') writes.push({ path, method:request.method(), data:request.postDataJSON() });
    let data: any = { items:[],total:0 };
    if (path === '/api/config') data={API_BASE_URL:base};
    else if (path.endsWith('/emp-auth/me')) data=employee;
    else if (path.includes('/app-config')) data={items:{}};
    else if (path === '/api/v1/sales-leads') {
      if (options.failList && url.searchParams.has('status')) return route.fulfill({status:503,json:{detail:'模拟筛选读取失败'}});
      data={items:[currentLead],total:1};
    } else if (/sales-leads\/(?:dashboard|reports|recovery)\//.test(path) || path.endsWith('/sales-leads/performance')) data=null;
    else if (path.endsWith('/sales-leads/stats')) data={total:1,assigned:1,unassigned:0,blacklisted:0,do_not_contact:0};
    else if (path.endsWith('/sales-leads/assignees')) data=[{id:11,name:'测试销售',role:'sales'}];
    else if (path.endsWith('/sales-deal-controls/options')) data={employees:[]};
    else if (path.includes('/product-plans')) data={business_lines:[],products:[],plans:[]};
    else if (path.endsWith('/call-history')) data=[];
    else if (path.endsWith('/follow-up')) { if(options.failFollowUp) return route.fulfill({status:503,json:{detail:'模拟跟进保存失败'}}); const payload=request.postDataJSON(); const stopped=payload.outcome==='do_not_contact'; const released=payload.outcome==='not_interested'; currentLead={...currentLead,status:stopped?'blocked':released?'lost':'interested',next_follow_up_at:payload.next_follow_up_at,do_not_contact:stopped,do_not_contact_reason:stopped?payload.notes:'',assigned_sales_id:released?null:11}; data={status:currentLead.status,next_follow_up_at:payload.next_follow_up_at,lead:currentLead}; }
    else if (path.endsWith('/readiness')) {
      if(options.failReadiness) return route.fulfill({status:503,json:{detail:'模拟审核读取失败'}});
      data={lead,quotes:[],handoff:{},blockers:['需要一张已审批的报价单']};
    } else if (path.endsWith('/workbench/today')) data={salesperson:{id:11,name:'测试销售'},quota:100,assigned_count:0,completed_count:0,remaining_count:0,categories:{},performance:{},items:[]};
    else if (path.endsWith('/workbench/prepare')) data={created:0,message:'今日任务已准备'};
    else if(path.endsWith('/sales-intelligence/leads')) data={items:[]};
    else if(path.endsWith('/sales-intelligence/views')) data=[];
    else if(path.endsWith('/sales-intelligence/overview')) data=null;
    await route.fulfill({status:200,json:data});
  });
  return writes;
}

async function openFollowUp(page: Page) {
  await page.getByRole('button', { name: /更多线索操作/ }).click();
  await page.getByRole('menuitem', { name: '记录跟进', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: lead.business_name });
  await expect(drawer).toBeVisible();
  return drawer;
}
async function openDetails(page: Page) {
  await page.getByRole('button', { name: /更多线索操作/ }).click();
  await page.getByRole('menuitem', { name: '编辑资料', exact: true }).click();
  return page.getByRole('dialog', { name: '编辑销售线索' });
}

for (const timezoneId of ['America/Los_Angeles', 'Asia/Shanghai']) {
  test(`跟进独立保存且时间按北京保存，随后资料编辑保留原号码：${timezoneId}`, async ({ browser }) => {
    const context = await browser.newContext({ timezoneId, viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const writes = await seed(page);
    await page.goto(`${base}/sales-leads`);
    const drawer = await openFollowUp(page);
    const notes = drawer.getByLabel('沟通记录 *', { exact: true });
    const time = drawer.getByLabel('下次回访 · 北京时间', { exact: true });
    await expect(time).toHaveValue('2026-10-10T10:30');
    await expect(drawer.getByRole('button', { name: '保存资料', exact: true })).toHaveCount(0);
    await notes.fill('已沟通预算，需准备报价');
    await time.fill('2026-10-11T10:30');
    expect(writes).toHaveLength(0);
    page.once('dialog', dialog => dialog.dismiss());
    await page.keyboard.press('Escape');
    await expect(drawer).toBeVisible();
    await expect(notes).toHaveValue('已沟通预算，需准备报价');
    await drawer.getByRole('button', { name: '保存跟进', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toMatchObject({ method: 'POST', path: '/api/v1/sales-leads/31/follow-up', data: { notes: '已沟通预算，需准备报价', next_follow_up_at: '2026-10-11T02:30:00.000Z' } });
    await expect(notes).toHaveValue('');
    await expect(drawer.getByRole('button', { name: '保存跟进', exact: true })).toBeEnabled();
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    const details = await openDetails(page);
    await expect(details.locator('input[type="datetime-local"]')).toHaveValue('2026-10-11T10:30');
    await details.getByRole('button', { name: '保存资料', exact: true }).click();
    await expect.poll(() => writes.length).toBe(2);
    expect(writes[1]).toMatchObject({ method: 'PUT', path: '/api/v1/sales-leads/31', data: { phone: lead.phone, next_follow_up_at: '2026-10-11T02:30:00.000Z' } });
    expect(writes.some(write => /payments|expenses|deals|handoff|convert/.test(write.path))).toBe(false);
    await context.close();
  });
}
test('审核加载失败仍可重试且不能转客户', async ({ page }) => {
  const writes = await seed(page, { failReadiness: true });
  await page.goto(`${base}/sales-leads`);
  await page.getByRole('button', { name: '准备报价', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '成交审核资料读取失败' })).toBeVisible();
  await expect(page.getByRole('button', { name: '重新加载审核资料' })).toBeVisible();
  expect(await page.getByRole('button', { name: '确认合作并转入正式客户' }).count()).toBe(0);
  expect(writes).toHaveLength(0);
});
test('首次准备今日任务仍需明确操作', async ({ page }) => {
  const writes = await seed(page);
  await page.goto(`${base}/sales-workbench?sales_employee_id=11`);
  await expect(page.getByRole('button', { name: '生成今日任务', exact: true })).toBeVisible();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: '生成今日任务', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ method: 'POST', path: '/api/v1/sales-leads/workbench/prepare' });
});
test('跟进日期拒绝无效日历值，UTC及无时区数据库时间显示一致', () => {
  expect(formatBusinessDateTimeInput('2026-10-10T02:30:00Z')).toBe('2026-10-10T10:30');
  expect(formatBusinessDateTimeInput('2026-10-10T02:30:00')).toBe('2026-10-10T10:30');
  expect(() => parseBusinessDateTimeInput('2026-02-30T10:30')).toThrow();
  expect(() => parseBusinessDateTimeInput('2026-10-10T24:30')).toThrow();
});
test('筛选读取失败明确标记旧数据并暂停批量选择', async ({ page }) => {
  const writes = await seed(page, { failList: true });
  await page.goto(`${base}/sales-leads`);
  await expect(page.getByRole('button', { name: lead.business_name, exact: true })).toBeVisible();
  await page.getByRole('button', { name: '有意向', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '当前显示上次读取的结果' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '选择当前页全部线索' })).toBeDisabled();
  await expect(page.getByRole('checkbox', { name: `选择 ${lead.business_name}` })).toBeDisabled();
  expect(writes).toHaveLength(0);
});
test('保存跟进时冻结字段，等待响应后再清空', async ({ page }) => {
  await seed(page);
  let finish: (() => void) | undefined;
  await page.route('**/api/v1/sales-leads/31/follow-up', async route => {
    await new Promise<void>(resolve => { finish = resolve; });
    await route.fulfill({ status: 200, json: { status: 'interested', next_follow_up_at: '2026-10-10T02:30:00Z' } });
  });
  await page.goto(`${base}/sales-leads`);
  const drawer = await openFollowUp(page);
  const notes = drawer.getByLabel('沟通记录 *', { exact: true });
  const time = drawer.getByLabel('下次回访 · 北京时间', { exact: true });
  await notes.fill('此次沟通');
  await drawer.getByRole('button', { name: '保存跟进', exact: true }).click();
  await expect(notes).toBeDisabled();
  await expect(time).toBeDisabled();
  await expect(drawer.getByRole('combobox', { name: '本次结果', exact: true })).toBeDisabled();
  await expect(drawer.getByRole('button', { name: '保存中…', exact: true })).toBeDisabled();
  finish?.();
  await expect(notes).toBeEnabled();
  await expect(notes).toHaveValue('');
});
test('跟进失败保留已写记录和时间，重试入口仍在', async ({ page }) => {
  const writes = await seed(page, { failFollowUp: true });
  await page.goto(`${base}/sales-leads`);
  const drawer = await openFollowUp(page);
  await drawer.getByLabel('沟通记录 *', { exact: true }).fill('保存失败也要保留这段');
  await drawer.getByLabel('下次回访 · 北京时间', { exact: true }).fill('2026-10-12T09:30');
  await drawer.getByRole('button', { name: '保存跟进', exact: true }).click();
  await expect(page.getByText('模拟跟进保存失败', { exact: true })).toBeVisible();
  await expect(drawer.getByLabel('沟通记录 *', { exact: true })).toHaveValue('保存失败也要保留这段');
  await expect(drawer.getByLabel('下次回访 · 北京时间', { exact: true })).toHaveValue('2026-10-12T09:30');
  await expect(drawer.getByRole('button', { name: '保存跟进', exact: true })).toBeEnabled();
  expect(writes).toHaveLength(1);
  expect(writes[0].path).toBe('/api/v1/sales-leads/31/follow-up');
});
for (const outcome of ['do_not_contact', 'not_interested']) {
  test(`跟进后的${outcome}保护或释放状态不被随后资料保存覆盖`, async ({ page }) => {
    const writes = await seed(page);
    await page.goto(`${base}/sales-leads`);
    const drawer = await openFollowUp(page);
    await drawer.getByRole('combobox', { name: '本次结果', exact: true }).selectOption(outcome);
    await drawer.getByLabel('沟通记录 *', { exact: true }).fill('商家明确表达要求');
    await drawer.getByRole('button', { name: '保存跟进', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    await expect(drawer.getByLabel('沟通记录 *', { exact: true })).toHaveCount(outcome === 'do_not_contact' ? 0 : 1);
    if (outcome !== 'do_not_contact') await expect(drawer.getByLabel('沟通记录 *', { exact: true })).toHaveValue('');
    await expect(page.getByText('跟进记录已加入时间线', { exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    const details = await openDetails(page);
    await details.getByRole('button', { name: '保存资料', exact: true }).click();
    await expect.poll(() => writes.length).toBe(2);
    expect(writes[1].data).toMatchObject(outcome === 'do_not_contact'
      ? { status: 'blocked', do_not_contact: true, do_not_contact_reason: '商家明确表达要求' }
      : { status: 'lost', assigned_sales_id: null });
  });
}
for (const width of [390, 800, 1093, 1440]) {
  test(`联系进展和跟进侧栏在${width}px可操作且不溢出`, async ({ page }) => {
    const writes = await seed(page);
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await page.goto(`${base}/sales-leads`);
    const drawer = await openFollowUp(page);
    await expect(drawer.getByRole('button', { name: '保存跟进', exact: true })).toBeInViewport();
    await expect(drawer.getByLabel('沟通记录 *', { exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    expect(writes).toHaveLength(0);
    const output = process.env.T24_UI_SCREENSHOT_DIR;
    if (output) await page.screenshot({ path: `${output}/contact-progress-${width}.png`, animations: 'disabled' });
  });
}
test('主管逾期处理链接直接初始化现有逾期列表且无写入', async ({ page }) => {
  const writes = await seed(page);
  const readQueries: string[] = [];
  await page.route('**/api/v1/sales-intelligence/leads?**', async route => {
    readQueries.push(route.request().url());
    await route.fulfill({ status: 200, json: { items: [], total: 0, facets: { owners: [], sources: [], industries: [], stages: [] } } });
  });
  await page.goto(`${base}/sales-leads?view=intelligence&panel=leads&signal=overdue`);
  await expect(page.getByRole('combobox').filter({ has: page.locator('option[value="overdue"]') })).toHaveValue('overdue');
  await expect.poll(() => readQueries.some(query => new URL(query).searchParams.get('signal') === 'overdue')).toBe(true);
  expect(writes).toHaveLength(0);
});
