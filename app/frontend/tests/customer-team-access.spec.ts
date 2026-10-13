import {expect,test,type Page,type Route} from '@playwright/test';
const baseUrl=process.env.T24_WORKBENCH_BASE_URL||'http://127.0.0.1:5173';
const modules=['basic','followups','delivery','materials'];
const permission=(owner=false,level='read_write')=>({access_level:level,modules:Object.fromEntries(modules.map(key=>[key,{read:true,write:level==='read_write'}])),finance_access:owner?'profit':'none',can_delete:owner,can_export:owner,can_reassign:owner,can_manage_access:owner,reveal_secrets:owner,explicit:!owner,sources:[{code:owner?'owner':'explicit',label:owner?'老板完整权限':'老板单独授权'}]});
const employees=[{id:31,name:'Sales Owner',role:'sales',status:'active'},{id:41,name:'Operations Member',role:'ops',status:'active'}];
const customerRows=[{id:101,customer_code:'T24-101',business_name:'Alpha Cafe',contact_name:'Amy',phone:'+1 (212) 555 0101',status:'following',level:'normal',industry:'restaurant',state:'CA',sales_person:'Sales Owner',sales_employee_id:31},{id:102,customer_code:'T24-102',business_name:'Beta Spa',contact_name:'Beth',phone:'+1 (212) 555 0102',status:'following',level:'normal',industry:'spa',state:'NV',sales_person:'Sales Owner',sales_employee_id:31}];
const json=(route:Route,data:unknown)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
async function mock(page:Page,payloads:unknown[],role='super_admin'){
 const employee={id:role==='sales'?99:1,name:role==='sales'?'Invited Sales':'Owner',role,status:'active'};
 const rows=customerRows.map(row=>({...row,effective_permissions:permission(role==='super_admin',role==='sales'?'read_only':'read_write')}));
 await page.addInitScript(({employee})=>{localStorage.setItem('emp_auth_token','synthetic-permission-test');localStorage.setItem('token','synthetic-permission-test');localStorage.setItem('emp_auth_data',JSON.stringify(employee));},{employee});
 await page.route(/^https?:\/\/[^/]+\/api\//,async route=>{const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/emp-auth/me'))return json(route,employee);
  if(path.includes('/app-config'))return json(route,{items:{}});
  if(path.endsWith('/employees/directory'))return json(route,{items:employees,total:2});
  if(path.endsWith('/customers/access/bulk-update')||path.endsWith('/customers/101/access')&&route.request().method()==='PUT'){payloads.push(route.request().postDataJSON());return json(route,{customer_count:2,member_count:1,updated_grants:2});}
  if(path.endsWith('/customers/101/access'))return json(route,{customer_id:101,members:[{...employees[0],employee_id:31,access_level:'read_write',scopes:{},finance_access:'none',can_delete:false,can_export:false,can_reassign:false,explicit:false,effective_permissions:permission()}],eligible_employees:employees});
  if(path==='/api/v1/entities/customers'||path==='/api/v1/entities/customers/all')return json(route,{items:rows,total:2});
  if(path.includes('/product-plans'))return json(route,{business_lines:[],products:[],plans:[]});
  if(path.endsWith('/private-note'))return json(route,{private_notes:null});
  if(path.endsWith('/finance-access-data'))return json(route,{finance_access:'profit',status:{payment_count:0,last_payment_date:null,has_outstanding:false},payments:[],refunds:[],expenses:[],deduction_rates:{}});
  if(path.includes('/entities/'))return json(route,{items:[],total:0});return json(route,{});
 });
}
test('老板批量授权只读不会同时开放财务或独立操作',async({page})=>{const payloads:any[]=[];await mock(page,payloads);await page.setViewportSize({width:1440,height:900});await page.goto(`${baseUrl}/customers`);await page.getByRole('checkbox',{name:'选择客户 Alpha Cafe'}).check();await page.getByRole('checkbox',{name:'选择客户 Beta Spa'}).check();await page.getByRole('button',{name:'批量设置访问权限'}).click();const dialog=page.getByRole('dialog');await dialog.getByLabel('Operations Member访问权限').selectOption('read_only');await dialog.getByRole('button',{name:'保存访问权限'}).click();expect(payloads).toHaveLength(1);expect(payloads[0]).toMatchObject({customer_ids:[101,102],operation:'upsert',members:[{employee_id:41,access_level:'read_only',finance_access:'none',can_export:false,can_delete:false,can_reassign:false}]});});
test('老板可将负责人明确设不可见而不是删除授权后回到继承',async({page})=>{const payloads:any[]=[];await mock(page,payloads);await page.goto(`${baseUrl}/customers`);await page.getByRole('button',{name:'更多客户操作：Alpha Cafe'}).click();await page.getByRole('menuitem',{name:'访问权限',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByLabel('Sales Owner访问权限').selectOption('none');await dialog.getByRole('button',{name:'保存访问权限'}).click();expect(payloads[0].members).toEqual([{employee_id:31,access_level:'none',scopes:{basic:'none',followups:'none',delivery:'none',materials:'none'},finance_access:'none',can_export:false,can_delete:false,can_reassign:false}]);});
test('受邀销售可以看非本人客户但没有只读之外的操作',async({page})=>{await mock(page,[],'sales');await page.goto(`${baseUrl}/customers`);await expect(page.getByText('Alpha Cafe',{exact:true}).first()).toBeVisible();await expect(page.getByRole('button',{name:'更多客户操作：Alpha Cafe'})).toHaveCount(0);await expect(page.getByRole('button',{name:'批量设置访问权限'})).toHaveCount(0);await expect(page.getByRole('button',{name:'导出',exact:true})).toHaveCount(0);});
