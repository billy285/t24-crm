import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

const path=resolve(dirname(fileURLToPath(import.meta.url)),'../src/components/SalesWorkbenchDial.tsx');
const flush=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
const same=(a,b)=>a&&b&&a.length===b.length&&a.every((value,index)=>Object.is(value,b[index]));
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}

function fixture(overrides={}){
 const state=[],effects=[],launched=[],busy=[],dialed=[],notices=[];let cursor=0,tree,unmounted=false,unmountedStateWrites=0;
 let props={phone:'+12135550123',country:'US',disabled:false,onPrepare:async()=>{},onLaunched:()=>launched.push(true),onBusyChange:value=>busy.push(value),...overrides};
 const react={
  useRef(initial){const i=cursor++;if(!state[i])state[i]={value:{current:initial}};return state[i].value;},
  useState(initial){const i=cursor++;if(!state[i])state[i]={value:initial};return[state[i].value,value=>{if(unmounted)unmountedStateWrites++;state[i].value=typeof value==='function'?value(state[i].value):value;}];},
  useEffect(callback,deps){const i=cursor++;if(!state[i]||!same(state[i].deps,deps)){const previous=state[i];state[i]={deps};effects.push(()=>{previous?.cleanup?.();state[i].cleanup=callback();});}},
 };
 const mod={exports:{}};
 const require=name=>{
  if(name==='react')return react;
  if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
  if(name==='sonner')return{toast:{error:message=>notices.push(message),info:message=>notices.push(message)}};
  if(name==='@/lib/use-sales-lead-enrichment')return{enrichmentError:error=>error.message};
  if(name==='@/lib/phone-dial')return{getCustomerDialValidation:phone=>({isValid:phone.startsWith('+'),e164:phone,reason:'invalid'}),launchCustomerDial:(...args)=>dialed.push(args)};
  return new Proxy({},{get:(_target,key)=>String(key)});
 };
 const code=ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 vm.runInNewContext(`(function(require,module,exports){${code}\n})`,{console})(require,mod,mod.exports);
 const flushEffects=()=>{while(effects.length)effects.shift()();};
 const render=(next={},runEffects=true)=>{assert.equal(unmounted,false);props={...props,...next};cursor=0;tree=mod.exports.default(props);if(runEffects)flushEffects();return tree;};
 const unmount=()=>{unmounted=true;for(const slot of state)slot?.cleanup?.();};
 const click=()=>tree.props.onClick();
 return{render,unmount,click,flushEffects,launched,busy,dialed,notices,tree:()=>tree,writesAfterUnmount:()=>unmountedStateWrites};
}

test('successful preparation launches exactly once and releases busy without changing the target',async()=>{
 const result=deferred();let prepares=0;const app=fixture({onPrepare:()=>{prepares++;return result.promise;}});app.render();app.click();app.click();app.render();assert.equal(app.tree().props.disabled,true);assert.equal(prepares,1);
 result.resolve();await flush();app.render();assert.equal(app.dialed.length,1);assert.deepEqual(app.dialed[0],['+12135550123','US']);assert.equal(app.launched.length,1);assert.deepEqual(app.busy,[true,false]);assert.equal(app.tree().props.disabled,false);
});

test('unmount cancels pending launch and releases parent hold once without post-unmount state writes',async()=>{
 const result=deferred();const app=fixture({onPrepare:()=>result.promise});app.render();app.click();app.render();app.unmount();assert.deepEqual(app.busy,[true,false]);result.resolve();await flush();
 assert.equal(app.dialed.length,0);assert.equal(app.launched.length,0);assert.deepEqual(app.busy,[true,false]);assert.equal(app.writesAfterUnmount(),0);
});

test('phone replacement cancels the old request before effects and does not launch it when it resolves',async()=>{
 const result=deferred();const app=fixture({onPrepare:()=>result.promise});app.render();app.click();app.render({phone:'+14155552671'},false);result.resolve();await flush();assert.equal(app.dialed.length,0);assert.equal(app.launched.length,0);app.flushEffects();app.render();assert.deepEqual(app.busy,[true,false]);assert.equal(app.tree().props.disabled,false);
});

test('country changes invalidate preparation even when phone text is unchanged',async()=>{
 const result=deferred();const app=fixture({onPrepare:()=>result.promise});app.render();app.click();app.render({country:'CA'});result.resolve();await flush();assert.equal(app.dialed.length,0);assert.equal(app.launched.length,0);assert.deepEqual(app.busy,[true,false]);
});

test('returning to the same number cannot revive an old generation or release a newer busy request',async()=>{
 const old=deferred(),next=deferred();let calls=0;const app=fixture({onPrepare:()=>++calls===1?old.promise:next.promise});app.render();app.click();app.render({phone:'+14155552671'});app.render({phone:'+12135550123'});app.click();app.render();assert.deepEqual(app.busy,[true,false,true]);
 old.resolve();await flush();app.render();assert.equal(app.tree().props.disabled,true);assert.deepEqual(app.busy,[true,false,true]);assert.equal(app.dialed.length,0);
 next.resolve();await flush();app.render();assert.deepEqual(app.busy,[true,false,true,false]);assert.equal(app.dialed.length,1);
});

test('rejected stale preparation is silent; current rejection remains visible and allows retry',async()=>{
 const old=deferred();const app=fixture({onPrepare:()=>old.promise});app.render();app.click();app.render({phone:'+14155552671'});old.reject(new Error('old denied'));await flush();assert.deepEqual(app.notices,[]);
 const next=deferred();app.render({onPrepare:()=>next.promise});app.click();next.reject(new Error('current denied'));await flush();app.render();assert.deepEqual(app.notices,['current denied']);assert.equal(app.tree().props.disabled,false);assert.equal(app.dialed.length,0);
});

test('synchronous removal in onLaunched cannot hand off to an external dialer',async()=>{
 const result=deferred();let app;app=fixture({onPrepare:()=>result.promise,onLaunched:()=>app.unmount()});app.render();app.click();result.resolve();await flush();assert.equal(app.dialed.length,0);assert.equal(app.writesAfterUnmount(),0);assert.deepEqual(app.busy,[true,false]);
});
