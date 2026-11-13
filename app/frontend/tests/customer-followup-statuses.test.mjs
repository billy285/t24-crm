import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const helperSource = readFileSync(new URL('../src/lib/customer-followup-statuses.ts', import.meta.url), 'utf8');
const context = { exports: {} };
vm.runInNewContext(ts.transpileModule(helperSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context);
const helpers = context.exports;
const source = readFileSync(new URL('../src/lib/dict-config.ts', import.meta.url), 'utf8');
const sf = ts.createSourceFile('dict-config.ts', source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS);
let defaults;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(sf) === 'defaultBusinessDictConfig') defaults = vm.runInNewContext(`(${node.initializer.getText(sf)})`);
  ts.forEachChild(node, visit);
}
visit(sf);
const plain = value => JSON.parse(JSON.stringify(value));
const entries = () => helpers.getCustomerFollowUpStatusEntries(defaults);

test('eight approved service defaults are separate from unchanged sales stages', () => {
  assert.deepEqual(plain(entries().map(entry => entry.label)), ['正常服务', '待客户回复', '需协调处理', '续费跟进', '增购沟通', '暂停服务', '服务结束', '后续跟进']);
  assert.equal(helpers.getDefaultCustomerFollowUpStatus(defaults), 'in_service');
  assert.equal(defaults.customerFollowUpStatusArchive, '');
  assert.equal(defaults.followUpStages, 'new_lead:新线索,contacted:已联系,communicating:沟通中,quoted:已报价,considering:考虑中,pending_close:待成交,closed:已成交,not_closed:未成交,lost:流失,follow_later:后续再跟进');
  assert.equal(helpers.getCustomerFollowUpStatusLabel(defaults, 'follow_later'), '后续再跟进');
  assert.equal(helpers.getCustomerFollowUpStatusLabel(defaults, 'service_follow_later'), '后续跟进');
});

test('stop, restore and reorder preserve stable keys and select only active defaults', () => {
  const draft = entries();
  draft[0].active = false;
  const saved = helpers.serializeCustomerFollowUpStatusEntries(draft);
  assert.equal(helpers.getDefaultCustomerFollowUpStatus(saved), 'awaiting_reply');
  assert.ok(saved.customerFollowUpStatusArchive.includes('in_service:正常服务'));
  const restored = helpers.getCustomerFollowUpStatusEntries(saved);
  restored.find(entry => entry.key === 'in_service').active = true;
  const reordered = [restored.at(-1), ...restored.slice(0, -1)];
  const final = helpers.serializeCustomerFollowUpStatusEntries(reordered);
  assert.equal(helpers.getDefaultCustomerFollowUpStatus(final), 'in_service');
  assert.equal(final.customerFollowUpStatusArchive, '');
});

test('archived stages are absent from new options but explicit in edits and history', () => {
  const config = { ...defaults, customerFollowUpStatuses: 'in_service:正常服务', customerFollowUpStatusArchive: 'old_service:原服务阶段' };
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(config)), [{ value: 'in_service', label: '正常服务' }]);
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(config, 'old_service'))[0], { value: 'old_service', label: '已停用：原服务阶段' });
  assert.equal(helpers.getCustomerFollowUpStatusLabel(config, 'old_service'), '原服务阶段');
});

test('legacy, unknown and empty edit values remain explicit instead of selecting a new service default', () => {
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(defaults, 'communicating'))[0], { value: 'communicating', label: '历史阶段：沟通中' });
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(defaults, 'unknown_legacy'))[0], { value: 'unknown_legacy', label: '历史阶段：unknown_legacy' });
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(defaults, ''))[0], { value: '', label: '历史阶段：未记录' });
  assert.equal(helpers.getCustomerFollowUpStatusLabel(defaults, null), '未记录');
  for (const stage of ['__proto__', 'constructor', 'toString']) {
    assert.equal(helpers.getCustomerFollowUpStatusLabel(defaults, stage), stage);
    assert.equal(helpers.getCustomerFollowUpStatusLabel(defaults, stage, 12), stage);
    assert.equal(typeof helpers.getCustomerFollowUpStatusOptions(defaults, stage)[0].label, 'string');
  }
});

test('linked opportunity rows retain sales meaning and cannot acquire a service option', () => {
  const config = { ...defaults, customerFollowUpStatuses: 'quoted:同名自定义服务' };
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(config, 'quoted', 12)), [{ value: 'quoted', label: '已报价' }]);
  assert.equal(helpers.getCustomerFollowUpStatusLabel(config, 'needs_confirmed', 12), '需求确认');
  assert.equal(helpers.getCustomerFollowUpStatusLabel(config, 'negotiating', 12), '商务沟通');
  assert.deepEqual(plain(helpers.getCustomerFollowUpStatusOptions(config, null, 12)), [{ value: '', label: '未记录' }]);
  assert.equal(helpers.getCustomerFollowUpStatusLabel(config, 'initial', 12), '初步意向');
  assert.equal(helpers.getCustomerFollowUpStatusLabel(config, 'payment_pending', 12), '待收款');
});

test('validation rejects empty or all-stopped configs and duplicate union keys or labels', () => {
  const validate = helpers.validateCustomerFollowUpStatusEntries;
  assert.match(validate([]), /至少保留/);
  assert.match(validate([{ key: 'a', label: '正常服务', active: false }]), /至少保留/);
  assert.match(validate([{ key: 'a', label: '甲', active: true }, { key: 'a', label: '乙', active: false }]), /标识不能重复/);
  assert.match(validate([{ key: 'a', label: 'Alpha', active: true }, { key: 'b', label: ' alpha ', active: false }]), /名称不能重复/);
  assert.throws(() => helpers.serializeCustomerFollowUpStatusEntries([]), /至少保留/);
});

test('validation enforces64-character safe keys,40-codepoint labels and separators/control restrictions', () => {
  const validate = label => helpers.validateCustomerFollowUpStatusEntries([{ key: 'service_a', label, active: true }]);
  assert.equal(validate('甲'.repeat(40)), '');
  assert.equal(validate('😀'.repeat(40)), '');
  assert.match(validate('😀'.repeat(41)), /1–40/);
  for (const label of ['甲,乙', '甲:乙', '甲，乙', '甲：乙', '甲\n乙', '甲\t乙', '甲\u0085乙', '甲\u200b乙', '甲\u3000乙']) assert.match(validate(label), /控制字符/);
  assert.equal(helpers.validateCustomerFollowUpStatusEntries([{ key: 'a'.repeat(64), label: '甲', active: true }]), '');
  for (const key of ['a'.repeat(65), '__proto__', 'a-b', 'a:b']) assert.match(helpers.validateCustomerFollowUpStatusEntries([{ key, label: '甲', active: true }]), /标识无效/);
});

test('new keys are stable and never reuse an active or archived key', () => {
  const key = helpers.createCustomerFollowUpStatusKey(entries(), '后续跟进');
  const repeated = helpers.createCustomerFollowUpStatusKey([...entries(), { key, label: '旧名称', active: false }], '后续跟进');
  assert.match(key, /^service_[a-z0-9_]+$/);
  assert.equal(repeated, `${key}_2`);
  assert.equal(helpers.createCustomerFollowUpStatusKey(entries(), '后续跟进'), key);
});

// Execute the manager's real save callback with a synthetic transport. This
// verifies CAS, draft retention and auth barriers without a browser/data write.
const managerSource = readFileSync(new URL('../src/components/CustomerFollowUpStatusManager.tsx', import.meta.url), 'utf8');
const managerSf = ts.createSourceFile('CustomerFollowUpStatusManager.tsx', managerSource, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
const declarations = new Map();
function capture(node) {
  if (ts.isFunctionDeclaration(node) && ['readStatusResponse', 'errorStatus', 'errorMessage'].includes(node.name?.text)) declarations.set(node.name.text, node.getText(managerSf));
  if (ts.isVariableDeclaration(node) && node.name.getText(managerSf) === 'save') declarations.set('save', `const save = ${node.initializer.getText(managerSf)};`);
  ts.forEachChild(node, capture);
}
capture(managerSf);
assert.equal(declarations.size, 4);
function saveFixture(overrides = {}) {
  const writes = [], cached = [], errors = [], events = [];
  const revision = 'a'.repeat(64);
  const sandbox = {
    exports: {}, ...helpers, endpoint: '/api/v1/app-config/dict_config/customer-followup-statuses',
    canManage: true, actorEpoch: 'session-A', managerScope: '1:admin:session-A', scopeRef: { current: { key: '1:admin:session-A', allowed: true } }, isAuthSessionCurrent: () => true, loading: false, loadError: '', revision, conflict: false,
    saveLock: { current: false }, requestId: { current: { value: 2 } }, newLabel: '', entries: entries(),
    defaultBusinessDictConfig: defaults,
    client: { apiCall: { invoke: async request => { writes.push(plain(request)); return { data: { active: defaults.customerFollowUpStatuses, archive: '', revision: 'b'.repeat(64) } }; } } },
    writeCachedAppConfig: (key, value) => cached.push([key, plain(value)]), readCachedAppConfig: () => ({ ...defaults, unrelated: 'preserved' }),
    setSaving: value => events.push(['saving', value]), setSaveError: value => errors.push(value), setEntries() {}, setBaseline() {}, setRevision() {}, setConflict: value => events.push(['conflict', value]), setLoadError: value => events.push(['loadError', value]),
    draft: { markSaved: () => events.push(['markSaved']) }, onSaved: value => events.push(['onSaved', plain(value)]), toast: { success: () => events.push(['success']) }, onOpenChange: value => events.push(['open', value]),
    ...overrides,
  };
  vm.runInNewContext(ts.transpileModule([...declarations.values()].join('\n') + '\nexports.save = save;', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, sandbox);
  return { save: sandbox.exports.save, writes, cached, errors, events, sandbox };
}

test('manager saves only service fields with the exact server revision and preserves unrelated cache', async () => {
  const f = saveFixture(); await f.save();
  assert.equal(f.writes.length, 1);
  assert.deepEqual(f.writes[0].data, { active: defaults.customerFollowUpStatuses, archive: '', expected_revision: 'a'.repeat(64) });
  assert.equal(f.writes[0].method, 'PATCH');
  assert.equal(f.cached[0][1].unrelated, 'preserved');
  assert.ok(f.events.some(event => event[0] === 'markSaved'));
  assert.ok(f.events.some(event => event[0] === 'open' && event[1] === false));
});

test('manager rejects blocked/invalid/unsent drafts before any request', async () => {
  for (const override of [{ canManage: false }, { isAuthSessionCurrent: () => false }, { loading: true }, { loadError: 'failed' }, { revision: '' }, { conflict: true }, { saveLock: { current: true } }, { newLabel: '还未添加' }, { entries: [] }]) {
    const f = saveFixture(override); await f.save(); assert.equal(f.writes.length, 0);
  }
});

test('409 keeps the draft, blocks stale save and requires explicit reread', async () => {
  const f = saveFixture({ client: { apiCall: { invoke: async () => { throw { response: { status: 409 } }; } } } });
  await f.save();
  assert.equal(f.cached.length, 0);
  assert.ok(f.events.some(event => event[0] === 'conflict' && event[1] === true));
  assert.ok(f.errors.some(error => error.includes('草稿已保留')));
  assert.ok(!f.events.some(event => ['markSaved', 'success', 'open', 'onSaved'].includes(event[0])));
});

test('401/403 remove editable config and never cache a rejected response', async () => {
  for (const status of [401, 403]) {
    const f = saveFixture({ client: { apiCall: { invoke: async () => { throw { status }; } } } }); await f.save();
    assert.equal(f.cached.length, 0); assert.ok(f.events.some(event => event[0] === 'loadError'));
    assert.ok(!f.events.some(event => event[0] === 'success'));
  }
});

test('late save responses after account or request changes cannot update cache or UI', async () => {
  let f;
  f = saveFixture({ client: { apiCall: { invoke: async () => { f.sandbox.requestId.current.value++; return { data: { active: defaults.customerFollowUpStatuses, archive: '', revision: 'b'.repeat(64) } }; } } } });
  await f.save(); assert.equal(f.cached.length, 0); assert.ok(!f.events.some(event => event[0] === 'success'));
  let current = true;
  const changed = saveFixture({ isAuthSessionCurrent: () => current, client: { apiCall: { invoke: async () => { current = false; return { data: { active: defaults.customerFollowUpStatuses, archive: '', revision: 'b'.repeat(64) } }; } } } });
  await changed.save(); assert.equal(changed.cached.length, 0); assert.ok(!changed.events.some(event => event[0] === 'success'));
});

test('render-time role withdrawal blocks a pending PATCH before effect cleanup runs', async () => {
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  const f = saveFixture({ client: { apiCall: { invoke: () => pending } } });
  const saving = f.save();
  f.sandbox.scopeRef.current = { key: '1:ops:session-A', allowed: false };
  resolve({ data: { active: defaults.customerFollowUpStatuses, archive: '', revision: 'b'.repeat(64) } });
  await saving;
  assert.equal(f.cached.length, 0);
  assert.ok(!f.events.some(event => ['markSaved', 'success', 'open', 'onSaved'].includes(event[0])));
});

test('render-time role withdrawal blocks a pending GET before effect cleanup runs', async () => {
  let effect;
  function findEffect(node) {
    if (ts.isCallExpression(node) && node.expression.getText(managerSf) === 'useEffect') effect = node.arguments[0].getText(managerSf);
    ts.forEachChild(node, findEffect);
  }
  findEffect(managerSf);
  let resolve;
  const pending = new Promise(done => { resolve = done; }), writes = [];
  const sandbox = { exports: {}, ...helpers, endpoint: '/api/v1/app-config/dict_config/customer-followup-statuses', open: true, canManage: true, actorEpoch: 'session-A', managerScope: '1:admin:session-A', scopeRef: { current: { key: '1:admin:session-A', allowed: true } }, requestId: { current: { value: 0 } }, isAuthSessionCurrent: () => true, client: { apiCall: { invoke: () => pending } } };
  for (const name of ['setEntries', 'setRevision', 'setBaseline', 'setLoading', 'setSaving', 'setLoadError', 'setSaveError', 'setConflict', 'setNewLabel']) sandbox[name] = value => writes.push([name, value]);
  vm.runInNewContext(ts.transpileModule([...declarations].filter(([name]) => name !== 'save').map(([, code]) => code).join('\n') + `\nexports.effect = ${effect};`, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, sandbox);
  const cleanup = sandbox.exports.effect();
  const before = writes.length;
  sandbox.scopeRef.current = { key: '1:ops:session-A', allowed: false };
  resolve({ data: { active: defaults.customerFollowUpStatuses, archive: '', revision: 'b'.repeat(64) } });
  await new Promise(done => setImmediate(done));
  assert.equal(writes.length, before);
  cleanup();
});
