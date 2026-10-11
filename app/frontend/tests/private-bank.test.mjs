import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import * as jsx from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const bankNow = Date.parse('2026-10-11T02:00:00Z');
function fixture() {
  const modules = new Map(); const requests = []; let tab = 'posted';
  const react = { useState: initial => [tab || initial, next => { tab = next; }] };
  function load(relative) {
    if (modules.has(relative)) return modules.get(relative);
    const filename = resolve(root, relative);
    const source = ts.transpileModule(readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const module = { exports: {} };
    const require = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return jsx;
      if (name === 'lucide-react') return new Proxy({}, { get: () => props => jsx.jsx('svg', props) });
      if (['@/lib/private-bank', './private-bank'].includes(name)) return load('lib/private-bank.ts');
      if (['@/lib/private-workspace-api', './private-workspace-api'].includes(name)) return load('lib/private-workspace-api.ts');
      if (name.endsWith('.css')) return {};
      if (name === './api') return { client: { apiCall: { invoke: async request => { requests.push(request); return { data: {} }; } } } };
      throw new Error(`Unexpected synthetic dependency ${name}`);
    };
    vm.runInNewContext(`(function(require,module,exports){${source}\n})`, { Date, Intl, URL, URLSearchParams })(require, module, module.exports);
    modules.set(relative, module.exports); return module.exports;
  }
  const helper = load('lib/private-bank.ts'); const api = load('lib/private-workspace-api.ts'); const components = load('pages/PrivateBankDashboard.tsx');
  function render(props = {}, detail = false) {
    const events = [];
    const defaults = { source: bankSource(), items: [bankItem()], total: 1, loading: false, now: bankNow, onConnect: () => events.push('connect'), onRefresh: () => events.push('refresh'), onSync: () => events.push('sync'), onSelect: item => events.push(item.id) };
    const element = detail ? components.PrivateBankDetail({ item: bankItem(), source: bankSource(), now: bankNow, ...props }) : components.default({ ...defaults, ...props });
    const expand = node => node == null || typeof node === 'boolean' ? [] : Array.isArray(node) ? node.flatMap(expand) : typeof node !== 'object' ? [String(node)] : typeof node.type === 'function' ? expand(node.type(node.props)) : [{ ...node, children: expand(node.props?.children) }];
    const nodes = expand(element); const all = tree => tree.flatMap(node => typeof node === 'object' ? [node, ...all(node.children || [])] : []);
    const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
    return { events, nodes: all(nodes), text: nodes.map(text).join('').replace(/\s/g, ' '), markup: () => renderToStaticMarkup(element), textOf: node => text(node).replace(/\s/g, ' '), button: label => all(nodes).find(node => node.type === 'button' && text(node) === label) };
  }
  return { ...helper, api, render, requests };
}
const bankAccount = (extra = {}) => ({ account_id: 'account-synthetic', name: 'Synthetic checking', mask: '1234', type: 'depository', subtype: 'checking', currency: 'USD', unofficial_currency: null, current_minor: 125000, available_minor: 120000, limit_minor: null, balance_kind: 'funds', balance_source: 'cached_accounts_get', balance_updated_at: '2026-10-11T00:30:00Z', ...extra });
const bankSource = (extra = {}) => ({ id: 'bofa_bank', name: 'Bank of America', status: 'connected', capabilities: [], missing_configuration: [], error: null, last_sync: '2026-10-11T01:00:00Z', metadata: {
  bank_item_id: 'item-synthetic', bank_environment: 'production', bank_institution_id: 'ins-synthetic', bank_institution_name: 'Bank of America', bank_accounts: [bankAccount()],
  bank_snapshot: { id: 'snapshot-synthetic', observed_at: '2026-10-11T01:00:00Z', item_id: 'item-synthetic', environment: 'production', institution_id: 'ins-synthetic', accounts_complete: true, transactions_complete: true, pagination_complete: true, transaction_update_status: 'HISTORICAL_UPDATE_COMPLETE', bank_updated_at: '2026-10-11T00:30:00Z', balance_realtime: false },
}, ...extra });
const bankItem = (extra = {}) => ({ id: 'tx-synthetic', source_id: 'bofa_bank', kind: 'bank_transaction', title: 'Synthetic bank transfer', summary: '', status: 'posted', priority: 'normal', amount_minor: 25000, currency: 'USD', occurred_at: '2026-10-10T00:00:00Z', due_at: null, source_url: 'https://secure.bankofamerica.com/', action_status: 'open', snoozed_until: null, evidence: {
  bank_item_id: 'item-synthetic', bank_environment: 'production', bank_institution_id: 'ins-synthetic', bank_account_id: 'account-synthetic', bank_account_mask: '1234', bank_transaction_id: 'tx-provider-synthetic', bank_snapshot_id: 'snapshot-synthetic', bank_observed_at: '2026-10-11T01:00:00Z', pending: false, amount_direction: 'inflow', accounting_effect: 'none', transaction_date: '2026-10-10',
}, ...extra });

// Isolated synthetic module execution: no browser, bank account, credentials or external transport.
test('bank snapshot validates current Item, environment, institution and cached account provenance', () => {
  const f = fixture(); const source = bankSource(); assert.equal(f.currentBankCondition(source, bankNow).state, 'fresh'); assert.equal(f.currentBankCondition(source, bankNow).accounts.length, 1);
  for (const changes of [{ bank_item_id: 'other' }, { bank_environment: 'sandbox' }, { bank_institution_id: 'other' }, { bank_snapshot: { ...source.metadata.bank_snapshot, balance_realtime: true } }, { bank_snapshot: { ...source.metadata.bank_snapshot, accounts_complete: false } }, { bank_snapshot: { ...source.metadata.bank_snapshot, observed_at: 'bad-time' } }, { bank_accounts: [bankAccount({ balance_source: 'unknown' })] }]) {
    const invalid = f.currentBankCondition({ ...source, metadata: { ...source.metadata, ...changes } }, bankNow); assert.equal(invalid.state, 'unverified'); assert.equal(invalid.accounts.length, 0);
  }
  assert.equal(f.currentBankCondition({ ...source, status: 'disconnected' }, bankNow).accounts.length, 0);
});
test('cached bank balance freshness downgrades after a day or source failure without inventing a live balance', () => {
  const f = fixture(); assert.equal(f.currentBankCondition(bankSource(), bankNow + 24 * 60 * 60_000).state, 'stale');
  assert.equal(f.currentBankCondition(bankSource({ status: 'error' }), bankNow).state, 'stale'); assert.equal(f.currentBankCondition(bankSource({ error: 'Sync failed' }), bankNow).state, 'stale');
  assert.ok(f.currentBankCondition(bankSource(), bankNow).label.includes('缓存')); assert.ok(!f.currentBankCondition(bankSource(), bankNow).label.includes('实时'));
});
test('bank missing values remain pending while deposits and credit debts have distinct labels', () => {
  const f = fixture(); const missing = f.privateBankAccountLabels(bankAccount({ available_minor: null })); assert.equal(missing.primaryAmount, '待提供');
  const deposit = f.privateBankAccountLabels(bankAccount()); assert.equal(deposit.primaryLabel, '可用余额'); assert.equal(deposit.secondaryLabel, '当前余额');
  const credit = f.privateBankAccountLabels(bankAccount({ type: 'credit', balance_kind: 'owed', current_minor: 50000, available_minor: 200000, limit_minor: 250000 })); assert.equal(credit.primaryLabel, '当前欠款'); assert.equal(credit.secondaryLabel, '可用额度'); assert.equal(credit.primaryAmount.replace(/\s/g, ' '), 'USD 500.00');
  assert.equal(f.privateBankAccountLabels(bankAccount({ type: 'credit', balance_kind: 'funds' })).primaryLabel, '当前欠款');
  for (const value of [null, undefined, '1000', 0.1, Number.MAX_SAFE_INTEGER + 1]) assert.equal(f.privateBankMoney(value, 'USD'), '待提供');
});
test('bank money preserves currency units without combining USD and another account currency', () => {
  const f = fixture(); assert.equal(f.privateBankMoney(12345, 'USD').replace(/\s/g, ' '), 'USD 123.45'); assert.equal(f.privateBankMoney(500, 'JPY').replace(/\s/g, ' '), 'JPY 500');
  const source = bankSource(); source.metadata.bank_accounts.push(bankAccount({ account_id: 'account-yen', name: 'Synthetic Yen', currency: 'JPY', current_minor: 100000, available_minor: 90000 }));
  const screen = f.render({ source }); assert.ok(screen.text.includes('USD 1,200.00')); assert.ok(screen.text.includes('JPY 90,000')); assert.ok(!screen.text.includes('合计'));
});
test('bank incremental history may use a prior snapshot but requires the current bound account and source identity', () => {
  const f = fixture(); const item = bankItem(); item.evidence.bank_snapshot_id = 'earlier-snapshot'; item.evidence.bank_observed_at = '2026-10-10T01:00:00Z'; assert.equal(f.privateBankRecord(item, bankSource(), bankNow).current, true);
  for (const changes of [{ bank_item_id: 'other' }, { bank_environment: 'sandbox' }, { bank_institution_id: 'other' }, { bank_account_id: 'other' }, { bank_snapshot_id: '' }, { bank_observed_at: 'invalid-time' }, { pending: true }]) { const row = f.privateBankRecord({ ...item, evidence: { ...item.evidence, ...changes } }, bankSource(), bankNow); assert.equal(row.current, false); assert.equal(row.amount, '待提供'); }
});
test('bank posted and pending records do not treat replacement or removal as current visible transactions', () => {
  const f = fixture(); const pending = bankItem({ id: 'pending', status: 'pending' }); pending.evidence.pending = true;
  assert.equal(f.privateBankRecords([bankItem(), pending, bankItem({ status: 'removed' }), bankItem({ status: 'replaced' })], bankSource(), bankNow).length, 2); assert.equal(f.privateBankRecord(pending, bankSource(), bankNow).stateLabel, '待入账');
});
test('bank signed transfer direction is preserved and requires matching provider evidence', () => {
  const f = fixture(); const inbound = f.privateBankRecord(bankItem(), bankSource(), bankNow); assert.equal(inbound.amountPrefix, '+'); assert.equal(inbound.directionLabel, '转入');
  const outboundItem = bankItem({ amount_minor: -25000 }); outboundItem.evidence.amount_direction = 'outflow'; const outbound = f.privateBankRecord(outboundItem, bankSource(), bankNow); assert.equal(outbound.amountPrefix, '−'); assert.equal(outbound.directionLabel, '转出');
  const mismatched = f.privateBankRecord(bankItem({ amount_minor: -25000 }), bankSource(), bankNow); assert.equal(mismatched.direction, 'unknown'); assert.equal(mismatched.amount, '待提供'); assert.ok(!Object.hasOwn(inbound, 'income') && !Object.hasOwn(outbound, 'expense'));
});
test('bank unsupported currency and missing amount do not become zero; malformed source date is withheld', () => {
  const f = fixture(); assert.equal(f.privateBankRecord(bankItem({ amount_minor: null, currency: null }), bankSource(), bankNow).amount, '待提供');
  const invalid = bankItem(); invalid.evidence.transaction_date = '2026-02-30'; assert.equal(f.privateBankRecord(invalid, bankSource(), bankNow).date, null);
});
test('bank dashboard folds source details and per-account times, invokes nothing while rendering', () => {
  const f = fixture(); const screen = f.render(); assert.deepEqual(screen.events, []); assert.ok(screen.text.includes('银行缓存余额'));
  const details = screen.nodes.filter(node => node.type === 'details'); assert.ok(details.length >= 2); assert.ok(details.every(node => node.props.open === undefined)); screen.nodes.find(node => node.type === 'button' && node.props.className === 'pw-bank-record').props.onClick(); assert.deepEqual(screen.events, ['tx-synthetic']);
});
test('bank dashboard shows visible cached balances and every sandbox amount is labeled non-real', () => {
  const f = fixture(); const source = bankSource(); source.metadata.bank_environment = 'sandbox'; source.metadata.bank_snapshot.environment = 'sandbox'; const item = bankItem(); item.evidence.bank_environment = 'sandbox';
  const screen = f.render({ source, items: [item] }); assert.ok(screen.text.includes('银行测试数据')); assert.ok(screen.text.includes('Sandbox · 非真实余额与流水'));
});
test('bank account or snapshot failures hide amounts and preserve an explicit safe connect action', () => {
  const f = fixture(); const screen = f.render({ source: bankSource({ status: 'disconnected', metadata: {} }) }); assert.ok(!screen.text.includes('USD')); assert.ok(!screen.text.includes('已入账0')); assert.ok(!screen.text.includes('待入账0')); assert.ok(screen.text.includes('授权并同步后查看银行数据')); screen.button('安全连接').props.onClick(); assert.deepEqual(screen.events, ['connect']);
});
test('unconfigured bank setup cannot launch authorization or imply a connected account or zero balance', () => {
  const f = fixture();
  for (const source of [bankSource({ status: 'not_configured', metadata: {} }), ...['disconnected', 'connecting', 'error'].map(status => bankSource({ status, missing_configuration: ['PRIVATE_WORKSPACE_PLAID_ENABLED'], metadata: {} }))]) {
    const screen = f.render({ source, items: [], total: 0 });
    assert.ok(screen.text.includes('接入配置尚未完成'));
    assert.ok(screen.text.includes('配置完成后，才能安全授权并读取真实账户数据。'));
    const disabled = screen.button('待完成配置'); assert.equal(disabled.props.disabled, true);
    disabled.props.onClick(); assert.deepEqual(screen.events, []);
    assert.equal(screen.button('安全连接'), undefined); assert.equal(screen.button('继续授权'), undefined);
    assert.equal(screen.button('连接 Bank of America'), undefined); assert.equal(screen.button('同步'), undefined);
    assert.ok(!screen.text.includes('已安全连接') && !screen.text.includes('USD') && !screen.text.includes('已入账0') && !screen.text.includes('待入账0'));
    assert.deepEqual(f.requests, []);
  }
});
test('a connected bank with missing configuration keeps management available without enabling sync or claiming current access', () => {
  const f = fixture(); const screen = f.render({ source: bankSource({ missing_configuration: ['PRIVATE_WORKSPACE_PLAID_SECRET'] }) });
  assert.ok(screen.text.includes('接入配置尚未完成')); assert.ok(!screen.text.includes('已安全连接'));
  assert.equal(screen.button('同步'), undefined);
  const manage = screen.button('管理接入'); assert.equal(manage.props.disabled, false); manage.props.onClick();
  assert.deepEqual(screen.events, ['connect']); assert.deepEqual(f.requests, []);
  assert.ok(screen.text.includes('银行缓存余额') && screen.text.includes('USD 1,200.00'));
});
test('missing bank source and busy configured connection cannot dispatch source actions', () => {
  const f = fixture(); const unknown = f.render({ source: undefined, items: [], total: 0 });
  assert.ok(unknown.text.includes('接入状态待确认')); const disabled = unknown.button('状态待确认'); assert.equal(disabled.props.disabled, true);
  disabled.props.onClick(); assert.deepEqual(unknown.events, []); assert.equal(unknown.button('连接 Bank of America'), undefined); assert.equal(unknown.button('同步'), undefined);
  for (const source of [bankSource({ status: 'disconnected', metadata: {} }), bankSource({ status: 'connecting', metadata: {} }), bankSource()]) {
    const screen = f.render({ source, busy: true });
    const actions = screen.nodes.filter(node => node.type === 'button' && ['安全连接', '继续授权', '连接 Bank of America', '管理接入', '同步'].includes(screen.textOf(node)));
    assert.ok(actions.length > 0); for (const action of actions) { assert.equal(action.props.disabled, true); action.props.onClick(); }
    assert.deepEqual(screen.events, []);
  }
});
test('bank ledger tabs separate pending from posted and actions need explicit clicks', () => {
  const f = fixture(); const pending = bankItem({ id: 'tx-pending', title: 'Synthetic pending transfer', status: 'pending' }); pending.evidence.pending = true; const before = f.render({ items: [bankItem(), pending], total: 2 }); assert.ok(before.text.includes('Synthetic bank transfer')); assert.ok(!before.text.includes('Synthetic pending transfer'));
  before.button('待入账1').props.onClick(); const after = f.render({ items: [bankItem(), pending], total: 2 }); assert.ok(!after.text.includes('Synthetic bank transfer')); assert.ok(after.text.includes('Synthetic pending transfer')); assert.deepEqual(after.events, []); after.button('同步').props.onClick(); assert.deepEqual(after.events, ['sync']);
});
test('bank historical sync readiness cannot become a claim of no transactions', () => {
  const f = fixture(); const source = bankSource(); source.metadata.bank_snapshot.transactions_complete = false; source.metadata.bank_snapshot.transaction_update_status = 'INITIAL_UPDATE_COMPLETE'; const screen = f.render({ source, items: [], total: 0 }); assert.ok(screen.text.includes('近期流水已就绪，历史流水仍在准备。')); assert.ok(screen.text.includes('尚无可查看')); assert.ok(!screen.text.includes('当前同步记录中没有'));
});
test('bank UI escape source HTML and strips unapproved source URLs', () => {
  const f = fixture(); const item = bankItem({ title: '<script>steal()</script>', source_url: 'https://secure.bankofamerica.com.evil.example/' }); assert.ok(!f.render({ item }, true).markup().includes('https://secure.bankofamerica.com.evil.example')); const screen = f.render({ items: [item] }); assert.ok(screen.markup().includes('&lt;script&gt;steal()&lt;/script&gt;')); assert.deepEqual(screen.events, []);
});
test('bank detail keeps source evidence folded and does not write tasks, financial data or invoke AI', () => {
  const f = fixture(); const detail = f.render({}, true); assert.ok(detail.text.includes('已入账 · 转入')); assert.ok(detail.text.includes('+USD 250.00')); assert.ok(detail.text.includes('不写入 CRM 账目')); assert.equal(detail.nodes.find(node => node.type === 'details' && node.props.className === 'pw-bank-detail-evidence').props.open, undefined); assert.deepEqual(f.requests, []); assert.deepEqual(detail.events, []);
});
test('bank loading and failure are explicit and neither auto-retries nor displays false zero transactions', () => {
  const f = fixture(); const loading = f.render({ loading: true }); assert.ok(loading.text.includes('正在读取流水')); assert.deepEqual(loading.events, []); const failed = f.render({ error: 'Synthetic unavailable' }); assert.ok(failed.text.includes('Synthetic unavailable')); assert.deepEqual(failed.events, []); failed.button('重新读取').props.onClick(); assert.deepEqual(failed.events, ['refresh']);
});
test('bank start and completion use private owner endpoints and only send the opaque session identifier', async () => {
  const f = fixture(); await f.api.privateWorkspaceApi.bankLinkStart(); await f.api.privateWorkspaceApi.bankLinkComplete('synthetic-session'); assert.equal(f.requests[0].method, 'POST'); assert.equal(f.requests[0].url, '/api/v1/private-workspace/bank/link/start'); assert.equal(f.requests[0].data, undefined); assert.equal(f.requests[0].options.timeout, 95_000); assert.equal(f.requests[1].options.timeout, 95_000); assert.equal(f.requests[1].url, '/api/v1/private-workspace/bank/link/complete'); assert.deepEqual(Object.keys(f.requests[1].data), ['session_id']); assert.equal(f.requests[1].data.session_id, 'synthetic-session');
});
test('bank Hosted Link opens only the exact approved HTTPS Plaid origin and hosted path', () => {
  const f = fixture(); const safe = 'https://secure.plaid.com/hl/synthetic-session'; assert.equal(f.api.verifiedBankAuthorizationUrl(safe), safe); for (const value of ['javascript:alert(1)', 'http://secure.plaid.com/hl/session', 'https://secure.plaid.com.evil.example/hl/session', 'https://secure.plaid.com:444/hl/session', 'https://user:pass@secure.plaid.com/hl/session', 'https://secure.plaid.com/other/session', 'https://secure.plaid.com/hl/']) assert.equal(f.api.verifiedBankAuthorizationUrl(value), null); assert.equal(f.api.verifiedPrivateAuthorizationUrl('bofa_bank', 'https://accounts.google.com/o/oauth2/v2/auth'), null);
});
