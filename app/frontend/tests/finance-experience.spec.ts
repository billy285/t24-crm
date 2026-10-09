import { expect, test, type Page, type Route } from '@playwright/test';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
if (!['localhost', '127.0.0.1'].includes(new URL(base).hostname)) throw new Error('Local mock server required');
test.use({ timezoneId: 'Asia/Shanghai', viewport: {width:390, height:844} });
type Write = {path:string; body:any; method:string};
const payrollItem = {id:9, employee_id:9, employee_name:'模拟员工', payment_method:'bank_card', base_salary:5000, fixed_performance:123.45, commission:88, bonus:55, allowance:2, reimbursement:3, absence_deduction:4, performance_deduction:5, salary_advance_deduction:6, other_deduction:7, payment_status:'pending', gross_amount:5281.45, deduction_amount:22, net_amount:5259.45};
async function setup(page:Page, handler:(route:Route, path:string)=>Promise<boolean>, role='admin') {
  await page.clock.install({ time:new Date('2026-10-10T12:00:00+08:00') });
  const employee={id:1,name:'体验模拟管理员',role,status:'active'};
  await page.addInitScript(e=>{localStorage.setItem('emp_auth_token','experience-fixture');localStorage.setItem('token','experience-fixture');localStorage.setItem('emp_auth_data',JSON.stringify(e));}, employee);
  const writes:Write[]=[];
  await page.route(/^https?:\/\/[^/]+\/api\//,async route=>{
    const request=route.request(); const path=new URL(request.url()).pathname;
    if(request.method()!=='GET') {writes.push({path,method:request.method(),body:request.postDataJSON()});await route.fulfill({json:{message:'模拟保存'}});return;}
    if(await handler(route,path))return;
    const data=path.endsWith('/emp-auth/me')?employee:path==='/api/v1/app-config'?{items:{}}:path.includes('/app-config/')?{value:{}}:path.includes('/entities/')?{items:[],total:0}:{};
    await route.fulfill({json:data});
  });
  return writes;
}
async function payrollFixture(page:Page, mode:'copy'|'fail'|'wrong') {
  const reads:string[]=[];
  const writes=await setup(page,async (route,path)=>{
    if(path==='/api/v1/payroll') {const month=new URL(route.request().url()).searchParams.get('month')!;reads.push(month);
      if(mode==='fail' && month==='2026-09'){await route.fulfill({status:503,json:{detail:'模拟月份读取失败'}});return true;}
      await route.fulfill({json:{sheet:{id:1,month:mode==='wrong'&&month==='2026-09'?'2026-08':month,status:'draft',currency:'CNY'},items:mode==='copy'&&month==='2026-10'?[]:[payrollItem],totals:{gross:5281.45,deductions:22,net:5259.45}}});return true;
    }
    if(path.endsWith('/payroll/employees')){await route.fulfill({json:[{id:9,name:'模拟员工'}]});return true;}
    return false;
  });return {reads,writes};
}
test('北京时间复制上月明确来源和目标，确认前不写入，动态项清零且固定项保留',async({page})=>{
  const {reads,writes}=await payrollFixture(page,'copy');await page.goto(`${base}/payroll`);await page.getByRole('button',{name:'复制上月',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'确认复制上月工资'});await expect(dialog).toContainText('来源 2026-09 → 目标 2026-10');expect(reads).toEqual(['2026-10','2026-09']);expect(writes).toHaveLength(0);
  await dialog.getByRole('button',{name:'确认复制',exact:true}).click();await expect(dialog).toBeHidden();expect(writes).toHaveLength(1);expect(writes[0]).toMatchObject({path:'/api/v1/payroll/2026-10/items',body:{base_salary:5000,fixed_performance:123.45,commission:0,bonus:0,absence_deduction:0,payment_status:'pending'}});
});
for(const mode of ['fail','wrong'] as const)test(`工资切月${mode}不能继续写旧月明细`,async({page})=>{
  const {writes}=await payrollFixture(page,mode);await page.goto(`${base}/payroll`);await expect(page.getByRole('button',{name:'编辑',exact:true})).toBeEnabled();await page.getByLabel('工资月份').fill('2026-09');
  await expect(page.getByText(/2026-09 工资表读取失败/)).toBeVisible();await expect(page.getByRole('button',{name:'新增员工',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'编辑',exact:true})).toHaveCount(0);expect(writes).toHaveLength(0);
});
test('扣点保留小数比例；关闭有修改的表单可继续编辑；读取失败不是默认15或暂无数据',async({page})=>{
  let failed=false;const writes=await setup(page,async(route,path)=>{if(path.endsWith('/deductions-monthly/default')){await route.fulfill({json:{rate:0.1555}});return true;}if(path.endsWith('/deductions-monthly')){await route.fulfill(failed?{status:503,json:{detail:'模拟扣点不可读'}}:{json:[{year_month:'2026-10',rate:0.1555}]});return true;}return false;});
  await page.goto(`${base}/settings/deduction`);await expect(page.locator('td[data-label="扣点比例"]')).toHaveText('15.55%');await expect(page.getByLabel('默认扣点 (%)')).toHaveValue('15.55');await page.getByRole('button',{name:'编辑',exact:true}).click();const dialog=page.getByRole('dialog',{name:'编辑月份'});await expect(dialog.getByLabel('扣点比例 (%)')).toHaveValue('15.55');await dialog.getByLabel('扣点比例 (%)').fill('17.25');page.once('dialog',dialog=>dialog.dismiss());await dialog.getByRole('button',{name:'取消',exact:true}).click();await expect(dialog).toBeVisible();await expect(dialog.getByLabel('扣点比例 (%)')).toHaveValue('17.25');page.once('dialog',dialog=>dialog.accept());await dialog.getByRole('button',{name:'取消',exact:true}).click();failed=true;await page.getByRole('button',{name:'刷新',exact:true}).click();await expect(page.getByText(/扣点设置读取失败/)).toBeVisible();await expect(page.getByRole('button',{name:'新增月份'})).toBeDisabled();await expect(page.getByText('暂无数据',{exact:true})).toHaveCount(0);expect(writes).toHaveLength(0);
});
async function financeFixture(page:Page, refundsCount=2, options:{missingDate?:boolean;receivable?:boolean}={}) {
  const customers=[{id:1,business_name:'同名客户',status:'active'},{id:2,business_name:'同名客户',status:'active'}];
  const payments=customers.map((customer,index)=>({id:11+index,customer_id:customer.id,customer_name:customer.business_name,amount_due:100+index,amount_paid:100+index,outstanding_amount:0,management_amount:100+index,ads_recharge_amount:0,stripe_fee_amount:0,currency:'USD',income_type:'management_fee',payment_mode:'manual_collection',payment_method:'zelle',payment_date:'2026-10-05',product_name:`模拟产品${index+1}`}));
  if(options.missingDate) payments[0].payment_date='';
  if(options.receivable) {payments[0].amount_due=200;payments[0].outstanding_amount=100;}
  const refunds=Array.from({length:refundsCount},(_,i)=>({id:100+i,payment_id:11,customer_id:1,customer_name:'同名客户',refund_amount:1,stripe_fee_refunded_amount:0,currency:'USD',status:i%2?'pending':'completed',refund_date:'2026-10-06',reason:`退款${i+1}`}));
  return setup(page,async(route,path)=>{const entity=path.match(/\/entities\/([^/]+)/)?.[1];const data=entity==='follow_ups'?{items:[{id:1,customer_id:1,created_at:'2026-10-09T04:00:00Z',content:'模拟跟进：客户已安排周五付款'}],total:1}:entity?{items:entity==='customers'?customers:entity==='payments'?payments:[],total:entity==='customers'||entity==='payments'?2:0}:path.includes('/entities/follow_ups')?{items:[{id:1,customer_id:1,created_at:'2026-10-09T04:00:00Z',content:'模拟跟进：客户已安排周五付款'}],total:1}:path.endsWith('/finance/refunds')?{items:refunds}:path.endsWith('/finance/ad-fund-settlements')?{items:[]}:path.includes('/deductions-monthly')?[{year_month:'2026-10',rate:0.15}]:path.endsWith('/commissions/dashboard')?{entries:[]}:path.includes('/reports/profit-monthly.json')?[{year_month:'2026-10',revenue:201,profit:170.85}]:path.endsWith('/product-plans')?{business_lines:[],products:[],plans:[]}:null;if(data){await route.fulfill({json:data});return true;}return false;});
}
test('同名客户利润进入原账按ID精确定位并保留账期和返回入口',async({page})=>{
  const writes=await financeFixture(page);await page.goto(`${base}/finance?tab=customer_profit`);const target=page.locator('.mfd-record[data-record-id="profit-1"]');await target.locator('summary').click();await target.getByRole('button',{name:'查看并编辑原始收支'}).click();await expect(page).toHaveURL(/customer_id=1/);await expect(page).toHaveURL(/start=2026-10-01/);await expect(page.getByRole('button',{name:'返回客户利润'})).toBeVisible();await expect(page.getByRole('region',{name:'流水列表'}).locator('summary')).toHaveCount(1);await expect(page.getByRole('region',{name:'流水列表'})).toContainText('模拟产品1');await expect(page.getByRole('region',{name:'流水列表'})).not.toContainText('模拟产品2');expect(writes).toHaveLength(0);
});
test('收款修改取消时有离开保护，继续编辑保留输入和原金额',async({page})=>{
  const writes=await financeFixture(page);await page.goto(`${base}/finance?tab=income`);const card=page.getByRole('region',{name:'流水列表'}).locator('details').first();await card.locator('summary').click();await card.getByRole('button',{name:/编辑收款记录/}).click();const dialog=page.getByRole('dialog',{name:'编辑收款记录'});await dialog.locator('textarea').fill('尚未保存的模拟备注');page.once('dialog',dialog=>dialog.dismiss());await dialog.getByRole('button',{name:'取消',exact:true}).click();await expect(dialog).toBeVisible();await expect(dialog.locator('textarea')).toHaveValue('尚未保存的模拟备注');expect(writes).toHaveLength(0);
});
test('退款桌面有状态搜索和分页，列表过滤不会写入账目',async({page})=>{
  await page.setViewportSize({width:1440,height:1000});const writes=await financeFixture(page,25);await page.goto(`${base}/finance?tab=refunds`);await expect(page.locator('table tbody tr')).toHaveCount(20);
  // Existing page bootstrapping may ensure monthly deduction configuration; filters must never mutate a financial record.
  expect(writes.every(write=>write.path==='/api/v1/deductions-monthly/ensure')).toBe(true);const loadedWriteCount=writes.length;
  await page.getByRole('button',{name:'下一页',exact:true}).click();await expect(page.locator('table tbody tr')).toHaveCount(5);await page.getByLabel('搜索退款记录').fill('退款25');await expect(page.locator('table tbody tr')).toHaveCount(1);expect(writes).toHaveLength(loadedWriteCount);
});
test('手机分润超过六个渠道仍可查看全部台账和结算，保持只读',async({page})=>{
  const entries=Array.from({length:25},(_,i)=>({id:i+1,payment_id:i+11,partner_name:`渠道${i+1}`,customer_name:`客户${i+1}`,customer_id:i+1,service_month:'2026-10',entry_type:'first_order',eligible_service_amount:100,gross_receipt_amount:100,contract_rate:0.1,activity_multiplier:1,commission_amount:10,currency:'USD',status:'confirmed',inactivity_months:0}));
  const writes=await setup(page,async(route,path)=>{if(path.endsWith('/commissions/dashboard')){await route.fulfill({json:{entries,partners:[],agreements:[],attributions:[],quality_issues:[],summary:{currencies:{},active_partner_count:0,pending_count:0}}});return true;}return false;});await page.goto(`${base}/commissions`);const region=page.getByRole('region',{name:'手机分润明细'});await expect(region.locator('details')).toHaveCount(20);await region.getByRole('button',{name:'加载更多分润'}).click();await expect(region.locator('details')).toHaveCount(25);await expect(region).toContainText('渠道7');await region.getByRole('button',{name:'月度结算',exact:true}).click();await region.getByRole('button',{name:'加载更多分润'}).click();await expect(region).toContainText('渠道7');await expect(page.getByRole('button',{name:'确认变更'})).toHaveCount(0);expect(writes).toHaveLength(0);
});

test('手机关账卡点直达正确月份和异常流水，返回月度检查不写入',async({page})=>{
  const writes=await financeFixture(page,2,{missingDate:true});await page.goto(`${base}/finance?tab=monthly_detail`);
  await page.locator('.mfd-record[data-record-id="month-2026-10"] summary').click();await page.getByRole('button',{name:'处理收款缺日期：1项',exact:true}).click();
  await expect(page).toHaveURL(/tab=income/);await expect(page).toHaveURL(/month=2026-10/);await expect(page).toHaveURL(/issue=missingPaymentDate/);
  await expect(page.getByRole('region',{name:'流水列表'}).locator('summary')).toHaveCount(1);await expect(page.getByRole('region',{name:'流水列表'})).toContainText('模拟产品1');
  await page.getByRole('button',{name:'返回月度检查'}).click();await expect(page).toHaveURL(/tab=monthly_detail/);expect(writes).toHaveLength(0);
});
test('手机应收显示原欠款、负责人及真实最近跟进，查阅不提交收款',async({page})=>{
  const writes=await financeFixture(page,2,{receivable:true});await page.goto(`${base}/finance?tab=receivables`);const list=page.getByRole('region',{name:'应收列表'});
  await expect(list).toContainText('$100');await expect(list).toContainText('负责人');await expect(list).toContainText('模拟跟进：客户已安排周五付款');await expect(list).toContainText('北京时间');expect(writes).toHaveLength(0);
});
test('桌面佣金变更先展示对象与旧新状态，取消不写入，确认只提交原transition字段',async({page})=>{
  await page.setViewportSize({width:1440,height:1000});const writes=await setup(page,async(route,path)=>{if(path.endsWith('/commissions/dashboard')){await route.fulfill({json:{entries:[{id:1,payment_id:11,partner_name:'模拟渠道',customer_name:'模拟客户',customer_id:1,service_month:'2026-10',entry_type:'first_order',eligible_service_amount:100,gross_receipt_amount:100,contract_rate:0.1555,activity_multiplier:1,commission_amount:15.55,currency:'USD',status:'confirmed',inactivity_months:0}],partners:[],agreements:[],attributions:[],quality_issues:[],summary:{currencies:{},active_partner_count:0,pending_count:0}}});return true;}return false;});
  await page.goto(`${base}/commissions`);await page.getByRole('button',{name:'转应付',exact:true}).click();const dialog=page.getByRole('dialog',{name:'确认佣金状态变更'});await expect(dialog).toContainText('模拟客户 · 模拟渠道 · 2026-10');await expect(dialog).toContainText('已确认入账 → 待发放');expect(writes).toHaveLength(0);await dialog.getByRole('button',{name:'取消',exact:true}).click();expect(writes).toHaveLength(0);await page.getByRole('button',{name:'转应付',exact:true}).click();await dialog.getByRole('button',{name:'确认变更'}).click();expect(writes).toEqual([{path:'/api/v1/commissions/entries/1/transition',method:'POST',body:{to_status:'payable',reason:null,payout_reference:null}}]);
});

test('合伙人手机三个分组完整可查，历史协议和小数比例不被隐藏，浏览保持只读',async({page})=>{
  const customers=Array.from({length:25},(_,i)=>({row_key:`row-${i}`,attribution_id:i+1,customer_name:`模拟客户${i+1}`,cooperation_status:'active_paid',renewal_status:'active',commission_impact:'按原协议',effective_from:'2026-10-01',is_active:true}));
  const entries=Array.from({length:25},(_,i)=>({id:i+1,customer_name:`模拟客户${i+1}`,entry_type:'first_order',status:'confirmed',service_month:'2026-10',currency:'USD',eligible_service_amount:100,contract_rate:0.1555,inactivity_months:0,activity_multiplier:1,commission_amount:15.55}));
  const writes=await setup(page,async(route,path)=>{if(path.endsWith('/commissions/my-dashboard')){await route.fulfill({json:{partner:{id:1,name:'模拟渠道',partner_code:'MOCK',status:'active',joined_at:'2026-10-01'},summary:{active_customer_count:25,cooperation_customer_count:25,renewal_attention_count:0,stopped_customer_count:0,ledger_count:25,currencies:{USD:{pending:0,confirmed:388.75,payable:0,paid:0}},status_updated_at:'2026-10-10T04:00:00Z'},customers,entries,agreements:[{id:1,version:1,business_line_name:'模拟业务',product_name:'模拟套餐',first_order_rate:0.1555,renewal_rate:0.05,activity_decay:{'6':0},refund_guard_days:30,effective_from:'2026-10-01',status:'active'},{id:2,version:2,business_line_name:'模拟业务',product_name:'历史套餐',first_order_rate:0.1555,renewal_rate:0.05,activity_decay:{'6':0},refund_guard_days:30,effective_from:'2026-09-01',status:'archived'}]}});return true;}return false;},'sales_partner');
  await page.goto(`${base}/partner-portal`);const region=page.getByRole('region',{name:'手机端客户与分润明细'});await expect(region.locator('article:visible')).toHaveCount(20);await region.getByRole('button',{name:'加载更多明细'}).click();await expect(region.locator('article:visible')).toHaveCount(25);await page.getByRole('button',{name:'分润',exact:true}).click();await expect(region.locator('article:visible')).toHaveCount(20);await expect(region.locator('article:visible').first()).toContainText('15.55%');await page.getByRole('button',{name:'协议',exact:true}).click();await page.getByRole('combobox').last().selectOption('inactive');await expect(region.getByText('V2 · 模拟业务',{exact:true})).toBeVisible();expect(writes).toHaveLength(0);
});
