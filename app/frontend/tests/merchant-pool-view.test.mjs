import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

const src=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const flush=async()=>{for(let n=0;n<4;n++)await new Promise(done=>setImmediate(done));};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const text=node=>node==null||typeof node==='boolean'?'':typeof node!=='object'?String(node):Array.isArray(node)?node.map(text).join(''):text(node.props?.children);
const nodes=node=>!node||typeof node!=='object'?[]:Array.isArray(node)?node.flatMap(nodes):[node,...nodes(node.props?.children)];
const stats={total:5274,pending:5069,converted:205,isolated:0,duplicates:0,archived:0};
function payload(zone='all',name){const east=zone==='eastern',total=east?3535:zone==='central'?152:5069;return{data:{items:[{id:east?2:1,business_name:name||(east?'合成东部商家':'合成中部商家'),phone:'+12125550123',country:'US',state:east?'NY':'IL',industry:'美业',data_source:'csv',pool_status:'pending',timezone: east?'America/New_York':'America/Chicago',timezone_group:east?'eastern':'central',collected_at:'2026-11-10T10:00:00Z',prospect_quality:{status:'pending',revision:0}}],total,industry_facets:[{value:'美业',label:'美业',count:total}],facet_total:total,quality_facets:{pending:total,valid:0,invalid_phone:0,not_target:0,closed:0}}};}

function fixture(handler,{mobile=false,batch=false}={}){
  const slots=[],effects=[],requests=[],toasts=[],listeners=new Map(),timers=new Map();let cursor=0,tree,timerId=0,actor={employee:{id:10},role:'sales_manager',isAdmin:false},unmounted=false,lateWrites=0;
  const react={
    useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:typeof initial==='function'?initial():initial};return[slots[i].value,value=>{if(unmounted)lateWrites++;slots[i].value=typeof value==='function'?value(slots[i].value):value;}];},
    useRef(initial){const i=cursor++;if(!slots[i])slots[i]={value:{current:initial}};return slots[i].value;},
    useEffect(callback,deps){const i=cursor++,old=slots[i];if(old&&deps&&deps.every((value,n)=>Object.is(value,old.deps?.[n])))return;slots[i]={deps};effects.push(()=>{old?.cleanup?.();slots[i].cleanup=callback();});},
  };
  const add=(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);};
  const remove=(name,fn)=>listeners.get(name)?.delete(fn);
  const win={location:{search:batch?'?batch_id=synthetic-current-view':''},history:{replaceState(){}},confirm:()=>true,addEventListener:add,removeEventListener:remove,setInterval:()=>++timerId,clearInterval(){},setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)};
  const document={visibilityState:'visible',addEventListener:add,removeEventListener:remove};
  const cache=new Map();
  const require=name=>{
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'};
    if(name==='react-router-dom')return{useNavigate:()=>()=>{}};
    if(name==='@/lib/role-context')return{useRole:()=>actor};
    if(name==='@/hooks/use-mobile')return{useIsMobile:()=>mobile};
    if(name==='@/lib/tokenStore')return{invokeWithAuth:request=>{requests.push({...request,actorId:actor.employee.id});return handler(request,actor);}};
    if(name==='sonner')return{toast:{error:value=>toasts.push(value),success:value=>toasts.push(value)}};
    if(name==='@/lib/use-unsaved-changes')return{useUnsavedChanges:()=>({confirmDiscard:()=>true}),confirmDiscardAllChanges:()=>true};
    if(name==='@/lib/phone-format')return{formatPhoneNumber:value=>value||''};
    if(name==='@/lib/contact-timezone')return{contactTimezoneLabels:{eastern:'东部',central:'中部'},formatContactClock:()=>null,contactTimezoneBasisLabel:()=>'',contactTimezoneLabel:()=>''};
    if(name==='@/lib/use-auto-refresh')return load(resolve(src,'lib/use-auto-refresh.ts'));
    if(name==='./data-refresh')return{BUSINESS_DATA_REFRESH_EVENT:'t24:business-data-refresh'};
    if(name==='@/components/ui/button')return{Button:'button'};
    if(name==='@/components/ui/input')return{Input:'input'};
    if(name==='@/components/ui/native-select')return{NativeSelect:'select'};
    return new Proxy({},{get:(_target,key)=>String(key)});
  };
  function load(file){if(cache.has(file))return cache.get(file);const mod={exports:{}};const code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;vm.runInNewContext(`(function(require,module,exports){${code}\n})`,{console,window:win,document,URLSearchParams,Date})(require,mod,mod.exports);cache.set(file,mod.exports);return mod.exports;}
  const Component=load(resolve(src,'pages/MerchantPool.tsx')).default;
  const runEffects=()=>{while(effects.length)effects.shift()();};
  const render=({effects:run=true,account}={})=>{if(account)actor={...actor,employee:{id:account}};cursor=0;tree=Component();if(run)runEffects();return tree;};
  const find=predicate=>nodes(tree).find(predicate);
  const button=(label)=>{const node=find(n=>n.type==='button'&&(typeof label==='string'?text(n)===label:label.test(text(n))));assert.ok(node,`button ${label}`);return node;};
  const byLabel=label=>{const node=find(n=>n.props?.['aria-label']===label);assert.ok(node,`label ${label}`);return node;};
  return{render,runEffects,requests,toasts,button,byLabel,find,content:()=>text(tree),tree:()=>tree,
    async settle(){for(let n=0;n<4;n++){await flush();render();}},
    chooseZone(zone,{effects=true}={}){button(zone).props.onClick();render({effects});},
    select(label,value){byLabel(label).props.onChange(value);render();},
    focus(){for(const fn of [...(listeners.get('focus')||[])])fn();},
    timeouts(){for(const [id,fn]of [...timers]){timers.delete(id);fn();}},
    unmount(){unmounted=true;for(const item of slots)item?.cleanup?.();},lateWrites:()=>lateWrites,
  };
}
function handlerFor(list,statsHandler=()=>Promise.resolve({data:stats})){
  return(request,actor)=>{
    if(request.url==='/api/v1/merchant-pool/stats')return statsHandler(request);
    if(request.url.startsWith('/api/v1/merchant-pool?'))return list(new URL('http://local'+request.url).searchParams,actor);
    if(request.url==='/api/v1/sales-leads/assignees')return Promise.resolve({data:[{id:11,name:'合成销售'}]});
    assert.equal(request.method,'GET','no business write is allowed in this regression');return Promise.resolve({data:{items:[],total:0}});
  };
}
const listCalls=app=>app.requests.filter(r=>r.url.startsWith('/api/v1/merchant-pool?'));

for(const mobile of [false,true])test(`${mobile?'mobile':'desktop'}: failed new timezone hides previous rows/facets/selection; retry keeps current filters`,async()=>{
  let failed=true;const app=fixture(handlerFor(query=>query.get('timezone_group')==='eastern'&&failed?Promise.reject(mobile?new Error('Request timed out after 15000ms'):{response:{status:500,data:{detail:'synthetic failure'}}}):Promise.resolve(payload(query.get('timezone_group')||'all'))),{mobile,batch:mobile});
  app.render();await app.settle();app.chooseZone('中部');await app.settle();assert.match(app.content(),/合成中部商家/);assert.match(app.content(),/共 152 条/);
  app.byLabel('分配：合成中部商家').props.onClick();app.render();assert.match(app.content(),/跨页已选 1 家商家/);
  app.button(/^更多筛选/).props.onClick();app.render();app.select('筛选资料来源','csv');await app.settle();app.select('筛选商家行业','美业');await app.settle();app.select('筛选首拨核验','pending');await app.settle();
  app.chooseZone('东部',{effects:false});assert.doesNotMatch(app.content(),/合成中部商家|共 152 条|美业152|首拨核验 · 待核验 152/);app.runEffects();await app.settle();
  assert.match(app.content(),/当前筛选加载失败，请重新加载后再分配商家/);assert.match(app.content(),/当前筛选数量暂不可用/);assert.doesNotMatch(app.content(),/合成中部商家|共 152 条|当前筛选下没有商家|跨页已选/);if(!mobile)assert.match(app.content(),/未分配5069/);
  assert.equal(app.button('下一页').props.disabled,true);assert.equal(app.find(n=>n.props?.['aria-label']==='选择本页可操作商家')?.props.disabled??true,true);assert.equal(app.find(n=>n.type==='button'&&text(n)==='确认分配'),undefined);
  const query=new URL('http://local'+listCalls(app).at(-1).url).searchParams;assert.equal(query.get('timezone_group'),'eastern');assert.equal(query.get('source'),'csv');assert.equal(query.get('industry'),'美业');assert.equal(query.get('quality_status'),'pending');assert.equal(query.get('batch_id'),mobile?'synthetic-current-view':null);
  failed=false;app.button('重新加载').props.onClick();app.render();await app.settle();assert.match(app.content(),/合成东部商家/);assert.match(app.content(),/共 3535 条/);assert.doesNotMatch(app.content(),/合成中部商家|当前筛选加载失败/);assert.equal(listCalls(app).at(-1).url,listCalls(app).at(-2).url);
  assert.equal(app.requests.some(r=>r.method!=='GET'),false);
});

test('render-to-effect gap rejects an earlier successful response before the next request starts',async()=>{
  const old=deferred();const app=fixture(handlerFor(query=>query.get('timezone_group')==='central'?old.promise:Promise.resolve(payload(query.get('timezone_group')||'all'))));
  app.render();await app.settle();app.chooseZone('中部');app.chooseZone('东部',{effects:false});old.resolve(payload('central','迟到的中部商家'));await flush();app.render({effects:false});assert.doesNotMatch(app.content(),/迟到的中部商家|共 152 条/);assert.match(app.content(),/正在加载商家池/);app.runEffects();await app.settle();assert.match(app.content(),/合成东部商家/);assert.match(app.content(),/共 3535 条/);
});

for(const outcome of ['success','failure'])test(`late ${outcome} for an older view cannot replace a newer accepted view`,async()=>{
  const old=deferred();const app=fixture(handlerFor(query=>query.get('timezone_group')==='central'?old.promise:Promise.resolve(payload(query.get('timezone_group')||'all'))));app.render();await app.settle();app.chooseZone('中部');app.chooseZone('东部');await app.settle();
  if(outcome==='success')old.resolve(payload('central','过时中部结果'));else old.reject(new Error('late old view failure'));await app.settle();assert.match(app.content(),/合成东部商家/);assert.match(app.content(),/共 3535 条/);assert.doesNotMatch(app.content(),/过时中部结果|当前筛选加载失败|共 152 条/);
});

test('real useAutoRefresh focus uses the latest selected view before its callback effect updates',async()=>{
  const app=fixture(handlerFor(query=>Promise.resolve(payload(query.get('timezone_group')||'all'))));app.render();await app.settle();const previous=listCalls(app).length;app.chooseZone('东部',{effects:false});app.focus();
  assert.equal(new URL('http://local'+listCalls(app).at(-1).url).searchParams.get('timezone_group'),'eastern');app.runEffects();await app.settle();assert.ok(listCalls(app).slice(previous).every(r=>new URL('http://local'+r.url).searchParams.get('timezone_group')==='eastern'));assert.match(app.content(),/合成东部商家/);
});

test('stats-only failure keeps the valid list and does not report list/assignment failure',async()=>{
  let failStats=false;const app=fixture(handlerFor(()=>Promise.resolve(payload('eastern')),()=>failStats?Promise.reject(new Error('stats unavailable')):Promise.resolve({data:stats})));app.render();await app.settle();failStats=true;app.focus();await app.settle();assert.match(app.content(),/合成东部商家|共 3535 条/);assert.doesNotMatch(app.content(),/当前筛选加载失败|当前筛选数量暂不可用/);assert.match(app.content(),/未分配5069/);assert.match(app.toasts.at(-1),/全局统计加载失败，当前商家列表仍可查看/);assert.equal(app.byLabel('分配：合成东部商家').props.disabled,false);
});

test('page-two failure retries the same page instead of treating an unavailable count as zero',async()=>{
  let fail=true;const app=fixture(handlerFor(query=>query.get('skip')==='20'&&fail?Promise.reject(new Error('page timeout')):Promise.resolve(payload('central'))));app.render();await app.settle();app.button('下一页').props.onClick();app.render();await app.settle();assert.match(app.content(),/2\/—/);assert.equal(new URL('http://local'+listCalls(app).at(-1).url).searchParams.get('skip'),'20');fail=false;app.button('重新加载').props.onClick();app.render();await app.settle();assert.equal(new URL('http://local'+listCalls(app).at(-1).url).searchParams.get('skip'),'20');assert.match(app.content(),/显示 21–40 条 \/ 共 152 条/);
});

test('account change and unmount reject stale replies without leaking old rows or late state writes',async()=>{
  const old=deferred();const app=fixture(handlerFor((_q,actor)=>actor.employee.id===10?old.promise:Promise.resolve(payload('eastern','新账号商家'))));app.render();app.render({account:20});await app.settle();old.resolve(payload('central','旧账号商家'));await app.settle();assert.match(app.content(),/新账号商家/);assert.doesNotMatch(app.content(),/旧账号商家/);
  const pending=deferred();const removed=fixture(handlerFor(()=>pending.promise));removed.render();await flush();removed.render();removed.unmount();pending.resolve(payload());await flush();assert.equal(removed.lateWrites(),0);
});

test('focus and view effect share one pending current-view read instead of duplicating expensive requests',async()=>{
  const pending=deferred();const app=fixture(handlerFor(query=>query.get('timezone_group')==='eastern'?pending.promise:Promise.resolve(payload())));app.render();await app.settle();const before=listCalls(app).length;
  app.chooseZone('东部',{effects:false});app.focus();app.runEffects();app.render();assert.equal(listCalls(app).length,before+1);assert.doesNotMatch(app.content(),/合成中部商家/);pending.resolve(payload('eastern'));await app.settle();assert.match(app.content(),/合成东部商家/);assert.match(app.content(),/共 3535 条/);
});

test('returning to a previous filter starts a new generation instead of sharing its invalidated pending read',async()=>{
  const previous=deferred();let centralReads=0;const app=fixture(handlerFor(query=>{
    if(query.get('timezone_group')==='central')return ++centralReads===1?previous.promise:Promise.resolve(payload('central','重新加载的中部商家'));
    return Promise.resolve(payload(query.get('timezone_group')||'all'));
  }));app.render();await app.settle();app.chooseZone('中部');app.chooseZone('东部');await app.settle();app.chooseZone('中部');await app.settle();assert.equal(centralReads,2);assert.match(app.content(),/重新加载的中部商家/);previous.resolve(payload('central','旧代次中部商家'));await app.settle();assert.doesNotMatch(app.content(),/旧代次中部商家/);assert.match(app.content(),/重新加载的中部商家/);
});

test('post-save refresh starts a fresh read instead of joining a pending pre-save GET',async()=>{
  const beforeSave=deferred();let reads=0;const app=fixture(handlerFor(()=>{
    reads++;return reads===2?beforeSave.promise:Promise.resolve(payload('eastern',reads===1?'保存前商家':'保存后的最新商家'));
  }));app.render();await app.settle();app.focus();app.render();assert.equal(reads,2);
  const dossier=app.find(n=>Object.hasOwn(n.props||{},'leadId')&&typeof n.props.onSaved==='function'&&typeof n.props.onClose==='function');assert.ok(dossier,'real dossier post-save callback');
  dossier.props.onSaved();await app.settle();assert.equal(reads,3);assert.match(app.content(),/保存后的最新商家/);beforeSave.resolve(payload('eastern','过时的保存前商家'));await app.settle();assert.doesNotMatch(app.content(),/过时的保存前商家/);assert.match(app.content(),/保存后的最新商家/);
});

test('same-view auto-refresh failure clears an existing assignment selection and keeps only global stats',async()=>{
  let fail=false;const app=fixture(handlerFor(()=>fail?Promise.reject(new Error('Request timed out after 15000ms')):Promise.resolve(payload('central'))));app.render();await app.settle();app.byLabel('分配：合成中部商家').props.onClick();app.render();assert.match(app.content(),/跨页已选 1 家商家/);
  fail=true;app.focus();await app.settle();assert.doesNotMatch(app.content(),/合成中部商家|跨页已选|共 152 条|首拨核验 · 待核验 152/);assert.match(app.content(),/全部行业—餐厅—美业—待分类—/);assert.match(app.content(),/未分配5069/);assert.match(app.content(),/当前筛选加载失败/);assert.equal(app.requests.some(r=>r.method!=='GET'),false);
});
