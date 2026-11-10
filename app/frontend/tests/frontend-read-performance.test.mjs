import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const read = file => readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');
const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; };
const compile = (source, imports = {}, globals = {}) => {
  const module = { exports: {} };
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(js, { module, exports: module.exports, require: name => imports[name] || {}, console, URLSearchParams, ...globals });
  return module.exports;
};
// Exercise the actual page's orchestration without rendering unrelated charts,
// forms or provider widgets. The real hook below still controls event overlap.
const refreshCallback = (file, reads) => {
  const source = read(file), parsed = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let callback;
  const visit = node => {
    if (ts.isCallExpression(node) && node.expression.getText(parsed) === 'useAutoRefresh') callback = node.arguments[0].getText(parsed);
    ts.forEachChild(node, visit);
  };
  visit(parsed); assert.ok(callback, `${file} must retain an automatic refresh callback`);
  return compile(`exports.callback = (${callback});`, {}, reads).callback;
};
const pageRead = (file, name, globals) => {
  const parsed = ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX); let initializer;
  const visit = node => {
    if (ts.isVariableDeclaration(node) && node.name.getText(parsed) === name) initializer = node.initializer.getText(parsed);
    ts.forEachChild(node, visit);
  };
  visit(parsed); assert.ok(initializer);
  return compile(`exports.read = (${initializer});`, {}, globals).read;
};
function autoRefresh(callback, options = {}) {
  const listeners = new Map(), effects = [], cleanups = [];
  const target = { addEventListener(name, fn) { const entries = listeners.get(name) || new Set(); entries.add(fn); listeners.set(name, entries); }, removeEventListener(name, fn) { listeners.get(name)?.delete(fn); } };
  const document = { ...target, visibilityState: 'visible' };
  const window = { ...target, setInterval: () => 1, clearInterval() {}, setTimeout: () => 2, clearTimeout() {} };
  const react = { useRef: value => ({ current: value }), useEffect: fn => effects.push(fn) };
  const { useAutoRefresh } = compile(read('lib/use-auto-refresh.ts'), { react, './data-refresh': { BUSINESS_DATA_REFRESH_EVENT: 'synthetic:business-data-refresh' } }, { window, document });
  useAutoRefresh(callback, options);
  for (const effect of effects) cleanups.push(effect());
  return { document, fire(name) { for (const fn of listeners.get(name) || []) fn(); }, stop() { for (const cleanup of cleanups) cleanup?.(); } };
}

test('dashboard event burst keeps one actual read batch pending until both sources settle', async () => {
  const primary = deferred(), owner = deferred(); let primaryReads = 0, ownerReads = 0;
  const callback = refreshCallback('pages/Dashboard.tsx', { isAdm: true, loadDashboard: () => { primaryReads++; return primary.promise; }, loadOwnerCockpit: () => { ownerReads++; return owner.promise; } });
  const hook = autoRefresh(callback);
  hook.fire('focus'); await flush(); hook.fire('visibilitychange'); hook.fire('pageshow'); await flush();
  assert.equal(primaryReads, 1); assert.equal(ownerReads, 1);
  primary.resolve(); await flush(); hook.fire('focus'); assert.equal(primaryReads, 1);
  owner.resolve(); await flush(); hook.fire('focus'); await flush();
  assert.equal(primaryReads, 2); assert.equal(ownerReads, 2);
  hook.stop();
});

test('ordinary dashboard refresh never invokes the owner-only data source', async () => {
  let primaryReads = 0, ownerReads = 0;
  await refreshCallback('pages/Dashboard.tsx', { isAdm: false, loadDashboard: async () => { primaryReads++; }, loadOwnerCockpit: async () => { ownerReads++; } })();
  assert.equal(primaryReads, 1); assert.equal(ownerReads, 0);
});

test('workbench starts all four independent reads before any response instead of waiting four network rounds', async () => {
  const pending = Array.from({ length: 4 }, deferred), reads = [];
  const names = ['loadWorkbench', 'loadRecoveryAlerts', 'loadPersonalPerformance', 'loadRingCentral'];
  const callback = refreshCallback('pages/SalesWorkbench.tsx', Object.fromEntries(names.map((name, index) => [name, options => { reads.push({ name, options }); return pending[index].promise; }])));
  let settled = false; const request = callback().then(() => { settled = true; });
  assert.deepEqual(reads.map(item => item.name), names); assert.equal(reads[0].options.background, true);
  pending[0].resolve(); await flush(); assert.equal(settled, false);
  pending.slice(1).forEach(item => item.resolve()); await request;
});

test('customer and employee reads overlap while detail still waits for the refreshed directory', async () => {
  const customers = deferred(), employees = deferred(), reads = [];
  const callback = refreshCallback('pages/Customers.tsx', {
    loadCustomers: () => { reads.push('customers'); return customers.promise; },
    loadEmployees: () => { reads.push('employees'); return employees.promise; },
    activeDetailCustomerIdRef: { current: 89 }, selectedCustomer: { id: 89 },
    loadCustomerDetail: async (id, fallback) => { assert.equal(id, 89); assert.equal(fallback.id, 89); reads.push('detail'); },
  });
  const request = callback(); assert.deepEqual(reads, ['customers', 'employees']);
  customers.resolve(); await flush(); assert.deepEqual(reads, ['customers', 'employees']);
  employees.resolve(); await request; assert.deepEqual(reads, ['customers', 'employees', 'detail']);
});

test('login mounts the destination once without a second timed full-page refresh', async () => {
  const timers = [], events = [], calls = [], verified = deferred();
  const jsx = (type, props) => ({ type, props });
  const { default: LoginPage } = compile(read('pages/LoginPage.tsx'), {
    'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-router-dom': { useLocation: () => ({ state: null }), useNavigate: () => (path, options) => { calls.push(['navigate', path, options.replace]); } },
    './Login': { __esModule: true, default: 'Login' },
    '@/lib/role-context': { useRole: () => ({ loading: false, authError: '', isLoggedIn: false, isDisabled: false, role: '', login: (...args) => { calls.push(['login', ...args]); return verified.promise; } }) },
    '@/lib/data-refresh': { requestBusinessDataRefresh: reason => events.push(reason) },
    '@/lib/app-navigation': { getDesktopLoginPath: () => '/sales-workbench' },
    '@/lib/navigation-state': { getSafeInternalPath: value => value },
  }, { window: { matchMedia: () => ({ matches: false }), setTimeout: fn => timers.push(fn) } });
  const page = LoginPage(), employee = { id: 7, role: 'sales' };
  const result = page.props.onLoginSuccess('synthetic-token', employee, false);
  assert.deepEqual(calls.map(call => call[0]), ['login']);
  verified.resolve(); await result; timers.forEach(fn => fn());
  assert.deepEqual(calls.map(call => call[0]), ['login', 'navigate']);
  assert.equal(calls[1][1], '/sales-workbench'); assert.equal(calls[1][2], true);
  assert.deepEqual(events, []);
});

test('automatic refresh remains disabled or hidden when required and explicit updates still trigger a fresh read', async () => {
  let reads = 0;
  const disabled = autoRefresh(async () => { reads++; }, { enabled: false }); disabled.fire('focus'); assert.equal(reads, 0); disabled.stop();
  const hook = autoRefresh(async () => { reads++; });
  hook.document.visibilityState = 'hidden'; hook.fire('focus'); await flush(); assert.equal(reads, 0);
  hook.document.visibilityState = 'visible'; hook.fire('synthetic:business-data-refresh'); await flush(); assert.equal(reads, 1);
  hook.fire('synthetic:business-data-refresh'); await flush(); assert.equal(reads, 2);
  hook.stop(); hook.fire('focus'); assert.equal(reads, 2);
});

function leadList(canManage = true) {
  const requests = [], state = { loading: true, auxiliaryLoading: true, items: [], total: 0, selectedLeadIds: [1, 2], statsReady: false, callReportError: false };
  const setters = Object.fromEntries(['Loading', 'AuxiliaryLoading', 'Items', 'ListError', 'Total', 'SelectedLeadIds', 'Stats', 'StatsReady', 'CallReport', 'CallReportError', 'Assignees', 'Dashboard', 'PerformanceDashboard', 'RecoveryOverview', 'DataErrors'].map(name => {
    const key = name[0].toLowerCase() + name.slice(1);
    return [`set${name}`, value => { state[key] = typeof value === 'function' ? value(state[key]) : value; }];
  }));
  const read = pageRead('pages/SalesLeads.tsx', 'loadData', {
    ...setters, loadRequestSeqRef: { current: 0 }, page: 1, pageSize: 20, search: '', statusFilter: '', contactFilter: '', dueRange: '',
    canManage, callReportDays: 7, performanceDays: 30, stats: { total: 0 },
    invokeWithAuth: args => { const pending = deferred(); requests.push({ ...args, ...pending }); return pending.promise; },
  });
  return { state, requests, read };
}

test('lead rows become available from their real response while slow or failed reports keep their own loading state', async () => {
  const f = leadList(), all = f.read();
  assert.equal(f.requests.length, 7);
  assert.equal(f.state.loading, true); assert.deepEqual(f.state.items, []);
  f.requests[0].resolve({ data: { items: [{ id: 1, business_name: 'Synthetic business' }], total: 31 } });
  await flush();
  assert.equal(f.state.loading, false); assert.equal(f.state.auxiliaryLoading, true);
  assert.equal(f.state.items[0].id, 1); assert.equal(f.state.total, 31);
  assert.equal(f.state.statsReady, false); assert.deepEqual(f.state.selectedLeadIds, [1]);
  f.requests[2].reject({ status: 403 });
  f.requests.slice(1).filter((_, index) => index !== 1).forEach(request => request.resolve({ data: {} }));
  await all;
  assert.equal(f.state.auxiliaryLoading, false); assert.equal(f.state.callReportError, true);
  assert.ok(f.state.dataErrors.includes('真实通话报告')); assert.equal(f.state.items[0].id, 1);
});

test('failed lead authorization never reports an empty successful list and nonmanagers do not request management data', async () => {
  for (const status of [401, 403]) {
    const f = leadList(false), all = f.read(); assert.equal(f.requests.length, 3);
    f.requests[0].reject({ status }); await flush();
    assert.equal(f.state.listError, true); assert.equal(f.state.loading, false); assert.equal(f.state.selectedLeadIds.length, 0);
    assert.equal(f.state.statsReady, false);
    f.requests.slice(1).forEach(request => request.resolve({ data: {} })); await all;
  }
});

test('a replaced lead request cannot overwrite newer rows, totals, loading or auxiliary results', async () => {
  const f = leadList(false), old = f.read(), current = f.read({ page: 2 });
  f.requests[3].resolve({ data: { items: [{ id: 21 }], total: 45 } }); await flush();
  f.requests[0].resolve({ data: { items: [{ id: 1 }], total: 900 } });
  f.requests.slice(1, 3).forEach(request => request.resolve({ data: {} })); await old;
  assert.equal(f.state.items[0].id, 21); assert.equal(f.state.total, 45); assert.equal(f.state.loading, false); assert.equal(f.state.auxiliaryLoading, true);
  f.requests.slice(4).forEach(request => request.resolve({ data: {} })); await current;
  assert.equal(f.state.items[0].id, 21); assert.equal(f.state.auxiliaryLoading, false);
});
