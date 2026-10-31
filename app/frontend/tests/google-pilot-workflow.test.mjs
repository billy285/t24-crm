import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url), ts = require('typescript');
const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(source, imports = {}) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { module, exports: module.exports, require: name => imports[name] || {}, Date, URL, URLSearchParams, Set, Map, console });
  return module.exports;
}
const gbp = compile(read('../src/lib/google-business-api.ts'));
const api = compile(read('../src/lib/google-readiness.ts'), { './google-business-api': gbp });
const images = compile(read('../src/lib/media-publication-images.ts'));
const binding = (overrides = {}) => ({ id: 2, customer_id: 7, customer_name: 'Synthetic merchant', connection_id: 3, location_name: 'accounts/3/locations/2', title: 'Synthetic place', address: 'Synthetic address', active: true, revision: 4, permissions: { can_read: true, can_reply: true, can_publish: true, can_manage: true }, ...overrides });
const task = (overrides = {}) => ({ id: 9, title: 'Synthetic post', content: 'Approved content', revision: 5, material_id: null, material_title: null, has_public_image: false, preview_image_url: null, publish_blocked_reason: null, ...overrides });
const readiness = (overrides = {}) => ({ binding: binding(), task: { id: 9, customer_id: 7, title: 'Synthetic post', status: 'ready', revision: 5, assignee_id: 11, assignee_name: 'Synthetic operator', due_at: '2026-11-03T14:00:00Z', timezone: 'America/New_York' }, checks: [{ key: 'approval', label: 'Approved content', status: 'passed', message: 'Synthetic verified content' }], image_delivery: { enabled: true, scope: 'owner_account', notice: 'Synthetic delivery notice' }, active_action: null, active_schedule: null, can_open_publish: true, can_open_schedule: true, ...overrides });
const action = (overrides = {}) => ({ id: 8, request_id: 'synthetic-request', binding_id: 2, customer_id: 7, kind: 'post_publish', task_id: 9, status: 'unknown', actor_name: 'Synthetic operator', created_at: '2026-11-03T14:00:00Z', updated_at: '2026-11-03T14:00:00Z', provider_state: null, provider_url: null, content: 'Approved content', message: 'Synthetic uncertain result', can_reconcile: true, ...overrides });

test('readiness accepts the exact merchant and task and keeps due time separate from schedule', () => {
  const value = api.verifiedGoogleReadiness(readiness(), 2, 7, 9);
  assert.equal(value.task.due_at, '2026-11-03T14:00:00Z');
  assert.equal(value.active_schedule, null);
});
test('cross merchant, task and operator summary data are rejected', () => {
  assert.throws(() => api.verifiedGoogleReadiness(readiness({ binding: binding({ customer_id: 8 }) }), 2, 7, 9));
  assert.throws(() => api.verifiedGoogleReadiness(readiness(), 3, 7, 9));
  assert.throws(() => api.verifiedGoogleReadiness(readiness(), 2, 7, 10));
  assert.throws(() => api.verifiedGoogleReadiness(readiness({ task: { ...readiness().task, customer_id: 8 } }), 2, 7, 9));
});
test('another merchant or task action cannot appear as this task result', () => {
  for (const overrides of [{ binding_id: 3 }, { customer_id: 8 }, { task_id: 10 }]) assert.throws(() => api.verifiedGoogleReadiness(readiness({ active_action: action(overrides) }), 2, 7, 9));
  assert.equal(api.verifiedGoogleReadiness(readiness({ active_action: action() }), 2, 7, 9).active_action.status, 'unknown');
});
test('historical cancelled schedule is readable without treating it as an active publication', () => {
  const schedule = { id: 5, revision: 2, binding_id: 2, task_id: 9, planned_at: '2026-11-03T14:00:00Z', timezone: 'America/New_York', status: 'cancelled', message: 'Cancelled by synthetic owner', action_id: null };
  assert.equal(api.verifiedGoogleReadiness(readiness({ active_schedule: schedule }), 2, 7, 9).active_schedule.status, 'cancelled');
  assert.throws(() => api.verifiedGoogleReadiness(readiness({ active_schedule: { ...schedule, task_id: 10 } }), 2, 7, 9));
});
test('incomplete and duplicated checks cannot produce a ready presentation', () => {
  for (const bad of [{ can_open_publish: undefined }, { image_delivery: { enabled: true, scope: 'all_users', notice: '' } }, { checks: [] }, { checks: [...readiness().checks, ...readiness().checks] }, { checks: [{ key: 'a', label: 'a', status: 'ready', message: '' }] }]) assert.throws(() => api.verifiedGoogleReadiness(readiness(bad), 2, 7, 9));
});
test('a blocked preview can be read while the actual publish remains disabled', () => {
  const blocked = task({ material_id: 6, publish_blocked_reason: 'Delivery is not enabled' });
  assert.equal(api.googleTaskPublishBlock(blocked), 'Delivery is not enabled');
  assert.equal(api.googleTaskReadyToPublish(blocked, binding(), readiness({ can_open_publish: false })), false);
  assert.equal(api.googleTaskReadyToPublish(task({ material_id: 6 }), binding(), readiness()), false);
});
test('publish requires a fresh exact revision, real publish permission and the ready task status', () => {
  assert.equal(api.googleTaskReadyToPublish(task(), binding(), null), false);
  assert.equal(api.googleTaskReadyToPublish(task(), binding(), readiness()), true);
  assert.equal(api.googleTaskReadyToPublish(task({ revision: 6 }), binding(), readiness()), false);
  assert.equal(api.googleTaskReadyToPublish(task(), binding({ revision: 5 }), readiness()), false);
  assert.equal(api.googleTaskReadyToPublish(task(), binding({ active: false }), readiness()), false);
  assert.equal(api.googleTaskReadyToPublish(task(), binding({ permissions: { can_read: true, can_reply: false, can_publish: false, can_manage: false } }), readiness()), false);
  assert.equal(api.googleTaskReadyToPublish(task(), binding(), readiness({ task: { ...readiness().task, status: 'draft' } })), false);
});

function checklistHarness() {
  const states = [], refs = [], effects = [], queue = [], requests = [], changes = [];
  let stateIndex = 0, refIndex = 0, effectIndex = 0;
  const hooks = {
    useState(initial) { const i = stateIndex++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
    useRef(initial) { const i = refIndex++; if (!(i in refs)) refs[i] = { current: initial }; return refs[i]; },
    useEffect(run, deps) { const i = effectIndex++, old = effects[i]; if (!old || deps.some((value, n) => value !== old.deps[n])) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: run() }; }); },
  };
  const mod = compile(read('../src/components/GoogleReadinessChecklist.tsx'), {
    react: hooks,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    'lucide-react': new Proxy({}, { get: (_, name) => name }), '@/components/ui/button': { Button: 'Button' },
    '@/lib/google-business-api': gbp, '@/lib/google-management-api': { gpmScheduleLabels: { cancelled: '已取消' } },
    '@/lib/media-publication-images': images,
    '@/lib/media-operations-api': { mediaError: (error, fallback) => error.message || fallback, mediaUtcToLocal: value => value },
    '@/lib/google-readiness': { readGoogleReadiness: (binding, taskId) => new Promise((resolve, reject) => requests.push({ bindingId: binding.id, taskId, resolve, reject })) },
  });
  return {
    requests, changes,
    render(scope = 'owner:1', selected = binding(), taskId = 9) { stateIndex = 0; refIndex = 0; effectIndex = 0; return mod.default({ scope, binding: selected, taskId, onReadiness: value => changes.push(value) }); },
    effects() { while (queue.length) queue.shift()(); },
    unmount() { effects.forEach(effect => effect?.cleanup?.()); },
  };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function text(node) { if (node == null || typeof node === 'boolean') return ''; if (typeof node !== 'object') return String(node); if (Array.isArray(node)) return node.map(text).join(''); return text(node.props?.children); }
function nodes(node) { if (node == null || typeof node !== 'object') return []; if (Array.isArray(node)) return node.flatMap(nodes); return [node, ...nodes(node.props?.children)]; }

test('actual checklist only performs read checks and publishes no task or provider operation', async () => {
  const h = checklistHarness(); h.render(); h.effects();
  assert.deepEqual(h.requests.map(x => [x.bindingId, x.taskId]), [[2, 9]]);
  h.requests[0].resolve(readiness()); await tick();
  const tree = h.render();
  assert.match(text(tree), /准备完成目标/);
  assert.match(text(tree), /尚未安排 Google 自动发布时间/);
  assert.equal(nodes(tree).some(x => x.type === 'Button' && /确认发布|保存排期|审核通过/.test(text(x))), false);
});
test('actual checklist rejects a late prior merchant response after A to B to A', async () => {
  const h = checklistHarness(); h.render(); h.effects(); const old = h.requests[0];
  h.render('owner:1', binding({ id: 3, customer_id: 8 })); h.effects();
  h.render(); h.effects(); const current = h.requests[2];
  old.resolve(readiness()); await tick();
  assert.equal(h.changes.filter(Boolean).length, 0);
  current.resolve(readiness()); await tick();
  assert.equal(h.changes.filter(Boolean).length, 1);
});
test('actual checklist clears old eligibility immediately on account change and ignores unmount responses', async () => {
  const h = checklistHarness(); h.render(); h.effects();
  h.requests[0].resolve(readiness()); await tick();
  assert.equal(h.changes.at(-1).can_open_publish, true);
  const tree = h.render('ops:2');
  assert.equal(text(tree).includes('当前条件已核对'), false);
  h.effects(); assert.equal(h.changes.at(-1), null);
  h.unmount(); const before = h.changes.length; h.requests[1].resolve(readiness()); await tick(); assert.equal(h.changes.length, before);
});
test('actual checklist gives a retry instead of showing fake pass when read fails', async () => {
  const h = checklistHarness(); h.render(); h.effects(); h.requests[0].reject(new Error('Synthetic revoked access')); await tick();
  const tree = h.render(); assert.match(text(tree), /Synthetic revoked access/); assert.equal(text(tree).includes('当前条件已核对'), false);
  const refresh = nodes(tree).find(x => x.props?.['aria-label'] === '重新核对开工条件'); refresh.props.onClick(); h.render(); h.effects(); assert.equal(h.requests.length, 2);
});

function workspaceHarness() {
  const source = read('../src/components/GoogleBusinessWorkspace.tsx');
  const names = [...source.matchAll(/\[\s*(\w+)\s*,\s*\w+\s*\]\s*=\s*useState/g)].map(x => x[1]);
  const states = [], refs = [], requests = []; let stateIndex = 0, refIndex = 0, requestId = 0;
  const hooks = {
    useState(initial) { const i = stateIndex++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
    useRef(initial) { const i = refIndex++; if (!(i in refs)) refs[i] = { current: initial }; return refs[i]; },
    useEffect() {}, useCallback: value => value, useMemo: value => value(),
  };
  const fallback = new Proxy({}, { get: (_, name) => name === '__esModule' ? true : String(name) });
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    module, exports: module.exports, URL, Date, Set, Map, console,
    require(name) {
      if (name === 'react') return hooks;
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
      if (name === '@/lib/google-business-api') return { ...gbp, googleBusinessApi: (path, method, body) => { requests.push({ path, method, body }); return new Promise(() => {}); } };
      if (name === '@/lib/google-readiness') return api;
      if (name === '@/lib/media-publication-images') return images;
      if (name === '@/lib/use-unsaved-changes') return { useUnsavedChanges: () => ({ markSaved() {}, confirmDiscard: () => true }), useHardNavigationBlock: () => ({ lock() {}, release() {} }) };
      if (name === '@/lib/media-operations-api') return { mediaErrorStatus: error => error.status, mediaError: (error, fallback) => error.message || fallback, mediaRequestId: () => `synthetic-${++requestId}` };
      if (name === '@/lib/google-business-ai-api') return { googleReviewNeedsOwner: () => false };
      return fallback;
    },
  });
  return {
    requests,
    set(name, value) { const index = names.indexOf(name); assert.ok(index >= 0, `State ${name} exists`); states[index] = value; },
    get(name) { return states[names.indexOf(name)]; },
    render() { stateIndex = 0; refIndex = 0; return module.exports.default({ scope: 'owner:1', isOwner: true, onOpenTask() {} }); },
  };
}
function seedWorkspace(h, value = task()) {
  h.render();
  h.set('state', { enabled: true, configured: true, setup_missing: [], is_owner: true, connections: [], bindings: [binding()] });
  h.set('loading', false); h.set('selectedId', 2); h.set('section', 'posts'); h.set('tasks', [value]);
  return h.render();
}
function workspaceButton(tree, label) { const result = nodes(tree).find(x => x.type === 'Button' && text(x) === label); assert.ok(result, `Button ${label}`); return result; }

test('actual blocked Google task opens its complete preview but forced submit sends no public request', () => {
  const h = workspaceHarness(), blocked = task({ publish_blocked_reason: 'Synthetic delivery blocked' });
  let tree = seedWorkspace(h, blocked), preview = workspaceButton(tree, '核对发布预览');
  assert.equal(Boolean(preview.props.disabled), false); preview.props.onClick();
  h.set('confirmed', true); h.set('publishReadiness', readiness({ can_open_publish: false })); tree = h.render();
  const submit = workspaceButton(tree, '确认发布到 Google'); assert.equal(submit.props.disabled, true);
  submit.props.onClick(); assert.equal(h.requests.length, 0); assert.match(h.get('modalError'), /Synthetic delivery blocked/);
});
test('actual public submit rejects absent and stale advisory snapshots even if checkbox was checked', () => {
  for (const snapshot of [null, readiness({ task: { ...readiness().task, revision: 6 } }), readiness({ binding: binding({ customer_id: 8 }) })]) {
    const h = workspaceHarness(); seedWorkspace(h); h.set('modal', { kind: 'publish', binding: binding(), task: task() }); h.set('confirmed', true); h.set('publishReadiness', snapshot);
    const submit = workspaceButton(h.render(), '确认发布到 Google'); assert.equal(submit.props.disabled, true); submit.props.onClick(); assert.equal(h.requests.length, 0);
  }
});
test('actual refreshed preflight clears an earlier public confirmation', () => {
  const h = workspaceHarness(); seedWorkspace(h); h.set('modal', { kind: 'publish', binding: binding(), task: task() }); h.set('confirmed', true); h.set('publishReadiness', readiness());
  const check = nodes(h.render()).find(x => typeof x.props?.onReadiness === 'function'); assert.ok(check);
  check.props.onReadiness(readiness()); assert.equal(h.get('confirmed'), false);
  const submit = workspaceButton(h.render(), '确认发布到 Google'); assert.equal(submit.props.disabled, true); submit.props.onClick(); assert.equal(h.requests.length, 0);
});
test('actual fresh public confirmation retains the exact reviewed task revision and rejects double clicks', () => {
  const h = workspaceHarness(); seedWorkspace(h); h.set('modal', { kind: 'publish', binding: binding(), task: task() }); h.set('confirmed', true); h.set('publishReadiness', readiness());
  const submit = workspaceButton(h.render(), '确认发布到 Google'); assert.equal(Boolean(submit.props.disabled), false); submit.props.onClick(); submit.props.onClick();
  assert.equal(h.requests.length, 1); assert.deepEqual(JSON.parse(JSON.stringify(h.requests[0])), { path: '/bindings/2/posts', method: 'POST', body: { request_id: 'synthetic-1', task_id: 9, expected_revision: 5, confirmed: true } });
});
