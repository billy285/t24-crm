import { expect, test, type Page, type Route } from '@playwright/test';
const baseUrl=process.env.T24_DOSSIER_BASE_URL||'http://127.0.0.1:8916';
const owner={id:1,name:'测试老板',role:'super_admin',status:'active'};
const viewer={id:3,name:'受邀销售',role:'sales',status:'active'};
const initial={
 insight:{id:91,business_name:'原线索名称',phone:'+16265550123',country:'US',owner:'主要销售 A',owner_id:2,source:'merchant_pool',industry:'餐厅',status:'follow_up',last_contact_at:'2026-10-15T04:00:00Z',next_follow_up_at:'2026-10-20T06:00:00Z',calls:3,connected:2,records:2,decision_conversations:1,manual_records:1,profile:{},revision:1,config:{pipelines:[],custom_fields:[]},timeline:[{id:'record1',label:'待回访',at:'2026-10-15T04:00:00Z',salesperson:'原销售 B',source:'manual',notes:'前台接听，老板不在；已约好下周二。'}],contributors:[{employee_id:2,name:'主要销售 A',calls:3,records:2,positive:1}],assignments:[]},
 enrichment:{lead_id:91,business_name:'核实后的洛杉矶餐厅',store_phone:'+16265550123',industry:'餐厅',country:'US',state:'CA',city:'Los Angeles',address:'100 Current Street',website:'https://example.com',contacts:[{id:'contact1',name:'陈老板',role:'老板',phone:'+16265550124',email:'chen@example.com',wechat:null,verification:'confirmed'}],preferred_contact_id:'contact1',interest_product_ids:[7],need_summary:'需要提高晚市客流',best_contact_time:'商家当地周二下午',verification:'confirmed',revision:2,lead_updated_at:'2026-10-15T04:00:00Z',updated_at:'2026-10-15T04:00:00Z',updated_by_name:'主要销售 A',can_edit:true,warnings:[]},
 summary:{revision:4,need_summary:'需要提高晚市客流',objections:'担心效果',promises:'周二前发案例',next_step:'按约定发广告案例',decision_maker:'陈老板',latest_conclusion:'老板有兴趣，等待案例',next_action_at:'2026-10-20T06:00:00Z',updated_by_name:'主要销售 A',updated_at:'2026-10-15T04:00:00Z'},
 protection:{can_contact:true,reason:'由主要负责人统一安排联系',cooldown_until:null},
 original:{id:293,business_name:'原始采集餐厅',phone:'+16265550123',contact_name:'前台',industry:'餐饮',state:'CA',city:'Alhambra',address:'27 Original Blvd',data_source:'Google Maps 原始采集',collected_at:'2026-10-14T03:00:00Z',pool_status:'converted',isolation_reason:'已人工确认并转入独立电话销售线索库'},
 permissions:{can_edit:true,can_edit_summary:true,can_invite:true,can_transfer:true,can_ack:false,can_review:true,can_edit_profile:true,can_release_protection:true},
 grants:[{id:1,employee_id:3,employee_name:'受邀销售',access:'view',status:'active',revision:1,employee_active:true}],
 handoffs:[{id:11,from_employee_id:4,to_employee_id:2,from_sales_name:'原销售 B',to_sales_name:'主要销售 A',note:'先查看已发资料，按约定周二回访。',summary:{promises:'周二前发案例'},status:'pending',created_at:'2026-10-14T06:00:00Z',acknowledged_at:null}],
 candidates:[{id:3,name:'受邀销售'},{id:4,name:'下一位销售'}],catalog:[{id:7,name:'Google 广告投放'}],
 changes:[{id:'change1',kind:'summary',actor_name:'主要销售 A',created_at:'2026-10-15T04:00:00Z',changed_fields:['promises'],before:{promises:''},after:{promises:'周二前发案例'}}],
};
async function json(route:Route,data:unknown,status=200){await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});}
async function seed(page:Page,options:{role?:'owner'|'viewer'|'collaborator'|'recipient';conflict?:boolean}={}){
 const emp=options.role==='owner'||!options.role?owner:options.role==='recipient'?{...viewer,id:2}:viewer;
 await page.addInitScript(emp=>{localStorage.setItem('emp_auth_token','fixture');localStorage.setItem('token','fixture');localStorage.setItem('emp_auth_data',JSON.stringify(emp));},emp);
 const data=JSON.parse(JSON.stringify(initial)),writes:{method:string;path:string;body:any}[]=[],reads:string[]=[];
 if(options.role&&options.role!=='owner'){data.permissions={can_edit:options.role==='collaborator',can_edit_summary:options.role==='collaborator',can_invite:false,can_transfer:false,can_ack:options.role==='recipient',can_review:false,can_edit_profile:false,can_release_protection:false};data.grants[0].access=options.role==='collaborator'?'collaborate':'view';data.candidates=[];}
 if(options.role==='recipient')data.protection={can_contact:false,reason:'请先确认接收交接摘要，再继续联系商家'};
 await page.route(/^https?:\/\/[^/]+\/api\//,async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
  if(req.method()!=='GET'){
   const body=req.postDataJSON();writes.push({method:req.method(),path:path+new URL(req.url()).search,body});
   if(path.endsWith('/91/summary')){if(options.conflict)return json(route,{detail:'资料已被他人更新，请重新核对'},409);data.summary={...data.summary,...body,revision:5};return json(route,data);}
   if(path.endsWith('/91/enrichment')){data.enrichment={...data.enrichment,...body,revision:3};return json(route,data);}
   if(path.endsWith('/91/invites')){data.grants.push({employee_id:body.employee_id,employee_name:'下一位销售',access:body.access,status:'active',revision:1});return json(route,data);}
   if(path.endsWith('/91/invites/3')){data.grants[0].status='revoked';return json(route,data);}
   if(path.endsWith('/handoffs/11/ack')){data.handoffs[0].acknowledged_at='2026-10-16T08:00:00Z';data.protection.can_contact=true;data.permissions.can_ack=false;return json(route,data);}
   return json(route,{detail:'拒绝未预期写入'},400);
  }
  reads.push(path);
  if(path.endsWith('/emp-auth/me'))return json(route,emp);
  if(path==='/api/v1/sales-lead-dossiers/91')return json(route,data);
  if(path==='/api/v1/sales-lead-dossiers')return json(route,{items:[{id:91,business_name:data.enrichment.business_name,industry:'餐厅',state:'CA',owner_name:'主要销售 A',access:options.role==='collaborator'?'collaborate':'view'}],total:1});
  if(path==='/api/v1/merchant-pool')return json(route,{items:[{...data.original,business_name:data.enrichment.business_name,pool_status:'converted',converted_lead_id:91}],total:1});
  if(path==='/api/v1/merchant-pool/stats')return json(route,{total:1,pending:0,converted:1,isolated:0,duplicates:0,archived:0});
  if(path.includes('/stats'))return json(route,{total:0,assigned:0,unassigned:0,blacklisted:0,do_not_contact:0});
  if(path.includes('/app-config'))return json(route,{items:{}});
  if(path.endsWith('/assignees'))return json(route,[{id:2,name:'主要销售 A',role:'sales'}]);
  return json(route,{items:[],total:0});
 });
 return{data,writes,reads};
}
async function open(page:Page,mode:'pool'|'shared'='pool'){
 await page.goto(`${baseUrl}/${mode==='pool'?'merchant-pool':'sales-leads?view=shared'}`);
 if(mode==='pool'){await page.getByRole('navigation',{name:'商家工作视图'}).getByRole('button',{name:/已转线索/}).click();await page.getByRole('button',{name:'查看资料：核实后的洛杉矶餐厅',exact:true}).click();}
 else await page.getByRole('button',{name:'打开协作档案：核实后的洛杉矶餐厅',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'核实后的洛杉矶餐厅',exact:true});await expect(dialog).toBeVisible();return dialog;
}
for(const width of[1093,390])test(`${width}px converted merchant shows latest dossier and folds raw import; history keeps authors`,async({page})=>{
 const{writes}=await seed(page);await page.setViewportSize({width,height:824});const d=await open(page);
 await expect(d.getByText('老板有兴趣，等待案例',{exact:true})).toBeVisible();await expect(d.getByRole('definition').filter({hasText:/^需要提高晚市客流$/})).toBeVisible();await expect(d.getByText('原始采集餐厅',{exact:true})).not.toBeVisible();if(process.env.T24_DOSSIER_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.T24_DOSSIER_SCREENSHOT_DIR}/dossier-overview-${width}.png`,fullPage:true,animations:'disabled'});await d.getByText('原始采集资料 · 保留来源',{exact:true}).click();await expect(d.getByText('原始采集餐厅',{exact:true})).toBeVisible();await expect(d.getByText('已转入销售跟进',{exact:true})).toBeVisible();await expect(d.getByText('隔离原因',{exact:true})).toHaveCount(0);
 await d.getByRole('button',{name:'联系人',exact:true}).click();await expect(d.getByRole('heading',{name:/陈老板/})).toBeVisible();await expect(d.getByText('Google 广告投放',{exact:true})).toBeVisible();await d.getByRole('button',{name:'累计记录',exact:true}).click();await expect(d.getByText('前台接听，老板不在；已约好下周二。',{exact:true})).toBeVisible();
 expect(writes).toEqual([]);expect(await d.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
 if(process.env.T24_DOSSIER_SCREENSHOT_DIR)await page.screenshot({path:`${process.env.T24_DOSSIER_SCREENSHOT_DIR}/dossier-${width}.png`,fullPage:true,animations:'disabled'});
});
test('summary clears fields with revision and does not replace authoritative needs/schedule',async({page})=>{
 const{writes}=await seed(page);const d=await open(page);await d.getByRole('button',{name:'更新摘要',exact:true}).click();await d.getByLabel('摘要：已承诺事项',{exact:true}).fill('');await d.getByLabel('摘要：主要顾虑',{exact:true}).fill('已解释费用，对方待确认');await expect(d.getByLabel('摘要：下次联系时间',{exact:true})).toHaveCount(0);await expect(d.getByLabel('摘要：商家需求',{exact:true})).toHaveCount(0);await d.getByRole('button',{name:'保存跟进摘要',exact:true}).click();await expect(d.getByText('已解释费用，对方待确认',{exact:true})).toBeVisible();expect(writes).toEqual([{method:'PUT',path:'/api/v1/sales-lead-dossiers/91/summary',body:{latest_conclusion:'老板有兴趣，等待案例',objections:'已解释费用，对方待确认',promises:'',expected_revision:4}}]);
});
test('409 preserves local input, and switching tabs cannot discard it',async({page})=>{
 const{writes}=await seed(page,{conflict:true});const d=await open(page);await d.getByRole('button',{name:'更新摘要',exact:true}).click();await d.getByLabel('摘要：已承诺事项',{exact:true}).fill('保留我的新承诺');await d.getByRole('button',{name:'保存跟进摘要',exact:true}).click();await expect(d.getByRole('alert')).toContainText('资料已被他人更新');await expect(d.getByLabel('摘要：已承诺事项',{exact:true})).toHaveValue('保留我的新承诺');await d.getByRole('button',{name:'联系人',exact:true}).click();await expect(d.getByLabel('摘要：已承诺事项',{exact:true})).toBeVisible();expect(writes).toHaveLength(1);
});
for(const role of['viewer','collaborator'] as const)test(`${role} uses invite endpoint only; cannot transfer, invite, dial or edit legacy profile`,async({page})=>{
 const{reads,writes}=await seed(page,{role});const d=await open(page,'shared');await expect(d.getByRole('button',{name:'更新摘要',exact:true})).toHaveCount(role==='collaborator'?1:0);await d.getByRole('button',{name:'归属与协作',exact:true}).click();await expect(d.getByRole('button',{name:'预览权限',exact:true})).toHaveCount(0);await expect(d.getByRole('button',{name:'转交并填写交接',exact:true})).toHaveCount(0);expect(reads.filter(path=>path.startsWith('/api/v1/sales-intelligence/leads/91')||path.startsWith('/api/v1/sales-leads/91/enrichment'))).toEqual([]);expect(writes).toEqual([]);
});
test('owner previews invitation before granting; revoke carries revision and disappears',async({page})=>{
 const{writes}=await seed(page);const d=await open(page);await d.getByRole('button',{name:'归属与协作',exact:true}).click();await d.getByLabel('邀请销售',{exact:true}).selectOption('4');await d.getByLabel('邀请权限',{exact:true}).selectOption('collaborate');await expect(d.getByRole('button',{name:'确认邀请',exact:true})).toHaveCount(0);expect(writes).toHaveLength(0);await d.getByRole('button',{name:'预览权限',exact:true}).click();await expect(d.getByLabel('邀请权限预览')).toContainText('不授予拨号');await expect(d.getByLabel('邀请权限预览')).toContainText('不开放公司财务');await d.getByRole('button',{name:'确认邀请',exact:true}).click();await expect(d.locator('.sd-person-row').filter({has:page.getByText('下一位销售',{exact:true})})).toBeVisible();expect(writes[0].body).toEqual({employee_id:4,access:'collaborate',expected_revision:0});const row=d.locator('.sd-person-row').filter({has:page.getByText('受邀销售',{exact:true})});await row.getByRole('button',{name:'撤销邀请',exact:true}).click();await d.getByRole('button',{name:'确认撤销',exact:true}).click();await expect(d.locator('.sd-person-row').filter({has:page.getByText('受邀销售',{exact:true})})).toHaveCount(0);expect(writes[1]).toEqual({method:'DELETE',path:'/api/v1/sales-lead-dossiers/91/invites/3?expected_revision=1',body:null});
});
test('recipient reads handoff note and snapshot, then explicitly acknowledges',async({page})=>{
 const{writes}=await seed(page,{role:'recipient'});const d=await open(page,'shared');await expect(d.getByLabel('待确认交接')).toContainText('先查看已发资料');await expect(d.getByLabel('待确认交接')).toContainText('周二前发案例');await d.getByRole('button',{name:'已阅读，确认接收',exact:true}).click();await expect(d.getByLabel('待确认交接')).toHaveCount(0);expect(writes).toEqual([{method:'POST',path:'/api/v1/sales-lead-dossiers/91/handoffs/11/ack',body:{}}]);
});

test('collaborator edits canonical contact through dossier endpoint with enrichment locks',async({page})=>{
 const{writes,reads}=await seed(page,{role:'collaborator'});const d=await open(page,'shared');await d.getByRole('button',{name:'补充资料',exact:true}).click();const edit=page.getByRole('dialog',{name:'快捷补全',exact:true});await expect(edit).toBeVisible();await edit.getByLabel('联系人 1 姓名',{exact:true}).fill('陈先生');await edit.getByRole('button',{name:'保存资料，继续沟通',exact:true}).click();await expect(edit).toHaveCount(0);await d.getByRole('button',{name:'联系人',exact:true}).click();await expect(d.getByRole('heading',{name:/陈先生/})).toBeVisible();expect(writes).toHaveLength(1);expect(writes[0].path).toBe('/api/v1/sales-lead-dossiers/91/enrichment');expect(writes[0].body.expected_revision).toBe(2);expect(writes[0].body.expected_lead_updated_at).toBe('2026-10-15T04:00:00Z');expect(writes[0].body.source).toBe('manual');expect(reads.filter(path=>path.startsWith('/api/v1/sales-leads/91/enrichment'))).toEqual([]);
});
test('existing sales-stage edits retain scope and warn before losing unsaved form',async({page})=>{
 const{writes}=await seed(page);const d=await open(page);await d.getByText('商机阶段与主管复核',{exact:true}).click();await d.getByLabel('参与人／决策人',{exact:true}).fill('新决策人待核实');await d.getByRole('button',{name:'累计记录',exact:true}).click();await expect(d.getByLabel('参与人／决策人',{exact:true})).toHaveValue('新决策人待核实');await expect(d.getByRole('alert')).toContainText('请先保存或取消');await d.getByRole('button',{name:'取消商机修改',exact:true}).click();await d.getByRole('button',{name:'累计记录',exact:true}).click();await expect(d.getByText('前台接听，老板不在；已约好下周二。',{exact:true})).toBeVisible();expect(writes).toEqual([]);
});
