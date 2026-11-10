import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const jsx = (type, props) => ({type, props});
function load(file, react = {}) {
  const module = {exports:{}};
  const require = name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return {jsx,jsxs:jsx};
    if (name === './app-config') return {readCachedAppConfig: (_key, fallback) => fallback};
    if (name === '@/lib/dict-config') return load('lib/dict-config.ts', react);
    return new Proxy({}, {get: (_target, key) => String(key)});
  };
  const compiled = ts.transpileModule(readFileSync(resolve(root,file),'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  vm.runInNewContext(`(function(require,module,exports){${compiled}\n})`, {console,Date,Math,URLSearchParams})(require,module,module.exports);
  return module.exports;
}
const {visibleCustomerColumns,currentPagePreview,customerAddressLines} = load('lib/customer-directory-presentation.ts');
test('customer identity stays visible even when all optional columns were hidden in persisted settings', () => {
  assert.equal(JSON.stringify(visibleCustomerColumns([],['business_name','phone'],['phone'])), '["business_name"]');
  assert.equal(JSON.stringify(visibleCustomerColumns(['phone','phone','removed'],['business_name','phone'],[])), '["business_name","phone"]');
});
test('preview cannot retain a customer from another page', () => {
  const page = [{id:21},{id:22}];
  assert.equal(currentPagePreview(page,1), page[0]);
  assert.equal(currentPagePreview(page,22), page[1]);
  assert.equal(currentPagePreview([],22), undefined);
});
test('address presentation separates known trailing region while retaining postal code and original data', () => {
  const customer = {address:'40919 Fremont Blvd #6, Fremont, CA 94538, USA',city:'Fremont',state:'CA',country:'US'};
  const before = JSON.stringify(customer);
  const lines = customerAddressLines(customer,'California','美国');
  assert.equal(lines.street,'40919 Fremont Blvd #6');
  assert.equal(lines.region,'Fremont, California, 美国, 94538');
  assert.equal(JSON.stringify(customer),before);
  assert.equal(customerAddressLines({address:'Unknown Market, Near Entrance',city:'Fremont',country:'US'},'', '美国').street,'Unknown Market, Near Entrance');
});
test('password setup status uses only the explicit API boolean', () => {
  const {employeePasswordState} = load('lib/employee-account-presentation.ts');
  assert.equal(employeePasswordState({login_username:'Alice',status:'active'}).label,'密码状态待确认');
  assert.equal(employeePasswordState({has_login_password:true}).label,'密码已设置');
  assert.equal(employeePasswordState({has_login_password:false}).label,'密码未设置');
});
function dictionaryFixture(initial) {
  const state=[];let cursor=0,value=initial,tree;
  const react={useState(initial){const i=cursor++;if(!(i in state))state[i]=typeof initial==='function'?initial():initial;return[state[i], next=>{state[i]=typeof next==='function'?next(state[i]):next;}];}};
  const Component=load('components/SettingsDictionaryEditor.tsx',react).default;
  const render=()=>{cursor=0;tree=Component({label:'行业类型',value,onChange:next=>{value=next;}});};
  const all=(node,predicate)=>!node?[]:Array.isArray(node)?node.flatMap(item=>all(item,predicate)):typeof node!=='object'?[]:[...(predicate(node)?[node]:[]),...all(node.props?.children,predicate)];
  return {render,value:()=>value,byLabel:label=>all(tree,node=>node.props?.['aria-label']===label)[0],button:label=>all(tree,node=>node.type==='Button'&&node.props.children===label)[0]};
}
test('friendly dictionary edits labels without changing identifiers or deleting blank drafts', () => {
  const app=dictionaryFixture('nail:美甲,beauty:美容');app.render();
  app.byLabel('行业类型：美甲').props.onChange({target:{value:'美甲护理'}});app.render();
  assert.equal(app.value(),'nail:美甲护理,beauty:美容');
  app.byLabel('行业类型：美甲护理').props.onChange({target:{value:''}});app.render();
  assert.equal(app.value(),'nail:美甲护理,beauty:美容');
  app.byLabel('行业类型：美甲护理').props.onBlur({target:{value:''}});app.render();
  assert.equal(app.value(),'nail:美甲护理,beauty:美容');
  app.byLabel('新增行业类型').props.onChange({target:{value:'头疗'}});app.render();
  app.button('添加选项').props.onClick();app.render();
  assert.match(app.value(),/^nail:美甲护理,beauty:美容,custom_.*:头疗$/);
});


test('finance registration filters search the server and reset pagination while keeping status scope', () => {
  const {financeEntryListQuery,changeFinanceEntryListFilters}=load('lib/finance-entry-list-filters.ts');
  const current=new URLSearchParams('status=submitted&page=9&q=old&kind=manual_receipt');
  const next=changeFinanceEntryListFilters(current,{q:'  Receipt 123  ',start:'2026-11-11',end:'2026-11-11'});
  assert.equal(next.get('page'),'1');assert.equal(next.get('status'),'submitted');assert.equal(next.get('q'),'Receipt 123');
  assert.equal(current.get('q'),'old');
  const request=financeEntryListQuery({page:3,limit:20,status:'submitted',q:next.get('q'),kind:'manual_receipt',start:next.get('start'),end:next.get('end')});
  assert.equal(request.get('skip'),'40');assert.equal(request.get('q'),'Receipt 123');assert.equal(request.get('kind'),'manual_receipt');assert.equal(request.get('end'),'2026-11-11');
  const cleared=changeFinanceEntryListFilters(next,{q:'',kind:'',start:'',end:''});
  assert.equal(cleared.toString(),'status=submitted&page=1');
});


test('settings save feedback waits for completion and never announces failed saves as successful', async () => {
  const {trackSettingsSave}=load('lib/settings-save-feedback.ts');
  const pending=[];let finish;
  const gate=new Promise(resolve=>{finish=resolve;});
  const run=trackSettingsSave('公司信息',()=>gate,result=>pending.push(result.phase));
  assert.equal(pending.join(','),'saving');
  finish();assert.equal(await run,true);
  assert.equal(pending.join(','),'saving,success');
  const failed=[];
  const result=await trackSettingsSave('提醒设置',async()=>{throw new Error('Synthetic rejected save');},feedback=>failed.push(feedback.phase));
  assert.equal(result,false);assert.equal(failed.join(','),'saving,error');
});
