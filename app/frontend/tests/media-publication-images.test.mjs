import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = fs.readFileSync(new URL('../src/lib/media-publication-images.ts', import.meta.url),'utf8');
const module = {exports:{}};
const base64 = value => Buffer.from(value, 'binary').toString('base64');
const sandbox = {module,exports:module.exports,require:()=>({invokeWithAuth:async()=>{throw new Error('No real API in unit test');}}),Blob,crypto:webcrypto,Uint8Array,DataView,btoa:base64,console};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,sandbox);
const api = module.exports;
const png = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64'));
const jpeg = Uint8Array.from([255,216,255,224,0,4,0,0,255,192,0,17,8,2,88,3,32,3,1,17,0,2,17,0,3,17,0,255,217]);
function pngDimensions(width,height) {const value=png.slice();const v=new DataView(value.buffer);v.setUint32(16,width);v.setUint32(20,height);return value;}
const id='a'.repeat(32),hash='b'.repeat(64);
const dto = overrides=>({id,customer_id:12,material_id:18,source_sha256:hash,image_sha256:hash,width:1200,height:800,byte_size:png.length,rights_basis:'client_provided',created_at:'2026-10-31T08:00:00Z',revoked_at:null,status:'ready',preview_path:`/api/v1/media-publication-images/${id}/preview`,can_revoke:false,...overrides});

test('reads true PNG and JPEG dimensions independently of a supplied MIME/filename',()=>{
  assert.deepEqual(JSON.parse(JSON.stringify(api.sourceImageDimensions(png))),{kind:'png',width:1,height:1});
  assert.deepEqual(JSON.parse(JSON.stringify(api.sourceImageDimensions(jpeg))),{kind:'jpeg',width:800,height:600});
});
test('rejects SVG, HTML, GIF, video and empty input before bitmap decoding',()=>{
  for(const data of ['<svg/>','<!doctype html><img src=x>','GIF89a','....ftypmp4',''])assert.throws(()=>api.sourceImageDimensions(new TextEncoder().encode(data)));
});
test('rejects a JPEG whose declared segment passes the available file',()=>{
  assert.throws(()=>api.sourceImageDimensions(Uint8Array.from([255,216,255,224,255,255,0,0])));
});
test('guards zero, extreme sides and decompression-sized pixel counts',()=>{
  for(const [w,h] of [[0,400],[12001,100],[100,12001],[10000,10000]])assert.throws(()=>api.sourceImageDimensions(pngDimensions(w,h)));
});
test('rejects animated PNG instead of silently choosing a frame',()=>{
  const acTL=Uint8Array.from([0,0,0,0,97,99,84,76,0,0,0,0]);
  const animated=new Uint8Array(png.length+acTL.length);animated.set(png.slice(0,33));animated.set(acTL,33);animated.set(png.slice(33),45);
  assert.throws(()=>api.sourceImageDimensions(animated),/动态图/);
});
test('scales long and portrait images proportionally, without upscaling',()=>{
  assert.deepEqual(JSON.parse(JSON.stringify(api.publicationImageSize(6000,3000))),{width:2048,height:1024});
  assert.deepEqual(JSON.parse(JSON.stringify(api.publicationImageSize(800,1600))),{width:800,height:1600});
  assert.deepEqual(JSON.parse(JSON.stringify(api.publicationImageSize(3000,6000))),{width:1024,height:2048});
});
test('only the exact authenticated derivative path is accepted for img preparation',()=>{
  assert.equal(api.imagePreviewPath(dto().preview_path,id),true);
  for(const value of ['https://t24-crm.com'+dto().preview_path,'//attacker.example/image.png',dto().preview_path+'?token=x','/api/v1/media-publication-images/delivery/secret.png',dto().preview_path.replace(id,'c'.repeat(32))])assert.equal(api.imagePreviewPath(value,id),false);
});
test('rejects another customer, material, oversized version and malformed identity',()=>{
  assert.throws(()=>api.verifiedPublicationImage(dto(),13,18));
  assert.throws(()=>api.verifiedPublicationImage(dto(),12,19));
  for(const value of [dto({id:'1'}),dto({byte_size:9*1024*1024}),dto({width:2049}),dto({image_sha256:'no'}),dto({rights_basis:'unknown'})])assert.throws(()=>api.verifiedPublicationImage(value));
});
test('auth preview verifies the final server SHA, rejects changed bytes and wrong size',async()=>{
  const blob=new Blob([png]);const sha=await api.sha256Blob(blob);const checked=dto({image_sha256:sha});
  assert.equal((await api.verifiedPreviewBlob(checked,blob)).type,'image/png');
  const changed=png.slice();changed[changed.length-1]^=1;
  await assert.rejects(api.verifiedPreviewBlob(checked,new Blob([changed])),/不一致/);
  await assert.rejects(api.verifiedPreviewBlob(checked,new Blob([png,png])),/不一致/);
});
test('browser conversion closes decoded bitmap and bounds generated output',async()=>{
  let closed=0,option;
  sandbox.createImageBitmap=async(_blob,options)=>{option=options;return{width:4000,height:2000,close(){closed++;}};};
  const canvas={width:0,height:0,getContext:()=>({drawImage(){}}),toBlob:callback=>callback(new Blob([png],{type:'image/png'}))};
  sandbox.document={createElement:()=>canvas};
  const result=await api.prepareBrowserImage(new Blob([png]));
  assert.equal(result.width,2048);assert.equal(result.height,1024);assert.equal(canvas.width,2048);assert.equal(option.imageOrientation,'from-image');assert.equal(closed,1);assert.equal(result.sourceSha256,await api.sha256Blob(new Blob([png])));
  canvas.toBlob=callback=>callback(new Blob([new Uint8Array(8*1024*1024+1)]));
  await assert.rejects(api.prepareBrowserImage(new Blob([png])),/过大/);assert.equal(closed,2);
});
test('oversized source is refused without invoking the browser decoder',async()=>{
  let decoded=false;sandbox.createImageBitmap=async()=>{decoded=true;};
  await assert.rejects(api.prepareBrowserImage(new Blob([new Uint8Array(20*1024*1024+1)])),/20MB/);assert.equal(decoded,false);
});
test('canvas unavailable is a recoverable preparation error and releases the bitmap',async()=>{
  let closed=false;sandbox.createImageBitmap=async()=>({width:10,height:10,close(){closed=true;}});sandbox.document={createElement:()=>({getContext:()=>null})};
  await assert.rejects(api.prepareBrowserImage(new Blob([png])),/浏览器/);assert.equal(closed,true);
});
test('decoder failure becomes an actionable image error instead of a browser diagnostic',async()=>{
  sandbox.createImageBitmap=async()=>{throw new Error('provider-internal decoder text');};
  await assert.rejects(api.prepareBrowserImage(new Blob([png])),/原图片无法完整解码/);
});
test('old customer requests cannot revive after A to B to A navigation',()=>{
  const scope=api.imageRequestScope('owner:customer12:material18');scope.activate();const old=scope.capture();
  scope.update('owner:customer13:material19');assert.equal(old(),false);
  scope.update('owner:customer12:material18');scope.activate();assert.equal(old(),false);assert.equal(scope.capture()(),true);
});
test('account switch invalidates a request before the next effect or response',()=>{
  const scope=api.imageRequestScope('owner:customer12');scope.activate();const save=scope.capture();
  scope.update('ops:customer12');assert.equal(save(),false);scope.activate();assert.equal(save(),false);
});
test('retry and unmount invalidate prior image load events',()=>{
  const scope=api.imageRequestScope('image:hash');scope.activate();const oldLoad=scope.capture();
  scope.invalidate();scope.activate();assert.equal(oldLoad(),false);const newLoad=scope.capture();assert.equal(newLoad(),true);
  scope.invalidate();assert.equal(newLoad(),false);
});
test('same-scope rerenders retain an active operation while late results are ignored',async()=>{
  const scope=api.imageRequestScope('A');scope.activate();const current=scope.capture();scope.update('A');assert.equal(current(),true);
  let resolve;const response=new Promise(done=>{resolve=done;});let accepted=false;
  const pending=response.then(()=>{if(current())accepted=true;});scope.update('B');resolve();await pending;assert.equal(accepted,false);
});

test('private PNG preview uses a fixed data MIME and preserves exact verified bytes',async()=>{
  const value=await api.publicationImagePreviewDataUrl(new Blob([png],{type:'application/octet-stream'}));
  assert.equal(value,'data:image/png;base64,'+Buffer.from(png).toString('base64'));
  assert.deepEqual(Buffer.from(value.split(',')[1],'base64'),Buffer.from(png));
});
test('preview refuses SVG, HTML, JPEG and oversized PNG dimensions despite image MIME labels',async()=>{
  for(const body of [new TextEncoder().encode('<svg onload="alert(1)"/>'),new TextEncoder().encode('<html>not an image</html>'),jpeg,pngDimensions(2049,1)]) {
    await assert.rejects(api.publicationImagePreviewDataUrl(new Blob([body],{type:'image/png'})));
  }
});
test('empty or over 8MB previews are rejected before reading or encoding their contents',async()=>{
  await assert.rejects(api.publicationImagePreviewDataUrl(new Blob([])),/8MB/);
  const large=new Blob([new Uint8Array(8*1024*1024+1)]);let read=false;
  large.arrayBuffer=async()=>{read=true;throw new Error('must not read oversized preview');};
  await assert.rejects(api.publicationImagePreviewDataUrl(large),/8MB/);assert.equal(read,false);
});

const componentSource=fs.readFileSync(new URL('../src/components/MediaPublicationImage.tsx',import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const flatten=node=>node==null||typeof node!=='object'?[]:Array.isArray(node)?node.flatMap(flatten):[node,...flatten(node.props?.children)];
const label=node=>node==null||typeof node==='boolean'?'':typeof node!=='object'?String(node):Array.isArray(node)?node.map(label).join(''):label(node.props?.children);
function componentHarness(kind='final') {
  const states=[],refs=[],effects=[],effectQueue=[],requests=[],notifications=[],changes=[];
  let stateIndex=0,refIndex=0,effectIndex=0;
  const hooks={useState(initial){const i=stateIndex++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value;}];},
    useRef(initial){const i=refIndex++;if(!(i in refs))refs[i]={current:initial};return refs[i];},
    useEffect(run,deps){const i=effectIndex++,old=effects[i];if(!old||!deps||deps.some((value,n)=>value!==old.deps?.[n]))effectQueue.push(()=>{old?.cleanup?.();effects[i]={deps,cleanup:run()};});}};
  const invokeWithAuth=options=>new Promise((resolve,reject)=>requests.push({options,resolve,reject}));
  const libModule={exports:{}};
  const library={module:libModule,exports:libModule.exports,require:()=>({invokeWithAuth}),Blob,crypto:webcrypto,Uint8Array,DataView,btoa:base64,console,
    createImageBitmap:async()=>({width:1,height:1,close(){}}),document:{createElement:()=>({width:0,height:0,getContext:()=>({drawImage(){}}),toBlob:callback=>callback(new Blob([png],{type:'image/png'}))})}};
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,library);
  const compiled={exports:{}};
  const objectUrlForbidden={createObjectURL(){throw new Error('blob: previews are blocked by production CSP');},revokeObjectURL(){throw new Error('no object URL should exist');}};
  vm.runInNewContext(ts.transpileModule(componentSource,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,
    {module:compiled,exports:compiled.exports,require:name=>{
      if(name==='react')return hooks;
      if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
      if(name==='@/lib/media-publication-images')return libModule.exports;
      if(name==='@/lib/tokenStore')return{invokeWithAuth};
      if(name==='@/lib/media-operations-api')return{mediaRequestId:()=> 'synthetic-image-request',mediaErrorStatus:error=>error.status,mediaError:(error,fallback)=>error.message||fallback};
      if(name==='@/lib/use-unsaved-changes')return{useUnsavedChanges:()=>({markSaved(){}}),useHardNavigationBlock:()=>({lock(){},release(){}})};
      return new Proxy({}, {get:(_,key)=>String(key)});
    },Blob,FormData,URL:objectUrlForbidden,console});
  return{requests,notifications,changes,async image(){return dto({width:1,height:1,image_sha256:await api.sha256Blob(new Blob([png]))});},
    render(image,scope='owner:12') {stateIndex=0;refIndex=0;effectIndex=0;return kind==='final'?compiled.exports.PublicationImagePreview({image,scope,onStateChange:value=>notifications.push(value)}):compiled.exports.default({customerId:12,materialId:18,value:'',canPrepare:true,scope,onChange:value=>changes.push(value)});},
    effects(){while(effectQueue.length)effectQueue.shift()();},unmount(){effects.forEach(effect=>effect?.cleanup?.());}};
}
async function settleUntil(test,turns=100){for(let i=0;i<turns;i++){if(test())return;await tick();}assert.ok(test(),'Expected asynchronous component result');}
const policyAllowsImage=src=>/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(src); // Production img-src 'self' data: https:

test('actual final image component emits a CSP-compatible PNG data source only after authenticated SHA verification',async()=>{
  const h=componentHarness(),image=await h.image();h.render(image);h.effects();
  assert.deepEqual(h.requests.map(x=>JSON.parse(JSON.stringify(x.options))),[{url:image.preview_path,method:'GET',options:{responseType:'blob'}}]);
  h.requests[0].resolve({data:new Blob([png])});await settleUntil(()=>flatten(h.render(image)).some(x=>x.type==='img'));
  const img=flatten(h.render(image)).find(x=>x.type==='img');assert.ok(policyAllowsImage(img.props.src));assert.equal(img.props.src.includes('token'),false);assert.equal(img.props.src.includes('/delivery/'),false);
  assert.deepEqual(Buffer.from(img.props.src.split(',')[1],'base64'),Buffer.from(png));img.props.onLoad();assert.equal(h.notifications.at(-1),'ready');assert.equal(h.requests.length,1);
});
test('actual final component refuses changed bytes rather than exposing them through a data source',async()=>{
  const h=componentHarness(),image=await h.image();h.render(image);h.effects();const changed=png.slice();changed[changed.length-1]^=1;
  h.requests[0].resolve({data:new Blob([changed])});await settleUntil(()=>h.notifications.includes('failed'));
  assert.equal(flatten(h.render(image)).some(x=>x.type==='img'),false);assert.equal(h.notifications.includes('ready'),false);
});
test('actual final preview drops stale sources and load callbacks across account A to B to A and unmount',async()=>{
  const h=componentHarness(),image=await h.image();h.render(image);h.effects();h.requests[0].resolve({data:new Blob([png])});await settleUntil(()=>flatten(h.render(image)).some(x=>x.type==='img'));
  const old=flatten(h.render(image)).find(x=>x.type==='img');h.render(image,'ops:13');h.render(image,'owner:12');assert.equal(flatten(h.render(image)).some(x=>x.type==='img'),false);
  old.props.onLoad();assert.equal(h.notifications.includes('ready'),false);h.effects();h.unmount();const before=h.notifications.length;for(const request of h.requests.slice(1))request.resolve({data:new Blob([png])});
  await tick();assert.equal(h.notifications.length,before);
});
test('actual candidate preview respects CSP and saves the PNG Blob, never a data URI or lease URL',async()=>{
  const h=componentHarness('candidate');h.render();h.effects();h.requests[0].resolve({data:{items:[],can_prepare:true,delivery_available:true}});await tick();
  let tree=h.render();const read=flatten(tree).find(x=>x.type==='Button'&&label(x)==='读取原图并准备新版本');assert.ok(read);read.props.onClick();
  assert.equal(h.requests[1].options.url,'/api/v1/entities/customer_materials/18/download');h.requests[1].resolve({data:new Blob([png])});
  await settleUntil(()=>flatten(h.render()).some(x=>x.type==='img'&&x.props.alt==='本次待保存的配图预览'));
  tree=h.render();const candidate=flatten(tree).find(x=>x.type==='img'&&x.props.alt==='本次待保存的配图预览');assert.ok(policyAllowsImage(candidate.props.src));
  flatten(tree).find(x=>x.props?.['aria-label']==='发布图片使用权依据').props.onChange('client_provided');tree=h.render();
  const consent=flatten(tree).find(x=>x.type==='input'&&x.props.type==='checkbox');consent.props.onChange({target:{checked:true}});tree=h.render();
  flatten(tree).find(x=>x.type==='Button'&&label(x)==='保存固定图片版本').props.onClick();
  const save=h.requests[2].options;assert.equal(save.url,'/api/v1/media-publication-images/prepare');assert.equal(save.method,'POST');assert.ok(save.data instanceof FormData);
  const file=save.data.get('file');assert.equal(file.type,'image/png');assert.equal(file.size,png.length);
  for(const value of save.data.values())if(typeof value==='string')assert.equal(value.startsWith('data:'),false);
  assert.equal(h.requests.some(x=>/delivery-policy|\/posts$|\/schedules$/.test(x.options.url)),false);
});
