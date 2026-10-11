import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import { adsFixture } from './fixtures/private-ads.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const same = (left, right) => left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const mail = (id, bucket = 'today') => ({
  id, source_id: 'gmail', kind: 'email', title: `Synthetic ${id}`, summary: 'Synthetic snippet', status: 'unread', priority: bucket === 'urgent' ? 'urgent' : 'high',
  amount_minor: null, currency: null, occurred_at: null, due_at: null, source_url: null, evidence: { from: 'Synthetic <sender@example.com>' }, action_status: 'open', snoozed_until: null,
  mail_relevance: { bucket, category: bucket === 'urgent' ? 'security' : 'business', reasons: ['Synthetic reason'], feedback: null, sender_address: 'sender@example.com', sender_verification: 'unverified' },
});
const briefSnapshot = (period = 'today', overrides = {}) => ({
  snapshot_id: `synthetic-${period}`, period, generated_at: '2026-10-11T08:00:00Z',
  window: { start: '2026-10-10T16:00:00Z', end: '2026-10-11T16:00:00Z', timezone: 'Asia/Shanghai' },
  issues: [], sources: [], capabilities: { configured: false, code: 'not_configured' }, limitations: [], ai: null, ...overrides,
});
const bossSource = (source_id = 'stripe', data_state = 'partial') => ({ source_id, status: 'connected', last_sync: new Date().toISOString(), data_state, summary: '已同步局部来源记录，完整范围仍需核对。', facts: [] });

// Run the actual component, API and draft guard against synthetic transport and
// controlled hook scheduling. No mailbox, browser storage or external API is used.
function fixture(items = [mail('message')], initialView = 'gmail', extraSources = [], overviewBalances = [], navigation = {}) {
  let cursor = 0, epoch = 'synthetic-owner', tree, now = Date.now();
  const timers = new Map();
  class SyntheticDate extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
  let hooks = [];
  const componentHooks = new Map([['root', hooks]]), effects = [], requests = [], listeners = new Map(), modules = new Map();
  const params = new URLSearchParams({ view: initialView, ...navigation.params });
  let historyIndex = 0, routeSequence = 0;
  const history = [{ pathname: '/private-workspace', search: `?${params}`, key: 'route-0', state: navigation.state || null }];
  const navigationCalls = [], scrollCalls = [];
  let overviewHandler, bankStartHandler, bankCompleteHandler, preferencesHandler, syncHandler, translationPreviewHandler, translationBodyHandler, mailCapabilitiesHandler, mailBriefHandler, briefHandler, explainHandler, stripeReportHandler;
  const preferences = { sync_interval_seconds: 2700, gmail: { topics: ['finance', 'security'], watch_senders: [], watch_keywords: [], muted_senders: [] } };
  const source = { id: 'gmail', status: 'connected', capabilities: [], missing_configuration: [], last_sync: null, error: null };
  const react = {
    useState(initial) { const index = cursor++; if (!hooks[index]) hooks[index] = { value: typeof initial === 'function' ? initial() : initial }; const hook = hooks[index]; return [hook.value, next => { hook.value = typeof next === 'function' ? next(hook.value) : next; }]; },
    useRef(initial) { const index = cursor++; if (!hooks[index]) hooks[index] = { value: { current: initial } }; return hooks[index].value; },
    useMemo(factory, dependencies) { const index = cursor++; if (!hooks[index] || !same(hooks[index].dependencies, dependencies)) hooks[index] = { value: factory(), dependencies }; return hooks[index].value; },
    useCallback(callback, dependencies) { return react.useMemo(() => callback, dependencies); },
    useEffect(effect, dependencies) { const index = cursor++; if (!hooks[index] || !same(hooks[index].dependencies, dependencies)) { const previous = hooks[index]; const hook = hooks[index] = { dependencies, cleanup: previous?.cleanup }; effects.push({ cleanup: () => hook.cleanup?.(), setup: () => { hook.cleanup = effect(); } }); } },
  };
  react.useLayoutEffect = react.useEffect;
  const window = { scrollY: 0, scrollTo: options => { scrollCalls.push(options); window.scrollY = typeof options === 'number' ? options : options.top; }, setInterval: callback => { const id = timers.size + 1; timers.set(id, callback); return id; }, clearInterval: id => timers.delete(id), confirm: () => true, location: { assign: () => { throw new Error('No OAuth expected'); } }, addEventListener: (name, listener) => { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(listener); }, removeEventListener: (name, listener) => listeners.get(name)?.delete(listener) };
  function copyParams(search) { for (const key of [...params.keys()]) params.delete(key); for (const [key, value] of new URLSearchParams(search)) params.append(key, value); }
  function allowNavigation(nextSearch) {
    // The real application's router blocker protects native POP as well as its
    // buttons. Run its shared draft guard instead of making back always succeed.
    if (nextSearch === `?${params}`) return true;
    return load('lib/use-unsaved-changes.ts').confirmDiscardAllChanges();
  }
  function setSearchParams(next, options = {}) {
    const search = `?${new URLSearchParams(typeof next === 'function' ? next(params) : next)}`;
    if (!allowNavigation(search)) return;
    const entry = { pathname: '/private-workspace', search, key: `route-${++routeSequence}`, state: options.state || null };
    navigationCalls.push({ type: options.replace ? 'REPLACE' : 'PUSH', search, state: options.state || null });
    if (options.replace) history[historyIndex] = entry;
    else { history.splice(historyIndex + 1); history.push(entry); historyIndex++; }
    copyParams(search);
  }
  function navigateRoute(delta) {
    assert.equal(typeof delta, 'number', 'private internal back must use a history delta');
    const nextIndex = historyIndex + delta;
    if (nextIndex < 0 || nextIndex >= history.length) return false;
    const next = history[nextIndex];
    if (!allowNavigation(next.search)) return false;
    navigationCalls.push({ type: 'POP', delta }); historyIndex = nextIndex; copyParams(next.search);
    return true;
  }
  const context = vm.createContext({ URL, URLSearchParams, Intl, Date: SyntheticDate, window, console });
  function load(relative) {
    if (modules.has(relative)) return modules.get(relative);
    const path = resolve(root, relative);
    const compiled = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const module = { exports: {} };
    const require = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return jsx;
      if (name === 'react-router-dom') return { Link: 'a', useLocation: () => history[historyIndex], useNavigate: () => navigateRoute, useSearchParams: () => [params, setSearchParams] };
      if (name === 'lucide-react') return new Proxy({}, { get: () => props => jsx.jsx('svg', props) });
      if (name.endsWith('.css')) return {};
      if (name === '@/lib/auth-storage') return { AUTH_SESSION_INVALIDATED_EVENT: 'synthetic-auth-invalidated', getAuthSessionEpoch: () => epoch };
      if (name === '@/lib/private-workspace-api' || name === './private-workspace-api') return load('lib/private-workspace-api.ts');
      if (name === '@/lib/private-bank') return load('lib/private-bank.ts');
      if (name === '@/lib/private-stripe-report') return load('lib/private-stripe-report.ts');
      if (name === './PrivateStripeDashboard') return load('pages/PrivateStripeDashboard.tsx');
      if (name === './PrivateBankDashboard') return load('pages/PrivateBankDashboard.tsx');
      if (name === './PrivateFundsOverview') return load('pages/PrivateFundsOverview.tsx');
      if (name === '@/lib/private-ads') return load('lib/private-ads.ts');
      if (name === '@/lib/private-boss-brief') return load('lib/private-boss-brief.ts');
      if (name === '@/lib/private-workspace-navigation') return load('lib/private-workspace-navigation.ts');
      if (name === './PrivateAdsDashboard') return load('pages/PrivateAdsDashboard.tsx');
      if (name === './PrivateMailContent') return load('pages/PrivateMailContent.tsx');
      if (name === './PrivateMailBrief') return load('pages/PrivateMailBrief.tsx');
      if (name === './PrivateBossBrief') return load('pages/PrivateBossBrief.tsx');
      if (name === '@/lib/use-dialog-draft') return load('lib/use-dialog-draft.ts');
      if (name === '@/lib/use-unsaved-changes') return load('lib/use-unsaved-changes.ts');
      if (name === './use-unsaved-changes') return load('lib/use-unsaved-changes.ts');
      if (name.startsWith('@/components/ui/')) return new Proxy({}, { get: (_, key) => key === 'Dialog' || key === 'Sheet' ? props => props.open ? props.children : null : props => jsx.jsx('div', props) });
      if (name === './api') return { client: { apiCall: { invoke: async request => {
        requests.push(request);
        const url = new URL(request.url, 'https://synthetic.example');
        if (url.pathname.endsWith('/bank/link/start')) return { data: bankStartHandler ? await bankStartHandler(request) : { session_id: 'synthetic-session', authorization_url: '', expires_at: null, mode: 'production' } };
        if (url.pathname.endsWith('/bank/link/complete')) return { data: bankCompleteHandler ? await bankCompleteHandler(request) : { state: 'pending', session_id: request.data.session_id, source_id: 'bofa_bank' } };
        if (url.pathname.endsWith('/access')) return { data: { allowed: true } };
        if (url.pathname.endsWith('/stripe/report')) {
          if (!stripeReportHandler) throw { response: { status: 503, data: { detail: '期间统计待接入' } } };
          return { data: await stripeReportHandler(request) };
        }
        if (url.pathname === '/api/v1/private-workspace') return { data: overviewHandler ? await overviewHandler(request) : { sources: [source, ...extraSources], items, balances: overviewBalances, last_sync: null } };
        if (url.pathname.endsWith('/brief')) return { data: briefHandler ? await briefHandler(request) : briefSnapshot(url.searchParams.get('period')) };
        if (url.pathname.endsWith('/brief/explain')) return { data: explainHandler ? await explainHandler(request) : briefSnapshot(request.data.period, { capabilities: { configured: false, code: 'not_configured' } }) };
        if (url.pathname.endsWith('/mail-capabilities')) return { data: mailCapabilitiesHandler ? await mailCapabilitiesHandler(request) : { smart_brief: { enabled: false, configured: false }, translation: { enabled: true, configured: true } } };
        if (url.pathname.endsWith('/mail-brief')) return { data: mailBriefHandler ? await mailBriefHandler(request) : { configured: false, item_id: decodeURIComponent(url.pathname.split('/').at(-2)), brief: { state: 'unavailable' }, code: 'not_configured' } };
        if (url.pathname.endsWith('/preferences')) {
          if (preferencesHandler) return { data: await preferencesHandler(request) };
          if (request.method === 'PATCH') Object.assign(preferences.gmail, request.data.gmail);
          return { data: structuredClone(preferences) };
        }
        if (url.pathname.endsWith('/sync')) return { data: syncHandler ? await syncHandler(request) : { source, counts: { created: 0, updated: 0 } } };
        if (url.pathname.endsWith('/mail-translations/batch')) return { data: translationPreviewHandler ? await translationPreviewHandler(request) : { configured: false, items: [], code: 'not_configured' } };
        if (url.pathname.endsWith('/mail-translation')) return { data: translationBodyHandler ? await translationBodyHandler(request) : { configured: false, item_id: decodeURIComponent(url.pathname.split('/').at(-2)), translation: { state: 'unavailable', title_zh: null, summary_zh: null, body_available: false, truncated: false }, code: 'not_configured' } };
        if (url.pathname.endsWith('/mail-feedback')) {
          const id = decodeURIComponent(url.pathname.split('/').at(-2));
          const item = items.find(value => value.id === id); item.mail_relevance.feedback = request.data.feedback;
          return { data: { item: structuredClone(item) } };
        }
        if (url.pathname.endsWith('/items')) {
          if (request.method === 'POST') {
            const item = { ...mail('new-personal'), ...request.data, source_id: 'manual', kind: 'task', status: 'manual', evidence: {}, mail_relevance: undefined };
            items.push(item); return { data: { item } };
          }
          const bucket = url.searchParams.get('mail_bucket');
          const sourceId = url.searchParams.get('source_id'), kind = url.searchParams.get('kind'), status = url.searchParams.get('action_status');
          const filtered = items.filter(item => (!sourceId || item.source_id === sourceId) && (!kind || item.kind === kind) && (!status || item.action_status === status) && (!bucket || item.mail_relevance?.bucket === bucket));
          const counts = { urgent: 0, today: 0, digest: 0, low: 0 }; items.forEach(item => { if (item.mail_relevance) counts[item.mail_relevance.bucket]++; });
          return { data: { items: structuredClone(filtered.slice(0, Number(url.searchParams.get('limit') || 100))), total: filtered.length, mail_counts: counts } };
        }
        if (/\/items\/[^/]+$/.test(url.pathname) && request.method === 'PATCH') {
          const item = items.find(value => value.id === decodeURIComponent(url.pathname.split('/').at(-1)));
          assert.ok(item, 'only existing synthetic personal records may be updated');
          Object.assign(item, request.data); return { data: { item: structuredClone(item) } };
        }
        throw new Error(`Unexpected synthetic request ${url.pathname}`);
      } } } };
      throw new Error(`Unexpected module ${name}`);
    };
    vm.runInContext(`(function(require,module,exports){${compiled}\n})`, context, { filename: path })(require, module, module.exports);
    modules.set(relative, module.exports); return module.exports;
  }
  const component = load('pages/PrivateWorkspace.tsx').default;
  let renderedComponents, renderedInputs = [];
  function expand(node, path = 'root') {
    if (node === null || node === undefined || typeof node === 'boolean') return [];
    if (Array.isArray(node)) return node.flatMap((child, index) => expand(child, `${path}/${child?.key ?? index}`));
    if (typeof node !== 'object') return [String(node)];
    if (typeof node.type === 'function') {
      renderedInputs.push(node);
      const id = `${path}/${node.type.name || 'component'}`;
      if (!componentHooks.has(id)) componentHooks.set(id, []);
      renderedComponents.add(id);
      const previousHooks = hooks, previousCursor = cursor;
      hooks = componentHooks.get(id); cursor = 0;
      const result = node.type(node.props);
      hooks = previousHooks; cursor = previousCursor;
      return expand(result, id);
    }
    return [{ ...node, children: expand(node.props?.children, `${path}/${String(node.type)}`) }];
  }
  function render() {
    hooks = componentHooks.get('root'); cursor = 0; renderedComponents = new Set(['root']); renderedInputs = [];
    tree = expand(component());
    for (const [id, ownedHooks] of componentHooks) if (!renderedComponents.has(id)) { ownedHooks.forEach(hook => hook?.cleanup?.()); componentHooks.delete(id); }
    const committed = effects.splice(0);
    // React performs passive effect destruction before creation, which matters
    // when the old page captures its position before the next page restores one.
    committed.forEach(effect => effect.cleanup()); committed.forEach(effect => effect.setup()); return tree;
  }
  const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
  function all(nodes = tree) { return nodes.flatMap(node => typeof node === 'object' ? [node, ...all(node.children || [])] : []); }
  async function flush() { for (let count = 0; count < 20; count++) { render(); await Promise.resolve(); } render(); }
  return {
    requests, window, preferences, params, flush, navigationCalls, scrollCalls,
    location: () => ({ ...history[historyIndex] }), history: () => history.map(entry => ({ ...entry })),
    back: async () => { const moved = navigateRoute(-1); await flush(); return moved; },
    forward: async () => { const moved = navigateRoute(1); await flush(); return moved; },
    remount: async () => {
      for (const ownedHooks of componentHooks.values()) ownedHooks.forEach(hook => hook?.cleanup?.());
      componentHooks.clear(); componentHooks.set('root', []); effects.splice(0); await flush();
    },
    changeSession: value => { epoch = value; for (const listener of listeners.get('synthetic-auth-invalidated') || []) listener(); },
    text: () => tree.map(text).join(''), textOf: text, nodes: () => all(),
    componentProps: name => renderedInputs.find(node => node.type.name === name)?.props,
    find: (type, label) => all().find(node => node.type === type && text(node) === label),
    button: label => all().find(node => node.type === 'button' && text(node).trim() === label),
    setOverviewHandler: handler => { overviewHandler = handler; },
    setStripeReportHandler: handler => { stripeReportHandler = handler; },
    setBankStartHandler: handler => { bankStartHandler = handler; },
    setBankCompleteHandler: handler => { bankCompleteHandler = handler; },
    setPreferencesHandler: handler => { preferencesHandler = handler; },
    setSyncHandler: handler => { syncHandler = handler; },
    setTranslationPreviewHandler: handler => { translationPreviewHandler = handler; },
    setTranslationBodyHandler: handler => { translationBodyHandler = handler; },
    setMailCapabilitiesHandler: handler => { mailCapabilitiesHandler = handler; },
    setMailBriefHandler: handler => { mailBriefHandler = handler; },
    setBriefHandler: handler => { briefHandler = handler; },
    setExplainHandler: handler => { explainHandler = handler; },
    advanceTime(milliseconds) { now += milliseconds; for (const callback of timers.values()) callback(); },
    invalidate() { epoch = 'synthetic-new-account'; for (const listener of listeners.get('synthetic-auth-invalidated') || []) listener(); },
    unmount() { for (const ownedHooks of componentHooks.values()) ownedHooks.forEach(hook => hook?.cleanup?.()); },
  };
}

const stripePeriodReport = (preset = 'month', marker = '本期经过核对的收款', extra = {}) => ({
  state: 'ready', snapshot_id: `synthetic-stripe-${preset}`, generated_at: '2026-10-12T08:00:00Z', account_label: 'Synthetic period account', mode: 'live',
  period: { preset, label: marker, start_date: preset === 'year' ? '2026-01-01' : '2026-10-01', end_date: '2026-10-12', timezone: 'UTC', comparison_label: '上期同等时段' },
  coverage: { complete: true, amounts_complete: true, classifications_complete: true, subscriptions_complete: true, funds_complete: true, reasons: [] },
  currencies: [{ currency: 'USD', gross_minor: 12345, subscription_minor: 12000, one_time_minor: 345, unclassified_minor: 0, refunds_minor: 0, net_receipts_minor: 12345, fees_minor: 100, count: 2, summary: [marker], comparison: { complete: true, gross_minor: 0, change_pct: null }, trend: [] }],
  records: [], subscriptions: [], attention: [], balances: [], ...extra,
});

test('Stripe report period switch discards a slower previous-period response and keeps view state without extra reads', async () => {
  const waiting = deferred(); const f = fixture([], 'stripe', [stripeSource()]);
  f.setStripeReportHandler(request => request.data.period === 'month' ? waiting.promise : stripePeriodReport(request.data.period, '季度经过核对的结果'));
  await f.flush(); assert.ok(f.text().includes('正在读取所选期间'));
  f.nodes().find(node => node.type === 'select' && node.props['aria-label'] === '收款统计期间').props.onChange({ target: { value: 'quarter' } }); await f.flush(); assert.ok(f.text().includes('季度经过核对的结果'));
  waiting.resolve(stripePeriodReport('month', '不得出现的旧月份结果')); await f.flush();
  assert.ok(!f.text().includes('不得出现的旧月份结果'));
  const calls = f.requests.filter(request => request.url.endsWith('/stripe/report')).length;
  f.button('订阅').props.onClick(); await f.flush(); f.button('资金').props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/stripe/report')).length, calls);
  assert.ok(f.text().includes('当前余额快照') || f.text().includes('余额')); f.unmount();
});

test('Stripe report in flight cannot repopulate another login session', async () => {
  const waiting = deferred(); const f = fixture([], 'stripe', [stripeSource()]);
  f.setStripeReportHandler(() => waiting.promise); await f.flush();
  f.invalidate(); waiting.resolve(stripePeriodReport('month', '原老板的私人收款')); await f.flush();
  assert.ok(!f.text().includes('原老板的私人收款')); assert.ok(!f.text().includes('USD 123.45')); f.unmount();
});

test('Stripe invalid custom range makes no upstream report call, and connection back retains report tab and period', async () => {
  const f = fixture([], 'stripe', [stripeSource()]); f.setStripeReportHandler(request => stripePeriodReport(request.data.period)); await f.flush();
  f.nodes().find(node => node.type === 'select' && node.props['aria-label'] === '收款统计期间').props.onChange({ target: { value: 'year' } }); await f.flush(); f.button('订阅').props.onClick(); await f.flush();
  f.button('管理接入').props.onClick(); await f.flush(); assert.equal(f.params.get('view'), 'connections');
  await f.back(); assert.equal(f.params.get('view'), 'stripe');
  assert.equal(f.nodes().find(node => node.type === 'select' && node.props['aria-label'] === '收款统计期间').props.value, 'year'); assert.equal(f.button('订阅').props['aria-selected'], true);
  f.nodes().find(node => node.type === 'select' && node.props['aria-label'] === '收款统计期间').props.onChange({ target: { value: 'custom' } }); await f.flush();
  const input = label => f.nodes().find(node => node.type === 'input' && node.props['aria-label'] === label);
  const count = f.requests.filter(request => request.url.endsWith('/stripe/report')).length;
  input('收款开始日期').props.onChange({ target: { value: '2026-12-31' } }); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/stripe/report')).length, count);
  assert.ok(f.text().includes('有效的开始')); f.unmount();
});

test('default Gmail groups collapse low priority and selecting a bucket asks the server', async () => {
  const f = fixture([mail('urgent', 'urgent'), mail('digest', 'digest'), mail('low', 'low')]);
  await f.flush();
  const low = f.nodes().find(node => node.type === 'details' && node.props.className === 'pw-mail-group pw-mail-low');
  assert.ok(low, f.text()); assert.equal(low.props.open, undefined);
  f.button('每日摘要1').props.onClick(); await f.flush();
  assert.ok(f.requests.at(-1).url.includes('mail_bucket=digest'));
  assert.ok(!f.text().includes('Synthetic urgent'));
  f.unmount();
});

test('message feedback defaults to one mail and sender feedback clearing requires explicit scope', async () => {
  const f = fixture(); await f.flush();
  f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-mail-row').props.onClick(); await f.flush();
  const checkbox = () => f.nodes().find(node => node.type === 'input' && node.props.type === 'checkbox');
  assert.equal(checkbox().props.checked, false);
  await f.button('需要关注').props.onClick(); await f.flush();
  assert.equal(f.requests.find(request => request.url.endsWith('mail-feedback')).data.apply_to_sender, false);
  await f.button('取消本封反馈').props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('mail-feedback')).at(-1).data.apply_to_sender, false);
  checkbox().props.onChange({ target: { checked: true } }); await f.flush();
  await f.button('不相关').props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('mail-feedback')).at(-1).data.apply_to_sender, true);
  checkbox().props.onChange({ target: { checked: true } }); await f.flush();
  await f.button('取消本封及发件人反馈').props.onClick(); await f.flush();
  const clear = f.requests.filter(request => request.url.endsWith('mail-feedback')).at(-1);
  assert.equal(clear.data.feedback, null); assert.equal(clear.data.apply_to_sender, true);
  f.unmount();
});

test('a later message without item feedback can explicitly reset its sender feedback without editing manual lists', async () => {
  const f = fixture(); f.preferences.gmail.watch_senders = ['manual@example.com']; f.preferences.gmail.muted_senders = ['muted.example.com'];
  await f.flush(); f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-mail-row').props.onClick(); await f.flush();
  assert.equal(f.button('取消本封反馈').props.disabled, true);
  f.nodes().find(node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({ target: { checked: true } }); await f.flush();
  assert.ok(f.text().includes('手动填写的关注与低优先名单保留'));
  const reset = f.button('取消本封及发件人反馈'); assert.equal(reset.props.disabled, false);
  reset.props.onClick(); await f.flush();
  const request = f.requests.find(value => value.url.endsWith('mail-feedback'));
  assert.equal(request.data.feedback, null); assert.equal(request.data.apply_to_sender, true);
  assert.equal(f.requests.filter(value => value.method === 'PATCH').length, 0);
  assert.deepEqual(f.preferences.gmail.watch_senders, ['manual@example.com']);
  assert.deepEqual(f.preferences.gmail.muted_senders, ['muted.example.com']);
  f.unmount();
});

test('filtered results above the display cap explain the limit without a no-op group button', async () => {
  const f = fixture(Array.from({ length: 103 }, (_, index) => mail(`digest-${index}`, 'digest')));
  await f.flush(); assert.ok(f.text().includes('全部已同步103'));
  f.button('每日摘要103').props.onClick(); await f.flush();
  assert.equal(f.button('查看该组邮件'), undefined);
  assert.ok(f.text().includes('当前显示前 100 封，已同步的该组共 103 封；更早邮件请在 Gmail 查看'));
  assert.equal(f.nodes().filter(node => node.type === 'button' && node.props.className === 'pw-mail-row').length, 100);
  f.unmount();
});

test('critical negative feedback visibly stays pending verification', async () => {
  const item = mail('critical', 'urgent'); item.mail_relevance.feedback = 'not_relevant';
  const f = fixture([item]); await f.flush();
  f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-mail-row').props.onClick(); await f.flush();
  assert.ok(f.text().includes('这封资金或安全提醒仍保留，等待核实'));
  assert.ok(f.text().includes('发件人身份待核实'));
  f.unmount();
});

test('preference drafts can cancel dismissal and saving omits the existing sync interval', async () => {
  const f = fixture(); await f.flush(); f.button('关注设置').props.onClick(); await f.flush();
  f.nodes().find(node => node.type === 'textarea' && node.props.placeholder.includes('客户名')).props.onChange({ target: { value: 'Synthetic project' } }); await f.flush();
  f.window.confirm = () => false; f.button('取消').props.onClick(); await f.flush();
  assert.ok(f.button('保存关注设置'));
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  const patch = f.requests.find(request => request.method === 'PATCH');
  assert.equal(Object.hasOwn(patch.data, 'sync_interval_seconds'), false);
  assert.equal(f.preferences.sync_interval_seconds, 2700);
  assert.deepEqual(Array.from(patch.data.gmail.watch_keywords), ['Synthetic project']);
  f.unmount();
});

test('failed settings load cannot save an empty replacement', async () => {
  const f = fixture(); f.setPreferencesHandler(() => { throw new Error('Synthetic unavailable'); });
  await f.flush(); f.button('关注设置').props.onClick(); await f.flush();
  assert.equal(f.button('保存关注设置'), undefined);
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  assert.equal(f.requests.filter(request => request.method === 'PATCH').length, 0);
  f.unmount();
});

test('logout clears private mail and drafts and discards a delayed preference response', async () => {
  const pending = deferred(); const f = fixture(); f.setPreferencesHandler(() => pending.promise);
  await f.flush(); f.button('关注设置').props.onClick(); await f.flush();
  f.invalidate(); await f.flush();
  pending.resolve({ sync_interval_seconds: 2700, gmail: { topics: [], watch_senders: ['old-owner@example.com'], watch_keywords: [], muted_senders: [] } }); await f.flush();
  assert.ok(f.text().includes('此空间仅对本人开放'));
  assert.ok(!f.text().includes('Synthetic message'));
  assert.ok(!f.text().includes('old-owner@example.com'));
  assert.equal(f.button('保存关注设置'), undefined);
  f.unmount();
});

test('today priorities exclude digest and low mail', async () => {
  const f = fixture([mail('focus', 'today'), mail('digest', 'digest'), mail('low', 'low')], 'today');
  f.setBriefHandler(() => briefSnapshot('today', { issues: [{ id: 'focus-issue', source_id: 'gmail', item_id: 'focus', title: '核对业务邮件', summary: 'Synthetic snippet', next_action: '核对来源', priority: 'high', observed_at: null }], sources: [bossSource('gmail')] })); await f.flush();
  assert.ok(f.text().includes('核对业务邮件'), f.text());
  assert.ok(!f.text().includes('Synthetic digest'));
  assert.ok(!f.text().includes('Synthetic low'));
  f.unmount();
});

const bossIssue = { id: 'payment-check', source_id: 'stripe', item_id: 'private-payment', title: '核对最近失败收款记录', summary: '最后记录状态，待核查', next_action: '打开 Stripe 核对原因', priority: 'high', observed_at: null };
test('boss brief is local GET only and unavailable AI cannot invoke a provider', async () => {
  const f = fixture([], 'today'); f.setBriefHandler(() => briefSnapshot('today', { issues: [bossIssue], sources: [bossSource()] })); await f.flush();
  assert.ok(f.text().includes(bossIssue.title));
  assert.equal(f.requests.filter(request => request.url.includes('/brief?')).length, 1);
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0);
  assert.equal(f.button('中文解读'), undefined); assert.ok(f.text().includes('中文解读尚待接入'));
  assert.equal(f.requests.filter(request => request.url.endsWith('/brief/explain')).length, 0); f.unmount();
});
test('boss brief period change discards a late previous-period snapshot', async () => {
  const f = fixture([], 'today'); const pending = deferred();
  f.setBriefHandler(request => request.url.includes('last7days') ? briefSnapshot('last7days', { issues: [{ ...bossIssue, title: '近7天已同步事件' }], sources: [bossSource()] }) : pending.promise);
  await f.flush(); f.button('近7天').props.onClick(); await f.flush();
  assert.ok(f.text().includes('近7天已同步事件'));
  pending.resolve(briefSnapshot('today', { issues: [{ ...bossIssue, title: '旧期间私密内容' }], sources: [bossSource()] })); await f.flush();
  assert.ok(!f.text().includes('旧期间私密内容')); assert.ok(f.text().includes('近7天已同步事件')); f.unmount();
});
test('boss brief rereads source freshness locally while an open page never automatically generates AI', async () => {
  const f = fixture([], 'today'); let expired = false;
  f.setBriefHandler(() => briefSnapshot('today', { issues: [bossIssue], sources: [{ ...bossSource(), data_state: expired ? 'stale' : 'partial', summary: expired ? '来源需更新' : '已同步局部事件' }] }));
  await f.flush(); assert.ok(f.text().includes(bossIssue.title)); expired = true; f.advanceTime(25 * 3600000); await f.flush();
  assert.ok(!f.text().includes(bossIssue.title)); assert.ok(f.text().includes('核实 Stripe 同步记录')); assert.ok(f.text().includes('数据待核实')); assert.ok(f.text().includes('来源需更新'));
  assert.equal(f.requests.filter(request => request.url.includes('/brief?')).length, 2);
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});
test('boss brief task action prefills the personal editor and writes only after save', async () => {
  const f = fixture([], 'today'); f.setBriefHandler(() => briefSnapshot('today', { issues: [bossIssue] })); await f.flush();
  f.button('加入个人事项').props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.method === 'POST').length, 0);
  const title = f.nodes().find(node => node.type === 'input' && node.props.maxLength === 240);
  assert.equal(title.props.value, bossIssue.title);
  assert.equal(f.nodes().find(node => node.type === 'input' && node.props.type === 'datetime-local').props.value, '');
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  const writes = f.requests.filter(request => request.method === 'POST');
  assert.equal(writes.length, 1); assert.equal(writes[0].url, '/api/v1/private-workspace/items');
  assert.equal(writes[0].data.source_id, 'manual'); assert.equal(writes[0].data.kind, 'task');
  assert.equal(writes[0].data.due_at, null); assert.ok(writes[0].data.summary.includes(bossIssue.next_action)); f.unmount();
});
test('boss brief source outside the old capped overview opens its source rather than guessing a detail', async () => {
  const f = fixture([], 'today'); f.setBriefHandler(() => briefSnapshot('today', { issues: [bossIssue] })); await f.flush();
  f.button('查看来源').props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'stripe'); assert.ok(!f.text().includes('事项详情')); f.unmount();
});
test('explicit boss AI double-click has one request and never replaces system facts or writes a task', async () => {
  const f = fixture([], 'today'); const pending = deferred();
  const snapshot = briefSnapshot('today', { issues: [bossIssue], sources: [bossSource()], capabilities: { configured: true } });
  f.setBriefHandler(() => snapshot); f.setExplainHandler(() => pending.promise); await f.flush();
  const action = f.button('中文解读').props.onClick; action(); action(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/brief/explain')).length, 1);
  assert.equal(f.requests.at(-1).data.snapshot_id, snapshot.snapshot_id);
  pending.resolve({ ...snapshot, ai: { state: 'ready', summary: '人工核对后再决定', source_refs: ['stripe'], issue_notes: [] } }); await f.flush();
  assert.ok(f.text().includes('人工核对后再决定')); assert.ok(f.text().includes(bossIssue.title));
  assert.equal(f.requests.filter(request => request.url.endsWith('/items') && request.method === 'POST').length, 0); f.unmount();
});
test('late boss snapshot and AI result are erased when owner session changes', async () => {
  for (const stage of ['read', 'ai']) {
    const f = fixture([], 'today'); const pending = deferred();
    const snapshot = briefSnapshot('today', { issues: [bossIssue], sources: [bossSource()], capabilities: { configured: true } });
    f.setBriefHandler(() => stage === 'read' ? pending.promise : snapshot);
    f.setExplainHandler(() => pending.promise); await f.flush();
    if (stage === 'ai') { f.button('中文解读').props.onClick(); await f.flush(); }
    f.invalidate(); pending.resolve({ ...snapshot, ai: { state: 'ready', summary: '旧老板的秘密解读', source_refs: ['stripe'], issue_notes: [] } }); await f.flush();
    assert.ok(f.text().includes('此空间仅对本人开放')); assert.ok(!f.text().includes(bossIssue.title)); assert.ok(!f.text().includes('旧老板的秘密解读')); f.unmount();
  }
});

test('expired authorization has a visible manual retry route and does not launch OAuth', async () => {
  const f = fixture(); f.params.set('connection', 'expired'); await f.flush();
  assert.ok(f.text().includes('这次授权链接已失效'));
  f.button('打开工作接入').props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'connections');
  assert.ok(!f.requests.some(request => request.url.endsWith('/connect')));
  f.unmount();
});

test('a source sync remains visibly busy while waiting and does not allow duplicate dispatch', async () => {
  const pending = deferred(); const f = fixture([], 'connections'); f.setSyncHandler(() => pending.promise);
  await f.flush(); f.button('同步').props.onClick(); await f.flush();
  const busy = f.button('正在同步…'); assert.ok(busy); assert.equal(busy.props.disabled, true);
  busy.props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/sync')).length, 1);
  assert.equal(f.requests.find(request => request.url.endsWith('/sync')).options.timeout, 65_000);
  pending.resolve({ counts: { created: 1, updated: 0 } }); await f.flush();
  assert.ok(f.text().includes('同步完成：新增 1 条，更新 0 条'));
  assert.ok(f.button('同步'));
  f.unmount();
});

test('only connectable Ads explains the broad Google grant before its read-only adapter connects', async () => {
  const ads = { id: 'google_ads', status: 'disconnected', capabilities: ['read_campaign_metrics'], missing_configuration: [], last_sync: null, error: null };
  const f = fixture([], 'connections', [ads]); await f.flush();
  const note = f.nodes().find(node => node.props.id === 'pw-google-ads-consent-note');
  assert.ok(note); assert.ok(f.textOf(note).includes('查看、修改、创建和删除广告账号及数据'));
  assert.ok(f.textOf(note).includes('当前工作空间仅查询广告表现'));
  assert.equal(f.button('连接来源').props['aria-describedby'], 'pw-google-ads-consent-note');
  const gmail = f.nodes().find(node => node.type === 'section' && node.props.className === 'pw-connection' && f.textOf(node).startsWith('Gmail'));
  assert.ok(gmail); assert.ok(!f.textOf(gmail).includes('修改、创建和删除'));
  assert.ok(!f.requests.some(request => request.url.endsWith('/connect')));
  f.unmount();
  const connected = fixture([], 'connections', [{ ...ads, status: 'connected' }]); await connected.flush();
  assert.ok(!connected.text().includes('Google 授权包含'));
  connected.unmount();
});

test('Ads labels the verified advertiser and explains missing health data without claiming mailbox identity', async () => {
  const ads = { id: 'google_ads', status: 'connected', capabilities: ['read_campaign_metrics'], missing_configuration: [], last_sync: null, error: null, metadata: { account_label: 'Synthetic Ads Account', sync_window: 'last_30_days' } };
  const f = fixture([], 'google_ads', [ads]); await f.flush();
  assert.ok(f.text().includes('广告账户：Synthetic Ads Account'));
  assert.ok(f.text().includes('尚无检查记录')); assert.ok(f.text().includes('数据待确认')); assert.ok(!f.text().includes('全部正常'));
  assert.ok(f.text().includes('待完成检查'));
  assert.ok(!f.text().includes('Google邮箱'));
  f.params.set('connection', 'expired'); f.params.set('source', 'google_ads'); await f.flush();
  assert.ok(f.text().includes('重新连接 Google Ads'));
  assert.ok(!f.text().includes('重新连接 Gmail'));
  f.unmount();
});

test('Ads connection and source view identify the bound advertiser without repeating a fallback ID', async () => {
  const ads = { id: 'google_ads', status: 'connected', capabilities: ['read_campaign_metrics'], missing_configuration: [], last_sync: null, error: null, metadata: { account_label: 'Synthetic advertiser', ads_customer_id: '7539806760' } };
  for (const view of ['connections', 'google_ads']) {
    const f = fixture([], view, [ads]); await f.flush();
    assert.ok(f.text().includes('广告账户：Synthetic advertiser · 753-980-6760'));
    f.unmount();
  }
  for (const account_label of ['7539806760', '753-980-6760', '']) {
    const f = fixture([], 'google_ads', [{ ...ads, metadata: { ...ads.metadata, account_label } }]); await f.flush();
    const label = f.nodes().find(node => node.type === 'span' && node.props.className === 'pw-account-label');
    assert.equal(f.textOf(label), '广告账户：753-980-6760');
    f.unmount();
  }
});

test('Ads never creates an advertiser ID from missing, malformed, or numeric metadata', async () => {
  for (const ads_customer_id of [undefined, 'short', '753-980-6760', '7539806760-extra', 7539806760]) {
    const ads = { id: 'google_ads', status: 'connected', capabilities: [], missing_configuration: [], last_sync: null, error: null, metadata: { account_label: 'Synthetic advertiser', ads_customer_id } };
    const f = fixture([], 'google_ads', [ads]); await f.flush();
    const label = f.nodes().find(node => node.type === 'span' && node.props.className === 'pw-account-label');
    assert.equal(f.textOf(label), '广告账户：Synthetic advertiser');
    f.unmount();
  }
});

test('Ads opens real problems first, includes attention in top three, and separates delivery from local work status', async () => {
  const fixtures = ['problem', 'attention', 'healthy', 'paused', 'unknown'].map((bucket, index) => adsFixture(bucket, index));
  const f = fixture(fixtures.map(value => value.item), 'google_ads', [fixtures[0].source]); await f.flush();
  assert.ok(f.text().includes('优先处理2 项')); assert.equal(f.nodes().filter(node => node.type === 'article').length, 2);
  assert.equal(f.button('异常停投1').props['aria-pressed'], true);
  assert.equal(f.nodes().filter(node => node.props.className === 'pw-ads-row').length, 1);
  assert.ok(!f.text().includes('Google Ads · 待处理'));
  f.button('正常投放1').props.onClick(); await f.flush(); assert.equal(f.nodes().filter(node => node.props.className === 'pw-ads-row').length, 1);
  const search = f.nodes().find(node => node.type === 'input' && node.props['aria-label'] === '搜索已同步广告系列');
  search.props.onChange({ target: { value: '合成广告系列 3' } }); await f.flush();
  assert.equal(f.nodes().filter(node => node.props.className === 'pw-ads-row').length, 1); assert.ok(f.text().includes('合成广告系列 3'));
  f.unmount();
});
test('without stoppage Ads gives attention the first place and never fabricates a problem group', async () => {
  const { item, source } = adsFixture('attention'); const f = fixture([item], 'google_ads', [source]); await f.flush();
  assert.equal(f.button('需关注1').props['aria-pressed'], true); assert.equal(f.button('异常停投0'), undefined);
  assert.equal(f.nodes().filter(node => node.type === 'article').length, 1); f.unmount();
});
test('Ads stale checks are pending observation, excluded from Today, and cannot suggest everything is normal', async () => {
  const { item, source } = adsFixture('problem', 1, { observed_at: new Date(Date.now() - 25 * 3600000).toISOString() });
  const f = fixture([item], 'google_ads', [source]); await f.flush(); assert.ok(f.text().includes('待完成检查')); assert.ok(f.text().includes('检查数据已过期'));
  assert.equal(f.nodes().filter(node => node.type === 'article').length, 0); f.unmount();
  const today = fixture([item], 'today', [source]); await today.flush(); assert.ok(!today.text().includes(item.title)); today.unmount();
});
test('Ads details have Chinese metric hierarchy and currency but no work status mutations', async () => {
  const { item, source } = adsFixture('healthy'); item.evidence.ads_health.tracking.state = 'unconfigured';
  const f = fixture([item], 'google_ads', [source]); await f.flush();
  f.nodes().find(node => node.props.className === 'pw-ads-row').props.onClick(); await f.flush();
  assert.ok(f.text().includes('昨日2026-10-10')); assert.ok(f.text().includes('近7日2026-10-04 至 2026-10-10'));
  assert.ok(f.text().includes('USD 5.00')); assert.ok(f.text().includes('USD 35.00')); assert.ok(f.text().includes('未配置'));
  assert.ok(f.text().includes('不以零转化判断效果差')); assert.ok(!f.text().includes('ads_health'));
  assert.equal(f.button('标记已处理'), undefined); assert.equal(f.button('稍后处理'), undefined);
  const link = f.nodes().find(node => node.type === 'a' && node.props.href === 'https://ads.google.com/aw/overview'); assert.ok(link);
  f.unmount();
});
test('an open Ads screen and detail downgrade on the local freshness clock without another provider sync', async () => {
  const { item, source } = adsFixture('healthy'); const f = fixture([item], 'google_ads', [source]); await f.flush();
  f.nodes().find(node => node.props.className === 'pw-ads-row').props.onClick(); await f.flush();
  assert.ok(!f.text().includes('检查数据已过期'));
  const before = f.requests.length; f.advanceTime(25 * 3600000); await f.flush();
  assert.ok(f.text().includes('检查数据已过期')); assert.equal(f.button('正常投放1'), undefined);
  assert.equal(f.requests.length, before); f.unmount();
});
test('Ads detail shows the actual platform configuration reason and actual versus target CPA', async () => {
  const { item, source } = adsFixture('problem'); const f = fixture([item], 'google_ads', [source]); await f.flush();
  f.nodes().find(node => node.props.className === 'pw-ads-row').props.onClick(); await f.flush();
  assert.ok(f.text().includes('预算配置错误')); assert.ok(f.text().includes('近7日实际 CPAUSD 3.33')); assert.ok(f.text().includes('当前目标 CPAUSD 10.00'));
  assert.ok(!f.text().includes('BUDGET_MISCONFIGURED')); f.unmount();
});

const translated = (id, extra = {}) => ({ state: 'ready', title_zh: `中文 ${id} · Stripe`, summary_zh: `中文摘要 ${id}`, body_available: false, truncated: false, ...extra });
test('Gmail automatically translates only the first ten and each manual next batch stays bounded', async () => {
  const f = fixture(Array.from({ length: 149 }, (_, index) => mail(`translate-${index}`)));
  f.setTranslationPreviewHandler(request => ({ configured: true, items: request.data.item_ids.map(id => ({ item_id: id, translation: translated(id) })) }));
  await f.flush(); await f.flush();
  let calls = f.requests.filter(request => request.url.endsWith('/mail-translations/batch'));
  assert.equal(calls.length, 1); assert.equal(calls[0].data.item_ids.length, 10); assert.ok(f.text().includes('中文 translate-0 · Stripe')); assert.ok(f.text().includes('中文摘要 translate-0'));
  f.button('翻译更多摘要').props.onClick(); await f.flush();
  calls = f.requests.filter(request => request.url.endsWith('/mail-translations/batch'));
  assert.equal(calls.length, 2); assert.equal(calls[1].data.item_ids.length, 10); assert.ok(calls[1].data.item_ids.every(id => !calls[0].data.item_ids.includes(id)));
  f.button('每日摘要0').props.onClick(); await f.flush(); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-translations/batch')).length, 2); f.unmount();
});
test('unconfigured translation keeps original mail and stops retries or next-batch actions', async () => {
  const f = fixture(Array.from({ length: 15 }, (_, index) => mail(`unconfigured-${index}`))); await f.flush(); await f.flush();
  assert.ok(f.text().includes('中文翻译尚未开通')); assert.ok(f.text().includes('Synthetic unconfigured-0')); assert.equal(f.button('翻译更多摘要'), undefined);
  assert.equal(f.requests.filter(request => request.url.endsWith('/mail-translations/batch')).length, 1);
  f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush(); assert.equal(f.button('翻译正文').props.disabled, true); f.unmount();
});
test('body translation keeps summary distinct, retains the original while waiting and switches Chinese or original body', async () => {
  const item = mail('body'); item.mail_translation = translated('body');
  const f = fixture([item]); const pending = deferred(); f.setTranslationBodyHandler(() => pending.promise); await f.flush();
  f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush();
  assert.ok(f.text().includes('邮件摘要')); assert.ok(!f.text().includes('邮件正文')); assert.ok(f.text().includes('当前显示邮件摘要，正文需单独读取与翻译'));
  const action = f.button('翻译正文').props.onClick; action(); action(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/mail-translation')).length, 1); assert.ok(f.text().includes('正在读取并翻译正文'));
  f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes('Original') === false); assert.ok(f.text().includes('Synthetic snippet'));
  pending.resolve({ configured: true, item_id: item.id, translation: translated('body', { body_original: 'Original full body <script>literal only</script> USD 263.94', body_zh: '中文完整正文 · USD 263.94', body_available: true, truncated: true }) }); await f.flush();
  assert.ok(f.text().includes('邮件正文仅展示已读取的部分')); assert.ok(f.text().includes('Original full body <script>literal only</script>'));
  assert.ok(!f.nodes().some(node => node.props.dangerouslySetInnerHTML));
  f.button('中文').props.onClick(); await f.flush(); assert.ok(f.text().includes('中文完整正文 · USD 263.94'));
  f.setBriefHandler(() => briefSnapshot('today', { issues: [{ id: 'translated-issue', source_id: 'gmail', title: '中文 body · Stripe', summary: '', next_action: '核对原文', priority: 'high', observed_at: null }], sources: [bossSource('gmail')] }));
  f.button('经营简报').props.onClick(); await f.flush(); assert.ok(!f.text().includes('Original full body')); assert.ok(!f.text().includes('中文完整正文')); assert.ok(f.text().includes('中文 body · Stripe')); f.unmount();
});
test('cached Chinese previews do not trigger another automatic translation and original title remains available', async () => {
  const item = mail('cached'); item.mail_translation = translated('cached'); const f = fixture([item]); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/mail-translations/batch')).length, 0);
  f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush(); f.button('原文').props.onClick(); await f.flush();
  assert.ok(f.text().includes('Synthetic cached')); assert.ok(f.text().includes('Synthetic snippet')); f.unmount();
});
test('a delayed translation reply after logout cannot repopulate private mail or body', async () => {
  const f = fixture(); const pending = deferred(); f.setTranslationPreviewHandler(() => pending.promise); await f.flush();
  f.invalidate(); await f.flush(); pending.resolve({ configured: true, items: [{ item_id: 'message', translation: translated('secret') }] }); await f.flush();
  assert.ok(f.text().includes('此空间仅对本人开放')); assert.ok(!f.text().includes('中文 secret')); f.unmount();
  const item = mail('body-logout'); item.mail_translation = translated('body-logout'); const body = fixture([item]); const later = deferred(); body.setTranslationBodyHandler(() => later.promise); await body.flush();
  body.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await body.flush(); body.button('翻译正文').props.onClick(); await body.flush(); body.invalidate(); await body.flush();
  later.resolve({ configured: true, item_id: item.id, translation: translated('body-logout', { body_available: true, body_original: 'Private original', body_zh: '私人正文' }) }); await body.flush();
  assert.ok(!body.text().includes('私人正文')); assert.ok(!body.text().includes('Private original')); body.unmount();
});
test('quota exhaustion stops further list translation and failures never expose upstream details', async () => {
  const f = fixture(Array.from({ length: 15 }, (_, index) => mail(`quota-${index}`)));
  f.setTranslationPreviewHandler(() => ({ configured: true, items: [], code: 'limit_reached' })); await f.flush();
  assert.ok(f.text().includes('本月翻译额度已用完')); assert.equal(f.button('翻译更多摘要'), undefined); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-translations/batch')).length, 1); f.unmount();
  const failed = fixture(); failed.setTranslationPreviewHandler(() => { throw new Error('RAW PROVIDER SECRET'); }); await failed.flush();
  assert.ok(failed.text().includes('可先查看原文')); assert.ok(!failed.text().includes('RAW PROVIDER SECRET')); failed.unmount();
});
test('preview replies cannot display cached body before an explicit body request', async () => {
  const f = fixture(); f.setTranslationPreviewHandler(request => ({ configured: true, items: request.data.item_ids.map(id => ({ item_id: id, translation: translated(id, { body_available: true, body_original: 'Unexpected private body', body_zh: '不应提前出现正文' }) })) }));
  await f.flush(); f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush();
  assert.ok(!f.text().includes('Unexpected private body')); assert.ok(!f.text().includes('不应提前出现正文')); assert.ok(!f.text().includes('邮件正文')); assert.ok(f.button('翻译正文')); f.unmount();
});
test('monthly quota still allows the user to open a previously cached full-body translation', async () => {
  const uncached = mail('quota-trigger'); const cached = mail('cached-body'); cached.mail_translation = translated('cached-body');
  const f = fixture([uncached, cached]); f.setTranslationPreviewHandler(() => ({ configured: true, items: [], code: 'limit_reached' }));
  f.setTranslationBodyHandler(() => ({ configured: true, item_id: cached.id, translation: translated('cached-body', { body_available: true, body_original: 'Cached original', body_zh: '已缓存的中文正文' }) }));
  await f.flush(); f.nodes().find(node => node.props.className === 'pw-mail-row' && f.textOf(node).includes('中文 cached-body')).props.onClick(); await f.flush();
  assert.equal(f.button('翻译正文').props.disabled, false); f.button('翻译正文').props.onClick(); await f.flush();
  assert.ok(f.text().includes('已缓存的中文正文')); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-translation')).length, 1); f.unmount();
});
test('a successful preview-only body response clearly explains that the message has no readable body', async () => {
  const item = mail('no-body'); item.mail_translation = translated('no-body'); const f = fixture([item]);
  f.setTranslationBodyHandler(() => ({ configured: true, item_id: item.id, translation: translated('no-body') })); await f.flush();
  f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush(); f.button('翻译正文').props.onClick(); await f.flush();
  assert.ok(f.text().includes('未找到可翻译正文，可在 Gmail 查看完整邮件')); assert.ok(!f.text().includes('邮件正文')); f.unmount();
});
test('a preview response arriving after an explicit body response cannot replace the full body', async () => {
  const item = mail('race'); const f = fixture([item]); const pending = deferred();
  f.setTranslationPreviewHandler(() => pending.promise); f.setTranslationBodyHandler(() => ({ configured: true, item_id: item.id, translation: translated('race', { body_available: true, body_original: 'Race original', body_zh: '正文保持可见' }) }));
  await f.flush(); f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush(); f.button('翻译正文').props.onClick(); await f.flush();
  assert.ok(f.text().includes('正文保持可见')); pending.resolve({ configured: true, items: [{ item_id: item.id, translation: translated('race') }] }); await f.flush();
  assert.ok(f.text().includes('正文保持可见')); f.unmount();
});

const briefCapabilities = (configured = true) => ({ smart_brief: { enabled: true, configured, ...(!configured ? { code: 'consent_required' } : {}) }, translation: { enabled: true, configured: true } });
const organized = (overrides = {}) => ({
  state: 'ready', title_zh: '客户需要确认广告方案', summary_zh: '客户询问下周广告安排，等待你的确认。', key_points: ['客户希望先确认安排'], relevance: '与你负责的广告项目有关', next_action: '核对方案后回复客户', needs_action: true,
  deadline: { at: null, text: '下周', confirmed: false, evidence: 'Please confirm next week.' }, importance: 'today', source_scope: 'body', original_body: 'Synthetic full mail. Please confirm next week.', source_evidence: ['Please confirm next week.'], truncated: false, ...overrides,
});
const openMail = async f => { f.nodes().find(node => node.props.className === 'pw-mail-row').props.onClick(); await f.flush(); };

test('smart brief mode reads capabilities first and makes no eager AI or parallel translation requests', async () => {
  const f = fixture(Array.from({ length: 149 }, (_, index) => mail(`smart-${index}`))); const pending = deferred(); f.setMailCapabilitiesHandler(() => pending.promise);
  await f.flush(); assert.equal(f.requests.filter(request => request.url.includes('/mail-translation') || request.url.endsWith('/mail-brief')).length, 0);
  await openMail(f); assert.equal(f.button('整理这封邮件').props.disabled, true);
  pending.resolve(briefCapabilities()); await f.flush(); assert.equal(f.button('整理这封邮件').props.disabled, false);
  assert.equal(f.requests.filter(request => request.url.includes('/mail-translation') || request.url.endsWith('/mail-brief')).length, 0);
  assert.equal(f.button('翻译更多摘要'), undefined); assert.equal(f.button('翻译正文'), undefined); f.unmount();
});
test('single explicit organize keeps original available while busy, blocks duplicate dispatch, and renders a concise Chinese hierarchy', async () => {
  const f = fixture(); const pending = deferred(); f.setMailCapabilitiesHandler(() => briefCapabilities()); f.setMailBriefHandler(() => pending.promise);
  await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  const busy = f.button('正在整理…'); assert.equal(busy.props.disabled, true); busy.props.onClick(); await f.flush();
  assert.ok(f.text().includes('Synthetic snippet')); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief')).length, 1);
  pending.resolve({ configured: true, item_id: 'message', brief: organized() }); await f.flush();
  for (const text of ['发生了什么', '我该做什么', '与你有关', '客户询问下周广告安排', '核对方案后回复客户', '下周', '待确认', 'AI 阅读整理']) assert.ok(f.text().includes(text), text);
  f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes('Synthetic full mail. Please confirm next week.')); assert.ok(f.text().includes('Synthetic message'));
  f.button('重点').props.onClick(); await f.flush(); assert.ok(!f.text().includes('Synthetic full mail. Please confirm next week.'));
  assert.ok(f.requests.every(request => request.url.startsWith('/api/v1/private-workspace'))); f.unmount();
});
test('unconfigured smart service keeps Gmail connected, disables organize, and does not fall back to billed translation', async () => {
  const f = fixture(); f.setMailCapabilitiesHandler(() => briefCapabilities(false)); await f.flush(); await openMail(f);
  assert.ok(f.text().includes('智能整理尚待确认接入')); assert.ok(f.text().includes('Synthetic snippet')); assert.equal(f.button('整理这封邮件').props.disabled, true);
  f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief') || request.url.includes('/mail-translation')).length, 0); f.unmount();
});
test('unavailable capabilities never initiate AI or legacy translation and do not expose transport detail', async () => {
  const f = fixture(); f.setMailCapabilitiesHandler(() => { throw new Error('RAW CAPABILITY SECRET'); }); await f.flush(); await openMail(f);
  assert.ok(f.text().includes('暂时无法检查智能整理服务')); assert.ok(!f.text().includes('RAW CAPABILITY SECRET')); assert.equal(f.button('整理这封邮件').props.disabled, true);
  assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief') || request.url.includes('/mail-translation')).length, 0); f.unmount();
});
test('summary-only AI response cannot be labeled as full body and missing deadlines remain unconfirmed', async () => {
  const f = fixture(); f.setMailCapabilitiesHandler(() => briefCapabilities()); f.setMailBriefHandler(() => ({ configured: true, item_id: 'message', brief: organized({ source_scope: 'preview', original_body: null, deadline: null, truncated: true }) }));
  await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('发生了什么 · 依据摘要')); assert.ok(f.text().includes('仅依据标题与摘要')); assert.ok(f.text().includes('待确认')); assert.ok(f.text().includes('未找到可读取正文'));
  const headline = f.nodes().find(node => node.props.className === 'pw-mail-brief-headline');
  assert.ok(f.textOf(headline).includes('内容待确认')); assert.ok(!f.nodes().some(node => node.props.className === 'pw-mail-brief-deadline'));
  f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes('原始摘要')); assert.ok(!f.text().includes('邮件原文')); f.unmount();
});
test('evidence-limited complete body brief remains visibly uncertain without changing the rule group', async () => {
  const item = mail('limited', 'urgent'); const f = fixture([item]); f.setMailCapabilitiesHandler(() => briefCapabilities());
  f.setMailBriefHandler(() => ({ configured: true, item_id: item.id, brief: organized({ evidence_limited: true, truncated: false, deadline: null, needs_action: null, next_action: null }) }));
  await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('部分依据不足')); assert.ok(f.text().includes('暂未提取到明确行动')); assert.ok(f.text().includes('待确认'));
  const headline = f.nodes().find(node => node.props.className === 'pw-mail-brief-headline');
  assert.ok(f.textOf(headline).includes('内容待确认')); assert.ok(!f.nodes().some(node => node.props.className === 'pw-mail-brief-deadline'));
  assert.ok(f.text().includes('立即关注')); assert.equal(item.mail_relevance.bucket, 'urgent'); f.unmount();
});
test('cached brief does not trigger AI and list previews cannot retain a detail-only original body', async () => {
  const item = mail('cached-smart'); item.mail_brief = organized({ original_body: undefined }); const f = fixture([item]); f.setMailCapabilitiesHandler(() => briefCapabilities());
  f.setMailBriefHandler(() => ({ configured: true, item_id: item.id, brief: organized({ original_body: 'Detail-only private original' }) }));
  await f.flush(); assert.ok(f.text().includes('客户需要确认广告方案')); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief')).length, 0);
  await openMail(f); f.button('查看原文正文').props.onClick(); await f.flush(); f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes('Detail-only private original'));
  await openMail(f); assert.ok(!f.text().includes('Detail-only private original')); assert.ok(f.text().includes('原始摘要')); assert.ok(f.button('查看原文正文')); f.unmount();
});
test('successful brief keeps quoted source and deadline evidence only in the selected detail', async () => {
  const f = fixture(); f.setMailCapabilitiesHandler(() => briefCapabilities()); f.setMailBriefHandler(() => ({ configured: true, item_id: 'message', brief: organized({ source_evidence: ['Detail-only source quotation'], deadline: { at: null, text: '下周', confirmed: false, evidence: 'Detail-only deadline quotation' } }) }));
  await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('Detail-only source quotation')); assert.ok(f.text().includes('Detail-only deadline quotation'));
  await openMail(f); assert.ok(!f.text().includes('Detail-only source quotation')); assert.ok(!f.text().includes('Detail-only deadline quotation')); assert.ok(f.text().includes('下周')); assert.ok(f.text().includes('客户询问下周广告安排')); f.unmount();
});
test('logout discards both delayed smart content and delayed capabilities without repopulating private mail', async () => {
  const f = fixture(); const pending = deferred(); f.setMailCapabilitiesHandler(() => briefCapabilities()); f.setMailBriefHandler(() => pending.promise); await f.flush(); await openMail(f);
  f.button('整理这封邮件').props.onClick(); await f.flush(); f.invalidate(); await f.flush(); pending.resolve({ configured: true, item_id: 'message', brief: organized({ summary_zh: 'Old owner private summary', original_body: 'Old owner private body' }) }); await f.flush();
  assert.ok(f.text().includes('此空间仅对本人开放')); assert.ok(!f.text().includes('Old owner private')); f.unmount();
  const later = fixture(); const capabilities = deferred(); later.setMailCapabilitiesHandler(() => capabilities.promise); await later.flush(); later.invalidate(); await later.flush(); capabilities.resolve(briefCapabilities()); await later.flush();
  assert.equal(later.button('整理这封邮件'), undefined); assert.equal(later.requests.filter(request => request.url.endsWith('/mail-brief')).length, 0); later.unmount();
});
test('a mismatched brief response and provider failure never replace the selected original or leak details', async () => {
  const f = fixture(); f.setMailCapabilitiesHandler(() => briefCapabilities()); f.setMailBriefHandler(() => ({ configured: true, item_id: 'different', brief: organized({ summary_zh: 'Wrong message summary' }) })); await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('Synthetic snippet')); assert.ok(!f.text().includes('Wrong message summary'));
  f.setMailBriefHandler(() => { throw new Error('RAW PROVIDER SECRET'); }); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('暂时无法整理这封邮件')); assert.ok(!f.text().includes('RAW PROVIDER SECRET')); assert.ok(f.text().includes('Synthetic snippet')); f.unmount();
});
test('AI-generated HTML and bank claims remain escaped reading suggestions without due date, financial, or account mutations', async () => {
  const item = mail('bank-mail', 'urgent'); item.mail_relevance.category = 'finance'; const f = fixture([item]); f.setMailCapabilitiesHandler(() => briefCapabilities());
  f.setMailBriefHandler(() => ({ configured: true, item_id: item.id, brief: organized({ title_zh: '<script>bank</script>', summary_zh: '邮件提及付款，请核对银行实际流水', next_action: '<a href="javascript:alert(1)">核对银行</a>', importance: 'read', deadline: { at: null, text: 'Friday', confirmed: false } }) }));
  await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('<script>bank</script>')); assert.equal(f.nodes().filter(node => node.type === 'script').length, 0); assert.equal(f.nodes().filter(node => node.type === 'a' && node.props.href?.startsWith('javascript:')).length, 0);
  assert.ok(f.text().includes('立即关注')); assert.equal(item.due_at, null); assert.equal(item.amount_minor, null); assert.equal(item.mail_relevance.bucket, 'urgent');
  assert.equal(f.requests.filter(request => ['PATCH', 'DELETE'].includes(request.method)).length, 0); assert.ok(f.requests.every(request => request.url.startsWith('/api/v1/private-workspace'))); f.unmount();
});
test('monthly budget exhaustion stays a concise detail notice and preserves cached Chinese and original access without retrying', async () => {
  const item = mail('budget-cached'); item.mail_brief = organized({ original_body: undefined, source_evidence: undefined });
  const f = fixture([item]); f.setMailCapabilitiesHandler(() => ({ ...briefCapabilities(), budget: { configured: true, limit_usd: '5.00', reserved_usd: '5.00', remaining_usd: '0.00', month: '2026-10' } }));
  f.setMailBriefHandler(() => ({ configured: true, item_id: item.id, brief: { state: 'unavailable' }, code: 'budget_exhausted' }));
  await f.flush(); assert.ok(!f.text().includes('US$5.00')); await openMail(f); assert.ok(!f.text().includes('US$5.00'));
  f.button('查看原文正文').props.onClick(); await f.flush(); assert.ok(f.text().includes('本月 US$5.00 智能整理可用额度不足，已整理邮件和原文仍可查看')); assert.ok(!f.text().includes('已达到本月')); assert.ok(f.text().includes('客户询问下周广告安排'));
  f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes('Synthetic snippet')); assert.ok(f.text().includes('Synthetic budget-cached')); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief')).length, 1);
  await f.flush(); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief')).length, 1); assert.equal(f.requests.filter(request => request.url.includes('/mail-translation')).length, 0);
  assert.equal(item.due_at, null); assert.equal(item.amount_minor, null); assert.equal(f.requests.filter(request => ['PATCH', 'DELETE'].includes(request.method)).length, 0); f.unmount();
});
test('month change preserves the original and requires a new explicit organize click instead of automatically retrying', async () => {
  const f = fixture(); f.setMailCapabilitiesHandler(() => briefCapabilities()); f.setMailBriefHandler(() => ({ configured: true, item_id: 'message', brief: { state: 'unavailable' }, code: 'budget_month_changed' }));
  await f.flush(); await openMail(f); f.button('整理这封邮件').props.onClick(); await f.flush();
  assert.ok(f.text().includes('月份已更新，请重新整理这封邮件')); assert.ok(f.text().includes('Synthetic snippet')); assert.ok(f.text().includes('Synthetic message'));
  f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes('Synthetic snippet'));
  await f.flush(); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief')).length, 1); assert.equal(f.requests.filter(request => request.url.includes('/mail-translation')).length, 0);
  f.button('整理这封邮件').props.onClick(); await f.flush(); assert.equal(f.requests.filter(request => request.url.endsWith('/mail-brief')).length, 2); f.unmount();
});


const stripeSource = (overrides = {}) => {
  const observed_at = new Date().toISOString();
  return { id: 'stripe', name: 'Stripe', status: 'connected', capabilities: [], missing_configuration: [], error: null, last_sync: observed_at,
    metadata: { account_label: 'Synthetic account', stripe_account_id: 'acct_synthetic', mode: 'live',
      stripe_snapshot: { id: 'synthetic-stripe-snapshot', observed_at, account_id: 'acct_synthetic', mode: 'live' },
      resources: { charges: { fetched: 1, partial: true }, refunds: { fetched: 0, partial: false }, disputes: { fetched: 0, partial: false }, payouts: { fetched: 0, partial: false } } }, ...overrides };
};
const stripePayment = (source, extra = {}) => ({ ...mail('stripe-payment'), source_id: 'stripe', kind: 'payment', title: 'Synthetic payment', summary: 'ch_synthetic', status: 'succeeded', amount_minor: 10000, currency: 'USD', mail_relevance: undefined,
  evidence: { stripe_account_id: 'acct_synthetic', stripe_mode: 'live', stripe_snapshot_id: 'synthetic-stripe-snapshot', stripe_observed_at: source.metadata.stripe_snapshot.observed_at,
    payment_state: 'authorized', amount_authorized_minor: 10000, amount_captured_minor: 0, amount_refunded_minor: 0, captured: false, paid: true }, ...extra });

test('mobile funds entry opens the cached overview without provider report, sync, or a nonexistent funds item query', async () => {
  const source = stripeSource();
  const f = fixture([], 'today', [source], [{ source_id: 'stripe', currency: 'USD', available_minor: 25000, pending_minor: 7500 }]);
  await f.flush();
  const mobileNav = f.nodes().find(node => node.type === 'nav' && node.props['aria-label'] === '手机版工作空间');
  mobileNav.children.find(node => node.type === 'button' && f.textOf(node) === '资金').props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'funds');
  assert.ok(f.text().includes('Stripe 当前余额')); assert.ok(f.text().replace(/\s/g, ' ').includes('USD 250.00'));
  assert.equal(f.requests.filter(request => request.url.endsWith('/stripe/report') || request.url.endsWith('/sync')).length, 0);
  assert.equal(f.requests.filter(request => request.url.includes('source_id=funds')).length, 0);
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});

test('funds overview keeps each current Stripe currency separate and unconfigured bank data unconfirmed', async () => {
  const source = stripeSource();
  const bank = { id: 'bofa_bank', status: 'not_configured', capabilities: [], missing_configuration: ['bank'], last_sync: null, error: null };
  const f = fixture([], 'funds', [source, bank], [
    { source_id: 'stripe', currency: 'USD', available_minor: 25000, pending_minor: 7500 },
    { source_id: 'stripe', currency: 'CNY', available_minor: 62000, pending_minor: 900 },
  ]); await f.flush();
  const stripeCard = f.nodes().find(node => node.type === 'section' && node.props['aria-label'] === 'Stripe 缓存余额');
  const bankCard = f.nodes().find(node => node.type === 'section' && node.props['aria-label'] === '银行缓存余额');
  const currencyRows = f.nodes().filter(node => node.props.className === 'pw-funds-currency');
  assert.equal(currencyRows.length, 2);
  assert.ok(f.textOf(currencyRows[0]).replace(/\s/g, ' ').includes('USD 250.00')); assert.ok(!f.textOf(currencyRows[0]).includes('CNY'));
  assert.ok(f.textOf(currencyRows[1]).replace(/\s/g, ' ').includes('CNY 620.00')); assert.ok(!f.textOf(currencyRows[1]).includes('USD'));
  assert.ok(f.textOf(stripeCard).includes('已读取快照')); assert.ok(!f.textOf(stripeCard).includes('合计'));
  assert.ok(f.textOf(bankCard).includes('尚待配置')); assert.ok(f.textOf(bankCard).includes('余额与流水待获取')); assert.ok(!f.textOf(bankCard).includes('0.00'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});

test('funds to Stripe or bank and internal back preserve the overview route, position, and mobile active destination', async () => {
  for (const [target, label] of [['stripe', '查看收款、订阅与流水'], ['bofa_bank', '查看银行账户与流水']]) {
    const f = fixture([], 'funds', [stripeSource()]); await f.flush();
    const key = f.location().key; const initialReads = f.requests.filter(request => request.url === '/api/v1/private-workspace').length;
    f.window.scrollY = 386;
    f.button(label).props.onClick(); await f.flush();
    assert.equal(f.params.get('view'), target); assert.equal(f.location().state.privateWorkspace.parentKey, key);
    const mobileNav = f.nodes().find(node => node.type === 'nav' && node.props['aria-label'] === '手机版工作空间');
    assert.equal(mobileNav.children.find(node => node.type === 'button' && f.textOf(node) === '资金').props['aria-current'], 'page');
    privateHeaderBack(f).props.onClick(); await f.flush();
    assert.equal(f.params.get('view'), 'funds'); assert.equal(f.location().key, key); assert.equal(f.window.scrollY, 386);
    assert.equal(f.requests.filter(request => request.url === '/api/v1/private-workspace').length, initialReads);
    assert.ok(f.history().every(entry => entry.pathname === '/private-workspace'));
    assert.equal(f.requests.filter(request => request.url.endsWith('/sync')).length, 0); f.unmount();
  }
});

test('stale and account-mismatched funds snapshots never appear as fresh zero balances', async () => {
  const source = stripeSource(); const observed_at = new Date(Date.now() - 25 * 3600000).toISOString();
  const stale = { ...source, last_sync: observed_at, metadata: { ...source.metadata, stripe_snapshot: { ...source.metadata.stripe_snapshot, observed_at } } };
  const balances = [{ source_id: 'stripe', currency: 'USD', available_minor: 1600, pending_minor: 340 }];
  const f = fixture([], 'funds', [stale], balances); await f.flush();
  assert.ok(f.text().includes('数据需更新')); assert.ok(f.text().replace(/\s/g, ' ').includes('USD 16.00')); assert.ok(!f.text().includes('已读取快照')); assert.ok(!f.text().includes('0.00'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
  const mismatch = { ...source, metadata: { ...source.metadata, stripe_account_id: 'acct_anotherowner' } };
  const missing = fixture([], 'funds', [mismatch], balances); await missing.flush();
  assert.ok(missing.text().includes('余额待确认')); assert.ok(missing.text().includes('余额待同步'));
  assert.ok(!missing.text().replace(/\s/g, ' ').includes('USD 16.00')); assert.ok(!missing.text().includes('0.00')); assert.ok(!missing.text().includes('已读取快照'));
  assert.equal(missing.requests.filter(request => request.method !== 'GET').length, 0); missing.unmount();
});

test('mail add-to-personal opens an attributed draft, waits for Save, and returns to the same source detail', async () => {
  const original = mail('draft-source-mail'); const f = fixture([original]); f.setMailCapabilitiesHandler(() => briefCapabilities(false));
  await f.flush(); await openMail(f);
  const detailKey = f.location().key;
  f.button('加入个人事项').props.onClick(); await f.flush();
  assert.equal(f.params.get('panel'), 'editor'); assert.equal(f.location().state.privateWorkspace.parentKey, detailKey);
  assert.ok(titleInput(f).props.value.includes(original.title));
  assert.ok(f.nodes().find(node => node.type === 'textarea' && node.props.maxLength === 5000).props.value.includes('来源：'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0);
  assert.equal(await f.back(), true); assert.equal(f.location().key, detailKey); assert.equal(f.params.get('item'), original.id); assert.equal(f.params.get('panel'), null);
  assert.ok(privateDetailBack(f)); assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0);
  f.button('加入个人事项').props.onClick(); await f.flush();
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  const writes = f.requests.filter(request => request.method !== 'GET');
  assert.equal(writes.length, 1); assert.equal(writes[0].url, '/api/v1/private-workspace/items'); assert.equal(writes[0].data.source_id, 'manual'); assert.equal(writes[0].data.due_at, null);
  assert.equal(original.action_status, 'open'); assert.equal(f.requests.filter(request => request.method === 'PATCH').length, 0);
  assert.equal(await f.back(), true); assert.equal(f.location().key, detailKey); assert.equal(f.params.get('item'), original.id); assert.ok(privateDetailBack(f));
  f.unmount();
});

test('Stripe connection can visibly retry a failed read with the bound credential and no reconnect request', async () => {
  const source = stripeSource({ action_availability: { can_connect: false, can_sync: true } });
  const f = fixture([], 'connections', [source]);
  const descendants = node => [node, ...(node.children || []).filter(value => typeof value === 'object').flatMap(descendants)];
  const stripeButtons = () => {
    const card = f.nodes().find(node => node.type === 'section' && node.props.className === 'pw-connection' && f.textOf(node).includes('Stripe'));
    return descendants(card).filter(node => node.type === 'button');
  };
  let fail = true;
  f.setSyncHandler(request => {
    assert.ok(request.url.endsWith('/sources/stripe/sync'));
    if (fail) {
      source.status = 'error'; source.error = '来源读取暂不可用';
      throw { response: { status: 502, data: { detail: source.error } } };
    }
    source.status = 'connected'; source.error = null;
    return { source, counts: { created: 1, updated: 0 } };
  });
  await f.flush();
  stripeButtons().find(node => f.textOf(node) === '同步').props.onClick(); await f.flush();
  assert.ok(f.text().includes('来源读取暂不可用'));
  assert.equal(stripeButtons().some(node => f.textOf(node).includes('重新连接')), false);
  const retry = stripeButtons().find(node => f.textOf(node) === '同步'); assert.ok(retry); assert.equal(retry.props.disabled, false);
  fail = false; retry.props.onClick(); await f.flush();
  assert.ok(f.text().includes('同步完成：新增 1 条，更新 0 条。'));
  assert.equal(f.requests.filter(request => request.url.endsWith('/sources/stripe/sync')).length, 2);
  assert.equal(f.requests.filter(request => request.url.endsWith('/sources/stripe/connect')).length, 0);
  f.unmount();
});

test('Stripe denied server actions hide both retry and unavailable reconnect for a source error', async () => {
  const source = stripeSource({ status: 'error', error: '来源账户绑定需要检查', action_availability: { can_connect: false, can_sync: false } });
  const f = fixture([], 'connections', [source]); await f.flush();
  const card = f.nodes().find(node => node.type === 'section' && node.props.className === 'pw-connection' && f.textOf(node).includes('Stripe'));
  assert.ok(f.textOf(card).includes('停止同步')); assert.ok(!f.textOf(card).includes('重新连接 / 授权'));
  assert.equal(f.requests.filter(request => request.url.endsWith('/sources/stripe/sync') || request.url.endsWith('/sources/stripe/connect')).length, 0);
  f.unmount();
});

test('Stripe balances are snapshots with account mode and coverage folded away', async () => {
  const source = stripeSource(); const f = fixture([stripePayment(source)], 'stripe', [source], [{ source_id: 'stripe', currency: 'USD', available_minor: 25000, pending_minor: 7500 }]);
  await f.flush();
  assert.ok(f.text().replace(/\s/g, ' ').includes('Synthetic account · acct_synthetic')); assert.ok(f.text().replace(/\s/g, ' ').includes('正式模式')); assert.ok(f.text().replace(/\s/g, ' ').includes('同步余额'));
  assert.ok(f.text().replace(/\s/g, ' ').includes('USD 250.00')); assert.ok(!f.text().replace(/\s/g, ' ').includes('实时余额'));
  const coverage = f.nodes().find(node => node.type === 'details' && node.props.className === 'pw-stripe-coverage');
  assert.ok(coverage); assert.equal(coverage.props.open, undefined); assert.ok(f.textOf(coverage).includes('还有较早记录未包含'));
  f.unmount();
});

test('Stripe balances without account bound snapshot are hidden rather than showing zero or legacy amounts', async () => {
  const source = stripeSource({ metadata: { mode: 'live' } }); const f = fixture([], 'stripe', [source], [{ source_id: 'stripe', currency: 'USD', available_minor: 25000, pending_minor: 0 }]);
  await f.flush(); assert.ok(f.text().replace(/\s/g, ' ').includes('待重新同步')); assert.ok(!f.text().replace(/\s/g, ' ').includes('USD 250.00')); assert.ok(!f.text().replace(/\s/g, ' ').includes('USD 0.00')); f.unmount();
});

test('Stripe authorization does not become successful income and detail separates capture and refunds', async () => {
  const source = stripeSource(); const f = fixture([stripePayment(source)], 'stripe', [source]); await f.flush();
  assert.ok(f.text().replace(/\s/g, ' ').includes('已授权 · 待捕获')); assert.ok(f.text().replace(/\s/g, ' ').includes('授权金额')); assert.ok(!f.text().replace(/\s/g, ' ').includes('收款成功'));
  f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-stripe-row ').props.onClick(); await f.flush();
  assert.ok(f.text().replace(/\s/g, ' ').includes('授权金额尚未捕获，不代表实际收款。'));
  assert.ok(f.text().replace(/\s/g, ' ').includes('请求金额USD 100.00')); assert.ok(f.text().replace(/\s/g, ' ').includes('已收款金额USD 0.00')); assert.ok(f.text().replace(/\s/g, ' ').includes('已退款金额USD 0.00'));
  const evidence = f.nodes().find(node => node.type === 'details' && node.props.className === 'pw-stripe-evidence'); assert.ok(evidence); assert.equal(evidence.props.open, undefined);
  assert.equal(f.requests.filter(request => (request.method === 'POST' || request.method === 'PATCH') && !request.url.endsWith('/stripe/report')).length, 0); f.unmount();
});

test('Stripe partial refunds display captured and refunded amounts rather than treating requested amount as collected', async () => {
  const source = stripeSource(); const item = stripePayment(source);
  item.evidence = { ...item.evidence, payment_state: 'partially_refunded', amount_captured_minor: 8000, amount_refunded_minor: 2500, captured: true };
  const f = fixture([item], 'stripe', [source]); await f.flush();
  const row = f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-stripe-row ');
  assert.ok(f.textOf(row).replace(/\s/g, ' ').includes('部分退款')); assert.ok(f.textOf(row).replace(/\s/g, ' ').includes('USD 80.00')); assert.ok(f.textOf(row).replace(/\s/g, ' ').includes('已退款 USD 25.00')); assert.ok(!f.textOf(row).replace(/\s/g, ' ').includes('USD 100.00')); f.unmount();
});

test('Stripe negative payout list and detail preserve source sign and require bank verification', async () => {
  const source = stripeSource();
  const item = stripePayment(source, { id: 'negative-payout', kind: 'payout', title: 'Synthetic negative payout',
    amount_minor: -1100, status: 'paid', due_at: '2026-10-12T00:00:00Z' });
  item.evidence = { stripe_account_id: 'acct_synthetic', stripe_mode: 'live',
    stripe_snapshot_id: 'synthetic-stripe-snapshot', stripe_observed_at: source.metadata.stripe_snapshot.observed_at,
    funds_movement: 'bank_to_stripe_balance', accounting_effect: 'none' };
  const f = fixture([item], 'stripe', [source]); await f.flush();
  f.button('提现').props.onClick(); await f.flush();
  const row = f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-stripe-row ');
  const rowText = f.textOf(row).replace(/\s/g, ' ');
  assert.ok(rowText.includes('反向划转金额') && rowText.includes('-USD 11.00'));
  assert.ok(rowText.includes('Stripe 标记完成 · 银行待核对'));
  assert.ok(!rowText.includes('收入') && !rowText.includes('银行已到账'));
  row.props.onClick(); await f.flush();
  const detail = f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-stripe-detail');
  const detailText = f.textOf(detail).replace(/\s/g, ' ');
  assert.ok(detailText.includes('反向划转金额-USD 11.00'));
  assert.ok(detailText.includes('保留 Stripe 原始金额符号，银行实际资金变化需核对流水'));
  const meta = f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-detail-meta');
  assert.ok(f.textOf(meta).includes('来源预计日期：')); assert.ok(!f.textOf(meta).includes('预计到账'));
  assert.equal(f.requests.filter(request => (request.method === 'POST' || request.method === 'PATCH') && !request.url.endsWith('/stripe/report')).length, 0);
  f.unmount();
});

test('Stripe uncaptured source refund marks show original fields with no received cash label', async () => {
  const source = stripeSource(); const item = stripePayment(source);
  item.evidence = { ...item.evidence, payment_state: 'uncaptured_refunded', amount_refunded_minor: 10000, refunded: true };
  const f = fixture([item], 'stripe', [source]); await f.flush();
  const row = f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-stripe-row ');
  const rowText = f.textOf(row).replace(/\s/g, ' ');
  assert.ok(rowText.includes('未捕获 · 来源标记退款')); assert.ok(rowText.includes('来源请求金额'));
  assert.ok(!rowText.includes('已收款') && !rowText.includes('已退款 USD'));
  row.props.onClick(); await f.flush();
  const detail = f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-stripe-detail');
  const detailText = f.textOf(detail).replace(/\s/g, ' ');
  assert.ok(detailText.includes('来源请求金额USD 100.00'));
  assert.ok(detailText.includes('来源捕获字段USD 0.00')); assert.ok(detailText.includes('来源退款字段USD 100.00'));
  assert.ok(!detailText.includes('已收款金额') && !detailText.includes('已退款金额'));
  assert.ok(detailText.includes('此笔付款未捕获；来源退款字段保留原值'));
  assert.equal(f.requests.filter(request => (request.method === 'POST' || request.method === 'PATCH') && !request.url.endsWith('/stripe/report')).length, 0);
  f.unmount();
});

test('Stripe snapshots become stale without a new sync and test mode remains explicit on every record', async () => {
  const source = stripeSource(); source.metadata.mode = 'test'; source.metadata.stripe_snapshot.mode = 'test';
  const item = stripePayment(source); item.evidence.stripe_mode = 'test';
  const f = fixture([item], 'stripe', [source], [{ source_id: 'stripe', currency: 'USD', available_minor: 1000, pending_minor: 0 }]); await f.flush();
  assert.ok(f.text().replace(/\s/g, ' ').includes('测试模式')); assert.ok(f.text().replace(/\s/g, ' ').includes('已授权 · 待捕获测试'));
  f.advanceTime(24 * 60 * 60 * 1000 + 60_000); await f.flush();
  assert.ok(f.text().replace(/\s/g, ' ').includes('上次同步 · 需更新')); assert.ok(f.text().replace(/\s/g, ' ').includes('上次同步记录 · 需更新')); f.unmount();
});


const bankCallbackSession = '12345678-abcd-1234-abcd-123456789abc';
const bankUiSource = () => ({ id: 'bofa_bank', name: 'Bank of America', status: 'connecting', capabilities: [], missing_configuration: [], error: null, last_sync: null, metadata: { bank_environment: 'production' } });

test('bank return parameters alone never complete authorization, sync, or fetch AI automatically', async () => {
  const f = fixture([], 'bofa_bank', [bankUiSource()]); f.params.set('bank_session', bankCallbackSession); await f.flush();
  assert.ok(f.button('确认银行连接')); assert.equal(f.requests.filter(request => request.method === 'POST').length, 0); f.unmount();
});

test('bank explicit Hosted Link rejects non-Plaid redirects and does not use Gmail authorization', async () => {
  const f = fixture([], 'bofa_bank', [bankUiSource()]); const redirects = []; f.window.location.assign = value => redirects.push(value);
  f.setBankStartHandler(() => ({ session_id: bankCallbackSession, authorization_url: 'https://secure.plaid.com.evil.example/hl/example', expires_at: new Date(Date.now() + 60_000).toISOString(), mode: 'production' })); await f.flush();
  f.button('继续授权').props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/bank/link/start')).length, 1); assert.equal(redirects.length, 0); assert.equal(f.requests.filter(request => request.url.includes('/sources/bofa_bank/connect')).length, 0); f.unmount();
});

test('bank confirmation double-click dispatches once and pending response cannot claim connected or sync', async () => {
  const f = fixture([], 'bofa_bank', [bankUiSource()]); const response = deferred(); f.params.set('bank_session', bankCallbackSession); f.setBankCompleteHandler(() => response.promise); await f.flush();
  const confirm = f.button('确认银行连接'); confirm.props.onClick(); confirm.props.onClick(); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/bank/link/complete')).length, 1);
  response.resolve({ state: 'pending', session_id: bankCallbackSession, source_id: 'bofa_bank' }); await f.flush(); assert.ok(f.text().includes('银行授权尚未完成')); assert.equal(f.requests.filter(request => request.url.endsWith('/sources/bofa_bank/sync')).length, 0); f.unmount();
});

test('bank completion validates the same session and exact connected state before beginning provider sync', async () => {
  for (const result of [{ state: 'unknown', session_id: bankCallbackSession, source_id: 'bofa_bank' }, { state: 'connected', session_id: 'other-session', source_id: 'bofa_bank' }, { state: 'connected', session_id: bankCallbackSession, source_id: 'stripe' }]) {
    const f = fixture([], 'bofa_bank', [bankUiSource()]); f.params.set('bank_session', bankCallbackSession); f.setBankCompleteHandler(() => result); await f.flush(); f.button('确认银行连接').props.onClick(); await f.flush();
    assert.equal(f.requests.filter(request => request.url.endsWith('/sources/bofa_bank/sync')).length, 0); assert.ok(!f.text().includes('银行账户与交易记录已同步。')); f.unmount();
  }
});

test('a bank completion arriving after owner logout is discarded without syncing another session', async () => {
  const f = fixture([], 'bofa_bank', [bankUiSource()]); const response = deferred(); f.params.set('bank_session', bankCallbackSession); f.setBankCompleteHandler(() => response.promise); await f.flush(); f.button('确认银行连接').props.onClick(); await f.flush();
  f.invalidate(); await f.flush(); response.resolve({ state: 'connected', session_id: bankCallbackSession, source_id: 'bofa_bank' }); await f.flush(); assert.equal(f.requests.filter(request => request.url.endsWith('/sources/bofa_bank/sync')).length, 0); assert.ok(!f.text().includes('银行账户与交易记录已同步。')); f.unmount();
});

test('a bank completion from an earlier callback session is discarded when a different callback is opened', async () => {
  const f = fixture([], 'bofa_bank', [bankUiSource()]); const response = deferred(); f.params.set('bank_session', bankCallbackSession); f.setBankCompleteHandler(() => response.promise); await f.flush(); f.button('确认银行连接').props.onClick(); await f.flush();
  f.params.set('bank_session', '87654321-abcd-1234-abcd-123456789abc'); await f.flush(); response.resolve({ state: 'connected', session_id: bankCallbackSession, source_id: 'bofa_bank' }); await f.flush();
  assert.equal(f.requests.filter(request => request.url.endsWith('/sources/bofa_bank/sync')).length, 0); assert.ok(!f.text().includes('银行账户与交易记录已同步。')); f.unmount();
});

test('a confirmed bank connection visibly reports the first sync failure and never claims data synchronized', async () => {
  const source = bankUiSource(); const f = fixture([], 'bofa_bank', [source]); f.params.set('bank_session', bankCallbackSession);
  f.setBankCompleteHandler(() => { source.status = 'connected'; return { state: 'connected', session_id: bankCallbackSession, source_id: 'bofa_bank' }; });
  const sync = deferred(); f.setSyncHandler(() => sync.promise); await f.flush(); f.button('确认银行连接').props.onClick(); await f.flush();
  sync.resolve(Promise.reject({ response: { status: 503, data: { detail: 'Synthetic bank sync unavailable' } } })); await f.flush();
  assert.ok(f.text().includes('Synthetic bank sync unavailable')); assert.ok(!f.text().includes('银行账户与交易记录已同步。')); f.unmount();
});

test('bank start double-click creates only one Hosted Link and a late logout result cannot navigate', async () => {
  const f = fixture([], 'bofa_bank', [bankUiSource()]); const response = deferred(); const redirects = []; f.window.location.assign = value => redirects.push(value); f.setBankStartHandler(() => response.promise); await f.flush();
  const start = f.button('继续授权'); start.props.onClick(); start.props.onClick(); await f.flush(); assert.equal(f.requests.filter(request => request.url.endsWith('/bank/link/start')).length, 1);
  f.invalidate(); await f.flush(); response.resolve({ session_id: bankCallbackSession, authorization_url: 'https://secure.plaid.com/hl/synthetic-session', expires_at: new Date(Date.now() + 60_000).toISOString(), mode: 'production' }); await f.flush(); assert.equal(redirects.length, 0); f.unmount();
});


test('successful bank confirmation followed by a failed local refresh exposes the read error and keeps retry read-only', async () => {
  const source = bankUiSource(); const f = fixture([], 'bofa_bank', [source]); f.params.set('bank_session', bankCallbackSession);
  f.setBankCompleteHandler(() => { source.status = 'connected'; return { state: 'connected', session_id: bankCallbackSession, source_id: 'bofa_bank' }; });
  f.setSyncHandler(() => ({ source, counts: { created: 0, updated: 0 } })); await f.flush();
  f.setOverviewHandler(() => { throw { response: { status: 503, data: { detail: 'Synthetic overview unavailable' } } }; });
  f.button('确认银行连接').props.onClick(); await f.flush(); assert.ok(f.text().includes('暂时无法读取工作空间')); assert.ok(f.text().includes('Synthetic overview unavailable'));
  assert.ok(!f.text().includes('银行已连接，正在读取账户和交易记录')); assert.equal(f.params.get('bank_session'), null);
  f.setOverviewHandler(null); f.button('重新读取').props.onClick(); await f.flush(); assert.ok(!f.text().includes('Synthetic overview unavailable'));
  assert.equal(f.requests.filter(request => request.url.endsWith('/bank/link/complete')).length, 1); assert.equal(f.requests.filter(request => request.url.endsWith('/sources/bofa_bank/sync')).length, 1); f.unmount();
});

test('owner permission loss during the local bank refresh erases the successful connection notice and private UI', async () => {
  const source = bankUiSource(); const f = fixture([], 'bofa_bank', [source]); f.params.set('bank_session', bankCallbackSession);
  f.setBankCompleteHandler(() => ({ state: 'connected', session_id: bankCallbackSession, source_id: 'bofa_bank' })); f.setSyncHandler(() => ({ source, counts: { created: 0, updated: 0 } })); await f.flush();
  f.setOverviewHandler(() => { throw { response: { status: 403 } }; }); f.button('确认银行连接').props.onClick(); await f.flush();
  assert.ok(f.text().includes('此空间仅对本人开放')); assert.ok(!f.text().includes('银行账户与交易记录已同步')); assert.ok(!f.text().includes('银行缓存余额')); assert.equal(f.requests.filter(request => request.url.endsWith('/sources/bofa_bank/sync')).length, 1); f.unmount();
});

const privateHeaderBack = f => f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-private-back');
const privateDetailBack = f => f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-private-back pw-detail-back');
const titleInput = f => f.nodes().find(node => node.type === 'input' && node.props.maxLength === 240);

test('private navigation returns detail to Gmail and Gmail to its brief without entering CRM', async () => {
  const f = fixture([mail('navigation-message')], 'today'); f.setMailCapabilitiesHandler(() => briefCapabilities(false)); await f.flush();
  const briefKey = f.location().key;
  f.button('重要邮件').props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'gmail');
  assert.equal(f.location().state.privateWorkspace.parentKey, briefKey);
  f.window.scrollY = 524;
  await openMail(f);
  assert.equal(f.params.get('item'), 'navigation-message');
  assert.ok(privateDetailBack(f));
  privateDetailBack(f).props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'gmail'); assert.equal(f.params.get('item'), null);
  assert.equal(privateDetailBack(f), undefined); assert.equal(f.window.scrollY, 524);
  privateHeaderBack(f).props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'today'); assert.equal(f.location().key, briefKey);
  assert.equal(privateHeaderBack(f), undefined);
  assert.ok(f.history().every(entry => entry.pathname === '/private-workspace'));
  assert.equal(f.requests.filter(request => request.method === 'PATCH' || request.method === 'POST').length, 0);
  f.unmount();
});

test('Stripe record type and Gmail bucket survive a trip to connections and browser back', async () => {
  const source = stripeSource(); const payment = stripePayment(source);
  const refund = { ...stripePayment(source), id: 'navigation-refund', kind: 'refund', title: 'Synthetic refund' };
  const stripe = fixture([payment, refund], 'stripe', [source]); await stripe.flush();
  stripe.button('退款').props.onClick(); await stripe.flush(); stripe.window.scrollY = 742;
  stripe.button('管理接入').props.onClick(); await stripe.flush();
  assert.equal(stripe.params.get('view'), 'connections'); assert.equal(await stripe.back(), true);
  assert.equal(stripe.params.get('view'), 'stripe'); assert.equal(stripe.button('退款').props['aria-pressed'], true);
  assert.equal(stripe.button('支付').props['aria-pressed'], false); assert.equal(stripe.window.scrollY, 742);
  assert.ok(stripe.text().includes('Synthetic refund')); assert.ok(!stripe.text().includes('Synthetic authorization'));
  assert.ok(stripe.requests.filter(request => request.url.includes('/items?')).at(-1).url.includes('kind=refund')); stripe.unmount();

  const gmail = fixture([mail('navigation-digest', 'digest'), mail('navigation-urgent', 'urgent')]); await gmail.flush();
  gmail.button('每日摘要1').props.onClick(); await gmail.flush(); gmail.window.scrollY = 318;
  gmail.button('工作接入').props.onClick(); await gmail.flush();
  assert.equal(await gmail.back(), true); assert.equal(gmail.params.get('view'), 'gmail');
  assert.equal(gmail.button('每日摘要1').props['aria-pressed'], true); assert.equal(gmail.window.scrollY, 318);
  assert.ok(gmail.text().includes('Synthetic navigation-digest')); assert.ok(!gmail.text().includes('Synthetic navigation-urgent'));
  gmail.unmount();
});

test('the private brief has no return arrow to CRM and More gives the explicit customer-system exit', async () => {
  const f = fixture([], 'today'); await f.flush();
  const header = f.nodes().find(node => node.type === 'header' && node.props.className === 'pw-mobile-header');
  assert.ok(f.textOf(header).includes('私人空间')); assert.ok(f.textOf(header).includes('仅本人'));
  assert.equal(privateHeaderBack(f), undefined); assert.equal(privateDetailBack(f), undefined);
  f.button('更多').props.onClick(); await f.flush();
  const exit = f.nodes().find(node => node.type === 'a' && node.props.className === 'pw-mobile-crm-exit');
  assert.ok(exit); assert.equal(exit.props.to, '/apps');
  assert.ok(f.textOf(exit).includes('返回客户系统')); assert.ok(f.textOf(exit).includes('离开私人空间'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});

test('direct or reloaded source entries fall back to the private brief instead of an untrusted previous route', async () => {
  for (const state of [null, { privateWorkspace: { session: 'synthetic-owner', parentKey: 'missing-route', parentView: 'gmail' } }, { privateWorkspace: { session: 'previous-owner', parentKey: 'route-0', parentView: 'stripe' } }]) {
    const f = fixture([], 'stripe', [stripeSource()], [], { state }); await f.flush();
    assert.ok(privateHeaderBack(f)); privateHeaderBack(f).props.onClick(); await f.flush();
    assert.equal(f.params.get('view'), 'today'); assert.equal(f.navigationCalls.some(call => call.type === 'POP'), false);
    assert.equal(f.history().length, 1); f.unmount();
  }
  const f = fixture([mail('reload-message')], 'today'); await f.flush(); f.button('重要邮件').props.onClick(); await f.flush(); await openMail(f);
  assert.ok(privateDetailBack(f)); await f.remount();
  assert.equal(f.params.get('item'), null); assert.equal(privateDetailBack(f), undefined);
  privateHeaderBack(f).props.onClick(); await f.flush();
  assert.equal(f.params.get('view'), 'today'); assert.equal(f.navigationCalls.some(call => call.type === 'POP'), false); f.unmount();
});

test('native back closes only the current detail layer and forward reopens its trusted in-session record', async () => {
  const f = fixture([mail('pop-message')], 'today'); await f.flush(); f.button('重要邮件').props.onClick(); await f.flush(); await openMail(f);
  const initialWrites = f.requests.filter(request => request.method !== 'GET').length;
  const detailKey = f.location().key;
  assert.equal(await f.back(), true); assert.equal(f.params.get('view'), 'gmail'); assert.equal(f.params.get('item'), null);
  assert.equal(privateDetailBack(f), undefined); assert.equal(f.nodes().some(node => node.props.className === 'pw-mail-feedback'), false);
  assert.equal(await f.forward(), true); assert.equal(f.location().key, detailKey); assert.equal(f.params.get('item'), 'pop-message'); assert.ok(privateDetailBack(f));
  assert.equal(await f.back(), true); assert.equal(await f.back(), true); assert.equal(f.params.get('view'), 'today');
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, initialWrites); f.unmount();
});

test('native back closes snooze above a detail and dirty time changes require confirmation', async () => {
  const f = fixture(); await f.flush(); await openMail(f); f.button('稍后处理').props.onClick(); await f.flush();
  const initialWrites = f.requests.filter(request => request.method !== 'GET').length;
  assert.equal(f.params.get('panel'), 'snooze'); assert.ok(f.button('保存时间'));
  const due = f.nodes().find(node => node.type === 'input' && node.props.type === 'datetime-local');
  due.props.onChange({ target: { value: '2030-12-01T09:00' } }); await f.flush();
  let prompts = 0; f.window.confirm = () => { prompts++; return false; };
  assert.equal(await f.back(), false); assert.equal(prompts, 1); assert.equal(f.params.get('panel'), 'snooze');
  assert.ok(f.button('保存时间')); assert.equal(f.requests.filter(request => request.method !== 'GET').length, initialWrites);
  f.window.confirm = () => { prompts++; return true; };
  assert.equal(await f.back(), true); assert.equal(prompts, 2); assert.equal(f.params.get('panel'), null);
  assert.equal(f.params.get('item'), 'message'); assert.ok(privateDetailBack(f)); assert.equal(f.button('保存时间'), undefined);
  assert.equal(await f.back(), true); assert.equal(f.params.get('item'), null); assert.equal(privateDetailBack(f), undefined); f.unmount();
});

test('native back protects a nested personal editor then returns to the unchanged detail before the list', async () => {
  const item = { ...mail('navigation-task'), source_id: 'manual', kind: 'task', title: 'Existing personal task', status: 'manual', mail_relevance: undefined };
  const f = fixture([item], 'manual'); await f.flush();
  f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-item ').props.onClick(); await f.flush();
  f.button('编辑').props.onClick(); await f.flush(); assert.equal(f.params.get('panel'), 'editor');
  titleInput(f).props.onChange({ target: { value: 'Unsaved private title' } }); await f.flush();
  let prompts = 0; f.window.confirm = () => { prompts++; return false; };
  assert.equal(await f.back(), false); assert.equal(prompts, 1); assert.equal(titleInput(f).props.value, 'Unsaved private title');
  f.window.confirm = () => { prompts++; return true; };
  assert.equal(await f.back(), true); assert.equal(prompts, 2); assert.equal(f.params.get('panel'), null);
  assert.equal(titleInput(f), undefined); assert.equal(f.params.get('item'), item.id); assert.ok(privateDetailBack(f));
  assert.ok(f.text().includes('Existing personal task')); assert.ok(!f.text().includes('Unsaved private title'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0);
  await f.back(); assert.equal(f.params.get('item'), null); assert.equal(f.params.get('view'), 'manual'); f.unmount();
});

test('saved personal edits return to the updated detail and the next back reaches the source list', async () => {
  const item = { ...mail('saved-task'), source_id: 'manual', kind: 'task', title: 'Before save', status: 'manual', mail_relevance: undefined };
  const f = fixture([item], 'manual'); await f.flush();
  f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-item ').props.onClick(); await f.flush();
  f.button('编辑').props.onClick(); await f.flush(); titleInput(f).props.onChange({ target: { value: 'Saved private task' } }); await f.flush();
  f.window.confirm = () => { throw new Error('A saved draft must not require discard confirmation'); };
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  assert.equal(f.params.get('panel'), null); assert.equal(f.params.get('item'), item.id); assert.equal(titleInput(f), undefined);
  assert.ok(f.text().includes('Saved private task')); assert.ok(f.text().includes('个人事项已保存'));
  assert.equal(f.requests.filter(request => request.method === 'PATCH').length, 1);
  assert.ok(f.requests.every(request => request.url.startsWith('/api/v1/private-workspace')));
  assert.equal(await f.back(), true); assert.equal(f.params.get('item'), null); assert.equal(f.params.get('view'), 'manual'); f.unmount();
});

test('history contains navigation metadata only and a new owner session cannot restore earlier detail caches', async () => {
  const item = mail('session-message'); item.summary = 'Private body must never enter router history';
  const f = fixture([item], 'today'); await f.flush(); f.button('重要邮件').props.onClick(); await f.flush(); await openMail(f);
  const states = f.history().map(entry => entry.state).filter(Boolean);
  for (const state of states) {
    assert.deepEqual(Object.keys(state), ['privateWorkspace']);
    assert.ok(Object.keys(state.privateWorkspace).every(key => ['session', 'parentKey', 'parentView', 'panelToken'].includes(key)));
    assert.ok(!JSON.stringify(state).includes(item.summary)); assert.ok(!JSON.stringify(state).includes(item.title));
  }
  f.changeSession('synthetic-second-owner'); await f.flush();
  assert.ok(f.text().includes('此空间仅对本人开放')); assert.equal(privateDetailBack(f), undefined);
  await f.remount(); assert.equal(f.params.get('item'), null); assert.equal(f.params.get('panel'), null); assert.equal(privateDetailBack(f), undefined);
  privateHeaderBack(f).props.onClick(); await f.flush(); assert.equal(f.params.get('view'), 'today');
  assert.equal(f.navigationCalls.some(call => call.type === 'POP'), false); f.unmount();
});

test('native back protects preference edits and forward rereads saved preferences without reviving discarded text', async () => {
  const f = fixture(); await f.flush(); f.button('关注设置').props.onClick(); await f.flush();
  const keywords = () => f.nodes().find(node => node.type === 'textarea' && node.props.placeholder.includes('项目名'));
  assert.equal(f.params.get('panel'), 'preferences');
  keywords().props.onChange({ target: { value: 'Unsaved navigation keyword' } }); await f.flush();
  let prompts = 0; f.window.confirm = () => { prompts++; return false; };
  assert.equal(await f.back(), false); assert.equal(prompts, 1); assert.equal(keywords().props.value, 'Unsaved navigation keyword');
  f.window.confirm = () => { prompts++; return true; };
  assert.equal(await f.back(), true); assert.equal(prompts, 2); assert.equal(f.params.get('panel'), null);
  assert.equal(f.button('保存关注设置'), undefined); assert.equal(f.requests.filter(request => request.method === 'PATCH').length, 0);
  const previousReads = f.requests.filter(request => request.url.endsWith('/preferences') && request.method === 'GET').length;
  assert.equal(await f.forward(), true); assert.equal(f.params.get('panel'), 'preferences');
  assert.ok(f.button('保存关注设置')); assert.equal(keywords().props.value, '');
  assert.equal(f.requests.filter(request => request.url.endsWith('/preferences') && request.method === 'GET').length, previousReads + 1);
  assert.equal(f.requests.filter(request => request.method === 'PATCH').length, 0); f.unmount();
});

test('saving preferences returns to the same Gmail list and later back remains inside the private space', async () => {
  const f = fixture([mail('preferences-save')], 'today'); await f.flush(); f.button('重要邮件').props.onClick(); await f.flush();
  f.button('关注设置').props.onClick(); await f.flush();
  f.nodes().find(node => node.type === 'textarea' && node.props.placeholder.includes('项目名')).props.onChange({ target: { value: 'Saved keyword' } }); await f.flush();
  f.window.confirm = () => { throw new Error('Saving preferences must release the draft guard'); };
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  assert.equal(f.params.get('panel'), null); assert.equal(f.params.get('view'), 'gmail'); assert.equal(f.button('保存关注设置'), undefined);
  assert.deepEqual(Array.from(f.preferences.gmail.watch_keywords), ['Saved keyword']);
  assert.equal(f.requests.filter(request => request.method === 'PATCH').length, 1);
  assert.equal(await f.back(), true); assert.equal(f.params.get('view'), 'today'); f.unmount();
});

test('new personal item save replaces its editor with the detail so one back reaches the list', async () => {
  const f = fixture([], 'manual'); await f.flush(); f.button('新增事项').props.onClick(); await f.flush();
  titleInput(f).props.onChange({ target: { value: 'New navigation task' } }); await f.flush();
  f.window.confirm = () => { throw new Error('A newly saved item must not prompt discard'); };
  await f.nodes().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await f.flush();
  assert.equal(f.params.get('panel'), null); assert.equal(f.params.get('item'), 'new-personal'); assert.ok(privateDetailBack(f));
  assert.ok(f.text().includes('New navigation task')); assert.equal(titleInput(f), undefined);
  assert.equal(f.requests.filter(request => request.method === 'POST').length, 1);
  assert.equal(f.requests.find(request => request.method === 'POST').url, '/api/v1/private-workspace/items');
  assert.equal(await f.back(), true); assert.equal(f.params.get('item'), null); assert.equal(f.params.get('view'), 'manual');
  assert.ok(f.text().includes('New navigation task')); assert.equal(privateDetailBack(f), undefined); f.unmount();
});

test('returning from Ads connections restores the selected delivery bucket and local search', async () => {
  const fixtures = ['problem', 'healthy'].map((bucket, index) => adsFixture(bucket, index));
  const f = fixture(fixtures.map(value => value.item), 'google_ads', [fixtures[0].source]); await f.flush();
  f.button('正常投放1').props.onClick(); await f.flush();
  f.nodes().find(node => node.type === 'input' && node.props['aria-label'] === '搜索已同步广告系列').props.onChange({ target: { value: '合成广告系列 1' } }); await f.flush();
  f.button('管理接入').props.onClick(); await f.flush(); assert.equal(f.params.get('view'), 'connections');
  assert.equal(await f.back(), true); assert.equal(f.params.get('view'), 'google_ads');
  const search = f.nodes().find(node => node.type === 'input' && node.props['aria-label'] === '搜索已同步广告系列');
  assert.equal(search.props.value, '合成广告系列 1');
  assert.equal(f.nodes().filter(node => node.props.className === 'pw-ads-row').length, 1);
  search.props.onChange({ target: { value: '' } }); await f.flush();
  assert.equal(f.button('正常投放1').props['aria-pressed'], true);
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});

const editorFields = f => ({
  title: titleInput(f),
  summary: f.nodes().find(node => node.type === 'textarea' && node.props.maxLength === 5000),
  priority: f.nodes().find(node => node.type === 'select'),
  due: f.nodes().find(node => node.type === 'input' && node.props.type === 'datetime-local'),
});

test('forward to a discarded new personal editor restores its blank starting values without resurrecting its draft', async () => {
  const f = fixture([], 'manual'); await f.flush(); f.button('新增事项').props.onClick(); await f.flush();
  const editorKey = f.location().key;
  const fields = editorFields(f);
  fields.title.props.onChange({ target: { value: 'Discarded private task title' } });
  fields.summary.props.onChange({ target: { value: 'Discarded private task notes' } });
  fields.priority.props.onChange({ target: { value: 'urgent' } });
  fields.due.props.onChange({ target: { value: '2030-12-01T09:00' } }); await f.flush();
  let prompts = 0; f.window.confirm = () => { prompts++; return true; };
  assert.equal(await f.back(), true); assert.equal(prompts, 1); assert.equal(f.params.get('panel'), null);
  assert.equal(await f.forward(), true); assert.equal(f.location().key, editorKey); assert.equal(f.params.get('panel'), 'editor');
  const restored = editorFields(f);
  assert.equal(restored.title.props.value, ''); assert.equal(restored.summary.props.value, '');
  assert.equal(restored.priority.props.value, 'normal'); assert.equal(restored.due.props.value, '');
  assert.ok(!JSON.stringify(f.history()).includes('Discarded private task'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0);
  f.window.confirm = () => { throw new Error('Restored initial editor values must be clean'); };
  assert.equal(await f.back(), true); assert.equal(f.params.get('view'), 'manual'); f.unmount();
});

test('brief proposal editor restores its own proposal on forward even after another new editor was visited', async () => {
  const f = fixture([], 'today'); f.setBriefHandler(() => briefSnapshot('today', { issues: [bossIssue] })); await f.flush();
  f.button('加入个人事项').props.onClick(); await f.flush(); const proposalKey = f.location().key;
  const initial = editorFields(f); const proposalSummary = initial.summary.props.value;
  assert.equal(initial.title.props.value, bossIssue.title); assert.ok(proposalSummary.includes(bossIssue.next_action));
  initial.title.props.onChange({ target: { value: 'Discarded proposal title' } });
  initial.summary.props.onChange({ target: { value: 'Discarded proposal notes' } });
  initial.priority.props.onChange({ target: { value: 'high' } });
  initial.due.props.onChange({ target: { value: '2030-12-02T09:00' } }); await f.flush();
  let prompts = 0; f.window.confirm = () => { prompts++; return true; };
  assert.equal(await f.back(), true); assert.equal(prompts, 1); assert.equal(await f.forward(), true);
  assert.equal(f.location().key, proposalKey); assert.equal(editorFields(f).title.props.value, bossIssue.title);
  assert.equal(editorFields(f).summary.props.value, proposalSummary); assert.equal(editorFields(f).priority.props.value, 'normal');
  assert.equal(editorFields(f).due.props.value, '');

  f.button('个人事项').props.onClick(); await f.flush(); f.button('新增事项').props.onClick(); await f.flush();
  editorFields(f).title.props.onChange({ target: { value: 'Another discarded editor title' } });
  editorFields(f).summary.props.onChange({ target: { value: 'Another discarded editor notes' } }); await f.flush();
  assert.equal(await f.back(), true); assert.equal(prompts, 2); assert.equal(f.params.get('view'), 'manual');
  assert.equal(await f.back(), true); assert.equal(f.location().key, proposalKey);
  assert.equal(editorFields(f).title.props.value, bossIssue.title); assert.equal(editorFields(f).summary.props.value, proposalSummary);
  f.window.confirm = () => { throw new Error('Discarded drafts must not dirty restored proposal values'); };
  assert.equal(await f.back(), true); assert.equal(f.params.get('view'), 'today'); assert.equal(f.params.get('panel'), null);
  assert.equal(await f.forward(), true); assert.equal(f.location().key, proposalKey);
  assert.equal(editorFields(f).title.props.value, bossIssue.title); assert.equal(editorFields(f).summary.props.value, proposalSummary);
  assert.equal(editorFields(f).priority.props.value, 'normal'); assert.equal(editorFields(f).due.props.value, '');
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});

test('forward to an earlier detail uses refreshed authoritative item fields rather than its old panel snapshot', async () => {
  const item = mail('authoritative-detail'); const f = fixture([item]);
  f.setMailCapabilitiesHandler(() => briefCapabilities(false)); await f.flush(); await openMail(f);
  const detail = () => f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-surface pw-detail-sheet');
  assert.ok(f.textOf(detail()).includes('Synthetic authoritative-detail'));
  assert.equal(await f.back(), true);
  item.title = 'Updated authoritative private title'; item.summary = 'Updated authoritative private summary'; item.action_status = 'done';
  f.button('刷新').props.onClick(); await f.flush();
  assert.ok(f.text().includes(item.title)); assert.equal(await f.forward(), true);
  assert.ok(detail()); assert.ok(f.textOf(detail()).includes(item.title)); assert.ok(f.textOf(detail()).includes(item.summary));
  assert.ok(f.textOf(detail()).includes('已处理')); assert.ok(!f.textOf(detail()).includes('Synthetic authoritative-detail'));
  assert.equal(f.button('标记已处理'), undefined); assert.ok(f.button('恢复待处理'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});

test('forward to a Stripe detail after refresh shows current captured and refund amounts instead of old authorization fields', async () => {
  const source = stripeSource(); const item = stripePayment(source); const f = fixture([item], 'stripe', [source]); await f.flush();
  f.nodes().find(node => node.type === 'button' && node.props.className === 'pw-stripe-row ').props.onClick(); await f.flush();
  const detail = () => f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-stripe-detail');
  assert.ok(f.textOf(detail()).includes('授权金额尚未捕获，不代表实际收款'));
  assert.equal(await f.back(), true);
  item.evidence = { ...item.evidence, captured: true, payment_state: 'partially_refunded', amount_captured_minor: 8000, amount_refunded_minor: 2500 };
  f.button('刷新').props.onClick(); await f.flush(); assert.equal(await f.forward(), true);
  const current = f.textOf(detail()).replace(/\s/g, ' ');
  assert.ok(current.includes('部分退款')); assert.ok(current.includes('已收款金额USD 80.00')); assert.ok(current.includes('已退款金额USD 25.00'));
  assert.ok(!current.includes('授权金额尚未捕获')); assert.ok(!current.includes('已收款金额USD 0.00'));
  assert.equal(f.requests.filter(request => request.method !== 'GET' && !request.url.endsWith('/stripe/report')).length, 0); f.unmount();
});

test('successful mail body or brief enrichment remains detail-only and survives back and forward without another provider request', async () => {
  for (const mode of ['body', 'brief']) {
    const item = mail(`enriched-${mode}`); const f = fixture([item]); const original = `Private enriched ${mode} original`;
    if (mode === 'body') {
      item.mail_translation = translated(item.id);
      f.setTranslationBodyHandler(() => ({ configured: true, item_id: item.id, translation: translated(item.id, { updated_at: '2026-10-11T08:30:00Z', body_original: original, body_zh: '详情中文正文保留', body_available: true }) }));
    } else {
      f.setMailCapabilitiesHandler(() => briefCapabilities());
      f.setMailBriefHandler(() => ({ configured: true, item_id: item.id, brief: organized({ updated_at: '2026-10-11T08:30:00Z', original_body: original, summary_zh: '已经整理的中文重点保留' }) }));
    }
    await f.flush(); await openMail(f); f.button(mode === 'body' ? '翻译正文' : '整理这封邮件').props.onClick(); await f.flush();
    assert.ok(f.text().includes(mode === 'body' ? '详情中文正文保留' : '已经整理的中文重点保留'));
    assert.equal(await f.back(), true); assert.ok(!f.text().includes(original)); assert.equal(privateDetailBack(f), undefined);
    assert.equal(await f.forward(), true); assert.ok(privateDetailBack(f));
    const detail = f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-surface pw-detail-sheet');
    assert.ok(f.textOf(detail).includes(mode === 'body' ? '详情中文正文保留' : '已经整理的中文重点保留'));
    f.button('原文').props.onClick(); await f.flush(); assert.ok(f.text().includes(original));
    const providerRequests = f.requests.filter(request => request.url.endsWith(mode === 'body' ? '/mail-translation' : '/mail-brief'));
    assert.equal(providerRequests.length, 1); assert.ok(!JSON.stringify(f.history()).includes(original));
    f.unmount();
  }
});

test('refreshed mail previews retain detail-only body only for matching text and version while keeping latest server brief fields', async () => {
  for (const mode of ['body', 'brief']) for (const revision of ['same', 'version', 'missing-version', 'title', 'summary']) {
    const item = mail(`preview-${mode}-${revision}`); const f = fixture([item]); const original = `Private cached ${mode} ${revision} body`;
    const enriched = mode === 'body'
      ? translated(item.id, { updated_at: '2026-10-11T08:30:00Z', body_original: original, body_zh: '已缓存中文正文', body_available: true })
      : organized({ updated_at: '2026-10-11T08:30:00Z', original_body: original, importance: 'urgent', needs_action: true, summary_zh: '旧版处理建议' });
    if (mode === 'body') {
      item.mail_translation = translated(item.id);
      f.setTranslationBodyHandler(() => ({ configured: true, item_id: item.id, translation: enriched }));
    } else {
      f.setMailCapabilitiesHandler(() => briefCapabilities());
      f.setMailBriefHandler(() => ({ configured: true, item_id: item.id, brief: enriched }));
    }
    await f.flush(); await openMail(f); f.button(mode === 'body' ? '翻译正文' : '整理这封邮件').props.onClick(); await f.flush();
    assert.equal(await f.back(), true);
    if (mode === 'body') item.mail_translation = { ...enriched, body_original: undefined, body_zh: undefined, body_available: false, summary_zh: '来源最新中文摘要' };
    else item.mail_brief = { ...enriched, original_body: undefined, source_evidence: undefined,
      importance: 'read', needs_action: false, summary_zh: '来源最新阅读建议', next_action: '阅读后了解即可', deadline: { ...enriched.deadline, evidence: undefined } };
    const preview = mode === 'body' ? item.mail_translation : item.mail_brief;
    if (revision === 'version') preview.updated_at = '2026-10-11T09:00:00Z';
    if (revision === 'missing-version') delete preview.updated_at;
    if (revision === 'title') item.title = 'Changed source mail subject';
    if (revision === 'summary') item.summary = 'Changed source mail snippet';
    f.button('刷新').props.onClick(); await f.flush(); assert.equal(await f.forward(), true);
    if (mode === 'brief') {
      const props = f.componentProps('PrivateMailBrief'); assert.ok(props);
      assert.equal(props.item.mail_brief.importance, 'read'); assert.equal(props.item.mail_brief.needs_action, false);
      assert.ok(f.text().includes('了解即可')); assert.ok(f.text().includes('来源最新阅读建议')); assert.ok(!f.text().includes('旧版处理建议'));
    }
    f.button('原文').props.onClick(); await f.flush();
    assert.equal(f.text().includes(original), revision === 'same', `${mode}/${revision} detail cache provenance`);
    assert.ok(!JSON.stringify(f.history()).includes(original));
    assert.equal(f.requests.filter(request => request.url.endsWith(mode === 'body' ? '/mail-translation' : '/mail-brief')).length, 1);
    f.unmount();
  }
});


test('Ads detail creates a readable source-based personal draft without changing an ad or saving automatically', async () => {
  const { item, source } = adsFixture('problem');
  item.title = 'LocalServicesCampaign:SystemGenerated:000657ec92f7095e';
  const f = fixture([item], 'google_ads', [source]); f.setMailCapabilitiesHandler(() => briefCapabilities(false));
  await f.flush(); f.button('查看检查').props.onClick(); await f.flush();
  const detailKey = f.location().key;
  const heading = f.nodes().find(node => node.type === 'div' && node.props.className === 'pw-surface pw-detail-sheet');
  assert.ok(f.textOf(heading).includes('本地服务广告'));
  f.button('加入个人事项').props.onClick(); await f.flush();
  assert.ok(titleInput(f).props.value.includes('本地服务广告'));
  const summary = f.nodes().find(node => node.type === 'textarea');
  assert.ok(summary.props.value.includes('检查预算配置原因'));
  assert.ok(summary.props.value.includes('https://ads.google.com/aw/overview'));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0);
  assert.equal(await f.back(), true); assert.equal(f.location().key, detailKey);
  assert.equal(f.params.get('item'), item.id); assert.ok(privateDetailBack(f));
  assert.equal(f.requests.filter(request => request.method !== 'GET').length, 0); f.unmount();
});
