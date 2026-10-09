import { expect, test, type Page } from '@playwright/test';
const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
if (!['127.0.0.1','localhost'].includes(new URL(base).hostname)) throw new Error('Local fixtures only');
async function seed(page: Page, total=0, failSecond=false) {
 const actor={id:11,name:'体验验收模拟账号',role:'admin',status:'active'};
 await page.addInitScript(actor=>{sessionStorage.setItem('emp_auth_token','mock');sessionStorage.setItem('token','mock');sessionStorage.setItem('emp_auth_data',JSON.stringify(actor));},actor);
 const reads:string[]=[];
 await page.route(/^https?:\/\/[^/]+\/api\//,async route=>{
  const req=route.request();const url=new URL(req.url());const path=url.pathname;
  if(req.method()!=='GET') return route.fulfill({status:409,json:{detail:'全局验收禁止业务写入'}});
  reads.push(req.url());
  if(path==='/api/config') return route.fulfill({json:{API_BASE_URL:base}});
  if(path.endsWith('/emp-auth/me')) return route.fulfill({json:actor});
  if(path.includes('/entities/tasks')) {
   const skip=Number(url.searchParams.get('skip')||0);const limit=Number(url.searchParams.get('limit')||500);
   if(failSecond&&skip>0) return route.fulfill({status:503,json:{detail:'第二页读取失败'}});
   return route.fulfill({json:{items:Array.from({length:Math.max(0,Math.min(limit,total-skip))},(_,i)=>({id:skip+i+1,title:'模拟任务 '+(skip+i+1),status:'pending',due_date:'2020-01-01'})),total}});
  }
  return route.fulfill({json:path.includes('app-config')?{items:{}}:{items:[],total:0}});
 });return reads;
}
test('首页完整分页超过500条',async({page})=>{
 const reads=await seed(page,705);await page.goto(base+'/apps');
 await expect(page.getByRole('group',{name:'逾期任务',exact:true})).toContainText('705');
 await expect(page.locator('.home-update-time')).toContainText('北京时间');
 expect(reads.some(url=>new URL(url).searchParams.get('skip')==='500')).toBe(true);
});
test('首页第二页失败显示未知并保留入口',async({page})=>{
 await seed(page,705,true);await page.goto(base+'/apps');
 await expect(page.getByRole('group',{name:'逾期任务',exact:true})).toContainText('待更新');
 await expect(page.getByRole('status').filter({hasText:'部分首页数字'})).toBeVisible();
});
test('完整集合拒绝变动总数、重复ID和缺页',async({page})=>{
 await seed(page);await page.goto(base+'/apps');
 const result=await page.evaluate(async()=>{
  const {readCompleteCollection}=await import('/src/lib/complete-collection.ts');
  const cases=[[{items:[{id:1}],total:2},{items:[{id:2}],total:3}],[{items:[{id:1}],total:2},{items:[{id:1}],total:2}],[{items:[{id:1}],total:2},{items:[],total:2}]];
  return Promise.all(cases.map(async pages=>{let index=0;try{await readCompleteCollection(async()=>({data:pages[index++]}),1);return false;}catch{return true;}}));
 });expect(result).toEqual([true,true,true]);
});
test('更多搜索、常用同步与320px布局',async({page})=>{
 await page.setViewportSize({width:320,height:844});await seed(page);await page.goto(base+'/more');
 await page.getByRole('textbox',{name:'搜索全部功能'}).fill('收入管理');
 await expect(page.getByRole('link',{name:/收入管理/})).toHaveCount(1);
 await page.getByRole('button',{name:'编辑常用',exact:true}).click();
 await page.getByRole('button',{name:'添加常用：收入管理',exact:true}).click();
 await expect(page.getByRole('button',{name:'移除常用：收入管理',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.getByRole('navigation',{name:'手机主导航'}).getByRole('button',{name:'首页',exact:true}).click();
 await expect(page.getByRole('region',{name:'个人常用功能'}).getByRole('button',{name:/收入管理/})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('新版本保留未保存输入，返回取消离开',async({page})=>{
 await page.setViewportSize({width:390,height:844});await seed(page);await page.route('**/app-version.json',route=>route.fulfill({json:{version:'abcdefabcdef'}}));
 await page.goto(base+'/apps');await page.goto(base+'/tasks');await page.getByRole('button',{name:'新建任务',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.locator('input').first().fill('未保存的模拟任务');
 const applied = await page.evaluate(async () => (await import('/src/lib/app-version.ts')).applyAppUpdate());
 expect(applied).toBe(false);
 await expect(dialog.locator('input').first()).toHaveValue('未保存的模拟任务');
 let discardPrompts=0;page.once('dialog',async d=>{discardPrompts+=1;await d.dismiss();});
 await page.evaluate(()=>history.back());
 await expect.poll(()=>discardPrompts).toBe(1);
 await expect(page).toHaveURL(/\/tasks$/);
 // Closing the editor is cancellable and must not discard input.
 page.once('dialog',d=>d.dismiss());await dialog.getByRole('button',{name:'取消',exact:true}).click();
 await expect(dialog.locator('input').first()).toHaveValue('未保存的模拟任务');
});
