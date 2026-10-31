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
const sandbox = {module,exports:module.exports,require:()=>({invokeWithAuth:async()=>{throw new Error('No real API in unit test');}}),Blob,crypto:webcrypto,Uint8Array,DataView,console};
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
