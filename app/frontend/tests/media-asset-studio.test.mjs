import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { webcrypto, createHash } from 'node:crypto';
const require = createRequire(import.meta.url), ts = require('typescript');
const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const apiSource = read('../src/lib/media-asset-studio.ts'), componentSource = read('../src/components/MediaAssetStudio.tsx');
const stamp = '2026-11-01T06:00:00Z', hash = 'a'.repeat(64), imageId = 'b'.repeat(32), jobId = 'c'.repeat(32), secondImage = 'd'.repeat(32), requestId = '00000000-0000-4000-8000-000000000001';
const source = (extra = {}) => ({ material_id: 3, title: 'LOCAL TEST real storefront', suggested_title: 'LOCAL TEST confirmed menu name', linked_item_id: null, image_id: imageId, image_sha256: hash, width: 640, height: 640, byte_size: 20100, preview_path: `/api/v1/media-publication-images/${imageId}/preview`, rights_basis: 'client_provided', ...extra });
const profile = (extra = {}) => ({ revision: 1, preset: 'editorial', brand_name: 'LOCAL TEST merchant', primary_color: '#203040', accent_color: '#F0A020', footer: 'LOCAL TEST confirmed footer', ...extra });
const recipe = (extra = {}) => ({ profile_revision: 1, kind: 'poster', image_ids: [imageId], title: 'LOCAL TEST confirmed menu name', subtitle: '', format: 'square', exposure: 0, color: 1, sharpness: 1, rights_confirmed: true, ...extra });
const output = (extra = {}) => ({ preview_path: `/api/v1/media-asset-studio/jobs/${jobId}/preview`, download_path: `/api/v1/media-asset-studio/jobs/${jobId}/download`, mime_type: 'image/png', sha256: hash, byte_size: 20100, width: 1080, height: 1080, duration_seconds: null, ...extra });
const job = (extra = {}) => ({ id: jobId, customer_id: 20, request_id: requestId, revision: 1, kind: 'poster', status: 'queued', profile_revision: 1, recipe: recipe(), sources: [source()], created_at: stamp, updated_at: stamp, error_code: null, message: 'LOCAL TEST private queue only', source_stale: false, output: null, adoption: null, can_retry: false, can_adopt: false, ...extra });
const succeeded = (extra = {}) => job({ status: 'succeeded', revision: 3, output: output(), can_adopt: true, ...extra });
const adopted = (extra = {}) => succeeded({ status: 'adopted', revision: 4, can_adopt: false, adoption: { material_id: 99, image_id: 'e'.repeat(32), preview_path: `/api/v1/media-publication-images/${'e'.repeat(32)}/preview` }, ...extra });
const studio = (extra = {}) => ({ customer_id: 20, customer_name: 'LOCAL TEST merchant', cooperation_active: true, read_only_reason: null, capabilities: { can_edit: true, can_create: true, can_adopt: true, poster: true, collage: true, enhance: true, video: false, video_reason: 'LOCAL TEST no verified video engine' }, profile: profile(), sources: [source(), source({ material_id: 4, image_id: secondImage, preview_path: `/api/v1/media-publication-images/${secondImage}/preview` })], jobs: [], ...extra });
const mutation = (kind, selectedJob, selectedProfile = null, extra = {}) => ({ kind, request_id: requestId, customer_id: 20, job: selectedJob, profile: selectedProfile, ...extra });
const tick = () => new Promise(resolve => setImmediate(resolve));
const compile = (body, imports = {}, globals = {}) => {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: name => imports[name] || {}, Blob, Uint8Array, DataView, crypto: webcrypto, btoa, URL, AbortController, Intl, Date, Set, Map, console, setTimeout, clearTimeout, ...globals });
  return module.exports;
};
const imageApi = compile(read('../src/lib/media-publication-images.ts'));
const api = compile(apiSource, { './media-publication-images': imageApi });
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, predicate) => { const result = nodes(tree).find(predicate); assert.ok(result, 'Expected studio control'); return result; };
const button = (tree, text) => find(tree, node => ['Button', 'button'].includes(node.type) && label(node) === text);
const field = (tree, aria) => find(tree, node => node.props?.['aria-label'] === aria);
const checkbox = (tree, text) => find(find(tree, node => node.type === 'label' && label(node).includes(text)), node => node.type === 'input' && node.props.type === 'checkbox');
function harness(initial = {}, exportName = 'default') {
  const states = [], refs = [], effects = [], queue = [], requests = [], timers = [], changes = [];
  let si = 0, ri = 0, ei = 0, held = false, clock = Date.parse(stamp), props = { scope: 'owner:1', customerId: 20, isOwner: true, ...initial };
  class ClockDate extends Date { static now() { return clock; } }
  const equal = (a, b) => a && b && a.length === b.length && a.every((value, index) => value === b[index]);
  const hooks = { useState(value) { const i = si++; if (!(i in states)) states[i] = typeof value === 'function' ? value() : value; return [states[i], next => { states[i] = typeof next === 'function' ? next(states[i]) : next; }]; }, useRef(value) { const i = ri++; if (!(i in refs)) refs[i] = { current: value }; return refs[i]; }, useEffect(callback, deps) { const i = ei++, old = effects[i]; if (!old || !equal(old.deps, deps)) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: callback() }; }); } };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth }, './media-publication-images': imageApi });
  const fallback = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) }, '@/lib/media-asset-studio': lib, '@/lib/media-operations-api': { mediaError: (error, message) => error?.message || message, mediaErrorStatus: cause => cause?.status, mediaRequestId: () => requestId }, '@/lib/use-unsaved-changes': { confirmDiscardAllChanges: () => !held, useUnsavedChanges: () => ({ markSaved() {} }), useHardNavigationBlock: () => ({ lock() { held = true; }, release() { held = false; } }) } }, { get: (value, key) => value[key] || fallback });
  const component = compile(componentSource, imports, { Date: ClockDate, setTimeout: callback => { timers.push(callback); return timers.length; }, clearTimeout() {}, document: { visibilityState: 'visible' } })[exportName];
  return { requests, timers, changes, get held() { return held; }, advance(ms) { clock += ms; }, render() { si = ri = ei = 0; const tree = component({ ...props, onChanged: () => changes.push(true) }); return tree && typeof tree.type === 'function' ? tree.type(tree.props) : tree; }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); }, setProps(next) { props = { ...props, ...next }; } };
}
async function ready(h, data = studio()) { h.render(); h.effects(); assert.equal(h.requests.length, 1); h.requests[0].resolve({ data }); await tick(); return h.render(); }
function selectSource(h, id = imageId) { const input = find(h.render(), node => node.type === 'label' && node.props?.className !== undefined && nodes(node).some(child => child.type === 'input') && label(node).includes(id === imageId ? 'real storefront' : 'SECOND SOURCE')); find(input, node => node.type === 'input').props.onChange(); return h.render(); }
function sourceReady(h) { for (const preview of nodes(h.render()).filter(node => typeof node.type === 'function' && node.props?.source && node.props.onReady)) preview.props.onReady(true); }
function createReady(h) { selectSource(h); sourceReady(h); checkbox(h.render(), '我已核对本商家真实照片').props.onChange({ target: { checked: true } }); return h.render(); }

test('strict studio rejects cross-merchant data, duplicate image IDs, malformed scope and stopped-customer writes', () => {
  assert.equal(api.verifiedAssetStudio(studio(), 20).customer_id, 20);
  for (const value of [studio({ customer_id: 21 }), studio({ sources: [source(), source()] }), studio({ cooperation_active: false }), studio({ capabilities: { ...studio().capabilities, can_create: 'yes' } })]) assert.throws(() => api.verifiedAssetStudio(value, 20));
});
test('bounded recipes enforce real image IDs, each format type and finite light adjustments', () => {
  assert.equal(api.verifiedAssetRecipe(recipe()).kind, 'poster');
  for (const value of [recipe({ image_ids: [imageId, imageId] }), recipe({ kind: 'collage' }), recipe({ kind: 'video' }), recipe({ image_ids: ['https://untrusted/image'] }), recipe({ exposure: NaN }), recipe({ color: 4 }), recipe({ sharpness: Infinity }), recipe({ rights_confirmed: false })]) assert.throws(() => api.verifiedAssetRecipe(value));
});
test('enhancement preserves original dimensions while poster formats remain explicit', async () => {
  assert.equal(api.verifiedAssetRecipe(recipe({ kind: 'enhance', format: 'original' })).format, 'original');
  assert.throws(() => api.verifiedAssetRecipe(recipe({ kind: 'enhance', format: 'square' })));
  assert.throws(() => api.verifiedAssetRecipe(recipe({ format: 'original' })));
  const h = harness(); await ready(h); find(h.render(), node => node.type === 'button' && label(node).includes('基础照片优化')).props.onClick();
  assert.match(label(h.render()), /保留原图尺寸与比例/); assert.ok(!nodes(h.render()).some(node => node.props?.['aria-label'] === '制作输出尺寸'));
});
test('job validation rejects foreign jobs, unsafe output paths and overwriting original material IDs', () => {
  assert.equal(api.verifiedAssetJob(succeeded(), 20).status, 'succeeded');
  for (const value of [job({ customer_id: 21 }), succeeded({ output: output({ preview_path: 'https://outside.invalid/a.png' }) }), adopted({ adoption: { material_id: 3, image_id: imageId, preview_path: source().preview_path } }), succeeded({ source_stale: true }), job({ can_retry: true }), job({ recipe: recipe({ image_ids: [secondImage] }) })]) assert.throws(() => api.verifiedAssetJob(value, 20));
});
test('video adoption is a new video material and never a Google fixed image', () => {
  const value = adopted({ kind: 'video', recipe: recipe({ kind: 'video', image_ids: [imageId, secondImage] }), sources: [source(), source({ material_id: 4, image_id: secondImage, preview_path: `/api/v1/media-publication-images/${secondImage}/preview` })], output: output({ mime_type: 'video/mp4', duration_seconds: 12 }), adoption: { material_id: 99, image_id: null, preview_path: null } });
  assert.equal(api.verifiedAssetJob(value, 20).adoption.image_id, null);
});
test('receipt proof pins request, merchant, immutable recipe, originals and new profile version', () => {
  const expected = { kind: 'create', request_id: requestId, customer_id: 20, recipe: recipe(), sources: [source()] };
  assert.equal(api.verifiedAssetMutation(mutation('create', job()), expected).job.id, jobId);
  for (const value of [mutation('adopt', job()), mutation('create', job(), null, { customer_id: 21 }), mutation('create', job(), null, { request_id: requestId.replace(/1$/, '2') }), mutation('create', job({ recipe: recipe({ title: 'substituted' }) })), mutation('create', job({ sources: [source({ image_sha256: 'f'.repeat(64) })] }))]) assert.throws(() => api.verifiedAssetMutation(value, expected));
});
test('late profile receipts show a newer current template, while same-version substituted text is rejected', () => {
  const expected = { kind: 'profile', request_id: requestId, customer_id: 20, profile_revision: 1, profile: { ...profile(), revision: undefined } }; delete expected.profile.revision;
  assert.throws(() => api.verifiedAssetMutation(mutation('profile', null, profile({ revision: 2, brand_name: 'changed' })), expected));
  assert.equal(api.verifiedAssetMutation(mutation('profile', null, profile({ revision: 3, brand_name: 'later update' })), expected).profile.revision, 3);
});
test('employees and invalid merchants make no requests', () => {
  for (const props of [{ isOwner: false }, { customerId: 0 }, { customerId: NaN }]) { const h = harness(props); assert.equal(h.render(), null); h.effects(); assert.equal(h.requests.length, 0); }
});
test('opening is one merchant-scoped authenticated GET and does not create jobs or fetch all source bytes', async () => {
  const h = harness(); await ready(h); assert.equal(h.requests[0].options.url, '/api/v1/media-asset-studio/customers/20/studio'); assert.equal(h.requests[0].options.method, 'GET'); assert.ok(h.requests[0].options.options.signal); assert.equal(h.requests.length, 1); assert.ok(!nodes(h.render()).some(node => typeof node.type === 'function' && node.props?.source));
});
test('selected real image suggests confirmed title; production needs bytes, consent, current brand and one click registers once', async () => {
  const h = harness(); await ready(h); selectSource(h); assert.equal(field(h.render(), '素材制作主标题').props.value, source().suggested_title); assert.equal(button(h.render(), '开始私有制作').props.disabled, true);
  sourceReady(h); checkbox(h.render(), '我已核对本商家真实照片').props.onChange({ target: { checked: true } });
  const trigger = button(h.render(), '开始私有制作'); trigger.props.onClick(); trigger.props.onClick(); assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1].options.url, '/api/v1/media-asset-studio/customers/20/jobs'); assert.equal(h.requests[1].options.data.rights_confirmed, true); assert.deepEqual(Array.from(h.requests[1].options.data.image_ids), [imageId]);
  h.requests[1].resolve({ data: mutation('create', job()) }); await tick(); assert.equal(h.held, false); assert.match(label(h.render()), /私有制作任务已登记/); assert.equal(h.requests.filter(row => row.options.method !== 'GET').length, 1);
});
test('typing a title invalidates consent without reloading the same real-photo bytes', async () => {
  const h = harness(); await ready(h); createReady(h); const before = find(h.render(), node => typeof node.type === 'function' && node.props?.source && node.props.onReady);
  field(h.render(), '素材制作主标题').props.onChange({ target: { value: 'Owner adjusted title' } }); const after = find(h.render(), node => typeof node.type === 'function' && node.props?.source && node.props.onReady);
  assert.equal(after.key, before.key); assert.equal(button(h.render(), '开始私有制作').props.disabled, true); checkbox(h.render(), '我已核对本商家真实照片').props.onChange({ target: { checked: true } }); assert.equal(button(h.render(), '开始私有制作').props.disabled, false);
});
test('internal material labels never become public copy when no approved title suggestion exists', async () => {
  const h = harness(); await ready(h, studio({ sources: [source({ title: 'INTERNAL owner upload note', suggested_title: undefined })] }));
  find(find(h.render(), node => node.type === 'label' && label(node).includes('INTERNAL owner upload note')), node => node.type === 'input').props.onChange();
  assert.equal(field(h.render(), '素材制作主标题').props.value, profile().brand_name);
});
test('existing merchant draft titles are reused only by an explicit choice and never trigger AI', async () => {
  const h = harness(); await ready(h, studio({ copy_suggestions: [{ title: 'LOCAL TEST existing reviewed title', subtitle: '', source_label: 'Existing draft' }] }));
  field(h.render(), '复用本商家已有文案').props.onChange('0'); assert.equal(field(h.render(), '素材制作主标题').props.value, 'LOCAL TEST existing reviewed title'); assert.equal(h.requests.length, 1);
});
test('too-light primary text color is explained and blocked before profile submission', async () => {
  const h = harness(); await ready(h); field(h.render(), '商家品牌主色').props.onChange({ target: { value: '#ffffff' } }); assert.equal(api.assetProfileReadable(profile({ primary_color: '#ffffff' })), false); assert.match(label(h.render()), /主色过浅/); button(h.render(), '保存本商家品牌模板').props.onClick(); assert.equal(h.requests.length, 1);
});
test('first brand requires explicit save; changed colors normalize before receipt comparison', async () => {
  const h = harness(); await ready(h, studio({ profile: profile({ revision: 0 }) })); createReady(h); assert.equal(button(h.render(), '开始私有制作').props.disabled, true);
  field(h.render(), '商家品牌主色').props.onChange({ target: { value: '#3344aa' } }); button(h.render(), '保存本商家品牌模板').props.onClick(); assert.equal(h.requests[1].options.data.primary_color, '#3344AA');
  h.requests[1].resolve({ data: mutation('profile', null, profile({ revision: 1, primary_color: '#3344AA' })) }); await tick(); assert.match(label(h.render()), /品牌模板已保存/); assert.equal(h.held, false);
});
test('video is unavailable until the actual capability is true, even with forced clicks', async () => {
  const h = harness(); await ready(h); const video = find(h.render(), node => node.type === 'button' && label(node).includes('真实素材短视频')); assert.equal(video.props.disabled, true);
  video.props.onClick(); createReady(h); button(h.render(), '开始私有制作').props.onClick(); assert.equal(h.requests.length, 1);
});
test('wrong recipe or original hash leaves an unknown operation held without automatic replay', async () => {
  const h = harness(); await ready(h); button(createReady(h), '开始私有制作').props.onClick(); h.requests[1].resolve({ data: mutation('create', job({ sources: [source({ image_sha256: 'f'.repeat(64) })] })) }); await tick(); assert.equal(h.held, true); assert.match(label(h.render()), /原操作结果待确认/); assert.equal(h.requests.length, 2);
});
test('network uncertainty uses original request lookup and only explicit404 permits same-body same-ID retry', async () => {
  const h = harness(); await ready(h); button(createReady(h), '开始私有制作').props.onClick(); const original = h.requests[1].options.data; h.requests[1].reject(new Error('offline')); await tick();
  button(h.render(), '查询原制作操作结果').props.onClick(); assert.equal(h.requests[2].options.url, `/api/v1/media-asset-studio/requests/${requestId}`); h.requests[2].reject({ status: 404 }); await tick();
  assert.equal(button(h.render(), '沿用原编号确认操作').props.disabled, true); checkbox(h.render(), '已核对暂未登记').props.onChange({ target: { checked: true } }); button(h.render(), '沿用原编号确认操作').props.onClick(); assert.deepEqual(h.requests[3].options.data, original);
  h.requests[3].resolve({ data: mutation('create', succeeded()) }); await tick(); assert.equal(h.held, false); assert.match(label(h.render()), /待核对成品/); assert.equal(h.changes.length, 0);
});
test('adoption requires actual output preview, explicit confirmation and creates only a new pending material', async () => {
  const h = harness(); await ready(h, studio({ jobs: [succeeded()] })); assert.equal(button(h.render(), '保存为新团队素材').props.disabled, true);
  find(h.render(), node => typeof node.type === 'function' && node.props?.output).props.onReady(true); checkbox(h.render(), '我已核对实际成品和原图').props.onChange({ target: { checked: true } }); button(h.render(), '保存为新团队素材').props.onClick();
  assert.equal(h.requests[1].options.url, `/api/v1/media-asset-studio/jobs/${jobId}/adopt`); assert.equal(h.requests[1].options.data.output_sha256, hash); assert.equal(h.requests[1].options.data.derivative_confirmed, true);
  h.requests[1].resolve({ data: mutation('adopt', adopted()) }); await tick(); assert.equal(h.changes.length, 1); assert.match(label(h.render()), /没有替换原图、任务或月度清单/); assert.ok(h.requests.every(row => !/publish|schedule|media-monthly|entities/.test(row.options.url)));
});
test('stale sources and stopped cooperation cannot create or adopt, but private history remains readable', async () => {
  const caps = { ...studio().capabilities, can_edit: false, can_create: false, can_adopt: false }, h = harness(); await ready(h, studio({ cooperation_active: false, read_only_reason: 'Stopped', capabilities: caps, jobs: [succeeded({ source_stale: true, can_adopt: false })] }));
  assert.match(label(h.render()), /历史成品不能直接保存采用/); assert.equal(button(h.render(), '保存为新团队素材').props.disabled, true); button(h.render(), '保存为新团队素材').props.onClick(); assert.equal(h.requests.length, 1);
});
test('unknown renderer outcomes do not expose automatic retry; failed task retry remains explicit', async () => {
  const h = harness(); await ready(h, studio({ jobs: [job({ status: 'unknown', can_retry: true })] })); assert.ok(!nodes(h.render()).some(node => label(node) === '重新制作此任务'));
  const failed = harness(); await ready(failed, studio({ jobs: [job({ status: 'failed', can_retry: true })] })); button(failed.render(), '重新制作此任务').props.onClick(); assert.equal(failed.requests[1].options.url, `/api/v1/media-asset-studio/jobs/${jobId}/retry`); assert.equal(failed.requests[1].options.data.expected_revision, 1);
});
test('active-job polling reads only the selected job and stops after the bounded window', async () => {
  const h = harness(); await ready(h, studio({ jobs: [job()] })); h.effects(); assert.equal(h.timers.length, 1); h.timers[0](); await tick();
  assert.equal(h.requests[1].options.url, `/api/v1/media-asset-studio/jobs/${jobId}`); assert.equal(h.requests[1].options.method, 'GET');
  h.requests[1].resolve({ data: job({ status: 'processing', revision: 2 }) }); await tick(); h.render(); h.effects(); h.advance(120001); h.timers.at(-1)(); await tick();
  assert.equal(h.requests.length, 2); assert.match(label(h.render()), /自动查询已暂停/);
});
test('changing real source invalidates old image callbacks and blocks production until current source is verified', async () => {
  const h = harness(); await ready(h, studio({ sources: [source(), source({ title: 'SECOND SOURCE', material_id: 4, image_id: secondImage, preview_path: `/api/v1/media-publication-images/${secondImage}/preview` })] }));
  createReady(h); const old = find(h.render(), node => typeof node.type === 'function' && node.props?.source && node.props.onReady); selectSource(h, secondImage); old.props.onReady(true); checkbox(h.render(), '我已核对本商家真实照片').props.onChange({ target: { checked: true } });
  assert.equal(button(h.render(), '开始私有制作').props.disabled, true); button(h.render(), '开始私有制作').props.onClick(); assert.equal(h.requests.length, 1);
});
test('unmount aborts the initial merchant request and stale responses cannot change the next scope', async () => {
  const h = harness(); h.render(); h.effects(); const signal = h.requests[0].options.options.signal; h.unmount(); assert.equal(signal.aborted, true); h.requests[0].resolve({ data: studio() }); await tick(); assert.ok(!label(h.render()).includes('LOCAL TEST merchant'));
});
test('real private preview rejects modified bytes and validates PNG dimensions before displaying', async () => {
  const bytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7nG6kAAAAASUVORK5CYII=', 'base64'), png = new Blob([bytes], { type: 'image/png' });
  const descriptor = source({ width: 1, height: 1, image_sha256: createHash('sha256').update(bytes).digest('hex'), byte_size: bytes.length });
  let response = png;
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth: async () => ({ data: response }) }, './media-publication-images': imageApi });
  assert.match((await lib.assetStudioPreview(descriptor)).pngUrl, /^data:image\/png;base64,/);
  response = new Blob([bytes.subarray(0, bytes.length - 1)]); await assert.rejects(lib.assetStudioPreview(descriptor), /内容与固定记录不一致/);
  response = png; await assert.rejects(lib.assetStudioPreview({ ...descriptor, width: 2 }), /尺寸与固定记录不一致/);
});
test('private preview ignores late load events after retry and unmount', async () => {
  const bytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7nG6kAAAAASUVORK5CYII=', 'base64');
  const states = [], descriptor = source({ width: 1, height: 1, byte_size: bytes.length, image_sha256: createHash('sha256').update(bytes).digest('hex') });
  const h = harness({ source: descriptor, label: 'LOCAL TEST preview', onReady: value => states.push(value) }, 'AssetPrivatePreview');
  h.render(); h.effects(); h.requests[0].resolve({ data: new Blob([bytes]) }); await new Promise(resolve => setTimeout(resolve, 20));
  const old = find(h.render(), node => node.type === 'img'); old.props.onLoad(); assert.equal(states.at(-1), true); old.props.onError(); button(h.render(), '重新读取私有预览').props.onClick(); h.render(); old.props.onLoad(); assert.equal(states.at(-1), false);
  h.effects(); h.unmount(); old.props.onLoad(); assert.equal(states.at(-1), false); assert.equal(h.requests.at(-1).options.options.signal.aborted, true);
});
test('new studio files contain no publication API, vendor endpoint, native JS dialog or persistent private cache', () => {
  assert.ok(!/\b(?:alert|confirm|prompt)\s*\(/.test(componentSource)); assert.ok(!/localStorage|sessionStorage|googleapis[.]com|facebook[.]com|openai[.]com/.test(apiSource + componentSource)); assert.ok(!/\/publish|\/schedule|\/complete/.test(apiSource + componentSource));
});
