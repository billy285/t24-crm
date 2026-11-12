import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const read = file => readFileSync(resolve(src, file), 'utf8');
const flush = async () => { for (let n = 0; n < 4; n++) await new Promise(done => setImmediate(done)); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const jsx = (type, props, key) => ({ type, props, key });
const compile = code => ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;

function merchant(id) {
  return { id, business_name: `Synthetic merchant ${id}`, phone: '+1202555' + String(100 + id).padStart(4, '0'), country: 'US', state: 'CA', industry: '美业', pool_status: 'pending', data_source: 'synthetic_test', collected_at: '2026-11-13T00:00:00Z', prospect_quality: { status: 'pending', revision: 0 } };
}
function poolFixture({ mobile = true, count = 41 } = {}) {
  const slots = [], effects = [], requests = [], toasts = [];
  let cursor = 0, tree, actorId = 10, records = Array.from({ length: count }, (_, i) => merchant(i + 1)), gate = null;
  const react = {
    useState(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: typeof initial === 'function' ? initial() : initial }; return [slots[i].value, value => { slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: { current: initial } }; return slots[i].value; },
    useEffect(callback, deps) { const i = cursor++, old = slots[i]; if (old && deps && deps.length === old.deps?.length && deps.every((value, n) => Object.is(value, old.deps[n]))) return; slots[i] = { deps }; effects.push(() => { old?.cleanup?.(); slots[i].cleanup = callback(); }); },
  };
  const transport = request => {
    requests.push(request);
    if (request.method !== 'GET') throw new Error('This synthetic test forbids business writes');
    if (request.url.includes('/sales-leads/assignees')) return Promise.resolve({ data: [{ id: 11, name: 'Synthetic sales' }] });
    if (request.url.endsWith('/merchant-pool/stats')) return Promise.resolve({ data: { total: records.length, pending: records.length, converted: 0, isolated: 0, duplicates: 0, archived: 0 } });
    const url = new URL(request.url, 'http://fixture.test');
    if (url.pathname === '/api/v1/merchant-pool') {
      const skip = Number(url.searchParams.get('skip') || 0), limit = Number(url.searchParams.get('limit') || 20);
      const result = { data: { items: records.slice(skip, skip + limit), total: records.length, industry_facets: [{ value: '美业', label: '美业', count: records.length }], facet_total: records.length, quality_facets: { pending: records.length, valid: 0 } } };
      if (gate?.skip === skip) { const pending = gate; gate = null; pending.result = result; return pending.promise; }
      return Promise.resolve(result);
    }
    return Promise.resolve({ data: { items: [], total: 0 } });
  };
  const mod = { exports: {} };
  const require = name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'fragment' };
    if (name === 'react-router-dom') return { useNavigate: () => () => {} };
    if (name === '@/lib/role-context') return { useRole: () => ({ employee: { id: actorId }, role: 'sales_manager', isAdmin: false }) };
    if (name === '@/hooks/use-mobile') return { useIsMobile: () => mobile };
    if (name === '@/lib/tokenStore') return { invokeWithAuth: transport };
    if (name === 'sonner') return { toast: { error: value => toasts.push(value), success: value => toasts.push(value) } };
    if (name === '@/lib/use-unsaved-changes') return { useUnsavedChanges: () => ({ confirmDiscard: () => true }), confirmDiscardAllChanges: () => true };
    if (name === '@/lib/use-auto-refresh') return { useAutoRefresh() {} };
    if (name === '@/lib/phone-format') return { formatPhoneNumber: value => value || '' };
    if (name === '@/lib/contact-timezone') return { contactTimezoneLabels: {}, contactTimezoneBasisLabel: () => '', contactTimezoneLabel: () => '', formatContactClock: () => null };
    if (name === '@/components/ui/button') return { Button: 'button' };
    if (name === '@/components/ui/input') return { Input: 'input' };
    if (name === '@/components/ui/native-select') return { NativeSelect: 'select' };
    return new Proxy({}, { get: (_target, key) => String(key) });
  };
  const window = { location: { search: '' }, history: { replaceState() {} }, confirm: () => true, setInterval: () => 1, clearInterval() {}, setTimeout: () => 1, clearTimeout() {} };
  vm.runInNewContext(`(function(require,module,exports){${compile(read('pages/MerchantPool.tsx'))}\n})`, { console, window, URLSearchParams, Date })(require, mod, mod.exports);
  const render = nextActor => { if (nextActor) actorId = nextActor; cursor = 0; tree = mod.exports.default(); while (effects.length) effects.shift()(); return tree; };
  const find = predicate => nodes(tree).find(predicate);
  const button = name => { const value = find(node => node.type === 'button' && (node.props['aria-label'] === name || text(node) === name)); assert.ok(value, `button ${name}`); return value; };
  const preview = () => find(node => node.type === 'aside' && node.props['aria-label'] === '商家资料') || find(node => node.type === 'Dialog' && node.props.open && text(node).includes('商家资料'));
  const openSelected = () => { button('查看所选资料').props.onClick(); render(); };
  const settle = async () => { for (let n = 0; n < 5; n++) { await flush(); render(); } };
  return { render, button, preview, requests, toasts, settle, openSelected, content: () => text(tree), tree: () => tree,
    select(id) { if (mobile) button(`分配：Synthetic merchant ${id}`).props.onClick(); else find(node => node.type === 'input' && node.props['aria-label'] === `选择 Synthetic merchant ${id}`).props.onChange({ target: { checked: true } }); render(); },
    pageNext() { button('下一页').props.onClick(); render(); },
    pageSize(value) { find(node => node.type === 'select' && node.props.options?.some(option => option.value === '100')).props.onChange(String(value)); render(); },
    delay(skip) { gate = { ...deferred(), skip }; return gate; },
    records(next) { records = next; },
  };
}

for (const mobile of [true, false]) test(`cross-page selected preview returns to an accepted fresh page without writes (${mobile ? 'phone' : 'desktop'})`, async () => {
  const app = poolFixture({ mobile }); app.render(); await app.settle(); app.select(1); app.pageNext(); await app.settle();
  assert.match(app.content(), /跨页已选 1 家商家/);
  const pending = app.delay(0); app.openSelected();
  assert.match(app.content(), /正在定位第 1 页/); assert.equal(Boolean(app.preview()), false);
  const region = nodes(app.tree()).find(node => node.props['aria-label'] === '商家批量操作'); assert.equal(region.props['aria-busy'], true);
  pending.resolve(pending.result); await app.settle();
  assert.ok(app.preview()); assert.match(text(app.preview()), /Synthetic merchant 1/);
  assert.match(app.content(), /跨页已选 1 家商家/);
  assert.equal(new URL(app.requests.filter(request => request.url.includes('/merchant-pool?')).at(-1).url, 'http://fixture.test').searchParams.get('skip'), '0');
  assert.equal(app.requests.some(request => request.method !== 'GET'), false);
});

test('selected offset adapts to a new page size and still opens a current record', async () => {
  const app = poolFixture({ count: 81 }); app.render(); await app.settle();
  for (let n = 0; n < 3; n++) { app.pageNext(); await app.settle(); }
  app.select(71); app.pageSize(50); await app.settle(); app.openSelected(); await app.settle();
  assert.match(text(app.preview()), /Synthetic merchant 71/);
  const url = new URL(app.requests.filter(request => request.url.includes('/merchant-pool?')).at(-1).url, 'http://fixture.test');
  assert.equal(url.searchParams.get('skip'), '50'); assert.equal(url.searchParams.get('limit'), '50');
});

test('a missing/reordered selected record gives feedback and keeps cross-page selection', async () => {
  const app = poolFixture(); app.render(); await app.settle(); app.select(1); app.pageNext(); await app.settle();
  app.records(Array.from({ length: 41 }, (_, i) => merchant(i + 2))); app.openSelected(); await app.settle();
  assert.equal(Boolean(app.preview()), false); assert.match(app.content(), /暂未找到所选商家，选择仍保留/);
  assert.match(app.content(), /跨页已选 1 家商家/); assert.ok(app.toasts.some(value => value.includes('暂未找到')));
});

test('changing page size during location cancels the pending preview without losing selection', async () => {
  const app = poolFixture(); app.render(); await app.settle(); app.select(1); app.pageNext(); await app.settle();
  const pending = app.delay(0); app.openSelected(); app.pageSize(50); pending.resolve(pending.result); await app.settle();
  assert.equal(Boolean(app.preview()), false); assert.match(app.content(), /每页数量已调整，选择仍保留/); assert.match(app.content(), /跨页已选 1 家商家/);
  app.openSelected(); await app.settle(); assert.match(text(app.preview()), /Synthetic merchant 1/);
});

test('failed location fetch preserves the existing failure withdrawal and allocation guards', async () => {
  const app = poolFixture(); app.render(); await app.settle(); app.select(1); app.pageNext(); await app.settle();
  const pending = app.delay(0); app.openSelected(); pending.reject({ response: { status: 403 } }); await app.settle();
  assert.equal(Boolean(app.preview()), false); assert.doesNotMatch(app.content(), /跨页已选/);
  assert.match(app.content(), /当前筛选加载失败/); assert.equal(app.requests.some(request => request.method !== 'GET'), false);
});

test('identity changes cancel pending location and late accepted pages cannot expose old preview', async () => {
  const app = poolFixture(); app.render(); await app.settle(); app.select(1); app.pageNext(); await app.settle();
  const pending = app.delay(0); app.openSelected(); app.render(20); pending.resolve(pending.result); await app.settle();
  assert.equal(Boolean(app.preview()), false); assert.doesNotMatch(app.content(), /跨页已选/);
});

function recentCallsFixture(count = 29) {
  const file = 'pages/SalesLeads.tsx', sf = ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const candidates = [], declarations = new Map(); let reset;
  const walk = node => {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(sf) === 'section' && node.getText(sf).includes('最近官方通话')) candidates.push(node);
    if (ts.isVariableDeclaration(node)) declarations.set(node.name.getText(sf), node);
    if (ts.isCallExpression(node) && node.expression.getText(sf) === 'useEffect' && node.arguments[0]?.getText(sf).includes('setRecentCallsVisibleCount(12)')) { assert.equal(node.arguments[1]?.getText(sf), '[callReportDays, missingCRMOnly]'); reset = node.arguments[0]; }
    ts.forEachChild(node, walk);
  }; walk(sf);
  const section = candidates.sort((a, b) => a.getWidth(sf) - b.getWidth(sf))[0]; assert.ok(section); assert.ok(reset);
  let visible = 12, missing = false, tree; const opened = [];
  const calls = Array.from({ length: count }, (_, n) => ({ id: n + 1, lead_id: n + 1, salesperson: 'Synthetic sales', business_name: `Synthetic call ${n + 1}`, remote_phone: '+12025550111', started_at: '2026-11-13T00:00:00Z', connected: true, duration_seconds: 30, result: '合成接通', crm_recorded: n % 2 === 1 }));
  const setVisible = value => { visible = typeof value === 'function' ? value(visible) : value; };
  const render = () => {
    const mod = { exports: {} }, context = { module: mod, exports: mod.exports, callReport: { recent_calls: calls }, missingCRMOnly: missing, recentCallsVisibleCount: visible, setRecentCallsVisibleCount: setVisible, setMissingCRMOnly: value => { missing = typeof value === 'function' ? value(missing) : value; }, setDossierId: id => opened.push(id), Button: 'button', Badge: 'badge', formatPhoneNumber: value => value, formatDate: value => value, formatDuration: value => `${value}秒`, require: name => name === 'react/jsx-runtime' ? { jsx, jsxs: jsx } : {} };
    for (const name of ['loadedRecentCalls', 'filteredRecentCalls', 'visibleRecentCalls', 'remainingRecentCalls']) {
      const declaration = declarations.get(name); assert.ok(declaration); const value = { exports: {} };
      vm.runInNewContext(compile(`module.exports = (${declaration.initializer.getText(sf)});`), { ...context, module: value }); context[name] = value.exports;
    }
    vm.runInNewContext(compile(`module.exports = (${section.getText(sf)});`), context); tree = mod.exports; return tree;
  };
  const button = pattern => nodes(tree).find(node => node.type === 'button' && pattern.test(text(node)));
  const resetScope = () => vm.runInNewContext(compile(`(${reset.getText(sf)})();`), { setRecentCallsVisibleCount: setVisible });
  return { render, button, opened, calls, content: () => text(tree), rows: () => nodes(tree).filter(node => typeof node.key === 'number' && calls.some(call => call.id === node.key)), resetScope, visible: () => visible };
}

test('all loaded calls can be expanded and collapsed with exact limited-scope counts', () => {
  const app = recentCallsFixture(); app.render(); assert.equal(app.rows().length, 12); assert.match(app.content(), /最近载入的 29 条/);
  app.button(/显示更多/).props.onClick(); app.render(); assert.equal(app.rows().length, 24);
  app.button(/显示更多/).props.onClick(); app.render(); assert.equal(app.rows().length, 29); assert.equal(app.button(/显示更多/), undefined);
  assert.match(app.content(), /当前显示 29 \/ 29 条/); assert.match(app.content(), /仅限已载入的 29 条/);
  const last = app.rows().find(row => row.key === 29); nodes(last).find(node => node.type === 'button' && text(node) === '打开档案补录').props.onClick(); assert.deepEqual(app.opened, [29]);
  assert.match(app.button(/收起至12条/).props.className, /min-h-11/); app.button(/收起至12条/).props.onClick(); app.render(); assert.equal(app.rows().length, 12);
});

test('pending-CRM filter and period changes reset expansion without altering loaded-data scope', () => {
  const app = recentCallsFixture(); app.render(); app.button(/显示更多/).props.onClick(); app.render();
  app.button(/只看待补CRM结果/).props.onClick(); app.resetScope(); app.render(); assert.equal(app.rows().length, 12); assert.match(app.content(), /12 \/ 15 条待补记录/);
  app.button(/显示更多/).props.onClick(); app.render(); assert.equal(app.rows().length, 15); assert.match(app.content(), /仅限已载入的 29 条/);
  app.resetScope(); app.render(); assert.equal(app.rows().length, 12);
  app.button(/查看全部最近记录/).props.onClick(); app.resetScope(); app.render(); assert.equal(app.rows().length, 12);
});

test('empty loaded-call result keeps the existing empty state and no show-more control', () => {
  const app = recentCallsFixture(0); app.render(); assert.equal(app.rows().length, 0); assert.equal(app.button(/显示更多/), undefined); assert.match(app.content(), /暂无RingCentral官方通话记录/);
});
