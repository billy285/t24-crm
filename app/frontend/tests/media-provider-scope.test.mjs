import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
const module={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(new URL('../src/lib/media-provider-scope.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module,exports:module.exports});
const {mediaProviderScope,mediaScopedBindings}=module.exports;
const rows=[{id:1,customer_id:7,platform:'facebook'},{id:2,customer_id:7,platform:'instagram'},{id:3,customer_id:8,platform:'facebook'}];
test('customer and platform are an intersection; missing matches never choose a different account',()=>{
 assert.deepEqual(Array.from(mediaScopedBindings(rows,7,'instagram'),x=>x.id),[2]);
 for(const [customer,platform] of [[9,'facebook'],[8,'instagram'],[7,'google_business']])assert.equal(mediaScopedBindings(rows,customer,platform).length,0);
 assert.deepEqual(Array.from(mediaScopedBindings(rows,7),x=>x.id),[1,2]);
 assert.deepEqual(Array.from(mediaScopedBindings(rows,undefined,'facebook'),x=>x.id),[1,3]);
 assert.equal(rows.length,3);
});
test('Google bindings without a platform discriminator only match Google in a scoped provider panel',()=>{
 const google=[{customer_id:7,id:4},{customer_id:8,id:5}];
 assert.deepEqual(Array.from(mediaScopedBindings(google,7,'google_business'),x=>x.id),[4]);
 assert.equal(mediaScopedBindings(google,7,'facebook').length,0);
});
test('request identity fences customer and platform changes while preserving legacy identity',()=>{
 assert.equal(mediaProviderScope('owner:1'),'owner:1');
 assert.notEqual(mediaProviderScope('owner:1',7,'facebook'),mediaProviderScope('owner:1',8,'facebook'));
 assert.notEqual(mediaProviderScope('owner:1',7,'facebook'),mediaProviderScope('owner:1',7,'instagram'));
 assert.notEqual(mediaProviderScope('owner:1',7,'facebook'),mediaProviderScope('staff:2',7,'facebook'));
});
