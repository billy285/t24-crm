import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

// Run the real component/effect code with a local React lifecycle and deferred
// transport. No browser, provider, credentials, database or real call is used.
const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const today = '2026-11-13';
const source = file => readFileSync(resolve(src, file), 'utf8');
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(done => setImmediate(done)); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
const nodes = tree => !tree || typeof tree !== 'object' ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const connected = id => ({ employee_id: id, employee_name: `Synthetic sales ${id}`, connected: true, realtime_sync_enabled: true, last_synced_at: today + 'T01:00:00Z', extension_number: String(id) });
const compile = code => ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;

function componentFixture(file, exported, handler, initialProps, initialActor = { employee: { id: 1 }, role: 'super_admin' }) {
  const slots = [], effects = [], requests = [], redirects = [], navigations = [], intervals = new Map();
  let cursor = 0, tree, actor = initialActor, props = initialProps, intervalId = 0;
  const react = {
    useState(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: typeof initial === 'function' ? initial() : initial }; return [slots[i].value, value => { slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: { current: initial } }; return slots[i].value; },
    useCallback(callback) { cursor++; return callback; },
    useEffect(callback, deps) { const i = cursor++, prior = slots[i]; if (prior && deps.length === prior.deps.length && deps.every((v, n) => Object.is(v, prior.deps[n]))) return; slots[i] = { deps }; effects.push(() => { prior?.cleanup?.(); slots[i].cleanup = callback(); }); },
  };
  const mod = { exports: {} };
  const require = name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' };
    if (name === 'react-router-dom') return { useNavigate: () => url => navigations.push(url) };
    if (name === '@/lib/role-context') return { useRole: () => actor };
    if (name === '@/components/ui/button') return { Button: 'button' };
    if (name === '@/lib/business-date') return { businessDateKey: () => today };
    if (name === '@/lib/tokenStore') return { invokeWithAuth: async request => { requests.push(request); return handler(request); } };
    return new Proxy({}, { get: (_target, key) => String(key) });
  };
  const window = { setInterval(callback) { intervals.set(++intervalId, callback); return intervalId; }, clearInterval(id) { intervals.delete(id); }, location: { assign: url => redirects.push(url) } };
  vm.runInNewContext(`(function(require,module,exports){${compile(source(file))}\n})`, { console, window, Intl, Date, URLSearchParams })(require, mod, mod.exports);
  const flushEffects = () => { while (effects.length) effects.shift()(); };
  const render = (nextProps = {}, nextActor, runEffects = true) => { props = { ...props, ...nextProps }; if (nextActor) actor = nextActor; cursor = 0; tree = mod.exports[exported](props); if (runEffects) flushEffects(); return tree; };
  const button = label => { const found = nodes(tree).find(node => node.type === 'button' && text(node) === label); assert.ok(found, `Button ${label}`); return found; };
  return { render, button, requests, redirects, navigations, flushEffects, tree: () => tree, content: () => text(tree), tick: () => { for (const callback of intervals.values()) callback(); }, unmount: () => { for (const slot of slots) slot?.cleanup?.(); } };
}

test('phone refresh and interval preserve cards while exposing busy state and blocking provider actions', async () => {
  const pending = deferred(); let reads = 0;
  const app = componentFixture('components/SalesPhoneConnections.tsx', 'default', () => ++reads === 1 ? { data: { items: [connected(1)] } } : pending.promise, { periodDays: 7 });
  app.render(); await flush(); app.render();
  app.button('刷新状态').props.onClick(); app.render(); app.render();
  assert.match(app.content(), /Synthetic sales 1/); assert.match(app.content(), /更新中/);
  assert.equal(app.tree().props['aria-busy'], true);
  assert.equal(app.button('补同步我的通话').props.disabled, true);
  app.button('补同步我的通话').props.onClick();
  assert.equal(app.requests.filter(request => request.method !== 'GET').length, 0);
  pending.resolve({ data: { items: [connected(1)] } }); await flush(); app.render();
  assert.equal(app.tree().props['aria-busy'], false);
  assert.match(app.content(), /Synthetic sales 1/);
  app.tick(); app.render(); assert.match(app.content(), /Synthetic sales 1/);
  app.unmount();
});

for (const status of [401, 403, 500]) test(`phone ${status} refresh keeps only authorized display and disables writes`, async () => {
  let reads = 0; const pending = deferred();
  const app = componentFixture('components/SalesPhoneConnections.tsx', 'default', () => ++reads === 1 ? { data: { items: [connected(1)] } } : pending.promise, {});
  app.render(); await flush(); app.render(); app.button('刷新状态').props.onClick(); app.render();
  pending.reject({ response: { status } }); await flush(); app.render();
  assert.match(app.content(), /连接状态暂不可用/);
  assert.equal(/Synthetic sales 1/.test(app.content()), status === 500);
  if (status === 500) { assert.equal(app.button('补同步我的通话').props.disabled, true); app.button('补同步我的通话').props.onClick(); }
  assert.equal(app.requests.filter(request => request.method !== 'GET').length, 0);
  assert.equal(app.button('重新读取连接状态').props.disabled, false);
  app.unmount();
});

test('phone actor/period changes hide old cards before effects; an old response cannot restore them', async () => {
  let reads = 0; const old = deferred(), next = deferred();
  const app = componentFixture('components/SalesPhoneConnections.tsx', 'default', () => ++reads === 1 ? { data: { items: [connected(1)] } } : reads === 2 ? old.promise : next.promise, { periodDays: 7 });
  app.render(); await flush(); app.render(); app.button('刷新状态').props.onClick(); app.render();
  app.render({ periodDays: 30 }, { employee: { id: 2 }, role: 'sales' }, false);
  assert.doesNotMatch(app.content(), /Synthetic sales 1/);
  old.resolve({ data: { items: [connected(1)] } }); await flush(); app.render({}, undefined, false);
  assert.doesNotMatch(app.content(), /Synthetic sales 1/);
  app.flushEffects(); next.resolve({ data: { items: [connected(2)] } }); await flush(); app.render();
  assert.match(app.content(), /Synthetic sales 2/); assert.doesNotMatch(app.content(), /Synthetic sales 1/);
  assert.ok(app.requests.at(-1).url.endsWith('days=30'));
  app.unmount();
});

test('authorization withdrawal during repair cannot continue into a provider backfill', async () => {
  let reads = 0; const repair = deferred();
  const app = componentFixture('components/SalesPhoneConnections.tsx', 'default', request => request.method === 'GET'
    ? ++reads === 1 ? { data: { items: [{ ...connected(1), realtime_sync_enabled: false }] } } : Promise.reject({ response: { status: 403 } })
    : repair.promise, {});
  app.render(); await flush(); app.render(); app.button('修复实时同步并补同步').props.onClick();
  app.tick(); await flush(); app.render(); assert.doesNotMatch(app.content(), /Synthetic sales 1/);
  repair.resolve({ data: {} }); await flush(); app.render();
  assert.deepEqual(app.requests.filter(request => request.method === 'POST').map(request => request.url), ['/api/ringcentral/subscription/ensure']);
  app.unmount();
});

function teamResponse(request, { unavailable = false } = {}) {
  if (request.url.includes('/workbench/today')) return { data: { salesperson: { id: 11 }, target_date: new URL('http://fixture.test' + request.url).searchParams.get('target_date'), quota: 100, completed_count: 10, remaining_count: 90 } };
  if (request.url.includes('/merchant-pool/stats')) return unavailable ? Promise.reject({ status: 503 }) : { data: { pending: 17 } };
  if (request.url.includes('/dashboard/management')) return { data: { target_date: new URL('http://fixture.test' + request.url).searchParams.get('target_date'), owner_attention: { overdue_followups: 2, high_intent_stale: 3 } } };
  return { data: { source: { status: 'verified' }, period: { start_date: today, end_date: today }, summary: { connected: 4 } } };
}
const teamProps = () => ({ employees: [{ id: 11, name: 'Synthetic sales 11' }], targetDate: today, onOpenWorkbench() {} });
const recordedValue = app => text(nodes(app.tree()).find(node => node.type === 'section' && node.props['aria-label'] === '团队任务概况')?.props.children[0]?.props.children[1]);

test('same-scope team retry keeps numbers; actor/date/roster changes immediately withdraw them', async () => {
  let refreshing = false; const pending = deferred();
  const app = componentFixture('components/SalesTeamPerformance.tsx', 'SalesTeamToday', request => refreshing && request.url.includes('/workbench/today') ? pending.promise : teamResponse(request, { unavailable: true }), teamProps());
  app.render(); await flush(); app.render(); assert.equal(recordedValue(app), '10');
  refreshing = true; app.button('重新读取').props.onClick(); app.render(); app.render();
  assert.equal(recordedValue(app), '10'); assert.equal(app.tree().props['aria-busy'], true);
  pending.resolve(teamResponse({ url: `/workbench/today?target_date=${today}` })); await flush(); app.render(); assert.equal(recordedValue(app), '10');
  app.render({ targetDate: '2026-11-14' }, undefined, false); assert.notEqual(recordedValue(app), '10');
  app.render({ targetDate: today }, { employee: { id: 2 }, role: 'admin' }, false); assert.notEqual(recordedValue(app), '10');
  app.render({ employees: [{ id: 12, name: 'Synthetic sales 12' }] }, undefined, false); assert.doesNotMatch(app.content(), /Synthetic sales 11/);
  app.unmount();
});

test('team 403 withdraws the retained summary and leaves no allocation action enabled', async () => {
  let denied = false;
  const app = componentFixture('components/SalesTeamPerformance.tsx', 'SalesTeamToday', request => denied ? Promise.reject({ response: { status: 403 } }) : teamResponse(request, { unavailable: true }), teamProps());
  app.render(); await flush(); app.render(); assert.equal(recordedValue(app), '10');
  denied = true; app.button('重新读取').props.onClick(); app.render(); await flush(); app.render();
  assert.notEqual(recordedValue(app), '10'); assert.match(app.content(), /任务授权暂不可用/);
  assert.equal(app.button('分配商家').props.disabled, true);
  app.unmount();
});

test('team links use SPA navigation with original route parameters, never document.assign', async () => {
  const app = componentFixture('components/SalesTeamPerformance.tsx', 'SalesTeamToday', teamResponse, teamProps());
  app.render(); await flush(); app.render(); app.button('分配商家').props.onClick();
  nodes(app.tree()).find(node => node.type === 'button' && node.props.title === '查看当前线索').props.onClick();
  nodes(app.tree()).find(node => node.type === 'button' && node.props.title === '查看当前商机').props.onClick();
  assert.deepEqual(app.navigations, ['/merchant-pool', '/sales-leads?view=intelligence&panel=leads&signal=overdue', '/sales-leads?view=intelligence&panel=leads']);
  assert.deepEqual(app.redirects, []); app.unmount();
});

function findNode(file, predicate) {
  const sf = ts.createSourceFile(file, source(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX); let found;
  const visit = node => { if (!found && predicate(node, sf)) found = node; if (!found) ts.forEachChild(node, visit); };
  visit(sf); assert.ok(found, `AST node in ${file}`); return { node: found, sf };
}
function initializer(file, name, context) {
  const { node, sf } = findNode(file, node => ts.isVariableDeclaration(node) && node.name.getText() === name);
  const mod = { exports: {} }; vm.runInNewContext(compile(`module.exports = (${node.initializer.getText(sf)});`), { ...context, module: mod }); return mod.exports;
}

test('merchant view derivation retains same-view loading rows, withdraws failed/new-scope rows, and keeps mutation locks', async () => {
  const file = 'pages/MerchantPool.tsx', loadedItems = [{ id: 1, business_name: 'Synthetic merchant' }];
  const derive = extra => {
    const ctx = { acceptedViewKey: 'actor1:view1', viewKey: 'actor1:view1', failedViewKey: null, requestLoading: true, loadedItems, ...extra };
    for (const name of ['listError', 'hasCurrentList', 'loading', 'showListLoading', 'items']) ctx[name] = initializer(file, name, ctx);
    return ctx;
  };
  const refreshing = derive({}); assert.equal(refreshing.showListLoading, false); assert.deepEqual(refreshing.items, loadedItems); assert.equal(refreshing.loading, true);
  for (const changed of [{ viewKey: 'actor2:view1' }, { viewKey: 'actor1:view2' }, { failedViewKey: 'actor1:view1', requestLoading: false }]) assert.equal(derive(changed).items.length, 0);
  assert.equal(derive({ viewKey: 'actor2:view1' }).showListLoading, true);
  for (const state of [{ loading: true, listError: false }, { loading: false, listError: true }]) {
    let requests = 0;
    const assign = initializer(file, 'assignSelectedMerchants', { ...state, selectedMerchantIds: [1], bulkAssigning: false, bulkUpdating: false, invokeWithAuth: () => requests++ });
    await assign(); assert.equal(requests, 0);
  }
  const sf = ts.createSourceFile(file, source(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX); let gated = 0;
  const visit = node => { if (ts.isConditionalExpression(node) && node.condition.getText(sf) === 'showListLoading') gated++; ts.forEachChild(node, visit); }; visit(sf);
  assert.ok(gated >= 3, 'both list renderers and stable result status use first-load state');
});

function insightFixture({ scope = 'actor1:page1', acceptedScope = scope, initial = { scope, items: { 1: { id: 1, profile: { next_step: 'Synthetic next step' } }, 2: { id: 2 } } } } = {}) {
  const pending = deferred(), ref = { current: scope }; let state = initial, loading = false, error = false, calls = 0;
  const file = 'pages/SalesLeads.tsx';
  const { node, sf } = findNode(file, node => ts.isCallExpression(node) && node.expression.getText() === 'useEffect' && node.arguments[0]?.getText().includes('setInsightsLoading(true)'));
  const mod = { exports: {} };
  vm.runInNewContext(compile(`module.exports = (${node.arguments[0].getText(sf)});`), { module: mod, view: 'leads', items: [{ id: 1 }, { id: 3 }], itemsScope: acceptedScope, listScope: scope, insightsScopeRef: ref, setInsightsLoading: value => { loading = value; }, setInsightsError: value => { error = value; }, setInsightsState: value => { state = typeof value === 'function' ? value(state) : value; }, URLSearchParams, salesApi: () => { calls++; return pending.promise; } });
  const cleanup = mod.exports();
  return { pending, ref, cleanup, state: () => state, loading: () => loading, error: () => error, calls: () => calls };
}

test('same-scope insights keep overlapping lead data and prune records removed from the refreshed list', async () => {
  const app = insightFixture(); assert.equal(app.state().items[1].profile.next_step, 'Synthetic next step'); assert.equal(app.state().items[2], undefined); assert.equal(app.loading(), true);
  app.pending.resolve({ items: [{ id: 1, profile: { next_step: 'Updated synthetic step' } }, { id: 3 }, { id: 99 }] }); await flush();
  assert.equal(app.state().items[1].profile.next_step, 'Updated synthetic step'); assert.equal(app.state().items[99], undefined); assert.equal(app.loading(), false);
});

test('new insight scope waits for an accepted list and never exposes old-scope details or late responses', async () => {
  const waiting = insightFixture({ scope: 'actor1:page2', acceptedScope: 'actor1:page1' }); assert.equal(waiting.calls(), 0);
  const app = insightFixture({ scope: 'actor1:page2', initial: { scope: 'actor1:page1', items: { 1: { id: 1 } } } }); assert.equal(Object.keys(app.state().items).length, 0);
  app.ref.current = 'actor2:page2'; app.pending.resolve({ items: [{ id: 1, profile: { next_step: 'Must not return' } }] }); await flush();
  assert.equal(Object.keys(app.state().items).length, 0);
  const hidden = initializer('pages/SalesLeads.tsx', 'leadInsights', { insightsState: { scope: 'actor1:page1', items: { 1: { id: 1 } } }, listScope: 'actor2:page1', itemsScope: 'actor2:page1' }); assert.equal(Object.keys(hidden).length, 0);
});

for (const status of [401, 403, 500]) test(`insight ${status} failure withdraws unauthorized data and otherwise retains marked stale data`, async () => {
  const app = insightFixture(); app.pending.reject({ response: { status } }); await flush();
  assert.equal(app.error(), true); assert.equal(app.loading(), false);
  assert.equal(Boolean(app.state().items[1]), status === 500);
});
