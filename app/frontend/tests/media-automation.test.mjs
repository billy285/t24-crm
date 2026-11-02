import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const stamp = '2026-11-02T01:00:00Z', hash = 'a'.repeat(64), runtimeHash = 'b'.repeat(64), requestId = '00000000-0000-4000-8000-000000000001';
function compile(body, imports = {}) { const module = { exports: {} }; vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: key => imports[key] || {}, Date, Intl, Set, Map, AbortController }); return module.exports; }
const monthly = compile(source('../src/lib/media-monthly-api.ts'));
const api = compile(source('../src/lib/media-automation-api.ts'), { './media-monthly-api': monthly });
const policy = extra => ({ id: 4, revision: 1, enabled: true, lead_days: 7, timezone: 'America/Denver', local_time: '09:00', profile_revision: 3, source_signature: hash, runtime_fingerprint: runtimeHash, confirmed_at: stamp, updated_at: stamp, ...extra });
const worker = { enabled: false, max_per_tick: 2, owner_daily_limit: 24, global_daily_limit: 72 };
const setup = extra => ({ customer: { id: 38, name: 'LOCAL TEST PokeCo' }, platform: 'instagram', policy: null, timezone: 'America/Denver', next_target_month: '2026-12', next_run_at: '2026-11-24T16:00:00Z', source_signature: hash, runtime: { enabled: true, provider: 'LOCAL TEST', model: 'LOCAL TEST text model', destination_host: 'text.example.test', fingerprint: runtimeHash }, notice: { version: 'monthly-autoprep-v1', text: 'Only confirmed public text, never images or private records.', send_fields: ['confirmed_public_facts'] }, eligibility: { can_enable: true, gaps: [] }, worker, latest_job: null, recent_jobs: [], automatic_publish: false, ...extra });
const job = extra => ({ id: 8, request_id: requestId, month: '2026-12', status: 'generated', run_id: 12, message: 'LOCAL TEST private draft', created_at: stamp, updated_at: stamp, customer_id: 38, customer_name: 'LOCAL TEST PokeCo', platform: 'instagram', ...extra });
const body = extra => ({ request_id: requestId, expected_revision: 0, enabled: true, lead_days: 7, local_time: '09:00', source_signature: hash, runtime_fingerprint: runtimeHash, confirmed: true, notice_version: 'monthly-autoprep-v1', ...extra });
const saved = extra => setup({ policy: policy(), receipt_request_id: requestId, ...extra });
const overview = extra => ({ automatic_publish: false, worker, period_start: '2026-10-02T01:00:00Z', period_end: stamp, counts: { policies: 3, enabled: 2, blocked: 1, unknown: 0, generated: 2 }, recent_jobs: [job({ status: 'blocked', run_id: null })], attention_jobs: [job({ status: 'blocked', run_id: null })], attention_total: 1, ...extra });
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, predicate) => { const value = nodes(tree).find(predicate); assert.ok(value, 'Expected automation control'); return value; };
const button = (tree, name) => find(tree, value => value.type === 'Button' && label(value) === name);
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(extra = {}, overviewMode = false) {
  let si = 0, ri = 0, ei = 0, held = false;
  const states = [], refs = [], effects = [], queue = [], requests = [], changed = [], opened = [];
  const props = { scope: 'owner:1', isOwner: true, customerId: 38, platform: 'instagram', customerName: 'LOCAL TEST PokeCo', visible: true, refreshToken: 0, onOpenMonthly: (...args) => opened.push(args), onOpen: item => opened.push(item), onChanged: () => changed.push(true), ...extra };
  const hooks = { useState(value) { const i = si++; if (!(i in states)) states[i] = typeof value === 'function' ? value() : value; return [states[i], next => states[i] = typeof next === 'function' ? next(states[i]) : next]; }, useRef(value) { const i = ri++; if (!(i in refs)) refs[i] = { current: value }; return refs[i]; }, useEffect(callback, deps) { const i = ei++, old = effects[i]; if (!old || !old.deps || old.deps.some((value, n) => value !== deps[n])) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: callback() }; }); } };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const scopedMonthly = compile(source('../src/lib/media-monthly-api.ts'), { './tokenStore': { invokeWithAuth } });
  const scopedApi = compile(source('../src/lib/media-automation-api.ts'), { './media-monthly-api': scopedMonthly });
  const fallback = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) }, '@/components/ui/button': { Button: 'Button' }, '@/components/ui/native-select': { NativeSelect: 'NativeSelect' }, '@/lib/media-monthly-api': { ...scopedMonthly, currentMonthlyMonth: () => '2026-11' }, '@/lib/media-automation-api': scopedApi, '@/lib/media-operations-api': { mediaError: (cause, message) => cause?.message || message, mediaErrorStatus: cause => cause?.status, mediaRequestId: () => requestId, mediaUtcToLocal: value => value.slice(0, 16) }, '@/lib/use-unsaved-changes': { confirmDiscardAllChanges: () => !held, useUnsavedChanges: () => ({ markSaved() {} }), useHardNavigationBlock: () => ({ lock() { held = true; }, release() { held = false; } }) } }, { get: (value, key) => value[key] || fallback });
  const mod = compile(source(overviewMode ? '../src/components/MediaAutomationOverview.tsx' : '../src/components/MediaAutomationPanel.tsx') + (overviewMode ? '\nexport { OwnerAutomationOverview };' : '\nexport { AutomationSettings };'), imports);
  return { props, requests, opened, changed, get held() { return held; }, render() { si = ri = ei = 0; return overviewMode ? mod.OwnerAutomationOverview(props) : mod.AutomationSettings(props); }, outer() { return mod.default(props); }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); } };
}
async function ready(h, value = setup()) { h.render(); h.effects(); assert.equal(h.requests.length, 1); h.requests[0].resolve({ data: value }); await tick(); return h.render(); }
function enable(h) { const input = find(h.render(), node => node.props?.['aria-label'] === '启用本商家草稿自动准备'); input.props.onChange({ target: { checked: true } }); }
function consent(h) { const row = find(h.render(), node => node.type === 'label' && label(node).includes('我确认按这份')); find(row, node => node.type === 'input').props.onChange({ target: { checked: true } }); }

test('automation setup is pinned to merchant/platform and refuses implied publishing', () => {
  assert.equal(api.verifiedAutomationSetup(setup(), 38, 'instagram').automatic_publish, false);
  for (const value of [setup({ customer: { id: 20, name: 'OTHER' } }), setup({ platform: 'facebook' }), setup({ automatic_publish: true }), setup({ next_run_at: 'unverified' }), setup({ timezone: 'Bad/Zone' }), setup({ policy: policy({ lead_days: 2 }) }), setup({ policy: policy({ timezone: 'Bad/Zone' }) }), setup({ runtime: { ...setup().runtime, fingerprint: 'unverified' } }), setup({ notice: { ...setup().notice, version: 'unknown' } })]) assert.throws(() => api.verifiedAutomationSetup(value, 38, 'instagram'));
});
test('draft-only eligibility may include image warnings; blocked sources cannot claim enable capability', () => {
  assert.equal(api.verifiedAutomationSetup(setup({ eligibility: { can_enable: true, gaps: ['photo is only a private reference'] } }), 38, 'instagram').eligibility.can_enable, true);
  assert.throws(() => api.verifiedAutomationSetup(setup({ source_signature: null }), 38, 'instagram'));
  assert.equal(api.verifiedAutomationSetup(setup({ source_signature: null, runtime: { ...setup().runtime, enabled: false, fingerprint: null }, eligibility: { can_enable: false, gaps: ['source pending'] } }), 38, 'instagram').source_signature, null);
});
test('job records reject missing runs, duplicate identities and cross-shaped provider outcomes', () => {
  for (const value of [job({ run_id: null }), job({ status: 'published' }), job({ month: '2026-13' }), job({ request_id: 'unverified' })]) assert.throws(() => api.verifiedAutomationJob(value));
  assert.throws(() => api.verifiedAutomationSetup(setup({ recent_jobs: [job(), job()] }), 38, 'instagram'));
});
test('save and recovery must match exact request, scope, revision and source pins', () => {
  assert.equal(api.verifiedAutomationSaved(saved(), 38, 'instagram', body()).policy.enabled, true);
  for (const value of [saved({ receipt_request_id: '00000000-0000-4000-8000-000000000002' }), saved({ policy: policy({ revision: 3 }) }), saved({ policy: policy({ source_signature: 'c'.repeat(64) }) }), saved({ policy: policy({ enabled: false }) })]) assert.throws(() => api.verifiedAutomationSaved(value, 38, 'instagram', body()));
  const receipt = { request_id: requestId, customer_id: 38, platform: 'instagram', result: saved(), current_revision: 1 };
  assert.equal(api.verifiedAutomationReceipt(receipt, 38, 'instagram', body()).current_revision, 1);
  for (const patch of [{ customer_id: 20 }, { platform: 'facebook' }, { current_revision: 0 }]) assert.throws(() => api.verifiedAutomationReceipt({ ...receipt, ...patch }, 38, 'instagram', body()));
});
test('worker-disabled configuration never says automation is running or content is approved', () => {
  assert.match(api.automationState(saved()).label, /服务待启用/);
  assert.match(api.automationState(saved({ worker: { ...worker, enabled: true } })).label, /已开启/);
  assert.match(api.automationState(saved({ latest_job: job({ status: 'unknown', run_id: null }) })).label, /需要处理/);
  assert.match(api.automationState(saved({ latest_job: job() })).label, /待审核/);
  assert.match(api.automationState(saved({ source_signature: 'c'.repeat(64), worker: { ...worker, enabled: true } })).label, /资料变化/);
});
test('current-month links follow server merchant target across the year boundary', () => {
  assert.equal(api.automationCurrentMonth(setup({ next_target_month: '2027-01' })), '2026-12');
  assert.equal(api.automationCurrentMonth(setup({ next_target_month: '2026-12' })), '2026-11');
});
test('initial policy preview follows the confirmed merchant timezone rather than Beijing', () => {
  assert.equal(api.automationTimezone(setup()), 'America/Denver');
  assert.equal(api.automationTimezone(setup({ timezone: 'America/Chicago', policy: policy() })), 'America/Chicago');
  assert.equal(api.automationTimezone(setup({ timezone: null, policy: policy() })), 'America/Denver');
  assert.equal(api.automationTimezone(setup({ timezone: null })), 'UTC');
});
test('editorial guidance is optional for legacy runs and cannot attach another item', () => {
  const rules = { timezone: 'America/Denver', weekdays: [2,4,6], local_time: '11:00', posts_per_week: 3, language: 'en', forbidden_claims: [], include_prices: false, generic_mode: true };
  const row = { id: 1, slot_id: '20261103', title: 'LOCAL TEST', content: 'LOCAL TEST', proposed_publish_at: '2026-11-03T18:00:00Z', timezone: 'America/Denver', material_id: null, image_version_id: null, image_sha256: null, menu_item_ids: [], revision: 1, copy_hash: hash, task_id: null, quality_warnings: [], owner_summary: 'LOCAL TEST' };
  const run = { platform: 'instagram', id: 9, customer_id: 38, month: '2026-11', status: 'unknown', revision: 1, input_hash: hash, ai_used: true, message: '', profile_snapshot: { public_facts: { public_name: 'LOCAL TEST', location: 'LOCAL TEST', highlights: [] }, rules }, items: [row], preview_hash: null, adoptable: false, canonical_request_id: requestId };
  assert.equal(monthly.verifiedMonthlyRun(run, 38, 9, '2026-11', 'instagram').editorial_review, undefined);
  const editorial = { version: 'monthly-editorial-v1', needs_review: true, duplicate_groups: 0, process_language_items: 1, warnings: ['Check internal wording'], item_warnings: { 1: ['Internal wording'] } };
  assert.equal(monthly.verifiedMonthlyRun({ ...run, editorial_review: editorial }, 38, 9, '2026-11', 'instagram').editorial_review.needs_review, true);
  for (const patch of [{ version: 'unverified' }, { duplicate_groups: -1 }, { item_warnings: { 2: ['OTHER ITEM'] } }, { item_warnings: { 20261103: ['SLOT ID INSTEAD OF ITEM'] } }]) assert.throws(() => monthly.verifiedMonthlyRun({ ...run, editorial_review: { ...editorial, ...patch } }, 38, 9, '2026-11', 'instagram'));
});
test('staff, invalid merchant and unsupported platform do not mount configuration or make requests', () => {
  for (const props of [{ isOwner: false }, { customerId: 0 }, { customerId: -1 }, { platform: 'tiktok' }]) { const h = harness(props); assert.equal(h.outer(), null); h.effects(); assert.equal(h.requests.length, 0); }
});
test('opening settings is a local read; enabling needs explicit public-text consent and never calls a publisher', async () => {
  const h = harness(); let tree = await ready(h); assert.equal(h.requests[0].options.method, 'GET'); assert.equal(h.requests[0].options.url, '/api/v1/media-monthly/customers/38/automation?platform=instagram');
  assert.match(label(tree), /自动准备服务尚未启用/); enable(h); tree = h.render(); assert.equal(button(tree, '保存自动准备规则').props.disabled, true); consent(h); tree = h.render(); assert.equal(button(tree, '保存自动准备规则').props.disabled, false); button(tree, '保存自动准备规则').props.onClick(); button(tree, '保存自动准备规则').props.onClick();
  assert.equal(h.requests.length, 2); const request = h.requests[1]; assert.equal(request.options.method, 'PUT'); assert.equal(request.options.data.enabled, true); assert.equal(request.options.data.local_time, '09:00'); assert.equal(request.options.data.confirmed, true); assert.equal(request.options.data.source_signature, hash); assert.equal(request.options.data.runtime_fingerprint, runtimeHash); assert.equal(request.options.data.expected_revision, 0); assert.equal(h.held, true);
  request.resolve({ data: saved() }); await tick(); tree = h.render(); assert.equal(h.held, false); assert.match(label(tree), /公开发布和排期权限没有变化/); assert.ok(h.requests.every(row => !/publish|review|schedule|google-business|meta-operations/.test(row.options.url)));
});
test('a changed-source active policy can be paused using original pins without enabling a service', async () => {
  const h = harness(); await ready(h, setup({ policy: policy(), source_signature: null, runtime: { ...setup().runtime, enabled: false, fingerprint: null }, eligibility: { can_enable: false, gaps: ['current sources changed'] } }));
  const input = find(h.render(), node => node.props?.['aria-label'] === '启用本商家草稿自动准备'); assert.equal(input.props.disabled, false); input.props.onChange({ target: { checked: false } }); const tree = h.render(); button(tree, '保存自动准备规则').props.onClick();
  const request = h.requests[1]; assert.equal(request.options.data.enabled, false); assert.equal(request.options.data.confirmed, false); assert.equal(request.options.data.source_signature, hash); assert.equal(request.options.data.runtime_fingerprint, runtimeHash);
  request.resolve({ data: saved({ policy: policy({ revision: 2, enabled: false }) }) }); await tick(); assert.equal(h.held, false); assert.match(label(h.render()), /已暂停后续草稿自动准备/);
});
test('unknown save locks writes and recovers same request through GET without resubmitting', async () => {
  const h = harness(); await ready(h); enable(h); consent(h); button(h.render(), '保存自动准备规则').props.onClick(); h.requests[1].reject(new Error('network response unknown')); await tick(); let tree = h.render(); assert.equal(h.held, true); assert.match(label(tree), /先不要重复保存/); assert.ok(!nodes(tree).some(node => node.type === 'Button' && label(node) === '保存自动准备规则'));
  button(tree, '查询原保存结果').props.onClick(); assert.equal(h.requests.length, 3); assert.equal(h.requests[2].options.method, 'GET'); assert.equal(h.requests[2].options.url, `/api/v1/media-monthly/automation/requests/${requestId}`);
  h.requests[2].resolve({ data: { request_id: requestId, customer_id: 38, platform: 'instagram', result: saved(), current_revision: 1 } }); await tick(); tree = h.render(); assert.equal(h.held, false); assert.match(label(tree), /无需重复提交/); assert.equal(h.requests.filter(row => row.options.method === 'PUT').length, 1);
});
test('a newer policy version after an unknown response is re-read rather than overwritten by the old receipt', async () => {
  const h = harness(); await ready(h); enable(h); consent(h); button(h.render(), '保存自动准备规则').props.onClick(); h.requests[1].reject(new Error('unknown')); await tick(); button(h.render(), '查询原保存结果').props.onClick(); h.requests[2].resolve({ data: { request_id: requestId, customer_id: 38, platform: 'instagram', result: saved(), current_revision: 2 } }); await tick(); assert.equal(h.requests[3].options.method, 'GET'); h.requests[3].resolve({ data: setup({ policy: policy({ revision: 2, enabled: false }) }) }); await tick(); assert.match(label(h.render()), /后来更新的最新规则/); assert.equal(find(h.render(), node => node.props?.['aria-label'] === '启用本商家草稿自动准备').props.checked, false); assert.equal(h.held, false);
});
test('failed reads never imply disabled/no work and late unmounted reads cannot render another store', async () => {
  const h = harness(); h.render(); h.effects(); h.requests[0].reject(new Error('read unavailable')); await tick(); assert.match(label(h.render()), /当前无法确认是否已启用|read unavailable/); assert.doesNotMatch(label(h.render()), /自动准备未设置|尚无自动准备记录/);
  const late = harness(); late.render(); late.effects(); late.unmount(); assert.equal(late.requests[0].options.options.signal.aborted, true); late.requests[0].resolve({ data: setup({ customer: { id: 20, name: 'OTHER STORE' } }) }); await tick(); assert.doesNotMatch(label(late.render()), /OTHER STORE/);
});
test('retained config and overview actions cannot run after unmount or scope change', async () => {
  const h = harness(); await ready(h); enable(h); consent(h); const trigger = button(h.render(), '保存自动准备规则'); h.unmount(); trigger.props.onClick(); assert.equal(h.requests.length, 1);
  const scoped = harness(); await ready(scoped); enable(scoped); consent(scoped); const old = button(scoped.render(), '保存自动准备规则'); scoped.props.scope = 'owner:2'; scoped.render(); old.props.onClick(); assert.equal(scoped.requests.length, 1);
  const o = harness({}, true); const tree = await ready(o, overview()); const target = find(tree, node => node.type === 'button' && label(node).includes('LOCAL TEST PokeCo')); o.unmount(); target.props.onClick(); assert.equal(o.opened.length, 0);
});
test('overview is owner-only, pins explicit affected merchant/platform and fails closed on incomplete counts', async () => {
  assert.equal(api.verifiedAutomationOverview(overview()).recent_jobs[0].customer_id, 38); assert.throws(() => api.verifiedAutomationOverview(overview({ counts: { policies: 1 } }))); assert.throws(() => api.verifiedAutomationOverview(overview({ automatic_publish: true })));
  for (const props of [{ isOwner: false }, { visible: false }]) { const h = harness(props, true); assert.equal(h.outer(), null); h.effects(); assert.equal(h.requests.length, 0); }
  const h = harness({}, true); const tree = await ready(h, overview()); assert.equal(h.requests[0].options.method, 'GET'); const target = find(tree, node => node.type === 'button' && label(node).includes('LOCAL TEST PokeCo')); target.props.onClick(); assert.equal(h.opened[0].customer_id, 38); assert.equal(h.opened[0].platform, 'instagram'); assert.equal(h.opened[0].run_id, null);
});

test('older exceptions remain actionable beyond the latest twenty successful jobs', async () => {
  const old = job({ id: 40, status: 'blocked', run_id: null, customer_name: 'OLDER EXCEPTION' });
  const recent = Array.from({ length: 20 }, (_, i) => job({ id: i + 50, request_id: `00000000-0000-4000-8000-${String(i + 50).padStart(12, '0')}` }));
  const h = harness({}, true), tree = await ready(h, overview({ recent_jobs: recent, attention_jobs: [old] }));
  const action = find(tree, node => node.type === 'button' && label(node).includes('OLDER EXCEPTION'));
  action.props.onClick();
  assert.equal(h.opened[0].id, 40);
  assert.throws(() => api.verifiedAutomationOverview(overview({ attention_jobs: [job()] })));
  assert.throws(() => api.verifiedAutomationOverview(overview({ attention_total: 0 })));
});
