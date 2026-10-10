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
