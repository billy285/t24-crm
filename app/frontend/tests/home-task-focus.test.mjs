import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = file => fs.readFileSync(new URL('../src/' + file, import.meta.url), 'utf8');
const compile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const nodes = tree => !tree || typeof tree !== 'object' ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const text = tree => tree == null || typeof tree === 'boolean' ? '' : typeof tree !== 'object' ? String(tree) : Array.isArray(tree) ? tree.map(text).join('') : text(tree.props?.children);
const tick = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
function fixture(file, exported, response, role = 'super_admin') {
  const slots = [], effects = [], requests = []; let cursor = 0, tree;
  const react = {
    useState(initial) { const i = cursor++; slots[i] ||= { value: typeof initial === 'function' ? initial() : initial }; return [slots[i].value, value => slots[i].value = typeof value === 'function' ? value(slots[i].value) : value]; },
    useRef(initial) { const i = cursor++; slots[i] ||= { value: { current: initial } }; return slots[i].value; },
    useId() { cursor++; return 'fixture-exceptions'; },
    useCallback(callback, deps) { const i = cursor++, old = slots[i]; if (old && deps.every((v, n) => Object.is(v, old.deps[n]))) return old.callback; slots[i] = { callback, deps }; return callback; },
    useEffect(callback, deps) { const i = cursor++, old = slots[i]; if (old && deps.length === old.deps.length && deps.every((v, n) => Object.is(v, old.deps[n]))) return; slots[i] = { deps }; effects.push(() => { old?.cleanup?.(); slots[i].cleanup = callback(); }); },
  };
  const count = value => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
  const require = name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' };
    if (name === 'react-router-dom') return { useLocation: () => ({ pathname: '/', search: '' }), useNavigate: () => () => {} };
    if (name === '@/lib/role-context') return { useRole: () => ({ role }) };
    if (name === '@/lib/use-auto-refresh') return { useAutoRefresh() {} };
    if (name === '@/lib/navigation-state') return { buildReturnLink: value => value, getSafeInternalPath: value => value };
    if (name === '@/lib/service-follow-through') return { followThroughApi: async path => { requests.push(path); return response(); }, followThroughAccessDenied: error => [401, 403].includes(error?.status), followThroughError: (_error, fallback) => fallback, followThroughHref: value => value?.startsWith('/') ? value : null, followThroughDate: () => 'fixture time' };
    if (name === './sales-handoff-navigation') return { ownerExceptionTaskHref: item => item.href };
    if (name === '@/lib/stripe-history-reconciliation') return { stripeReconciliationApi: async path => { requests.push(path); return response(); }, stripeReconciliationDenied: error => [401, 403].includes(error?.status), stripeReconciliationError: (_error, fallback) => fallback, reconciliationMoney: () => '$0', reconciliationTime: () => 'fixture time' };
    if (name === '@/lib/stripe-history-reminders') { const mod = { exports: {} }; vm.runInNewContext(`(function(require,module,exports){${compile(source('lib/stripe-history-reminders.ts'))}\n})`, { URLSearchParams })(require, mod, mod.exports); return mod.exports; }
    if (name === '@/lib/stripe-auto-posting') return { autoPostingCount: count, safeAutoPostingTotals: value => Array.isArray(value) ? value : null, autoPostingTotalsCount: value => Array.isArray(value) ? value.reduce((sum, row) => sum + row.count, 0) : null };
    if (name === '@/components/ui/button') return { Button: 'button' };
    return new Proxy({}, { get: (_target, key) => String(key) });
  };
  const mod = { exports: {} }; vm.runInNewContext(`(function(require,module,exports){${compile(source(file))}\n})`, { console })(require, mod, mod.exports);
  return { render() { cursor = 0; tree = mod.exports[exported]({ compact: true }); while (effects.length) effects.shift()(); return tree; }, tree: () => tree, requests };
}
const counts = { pending_receipt: 0, pending_access: 0, pending_operations: 0, kickoff_missing: 0, kickoff_blocked: 0, kickoff_overdue: 0, renewal_attention: 0, renewal_unconnected: 0, total_actions: 1 };
const ownerData = overrides => ({ counts: { ...counts, ...overrides }, generated_at: '2026-11-13', items: [{ id: 1, title: 'FIRST REAL EXCEPTION', business_name: 'LOCAL CUSTOMER', href: '/tasks?task_id=1', waiting_days: 2 }] });
async function owner(overrides) { const app = fixture('components/ServiceFollowThrough.tsx', 'OwnerExceptions', () => ownerData(overrides)); app.render(); await tick(); app.render(); return app; }

test('real owner exception rows come before Stripe and count lanes without changing backend order', async () => {
  const app = await owner({ pending_receipt: 2 }); const all = nodes(app.tree());
  const list = all.findIndex(n => n.props?.className === 'sf-exception-list'), lane = all.findIndex(n => n.props?.className === 'sf-work-lanes'), stripe = all.findIndex(n => n.type === 'default');
  assert.ok(list >= 0 && lane > list); assert.ok(stripe > list); assert.match(text(all[list]), /FIRST REAL EXCEPTION/);
});
test('all eight exact zero states are in one closed disclosure and zero owner/team lanes are omitted', async () => {
  const app = await owner(); const all = nodes(app.tree()); assert.equal(all.some(n => n.props?.className === 'sf-work-lanes'), false);
  const quiet = all.find(n => n.type === 'details' && n.props.className === 'sf-owner-quiet-statuses'); assert.ok(quiet); assert.equal(quiet.props.open, undefined); assert.match(text(quiet), /8 项当前为 0/); assert.equal(nodes(quiet).filter(n => n.type === 'button').length, 8);
});
test('unknown owner counts stay visible as unknown rather than being folded as zero', async () => {
  const app = await owner({ pending_receipt: undefined }); const lane = nodes(app.tree()).find(n => n.props?.['aria-label'] === '待我处理'); assert.ok(lane); assert.match(text(lane), /待核款—/);
});
test('owner read failures stay direct and denied data is withdrawn', async () => {
  for (const status of [500, 403]) { let failure = false; const app = fixture('components/ServiceFollowThrough.tsx', 'OwnerExceptions', () => failure ? Promise.reject({ status }) : ownerData()); app.render(); await tick(); app.render(); failure = true; nodes(app.tree()).find(n => n.props?.['aria-label'] === '刷新老板异常总览').props.onClick(); await tick(); const tree = app.render(); assert.ok(nodes(tree).some(n => n.props?.role === 'alert')); assert.equal(text(tree).includes('FIRST REAL EXCEPTION'), status !== 403); }
});
const stripeData = ({ pending = 0, exception = 0, retry = 0, automatic = 0, warning = false } = {}) => ({ manual_pending: pending, counts: { pending_review: pending, needs_refresh: 0, exception, total: pending + exception }, items: [], exception_items: [], daily_scan: { enabled: !warning, last_run_status: warning ? 'disabled' : 'completed', last_completed_at: 'fixture time', last_run_at: 'fixture time', active_bindings: 1, covered_bindings: 1, retry_bindings: retry, running_bindings: 0, catchup_bindings: 0, last_discovered_reviews: 0 }, auto_posting: { today_totals: [], counts: { manual_required: automatic }, enabled_count: 1 } });
async function stripe(value, fail = false) { const app = fixture('components/StripeHistoryReminders.tsx', 'default', () => fail ? Promise.reject({ status: 500 }) : value); app.render(); await tick(); app.render(); return app; }
test('quiet compact Stripe controls and metadata remain available in a closed summary', async () => {
  const app = await stripe(stripeData()); const disclosure = nodes(app.tree()).find(n => n.type === 'details' && n.props.className === 'shr-routine-disclosure'); assert.ok(disclosure); assert.equal(disclosure.props.open, undefined); assert.match(text(disclosure), /待核 0 · 异常 0 · 自动待处理 0/); assert.ok(nodes(disclosure).some(n => n.props?.['aria-label'] === 'Stripe 自动入账摘要'));
});
for (const [kind, value] of Object.entries({ pending: { pending: 1 }, exception: { exception: 1 }, retry: { retry: 1 }, automatic: { automatic: 1 }, warning: { warning: true } })) test(`Stripe ${kind} risk stays outside the routine disclosure`, async () => {
  const app = await stripe(stripeData(value)); assert.equal(nodes(app.tree()).some(n => n.props?.className === 'shr-routine-disclosure'), false); assert.ok(nodes(app.tree()).some(n => n.props?.className === 'shr-reminders-top'));
});
test('unknown Stripe counts remain directly visible instead of being treated as quiet zero', async () => {
  const value = stripeData(); value.auto_posting = undefined; const app = await stripe(value); assert.equal(nodes(app.tree()).some(n => n.props?.className === 'shr-routine-disclosure'), false); assert.match(text(app.tree()), /自动记账待处理—/);
});
test('unconfirmed scan coverage stays direct even when known pending counts are zero', async () => {
  const value = stripeData(); value.daily_scan.last_run_status = 'never'; const app = await stripe(value); assert.equal(nodes(app.tree()).some(n => n.props?.className === 'shr-routine-disclosure'), false); assert.match(text(app.tree()), /等待首次补查/);
});
test('Stripe loading failure is directly visible and never folded as routine status', async () => {
  const app = await stripe(null, true); assert.equal(nodes(app.tree()).some(n => n.props?.className === 'shr-routine-disclosure'), false); assert.match(text(app.tree()), /Stripe 待核提醒暂时无法读取/);
});
test('task clamps target only route scoped list names; task detail retains its full title and notes', () => {
  const css = source('components/crm-final-home-tasks.css'), tasks = source('pages/Tasks.tsx'); assert.match(css, /-webkit-line-clamp: 2/); assert.match(css, /data-crm-page="\/tasks"/); assert.match(css, /min-height: 44px/); assert.match(tasks, /title=\{t.title\} className=\{`fp-task-title/); assert.match(tasks, /title=\{t.customer_name\}/); assert.match(tasks, /taskDetails\.title/); assert.match(tasks, /taskDetails\.notes/); assert.ok(!css.includes('taskDetails'));
});
