import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

// Exercise the actual component handlers with a synthetic React lifecycle and
// API transport. No browser, OAuth provider or real call is used.
const file = resolve(dirname(fileURLToPath(import.meta.url)), '../src/components/SalesPhoneConnections.tsx');
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(done => setImmediate(done)); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
const nodes = tree => !tree || typeof tree !== 'object' ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const connected = employee_id => ({ employee_id, employee_name: `Sales ${employee_id}`, connected: true, realtime_sync_enabled: true, last_synced_at: '2026-11-10T01:00:00Z', extension_number: String(employee_id) });

function fixture(handler, initialActor = { employee: { id: 11 }, role: 'sales_manager' }) {
  const slots = [], effects = [], requests = [], redirects = [];
  let cursor = 0, actor = initialActor, tree, unmounted = false, lateWrites = 0, complete = 0;
  const react = {
    useState(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: initial }; return [slots[i].value, value => { if (unmounted) lateWrites++; slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: { current: initial } }; return slots[i].value; },
    useCallback(callback) { cursor++; return callback; },
    useEffect(callback, deps) { const i = cursor++, prior = slots[i]; if (prior && deps.every((v,n) => Object.is(v,prior.deps[n]))) return; slots[i] = { deps }; effects.push(() => { prior?.cleanup?.(); slots[i].cleanup = callback(); }); },
  };
  const mod = { exports: {} };
  const require = name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' };
    if (name === '@/lib/role-context') return { useRole: () => actor };
    if (name === '@/components/ui/button') return { Button: 'button' };
    if (name === '@/lib/tokenStore') return { invokeWithAuth: async request => { requests.push(request); return handler(request); } };
    return new Proxy({}, { get: (_target, key) => String(key) });
  };
  const code = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const window = { setInterval: () => 1, clearInterval() {}, location: { assign: url => redirects.push(url) } };
  vm.runInNewContext(`(function(require,module,exports){${code}\n})`, { console, window, Intl, Date })(require, mod, mod.exports);
  const render = nextActor => { if (nextActor) actor = nextActor; cursor = 0; tree = mod.exports.default({ periodDays: 30, onSyncComplete: () => complete++ }); while (effects.length) effects.shift()(); return tree; };
  const button = label => { const found = nodes(tree).find(node => node.type === 'button' && text(node) === label); assert.ok(found, `Button ${label}`); return found; };
  return { render, button, requests, redirects, content: () => text(tree), completed: () => complete,
    unmount() { unmounted = true; for (const slot of slots) slot?.cleanup?.(); }, lateWrites: () => lateWrites,
    coverage: props => mod.exports.SyncCoverageDetails(props) };
}

test('manager can act only on own binding; duplicate click sends one explicit bounded sync', async () => {
  const pending = deferred();
  const app = fixture(request => request.method === 'GET' ? { data: { items: [connected(11), connected(12)] } } : pending.promise);
  app.render(); await flush(); app.render();
  assert.ok(app.requests[0].url.endsWith('days=30'));
  assert.equal(nodes(app.render()).filter(node => node.type === 'button' && text(node) === '补同步我的通话').length, 1);
  const sync = app.button('补同步我的通话'); sync.props.onClick(); sync.props.onClick();
  assert.deepEqual(app.requests.filter(r => r.method === 'POST').map(r => r.url), ['/api/ringcentral/sync?days=7']);
  pending.resolve({ data: { synced: 0, sync_window: { status: 'completed' } } }); await flush(); app.render();
  assert.equal(app.completed(), 1); assert.match(app.content(), /历史完整性仍待核验/);
  assert.equal(app.redirects.length, 0);
});

test('subscription repair failure does not start a backfill and remains actionable', async () => {
  const item = { ...connected(11), realtime_sync_enabled: false, last_error: 'subscription expired' };
  const app = fixture(request => request.method === 'GET' ? { data: { items: [item] } } : Promise.reject({ response: { data: { detail: '请检查实时订阅权限' } } }));
  app.render(); await flush(); app.render(); app.button('修复实时同步并补同步').props.onClick(); await flush(); app.render();
  assert.deepEqual(app.requests.filter(r => r.method === 'POST').map(r => r.url), ['/api/ringcentral/subscription/ensure']);
  assert.match(app.content(), /请检查实时订阅权限/);
});

test('explicit 30-day selection changes only the current employee sync window', async () => {
  const app = fixture(request => request.method === 'GET' ? { data: { items: [connected(11)] } } : { data: { synced: 0, sync_window: { status: 'completed' } } });
  app.render(); await flush(); app.render();
  nodes(app.render()).find(node => node.type === 'select').props.onChange({ target: { value: '30' } });
  app.render(); app.button('补同步我的通话').props.onClick(); await flush();
  assert.deepEqual(app.requests.filter(r => r.method === 'POST').map(r => r.url), ['/api/ringcentral/sync?days=30']);
});

test('binding conflict has no reconnect, repair or backfill action', async () => {
  const app = fixture(() => ({ data: { items: [{ ...connected(11), binding_conflict: true, realtime_sync_enabled: false }] } }));
  app.render(); await flush(); app.render();
  const actions = nodes(app.render()).filter(node => node.type === 'button').map(text);
  assert.equal(actions.some(label => /补同步我的|重新连接我的|修复实时同步/.test(label)), false);
  assert.match(app.content(), /同一分机绑定了多个员工/);
  assert.equal(app.requests.filter(r => r.method !== 'GET').length, 0);
});

test('changing logged-in employee during repair cannot continue sync under the new identity', async () => {
  const pending = deferred();
  const app = fixture(request => request.method === 'GET' ? { data: { items: [{ ...connected(11), realtime_sync_enabled: false }] } } : pending.promise);
  app.render(); await flush(); app.render(); app.button('修复实时同步并补同步').props.onClick();
  app.render({ employee: { id: 12 }, role: 'sales' }); pending.resolve({ data: {} }); await flush(); app.render();
  assert.equal(app.requests.filter(r => r.url.includes('/sync?')).length, 0);
  assert.equal(app.completed(), 0);
});

test('unmount while authorizing cannot redirect or write late state', async () => {
  const pending = deferred();
  const app = fixture(request => request.url.includes('team-status') ? { data: { items: [{ ...connected(11), connected: false, realtime_sync_enabled: false }] } } : pending.promise);
  app.render(); await flush(); app.render(); app.button('连接我的RingCentral').props.onClick(); app.unmount();
  pending.resolve({ data: { authorization_url: 'https://provider.invalid/never-open' } }); await flush();
  assert.equal(app.redirects.length, 0); assert.equal(app.lateWrites(), 0);
});

test('fetch window with zero calls still states historical completeness is unverified', () => {
  const app = fixture(() => ({ data: { items: [] } }));
  const node = app.coverage({ coverage: { status: 'window_fetched', data_complete: false, requested_from: '2026-11-01T00:00:00Z', requested_to: '2026-11-02T00:00:00Z', unverified_ranges: [], last_attempt: { status: 'completed', requested_from: '2026-11-01T00:00:00Z', requested_to: '2026-11-02T00:00:00Z', pages: 1, fetched: 0, saved: 0, skipped: 0 } } });
  assert.match(text(node), /分页拉取完成/); assert.match(text(node), /仍不代表历史完整/);
});
