import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(body, imports = {}, extra = {}) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { module, exports: module.exports, require: key => imports[key] || {}, Set, Map, AbortController, ...extra });
  return module.exports;
}
const monthly = compile(source('../src/lib/media-monthly-api.ts'));
const api = compile(source('../src/lib/media-monthly-attention.ts'), {'./media-monthly-api':monthly});
const result = extra => ({ customer_id: 20, run_id: 1, items: [], counts: { attention: 0, total: 0, blocked: 0, unknown: 0, missed: 0, failed: 0, pending_confirmation: 1 }, ...extra });
const alert = extra => ({ key: 'schedule:1:unknown', version: 'a'.repeat(64), level: 'warning', status: 'unknown', title: '结果待确认', message: '读取原发布结果，勿重复发送。', ...extra });
const label = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(label).join('') : label(node.props?.children);
const nodes = node => node == null || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(extra = {}) {
  let si = 0, ri = 0, ei = 0;
  const states = [], refs = [], effects = [], queue = [], requests = [], timers = new Map(), listeners = new Map(), opened = [];
  const props = { scope: 'owner:1', isOwner: true, customerId: 20, visible: true, refreshToken: 0, onOpen: id => opened.push(id), ...extra };
  const hooks = {
    useState(value) { const i = si++; if (!(i in states)) states[i] = typeof value === 'function' ? value() : value; return [states[i], next => states[i] = typeof next === 'function' ? next(states[i]) : next]; },
    useRef(value) { const i = ri++; if (!(i in refs)) refs[i] = { current: value }; return refs[i]; },
    useEffect(fn, deps) { const i = ei++, old = effects[i]; if (!old || old.deps.some((value, n) => value !== deps[n])) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; }); },
  };
  const document = { visibilityState: 'visible', addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key) };
  const window = { setInterval: fn => { const id = timers.size + 1; timers.set(id, fn); return id; }, clearInterval: id => timers.delete(id) };
  const jsx = (type, props, key) => ({ type, props, key });
  const exports = compile(source('../src/components/MediaMonthlyAttention.tsx'), {
    react: hooks, 'react/jsx-runtime': { jsx, jsxs: jsx }, 'lucide-react': {}, '@/components/ui/button': { Button: 'Button' },
    '@/lib/media-monthly-attention': api,
    '@/lib/media-monthly-api': { ...monthly, monthlyApi: (path, method, body, signal) => new Promise((resolve, reject) => requests.push({ path, method, body, signal, resolve, reject })) },
  }, { window, document });
  return { props, requests, timers, listeners, document, opened,
    render() { si = ri = ei = 0; const root = exports.default(props); return root && typeof root.type === 'function' ? root.type(root.props) : root; },
    effects() { while (queue.length) queue.shift()(); },
    unmount() { effects.forEach(effect => effect.cleanup?.()); },
  };
}

test('monthly attention rejects cross-customer, incomplete counts, invalid batch and duplicate warning versions', () => {
  for (const value of [result({ customer_id: 21 }), result({ run_id: null }), result({ counts: { total: 0 } }), result({ items: [alert(), alert()] }), result({ items: [alert({ version: 'unverified' })] })]) assert.throws(() => api.verifiedMonthlyAttention(value));
  assert.equal(api.verifiedMonthlyAttention(result()).counts.pending_confirmation, 1);
});
test('staff, all-merchant scope and hidden provider pane perform zero attention requests', () => {
  for (const props of [{ isOwner: false }, { customerId: null }, { customerId: 0 }, { visible: false }]) { const h = harness(props); assert.equal(h.render(), null); h.effects(); assert.equal(h.requests.length, 0); }
});
test('owner reminder separates pending confirmation from actual publishing failure and opens exact run', async () => {
  const h = harness(); h.render(); h.effects(); assert.equal(h.requests[0].method, 'GET');
  h.requests[0].resolve(result()); await tick(); const tree = h.render();
  assert.match(label(tree), /1 批等待你确认/); assert.match(label(tree), /当前未发现发布异常/);
  nodes(tree).find(node => node.type === 'Button').props.onClick(); assert.deepEqual(h.opened, [1]);
});
test('failed reads do not report zero pending or success', async () => {
  const h = harness(); h.render(); h.effects(); h.requests[0].reject(new Error('network')); await tick();
  assert.match(label(h.render()), /当前无法确认是否有待办/); assert.doesNotMatch(label(h.render()), /当前未发现发布异常/);
});
test('visibility refresh and timer read only local alerts; unmount aborts late results', async () => {
  const h = harness(); h.render(); h.effects(); h.requests[0].resolve(result()); await tick();
  h.document.visibilityState = 'hidden'; [...h.timers.values()][0](); assert.equal(h.requests.length, 1);
  h.document.visibilityState = 'visible'; h.listeners.get('visibilitychange')(); assert.equal(h.requests.length, 2);
  h.unmount(); assert.equal(h.requests[1].signal.aborted, true); assert.equal(h.timers.size, 0); assert.equal(h.listeners.size, 0);
  h.requests[1].resolve(result({ items: [alert()], counts: { ...result().counts, attention: 1, total: 1, unknown: 1 } })); await tick();
  assert.doesNotMatch(label(h.render()), /1 项发布异常待处理/); assert.equal(h.requests.every(row => row.method === 'GET' && row.path === '/customers/20/workflow-alerts?platform=google_business'), true);
});


test('another selected merchant reads only its exact month and does not show a stale month result', async () => {
  const h = harness({ customerId:31, customerName:'LOCAL TEST 31', month:'2027-03' });h.render();h.effects();
  assert.equal(h.requests[0].path,'/customers/31/workflow-alerts?platform=google_business&month=2027-03');
  h.requests[0].resolve(result({customer_id:31,month:'2027-04'}));await tick();
  assert.match(label(h.render()),/当前无法确认是否有待办/);
  assert.throws(()=>api.verifiedMonthlyAttention(result({customer_id:32,month:'2027-03'}),31,'2027-03'));
  assert.equal(api.verifiedMonthlyAttention(result({customer_id:31,month:'2027-03'}),31,'2027-03').customer_id,31);
});

test('Meta reminder is pinned to exact platform and cannot reuse a Google result',async()=>{const h=harness({platform:'instagram',month:'2026-11'});h.render();h.effects();assert.equal(h.requests[0].path,'/customers/20/workflow-alerts?platform=instagram&month=2026-11');h.requests[0].resolve(result({platform:'instagram',month:'2026-11'}));await tick();assert.match(label(h.render()),/Instagram/);assert.throws(()=>api.verifiedMonthlyAttention(result({month:'2026-11'}),20,'2026-11','instagram'));});
