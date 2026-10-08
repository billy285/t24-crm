import { test, expect, type Page } from '@playwright/test';
import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '../src/lib/business-date';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const employee = { id: 1, name: '测试管理员', role: 'super_admin', status: 'active' };
const lead = { id: 31, business_name: '统一流程餐厅', phone: '(212) 555-0123 ext. 9', country: 'US', contact_name: '陈老板', industry: '餐厅', status: 'interested', assigned_sales_id: 11, assigned_sales_name: '测试销售', next_follow_up_at: '2026-10-10T02:30:00Z', created_at:'2026-10-01T00:00:00Z', is_blacklisted:false, do_not_contact:false };
async function seed(page: Page, options: { failReadiness?: boolean; failList?: boolean } = {}) {
  const writes: { path:string; method:string; data:any }[] = [];
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
      data={items:[lead],total:1};
    } else if (/sales-leads\/(?:dashboard|reports|recovery)\//.test(path) || path.endsWith('/sales-leads/performance')) data=null;
    else if (path.endsWith('/sales-leads/stats')) data={total:1,assigned:1,unassigned:0,blacklisted:0,do_not_contact:0};
    else if (path.endsWith('/sales-leads/assignees')) data=[{id:11,name:'测试销售',role:'sales'}];
    else if (path.endsWith('/sales-deal-controls/options')) data={employees:[]};
    else if (path.includes('/product-plans')) data={business_lines:[],products:[],plans:[]};
    else if (path.endsWith('/call-history')) data=[];
    else if (path.endsWith('/follow-up')) { const payload=request.postDataJSON(); const stopped=payload.outcome==='do_not_contact'; const released=payload.outcome==='not_interested'; data={status:stopped?'blocked':released?'lost':'interested',next_follow_up_at:payload.next_follow_up_at,lead:{...lead,status:stopped?'blocked':released?'lost':'interested',do_not_contact:stopped,do_not_contact_reason:stopped?payload.notes:null,assigned_sales_id:released?null:11}}; }
    else if (path.endsWith('/readiness')) {
      if(options.failReadiness) return route.fulfill({status:503,json:{detail:'模拟审核读取失败'}});
      data={lead,quotes:[],handoff:{},blockers:['需要一张已审批的报价单']};
    } else if (path.endsWith('/workbench/today')) data={salesperson:{id:11,name:'测试销售'},quota:100,assigned_count:0,completed_count:0,remaining_count:0,categories:{},performance:{},items:[]};
    else if (path.endsWith('/workbench/prepare')) data={created:0,message:'今日任务已准备'};
    else if(path.endsWith('/sales-intelligence/leads')) data={items:[]};
    await route.fulfill({status:200,json:data});
  });
  return writes;
}
for (const timezoneId of ['America/Los_Angeles', 'Asia/Shanghai']) {
  test(`跟进草稿不可被保存资料吞掉，时间按北京保存：${timezoneId}`, async ({ browser }) => {
    const context=await browser.newContext({timezoneId,viewport:{width:1440,height:1000}});
    const page=await context.newPage(); const writes=await seed(page);
    await page.goto(`${base}/sales-leads`);
    await page.getByRole('button',{name:'编辑',exact:true}).click();
    const dialog=page.getByRole('dialog');
    const times=dialog.locator('input[type="datetime-local"]');
    await expect(times.first()).toHaveValue('2026-10-10T10:30');
    await dialog.locator('textarea').nth(1).fill('已沟通预算，需准备报价');
    await times.nth(1).fill('2026-10-11T10:30');
    await dialog.getByRole('button',{name:'保存资料',exact:true}).click();
    expect(writes).toHaveLength(0);
    await expect(dialog).toBeVisible();
    await expect(page.getByText('本次跟进尚未保存，请先点击“保存本次跟进”，再保存资料。')).toBeVisible();
    await dialog.getByRole('button',{name:'保存本次跟进',exact:true}).click();
    await expect.poll(()=>writes.length).toBe(1);
    expect(writes[0]).toMatchObject({method:'POST',path:'/api/v1/sales-leads/31/follow-up',data:{notes:'已沟通预算，需准备报价',next_follow_up_at:'2026-10-11T02:30:00.000Z'}});
    await expect(dialog.locator('textarea').nth(1)).toHaveValue('');
    await dialog.getByRole('button',{name:'保存资料',exact:true}).click();
    await expect.poll(()=>writes.length).toBe(2);
    expect(writes[1]).toMatchObject({method:'PUT',path:'/api/v1/sales-leads/31',data:{phone:lead.phone,next_follow_up_at:'2026-10-11T02:30:00.000Z'}});
    await context.close();
  });
}
test('审核加载失败保留重试入口且不能转客户', async ({page}) => {
  const writes=await seed(page,{failReadiness:true});await page.goto(`${base}/sales-leads`);
  await page.getByRole('button',{name:'准备报价',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'成交审核资料读取失败'})).toBeVisible();
  await expect(page.getByRole('button',{name:'重新加载审核资料'})).toBeVisible();
  expect(await page.getByRole('button',{name:'确认合作并转入正式客户'}).count()).toBe(0);
  expect(writes).toHaveLength(0);
});
test('页面读取不自动生成任务，用户明确操作后才准备队列', async({page})=>{
 const writes=await seed(page);await page.goto(`${base}/sales-workbench`);
 await expect(page.getByRole('button',{name:'生成今日任务',exact:true})).toBeVisible();
 expect(writes).toHaveLength(0);
 await page.getByRole('button',{name:'生成今日任务',exact:true}).click();
 await expect.poll(()=>writes.length).toBe(1);
 expect(writes[0]).toMatchObject({method:'POST',path:'/api/v1/sales-leads/workbench/prepare'});
});
test('跟进日期拒绝无效日历值，UTC及无时区数据库时间显示一致',()=>{
 expect(formatBusinessDateTimeInput('2026-10-10T02:30:00Z')).toBe('2026-10-10T10:30');
 expect(formatBusinessDateTimeInput('2026-10-10T02:30:00')).toBe('2026-10-10T10:30');
 expect(()=>parseBusinessDateTimeInput('2026-02-30T10:30')).toThrow();
 expect(()=>parseBusinessDateTimeInput('2026-10-10T24:30')).toThrow();
});

test('筛选读取失败明确显示旧数据并暂停全选和单行批量选择',async({page})=>{
 const writes=await seed(page,{failList:true});await page.goto(`${base}/sales-leads`);
 await expect(page.getByRole('button',{name:lead.business_name,exact:true})).toBeVisible();
 await page.getByRole('button',{name:'有意向',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'当前显示上次读取的结果'})).toBeVisible();
 await expect(page.getByRole('checkbox',{name:'选择当前页全部线索'})).toBeDisabled();
 await expect(page.getByRole('checkbox',{name:`选择 ${lead.business_name}`})).toBeDisabled();
 expect(writes).toHaveLength(0);
});
test('保存跟进时冻结字段，避免异步响应清掉新输入',async({page})=>{
 await seed(page);let finish: (()=>void)|undefined;
 await page.route('**/api/v1/sales-leads/31/follow-up', async route=>{
   await new Promise<void>(resolve=>{finish=resolve;});
   await route.fulfill({status:200,json:{status:'interested',next_follow_up_at:'2026-10-10T02:30:00Z'}});
 });
 await page.goto(`${base}/sales-leads`);await page.getByRole('button',{name:'编辑',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.locator('textarea').nth(1).fill('此次沟通');
 await dialog.getByRole('button',{name:'保存本次跟进',exact:true}).click();
 await expect(dialog.locator('textarea').nth(1)).toBeDisabled();
 await expect(dialog.locator('input[type="datetime-local"]').nth(1)).toBeDisabled();
 await expect(dialog.getByRole('button',{name:'保存资料',exact:true})).toBeDisabled();
 finish?.();await expect(dialog.locator('textarea').nth(1)).toBeEnabled();
 await expect(dialog.locator('textarea').nth(1)).toHaveValue('');
});

for(const outcome of ['do_not_contact','not_interested']) {
 test(`跟进后的${outcome}保护或释放状态不会被资料保存覆盖`,async({page})=>{
  const writes=await seed(page);await page.goto(`${base}/sales-leads`);await page.getByRole('button',{name:'编辑',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.locator('label').filter({hasText:'本次跟进结果'}).locator('..').locator('select').selectOption(outcome);
  await dialog.locator('textarea').nth(1).fill('商家明确表达要求');
  await dialog.getByRole('button',{name:'保存本次跟进',exact:true}).click();
  await expect.poll(()=>writes.length).toBe(1);
  await expect(dialog.getByRole('button',{name:'保存资料',exact:true})).toBeEnabled();
  await dialog.getByRole('button',{name:'保存资料',exact:true}).click();
  await expect.poll(()=>writes.length).toBe(2);
  expect(writes[1].data).toMatchObject(outcome==='do_not_contact'?{status:'blocked',do_not_contact:true,do_not_contact_reason:'商家明确表达要求'}:{status:'lost',assigned_sales_id:null});
 });
}
