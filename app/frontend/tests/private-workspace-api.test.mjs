import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the actual API module with an isolated transport. No browser, account,
// storage, or external network is used by these regressions.
const file = resolve(dirname(fileURLToPath(import.meta.url)), '../src/lib/private-workspace-api.ts');
const source = ts.transpileModule(readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function fixture(handler = () => { throw new Error('Unexpected synthetic request'); }) {
  const requests = [];
  const module = { exports: {} };
  const context = vm.createContext({ URL, URLSearchParams, Intl });
  const require = name => {
    assert.equal(name, './api');
    return { client: { apiCall: { invoke: async request => {
      requests.push(request);
      return { data: await handler(request) };
    } } } };
  };
  vm.runInContext(`(function(require,module,exports){${source}\n})`, context, { filename: file })(require, module, module.exports);
  return { api: module.exports, requests };
}

const { api } = fixture();
const amount = (minor, currency, sourceId) => api.formatPrivateAmount(minor, currency, sourceId).replace(/\s/g, ' ');

test('boss summary reads are local and explicit interpretation sends only the selected period and snapshot', async () => {
  const f = fixture(() => ({ period: 'last7days', snapshot_id: 'synthetic-current' }));
  await f.api.privateWorkspaceApi.brief('last7days');
  await f.api.privateWorkspaceApi.explainBrief('last7days', 'synthetic-current');
  assert.equal(f.requests[0].url, '/api/v1/private-workspace/brief?period=last7days');
  assert.equal(f.requests[0].method, 'GET'); assert.equal(f.requests[0].data, undefined);
  assert.equal(f.requests[1].url, '/api/v1/private-workspace/brief/explain'); assert.equal(f.requests[1].method, 'POST');
  assert.equal(f.requests[1].data.period, 'last7days'); assert.equal(f.requests[1].data.snapshot_id, 'synthetic-current');
  assert.deepEqual(Object.keys(f.requests[1].data).sort(), ['period', 'snapshot_id']); assert.equal(f.requests[1].options.timeout, 65_000);
});

// Fixed major-unit expectations from https://docs.stripe.com/currencies.
// In particular, Stripe ISK/UGX 500 means 5, and HUF/TWD payout amounts retain /100.
for (const [currency, minor, expected] of [
  ['USD', 26394, 'USD 263.94'],
  ['JPY', 500, 'JPY 500'],
  ['ISK', 500, 'ISK 5'],
  ['UGX', 500, 'UGX 5'],
  ['HUF', 1000, 'HUF 10.00'],
  ['HUF', 1045, 'HUF 10.45'],
  ['TWD', 80000, 'TWD 800.00'],
  ['TWD', 80045, 'TWD 800.45'],
  ['MGA', 500, 'MGA 500'],
]) {
  test(`Stripe ${currency} ${minor} preserves provider minor units`, () => {
    assert.equal(amount(minor, currency, 'stripe'), expected);
  });
}

test('manual default retains ISO units and unverified Stripe three-decimal units stay unconfirmed', () => {
  assert.equal(amount(500, 'ISK'), 'ISK 500');
  assert.equal(amount(500, 'UGX', 'manual'), 'UGX 500');
  assert.equal(amount(1234, 'KWD', 'manual'), 'KWD 1.234');
  assert.equal(amount(1234, 'KWD', 'stripe'), '待确认');
});

test('invalid or missing amounts are not formatted as money', () => {
  for (const [minor, currency] of [[null, 'USD'], [undefined, 'USD'], [1.2, 'USD'], [Number.MAX_SAFE_INTEGER + 1, 'USD'], [100, null], [100, 'usd'], [100, 'invalid']]) {
    assert.equal(amount(minor, currency, 'stripe'), '待确认');
  }
});

const authorization = 'https://accounts.google.com/o/oauth2/v2/auth?client_id=synthetic';
test('Gmail, Ads, and BofA accept only verified Google authorization URLs', () => {
  for (const id of ['gmail', 'google_ads', 'bofa']) {
    assert.equal(api.verifiedPrivateAuthorizationUrl(id, authorization), authorization);
    assert.equal(api.verifiedPrivateAuthorizationUrl(id, 'https://accounts.google.com/o/oauth2/auth'), 'https://accounts.google.com/o/oauth2/auth');
  }
  for (const id of ['stripe', 'manual']) assert.equal(api.verifiedPrivateAuthorizationUrl(id, authorization), null);
  for (const value of [
    'javascript:alert(1)', 'http://accounts.google.com/o/oauth2/v2/auth',
    'https://accounts.google.com.evil.example/o/oauth2/v2/auth',
    'https://accounts.google.com:444/o/oauth2/v2/auth',
    'https://user:password@accounts.google.com/o/oauth2/v2/auth',
    'https://accounts.google.com/other', 'https://accounts.google.com/o/oauth2/v2/auth/extra',
  ]) assert.equal(api.verifiedPrivateAuthorizationUrl('bofa', value), null);
});

test('original source links use exact HTTPS provider hosts including BofA Gmail reminders', () => {
  assert.equal(api.verifiedPrivateSourceUrl('bofa', 'https://mail.google.com/mail/u/0/#inbox/synthetic'), 'https://mail.google.com/mail/u/0/#inbox/synthetic');
  assert.equal(api.verifiedPrivateSourceUrl('bofa', 'https://secure.bankofamerica.com/'), 'https://secure.bankofamerica.com/');
  assert.equal(api.verifiedPrivateSourceUrl('stripe', 'https://dashboard.stripe.com/payments/synthetic'), 'https://dashboard.stripe.com/payments/synthetic');
  assert.equal(api.verifiedPrivateSourceUrl('gmail', 'https://dashboard.stripe.com/'), null);
  assert.equal(api.verifiedPrivateSourceUrl('manual', 'https://mail.google.com/'), null);
  for (const value of ['javascript:alert(1)', 'http://mail.google.com/', 'https://mail.google.com.evil.example/', 'https://mail.google.com:444/', 'https://user:password@mail.google.com/']) {
    assert.equal(api.verifiedPrivateSourceUrl('bofa', value), null);
  }
});

test('existing connections can be disconnected despite errors or missing configuration', () => {
  for (const status of ['not_configured', 'disconnected', 'connecting', 'connected', 'error']) {
    for (const missing_configuration of [[], ['GOOGLE_CLIENT_ID']]) {
      const actions = api.privateSourceActionAvailability({ id: 'bofa', status, missing_configuration });
      const pending = status === 'not_configured' || missing_configuration.length > 0;
      assert.equal(actions.pendingConfiguration, pending);
      assert.equal(actions.canConnect, !pending && status !== 'connected');
      assert.equal(actions.canSync, !pending && status === 'connected');
      assert.equal(actions.canDisconnect, ['connecting', 'connected', 'error'].includes(status));
    }
  }
  const manual = api.privateSourceActionAvailability({ id: 'manual', status: 'connected', missing_configuration: [] });
  assert.equal(manual.canConnect, false); assert.equal(manual.canSync, false); assert.equal(manual.canDisconnect, false);
});

test('BofA connect uses its own endpoint and accepts the returned Gmail OAuth redirect', async () => {
  const f = fixture(() => ({ source: { id: 'bofa', status: 'connecting' }, requires_redirect: true, authorization_url: authorization }));
  const response = await f.api.privateWorkspaceApi.connect('bofa');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/v1/private-workspace/sources/bofa/connect');
  assert.equal(f.requests[0].method, 'POST');
  assert.equal(response.requires_redirect, true);
  assert.equal(f.api.verifiedPrivateAuthorizationUrl('bofa', response.authorization_url), authorization);
});

test('Gmail bucket queries reach the server before the result limit is applied', async () => {
  const f = fixture(() => ({ items: [], total: 23, mail_counts: { urgent: 2, today: 5, digest: 23, low: 9 } }));
  const response = await f.api.privateWorkspaceApi.items({ source_id: 'gmail', mail_bucket: 'digest', limit: 1000 });
  const url = new URL(f.requests[0].url, 'https://synthetic.example');
  assert.equal(url.searchParams.get('source_id'), 'gmail');
  assert.equal(url.searchParams.get('mail_bucket'), 'digest');
  assert.equal(url.searchParams.get('limit'), '100');
  assert.equal(response.total, 23);
  assert.equal(response.mail_counts.urgent, 2);
});

test('Gmail preference updates preserve the worker interval by omitting unrelated fields', async () => {
  const f = fixture(() => ({ sync_interval_seconds: 2700, gmail: { topics: ['finance'], watch_senders: [], watch_keywords: [], muted_senders: [] } }));
  await f.api.privateWorkspaceApi.preferences();
  const response = await f.api.privateWorkspaceApi.updatePreferences({ gmail: { topics: ['finance'], watch_keywords: ['synthetic project'] } });
  assert.equal(f.requests[0].url, '/api/v1/private-workspace/preferences');
  assert.equal(f.requests[0].method, 'GET');
  assert.equal(f.requests[1].method, 'PATCH');
  assert.equal(Object.hasOwn(f.requests[1].data, 'sync_interval_seconds'), false);
  assert.equal(response.sync_interval_seconds, 2700);
});

test('feedback applies only to the selected message unless sender scope is explicitly chosen', async () => {
  const f = fixture(() => ({ item: { id: 'synthetic/mail' } }));
  await f.api.privateWorkspaceApi.mailFeedback('synthetic/mail', 'not_relevant');
  await f.api.privateWorkspaceApi.mailFeedback('synthetic/mail', 'important', true);
  await f.api.privateWorkspaceApi.mailFeedback('synthetic/mail', null);
  assert.equal(f.requests[0].url, '/api/v1/private-workspace/items/synthetic%2Fmail/mail-feedback');
  assert.equal(f.requests[0].method, 'POST');
  assert.equal(f.requests[0].data.apply_to_sender, false);
  assert.equal(f.requests[1].data.apply_to_sender, true);
  assert.equal(f.requests[2].data.feedback, null);
  assert.equal(f.requests[2].data.apply_to_sender, false);
  assert.ok(f.requests.every(request => request.url.startsWith('/api/v1/private-workspace/')));
});

test('unclassified old mail remains in the digest and digest or low mail does not enter today priorities', () => {
  assert.equal(api.privateMailBucket({}), 'digest');
  assert.equal(api.privateMailBucket({ mail_relevance: { bucket: 'invalid' } }), 'digest');
  for (const bucket of ['urgent', 'today', 'digest', 'low']) {
    assert.equal(api.privateMailBucket({ mail_relevance: { bucket } }), bucket);
    assert.equal(api.privateMailNeedsAttention({ source_id: 'gmail', mail_relevance: { bucket } }), ['urgent', 'today'].includes(bucket));
  }
  assert.equal(api.privateMailNeedsAttention({ source_id: 'gmail' }), false);
  assert.equal(api.privateMailNeedsAttention({ source_id: 'manual' }), true);
});

test('preference and feedback session changes remain authentication failures', async () => {
  const f = fixture(() => { const error = new Error('synthetic old account'); error.name = 'AuthSessionChangedError'; throw error; });
  await assert.rejects(() => f.api.privateWorkspaceApi.preferences(), error => error.status === 401);
  await assert.rejects(() => f.api.privateWorkspaceApi.mailFeedback('synthetic', 'important'), error => error.status === 401);
});

test('private source sync extends its timeout while existing private reads and mutations retain defaults', async () => {
  const f = fixture(() => ({ sources: [], items: [], total: 0, counts: { created: 0, updated: 0 } }));
  await f.api.privateWorkspaceApi.overview();
  await f.api.privateWorkspaceApi.preferences();
  await f.api.privateWorkspaceApi.items({ source_id: 'gmail' });
  await f.api.privateWorkspaceApi.connect('gmail');
  await f.api.privateWorkspaceApi.updatePreferences({ gmail: { topics: ['finance'] } });
  await f.api.privateWorkspaceApi.mailFeedback('synthetic', 'important');
  for (const source of ['gmail', 'google_ads', 'bofa', 'stripe']) await f.api.privateWorkspaceApi.sync(source);
  for (const request of f.requests) {
    if (request.url.endsWith('/sync')) assert.equal(request.options.timeout, 65_000);
    else assert.equal(Object.hasOwn(request, 'options'), false);
  }
  assert.ok(f.requests.every(request => request.url.startsWith('/api/v1/private-workspace')));
});

test('sync network and timeout outcomes are uncertain, do not leak transport details, and are not replayed', async () => {
  for (const failure of [
    { code: 'ECONNABORTED', message: 'synthetic sensitive timeout trace' },
    { code: 'ERR_NETWORK', message: 'synthetic sensitive network trace' },
    { response: { status: 408, data: { detail: 'synthetic internal response' } } },
    { response: { status: 504, data: { detail: 'synthetic internal gateway' } } },
  ]) {
    const f = fixture(() => { throw failure; });
    await assert.rejects(() => f.api.privateWorkspaceApi.sync('gmail'), error => {
      assert.ok(error.message.includes('服务端可能仍在处理'));
      assert.ok(error.message.includes('请先刷新查看最后同步时间'));
      assert.ok(!error.message.includes('synthetic'));
      return true;
    });
    assert.equal(f.requests.length, 1);
  }
});

test('sync session denial keeps authentication handling instead of an uncertain-sync message', async () => {
  for (const [failure, expectedStatus] of [
    [{ response: { status: 401 } }, 401],
    [{ response: { status: 403 } }, 403],
    [{ name: 'AuthSessionChangedError' }, 401],
  ]) {
    const f = fixture(() => { throw failure; });
    await assert.rejects(() => f.api.privateWorkspaceApi.sync('gmail'), error => {
      assert.equal(error.status, expectedStatus);
      assert.ok(!error.message.includes('可能仍在处理'));
      return true;
    });
  }
  const ordinary = fixture(() => { throw { code: 'ECONNABORTED', message: 'synthetic trace' }; });
  await assert.rejects(() => ordinary.api.privateWorkspaceApi.overview(), error => error.message === '操作暂时无法完成，请重试。');
});

test('private mail translation preview requests deduplicate and cap at ten without requesting body', async () => {
  const f = fixture(() => ({ configured: true, items: [] }));
  await f.api.privateWorkspaceApi.translateMailPreviews(['same', 'same', ...Array.from({ length: 20 }, (_, index) => `synthetic-${index}`)]);
  const request = f.requests[0]; assert.equal(request.url, '/api/v1/private-workspace/mail-translations/batch'); assert.equal(request.method, 'POST'); assert.equal(request.data.item_ids.length, 10); assert.equal(new Set(request.data.item_ids).size, 10); assert.equal(request.options.timeout, 65000);
  assert.equal(request.data.mode, undefined);
});
test('full-body mail translation uses the private item endpoint and explicit body mode', async () => {
  const f = fixture(() => ({ configured: false, item_id: 'synthetic/id', translation: { state: 'unavailable' } }));
  await f.api.privateWorkspaceApi.translateMailBody('synthetic/id');
  assert.equal(f.requests[0].url, '/api/v1/private-workspace/items/synthetic%2Fid/mail-translation'); assert.equal(f.requests[0].data.mode, 'body'); assert.equal(f.requests[0].options.timeout, 65000);
});
test('Chinese mail uses only ready nonempty translation and retains names and original fallbacks', () => {
  const item = { source_id: 'gmail', title: 'Original Stripe subject', summary: 'Original snippet', mail_translation: { state: 'ready', title_zh: 'Stripe 付款提醒', summary_zh: '' } };
  assert.equal(api.privateMailChinese(item, 'title'), 'Stripe 付款提醒'); assert.equal(api.privateMailChinese(item, 'summary'), 'Original snippet');
  item.mail_translation.state = 'pending'; assert.equal(api.privateMailChinese(item, 'title'), 'Original Stripe subject');
  item.mail_translation.state = 'ready'; item.source_id = 'stripe'; assert.equal(api.privateMailChinese(item, 'title'), 'Original Stripe subject');
  assert.ok(!api.privateMailTranslationNotice('raw-secret-details').includes('raw-secret-details'));
});

test('smart mail capabilities are private reads and a brief explicitly requests only the selected item body', async () => {
  const f = fixture(() => ({ configured: true, item_id: 'synthetic/id', brief: { state: 'ready' } }));
  await f.api.privateWorkspaceApi.mailCapabilities(); await f.api.privateWorkspaceApi.organizeMail('synthetic/id');
  assert.equal(f.requests[0].url, '/api/v1/private-workspace/mail-capabilities'); assert.equal(f.requests[0].method, 'GET');
  assert.equal(f.requests[1].url, '/api/v1/private-workspace/items/synthetic%2Fid/mail-brief'); assert.equal(f.requests[1].method, 'POST');
  assert.equal(f.requests[1].data.mode, 'body'); assert.equal(f.requests[1].options.timeout, 65000); assert.equal(f.requests.length, 2);
});
test('ready Chinese brief takes precedence without changing original fields or financial source display', () => {
  const item = { source_id: 'gmail', title: 'Original subject', summary: 'Original snippet', mail_translation: { state: 'ready', title_zh: '旧译文', summary_zh: '旧摘要' }, mail_brief: { state: 'ready', title_zh: '整理后的标题', summary_zh: '整理后的重点' } };
  assert.equal(api.privateMailChinese(item, 'title'), '整理后的标题'); assert.equal(api.privateMailChinese(item, 'summary'), '整理后的重点');
  assert.equal(item.title, 'Original subject'); assert.equal(item.summary, 'Original snippet');
  item.mail_brief.state = 'failed'; assert.equal(api.privateMailChinese(item, 'title'), '旧译文');
  item.source_id = 'bofa'; assert.equal(api.privateMailChinese(item, 'title'), 'Original subject');
  assert.ok(!api.privateMailBriefNotice('RAW PROVIDER SECRET').includes('RAW PROVIDER SECRET'));
});
test('budget exhaustion notice shows only a validated configured USD limit and keeps cached reading available', () => {
  const budget = { configured: true, limit_usd: '5.00', reserved_usd: '5.00', remaining_usd: '0.00', month: '2026-10' };
  const notice = api.privateMailBriefNotice('budget_exhausted', budget);
  assert.equal(notice, '本月 US$5.00 智能整理可用额度不足，已整理邮件和原文仍可查看');
  assert.equal(api.privateMailBriefNotice('budget_exhausted'), '本月智能整理可用额度不足，已整理邮件和原文仍可查看');
  assert.ok(!api.privateMailBriefNotice('budget_exhausted', { ...budget, configured: false }).includes('US$5.00'));
  for (const limit_usd of ['<script>secret</script>', '5.00 SECRET', '-5.00', '5', 5]) {
    const value = api.privateMailBriefNotice('budget_exhausted', { ...budget, limit_usd });
    assert.ok(!value.includes('SECRET')); assert.ok(!value.includes('script')); assert.ok(!value.includes('US$'));
  }
  assert.ok(!api.privateMailBriefNotice('not_configured', budget).includes('US$'));
});

const syntheticStripeSource = {
  id: 'stripe', status: 'connected', error: null,
  metadata: { stripe_account_id: 'acct_synthetic', mode: 'live', stripe_snapshot: { id: 'snapshot-synthetic', account_id: 'acct_synthetic', mode: 'live', observed_at: '2026-10-11T01:00:00Z' } },
};
const stripeNow = Date.parse('2026-10-11T02:00:00Z');
const syntheticStripeItem = (kind = 'payment', evidence = {}) => ({
  source_id: 'stripe', kind, amount_minor: 10000, currency: 'USD', status: 'succeeded',
  evidence: { stripe_account_id: 'acct_synthetic', stripe_mode: 'live', stripe_snapshot_id: 'snapshot-synthetic', stripe_observed_at: '2026-10-11T01:00:00Z',
    amount_authorized_minor: 10000, amount_captured_minor: 0, amount_refunded_minor: 0, paid: true, captured: false, ...evidence },
});

test('Stripe freshness is account and mode bound and never labels snapshots real-time', () => {
  assert.equal(api.privateStripeSnapshot(syntheticStripeSource, stripeNow).state, 'fresh');
  assert.equal(api.privateStripeSnapshot(syntheticStripeSource, stripeNow).label, '同步余额');
  assert.equal(api.privateStripeSnapshot(syntheticStripeSource, stripeNow + 24 * 60 * 60_000).state, 'stale');
  assert.equal(api.privateStripeSnapshot({ ...syntheticStripeSource, status: 'error' }, stripeNow).state, 'stale');
  for (const source of [undefined, { ...syntheticStripeSource, status: 'disconnected' }, { ...syntheticStripeSource, metadata: { mode: 'live' } },
    { ...syntheticStripeSource, metadata: { ...syntheticStripeSource.metadata, stripe_account_id: 'acct_other' } },
    { ...syntheticStripeSource, metadata: { ...syntheticStripeSource.metadata, mode: 'test' } },
    { ...syntheticStripeSource, metadata: { ...syntheticStripeSource.metadata, stripe_snapshot: { ...syntheticStripeSource.metadata.stripe_snapshot, observed_at: 'not-a-time' } } },
  ]) assert.equal(api.privateStripeSnapshot(source, stripeNow).state, 'unverified');
});

test('Stripe pending capture and partial capture use their explicit source amounts', () => {
  const authorization = api.privateStripeRecord(syntheticStripeItem('payment', { payment_state: 'authorized' }), syntheticStripeSource, stripeNow);
  assert.equal(authorization.amountMinor, 10000); assert.equal(authorization.amountLabel, '授权金额'); assert.equal(authorization.statusLabel, '已授权 · 待捕获'); assert.equal(authorization.current, true);
  const captured = api.privateStripeRecord(syntheticStripeItem('payment', { payment_state: 'partially_captured', amount_captured_minor: 6000, captured: true }), syntheticStripeSource, stripeNow);
  assert.equal(captured.amountMinor, 6000); assert.equal(captured.amountLabel, '已收款金额'); assert.equal(captured.statusLabel, '部分收款');
  const legacy = api.privateStripeRecord(syntheticStripeItem('payment'), syntheticStripeSource, stripeNow);
  assert.equal(legacy.statusLabel, '收款状态待复核'); assert.equal(legacy.amountLabel, '请求金额');
});

test('Stripe refunds preserve captured and refunded values without inventing net income', () => {
  const record = api.privateStripeRecord(syntheticStripeItem('payment', { payment_state: 'partially_refunded', amount_captured_minor: 8000, amount_refunded_minor: 2500, captured: true }), syntheticStripeSource, stripeNow);
  assert.equal(record.amountMinor, 8000); assert.equal(record.refundedMinor, 2500); assert.equal(record.hasRefund, true); assert.equal(record.statusLabel, '部分退款');
  assert.ok(!Object.hasOwn(record, 'income') && !Object.hasOwn(record, 'net_income'));
  const payout = api.privateStripeRecord({ ...syntheticStripeItem('payout'), status: 'paid' }, syntheticStripeSource, stripeNow);
  assert.equal(payout.statusLabel, 'Stripe 标记支付 · 银行待核对'); assert.equal(payout.amountLabel, '提现金额');
});

test('Stripe old snapshots and missing monetary evidence remain visibly unconfirmed', () => {
  const old = syntheticStripeItem('payment', { payment_state: 'captured', stripe_snapshot_id: 'older-snapshot', amount_captured_minor: undefined });
  const record = api.privateStripeRecord(old, syntheticStripeSource, stripeNow);
  assert.equal(record.current, false); assert.equal(record.freshnessLabel, '历史记录 · 待重新同步'); assert.equal(record.amountMinor, null);
  for (const bad of [-1, '1000', 10.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(api.privateStripeRecord(syntheticStripeItem('payment', { payment_state: 'captured', amount_captured_minor: bad }), syntheticStripeSource, stripeNow).amountMinor, null);
  }
  const prototypeState = api.privateStripeRecord(syntheticStripeItem('payment', { payment_state: 'constructor' }), syntheticStripeSource, stripeNow);
  assert.equal(prototypeState.statusLabel, '收款状态待复核');
});
