import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const apiSource = source('../src/lib/media-monthly-workflow-api.ts');
const componentSource = source('../src/components/MediaMetaMonthlyPipeline.tsx');
const stamp = '2026-11-01T03:42:00Z', hash = 'a'.repeat(64), previewHash = 'c'.repeat(64), imageId = 'b'.repeat(32);
const requestId = '00000000-0000-4000-8000-000000000001';
class ClockDate extends Date { static now() { return Date.parse(stamp); } }
function compile(body, imports = {}) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: name => imports[name] || {}, Date: ClockDate, Set, Map, AbortController, console });
  return module.exports;
}
const images = compile(source('../src/lib/media-publication-images.ts'));
const constants = compile(source('../src/lib/media-monthly-api.ts'), { './media-publication-images': images });
const rules = { timezone: 'America/Chicago', weekdays: [2,4,6], local_time: '11:00', posts_per_week: 3, language: 'en', forbidden_claims: [], include_prices: false, generic_mode: true };
const metaApi = compile(source('../src/lib/meta-operations-api.ts'), { './media-publication-images': images });
const api = compile(apiSource, { './meta-operations-api': metaApi, './media-publication-images': images, './media-monthly-api': constants });
const image = (extra = {}) => ({ id: imageId, customer_id: 20, material_id: 3, source_sha256: hash, image_sha256: hash, width: 640, height: 640, byte_size: 201000, rights_basis: 'client_provided', created_at: stamp, revoked_at: null, status: 'ready', preview_path: `/api/v1/media-publication-images/${imageId}/preview`, can_revoke: true, ...extra });
const material = (extra = {}) => ({ id: 3, title: 'LOCAL TEST store photo', linked_item_id: null, approval_status: 'pending', copyright_status: 'unknown', image_versions: [image()], fingerprint: hash, width: 640, height: 640, quality_warning: 'LOCAL TEST original metadata pending', needs_quality_confirmation: true, ...extra });
const items = () => [3, 5, 7, 10, 12, 14, 17, 19, 21, 24, 26, 28].map((day, index) => ({ item_id: index + 1, slot_id: `202611${String(day).padStart(2, '0')}`, title: `LOCAL TEST title ${index + 1}`, content: `LOCAL TEST public copy ${index + 1}`, owner_summary: `仅内部中文核对 ${index + 1}`, proposed_publish_at: `2026-11-${String(day).padStart(2, '0')}T17:00:00Z`, timezone: 'America/Chicago', revision: 2, copy_hash: hash, material_id: 3, image_version_id: imageId, image_sha256: hash, publication_image: image(), quality_warnings: [], task_id: null, schedule: null }));
const packet = (extra = {}) => ({ id: 7, revision: 1, status: 'prepared', preview_hash: previewHash, source_hash: hash, reviewed_at: null, created_at: stamp, updated_at: stamp, expires_at: '2026-11-02T03:42:00Z', ...extra });
const workflow = (extra = {}) => ({ run_id: 1, customer_id: 20, month: '2026-11', rules, run_revision: 13, source_stale: false, workflow: null, items: items(), materials: [material()], binding: { id: 4, revision: 3, customer_id: 20, customer_name: 'LOCAL TEST Northern', title: 'LOCAL TEST Google Northern', primary_operator_id: 1, primary_operator_name: 'LOCAL TEST owner' }, delivery: { enabled: false, can_manage: true, notice: 'LOCAL TEST private delivery remains off', activated_at: null }, scheduler: { enabled: true, activation_from: '2026-10-30T19:42:04Z' }, checks: [], alerts: [], counts: { total: 12, scheduled: 0, succeeded: 0, blocked: 0, unknown: 0, missed: 0, cancelled: 0 }, capabilities: { is_owner: true, can_prepare: true, can_review: false, can_schedule: false, can_cancel: false }, ...extra });
const prepared = (extra = {}) => workflow({ workflow: packet(), capabilities: { is_owner: true, can_prepare: false, can_review: true, can_schedule: false, can_cancel: true }, ...extra });
const reviewed = (extra = {}) => prepared({ workflow: packet({ status: 'reviewed', revision: 2, reviewed_at: stamp }), items: items().map(item => ({ ...item, task_id: item.item_id + 100 })), delivery: { enabled: true, can_manage: true, notice: 'LOCAL TEST delivery on', activated_at: stamp }, capabilities: { is_owner: true, can_prepare: false, can_review: false, can_schedule: true, can_cancel: true }, ...extra });
const scheduled = (extra = {}) => reviewed({ workflow: packet({ status: 'scheduled', revision: 3, reviewed_at: stamp }), items: reviewed().items.map(item => ({ ...item, schedule: { id: item.item_id + 200, revision: 1, binding_id: 4, task_id: item.task_id, timezone: item.timezone, status: 'scheduled', message: 'LOCAL TEST waits until due', action_id: null, planned_at: item.proposed_publish_at } })), counts: { ...workflow().counts, scheduled: 12 }, capabilities: { is_owner: true, can_prepare: false, can_review: false, can_schedule: false, can_cancel: true }, ...extra });
const receipt = (data, kind) => ({ ...data, request_receipt: { request_id: requestId, kind, workflow_revision: data.workflow.revision, result_hash: hash } });
const run = (extra = {}) => ({ id: 1, customer_id: 20, month: '2026-11', profile_snapshot: { public_facts: { public_name: 'LOCAL TEST Northern', location: 'LOCAL TEST location', highlights: ['LOCAL TEST verified'] }, rules }, items: items(), revision: 13, status: 'generated', ...extra });
const tick = () => new Promise(resolve => setImmediate(resolve));
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, predicate) => { const result = nodes(tree).find(predicate); assert.ok(result, 'Expected pipeline control'); return result; };
const button = (tree, text) => find(tree, item => ['Button', 'button'].includes(item.type) && label(item) === text);
const checkbox = (tree, text) => find(find(tree, item => item.type === 'label' && label(item).includes(text)), item => item.type === 'input' && item.props.type === 'checkbox');
const check = (h, text) => { checkbox(h.render(), text).props.onChange({ target: { checked: true } }); return h.render(); };
function harness(initial = {}) {
  const states = [], refs = [], effects = [], memos = [], queue = [], requests = [], active = [], changed = [], reloaded = [];
  let si = 0, ri = 0, ei = 0, mi = 0, held = false, props = { scope: 'owner:1', run: metaRun(), isOwner: true, parentBlocked: false, ...initial };
  const equal = (a, b) => a && b && a.length === b.length && a.every((value, index) => value === b[index]);
  const hooks = {
    useState(value) { const index = si++; if (!(index in states)) states[index] = typeof value === 'function' ? value() : value; return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }]; },
    useRef(value) { const index = ri++; if (!(index in refs)) refs[index] = { current: value }; return refs[index]; },
    useEffect(callback, deps) { const index = ei++, old = effects[index]; if (!old || !equal(old.deps, deps)) queue.push(() => { old?.cleanup?.(); effects[index] = { deps, cleanup: callback() }; }); },
    useMemo(callback, deps) { const index = mi++; if (!memos[index] || !equal(memos[index].deps, deps)) memos[index] = { deps, value: callback() }; return memos[index].value; },
  };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth }, './media-publication-images': images, './media-monthly-api': constants, './meta-operations-api': metaApi });
  const fallback = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) }, '@/lib/media-monthly-workflow-api': lib, '@/lib/media-monthly-api': constants, '@/lib/media-operations-api': { mediaError: (error, message) => error?.message || message, mediaErrorStatus: error => error?.status, mediaRequestId: () => requestId, mediaUtcToLocal: (value, zone) => `${value.slice(0, 10)}T${zone === 'Asia/Shanghai' ? '01:00' : '11:00'}` }, '@/lib/use-unsaved-changes': { confirmDiscardAllChanges: () => !held, useUnsavedChanges: () => ({ markSaved() {} }), useHardNavigationBlock: () => ({ lock() { held = true; }, release() { held = false; } }) } }, { get: (value, key) => value[key] || fallback });
  const Component = compile(componentSource, imports).default;
  return { requests, active, changed, reloaded, get held() { return held; }, setProps(next) { props = { ...props, ...next }; }, render() { si = ri = ei = mi = 0; const tree = Component({ ...props, onPacketActive: value => active.push(value), onReloadRun: () => reloaded.push(true), onChanged: () => changed.push(true) }); return tree && typeof tree.type === 'function' ? tree.type(tree.props) : tree; }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); } };
}
async function ready(h, data = workflow()) { h.render(); h.effects(); assert.equal(h.requests.length, 1); h.requests[0].resolve({ data }); await tick(); return h.render(); }
function photosReady(h) { for (const preview of nodes(h.render()).filter(item => item.type === 'PublicationImagePreview')) preview.props.onStateChange('ready'); return h.render(); }
function prepareReady(h) { photosReady(h); check(h, '我已核对所选真实图片'); return check(h, '保留现有12篇文案'); }
async function finishMutation(h, data, kind) { h.requests.at(-1).resolve({ data: receipt(data, kind) }); await tick(); assert.equal(h.requests.at(-1).options.method, 'GET'); assert.equal(h.requests.at(-1).options.url, '/api/v1/media-monthly/runs/1/workflow'); h.requests.at(-1).resolve({ data }); await tick(); return h.render(); }


const media = (extra={}) => ({id:'d'.repeat(32),sha256:'e'.repeat(64),width:640,height:640,byte_size:25000,preview_path:`/api/v1/meta-operations/media/${'d'.repeat(32)}/preview`,created_at:stamp,...extra});
const metaRun=(platform='facebook',extra={})=>run({platform,...extra});
const metaFlow=(platform='facebook',extra={})=>workflow({platform,binding:{...workflow().binding,platform,asset_name:`LOCAL TEST ${platform} account`,operations_active:true},items:items().map(item=>({...item,draft_id:null,meta_media:null})),scheduler:{enabled:false,activation_from:null},capabilities:{is_owner:true,can_prepare:true,can_review:false,can_schedule:false,can_activate:false,can_cancel:false},...extra});
const metaPrepared=(platform='facebook',extra={})=>metaFlow(platform,{workflow:packet(),items:items().map(item=>({...item,draft_id:null,meta_media:media()})),capabilities:{is_owner:true,can_prepare:false,can_review:true,can_schedule:false,can_activate:false,can_cancel:true},...extra});
const metaReviewed=(platform='facebook',extra={})=>metaPrepared(platform,{workflow:packet({status:'reviewed',revision:2,reviewed_at:stamp}),items:metaPrepared(platform).items.map(item=>({...item,draft_id:item.item_id+100})),capabilities:{is_owner:true,can_prepare:false,can_review:false,can_schedule:true,can_activate:false,can_cancel:true},...extra});
const metaPlanned=(platform='facebook',extra={})=>metaReviewed(platform,{workflow:packet({status:'schedule_prepared',revision:3,reviewed_at:stamp}),items:metaReviewed(platform).items.map(item=>({...item,schedule:{id:item.item_id+200,revision:1,binding_id:4,draft_id:item.draft_id,draft_revision:1,preview_hash:hash,timezone:item.timezone,status:'prepared',message:'LOCAL TEST private only',action_id:null,planned_at:item.proposed_publish_at,created_at:stamp,submitted_draft:{title:item.title,content:item.content,media_id:media().id,kind:'post',target_ref:null,draft_revision:1,preview_hash:hash},media:media(),target:{customer_name:'LOCAL TEST Northern',platform,asset_name:`LOCAL TEST ${platform} account`}}})),counts:{...workflow().counts,prepared:12},capabilities:{is_owner:true,can_prepare:false,can_review:false,can_schedule:false,can_activate:false,can_cancel:true},...extra});
const jpegReady=h=>{for(const preview of nodes(h.render()).filter(item=>item.type==='MetaPrivateImage'))preview.props.onReady(true);return h.render();};

test('Meta workflow identity requires exact persisted platform, customer, binding account and native media',()=>{
  for(const platform of ['facebook','instagram'])assert.equal(api.verifiedMonthlyWorkflow(metaPrepared(platform),1,metaRun(platform)).platform,platform);
  for(const data of [metaPrepared('instagram'),metaPrepared('facebook',{platform:undefined}),metaPrepared('facebook',{customer_id:21}),metaPrepared('facebook',{binding:{...metaPrepared().binding,platform:'instagram'}})])assert.throws(()=>api.verifiedMonthlyWorkflow(data,1,metaRun()));
  const invalid=metaPlanned();invalid.items[0].schedule.target.asset_name='WRONG ACCOUNT';assert.throws(()=>api.verifiedMonthlyWorkflow(invalid,1,metaRun()));
  const switched=metaPlanned();switched.items[0].schedule.target.platform='instagram';assert.throws(()=>api.verifiedMonthlyWorkflow(switched,1,metaRun()));
});
test('Instagram rejects incompatible JPEG aspect and same JPEG identity with differing bytes',()=>{
  const aspect=metaPrepared('instagram');aspect.items[0].publication_image={...aspect.items[0].publication_image,width:2000,height:600};aspect.items[0].meta_media=media({width:2000,height:600});assert.throws(()=>api.verifiedMonthlyWorkflow(aspect,1,metaRun('instagram')));
  const mutated=metaPrepared();mutated.items[1].meta_media=media({sha256:'f'.repeat(64)});assert.throws(()=>api.verifiedMonthlyWorkflow(mutated,1,metaRun()));
});
test('staff and non-Meta batches perform zero reads, even with forced retained handlers',()=>{
  for(const props of [{isOwner:false},{run:run()},{run:metaRun('facebook',{status:'failed'})}]){const h=harness(props);assert.equal(h.render(),null);h.effects();assert.equal(h.requests.length,0);}
});
test('opening a Meta month makes one bounded local read and never enables a provider or writes',async()=>{
  const h=harness();await ready(h,metaFlow());assert.equal(h.requests.length,1);assert.equal(h.requests[0].options.method,'GET');assert.ok(label(h.render()).includes('不会启用发布服务或自动提交'));assert.ok(label(h.render()).includes('LOCAL TEST facebook account'));
});
test('source PNG consent alone cannot approve actual JPEG; every JPEG callback is required',async()=>{
  const h=harness();await ready(h,metaPrepared());assert.equal(nodes(h.render()).filter(n=>n.type==='MetaPrivateImage').length,12);photosReady(h);check(h,'仅确认内部内容审核');assert.equal(button(h.render(),'整月审核通过，暂不发布').props.disabled,true);
  jpegReady(h);button(check(h,'仅确认内部内容审核'),'整月审核通过，暂不发布').props.onClick();const sent=h.requests.at(-1);assert.equal(sent.options.url,'/api/v1/media-monthly/runs/1/review');assert.equal(sent.options.data.confirmed,true);assert.equal(sent.options.data.publication_confirmed,undefined);
});
test('disabled scheduler saves only prepared native schedules after separate private-plan confirmation',async()=>{
  for(const platform of ['facebook','instagram']){const h=harness({run:metaRun(platform)});await ready(h,metaReviewed(platform));jpegReady(h);assert.equal(button(h.render(),'保存批量排期（待发布确认）').props.disabled,true);const trigger=button(check(h,'确认仅保存上述'),'保存批量排期（待发布确认）');assert.equal(trigger.props.disabled,false);trigger.props.onClick();trigger.props.onClick();assert.equal(h.requests.filter(r=>r.options.method==='POST').length,1);const original=h.requests.at(-1);assert.equal(original.options.data.publication_confirmed,false);assert.equal(original.options.url,'/api/v1/media-monthly/runs/1/schedule');await finishMutation(h,metaPlanned(platform),'schedule');assert.ok(label(h.render()).includes('全部等待发布确认'));assert.ok(label(h.render()).includes('仅保存计划'));assert.ok(!nodes(h.render()).some(n=>n.type==='Button'&&label(n).includes('确认公开发布')));}
});
test('private schedule receipt cannot claim armed jobs, changed JPEG or cross-platform success',()=>{
  const before=metaReviewed(),body={request_id:requestId,expected_revision:2,preview_hash:previewHash,publication_confirmed:false,confirmation_version:'monthly-publication-v1'},mutation={kind:'schedule',body};assert.equal(api.monthlyWorkflowMutationMatches(receipt(metaPlanned(),'schedule'),before,mutation),true);
  for(const after of [metaPlanned('instagram'),metaPlanned('facebook',{workflow:packet({revision:3,status:'scheduled'})}),metaPlanned('facebook',{items:metaPlanned().items.map(item=>({...item,meta_media:media({sha256:'f'.repeat(64)})}))})])assert.equal(api.monthlyWorkflowMutationMatches(receipt(after,'schedule'),before,mutation),false);
});
test('unknown batch save reads original request only and explicit retry retains publication false',async()=>{
  const h=harness();await ready(h,metaReviewed());jpegReady(h);button(check(h,'确认仅保存上述'),'保存批量排期（待发布确认）').props.onClick();const original=h.requests.at(-1),body=original.options.data;original.reject(new Error('timeout'));await tick();assert.equal(h.held,true);button(h.render(),'读取原流程操作结果').props.onClick();assert.ok(h.requests.at(-1).options.url.endsWith('/workflow-requests/'+requestId));h.requests.at(-1).reject({status:404,message:'LOCAL TEST absent'});await tick();assert.equal(h.requests.filter(r=>r.options.method==='POST').length,1);button(check(h,'仅沿用原编号'),'沿用原流程请求确认').props.onClick();assert.deepEqual(h.requests.at(-1).options.data,body);assert.equal(h.requests.at(-1).options.data.publication_confirmed,false);
});
test('late workflow and JPEG callbacks cannot restore a revoked owner or changed platform',async()=>{
  const h=harness();await ready(h,metaPrepared());const callbacks=nodes(h.render()).filter(n=>n.type==='MetaPrivateImage').map(n=>n.props.onReady);h.setProps({isOwner:false});assert.equal(h.render(),null);h.unmount();callbacks.forEach(fn=>fn(true));assert.equal(h.requests.length,1);
  const late=harness();late.render();late.effects();const request=late.requests[0];late.unmount();request.resolve({data:metaPrepared()});await tick();assert.equal(late.active.length,0);assert.equal(request.options.options.signal.aborted,true);
});
test('stale source, failed actual image, wrong run version and parent edit block batch save',async()=>{
  for(const value of [metaReviewed('facebook',{source_stale:true}),metaReviewed('facebook',{run_revision:14}),metaReviewed('facebook',{items:metaReviewed().items.map(item=>({...item,quality_warnings:['Image changed']}))})]){const h=harness();await ready(h,value);jpegReady(h);const trigger=button(check(h,'确认仅保存上述'),'保存批量排期（待发布确认）');assert.equal(trigger.props.disabled,true);trigger.props.onClick();assert.equal(h.requests.length,1);}
  const h=harness({parentBlocked:true});await ready(h,metaReviewed());jpegReady(h);button(check(h,'确认仅保存上述'),'保存批量排期（待发布确认）').props.onClick();assert.equal(h.requests.length,1);
});
