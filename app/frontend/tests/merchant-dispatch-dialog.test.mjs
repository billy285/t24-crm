import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

const file = resolve(dirname(fileURLToPath(import.meta.url)), '../src/components/MerchantDispatchDialog.tsx');
const flush = async () => { for (let n=0;n<5;n++) await new Promise(done=>setImmediate(done)); };
const deferred = () => { let resolve; const promise=new Promise(done=>{resolve=done;}); return {promise,resolve}; };
const text = node => node==null||typeof node==='boolean'?'':typeof node!=='object'?String(node):Array.isArray(node)?node.map(text).join(''):text(node.props?.children);
const nodes = node => !node||typeof node!=='object'?[]:Array.isArray(node)?node.flatMap(nodes):[node,...nodes(node.props?.children)];
const preview = {target_date:'2026-11-11',plan_sha256:'a'.repeat(64),assigned_count:1,unassigned_count:0,policy:'test',assignments:[{merchant_id:1,business_name:'Synthetic',sales_employee_id:21,salesperson:'A',timezone_group:'eastern',queue_reason:'建议联系时段内',completeness:3,quality_status:'pending'}],unassigned:[],employees:[{sales_employee_id:21,salesperson:'A',quota:100,today_tasks:0,existing_pending_load:0,reserved_existing:0,remaining:100,assigned_count:1,timezones:{eastern:1}}]};

function fixture(handler) {
  const slots=[],effects=[],requests=[],changes=[];let cursor=0,tree,actor={employee:{id:1},role:'admin'},assigned=0,unmounted=false,lateWrites=0;
  let props={open:true,merchantIds:[1],assignees:[{id:21,name:'A'}],onOpenChange:value=>changes.push(value),onAssigned:()=>assigned++};
  const react={
    useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:initial};return[slots[i].value,value=>{if(unmounted)lateWrites++;slots[i].value=typeof value==='function'?value(slots[i].value):value;}];},
    useRef(initial){const i=cursor++;if(!slots[i])slots[i]={value:{current:initial}};return slots[i].value;},
    useEffect(callback,deps){const i=cursor++,old=slots[i];if(old&&deps.every((v,n)=>Object.is(v,old.deps[n])))return;slots[i]={deps};effects.push(()=>{old?.cleanup?.();slots[i].cleanup=callback();});},
  };
  const mod={exports:{}};const require=name=>{
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
    if(name==='@/lib/role-context')return{useRole:()=>actor};
    if(name==='@/lib/tokenStore')return{invokeWithAuth:request=>{requests.push(request);return handler(request);}};
    if(name==='@/components/ui/button')return{Button:'button'};
    return new Proxy({},{get:(_target,key)=>String(key)});
  };
  const code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  vm.runInNewContext(`(function(require,module,exports){${code}\n})`,{console})(require,mod,mod.exports);
  const render=(next={},nextActor)=>{props={...props,...next};if(nextActor)actor=nextActor;cursor=0;tree=mod.exports.default(props);while(effects.length)effects.shift()();return tree;};
  const button=label=>{const node=nodes(tree).find(n=>n.type==='button'&&text(n)===label);assert.ok(node,label);return node;};
  return{render,button,requests,changes,assigned:()=>assigned,content:()=>text(tree),lateWrites:()=>lateWrites,
    choose(){nodes(tree).find(n=>n.type==='input').props.onChange({target:{checked:true}});render();},
    unmount(){unmounted=true;for(const item of slots)item?.cleanup?.();}};
}

test('preview does not assign; confirm uses exact preview hash once and 409 removes stale plan',async()=>{
  const app=fixture(async request=>{
    if(request.url.endsWith('/preview'))return{data:preview};
    throw{response:{data:{detail:'配额已变化，请重新预览'}}};
  });
  app.render();assert.equal(app.requests.length,0);app.choose();app.button('生成派单预览').props.onClick();await flush();app.render();
  assert.equal(app.assigned(),0);const confirm=app.button('确认分配1条并创建今日任务');confirm.props.onClick();confirm.props.onClick();await flush();app.render();
  const requests=app.requests.filter(r=>r.url.endsWith('/confirm'));assert.equal(requests.length,1);
  assert.equal(requests[0].data.plan_sha256,preview.plan_sha256);assert.deepEqual([...requests[0].data.merchant_ids],[1]);
  assert.match(app.content(),/配额已变化，请重新预览/);assert.equal(app.button('确认分配0条并创建今日任务').props.disabled,true);
  assert.equal(app.assigned(),0);assert.deepEqual(app.changes,[]);
});

test('late successful confirm after account or selected-merchant change cannot update current UI',async()=>{
  for(const change of ['account','selection']){
    const pending=deferred();const app=fixture(request=>request.url.endsWith('/preview')?Promise.resolve({data:preview}):pending.promise);
    app.render();app.choose();app.button('生成派单预览').props.onClick();await flush();app.render();app.button('确认分配1条并创建今日任务').props.onClick();
    if(change==='account')app.render({}, {employee:{id:2},role:'admin'});else app.render({merchantIds:[2]});
    pending.resolve({data:{assigned_count:1}});await flush();app.render();
    assert.equal(app.assigned(),0);assert.deepEqual(app.changes,[]);assert.equal(app.button('确认分配0条并创建今日任务').props.disabled,true);
  }
});

test('unmount while confirming does not trigger callbacks or late state writes',async()=>{
  const pending=deferred();const app=fixture(request=>request.url.endsWith('/preview')?Promise.resolve({data:preview}):pending.promise);
  app.render();app.choose();app.button('生成派单预览').props.onClick();await flush();app.render();app.button('确认分配1条并创建今日任务').props.onClick();app.unmount();
  pending.resolve({data:{assigned_count:1}});await flush();assert.equal(app.assigned(),0);assert.deepEqual(app.changes,[]);assert.equal(app.lateWrites(),0);
});
