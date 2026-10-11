import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const row = (extra = {}) => ({
  currency: 'USD', gross_minor: 100000, subscription_minor: 70000, one_time_minor: 25000, unclassified_minor: 5000,
  refunds_minor: 10000, net_receipts_minor: 90000, fees_minor: 3100, count: 3,
  summary: ['本月已收款 USD 1,000.00，其中订阅收款 USD 700.00。', '成功退款 USD 100.00，待分类收款 USD 50.00。'],
  comparison: { gross_minor: 80000, change_pct: 25, complete: true },
  trend: [{ date: '2026-10-01', subscription_minor: 40000, one_time_minor: 15000, unclassified_minor: 5000 }, { date: '2026-10-02', subscription_minor: 30000, one_time_minor: 10000, unclassified_minor: 0 }], ...extra,
});
const record = (id = 'payment-1', extra = {}) => ({
  id, kind: 'payment', title: `Synthetic ${id}`, status: 'captured', occurred_at: '2026-10-02T12:00:00Z', amount_minor: 40000, currency: 'USD', category: 'subscription',
  customer_label: 'Synthetic customer', subscription_id: 'sub-synthetic', invoice_id: 'in-synthetic', source_url: 'https://dashboard.stripe.com/payments/synthetic', details: { provider_id: 'ch-synthetic' }, ...extra,
});
const report = (extra = {}) => ({
  state: 'ready', snapshot_id: 'synthetic-snapshot', generated_at: '2026-10-12T08:00:00Z', account_label: 'Synthetic account', mode: 'live',
  period: { preset: 'month', label: '本月', start_date: '2026-10-01', end_date: '2026-10-12', timezone: 'UTC', comparison_label: '与上月同期相比' },
  coverage: { complete: true, amounts_complete: true, classifications_complete: true, subscriptions_complete: true, payouts_complete: true, disputes_complete: true, funds_complete: true, attention_complete: true, reasons: [] },
  currencies: [row()], records: [record(), record('refund-1', { kind: 'refund', amount_minor: 10000, status: 'succeeded', category: null }), record('payout-1', { kind: 'payout', amount_minor: 50000, status: 'paid', category: null })],
  subscriptions: [{ id: 'sub-synthetic', customer_label: 'Synthetic subscriber', status: 'active', currency: 'USD', next_payment_at: '2026-11-01T12:00:00Z', amount_minor: 20000, source_url: 'https://dashboard.stripe.com/subscriptions/synthetic' }],
  attention: [{ id: 'attention-1', title: 'Synthetic attention', reason: 'Synthetic reason', source_url: 'https://dashboard.stripe.com/disputes/synthetic' }],
  balances: [{ currency: 'USD', available_minor: 25000, pending_minor: 15000, observed_at: '2026-10-12T07:00:00Z' }], ...extra,
});

// Execute real formatting, filtering and rendering against isolated synthetic
// reports. No Stripe account, browser, storage or external transport is used.
function fixture() {
  const modules = new Map(), context = vm.createContext({ URL, Intl, Date, console });
  function load(relative) {
    if (modules.has(relative)) return modules.get(relative);
    const path = resolve(root, relative), module = { exports: {} };
    const compiled = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const require = name => {
      if (name === 'react/jsx-runtime') return jsx;
      if (name === 'lucide-react') return new Proxy({}, { get: () => props => jsx.jsx('svg', props) });
      if (name.endsWith('.css')) return {};
      if (name === '@/lib/private-stripe-report') return load('lib/private-stripe-report.ts');
      if (name === './private-workspace-api') return load('lib/private-workspace-api.ts');
      if (name === './api') return { client: { apiCall: { invoke: () => { throw new Error('Rendering a Stripe report must not invoke transport'); } } } };
      throw new Error(`Unexpected module ${name}`);
    };
    vm.runInContext(`(function(require,module,exports){${compiled}\n})`, context, { filename: path })(require, module, module.exports);
    modules.set(relative, module.exports); return module.exports;
  }
  const helpers = load('lib/private-stripe-report.ts'), Component = load('pages/PrivateStripeDashboard.tsx').default;
  const textOf = node => typeof node === 'string' ? node : (node.children || []).map(textOf).join('');
  function expand(node) {
    if (node === null || node === undefined || typeof node === 'boolean') return [];
    if (Array.isArray(node)) return node.flatMap(expand);
    if (typeof node !== 'object') return [String(node)];
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return [{ ...node, children: expand(node.props?.children) }];
  }
  function render(extra = {}) {
    const events = [];
    const props = { report: report(), selection: helpers.createPrivateStripeSelection(new Date('2026-10-12T00:00:00Z')), loading: false, connected: true,
      onChangeSelection: next => events.push({ type: 'selection', value: next }), onRetry: () => events.push({ type: 'retry' }), onManageConnection: () => events.push({ type: 'manage' }), ...extra };
    const tree = expand(Component(props));
    const flatten = nodes => nodes.flatMap(node => typeof node === 'object' ? [node, ...flatten(node.children || [])] : []);
    const nodes = flatten(tree);
    return { nodes, text: tree.map(textOf).join('').replace(/\s/g, ' '), events, props, textOf, find: (type, label) => nodes.find(node => node.type === type && textOf(node).trim() === label) };
  }
  return { ...helpers, render };
}

test('Stripe report money preserves provider currency units and missing amounts stay unknown', () => {
  const f = fixture();
  assert.equal(f.privateStripeReportMoney(12345, 'USD').replace(/\s/g, ' '), 'USD 123.45');
  assert.equal(f.privateStripeReportMoney(500, 'JPY').replace(/\s/g, ' '), 'JPY 500');
  assert.equal(f.privateStripeReportMoney(12300, 'ISK').replace(/\s/g, ' '), 'ISK 123');
  for (const value of [null, undefined, '100', NaN, 0.1, Number.MAX_SAFE_INTEGER + 1]) assert.equal(f.privateStripeReportMoney(value, 'USD'), '待确认');
  assert.equal(f.privateStripeReportMoney(500, null), '待确认'); assert.equal(f.privateStripeReportMoney(1000, 'BHD'), '待确认');
  assert.equal(f.privateStripeReportMoney(0, 'USD').replace(/\s/g, ' '), 'USD 0.00');
});
test('period mismatch and invalid custom dates withhold stale reports', () => {
  const f = fixture(), selection = f.createPrivateStripeSelection(new Date('2026-10-12T00:00:00Z'));
  assert.ok(f.privateStripeReportForSelection(report(), selection));
  assert.equal(f.privateStripeReportForSelection(report(), { ...selection, preset: 'quarter' }), null);
  const custom = report({ period: { ...report().period, preset: 'custom' } });
  assert.equal(f.privateStripeReportForSelection(custom, { ...selection, preset: 'custom', end_date: '2026-10-11' }), null);
  assert.equal(f.privateStripeReportDate('2026-02-30'), false);
  assert.equal(f.privateStripeReportForSelection(report({ period: { ...report().period, start_date: '2026-02-30' } }), selection), null);
  assert.ok(f.render({ report: report(), selection: { ...selection, preset: 'quarter' } }).text.includes('数据待确认'));
});
test('backend computed totals and Chinese narrative are displayed independently of visible records', () => {
  const f = fixture(), screen = f.render({ report: report({ records: [record('unrelated-amount', { amount_minor: 999999 })] }) });
  assert.ok(screen.text.includes('USD 1,000.00')); assert.ok(screen.text.includes('USD 9,999.99'));
  assert.ok(screen.text.includes('本月已收款 USD 1,000.00，其中订阅收款 USD 700.00。'));
  assert.ok(screen.text.includes('成功退款USD 100.00')); assert.ok(screen.text.includes('收款扣退款USD 900.00')); assert.ok(screen.text.includes('Stripe 费用USD 31.00'));
  assert.ok(screen.text.includes('增加 25%')); assert.deepEqual(screen.events, []);
});
test('amount coverage and classification coverage remain independent and unsupported comparison stays unknown', () => {
  const f = fixture(), data = report({ state: 'partial', coverage: { complete: false, amounts_complete: true, classifications_complete: false, reasons: ['订阅关联读取尚未完整'] } });
  const screen = f.render({ report: data }); assert.ok(screen.text.includes('本月 · 已收款')); assert.ok(screen.text.includes('已识别订阅相关收款')); assert.ok(screen.text.includes('待分类收款'));
  assert.ok(screen.text.includes('数据范围尚未完整')); assert.ok(screen.text.includes('订阅关联读取尚未完整'));
  const observed = report({ state: 'partial', coverage: { complete: false, amounts_complete: false, classifications_complete: false, reasons: [] } });
  const partialScreen = f.render({ report: observed }); assert.ok(partialScreen.text.includes('本月 · 已读取收款')); assert.ok(partialScreen.text.includes('对比待确认')); assert.ok(!partialScreen.text.includes('增加 25%'));
});
test('loading, request errors and unavailable coverage never display a previous total or zero', () => {
  const f = fixture();
  for (const props of [{ loading: true }, { error: 'Synthetic failure' }, { report: report({ state: 'unavailable', coverage: { complete: false, reasons: ['范围未读取'] } }) }, { report: null }]) {
    const screen = f.render(props); assert.ok(!screen.text.includes('USD 1,000.00')); assert.ok(!screen.text.includes('USD 0.00'));
  }
  const error = f.render({ error: 'Synthetic failure' }); assert.ok(error.nodes.some(node => node.props?.role === 'alert')); error.find('button', '重新读取').props.onClick(); assert.deepEqual(error.events, [{ type: 'retry' }]);
});
test('known zero totals display zero while missing fees and net receipts remain unknown', () => {
  const f = fixture(), data = report({ currencies: [row({ gross_minor: 0, subscription_minor: 0, one_time_minor: 0, unclassified_minor: 0, refunds_minor: 0, net_receipts_minor: null, fees_minor: null, summary: ['本期未有已收款记录。'], comparison: { gross_minor: 0, change_pct: null, complete: true }, trend: [{ date: '2026-10-01', subscription_minor: 0, one_time_minor: 0, unclassified_minor: 0 }] })], records: [], attention: [] });
  const screen = f.render({ report: data }); assert.ok(screen.text.includes('USD 0.00')); assert.ok(screen.text.includes('Stripe 费用待确认')); assert.ok(screen.text.includes('收款扣退款待确认'));
  assert.ok(!screen.text.includes('待分类收款')); assert.ok(screen.text.includes('期间未有已收款')); assert.ok(screen.text.includes('对比待确认'));
});
test('separate currency selection never adds USD and JPY totals or mixes their records', () => {
  const f = fixture(), selection = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), currency: 'JPY' };
  const data = report({ currencies: [row(), row({ currency: 'JPY', gross_minor: 9000, subscription_minor: 9000, one_time_minor: 0, unclassified_minor: 0, refunds_minor: 0, net_receipts_minor: 9000, fees_minor: 100, summary: ['本月已收款 JPY 9,000。'] })], records: [record(), record('yen-payment', { currency: 'JPY', amount_minor: 9000 })] });
  const screen = f.render({ report: data, selection }); assert.ok(screen.text.includes('JPY 9,000')); assert.ok(!screen.text.includes('USD 1,000.00')); assert.ok(!screen.text.includes('Synthetic payment-1'));
  const missingCurrency = f.render({ report: data, selection: { ...selection, currency: 'EUR' } }); assert.ok(!missingCurrency.text.includes('USD 1,000.00')); assert.ok(!missingCurrency.text.includes('JPY 9,000'));
});
test('overview caps attention and recent rows and excludes payouts from income records', () => {
  const f = fixture(), data = report({ records: [record('fund-payout', { kind: 'payout', category: null }), ...Array.from({ length: 9 }, (_, index) => record(`visible-${index}`))], attention: Array.from({ length: 6 }, (_, index) => ({ id: `a-${index}`, title: `Synthetic attention ${index}`, reason: 'Reason', source_url: null })) });
  const screen = f.render({ report: data }); assert.equal(screen.nodes.filter(node => node.props?.className === 'ps-record-button').length, 5);
  assert.ok(screen.text.includes('Synthetic attention 2')); assert.ok(!screen.text.includes('Synthetic attention 3')); assert.ok(!screen.text.includes('fund-payout'));
});
test('tabs, filters and inline details are controlled and emit no navigation or financial requests', () => {
  const f = fixture(), screen = f.render();
  screen.find('button', '订阅').props.onClick(); assert.equal(screen.events.at(-1).value.tab, 'subscriptions');
  const paymentButton = screen.nodes.find(node => node.props?.className === 'ps-record-button'); paymentButton.props.onClick(); const next = screen.events.at(-1).value;
  assert.equal(next.expanded_record_id, 'payment-1'); assert.equal(next.tab, 'overview');
  const expanded = f.render({ selection: next }); assert.ok(expanded.text.includes('关联订阅sub-synthetic')); assert.ok(expanded.text.includes('关联账单in-synthetic'));
  expanded.find('button', '流水').props.onClick(); assert.equal(expanded.events.at(-1).value.expanded_record_id, 'payment-1');
  const records = f.render({ selection: { ...next, tab: 'records' } }); records.nodes.find(node => node.type === 'select' && node.props['aria-label'] === '收款流水分类').props.onChange({ target: { value: 'refund' } }); assert.equal(records.events.at(-1).value.filter, 'refund');
});
test('custom dates and currency changes preserve controlled navigation while clearing old details', () => {
  const f = fixture(), screen = f.render({ selection: { ...f.createPrivateStripeSelection(new Date('2026-10-12')), tab: 'funds', search: 'Synthetic', expanded_record_id: 'payment-1' } });
  screen.find('button', '自定义').props.onClick(); assert.equal(screen.events.at(-1).value.preset, 'custom'); assert.equal(screen.events.at(-1).value.tab, 'funds'); assert.equal(screen.events.at(-1).value.expanded_record_id, null);
  const invalid = f.render({ selection: { ...screen.events.at(-1).value, start_date: '2026-10-15', end_date: '2026-10-01' } }); assert.ok(invalid.text.includes('请选择有效的开始与结束日期')); assert.ok(!invalid.text.includes('USD 1,000.00'));
});
test('funds show current timestamped balances and payout events outside period income', () => {
  const f = fixture(), data = report({ records: [record('negative-payout', { kind: 'payout', status: 'paid', amount_minor: -70000, category: null }), record('adjustment', { kind: 'adjustment', amount_minor: 10000, category: null }), record()] });
  const selection = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), tab: 'funds', expanded_record_id: 'negative-payout' };
  const screen = f.render({ report: data, selection }); assert.ok(screen.text.includes('当前快照')); assert.ok(screen.text.includes('可用余额USD 250.00')); assert.ok(screen.text.includes('待结算余额USD 150.00'));
  assert.ok(screen.text.includes('Stripe 已支付 · 银行待核对')); assert.ok(screen.text.includes('-USD 700.00')); assert.ok(screen.text.includes('其他资金变动')); assert.ok(screen.text.includes('提现不计入收入'));
  assert.ok(!screen.text.includes('USD 1,000.00')); assert.ok(!screen.text.includes('Synthetic payment-1'));
});
test('provider lowercase balances, subscriptions, plans, payouts and disputes stay visible with uppercase summary selection', () => {
  const f = fixture(), initial = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), currency: 'USD' };
  // Match provider/service output: income summary uppercase, other rows lower.
  const data = report({
    balances: [{ currency: 'usd', available_minor: 1234, pending_minor: 5678, observed_at: '2026-10-12T07:00:00Z' }],
    subscriptions: [{ id: 'sub-provider', customer_label: 'Provider subscriber', status: 'active', currency: 'usd', next_payment_at: null, amount_minor: null, source_url: null, period_end: '2026-11-01T12:00:00Z', plans: [{ label: 'Provider plan', amount_minor: 9876, currency: 'usd', quantity: 1, interval: 'month', interval_count: 1 }] }],
    records: [record('provider-payout', { title: 'Provider payout', kind: 'payout', category: null, currency: 'usd', amount_minor: -12500, status: 'paid' }), record('provider-dispute', { title: 'Provider dispute', kind: 'dispute', category: null, currency: 'usd', amount_minor: 5800, status: 'needs_response' })],
  });
  const funds = f.render({ report: data, selection: { ...initial, tab: 'funds' } });
  assert.ok(funds.text.includes('可用余额USD 12.34')); assert.ok(funds.text.includes('待结算余额USD 56.78'));
  assert.ok(funds.text.includes('Provider payout')); assert.ok(funds.text.includes('-USD 125.00'));
  assert.ok(!funds.text.includes('当前余额待确认')); assert.ok(!funds.text.includes('Provider dispute'));
  const subscriptions = f.render({ report: data, selection: { ...initial, tab: 'subscriptions', expanded_subscription_id: 'sub-provider' } });
  assert.ok(subscriptions.text.includes('Provider subscriber')); assert.ok(subscriptions.text.includes('Provider plan · USD 98.76 / 每月'));
  assert.ok(!subscriptions.text.includes('当前没有可查看的订阅'));
  const disputes = f.render({ report: data, selection: { ...initial, tab: 'records', filter: 'dispute' } });
  assert.ok(disputes.text.includes('Provider dispute')); assert.ok(disputes.text.includes('USD 58.00'));
  assert.ok(!disputes.text.includes('所选期间暂无此类流水')); assert.ok(!disputes.text.includes('Provider payout'));
});
test('selection boundary normalizes mixed ASCII currency copies without mutating reports or amounts', () => {
  const f = fixture(), selection = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), currency: 'JPY' };
  const data = report({ currencies: [row({ currency: 'uSd' }), row({ currency: 'jpy', gross_minor: 500 })],
    records: [record('mixed-dollar', { currency: 'uSd', amount_minor: null }), record('mixed-yen', { currency: 'jPy', amount_minor: -500 })],
    balances: [{ currency: 'jpy', available_minor: 0, pending_minor: null, observed_at: null }],
    subscriptions: [{ id: 'sub-mixed', customer_label: null, status: 'active', currency: 'jPy', next_payment_at: null, amount_minor: null, source_url: null, plans: [{ label: 'Mixed yen plan', currency: 'jpY', amount_minor: 500, quantity: 1, interval: 'month', interval_count: 1 }] }],
  });
  const original = JSON.stringify(data);
  function freeze(value) { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } }
  freeze(data);
  const normalized = f.privateStripeReportForSelection(data, selection);
  assert.notStrictEqual(normalized, data); assert.notStrictEqual(normalized.balances[0], data.balances[0]);
  assert.notStrictEqual(normalized.subscriptions[0].plans[0], data.subscriptions[0].plans[0]);
  assert.equal(normalized.currencies[0].currency, 'USD'); assert.equal(normalized.currencies[1].currency, 'JPY');
  assert.equal(normalized.records[0].currency, 'USD'); assert.equal(normalized.records[1].currency, 'JPY');
  assert.equal(normalized.balances[0].currency, 'JPY'); assert.equal(normalized.subscriptions[0].currency, 'JPY');
  assert.equal(normalized.subscriptions[0].plans[0].currency, 'JPY');
  assert.equal(normalized.records[0].amount_minor, null); assert.equal(normalized.records[1].amount_minor, -500);
  assert.equal(normalized.balances[0].available_minor, 0); assert.equal(normalized.balances[0].pending_minor, null);
  assert.strictEqual(normalized.coverage, data.coverage); assert.strictEqual(normalized.currencies[0].trend, data.currencies[0].trend);
  assert.equal(JSON.stringify(data), original);
  assert.equal(f.privateStripeReportRecords(normalized, selection).length, 1);
  assert.equal(f.privateStripeReportRecords(normalized, selection)[0].id, 'mixed-yen');
  assert.equal(f.privateStripeReportMoney(normalized.records[1].amount_minor, normalized.records[1].currency).replace(/\s/g, ' '), '-JPY 500');
});
test('currency normalization rejects whitespace, non-ASCII, malformed and non-string codes across all views', () => {
  const f = fixture(), selection = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), currency: 'USD' };
  const invalid = [' usd', 'usd ', 'usd\n', 'USD\n', 'usd\r', 'u$d', 'US', 'USDD', 'ＵＳＤ', 'uſd', null, 123];
  const data = report({ currencies: [row({ currency: 'usd' }), ...invalid.map(currency => row({ currency }))],
    balances: invalid.map(currency => ({ currency, available_minor: 999999, pending_minor: 999999, observed_at: null })),
    records: invalid.map((currency, index) => record(`invalid-${index}`, { currency })),
    subscriptions: invalid.map((currency, index) => ({ id: `invalid-sub-${index}`, customer_label: 'Invalid currency subscriber', status: 'active', currency, next_payment_at: null, amount_minor: 999999, source_url: null })),
  });
  const normalized = f.privateStripeReportForSelection(data, selection);
  invalid.forEach((currency, index) => assert.equal(normalized.balances[index].currency, currency));
  assert.equal(f.privateStripeReportCurrencies(normalized).length, 1);
  assert.equal(f.privateStripeReportRecords(normalized, selection).length, 0);
  assert.equal(f.privateStripeReportSubscriptions(normalized, selection).length, 0);
  const funds = f.render({ report: data, selection: { ...selection, tab: 'funds' } });
  assert.ok(funds.text.includes('当前余额待确认')); assert.ok(!funds.text.includes('9,999.99'));
  assert.equal(funds.nodes.filter(node => node.type === 'option' && node.props.value === 'USD').length, 1);
  assert.equal(f.privateStripeReportMoney(500, 'usd'), '待确认');
});
test('subscription amounts remain source amounts and pending collection never becomes actual income', () => {
  const f = fixture(), selection = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), tab: 'subscriptions', expanded_subscription_id: 'sub-synthetic' };
  const screen = f.render({ selection }); assert.ok(screen.text.includes('来源订阅金额')); assert.ok(screen.text.includes('实际收款以期间已收款记录为准')); assert.ok(screen.text.includes('下次付款'));
  assert.ok(!screen.text.includes('MRR')); assert.ok(!screen.text.includes('USD 1,000.00'));
});
test('source links allow only exact approved Stripe HTTPS host without credentials or alternate ports', () => {
  const f = fixture();
  for (const url of ['javascript:alert(1)', 'https://dashboard.stripe.com.evil.example/payments/id', 'http://dashboard.stripe.com/payments/id', 'https://attacker@dashboard.stripe.com/payments/id', 'https://dashboard.stripe.com:444/payments/id']) assert.equal(f.privateStripeReportSourceUrl(url), null);
  assert.ok(f.privateStripeReportSourceUrl('https://dashboard.stripe.com/payments/id'));
  const data = report({ records: [record('unsafe', { source_url: 'https://evil.example/stripe' })], attention: [] });
  const screen = f.render({ report: data, selection: { ...f.createPrivateStripeSelection(new Date('2026-10-12')), expanded_record_id: 'unsafe' } }); assert.equal(screen.nodes.filter(node => node.type === 'a').length, 0);
});
test('incomplete trend points are withheld instead of filling missing values with zero', () => {
  const f = fixture(), data = report({ currencies: [row({ trend: [{ date: '2026-10-01', subscription_minor: null, one_time_minor: 1000, unclassified_minor: 0 }] })] });
  const screen = f.render({ report: data }); assert.ok(screen.text.includes('趋势数据待确认')); assert.ok(!screen.text.includes('期间未有已收款'));
});
test('Chinese financial evidence stays visible in expanded provider records', () => {
  const f = fixture(), data = report({ records: [record('chinese-details', { details: { 统计依据: 'Stripe 资金流水发生时间', 分类依据: '关联订阅账单', 手续费: 'USD 2.50', 资金净变动: 'USD 97.50', 来源编号: 'ch-synthetic', 流水编号: 'txn-synthetic', 原支付币种: 'USD', 收款核对: '已核对' } })] });
  const screen = f.render({ report: data, selection: { ...f.createPrivateStripeSelection(new Date('2026-10-12')), expanded_record_id: 'chinese-details' } });
  assert.ok(screen.text.includes('分类依据关联订阅账单')); assert.ok(screen.text.includes('手续费USD 2.50')); assert.ok(screen.text.includes('资金净变动USD 97.50')); assert.ok(screen.text.includes('流水编号txn-synthetic'));
});
test('subscription plans are inspectable standard prices and never promised as the next invoice', () => {
  const f = fixture(), data = report({ subscriptions: [{ id: 'sub-synthetic', customer_label: 'Synthetic subscriber', status: 'active', currency: 'USD', next_payment_at: null, amount_minor: null, source_url: null, period_end: '2026-11-01T12:00:00Z', cancel_at_period_end: true, plans: [{ label: 'Synthetic standard plan', amount_minor: 20000, currency: 'USD', quantity: 2, interval: 'month', interval_count: 1 }] }] });
  const screen = f.render({ report: data, selection: { ...f.createPrivateStripeSelection(new Date('2026-10-12')), tab: 'subscriptions', expanded_subscription_id: 'sub-synthetic' } });
  assert.ok(screen.text.includes('周期截止')); assert.ok(screen.text.includes('周期结束后取消')); assert.ok(screen.text.includes('标准价格')); assert.ok(screen.text.includes('USD 200.00 / 每月 · 数量 2')); assert.ok(screen.text.includes('不代表下次账单金额')); assert.ok(screen.text.includes('下次付款待确认'));
});
test('empty subscriptions require subscription inventory coverage independently of receipt classification', () => {
  const f = fixture(), selection = { ...f.createPrivateStripeSelection(new Date('2026-10-12')), tab: 'subscriptions' };
  const unknown = f.render({ report: report({ subscriptions: [], coverage: { complete: true, amounts_complete: true, classifications_complete: true, subscriptions_complete: false, reasons: [] } }), selection }); assert.ok(unknown.text.includes('订阅数据待确认')); assert.ok(!unknown.text.includes('当前没有可查看的订阅'));
  const known = f.render({ report: report({ subscriptions: [], coverage: { complete: true, subscriptions_complete: true, reasons: [] } }), selection }); assert.ok(known.text.includes('当前没有可查看的订阅'));
});
test('incomplete secondary resources never imply absence despite complete income coverage', () => {
  const f = fixture(), initial = f.createPrivateStripeSelection(new Date('2026-10-12'));
  const data = report({ records: [], subscriptions: [], attention: [], coverage: { ...report().coverage, funds_complete: false, disputes_complete: false, subscriptions_complete: false, attention_complete: false } });
  const funds = f.render({ report: data, selection: { ...initial, tab: 'funds' } }); assert.ok(funds.text.includes('资金记录读取尚未完整')); assert.ok(funds.text.includes('资金记录待确认')); assert.ok(!funds.text.includes('暂无提现'));
  const disputes = f.render({ report: data, selection: { ...initial, tab: 'records', filter: 'dispute' } }); assert.ok(disputes.text.includes('争议读取尚未完整')); assert.ok(disputes.text.includes('流水待确认')); assert.ok(!disputes.text.includes('暂无此类流水'));
  const overview = f.render({ report: data }); assert.ok(overview.text.includes('当前处理项尚未读取完整')); assert.ok(!overview.text.includes('暂无收款、退款或争议记录'));
});
test('empty incomplete reads withhold derived zero metrics and zero narrative', () => {
  const f = fixture(), data = report({ state: 'partial', coverage: { ...report().coverage, complete: false, amounts_complete: false, classifications_complete: false }, currencies: [row({ gross_minor: 0, subscription_minor: 0, one_time_minor: 0, unclassified_minor: 0, refunds_minor: 0, net_receipts_minor: 0, fees_minor: 0, summary: ['已读取范围内成功收款 USD 0.00。'], trend: [] })], records: [], attention: [] });
  const screen = f.render({ report: data }); assert.ok(!screen.text.includes('USD 0.00')); assert.ok(screen.text.includes('已读取收款')); assert.ok(screen.text.includes('Stripe 费用待确认')); assert.ok(screen.text.includes('趋势数据待确认')); assert.ok(!screen.text.includes('期间未有已收款'));
});
