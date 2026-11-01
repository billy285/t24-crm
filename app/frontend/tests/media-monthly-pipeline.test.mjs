import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const apiSource = source('../src/lib/media-monthly-workflow-api.ts');
const componentSource = source('../src/components/MediaMonthlyPipeline.tsx');
const stamp = '2026-11-01T03:42:00Z', hash = 'a'.repeat(64), previewHash = 'c'.repeat(64), imageId = 'b'.repeat(32);
const requestId = '00000000-0000-4000-8000-000000000001';
class ClockDate extends Date { static now() { return Date.parse(stamp); } }
function compile(body, imports = {}) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: name => imports[name] || {}, Date: ClockDate, Set, Map, AbortController, console });
  return module.exports;
}
const images = compile(source('../src/lib/media-publication-images.ts'));
const constants = { MONTHLY_PILOT_CUSTOMER_ID: 20, MONTHLY_PILOT_MONTH: '2026-11' };
const api = compile(apiSource, { './media-publication-images': images, './media-monthly-api': constants });
const image = (extra = {}) => ({ id: imageId, customer_id: 20, material_id: 3, source_sha256: hash, image_sha256: hash, width: 289, height: 312, byte_size: 201000, rights_basis: 'client_provided', created_at: stamp, revoked_at: null, status: 'ready', preview_path: `/api/v1/media-publication-images/${imageId}/preview`, can_revoke: true, ...extra });
const material = (extra = {}) => ({ id: 3, title: 'LOCAL TEST store photo', linked_item_id: null, approval_status: 'pending', copyright_status: 'unknown', image_versions: [image()], fingerprint: hash, width: 289, height: 312, quality_warning: 'LOCAL TEST original metadata pending', needs_quality_confirmation: true, ...extra });
const items = () => [3, 5, 7, 10, 12, 14, 17, 19, 21, 24, 26, 28].map((day, index) => ({ item_id: index + 1, slot_id: `202611${String(day).padStart(2, '0')}`, title: `LOCAL TEST title ${index + 1}`, content: `LOCAL TEST public copy ${index + 1}`, owner_summary: `仅内部中文核对 ${index + 1}`, proposed_publish_at: `2026-11-${String(day).padStart(2, '0')}T17:00:00Z`, timezone: 'America/Chicago', revision: 2, copy_hash: hash, material_id: 3, image_version_id: imageId, image_sha256: hash, publication_image: image(), quality_warnings: [], task_id: null, schedule: null }));
const packet = (extra = {}) => ({ id: 7, revision: 1, status: 'prepared', preview_hash: previewHash, source_hash: hash, reviewed_at: null, created_at: stamp, updated_at: stamp, expires_at: '2026-11-02T03:42:00Z', ...extra });
const workflow = (extra = {}) => ({ run_id: 1, customer_id: 20, month: '2026-11', run_revision: 13, source_stale: false, workflow: null, items: items(), materials: [material()], binding: { id: 4, revision: 3, customer_id: 20, customer_name: 'LOCAL TEST Northern', title: 'LOCAL TEST Google Northern', primary_operator_id: 1, primary_operator_name: 'LOCAL TEST owner' }, delivery: { enabled: false, can_manage: true, notice: 'LOCAL TEST private delivery remains off', activated_at: null }, scheduler: { enabled: true, activation_from: '2026-10-30T19:42:04Z' }, checks: [], alerts: [], counts: { total: 12, scheduled: 0, succeeded: 0, blocked: 0, unknown: 0, missed: 0, cancelled: 0 }, capabilities: { is_owner: true, can_prepare: true, can_review: false, can_schedule: false, can_cancel: false }, ...extra });
const prepared = (extra = {}) => workflow({ workflow: packet(), capabilities: { is_owner: true, can_prepare: false, can_review: true, can_schedule: false, can_cancel: true }, ...extra });
const reviewed = (extra = {}) => prepared({ workflow: packet({ status: 'reviewed', revision: 2, reviewed_at: stamp }), items: items().map(item => ({ ...item, task_id: item.item_id + 100 })), delivery: { enabled: true, can_manage: true, notice: 'LOCAL TEST delivery on', activated_at: stamp }, capabilities: { is_owner: true, can_prepare: false, can_review: false, can_schedule: true, can_cancel: true }, ...extra });
const scheduled = (extra = {}) => reviewed({ workflow: packet({ status: 'scheduled', revision: 3, reviewed_at: stamp }), items: reviewed().items.map(item => ({ ...item, schedule: { id: item.item_id + 200, revision: 1, binding_id: 4, task_id: item.task_id, timezone: item.timezone, status: 'scheduled', message: 'LOCAL TEST waits until due', action_id: null, planned_at: item.proposed_publish_at } })), counts: { ...workflow().counts, scheduled: 12 }, capabilities: { is_owner: true, can_prepare: false, can_review: false, can_schedule: false, can_cancel: true }, ...extra });
const receipt = (data, kind) => ({ ...data, request_receipt: { request_id: requestId, kind, workflow_revision: data.workflow.revision, result_hash: hash } });
const run = (extra = {}) => ({ id: 1, customer_id: 20, revision: 13, status: 'generated', ...extra });
const tick = () => new Promise(resolve => setImmediate(resolve));
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, predicate) => { const result = nodes(tree).find(predicate); assert.ok(result, 'Expected pipeline control'); return result; };
const button = (tree, text) => find(tree, item => ['Button', 'button'].includes(item.type) && label(item) === text);
const checkbox = (tree, text) => find(find(tree, item => item.type === 'label' && label(item).includes(text)), item => item.type === 'input' && item.props.type === 'checkbox');
const check = (h, text) => { checkbox(h.render(), text).props.onChange({ target: { checked: true } }); return h.render(); };
function harness(initial = {}) {
  const states = [], refs = [], effects = [], memos = [], queue = [], requests = [], active = [], changed = [], reloaded = [];
  let si = 0, ri = 0, ei = 0, mi = 0, held = false, props = { scope: 'owner:1', run: run(), isOwner: true, parentBlocked: false, ...initial };
  const equal = (a, b) => a && b && a.length === b.length && a.every((value, index) => value === b[index]);
  const hooks = {
    useState(value) { const index = si++; if (!(index in states)) states[index] = typeof value === 'function' ? value() : value; return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }]; },
    useRef(value) { const index = ri++; if (!(index in refs)) refs[index] = { current: value }; return refs[index]; },
    useEffect(callback, deps) { const index = ei++, old = effects[index]; if (!old || !equal(old.deps, deps)) queue.push(() => { old?.cleanup?.(); effects[index] = { deps, cleanup: callback() }; }); },
    useMemo(callback, deps) { const index = mi++; if (!memos[index] || !equal(memos[index].deps, deps)) memos[index] = { deps, value: callback() }; return memos[index].value; },
  };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth }, './media-publication-images': images, './media-monthly-api': constants });
  const fallback = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) }, '@/lib/media-monthly-workflow-api': lib, '@/lib/media-monthly-api': constants, '@/lib/media-operations-api': { mediaError: (error, message) => error?.message || message, mediaErrorStatus: error => error?.status, mediaRequestId: () => requestId, mediaUtcToLocal: (value, zone) => `${value.slice(0, 10)}T${zone === 'Asia/Shanghai' ? '01:00' : '11:00'}` }, '@/lib/use-unsaved-changes': { confirmDiscardAllChanges: () => !held, useUnsavedChanges: () => ({ markSaved() {} }), useHardNavigationBlock: () => ({ lock() { held = true; }, release() { held = false; } }) } }, { get: (value, key) => value[key] || fallback });
  const Component = compile(componentSource, imports).default;
  return { requests, active, changed, reloaded, get held() { return held; }, setProps(next) { props = { ...props, ...next }; }, render() { si = ri = ei = mi = 0; const tree = Component({ ...props, onPacketActive: value => active.push(value), onReloadRun: () => reloaded.push(true), onChanged: () => changed.push(true) }); return tree && typeof tree.type === 'function' ? tree.type(tree.props) : tree; }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); } };
}
async function ready(h, data = workflow()) { h.render(); h.effects(); assert.equal(h.requests.length, 1); h.requests[0].resolve({ data }); await tick(); return h.render(); }
function photosReady(h) { for (const preview of nodes(h.render()).filter(item => item.type === 'PublicationImagePreview')) preview.props.onStateChange('ready'); return h.render(); }
function prepareReady(h) { photosReady(h); check(h, '我已核对所选真实图片'); return check(h, '保留现有12篇文案'); }
async function finishMutation(h, data, kind) { h.requests.at(-1).resolve({ data: receipt(data, kind) }); await tick(); assert.equal(h.requests.at(-1).options.method, 'GET'); assert.equal(h.requests.at(-1).options.url, '/api/v1/media-monthly/runs/1/workflow'); h.requests.at(-1).resolve({ data }); await tick(); return h.render(); }

test('strict workflow rejects cross-owner scope, wrong batch/month, duplicate slots and altered Chicago dates', () => {
  assert.equal(api.verifiedMonthlyWorkflow(workflow(), 1).items.length, 12);
  for (const value of [workflow({ customer_id: 21 }), workflow({ run_id: 2 }), workflow({ month: '2026-12' }), workflow({ capabilities: { ...workflow().capabilities, is_owner: false } }), workflow({ items: items().map(item => ({ ...item, slot_id: '20261103' })) }), workflow({ items: items().map((item, index) => index === 1 ? { ...item, proposed_publish_at: items()[0].proposed_publish_at } : item) })]) assert.throws(() => api.verifiedMonthlyWorkflow(value, 1));
});
test('fixed images must match the item hash, merchant, material and one immutable metadata identity', () => {
  for (const patch of [{ publication_image: image({ customer_id: 21 }) }, { publication_image: image({ image_sha256: 'f'.repeat(64) }) }, { publication_image: image({ width: 300 }) }]) {
    const value = prepared({ items: items().map((item, index) => index === 1 ? { ...item, ...patch } : item) });
    assert.throws(() => api.verifiedMonthlyWorkflow(value, 1));
  }
  assert.equal(api.monthlyWorkflowImages(api.verifiedMonthlyWorkflow(prepared(), 1)).length, 1);
});
test('formal schedule rows cannot attach another binding, task, timezone or proposed date', () => {
  for (const patch of [{ binding_id: 9 }, { task_id: 999 }, { timezone: 'Asia/Shanghai' }, { planned_at: '2026-11-03T16:00:00Z' }]) assert.throws(() => api.verifiedMonthlyWorkflow(scheduled({ items: scheduled().items.map((item, index) => index === 0 ? { ...item, schedule: { ...item.schedule, ...patch } } : item) }), 1));
});
test('staff, another merchant and non-generated legacy runs issue zero pipeline requests', () => {
  for (const props of [{ isOwner: false }, { run: run({ customer_id: 21 }) }, { run: run({ status: 'adopted' }) }]) { const h = harness(props); assert.equal(h.render(), null); h.effects(); assert.equal(h.requests.length, 0); }
});
test('opening the pipeline makes one local workflow read with cancellation and no provider, AI or write', async () => {
  const h = harness(); await ready(h);
  assert.equal(h.requests[0].options.url, '/api/v1/media-monthly/runs/1/workflow');
  assert.equal(h.requests[0].options.method, 'GET'); assert.ok(h.requests[0].options.options.signal);
  assert.deepEqual(h.active, [false]); assert.equal(h.requests.length, 1);
});
test('twelve copies sharing a photo verify one unique private image and prepare once without changing copy', async () => {
  const h = harness(); await ready(h); assert.equal(nodes(h.render()).filter(item => item.type === 'PublicationImagePreview').length, 1);
  assert.equal(button(h.render(), '准备本月审核清单，保留文案').props.disabled, true);
  const trigger = button(prepareReady(h), '准备本月审核清单，保留文案'); trigger.props.onClick(); trigger.props.onClick();
  assert.equal(h.requests.length, 2); const request = h.requests[1];
  assert.equal(request.options.url, '/api/v1/media-monthly/runs/1/prepare'); assert.equal(request.options.data.expected_run_revision, 13);
  assert.equal(request.options.data.items.length, 12); assert.ok(request.options.data.items.every(item => item.image_version_id === imageId && item.rights_confirmed === true));
  assert.equal(request.options.data.expected_workflow_revision, 0); assert.equal(request.options.data.facts_confirmed, true);
  await finishMutation(h, prepared(), 'prepare'); assert.deepEqual(h.active.slice(-1), [true]);
  assert.match(label(h.render()), /本月完整审核清单/); assert.equal(nodes(h.render()).filter(item => item.props?.className === 'mm-flow-copy').length, 12);
  assert.ok(h.requests.every(request => !/google-business|publish|images\/delivery|customers\/20\/runs$/.test(request.options.url)));
});
test('changing selected photo invalidates all previous image callbacks and material consent', async () => {
  const other = image({ id: 'd'.repeat(32), image_sha256: 'e'.repeat(64), preview_path: `/api/v1/media-publication-images/${'d'.repeat(32)}/preview` });
  const h = harness(); await ready(h, workflow({ materials: [material({ image_versions: [image(), other] })] }));
  const old = find(h.render(), item => item.type === 'PublicationImagePreview'); prepareReady(h);
  find(h.render(), item => item.props?.['aria-label'] === '本月清单配图 1').props.onChange(other.id);
  old.props.onStateChange('ready'); check(h, '我已核对所选真实图片'); check(h, '保留现有12篇文案');
  assert.equal(button(h.render(), '准备本月审核清单，保留文案').props.disabled, true);
});
test('low-resolution or unavailable versions are excluded from preparation even if forced into selection', async () => {
  const low = image({ width: 145, height: 156 }), h = harness(); await ready(h, workflow({ items: items().map(item => ({ ...item, publication_image: low })), materials: [material({ image_versions: [low] })] }));
  check(h, '我已核对所选真实图片'); check(h, '保留现有12篇文案'); button(h.render(), '准备本月审核清单，保留文案').props.onClick();
  assert.equal(h.requests.length, 1); assert.match(label(h.render()), /暂无符合尺寸/);
});
test('internal monthly review never activates schedules and needs new photo verification on every read', async () => {
  const h = harness(); await ready(h, prepared()); const original = find(h.render(), item => item.type === 'PublicationImagePreview'); photosReady(h);
  button(check(h, '我已核对北方面食 Google 商家的这12篇'), '整月审核通过，暂不排期').props.onClick();
  assert.equal(h.requests[1].options.url, '/api/v1/media-monthly/runs/1/review');
  assert.equal(h.requests[1].options.data.preview_hash, previewHash); assert.equal(h.requests[1].options.data.confirmed, true);
  await finishMutation(h, reviewed(), 'review'); assert.equal(h.requests.filter(request => request.options.method === 'POST').length, 1);
  original.props.onStateChange('ready'); check(h, '我确认将上方12篇已审核');
  assert.equal(button(h.render(), '确认整月排期并启用到期发布').props.disabled, true);
  assert.match(label(h.render()), /内容审核已通过，尚未创建正式排期/);
});
test('formal scheduling needs its own explicit public confirmation, current images and delivery state', async () => {
  const h = harness(); await ready(h, reviewed()); photosReady(h);
  assert.equal(button(h.render(), '确认整月排期并启用到期发布').props.disabled, true);
  button(h.render(), '确认整月排期并启用到期发布').props.onClick(); assert.equal(h.requests.length, 1);
  button(check(h, '我确认将上方12篇已审核'), '确认整月排期并启用到期发布').props.onClick();
  const body = h.requests[1].options.data; assert.equal(body.publication_confirmed, true); assert.equal(body.confirmation_version, 'monthly-publication-v1');
  assert.equal(body.preview_hash, previewHash); assert.equal(h.requests[1].options.url, '/api/v1/media-monthly/runs/1/schedule');
  await finishMutation(h, scheduled(), 'schedule'); assert.match(label(h.render()), /正式排期已保存/);
});
test('disabled delivery, scheduler, stale sources or expiry block scheduling even with forced checkbox events', async () => {
  for (const patch of [{ delivery: { ...reviewed().delivery, enabled: false } }, { scheduler: { enabled: false, activation_from: null } }, { source_stale: true }, { workflow: packet({ status: 'reviewed', revision: 2, expires_at: '2026-10-31T00:00:00Z' }) }]) {
    const h = harness(); await ready(h, reviewed(patch)); photosReady(h); check(h, '我确认将上方12篇已审核'); button(h.render(), '确认整月排期并启用到期发布').props.onClick(); assert.equal(h.requests.length, 1);
  }
});
test('delivery settings are opt-in, reuse the existing policy panel and never arm the month automatically', async () => {
  const h = harness(); await ready(h, reviewed()); photosReady(h);
  assert.equal(nodes(h.render()).filter(item => item.type === 'MediaImageDeliveryPolicy').length, 0);
  button(check(h, '我确认将上方12篇已审核'), '真实排期前核对图片投递').props.onClick();
  assert.equal(nodes(h.render()).filter(item => item.type === 'MediaImageDeliveryPolicy').length, 1);
  check(h, '我确认将上方12篇已审核'); button(h.render(), '确认整月排期并启用到期发布').props.onClick();
  assert.equal(h.requests.length, 1);
  find(h.render(), item => item.type === 'MediaImageDeliveryPolicy').props.onChanged();
  assert.equal(h.requests.at(-1).options.url, '/api/v1/media-monthly/runs/1/workflow');
  assert.equal(h.requests.filter(request => request.options.method === 'POST').length, 0);
});
test('wrong receipt, changed copy or substituted image causes unknown rather than a successful preparation claim', async () => {
  for (const patch of ['receipt', 'copy', 'photo']) {
    const h = harness(); await ready(h); button(prepareReady(h), '准备本月审核清单，保留文案').props.onClick();
    let value = receipt(prepared(), 'prepare');
    if (patch === 'receipt') value.request_receipt.request_id = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
    if (patch === 'copy') value.items[0].content = 'Different public copy';
    if (patch === 'photo') value.items[0].image_version_id = 'd'.repeat(32);
    h.requests[1].resolve({ data: value }); await tick(); assert.equal(h.held, true); assert.match(label(h.render()), /结果待确认/); assert.equal(h.requests.length, 2);
  }
});
test('unknown scheduling recovers only the original UUID; explicit absent-result retry preserves exact request body', async () => {
  const h = harness(); await ready(h, reviewed()); photosReady(h); button(check(h, '我确认将上方12篇已审核'), '确认整月排期并启用到期发布').props.onClick();
  const original = h.requests[1]; original.reject(new Error('network')); await tick(); assert.equal(h.held, true);
  button(h.render(), '读取原流程操作结果').props.onClick(); assert.equal(h.requests[2].options.url, `/api/v1/media-monthly/workflow-requests/${requestId}`);
  h.requests[2].reject({ status: 404 }); await tick(); assert.equal(h.requests.filter(request => request.options.method === 'POST').length, 1);
  button(check(h, '我已核对暂未登记'), '沿用原流程请求确认').props.onClick(); assert.deepEqual(h.requests[3].options, original.options);
});
test('late historical recovery conflict reads current cancelled state and cannot restore an old scheduled phase', async () => {
  const h = harness(); await ready(h, reviewed()); photosReady(h); button(check(h, '我确认将上方12篇已审核'), '确认整月排期并启用到期发布').props.onClick(); h.requests[1].reject(new Error('network')); await tick();
  button(h.render(), '读取原流程操作结果').props.onClick(); h.requests[2].reject({ status: 409 }); await tick();
  assert.equal(h.requests[3].options.url, '/api/v1/media-monthly/runs/1/workflow');
  h.requests[3].resolve({ data: workflow({ workflow: packet({ status: 'cancelled', revision: 4 }) }) }); await tick();
  assert.equal(h.held, false); assert.match(label(h.render()), /批次版本已有变化/); assert.equal(label(h.render()).includes('正式排期已开启'), false);
  assert.equal(h.requests.filter(request => request.options.method === 'POST').length, 1);
});
test('failed current-state read after a receipt keeps later actions blocked', async () => {
  const h = harness(); await ready(h, prepared()); photosReady(h); button(check(h, '我已核对北方面食 Google 商家的这12篇'), '整月审核通过，暂不排期').props.onClick();
  h.requests[1].resolve({ data: receipt(reviewed(), 'review') }); await tick(); h.requests[2].reject(new Error('current read unavailable')); await tick();
  assert.equal(button(h.render(), '整月审核通过，暂不排期').props.disabled, true); assert.equal(nodes(h.render()).some(item => ['Button', 'button'].includes(item.type) && label(item) === '确认整月排期并启用到期发布'), false); assert.match(label(h.render()), /当前清单尚未重新读取成功/);
});
test('cancellation needs an explicit reason and only uses the local cancel endpoint, preserving copy', async () => {
  const h = harness(); await ready(h, scheduled());
  button(h.render(), '确认撤回，保留文案').props.onClick(); assert.equal(h.requests.length, 1);
  find(h.render(), item => item.props?.['aria-label'] === '撤回本月清单原因').props.onChange({ target: { value: 'LOCAL TEST owner withdrew' } });
  button(check(h, '确认撤回本批次尚未执行'), '确认撤回，保留文案').props.onClick(); assert.equal(h.requests[1].options.url, '/api/v1/media-monthly/runs/1/cancel');
  const cancelled = scheduled({ workflow: packet({ status: 'cancelled', revision: 4 }), items: scheduled().items.map(item => ({ ...item, schedule: { ...item.schedule, status: 'cancelled' } })), counts: { ...workflow().counts, cancelled: 12 } });
  await finishMutation(h, cancelled, 'cancel'); assert.equal(h.active.at(-1), false); assert.match(label(h.render()), /文案保留/);
});
test('stopping remaining jobs preserves already-public or unknown results and keeps immutable history visible', async () => {
  for (const originalState of ['succeeded', 'unknown', 'accepted', 'dispatching']) {
    const before = scheduled({ items: scheduled().items.map((item, index) => index === 0 ? { ...item, schedule: { ...item.schedule, status: originalState, action_id: requestId } } : item) });
    const h = harness(); await ready(h, before);
    find(h.render(), item => item.props?.['aria-label'] === '撤回本月清单原因').props.onChange({ target: { value: 'Stop remaining dates' } });
    button(check(h, '确认撤回本批次尚未执行'), '确认撤回，保留文案').props.onClick();
    const after = { ...before, workflow: packet({ status: 'cancelled', revision: 4 }), items: before.items.map((item, index) => index === 0 ? item : { ...item, schedule: { ...item.schedule, status: 'cancelled' } }), counts: { ...workflow().counts, cancelled: 11, succeeded: originalState === 'succeeded' ? 1 : 0, unknown: originalState === 'unknown' ? 1 : 0 }, capabilities: { is_owner: true, can_prepare: false, can_review: false, can_schedule: false, can_cancel: false } };
    await finishMutation(h, after, 'cancel'); assert.equal(h.held, false); assert.equal(h.active.at(-1), true);
    assert.match(label(h.render()), /历史结果保留/); assert.equal(nodes(h.render()).some(item => ['Button', 'button'].includes(item.type) && label(item) === '准备本月审核清单，保留文案'), false);
    assert.equal(after.items[0].schedule.status, originalState);
  }
});
test('cancel receipts cannot add replacement tasks or schedules, or leave untouched future jobs armed', () => {
  const before = scheduled(), body = { request_id: requestId, expected_revision: 3, reason: 'Stop remaining dates' }, mutation = { kind: 'cancel', body };
  const after = receipt({ ...before, workflow: packet({ status: 'cancelled', revision: 4 }), items: before.items.map(item => ({ ...item, schedule: { ...item.schedule, status: 'cancelled' } })) }, 'cancel');
  assert.equal(api.monthlyWorkflowMutationMatches(after, before, mutation), true);
  for (const patch of [{ schedule: { ...after.items[0].schedule, id: 999 } }, { task_id: 999 }, { schedule: { ...after.items[0].schedule, status: 'scheduled' } }]) assert.equal(api.monthlyWorkflowMutationMatches({ ...after, items: after.items.map((item, index) => index === 0 ? { ...item, ...patch } : item) }, before, mutation), false);
});
test('scheduled jobs do not become expired merely because the original confirmation window passed', async () => {
  const h = harness(); await ready(h, scheduled({ workflow: packet({ status: 'scheduled', revision: 3, expires_at: '2026-10-31T00:00:00Z' }) }));
  assert.match(label(h.render()), /每次到期仍核对门店、权限和内容/); assert.equal(label(h.render()).includes('已过期，请撤回'), false);
});
test('parent unsaved edits block preparation and a changed legacy revision requires an explicit reread', async () => {
  const h = harness({ parentBlocked: true }); await ready(h); button(prepareReady(h), '准备本月审核清单，保留文案').props.onClick(); assert.equal(h.requests.length, 1);
  const other = harness(); await ready(other, workflow({ run_revision: 14 })); assert.match(label(other.render()), /文案版本已更新/); button(other.render(), '读取最新草稿版本').props.onClick(); assert.equal(other.reloaded.length, 1);
});
test('alerts remain visible with no automatic retry or dismissal action', async () => {
  const h = harness(); await ready(h, scheduled({ alerts: [{ key: 'schedule:201:unknown', version: '2', run_id: 1, level: 'error', status: 'unknown', title: 'LOCAL TEST result unknown', message: 'Original request must be checked', item_id: 1, task_id: 101, schedule_id: 201, action_id: requestId }], counts: { ...workflow().counts, unknown: 1, scheduled: 11 }, capabilities: { ...scheduled().capabilities, can_cancel: false } }));
  assert.match(label(h.render()), /Original request must be checked/); assert.equal(nodes(h.render()).some(item => ['Button', 'button'].includes(item.type) && /重发|清除异常|确认撤回/.test(label(item))), false); assert.equal(h.requests.length, 1);
});
test('unmount aborts the pending read and ignores every late response and image event', async () => {
  const h = harness(); h.render(); h.effects(); h.unmount(); assert.equal(h.requests[0].options.options.signal.aborted, true); h.requests[0].resolve({ data: prepared() }); await tick(); assert.equal(h.active.length, 0); assert.equal(h.requests.length, 1);
  const other = harness(); await ready(other, prepared()); const old = find(other.render(), item => item.type === 'PublicationImagePreview'); other.unmount(); old.props.onStateChange('ready'); assert.equal(button(check(other, '我已核对北方面食 Google 商家的这12篇'), '整月审核通过，暂不排期').props.disabled, true);
});

test('a cancelled packet with frozen completion history stays read-only even without a schedule row',async()=>{const h=harness();await ready(h,reviewed({workflow:packet({status:'cancelled',revision:4}),history_frozen:true,capabilities:{is_owner:true,can_prepare:false,can_review:false,can_schedule:false,can_cancel:false}}));assert.equal(h.active.at(-1),true);assert.match(label(h.render()),/本月完整审核清单/);assert.equal(nodes(h.render()).some(item=>['Button','button'].includes(item.type)&&label(item)==='准备本月审核清单，保留文案'),false);});
