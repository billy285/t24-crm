import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';
import * as jsx from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const modules = new Map();
function load(relative) {
  if (modules.has(relative)) return modules.get(relative);
  const filename = resolve(root, relative);
  const source = ts.transpileModule(readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const module = { exports: {} };
  const require = name => {
    if (name === 'react/jsx-runtime') return jsx;
    if (name === 'lucide-react') return new Proxy({}, { get: () => props => jsx.jsx('svg', props) });
    if (name === '@/lib/private-boss-brief') return load('lib/private-boss-brief.ts');
    if (name.endsWith('.css')) return {};
    throw new Error(`Unexpected synthetic dependency: ${name}`);
  };
  vm.runInNewContext(`(function(require,module,exports){${source}\n})`, { Date, Intl })(require, module, module.exports);
  modules.set(relative, module.exports); return module.exports;
}
const helpers = load('lib/private-boss-brief.ts');
const component = load('pages/PrivateBossBrief.tsx').default;
const issue = (id, source_id = 'gmail') => ({ id, source_id, item_id: `item-${id}`, title: `Synthetic ${id}`, summary: '系统识别的关注事项', next_action: '核对原始来源后处理', priority: 'high', observed_at: '2026-10-11T02:00:00Z', task_title: `核对 ${id}` });
const source = (source_id, facts = []) => ({ source_id, status: 'connected', last_sync: '2026-10-11T02:00:00Z', data_state: 'ready', summary: '本期已同步的信息', facts });
const data = (overrides = {}) => ({ snapshot_id: 'synthetic-snapshot', period: 'today', generated_at: '2026-10-11T02:30:00Z', window: { start: '2026-10-10T16:00:00Z', end: '2026-10-11T02:30:00Z', timezone: 'Asia/Shanghai' }, issues: [issue('mail'), issue('ads', 'google_ads'), issue('dispute', 'stripe')], sources: [source('gmail'), source('google_ads'), source('stripe', ['USD 可用余额：129.00', 'CNY 可用余额：600.00']), source('bofa', ['银行邮件提醒 · 待核实']), source('manual')], capabilities: { configured: true }, limitations: ['Ads 指标按广告账户时区，近7天不含今天。'], ...overrides });
function fixture(value = data(), overrides = {}) {
  const actions = [];
  const props = { data: value, period: 'today', loading: false, aiBusy: false, onExplain: () => actions.push(['explain']), onRefresh: () => actions.push(['refresh']), onPeriodChange: period => actions.push(['period', period]), onOpenSource: id => actions.push(['source', id]), onOpenItem: id => actions.push(['item', id]), onCreateTask: draft => actions.push(['draft', draft]), ...overrides };
  const element = component(props);
  function expand(node) {
    if (node == null || typeof node === 'boolean') return [];
    if (Array.isArray(node)) return node.flatMap(expand);
    if (typeof node !== 'object') return [String(node)];
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return [{ ...node, children: expand(node.props?.children) }];
  }
  const tree = expand(element);
  const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
  const all = nodes => nodes.flatMap(node => typeof node === 'object' ? [node, ...all(node.children || [])] : []);
  return { props, actions, nodes: all(tree), text: tree.map(text).join(''), textOf: text, markup: () => renderToStaticMarkup(element), button: label => all(tree).find(node => node.type === 'button' && text(node) === label) };
}

test('system overview stays capped at three, folds all source cards and never calls AI on render', () => {
  const f = fixture(data({ issues: [issue('one'), issue('two'), issue('three'), issue('four')] }));
  assert.equal(f.nodes.filter(node => node.type === 'article' && node.props.className === 'pw-boss-issue').length, 3);
  assert.ok(!f.text.includes('Synthetic four')); assert.equal(f.actions.length, 0);
  const cards = f.nodes.filter(node => node.type === 'details' && node.props.className === 'pw-boss-source'); assert.equal(cards.length, 5); assert.ok(cards.every(card => card.props.open === undefined));
  assert.equal(f.nodes.find(node => node.props.className === 'pw-boss-limits').props.open, undefined);
  assert.ok(!f.text.includes('老板经营简报')); assert.ok(f.button('近7天')); f.button('近7天').props.onClick(); assert.deepEqual(f.actions, [['period', 'last7days']]);
});
test('compact priority cards keep full evidence collapsed while next actions remain visible and normal refresh is not duplicated', () => {
  const value = data({ issues: [{ ...issue('mail'), summary: '原始来源依据：USD 129.00，待核实付款提醒。' }, issue('ads', 'google_ads')] });
  const f = fixture(value);
  const cards = f.nodes.filter(node => node.type === 'article' && node.props.className === 'pw-boss-issue');
  assert.equal(cards.length, 2);
  const evidence = f.nodes.filter(node => node.type === 'details' && node.props.className === 'pw-boss-issue-evidence');
  assert.equal(evidence.length, 2); assert.ok(evidence.every(node => node.props.open === undefined));
  assert.ok(f.textOf(evidence[0]).includes(value.issues[0].summary));
  assert.equal(f.textOf(evidence[0].children.find(node => node.type === 'summary')), '依据');
  const actions = f.nodes.filter(node => node.props.className === 'pw-boss-issue-actions');
  assert.ok(actions.every(node => node.children.some(child => child.props?.className === 'pw-boss-issue-evidence')));
  assert.equal(f.nodes.filter(node => node.props.className === 'pw-boss-next').length, 2);
  assert.ok(!f.nodes.some(node => node.props.className === 'pw-boss-issue-summary'));
  assert.ok(!f.nodes.some(node => node.type === 'button' && node.props['aria-label'] === '重新读取经营简报'));
  assert.equal(f.button('重新读取'), undefined);
  const header = f.nodes.find(node => node.type === 'header' && node.props.className === 'pw-boss-header');
  assert.ok(f.textOf(header).includes('更新')); assert.ok(f.textOf(header).includes('今日近7天'));
  assert.equal(f.actions.length, 0);
});
test('unconfigured AI remains visibly pending, disabled and never invents AI text or monetary zeros for disconnected sources', () => {
  const missing = { ...source('stripe', ['USD 收款：0.00']), status: 'not_configured', data_state: 'missing', summary: 'USD 收款：0.00' };
  const f = fixture(data({ capabilities: { configured: false, code: 'not_configured' }, sources: [missing], ai: null }));
  assert.equal(f.button('中文解读').props.disabled, true); assert.ok(f.text.includes('中文解读尚待接入')); assert.ok(f.text.includes('尚未连接'));
  assert.ok(!f.text.includes('USD 收款：0.00')); assert.ok(!f.text.includes('AI 阅读建议')); assert.equal(f.actions.length, 0);
});
test('AI ready explanation is separate from source amounts, cannot change system order or populate personal task drafts', () => {
  const value = data({ ai: { state: 'ready', summary: 'AI给出的阅读建议', issue_notes: [{ issue_id: 'mail', explanation: 'AI建议调整广告金额99999' }, { issue_id: 'unknown', explanation: 'Unknown private issue' }] } });
  const before = JSON.stringify(value); const f = fixture(value);
  assert.ok(f.text.includes('AI给出的阅读建议')); assert.ok(f.text.includes('USD 可用余额：129.00')); assert.ok(f.text.includes('CNY 可用余额：600.00')); assert.ok(!f.text.includes('合计')); assert.ok(!f.text.includes('Unknown private issue'));
  assert.ok(f.text.indexOf('Synthetic mail') < f.text.indexOf('Synthetic ads')); const task = f.nodes.find(node => node.type === 'button' && f.textOf(node) === '加入个人事项'); task.props.onClick();
  assert.equal(f.actions[0][0], 'draft'); assert.equal(f.actions[0][1].title, '核对 mail'); assert.ok(f.actions[0][1].summary.includes('核对原始来源后处理')); assert.ok(!f.actions[0][1].summary.includes('99999')); assert.equal(JSON.stringify(value), before);
  const read = f.nodes.find(node => node.type === 'button' && f.textOf(node) === '查看来源'); read.props.onClick(); assert.deepEqual(f.actions[1], ['item', 'item-mail']);
});
test('old-period system and AI data cannot appear in a newly selected period', () => {
  const f = fixture(data({ ai: { state: 'ready', summary: 'Old private explanation', issue_notes: [] } }), { period: 'last7days' });
  assert.ok(f.text.includes('简报尚未就绪')); assert.ok(!f.text.includes('Synthetic mail')); assert.ok(!f.text.includes('Old private explanation')); assert.equal(f.actions.length, 0);
});
test('pending or failed interpretation preserves system data with safe notices and never automatically retries', () => {
  for (const ai of [{ state: 'pending', code: 'pending' }, { state: 'failed', code: 'RAW SECRET' }]) {
    const f = fixture(data({ ai: { ...ai, summary: '', issue_notes: [] } })); assert.ok(f.text.includes('Synthetic mail')); assert.ok(!f.text.includes('RAW SECRET')); assert.equal(f.actions.length, 0);
  }
  const busy = fixture(data(), { aiBusy: true }); assert.equal(busy.button('正在解读…').props.disabled, true); assert.ok(busy.text.includes('系统简报仍可查看')); assert.equal(busy.actions.length, 0);
});
test('bank reminders remain unverified and each source keeps its own time without merging financial totals', () => {
  const ads = { ...source('google_ads', ['近7日费用 USD 41.20']), last_sync: '2026-10-10T02:00:00Z', data_state: 'stale' };
  const bank = source('bofa', ['银行邮件提醒 · 待核实']); const f = fixture(data({ sources: [source('gmail'), ads, source('stripe', ['提现 USD 129.00 · 银行待核对']), bank] }));
  const cards = f.nodes.filter(node => node.type === 'details' && node.props.className === 'pw-boss-source');
  const bankCard = cards.find(card => f.textOf(card).includes('银行邮件提醒')); assert.ok(f.textOf(bankCard).includes('待核实')); assert.ok(!f.textOf(bankCard).includes('已到账'));
  const adsCard = cards.find(card => f.textOf(card).includes('广告观察')); assert.ok(f.textOf(adsCard).includes(helpers.bossBriefTime(ads.last_sync))); assert.ok(f.textOf(adsCard).includes('需更新'));
  assert.ok(f.text.includes('提现 USD 129.00 · 银行待核对')); assert.ok(!f.text.includes('经营收入')); assert.equal(f.actions.length, 0);
});
test('malformed source IDs and facts stay bounded and model HTML is rendered as escaped text', () => {
  const html = '<script>alert(1)</script><a href="javascript:alert(1)">click</a>';
  const f = fixture(data({ issues: [issue('safe'), { ...issue('ignored'), source_id: 'crm_finance' }], ai: { state: 'ready', summary: html, issue_notes: [{ issue_id: 'safe', explanation: html }] }, sources: [source('gmail', [html, { secret: 'bad' }]), source('not_a_source', ['Unknown source raw body'])] }));
  assert.ok(!f.text.includes('Synthetic ignored')); assert.ok(!f.text.includes('Unknown source raw body')); assert.ok(!f.text.includes('[object Object]'));
  const markup = f.markup(); assert.ok(markup.includes('&lt;script&gt;')); assert.ok(!markup.includes('<script>')); assert.ok(!markup.includes('href="javascript:')); assert.equal(f.actions.length, 0);
});
test('error and loading states hide stale private details and use explicit refresh handlers', () => {
  const loading = fixture(data(), { loading: true }); assert.ok(loading.text.includes('正在整理系统简报')); assert.ok(!loading.text.includes('Synthetic mail'));
  const failed = fixture(data(), { error: '暂时无法读取系统简报' }); assert.ok(!failed.text.includes('Synthetic mail')); failed.button('重新读取').props.onClick(); assert.deepEqual(failed.actions, [['refresh']]);
});
test('a system issue without an item id opens only its private source and task draft has no due date or financial writes', () => {
  const item = { ...issue('connection', 'bofa'), item_id: null, task_title: null }; const f = fixture(data({ issues: [item] }));
  f.button('查看来源').props.onClick(); assert.deepEqual(f.actions, [['source', 'bofa']]); f.button('加入个人事项').props.onClick();
  const draft = f.actions[1][1]; assert.deepEqual(Object.keys(draft).sort(), ['summary', 'title']); assert.equal(draft.title, 'Synthetic connection'); assert.ok(draft.summary.includes('银行邮件提醒'));
});
test('valid shared monthly budget is confined to collapsed coverage and does not claim actual money spent', () => {
  const budget = { configured: true, limit_usd: '5.00', reserved_usd: '4.65', remaining_usd: '0.35', month: '2026-10' }; const f = fixture(data({ budget }));
  const coverage = f.nodes.find(node => node.type === 'details' && node.props.className === 'pw-boss-limits'); assert.equal(coverage.props.open, undefined);
  assert.ok(f.textOf(coverage).includes('邮件与简报共用每月 US$5.00 额度；本月可用 US$0.35。')); assert.ok(!f.text.includes('已花费')); assert.ok(!f.text.includes('已达到'));
  assert.deepEqual(Object.keys(helpers.bossBriefBudget(data({ budget }))).sort(), ['limit', 'remaining']);
  const disabled = fixture(data({ budget, capabilities: { configured: false, code: 'consent_required' } })); assert.ok(!disabled.text.includes('本月可用 US$')); assert.ok(!disabled.text.includes('共用每月 US$'));
  for (const invalid of [{ ...budget, limit_usd: '99.00' }, { ...budget, remaining_usd: '6.00' }, { ...budget, remaining_usd: '<script>secret</script>' }, { ...budget, configured: false }]) assert.equal(helpers.bossBriefBudget(data({ budget: invalid })), null);
});
test('changed snapshot has a safe manual-refresh notice and no automatic explanation', () => {
  const f = fixture(data({ ai: { state: 'failed', summary: '', issue_notes: [], code: 'snapshot_changed' } }));
  assert.ok(f.text.includes('数据已更新，请重新读取简报后再解读')); assert.ok(f.text.includes('Synthetic mail')); assert.equal(f.actions.length, 0);
  f.button('中文解读').props.onClick(); assert.deepEqual(f.actions, [['explain']]); assert.ok(!helpers.bossBriefNotice('RAW SECRET').includes('RAW SECRET'));
});


test('actual bank source stays separate from bank emails and its count-only coverage opens the bank dashboard', () => {
  const bank = source('bofa_bank', ['当前绑定银行已入账 3 条；待入账 1 条']);
  const mail = source('bofa', ['银行邮件提醒 · 待核实']);
  const f = fixture(data({ sources: [bank, mail], issues: [] }));
  assert.ok(f.text.includes('银行余额与流水')); assert.ok(f.text.includes('银行邮件提醒'));
  const cards = f.nodes.filter(node => node.type === 'details' && node.props.className === 'pw-boss-source'); assert.equal(cards.length, 2);
  const bankCard = cards.find(node => f.textOf(node).includes('银行余额与流水'));
  assert.ok(f.textOf(bankCard).includes('已同步')); assert.ok(!f.textOf(bankCard).includes('待核实'));
  f.button('打开银行余额与流水').props.onClick(); assert.deepEqual(f.actions, [['source', 'bofa_bank']]);
});
