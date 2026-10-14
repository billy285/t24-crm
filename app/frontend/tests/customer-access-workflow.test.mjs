import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
import ts from 'typescript';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const backend=resolve(root,'../../backend');
const flush=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));};
const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
function validate(request){
 const model=request.method==='PUT'&&request.url.endsWith('/access')?'CustomerAccessUpdateRequest':request.method==='POST'&&request.url.endsWith('/access/preview')?'CustomerAccessAssignment':request.url.endsWith('/access/bulk-update')?'CustomerAccessBulkUpdateRequest':request.method==='PUT'&&request.url.endsWith('/finance')?'CustomerFinanceAccessInput':request.method==='PUT'&&request.url.endsWith('/private-note')?'CustomerPrivateNoteInput':null;
 if(!model)return;
 const result=spawnSync(process.env.T24_TEST_PYTHON||'python3',['-c',`import json,sys\nfrom routers import customers\ngetattr(customers,sys.argv[1]).model_validate(json.load(sys.stdin))\nprint('validated')`,model],{cwd:backend,input:JSON.stringify(request.data),encoding:'utf8',env:{...process.env,APP_ENV:'test',DATABASE_URL:'sqlite+aiosqlite:///:memory:',PYTHONPATH:'.:..'}});
 assert.equal(result.status,0,`Real ${model} rejected payload. ${result.stderr||result.error||''}`);
}
function fixture(file,initialProps={},handler=()=>({})){const states=[],effects=[],cache=new Map(),requests=[],notices=[],exports=[],validationErrors=[];let cursor=0,tree,props=initialProps;
 const react={
 useState(initial){const i=cursor++;if(!states[i])states[i]={value:typeof initial==='function'?initial():initial};return[states[i].value,v=>{states[i].value=typeof v==='function'?v(states[i].value):v;}];},
 useRef(initial){const i=cursor++;if(!states[i])states[i]={value:{current:initial}};return states[i].value;},
 useMemo(factory,deps){const i=cursor++;if(!states[i]||!same(states[i].deps,deps))states[i]={value:factory(),deps};return states[i].value;},
 useCallback(fn,deps){return react.useMemo(()=>fn,deps);},
 useEffect(fn,deps){const i=cursor++;if(!states[i]||!same(states[i].deps,deps)){states[i]?.cleanup?.();states[i]={deps};effects.push(()=>{states[i].cleanup=fn();});}},
 };
 const storage=new Map();
 function load(relative){if(cache.has(relative))return cache.get(relative);const module={exports:{}};const compiled=ts.transpileModule(readFileSync(resolve(root,relative),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const req=name=>{
  if(name==='react')return react;if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'Fragment'};
  if(name.endsWith('.css'))return{};
  if(name==='@/lib/customer-permissions')return load('lib/customer-permissions.ts');
  if(name==='@/lib/permissions')return load('lib/permissions.ts');
  if(name==='./finance-navigation')return{financeNavigationItems:[],normalizeFinanceTab:value=>value};
  if(name==='./app-config')return {readCachedAppConfig:(_k,f)=>f,writeCachedAppConfig:()=>{}};
  if(name==='@/lib/tokenStore')return{invokeWithAuth:async request=>{requests.push(request);try{validate(request);}catch(err){validationErrors.push(err);throw err;}return{data:await handler(request)};}};
  if(name==='@/lib/use-unsaved-changes')return{useUnsavedChanges:()=>({confirmDiscard:()=>true,markSaved:()=>{}})};
  if(name==='@/lib/export')return{exportCSV:args=>exports.push(args),exportExcel:args=>exports.push(args)};
  if(name==='sonner')return{toast:{success:t=>notices.push(t),error:t=>notices.push(t)}};
  return new Proxy({default:name},{get:(target,key)=>target[key]||String(key)});
 };
 vm.runInNewContext(`(function(require,module,exports){${compiled}\n})`,{Intl,Date,console:{...console,error:()=>{}},URL,URLSearchParams,localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}})(req,module,module.exports);cache.set(relative,module.exports);return module.exports;}
 const Component=load(file).default;
 const render=(next)=>{if(next)props=next;cursor=0;tree=Component(props);while(effects.length)effects.shift()();return tree;};
 const settle=async()=>{await flush();render();await flush();render();assert.equal(validationErrors.length,0,validationErrors[0]?.message);};
 const walk=(node,predicate)=>!node?[]:Array.isArray(node)?node.flatMap(n=>walk(n,predicate)):typeof node!=='object'?[]:[...(predicate(node)?[node]:[]),...walk(typeof node.type==='function'?node.type(node.props):node.props?.children,predicate)];
 const text=node=>node==null||typeof node==='boolean'?'':typeof node!=='object'?String(node):Array.isArray(node)?node.map(text).join(' '):text(typeof node.type==='function'?node.type(node.props):node.props?.children);
 const all=predicate=>walk(tree,predicate);
 return{render,settle,requests,notices,exports,load,text,tree:()=>tree,all,byLabel:label=>all(n=>n.props?.['aria-label']===label)[0],button:label=>all(n=>n.type==='Button'&&text(n).replace(/\s+/g,' ').trim()===label)[0]};
}
const scopes={basic:'read_only',contacts:'none',followups:'none',opportunities:'none',delivery:'none',renewals:'none',deals:'read_only',materials:'none'};
function permission(level='read_write',finance='none',overrides={}){return{access_level:level,modules:Object.fromEntries(Object.keys(scopes).map(k=>[k,{read:level!=='none',write:level==='read_write'}])),finance_access:finance,can_delete:false,can_export:false,can_reassign:false,can_manage_access:false,reveal_secrets:false,sources:[{code:'responsible',label:'客户负责人'}],explicit:true,invitation_status:'active',invitation_source:'owner_invitation',...overrides};}
const employees=[{id:1,name:'老板',role:'super_admin',status:'active'},{id:2,name:'销售甲',role:'sales',status:'active'},{id:3,name:'设计乙',role:'design',status:'active'},{id:4,name:'管理员丙',role:'admin',status:'active'}];
const member=(id,legacy=false)=>({...employees.find(e=>e.id===id),employee_id:id,access_level:'read_only',scopes,finance_access:legacy?'profit':'none',can_delete:false,can_export:false,can_reassign:false,explicit:true,invitation_status:legacy?'pending':'active',invitation_source:legacy?'legacy':'owner_invitation',effective_permissions:permission('read_only',legacy?'none':'none',{modules:Object.fromEntries(Object.entries(scopes).map(([k,v])=>[k,{read:v!=='none',write:v==='read_write'}]))})});
function accessResponse(request){if(request.url.endsWith('/access')&&request.method==='GET')return{customer_id:101,owner:employees[0],members:[member(2)],pending_legacy_members:[member(4,true)],eligible_employees:employees};if(request.url.endsWith('/preview'))return{effective_permissions:permission(request.data.access_level,'none',{modules:Object.fromEntries(Object.entries(request.data.scopes).map(([k,v])=>[k,{read:v!=='none',write:v==='read_write'}])),sources:[{code:'owner_invitation',label:'老板邀请'}]})};return{};}
const baseProps={customer:{id:101,business_name:'合成客户'},open:true,onSaved:()=>{},onClose:()=>{}};
const openScope=(app,name)=>{const row=app.all(n=>n.type==='article'&&app.text(n).includes(name))[0];const visit=n=>!n?[]:Array.isArray(n)?n.flatMap(visit):typeof n!=='object'?[]:[n,...visit(n.props?.children)];visit(row).find(n=>n.type==='Button'&&app.text(n)==='栏目').props.onClick();app.render();};
const preview=async app=>{await app.button('预览更改').props.onClick();await app.settle();};
const invite=async(app,name)=>{app.button('邀请成员').props.onClick();app.render();app.byLabel(`邀请${name}`).props.onChange({target:{checked:true}});app.render();app.button('加入 1 人').props.onClick();app.render();};

test('missing or revoked effective metadata denies every module, finance and independent action',()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});const {customerPermissions,customerCanReadTab}=app.load('lib/customer-permissions.ts');
 for(const customer of [null,{}, {effective_permissions:{modules:{basic:{read:true,write:true}},finance_access:'profit'}},{effective_permissions:permission('none','profit',{can_delete:true,can_export:true,can_manage_access:true})},{effective_permissions:permission('read_write','profit',{invitation_status:'pending_review',invitation_source:'legacy',can_delete:true})}]){const p=customerPermissions(customer);assert.equal(p.finance_access,'none');assert.equal(p.can_export,false);assert.equal(customerCanReadTab(customer,'payments'),false);assert.equal(p.modules.basic.read,false);}
 const readOnly={effective_permissions:permission('read_only','status')};assert.equal(customerPermissions(readOnly).modules.basic.write,false);assert.equal(customerCanReadTab(readOnly,'payments'),true);assert.equal(customerCanReadTab(readOnly,'logs'),false);
});
test('ordinary admin cannot gain company finance through legacy role configuration; partner portal stays available',()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});const {canAccessPage,normalizeRolePermissions}=app.load('lib/permissions.ts');
 for(const role of ['admin','finance','sales','ops','design'])for(const path of ['/finance','/commissions','/payroll','/management-decisions','/permissions','/employees','/settings'])assert.equal(canAccessPage(role,path),false,`${role} ${path}`);
 assert.equal(canAccessPage('sales_partner','/partner-portal'),true);assert.equal(canAccessPage('super_admin','/finance'),true);
 const roles=normalizeRolePermissions({admin:{pages:['/finance','/customers'],sensitiveFields:{viewFinance:true}}});assert.equal(roles.admin.sensitiveFields.viewFinance,false);assert.equal(roles.admin.pages.includes('/finance'),false);assert.equal(roles.admin.pages.includes('/settings/deduction'),false);
});
test('normal customer edit excludes private note/access grants and cannot transfer responsibility',()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});const {editableCustomerPayload}=app.load('lib/customer-permissions.ts');const output=editableCustomerPayload({business_name:'合成',notes:'团队',sales_person:'甲',sales_employee_id:2,private_notes:'机密',effective_permissions:{},members:[],access_level:'read_write'},false);
 assert.deepEqual(JSON.parse(JSON.stringify(output)),{business_name:'合成'});
});
test('member list shows only invitations and owner; candidate employees appear only in the invite picker',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',baseProps,accessResponse);app.render();await app.settle();
 assert.equal(app.byLabel('邀请设计乙'),undefined);assert.equal(app.all(n=>n.type==='article').length,1);assert.match(app.text(app.tree()),/销售甲/);assert.equal(app.byLabel('搜索可邀请员工'),undefined);assert.equal(app.button('预览更改').props.disabled,true);
 app.button('邀请成员').props.onClick();app.render();assert.ok(app.byLabel('邀请设计乙'));assert.equal(app.byLabel('邀请老板'),undefined);assert.equal(app.byLabel('邀请销售甲'),undefined);
});
test('multi-select invitations default to basic and deals only; preview is required and uses the real server contract',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',baseProps,accessResponse);app.render();await app.settle();app.button('邀请成员').props.onClick();app.render();for(const name of ['设计乙','管理员丙'])app.byLabel(`邀请${name}`).props.onChange({target:{checked:true}});app.render();app.button('加入 2 人').props.onClick();app.render();assert.equal(app.button('确认保存协作'),undefined);await preview(app);await app.button('确认保存协作').props.onClick();await app.settle();const data=app.requests.find(r=>r.method==='PUT').data;
 assert.equal(data.members.length,3);for(const row of data.members.filter(r=>r.employee_id!==2)){assert.equal(row.access_level,'read_only');assert.deepEqual(JSON.parse(JSON.stringify(row.scopes)),scopes);assert.equal(row.finance_access,'none');assert.equal(row.can_delete,false);assert.equal(row.can_export,false);assert.equal(row.can_reassign,false);assert.equal(Object.hasOwn(row,'invitation_status'),false);}
 assert.equal(app.requests.filter(r=>r.url.endsWith('/preview')).length,2);
});
test('revoking an active invitation removes it from single-customer save and previews no access',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',baseProps,accessResponse);app.render();await app.settle();app.byLabel('撤销销售甲邀请').props.onClick();app.render();await preview(app);assert.equal(app.requests.find(r=>r.url.endsWith('/preview')).data.access_level,'none');await app.button('确认保存协作').props.onClick();await app.settle();assert.deepEqual(JSON.parse(JSON.stringify(app.requests.find(r=>r.method==='PUT').data.members)),[]);
});
test('a legacy confirmation uses a new basic/deals invitation and cannot resurrect previous finance',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',baseProps,accessResponse);app.render();await app.settle();assert.equal(app.all(n=>n.type==='article').length,1);app.byLabel('确认旧授权管理员丙').props.onChange({target:{checked:true}});app.render();app.button('确认邀请 1 人').props.onClick();app.render();await preview(app);await app.button('确认保存协作').props.onClick();await app.settle();const row=app.requests.find(r=>r.method==='PUT').data.members.find(r=>r.employee_id===4);assert.deepEqual(JSON.parse(JSON.stringify(row.scopes)),scopes);assert.equal(row.finance_access,'none');
});
test('module checkboxes and write levels are independent; changing a draft invalidates permission preview',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',baseProps,accessResponse);app.render();await app.settle();await invite(app,'设计乙');assert.equal(app.byLabel('设计乙成交记录权限').props.options.length,1);app.byLabel('设计乙跟进记录可见').props.onChange({target:{checked:true}});app.render();app.byLabel('设计乙跟进记录权限').props.onChange('read_write');app.render();await preview(app);assert.ok(app.button('确认保存协作'));assert.equal(app.byLabel('设计乙成交记录可见'),undefined);app.button('返回调整').props.onClick();app.render();app.byLabel('设计乙成交记录可见').props.onChange({target:{checked:false}});app.render();assert.equal(app.button('确认保存协作'),undefined);assert.equal(app.byLabel('设计乙独立财务权限'),undefined);await preview(app);await app.button('确认保存协作').props.onClick();await app.settle();const row=app.requests.find(r=>r.method==='PUT').data.members.find(r=>r.employee_id===3);assert.equal(row.scopes.followups,'read_write');assert.equal(row.scopes.deals,'none');assert.equal(row.scopes.contacts,'none');assert.equal(row.finance_access,'none');
});
test('a stale in-flight preview cannot authorize saving a modified invitation',async()=>{
 let done;const app=fixture('components/CustomerAccessPanel.tsx',baseProps,r=>r.url.endsWith('/preview')?new Promise(resolve=>{done=resolve;}):accessResponse(r));app.render();await app.settle();openScope(app,'销售甲');app.byLabel('销售甲基础信息权限').props.onChange('read_write');app.render();const pending=app.button('预览更改').props.onClick();app.byLabel('销售甲成交记录可见').props.onChange({target:{checked:false}});app.render();done({effective_permissions:permission('read_write')});await pending;await app.settle();assert.equal(app.byLabel('保存前权限预览'),undefined);assert.equal(app.button('确认保存协作'),undefined);
});
test('bulk revoke previews each customer and uses remove without touching unrelated members',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,customerIds:[101,102]},accessResponse);app.render();await app.settle();app.byLabel('撤销销售甲邀请').props.onClick();app.render();await preview(app);assert.equal(app.requests.filter(r=>r.url.endsWith('/preview')).length,2);await app.button('确认保存协作').props.onClick();await app.settle();const r=app.requests.find(r=>r.url.endsWith('/bulk-update'));assert.equal(r.data.operation,'remove');assert.equal(r.data.members[0].employee_id,2);assert.deepEqual(r.data.customer_ids,[101,102]);
});
test('independent financial authorization has its own endpoint and explicit confirmation',async()=>{
 const app=fixture('components/CustomerFinanceAccessPanel.tsx',baseProps,accessResponse);app.render();await app.settle();app.byLabel('销售甲独立财务权限').props.onChange('receipts');app.render();assert.equal(app.button('保存财务授权').props.disabled,true);app.byLabel('确认独立财务授权').props.onChange({target:{checked:true}});app.render();await app.button('保存财务授权').props.onClick();await app.settle();const request=app.requests.find(r=>r.method==='PUT');assert.equal(request.url,'/api/v1/entities/customers/101/access/2/finance');assert.deepEqual(JSON.parse(JSON.stringify(request.data)),{finance_access:'receipts'});
});
test('basic plus deals invitation exposes exactly those tabs and rejects every cross-module deep link',()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});const {customerVisibleTabs,customerCanReadTab,customerDefaultTab}=app.load('lib/customer-permissions.ts');const customer={effective_permissions:member(2).effective_permissions};assert.deepEqual(JSON.parse(JSON.stringify(customerVisibleTabs(customer).map(row=>row.value))),['info','deals']);assert.equal(customerDefaultTab(customer),'info');for(const tab of ['overview','timeline','payments','renewals','opportunities','contacts','followups','subscriptions','materials','ai_copy','media','logs'])assert.equal(customerCanReadTab(customer,tab),false,tab);
});
test('owner private note never goes through customer/team write endpoints',async()=>{
 const app=fixture('components/CustomerPrivateNote.tsx',{customerId:101},r=>r.method==='GET'?{private_notes:'旧私密备注'}:{});app.render();await app.settle();const area=app.all(n=>n.type==='Textarea')[0];area.props.onChange({target:{value:'新的私密备注'}});app.render();await app.button('保存私密备注').props.onClick();await app.settle();const request=app.requests.find(r=>r.method==='PUT');assert.equal(request.url,'/api/v1/entities/customers/101/private-note');assert.deepEqual(JSON.parse(JSON.stringify(request.data)),{private_notes:'新的私密备注'});assert.ok(app.requests.every(r=>r.url.endsWith('/private-note')));
});
test('status view never renders received monetary data; receipt view omits seeded fee/cost/profit and shows refunds',()=>{
 const props={level:'status',status:{payment_count:2,last_payment_date:'2026-10-12',has_outstanding:true},payments:[{id:1,product_name:'服务A',amount_paid:456.78,outstanding_amount:23.45,currency:'USD',payment_date:'2026-10-12',stripe_fee:111.11,cost:222.22,profit:333.33}],refunds:[{id:9,refund_date:'2026-10-13',refund_amount:12.34,currency:'USD',status:'completed'}]};const app=fixture('components/CustomerFinanceSummary.tsx',props);app.render();assert.doesNotMatch(app.text(app.tree()),/456|23.45|111|222|333|12.34/);app.render({...props,level:'receipts'});assert.match(app.text(app.tree()),/456.78/);assert.match(app.text(app.tree()),/12.34/);assert.match(app.text(app.tree()),/已退款/);assert.doesNotMatch(app.text(app.tree()),/111.11|222.22|333.33/);app.render({...props,level:'none'});assert.equal(app.tree(),null);
});
test('failed server-authorized export never falls back to cached customer rows',async()=>{
 const app=fixture('components/ExportButton.tsx',{data:[{notes:'cached secret'}],columns:[],filename:'qa',prepareData:async()=>{throw new Error('403');}});app.render();app.all(n=>n.type==='DropdownMenuItem')[0].props.onClick();await app.settle();assert.equal(app.exports.length,0);assert.ok(app.notices.includes('导出失败，请重试'));
});

 test('employee landing routes do not send nonowners into company finance or the owner dashboard',()=>{const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});const nav=app.load('lib/app-navigation.ts');for(const role of ['admin','finance']){assert.equal(nav.getDesktopLoginPath(role),'/customers');assert.equal(nav.getRoleTodayPath(role),'/customers');}assert.equal(nav.getRolePendingPath('finance'),'/customers');assert.equal(nav.getDesktopLoginPath('sales_partner'),'/partner-portal');assert.equal(nav.getRoleTodayPath('super_admin'),'/');});

test('the real customer list query retains every authorized module shell and omits hidden basic data',()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});
 const query=app.load('lib/customer-permissions.ts').CUSTOMER_SHELL_LIST_QUERY;
 const result=spawnSync(process.env.T24_TEST_PYTHON||'python3',['-c',String.raw`
import asyncio,json,sys
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from core.database import Base,get_db
from dependencies.auth import get_current_user
from models.customers import Customers
from models.employees import Employees
from models.customer_access_grants import CustomerAccessGrant
from routers.customers import router
from schemas.auth import UserResponse
query=json.load(sys.stdin)
async def main():
 engine=create_async_engine('sqlite+aiosqlite:///:memory:')
 async with engine.begin() as conn:
  await conn.run_sync(Base.metadata.create_all)
  await conn.execute(text('CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY,value_json TEXT)'))
 async with async_sessionmaker(engine,expire_on_commit=False)() as db:
  db.add(Employees(id=2,user_id='2',name='Member',role='ops',status='active'))
  for i,module in enumerate(('materials','delivery','followups','finance'),1):
   db.add(Customers(id=i,business_name='Shell '+str(i),contact_name='HIDDEN CONTACT',phone='+12125550123'))
   db.add(CustomerAccessGrant(customer_id=i,employee_id=2,access_level='read_only',invitation_source='owner_invitation',invitation_status='active',scopes={key:('read_only' if key==module else 'none') for key in ('basic','contacts','followups','opportunities','delivery','renewals','deals','materials')},finance_access='status' if module=='finance' else 'none'))
  db.add(Customers(id=5,business_name='Denied',contact_name='HIDDEN CONTACT',phone='+12125550123'))
  db.add(CustomerAccessGrant(customer_id=5,employee_id=2,access_level='none'))
  await db.commit()
  app=FastAPI();app.include_router(router)
  async def session():yield db
  app.dependency_overrides[get_db]=session
  app.dependency_overrides[get_current_user]=lambda:UserResponse(id='2',role='ops',name='Member',email='synthetic@example.invalid')
  async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
   response=await client.get('/api/v1/entities/customers',params=query)
   assert response.status_code==200,response.text
   body=response.json();assert body['total']==4,body
   assert [item['id'] for item in body['items']]==[4,3,2,1],body
   assert 'HIDDEN CONTACT' not in response.text,response.text
   assert '+12125550123' not in response.text,response.text
 await engine.dispose()
asyncio.run(main())
`],{cwd:backend,input:JSON.stringify(query),encoding:'utf8',env:{...process.env,APP_ENV:'test',DATABASE_URL:'sqlite+aiosqlite:///:memory:',PYTHONPATH:'.:..'}});
 assert.equal(result.status,0,`Real customer list rejected or hid a module-only grant. ${result.stderr||result.error||''}`);
});

test('business record deletion permission never grants whole-customer deletion to an ordinary employee',()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});
 const {customerCanDeleteCustomer}=app.load('lib/customer-permissions.ts');
 const customer={effective_permissions:permission('read_write','profit',{can_delete:true})};
 for(const role of ['admin','finance','sales','ops','design'])assert.equal(customerCanDeleteCustomer(customer,role),false,role);
 assert.equal(customerCanDeleteCustomer(customer,'super_admin'),true);
 assert.equal(customerCanDeleteCustomer({effective_permissions:permission('none','none')},'super_admin'),false);
});

test('the rendered invited navigation omits 360, timeline, finance, contacts and renewals',()=>{
 const app=fixture('components/CustomerCollaborationTabs.tsx',{customer:{effective_permissions:member(2).effective_permissions}});app.render();assert.equal(app.all(node=>node.type==='TabsTrigger').length,2);assert.match(app.text(app.tree()),/基础信息/);assert.match(app.text(app.tree()),/成交记录/);assert.doesNotMatch(app.text(app.tree()),/360|时间线|财务|续费|联系人|跟进|商机/);
});
test('deal-only read renderer ignores injected financial and private fields unless separately authorized',()=>{
 const props={customer:{effective_permissions:member(2).effective_permissions},deals:[{id:9,package_name:'基础服务',product_type:'website',billing_cycle:'monthly',deal_date:'2026-10-14',sales_name:'合成销售',deal_amount:777.88,is_paid:true,is_handed_over:true,notes:'PRIVATE_NOTE',source_payment_id:888,commission_amount:999}],classify:name=>({currentLabel:name}),productLabels:{website:'官网'},cycleLabels:{monthly:'月付'}};
 const app=fixture('components/CustomerDealRecords.tsx',props);app.render();assert.match(app.text(app.tree()),/基础服务|官网|合成销售/);assert.doesNotMatch(app.text(app.tree()),/777.88|付款|PRIVATE_NOTE|888|999/);app.render({...props,customer:{effective_permissions:{...member(2).effective_permissions,finance_access:'receipts'}}});assert.match(app.text(app.tree()),/777.88/);assert.match(app.text(app.tree()),/已付/);assert.doesNotMatch(app.text(app.tree()),/PRIVATE_NOTE|888|999/);app.render({...props,customer:{effective_permissions:permission('none')}});assert.equal(app.tree(),null);
});
test('bulk invitation can add an existing member to the other selected customers even with the same template',async()=>{
 const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,customerIds:[101,102]},r=>r.method==='GET'&&r.url.includes('/102/')?{...accessResponse(r),members:[]}:accessResponse(r));app.render();await app.settle();await invite(app,'销售甲');await preview(app);await app.button('确认保存协作').props.onClick();await app.settle();const request=app.requests.find(r=>r.url.endsWith('/bulk-update'));assert.equal(request.data.operation,'upsert');assert.deepEqual(request.data.customer_ids,[101,102]);assert.equal(request.data.members[0].employee_id,2);assert.equal(request.data.members[0].finance_access,'none');
});

 test('new customers without an invitation are acknowledged as created and never opened automatically',()=>{const app=fixture('components/CustomerAccessPanel.tsx',{...baseProps,open:false});const {customerCreationFeedback,editableCustomerPayload}=app.load('lib/customer-permissions.ts');const result=customerCreationFeedback({id:99,effective_permissions:permission('none')});assert.equal(result.canOpen,false);assert.equal(result.message,'客户已创建，等待老板授权查看');assert.equal(customerCreationFeedback({effective_permissions:permission('read_only')}).canOpen,true);const data=editableCustomerPayload({business_name:'合成',notes:'historical owner note',private_notes:'private'},false,false);assert.deepEqual(JSON.parse(JSON.stringify(data)),{business_name:'合成'});assert.equal(editableCustomerPayload({notes:'owner preserved'},true,true).notes,'owner preserved');});
