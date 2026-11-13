import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/pages/Customers.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('Customers.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const compile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
function pureModule(path) {
  const mod = { exports: {} };
  vm.runInNewContext(`(function(module,exports){${compile(fs.readFileSync(new URL(path, import.meta.url), 'utf8'))}\n})`)(mod, mod.exports);
  return mod.exports;
}
const permission = pureModule('../src/lib/customer-permissions.ts');
const guards = pureModule('../src/lib/customer-detail-refresh.ts');
const functions = new Map(); const effectCallbacks = []; let autoCallback;
function scan(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && ts.isArrowFunction(node.initializer)) functions.set(node.name.text, node.initializer.getText(ast));
  if (ts.isCallExpression(node) && node.expression.getText(ast) === 'useEffect') effectCallbacks.push(node.arguments[0]?.getText(ast));
  if (ts.isCallExpression(node) && node.expression.getText(ast) === 'useAutoRefresh') autoCallback = node.arguments[0].getText(ast);
  ts.forEachChild(node, scan);
}
scan(ast);
const names = ['clearCustomerDetailAssociations', 'invalidateCustomerDetailRequests', 'withdrawCustomerDetail', 'loadCustomerDetail', 'checkCustomerDetailAccess', 'loadCustomers', 'loadEmployees'];
const moduleNames = ['basic', 'contacts', 'followups', 'opportunities', 'delivery', 'renewals', 'deals', 'materials'];
const permissions = () => ({ access_level: 'read_write', finance_access: 'profit', modules: Object.fromEntries(moduleNames.map(key => [key, { read: true, write: true }])), can_manage_access: true, can_delete: true, can_export: true, can_reassign: true, reveal_secrets: true, sources: [], explicit: true });
const customer = () => ({ id: 1, business_name: 'Synthetic reading customer', status: 'closed', effective_permissions: permissions() });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)); };
function fixture() {
  const accepted = customer(), calls = [], sets = [];
  const state = { selectedCustomer: accepted, selectedCustomerTab: 'followups', customers: [accepted], detailLoadedAt: 'accepted-before-read', detailLoading: false, detailRefreshing: false, showFollowForm: false };
  for (const key of ['FollowUps', 'Deals', 'Payments', 'CustomerRefunds', 'CustomerExpenses', 'Subscriptions', 'RenewalSubscriptions', 'CustomerProjects', 'ServiceProgresses', 'ServiceTasks', 'Contacts']) state[key[0].toLowerCase() + key.slice(1)] = [{ id: `accepted-${key}` }];
  let nextCustomer = customer(), transport;
  const response = async (name, args) => {
    calls.push({ name, args });
    if (transport) { const value = transport(name, args); if (value !== undefined) return value; }
    if (name === 'customer') return { data: { items: [nextCustomer] } };
    if (name.includes('finance-access-data')) return { data: { payments: [{ id: 'fresh-payment' }], refunds: [], expenses: [], deduction_rates: {}, status: { payment_count: 1 } } };
    return { data: { items: [{ id: `fresh-${name}` }] } };
  };
  const entities = Object.fromEntries(['customers', 'follow_ups', 'deals', 'service_progresses', 'service_tasks', 'customer_contacts'].map(name => [name, { query: args => response(name === 'customers' ? 'customer' : name, args), queryAll: args => response(name, args) }]));
  const ctx = {
    ...permission, ...guards, console: { error() {}, warn() {} }, Date, JSON,
    client: { entities }, invokeWithAuth: args => response(args.url, args), loadWithRetry: callback => callback(),
    customerActor: 'actor-A', customerActorRef: { current: 'actor-A' }, session: 'session-A', getAuthSessionEpoch: () => ctx.session,
    customerMountedRef: { current: true }, customerListSequence: { current: 0 },
    detailRequestSeqRef: { current: 0 }, activeDetailCustomerIdRef: { current: 1 }, detailAccessSequenceRef: { current: 0 },
    detailSnapshotScopeRef: { current: 'actor-A:1' }, detailRefreshFlightRef: { current: null },
    detailEditorRef: { current: { key: '', generation: 0 } }, detailEditActiveRef: { current: false }, selectedCustomerRef: { current: accepted },
    hasUnsavedChanges: () => ctx.unsaved === true, unsaved: false, isOwner: true,
    displayCustomerStatus: value => value, decorateCustomerSubscriptions: value => value,
    getLoadErrorMessage: error => error.message || String(error.status || 'failed'), toast: { error() {} }, CUSTOMER_SHELL_LIST_QUERY: { limit: 1000, sort: '-id' },
  };
  const setterNames = new Set(); function collect(node) { if (ts.isCallExpression(node) && /^set[A-Z]/.test(node.expression.getText(ast))) setterNames.add(node.expression.getText(ast)); ts.forEachChild(node, collect); }
  collect(ast);
  for (const name of setterNames) ctx[name] = value => { const key = name[3].toLowerCase() + name.slice(4); state[key] = typeof value === 'function' ? value(state[key]) : value; sets.push(key); if (key === 'selectedCustomer') ctx.selectedCustomerRef.current = state[key]; };
  vm.createContext(ctx);
  vm.runInContext(compile(names.map(name => `const ${name}=${functions.get(name)};`).join('\n') + `\nglobalThis.actions={${names.join(',')},auto:${autoCallback}};`), ctx);
  return { ctx, state, calls, sets, actions: ctx.actions, accepted, setCustomer: value => nextCustomer = value, transport: value => transport = value };
}

test('all actual timer/focus/visibility/pageshow/reconnect events only check access while reading', async () => {
  const f = fixture(), listeners = new Map(); let interval;
  const mod = { exports: {} }, document = { visibilityState: 'visible', addEventListener: (name, cb) => listeners.set(name, cb), removeEventListener() {} };
  const window = { setInterval: cb => { interval = cb; return 1; }, clearInterval() {}, addEventListener: (name, cb) => listeners.set(name, cb), removeEventListener() {} };
  const require = name => name === 'react' ? { useRef: value => ({ current: value }), useEffect: callback => callback() } : { BUSINESS_DATA_REFRESH_EVENT: 'fixture-business' };
  vm.runInNewContext(`(function(require,module,exports){${compile(fs.readFileSync(new URL('../src/lib/use-auto-refresh.ts', import.meta.url), 'utf8'))}\n})`, { window, document, console })(require, mod, mod.exports);
  mod.exports.useAutoRefresh(f.actions.auto, { intervalMs: 30000 });
  for (const run of [interval, ...['focus', 'visibilitychange', 'pageshow', 'online', 'fixture-business'].map(name => listeners.get(name))]) { run(); await tick(); }
  assert.equal(f.calls.length, 6); assert.ok(f.calls.every(call => call.name === 'customer' && call.args.query.id === 1));
  assert.equal(f.state.selectedCustomer, f.accepted); assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.state.detailLoading, false); assert.equal(f.state.followUps[0].id, 'accepted-FollowUps'); assert.equal(f.state.selectedCustomerTab, 'followups');
  assert.equal(f.sets.includes('showFollowForm'), false);
});

test('basic changes signal pending data without replacing any reading snapshot or clock', async () => {
  const f = fixture(); f.setCustomer({ ...customer(), business_name: 'Changed elsewhere' }); await f.actions.checkCustomerDetailAccess();
  assert.equal(f.state.detailUpdateAvailable, true); assert.equal(f.state.selectedCustomer.business_name, f.accepted.business_name); assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.calls.length, 1);
});

test('quiet module/finance downgrade withdraws prior data before fetching only allowed sections', async () => {
  const f = fixture(), pending = deferred(), next = customer(); next.effective_permissions.finance_access = 'none'; next.effective_permissions.modules.followups = { read: false, write: false }; f.setCustomer(next);
  let customerReads = 0; f.transport(name => name === 'customer' && ++customerReads === 2 ? pending.promise : undefined);
  const load = f.actions.checkCustomerDetailAccess(); await tick();
  assert.equal(f.state.payments.length, 0); assert.equal(f.state.followUps.length, 0); assert.equal(f.state.detailLoadedAt, null); assert.equal(f.state.detailLoading, true);
  pending.resolve({ data: { items: [next] } }); await load;
  assert.equal(f.state.payments.length, 0); assert.equal(f.state.followUps.length, 0); assert.equal(f.calls.some(call => call.name.includes('finance-access-data') || call.name === 'follow_ups'), false);
  assert.ok(f.state.contacts.length > 0); assert.equal(f.state.selectedCustomer.effective_permissions.finance_access, 'none');
});

for (const status of [401, 403]) test(`quiet ${status} immediately withdraws the detail`, async () => {
  const f = fixture(); f.transport(() => Promise.reject({ status })); await f.actions.checkCustomerDetailAccess();
  assert.equal(f.state.selectedCustomer, null); assert.equal(f.state.payments.length, 0); assert.equal(f.ctx.activeDetailCustomerIdRef.current, null);
});
test('quiet no-access result withdraws the detail while 503 retains marked read-only content', async () => {
  const f = fixture(); f.transport(() => Promise.reject({ status: 503 })); await f.actions.checkCustomerDetailAccess(); assert.equal(f.state.selectedCustomer, f.accepted); assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.match(f.state.detailAccessError, /保留阅读内容/);
  const next = customer(); next.effective_permissions.access_level = 'none'; f.transport(undefined); f.setCustomer(next); await f.actions.checkCustomerDetailAccess(); assert.equal(f.state.selectedCustomer, null); assert.equal(f.state.contacts.length, 0);
});
test('same-customer manual refresh retains content while pending and atomically commits fresh records', async () => {
  const f = fixture(), pending = deferred(); f.transport(name => name === 'customer' ? pending.promise : undefined);
  const load = f.actions.loadCustomerDetail(1, f.accepted, { manual: true });
  assert.equal(f.state.detailRefreshing, true); assert.equal(f.state.detailLoading, false); assert.equal(f.state.followUps[0].id, 'accepted-FollowUps'); assert.equal(f.state.detailLoadedAt, 'accepted-before-read');
  pending.resolve({ data: { items: [customer()] } }); await load;
  assert.equal(f.state.payments[0].id, 'fresh-payment'); assert.equal(f.state.detailRefreshing, false); assert.notEqual(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.sets.includes('showFollowForm'), false);
});
test('manual 503 keeps accepted content and timestamp, then retry applies real fresh data', async () => {
  const f = fixture(); f.transport(() => Promise.reject({ status: 503 })); await f.actions.loadCustomerDetail(1, f.accepted, { manual: true }); assert.equal(f.state.followUps[0].id, 'accepted-FollowUps'); assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.state.detailLoading, false); assert.equal(f.state.detailLoadError, '503');
  f.transport(undefined); await f.actions.loadCustomerDetail(1, f.accepted, { manual: true }); assert.equal(f.state.detailLoadError, null); assert.equal(f.state.payments[0].id, 'fresh-payment');
});
test('a denied associated read cannot be retained or converted into a zero balance', async () => {
  const f = fixture(); f.transport(name => name === 'customer_contacts' ? Promise.reject({ status: 403 }) : undefined); await f.actions.loadCustomerDetail(1, f.accepted, { manual: true }); assert.equal(f.state.selectedCustomer, null); assert.equal(f.state.payments.length, 0); assert.equal(f.state.contacts.length, 0);
});
test('manual refresh blocks an open draft, and an early refresh cannot replace a newly opened draft', async () => {
  const f = fixture(); f.ctx.detailEditActiveRef.current = true; await f.actions.loadCustomerDetail(1, f.accepted, { manual: true }); assert.equal(f.calls.length, 0);
  f.ctx.detailEditActiveRef.current = false; const pending = deferred(); f.transport(name => name === 'customer' ? pending.promise : undefined); const load = f.actions.loadCustomerDetail(1, f.accepted, { manual: true });
  f.ctx.detailEditorRef.current.generation += 1; f.state.showFollowForm = true; f.ctx.unsaved = true;
  pending.resolve({ data: { items: [customer()] } }); await load;
  assert.equal(f.state.showFollowForm, true); assert.equal(f.state.followUps[0].id, 'accepted-FollowUps'); assert.equal(f.state.detailUpdateAvailable, true); assert.equal(f.state.detailLoadedAt, 'accepted-before-read');
});
for (const changed of ['customer', 'actor', 'session', 'closed', 'unmounted']) test(`${changed} change rejects a late manual response`, async () => {
  const f = fixture(), pending = deferred(); f.transport(() => pending.promise); const load = f.actions.loadCustomerDetail(1, f.accepted, { manual: true });
  if (changed === 'customer') f.ctx.activeDetailCustomerIdRef.current = 2;
  if (changed === 'actor') f.ctx.customerActorRef.current = 'actor-B';
  if (changed === 'session') f.ctx.session = 'session-B';
  if (changed === 'closed') f.ctx.activeDetailCustomerIdRef.current = null;
  if (changed === 'unmounted') f.ctx.customerMountedRef.current = false;
  pending.resolve({ data: { items: [customer()] } }); await load;
  assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.state.followUps[0].id, 'accepted-FollowUps'); assert.equal(f.calls.length, 1);
});
test('late quiet rejection cannot withdraw a newer manually verified snapshot', async () => {
  const f = fixture(), pending = deferred(); let reads = 0; f.transport(name => name === 'customer' && ++reads === 1 ? pending.promise : undefined); const quiet = f.actions.checkCustomerDetailAccess();
  await f.actions.loadCustomerDetail(1, f.accepted, { manual: true }); pending.reject({ status: 403 }); await quiet;
  assert.ok(f.state.selectedCustomer); assert.equal(f.state.payments[0].id, 'fresh-payment');
});
test('save-triggered refresh still performs and applies the original associated reads', async () => {
  const f = fixture(); f.ctx.detailEditActiveRef.current = true; await f.actions.loadCustomerDetail(1, f.accepted);
  assert.ok(f.calls.some(call => call.name === 'follow_ups')); assert.ok(f.calls.some(call => call.name.includes('finance-access-data'))); assert.equal(f.state.payments[0].id, 'fresh-payment'); assert.notEqual(f.state.detailLoadedAt, 'accepted-before-read');
});
test('deep-link tab is consumed once; a list refresh cannot reapply an old tab', () => {
  const fn = effectCallbacks.find(value => value?.includes('// Handle deep link from Sales page')); assert.ok(fn);
  const selected = [], ctx = { searchParams: new URLSearchParams('detail=1&tab=followups'), statusLabels: {}, customerActor: 'actor-A', resolvedCustomerActor: 'actor-A', customers: [{ id: 1 }], selectedCustomer: { id: 1 }, requestedDetailRouteRef: { current: '' }, normalizeCustomerDetailTab: value => value || 'overview', setFilterStatus() {}, setSelectedCustomerTab: value => selected.push(value), openDetail() { throw Error('same-customer should not reopen'); } };
  vm.createContext(ctx); vm.runInContext(compile(`globalThis.effect=${fn};`), ctx); ctx.effect(); assert.equal(selected.length, 1); ctx.customers = [{ id: 1, business_name: 'new list shell' }]; ctx.effect(); assert.equal(selected.length, 1);
  ctx.searchParams = new URLSearchParams('detail=1&tab=payments'); ctx.effect(); assert.deepEqual(selected, ['followups', 'payments']);
});


test('failed associated 503 keeps the entire accepted bundle instead of a false empty list', async () => {
  const f = fixture(); f.transport(name => name === 'follow_ups' ? Promise.reject({ status: 503 }) : undefined);
  await f.actions.loadCustomerDetail(1, f.accepted, { manual: true });
  assert.equal(f.state.followUps[0].id, 'accepted-FollowUps'); assert.equal(f.state.payments[0].id, 'accepted-Payments'); assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.state.detailLoadError, '503');
});
test('quiet added permissions stay pending until an explicit fresh full load', async () => {
  const f = fixture(); f.accepted.effective_permissions.finance_access = 'status'; const next = customer(); next.effective_permissions.finance_access = 'profit'; f.setCustomer(next);
  await f.actions.checkCustomerDetailAccess();
  assert.equal(f.state.selectedCustomer.effective_permissions.finance_access, 'status'); assert.equal(f.state.detailUpdateAvailable, true); assert.equal(f.calls.length, 1);
  await f.actions.loadCustomerDetail(1, f.accepted, { manual: true }); assert.equal(f.state.selectedCustomer.effective_permissions.finance_access, 'profit');
});
test('a running list refresh cannot reload or clear a detail/draft opened while it awaited', async () => {
  const f = fixture(), pending = deferred(); f.ctx.activeDetailCustomerIdRef.current = null;
  f.transport(name => name === 'customer' ? pending.promise : undefined);
  const load = f.actions.auto(); f.ctx.activeDetailCustomerIdRef.current = 1; f.state.showFollowForm = true; f.ctx.detailEditorRef.current.generation += 1;
  pending.resolve({ data: { items: [customer()] } }); await load;
  assert.equal(f.state.showFollowForm, true); assert.equal(f.state.detailLoadedAt, 'accepted-before-read'); assert.equal(f.calls.filter(call => call.name === 'customer').length, 1); assert.equal(f.calls.some(call => call.name === 'follow_ups'), false);
});

test('a late failed manual response cannot mark or disable a newly opened draft', async () => {
  const f = fixture(), pending = deferred(); f.transport(() => pending.promise);
  const load = f.actions.loadCustomerDetail(1, f.accepted, { manual: true });
  f.ctx.detailEditorRef.current.generation += 1; f.state.showContactForm = true;
  pending.reject({ status: 503 }); await load;
  assert.equal(f.state.showContactForm, true); assert.equal(f.state.detailLoadError, null); assert.equal(f.state.detailUpdateAvailable, true); assert.equal(f.state.detailLoadedAt, 'accepted-before-read');
});
test('permission-only checks remain enabled with an open detail draft', () => {
  let options;
  function find(node) { if (ts.isCallExpression(node) && node.expression.getText(ast) === 'useAutoRefresh') options = node.arguments[1].getText(ast); ts.forEachChild(node, find); } find(ast);
  const ctx = { selectedCustomer: customer(), showForm: false, showFollowForm: true, showContactForm: false }; vm.createContext(ctx); vm.runInContext(compile(`globalThis.options=${options};`), ctx); assert.equal(ctx.options.enabled, true);
});
