import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const apiSource = read('../src/lib/google-onboarding-api.ts'), componentSource = read('../src/components/GoogleOnboardingWorkspace.tsx');
const stamp = '2026-11-02T04:00:00Z', catalogId = 'a'.repeat(32), batchId = 'b'.repeat(32), hash = 'c'.repeat(64);
const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const customer = (id, extra = {}) => ({ id, name: `LOCAL TEST merchant ${id}`, status: 'closed', address: `${id} Verified Street`, city: 'Houston', state: 'TX', country: 'US', ...extra });
const google = (id, extra = {}) => ({ location_name: `accounts/1/locations/${id}`, title: `LOCAL TEST Google location ${id}`, address: `${id - 90} Verified Street, Houston, TX, US`, observed_at: stamp, ...extra });
const catalogSummary = (extra = {}) => ({ id: catalogId, connection_id: 1, customer_id: null, status: 'ready', revision: 2, observed_at: stamp, expires_at: '2026-11-02T04:10:00Z', message: 'LOCAL TEST complete authorized inventory', error_code: null, total_locations: 5, truncated: false, ...extra });
const binding = (extra = {}) => ({ id: 50, customer_id: 14, location_name: google(104).location_name, active: true, title: customer(14).name, address: '', google_identity: null, ...extra });
const context = (extra = {}) => ({ is_owner: true, customer_id: null, customers: [10, 11, 12, 13, 14].map(id => customer(id)), connections: [{ id: 1, label: 'LOCAL TEST current account', active: true, needs_reconnect: false, connected_at: stamp, last_error: null }, { id: 2, label: 'LOCAL TEST second account', active: true, needs_reconnect: false, connected_at: stamp, last_error: null }], bindings: [binding()], recent_catalogs: [], recent_batches: [], worker_enabled: true, ...extra });
const catalog = (extra = {}) => ({ is_owner: true, customer_id: null, catalog: catalogSummary(), locations: [100, 101, 102, 103, 104].map(id => google(id)), comparisons: [10, 11, 12, 13, 14].map(id => ({ customer: customer(id), match_state: id < 12 ? 'eligible' : id < 14 ? 'review_needed' : 'already_bound', reasons: id < 12 ? ['LOCAL TEST verified fields ready for owner review'] : ['LOCAL TEST owner must check address'], candidates: [google(id + 90)], existing_binding: id === 14 ? binding({ google_identity: google(104) }) : null })), ...extra });
const counts = (extra = {}) => ({ total: 2, queued: 0, processing: 0, bound: 0, conflict: 0, failed: 0, cancelled: 0, unknown: 0, ...extra });
const summary = (extra = {}) => ({ id: batchId, catalog_id: catalogId, customer_id: null, status: 'preview', revision: 1, preview_hash: hash, expires_at: '2026-11-02T04:05:00Z', created_at: stamp, updated_at: stamp, message: 'LOCAL TEST frozen identity preview only', counts: counts(), ...extra });
const batch = (extra = {}) => ({ is_owner: true, customer_id: null, batch: summary(), items: [10, 11].map((id, i) => ({ id: String(i + 1).repeat(32), position: i + 1, customer: customer(id), google: google(id + 90), status: 'preview', warnings: [], binding_id: null, message: 'LOCAL TEST not bound', error_code: null, request_id: uuid(id) })), ...extra });
const receipt = (kind, requestId, resource = batchId) => ({ request_id: requestId, kind, resource_id: resource, created_at: stamp });
const queued = () => batch({ batch: summary({ status: 'queued', revision: 2, counts: counts({ queued: 2 }) }), items: batch().items.map(row => ({ ...row, status: 'queued' })) });
const partial = () => batch({ batch: summary({ status: 'partial', revision: 3, counts: counts({ bound: 1, conflict: 1 }) }), items: batch().items.map((row, index) => ({ ...row, status: index ? 'conflict' : 'bound', binding_id: index ? null : 60, message: index ? 'LOCAL TEST address changed, not bound' : 'LOCAL TEST bound' })) });
const tick = () => new Promise(resolve => setImmediate(resolve));
function compile(source, imports = {}, globals = {}) { const module = { exports: {} }; vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: name => imports[name] || {}, Date, Intl, Map, Set, AbortController, URLSearchParams, setTimeout, clearTimeout, ...globals }); return module.exports; }
const api = compile(apiSource);
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, check) => { const node = nodes(tree).find(check); assert.ok(node, 'Expected onboarding control'); return node; };
const button = (tree, text) => find(tree, node => ['Button', 'button'].includes(node.type) && label(node) === text);
const field = (tree, aria) => find(tree, node => node.props?.['aria-label'] === aria);
const checkbox = (tree, text) => find(find(tree, node => node.type === 'label' && label(node).includes(text)), node => node.type === 'input' && node.props.type === 'checkbox');
function harness(initial = {}, storage = new Map()) {
  let states = [], refs = [], effects = [], queue = [], si = 0, ri = 0, ei = 0, key = null, counter = 100, clock = Date.parse(stamp), props = { scope: 'owner:1', isOwner: true, onClose() {}, ...initial }, autoContext = null;
  const requests = [], timers = [], changes = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((value, index) => value === b[index]);
  class ClockDate extends Date { static now() { return clock; } }
  const hooks = { useState(value) { const i = si++; if (!(i in states)) states[i] = typeof value === 'function' ? value() : value; return [states[i], next => { states[i] = typeof next === 'function' ? next(states[i]) : next; }]; }, useRef(value) { const i = ri++; if (!(i in refs)) refs[i] = { current: value }; return refs[i]; }, useEffect(callback, deps) { const i = ei++, old = effects[i]; if (!old || !equal(old.deps, deps)) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: callback() }; }); } };
  const invokeWithAuth = options => new Promise((resolve, reject) => { const row = { options, resolve, reject }; requests.push(row); if (autoContext && options.url.includes('/context')) resolve({ data: autoContext }); });
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth } });
  const fallback = new Proxy({}, { get: (_, name) => name === '__esModule' ? true : String(name) });
  const jsx = (type, props, key) => typeof type === 'function' && type.name === 'IdentityComparison' ? type(props) : ({ type, props, key });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx, jsxs: jsx }, '@/lib/google-onboarding-api': lib, '@/lib/media-operations-api': { mediaError: (cause, message) => cause?.message || message, mediaErrorStatus: cause => cause?.status, mediaRequestId: () => uuid(counter++) } }, { get: (value, name) => value[name] || fallback });
  const component = compile(componentSource, imports, { Date: ClockDate, document: { visibilityState: 'visible' }, sessionStorage: { getItem: name => storage.get(name) ?? null, setItem: (name, value) => storage.set(name, value), removeItem: name => storage.delete(name) }, setTimeout: (callback, delay) => { const row = { callback, delay, cancelled: false }; timers.push(row); return row; }, clearTimeout: timer => { if (timer) timer.cancelled = true; } }).default;
  return { requests, timers, changes, storage, render() { const outer = component({ ...props, onChanged: () => changes.push(true) }); if (!outer) return null; if (key !== outer.key) { effects.forEach(effect => effect?.cleanup?.()); states = []; refs = []; effects = []; queue = []; key = outer.key; } si = ri = ei = 0; return outer.type(outer.props); }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); }, setProps(next) { props = { ...props, ...next }; }, advance(ms) { clock += ms; }, setAutoContext(value) { autoContext = value; }, async timer() { const available = timers.filter(row => !row.cancelled).sort((a, b) => a.delay - b.delay); assert.ok(available.length); const row = available[0]; row.cancelled = true; clock += row.delay; row.callback(); await tick(); } };
}
async function ready(h, value = context()) { h.render(); h.effects(); h.setAutoContext(value); h.requests[0].resolve({ data: value }); await tick(); return h.render(); }
async function discoverReady(h, value = catalog()) { let tree = await ready(h); field(tree, '接入使用的 Google 连接').props.onChange('1'); tree = h.render(); button(tree, '读取 Google 门店').props.onClick(); const request = h.requests.find(row => row.options.method === 'POST'); request.resolve({ data: { ...value, request_receipt: receipt('discovery', request.options.data.request_id, catalogId) } }); await tick(); return h.render(); }
function pick(h, id) { const tree = h.render(); field(tree, `为 LOCAL TEST merchant ${id} 选择 Google 门店`).props.onChange(google(id + 90).location_name); field(h.render(), `确认 LOCAL TEST merchant ${id} 的名称地址并加入本批`).props.onChange({ target: { checked: true } }); return h.render(); }
async function previewReady(h) { await discoverReady(h); pick(h, 10); pick(h, 11); button(h.render(), '预检所选对应关系').props.onClick(); const request = h.requests.filter(row => row.options.method === 'POST').at(-1); request.resolve({ data: { ...batch(), request_receipt: receipt('preview', request.options.data.request_id) } }); await tick(); return h.render(); }

test('strict DTOs reject wrong scope including null, forged identities and physical-location aliases', () => {
  assert.equal(api.verifiedOnboardingContext(context(), null).customers.length, 5);
  assert.throws(() => api.verifiedCatalogResponse(catalog({ customer_id: 10, catalog: catalogSummary({ customer_id: 10 }) }), null));
  assert.throws(() => api.verifiedCatalogResponse(catalog(), 10));
  const malformed = catalog(); malformed.comparisons[0].candidates[0].title = 'SUBSTITUTED'; assert.throws(() => api.verifiedCatalogResponse(malformed, null));
  const duplicated = batch(); duplicated.items[1].google.location_name = 'accounts/2/locations/100'; assert.throws(() => api.verifiedBatchResponse(duplicated, null));
  assert.equal(api.onboardingLocationKey('accounts/2/locations/100'), '100');
  assert.throws(() => api.verifiedCatalogResponse(catalog({ catalog: catalogSummary({ total_locations: 4 }) }), null));
  assert.throws(() => api.verifiedCatalogResponse(catalog({ catalog: catalogSummary({ status: 'processing' }) }), null));
});
test('nameless CRM read-only rows do not break the catalog and cannot join a batch', async () => {
  const missing = customer(10, { name: '' }), ctx = context({ customers: context().customers.map(row => row.id === 10 ? missing : row) }), directory = catalog();
  directory.comparisons[0] = { ...directory.comparisons[0], customer: missing, match_state: 'review_needed', reasons: ['CRM名称缺失，请先补充；本行不可批量接入'] };
  assert.equal(api.verifiedOnboardingContext(ctx, null).customers[0].name, ''); assert.equal(api.verifiedCatalogResponse(directory, null).comparisons.length, 5);
  const invalidBatch = batch(); invalidBatch.items[0].customer = missing; assert.throws(() => api.verifiedBatchResponse(invalidBatch, null));
  const h = harness(); await discoverReady(h, directory); assert.match(label(h.render()), /LOCAL TEST merchant 11/); button(h.render(), '需要进一步确认3').props.onClick(); const tree = h.render();
  assert.match(label(tree), /名称待补充 · 客户 10/); assert.match(label(tree), /不能加入接入批次/); assert.ok(!nodes(tree).some(row => row.props?.['aria-label'] === '为  选择 Google 门店'));
  assert.ok(!nodes(tree).some(row => row.props?.['aria-label'] === '确认  的名称地址并加入本批'));
});
test('receipt recovery uses original UUID, kind, resource, preview version and exact selected pairs', () => {
  const expected = { request_id: uuid(1), kind: 'confirm', customer_id: null, resource_id: batchId, preview_hash: hash, pairs: batch().items.map(row => ({ customer_id: row.customer.id, location_name: row.google.location_name })) };
  const value = { is_owner: true, request_receipt: receipt('confirm', uuid(1)), catalog: null, batch: partial() };
  assert.equal(api.verifiedOnboardingRequest(value, expected).batch.status, 'partial');
  for (const change of [{ ...expected, request_id: uuid(2) }, { ...expected, kind: 'cancel' }, { ...expected, preview_hash: 'd'.repeat(64) }, { ...expected, resource_id: 'e'.repeat(32) }, { ...expected, pairs: [{ customer_id: 10, location_name: google(101).location_name }] }]) assert.throws(() => api.verifiedOnboardingRequest(value, change));
});
test('only opaque request pointers can be restored; no names addresses or pair cache', () => {
  const pointer = { request_id: uuid(1), kind: 'confirm', customer_id: null, resource_id: batchId };
  assert.equal(api.onboardingRecoveryPointer(JSON.stringify(pointer), null).resource_id, batchId);
  assert.equal(api.onboardingRecoveryPointer(JSON.stringify({ ...pointer, customer_id: 10 }), null), null);
  assert.equal(api.onboardingRecoveryPointer(JSON.stringify({ ...pointer, address: 'PRIVATE' }), null), null);
});
test('staff and invalid customer props make no requests', () => { for (const props of [{ isOwner: false }, { customerId: 0 }, { customerId: -1 }]) { const h = harness(props); assert.equal(h.render(), null); h.effects(); assert.equal(h.requests.length, 0); } });
test('discovery is explicitly requested, async and never preselects proposed mappings', async () => {
  const h = harness(); const tree = await discoverReady(h); assert.equal(h.requests.filter(row => row.options.method === 'POST').length, 1);
  assert.equal(nodes(tree).filter(row => row.type === 'input' && row.props.type === 'checkbox' && row.props.checked).length, 0);
  assert.match(label(tree), /LOCAL TEST Google location 100/); assert.match(label(tree), /10 Verified Street/);
  assert.ok(button(tree, '预检所选对应关系').props.disabled);
  assert.equal(h.requests.find(row => row.options.method === 'POST').options.url, '/api/v1/google-business/onboarding/catalogs');
});
test('queued discovery polls GET only and incomplete results never claim definite no-match', async () => {
  const h = harness(); await discoverReady(h, catalog({ catalog: catalogSummary({ status: 'processing', revision: 1, observed_at: null, expires_at: null, total_locations: 0 }), locations: [], comparisons: [] })); h.effects(); await h.timer();
  const request = h.requests.at(-1); assert.equal(request.options.method, 'GET'); assert.match(request.options.url, /\/catalogs\//);
  request.resolve({ data: catalog({ catalog: catalogSummary({ truncated: true }), comparisons: [] }) }); await tick(); const tree = h.render();
  assert.match(label(tree), /本次门店清单未完整返回/); assert.match(label(tree), /不能据此判断不存在或未授权/); h.unmount();
});
test('preview freezes only explicitly checked pairs and does not bind before final confirmation', async () => {
  const h = harness(); const tree = await previewReady(h), posts = h.requests.filter(row => row.options.method === 'POST');
  assert.equal(posts.length, 2); assert.equal(posts[1].options.url, '/api/v1/google-business/onboarding/previews');
  assert.deepEqual(JSON.parse(JSON.stringify(posts[1].options.data.items)), [{ customer_id: 10, location_name: google(100).location_name }, { customer_id: 11, location_name: google(101).location_name }]);
  assert.ok(button(tree, '确认接入 2 家').props.disabled); assert.match(label(tree), /此预检尚未创建绑定/);
});
test('connection changes invalidate old directory choices preview and stale callbacks', async () => {
  const h = harness(); await previewReady(h); field(h.render(), '接入使用的 Google 连接').props.onChange('2'); const tree = h.render();
  assert.ok(!label(tree).includes('等待你确认对应关系')); assert.ok(!label(tree).includes('确认接入 2 家'));
  assert.equal(field(tree, '接入使用的 Google 连接').props.value, '2'); assert.match(label(tree), /请重新读取这个连接/);
});
test('an unknown confirm never auto-resubmits and original-request GET restores per-item partial results', async () => {
  const h = harness(); await previewReady(h); checkbox(h.render(), '我已核对本批 2 组客户与门店').props.onChange({ target: { checked: true } }); button(h.render(), '确认接入 2 家').props.onClick();
  const post = h.requests.filter(row => row.options.method === 'POST').at(-1); post.reject(new Error('LOCAL TEST timeout')); await tick();
  let tree = h.render(); assert.match(label(tree), /原请求已保留/); const count = h.requests.filter(row => row.options.method === 'POST').length;
  button(tree, '查询原请求').props.onClick(); const get = h.requests.at(-1); assert.equal(get.options.url, `/api/v1/google-business/onboarding/requests/${post.options.data.request_id}`);
  get.resolve({ data: { is_owner: true, request_receipt: receipt('confirm', post.options.data.request_id), catalog: null, batch: partial() } }); await tick(); tree = h.render();
  assert.match(label(tree), /部分已接入/); assert.match(label(tree), /address changed/); assert.equal(h.requests.filter(row => row.options.method === 'POST').length, count); assert.ok(h.changes.length);
});
test('reload restores the saved UUID by GET without repeating confirmation', async () => {
  const storage = new Map([['t24-google-onboarding-request:v1:owner:1:all', JSON.stringify({ request_id: uuid(7), kind: 'confirm', customer_id: null, resource_id: batchId })]]);
  const h = harness({}, storage); await ready(h, context({ recent_catalogs: [catalogSummary()] })); const get = h.requests.at(-1);
  assert.equal(get.options.url, `/api/v1/google-business/onboarding/requests/${uuid(7)}`);
  get.resolve({ data: { is_owner: true, request_receipt: receipt('confirm', uuid(7)), catalog: null, batch: partial() } }); await tick();
  assert.match(label(h.render()), /部分已接入/); assert.equal(h.requests.filter(row => row.options.method === 'POST').length, 0);
});
test('opaque-pointer404 has a safe explicit local exit and keeps original UUID queryable after reload', async () => {
  const storage = new Map([['t24-google-onboarding-request:v1:owner:1:all', JSON.stringify({ request_id: uuid(70), kind: 'confirm', customer_id: null, resource_id: batchId })]]);
  const h = harness({}, storage); await ready(h, context({ recent_batches: [summary({ status: 'completed', counts: counts({ bound: 2 }) })] })); h.requests.at(-1).reject({ status: 404, message: 'LOCAL TEST original not found yet' }); await tick();
  const record = button(h.render(), '本批接入已完成11/2 12:00 · 2 家 · 已绑定 2'); assert.equal(record.props.disabled, false);
  assert.ok(button(h.render(), '结束本地等待，保留原编号').props.disabled); checkbox(h.render(), '我理解只是结束本页等待').props.onChange({ target: { checked: true } }); button(h.render(), '结束本地等待，保留原编号').props.onClick(); await tick();
  assert.equal(storage.has('t24-google-onboarding-request:v1:owner:1:all'), false); assert.match(label(h.render()), /服务器是否执行仍待确认/); assert.match(label(h.render()), new RegExp(uuid(70))); assert.equal(h.requests.filter(row => row.options.method === 'POST').length, 0); h.unmount();
  const next = harness({}, storage); await ready(next); assert.equal(next.requests.length, 1); button(next.render(), '查询保留请求').props.onClick(); assert.equal(next.requests.at(-1).options.url, `/api/v1/google-business/onboarding/requests/${uuid(70)}`); assert.equal(next.requests.filter(row => row.options.method === 'POST').length, 0); next.unmount();
});
test('old owner responses cannot populate a new actor workspace', async () => {
  const h = harness(); h.render(); h.effects(); const old = h.requests[0]; h.setProps({ scope: 'owner:2' }); h.render(); h.effects(); old.resolve({ data: context() }); await tick();
  assert.ok(!label(h.render()).includes('LOCAL TEST current account')); h.unmount();
});
test('expired catalog and preview disable acceptance while preserving read-only evidence', async () => {
  const h = harness(); await previewReady(h); checkbox(h.render(), '我已核对本批 2 组客户与门店').props.onChange({ target: { checked: true } }); assert.equal(button(h.render(), '确认接入 2 家').props.disabled, false); h.effects(); await h.timer(); const tree = h.render(); assert.ok(button(tree, '确认接入 2 家').props.disabled); assert.match(label(tree), /预检已过期/); h.unmount();
});
test('a definitive original-request404 permits only explicit identical UUID and body replay', async () => {
  const h = harness(); await previewReady(h); checkbox(h.render(), '我已核对本批 2 组客户与门店').props.onChange({ target: { checked: true } }); button(h.render(), '确认接入 2 家').props.onClick(); const original = h.requests.filter(row => row.options.method === 'POST').at(-1); original.reject(new Error('LOCAL TEST transport unknown')); await tick();
  button(h.render(), '查询原请求').props.onClick(); h.requests.at(-1).reject({ status: 404, message: 'LOCAL TEST not reserved' }); await tick(); assert.ok(button(h.render(), '以原编号重新提交').props.disabled);
  checkbox(h.render(), '已查询原编号且当前未查到').props.onChange({ target: { checked: true } }); button(h.render(), '以原编号重新提交').props.onClick(); const replay = h.requests.filter(row => row.options.method === 'POST').at(-1); assert.equal(replay.options.url, original.options.url); assert.deepEqual(replay.options.data, original.options.data);
  replay.resolve({ data: { ...queued(), request_receipt: receipt('confirm', original.options.data.request_id) } }); await tick(); h.unmount();
});
test('stopping remaining work is explicit and keeps previously bound rows in the result', async () => {
  const storage = new Map([['t24-google-onboarding-request:v1:owner:1:all', JSON.stringify({ request_id: uuid(8), kind: 'confirm', customer_id: null, resource_id: batchId })]]); const h = harness({}, storage); await ready(h, context({ recent_catalogs: [catalogSummary()] }));
  const processing = queued(); processing.batch.counts = counts({ bound: 1, queued: 1 }); processing.items[0] = { ...processing.items[0], status: 'bound', binding_id: 60 };
  h.requests.at(-1).resolve({ data: { is_owner: true, request_receipt: receipt('confirm', uuid(8)), catalog: null, batch: processing } }); await tick(); button(h.render(), '停止尚未完成的接入').props.onClick(); assert.ok(button(h.render(), '确认停止剩余接入').props.disabled);
  field(h.render(), '停止本批剩余接入的原因').props.onChange({ target: { value: 'LOCAL TEST pause remaining' } }); checkbox(h.render(), '仅停止还未完成的行').props.onChange({ target: { checked: true } }); button(h.render(), '确认停止剩余接入').props.onClick();
  const post = h.requests.filter(row => row.options.method === 'POST').at(-1); assert.match(post.options.url, /\/cancel$/); assert.equal(post.options.data.expected_revision, 2);
  const stopped = { ...processing, batch: summary({ status: 'cancelled', revision: 3, counts: counts({ bound: 1, cancelled: 1 }) }), items: processing.items.map((row, index) => index ? { ...row, status: 'cancelled' } : row) };
  post.resolve({ data: { ...stopped, request_receipt: receipt('cancel', post.options.data.request_id) } }); await tick(); assert.match(label(h.render()), /已停止剩余接入/); assert.match(label(h.render()), /已绑定/); h.unmount();
});
test('same frozen batch progress preserves stop intent while cancel submits the latest revision', async () => {
  const storage = new Map([['t24-google-onboarding-request:v1:owner:1:all', JSON.stringify({ request_id: uuid(80), kind: 'confirm', customer_id: null, resource_id: batchId })]]); const h = harness({}, storage); await ready(h, context({ recent_catalogs: [catalogSummary()] }));
  h.requests.at(-1).resolve({ data: { is_owner: true, request_receipt: receipt('confirm', uuid(80)), catalog: null, batch: queued() } }); await tick(); button(h.render(), '停止尚未完成的接入').props.onClick(); field(h.render(), '停止本批剩余接入的原因').props.onChange({ target: { value: 'LOCAL TEST preserve stop intent' } }); checkbox(h.render(), '仅停止还未完成的行').props.onChange({ target: { checked: true } });
  button(h.render(), '刷新本批结果').props.onClick(); h.requests.at(-1).resolve({ data: { ...queued(), batch: summary({ status: 'processing', revision: 3, counts: counts({ queued: 1, processing: 1 }) }), items: queued().items.map((row, i) => i ? row : { ...row, status: 'processing' }) } }); await tick();
  assert.equal(checkbox(h.render(), '仅停止还未完成的行').props.checked, true); assert.equal(field(h.render(), '停止本批剩余接入的原因').props.value, 'LOCAL TEST preserve stop intent'); button(h.render(), '确认停止剩余接入').props.onClick(); assert.equal(h.requests.at(-1).options.data.expected_revision, 3); h.unmount();
});
test('existing bindings cannot be selected and current Google identity is separate from CRM alias', async () => {
  const h = harness(); await discoverReady(h); button(h.render(), '已绑定 · 保持不变1').props.onClick(); const tree = h.render();
  assert.match(label(tree), /LOCAL TEST Google location 104/); assert.match(label(tree), /本次读取资料/);
  assert.ok(!nodes(tree).some(row => row.props?.['aria-label'] === '为 LOCAL TEST merchant 14 选择 Google 门店'));
});
test('integration adds only owner onboarding entries without changing merchant status badges or grants', () => {
  const merchant = read('../src/components/MediaMerchantWorkspace.tsx'), googleWorkspace = read('../src/components/GoogleBusinessWorkspace.tsx');
  assert.match(merchant, /isOwner && view === 'merchants' && customerId === null/); assert.match(merchant, /GoogleOnboardingWorkspace scope=\{scope\} isOwner=\{isOwner\}/);
  assert.match(googleWorkspace, /entry.kind === 'bind'.*setOnboardingTarget\(customerId \?\? entry.customerId\)/);
  assert.match(googleWorkspace, /onboardingTarget \?\? undefined/);
  assert.match(merchant, /merchant.platforms.map\(platform => <span/);
  assert.ok(!componentSource.includes('/grants') && !componentSource.includes('/publish') && !componentSource.includes('/schedule') && !componentSource.includes('beforeunload'));
});
