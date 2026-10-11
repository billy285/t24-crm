import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const same = (left, right) => left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const mail = (id, bucket = 'today') => ({
  id, source_id: 'gmail', kind: 'email', title: `Synthetic ${id}`, summary: 'Synthetic snippet', status: 'unread', priority: bucket === 'urgent' ? 'urgent' : 'high',
  amount_minor: null, currency: null, occurred_at: null, due_at: null, source_url: null, evidence: { from: 'Synthetic <sender@example.com>' }, action_status: 'open', snoozed_until: null,
  mail_relevance: { bucket, category: bucket === 'urgent' ? 'security' : 'business', reasons: ['Synthetic reason'], feedback: null, sender_address: 'sender@example.com', sender_verification: 'unverified' },
});

// Run the actual component, API and draft guard against synthetic transport and
// controlled hook scheduling. No mailbox, browser storage or external API is used.
function fixture(items = [mail('message')], initialView = 'gmail', extraSources = []) {
  let cursor = 0, epoch = 'synthetic-owner', tree, now = Date.now();
  const timers = new Map();
  class SyntheticDate extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
  const hooks = [], effects = [], requests = [], listeners = new Map(), modules = new Map();
  const params = new URLSearchParams({ view: initialView });
  let preferencesHandler, syncHandler, translationPreviewHandler, translationBodyHandler;
  const preferences = { sync_interval_seconds: 2700, gmail: { topics: ['finance', 'security'], watch_senders: [], watch_keywords: [], muted_senders: [] } };
  const source = { id: 'gmail', status: 'connected', capabilities: [], missing_configuration: [], last_sync: null, error: null };
  const react = {
    useState(initial) { const index = cursor++; if (!hooks[index]) hooks[index] = { value: typeof initial === 'function' ? initial() : initial }; return [hooks[index].value, next => { hooks[index].value = typeof next === 'function' ? next(hooks[index].value) : next; }]; },
    useRef(initial) { const index = cursor++; if (!hooks[index]) hooks[index] = { value: { current: initial } }; return hooks[index].value; },
    useMemo(factory, dependencies) { const index = cursor++; if (!hooks[index] || !same(hooks[index].dependencies, dependencies)) hooks[index] = { value: factory(), dependencies }; return hooks[index].value; },
    useCallback(callback, dependencies) { return react.useMemo(() => callback, dependencies); },
    useEffect(effect, dependencies) { const index = cursor++; if (!hooks[index] || !same(hooks[index].dependencies, dependencies)) { const previous = hooks[index]; hooks[index] = { dependencies, cleanup: previous?.cleanup }; effects.push(() => { hooks[index].cleanup?.(); hooks[index].cleanup = effect(); }); } },
  };
  react.useLayoutEffect = react.useEffect;
  const window = { setInterval: callback => { const id = timers.size + 1; timers.set(id, callback); return id; }, clearInterval: id => timers.delete(id), confirm: () => true, location: { assign: () => { throw new Error('No OAuth expected'); } }, addEventListener: (name, listener) => { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(listener); }, removeEventListener: (name, listener) => listeners.get(name)?.delete(listener) };
  const context = vm.createContext({ URL, URLSearchParams, Intl, Date: SyntheticDate, window, console });
  function load(relative) {
    if (modules.has(relative)) return modules.get(relative);
    const path = resolve(root, relative);
    const compiled = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const module = { exports: {} };
    const require = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return jsx;
      if (name === 'react-router-dom') return { Link: 'a', useSearchParams: () => [params, next => { for (const key of [...params.keys()]) params.delete(key); for (const [key, value] of Object.entries(next)) params.set(key, value); }] };
      if (name === 'lucide-react') return new Proxy({}, { get: () => props => jsx.jsx('svg', props) });
      if (name.endsWith('.css')) return {};
      if (name === '@/lib/auth-storage') return { AUTH_SESSION_INVALIDATED_EVENT: 'synthetic-auth-invalidated', getAuthSessionEpoch: () => epoch };
      if (name === '@/lib/private-workspace-api') return load('lib/private-workspace-api.ts');
      if (name === '@/lib/private-ads') return load('lib/private-ads.ts');
      if (name === './PrivateAdsDashboard') return load('pages/PrivateAdsDashboard.tsx');
      if (name === './PrivateMailContent') return load('pages/PrivateMailContent.tsx');
      if (name === '@/lib/use-dialog-draft') return load('lib/use-dialog-draft.ts');
      if (name === './use-unsaved-changes') return load('lib/use-unsaved-changes.ts');
      if (name.startsWith('@/components/ui/')) return new Proxy({}, { get: (_, key) => key === 'Dialog' || key === 'Sheet' ? props => props.open ? props.children : null : props => jsx.jsx('div', props) });
      if (name === './api') return { client: { apiCall: { invoke: async request => {
        requests.push(request);
        const url = new URL(request.url, 'https://synthetic.example');
        if (url.pathname.endsWith('/access')) return { data: { allowed: true } };
        if (url.pathname === '/api/v1/private-workspace') return { data: { sources: [source, ...extraSources], items, balances: [], last_sync: null } };
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
          const bucket = url.searchParams.get('mail_bucket');
          const filtered = items.filter(item => !bucket || item.mail_relevance?.bucket === bucket);
          const counts = { urgent: 0, today: 0, digest: 0, low: 0 }; items.forEach(item => { if (item.mail_relevance) counts[item.mail_relevance.bucket]++; });
          return { data: { items: structuredClone(filtered.slice(0, Number(url.searchParams.get('limit') || 100))), total: filtered.length, mail_counts: counts } };
        }
        throw new Error(`Unexpected synthetic request ${url.pathname}`);
      } } } };
      throw new Error(`Unexpected module ${name}`);
    };
    vm.runInContext(`(function(require,module,exports){${compiled}\n})`, context, { filename: path })(require, module, module.exports);
    modules.set(relative, module.exports); return module.exports;
  }
  const component = load('pages/PrivateWorkspace.tsx').default;
  function expand(node) {
    if (node === null || node === undefined || typeof node === 'boolean') return [];
    if (Array.isArray(node)) return node.flatMap(expand);
    if (typeof node !== 'object') return [String(node)];
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return [{ ...node, children: expand(node.props?.children) }];
  }
  function render() { cursor = 0; tree = expand(component()); while (effects.length) effects.shift()(); return tree; }
  const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
  function all(nodes = tree) { return nodes.flatMap(node => typeof node === 'object' ? [node, ...all(node.children || [])] : []); }
  async function flush() { for (let count = 0; count < 20; count++) { render(); await Promise.resolve(); } render(); }
  return {
    requests, window, preferences, params, flush, text: () => tree.map(text).join(''), textOf: text, nodes: () => all(),
    find: (type, label) => all().find(node => node.type === type && text(node) === label),
    button: label => all().find(node => node.type === 'button' && text(node).trim() === label),
    setPreferencesHandler: handler => { preferencesHandler = handler; },
    setSyncHandler: handler => { syncHandler = handler; },
    setTranslationPreviewHandler: handler => { translationPreviewHandler = handler; },
    setTranslationBodyHandler: handler => { translationBodyHandler = handler; },
    advanceTime(milliseconds) { now += milliseconds; for (const callback of timers.values()) callback(); },
    invalidate() { epoch = 'synthetic-new-account'; for (const listener of listeners.get('synthetic-auth-invalidated') || []) listener(); },
    unmount() { hooks.forEach(hook => hook?.cleanup?.()); },
  };
}

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
  const f = fixture([mail('focus', 'today'), mail('digest', 'digest'), mail('low', 'low')], 'today'); await f.flush();
  assert.ok(f.text().includes('Synthetic focus'), f.text());
  assert.ok(!f.text().includes('Synthetic digest'));
  assert.ok(!f.text().includes('Synthetic low'));
  f.unmount();
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
  assert.ok(f.text().includes('尚无可判断的广告检查数据'));
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

import { adsFixture } from './fixtures/private-ads.mjs';
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
  f.button('今日重点').props.onClick(); await f.flush(); assert.ok(!f.text().includes('Original full body')); assert.ok(!f.text().includes('中文完整正文')); assert.ok(f.text().includes('中文 body · Stripe')); f.unmount();
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
