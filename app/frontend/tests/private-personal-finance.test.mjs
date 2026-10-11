import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const file = resolve(dirname(fileURLToPath(import.meta.url)), '../src/lib/private-personal-finance.ts');
const source = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function fixture(handler = () => ({})) {
  const requests = []; const module = { exports: {} };
  const context = vm.createContext({ Intl, URLSearchParams, crypto: { randomUUID: () => 'synthetic-uuid' } });
  vm.runInContext(`(function(require,module,exports){${source}\n})`, context, { filename: file })(name => { assert.equal(name, './api'); return { client: { apiCall: { invoke: async request => { requests.push(request); return { data: await handler(request) }; } } } }; }, module, module.exports);
  return { api: module.exports, requests };
}
const { api } = fixture();
test('decimal amounts become exact fen and reject ambiguous or overflowing input', () => {
  for (const [text, value] of [['0.01', 1], ['0.10', 10], ['1.1', 110], ['10.29', 1029], ['90000000000', 9000000000000], [' 32.40 ', 3240]]) assert.equal(api.parseFinanceAmount(text), value);
  for (const text of ['', '0', '-1', '+1', '01', '.1', '1.', '1,000', '1e2', '0.001', 'NaN', '90000000000.01', '99999999999']) assert.equal(api.parseFinanceAmount(text), null);
  assert.equal(api.parseFinanceAmount('0', true), 0);
  assert.equal(api.parseFinanceAmount('0.01') + api.parseFinanceAmount('0.02'), 3);
  assert.equal(api.financeAmountInput(1029), '10.29');
  assert.equal(api.formatFinanceAmount(1029), '¥10.29');
  assert.equal(api.formatFinanceAmount(-1029), '−¥10.29');
  assert.equal(api.formatFinanceAmount(null), '—');
  assert.equal(api.formatFinanceAmount(1.2), '—');
});
test('today uses Beijing date across the UTC day boundary', () => {
  assert.equal(api.financeToday(new Date('2026-10-11T16:01:00Z')), '2026-10-12');
  assert.equal(api.financeToday(new Date('2026-10-11T15:59:00Z')), '2026-10-11');
});
test('calendar validity rejects impossible dates and honors leap years', () => {
  for (const value of ['2000-02-29', '2024-02-29', '2100-02-28']) assert.equal(api.validFinanceDate(value), true);
  for (const value of ['1999-12-31', '2101-01-01', '2100-02-29', '2026-02-29', '2026-04-31', '2026-13-01', '2026-01-00', '26-01-01', '2026-1-1']) assert.equal(api.validFinanceDate(value), false);
});
test('month quarter and year include their exact first and final dates', () => {
  const expect = (preset, date, start, end) => { const range = api.financePeriodRange(preset, date); assert.equal(range.start_date, start); assert.equal(range.end_date, end); };
  expect('month', '2024-02-03', '2024-02-01', '2024-02-29');
  expect('month', '2100-02-03', '2100-02-01', '2100-02-28');
  expect('quarter', '2026-01-01', '2026-01-01', '2026-03-31');
  expect('quarter', '2026-12-31', '2026-10-01', '2026-12-31');
  expect('year', '2026-05-18', '2026-01-01', '2026-12-31');
  assert.equal(api.shiftFinanceAnchor('2026-01-31', 'month', -1), '2025-12-01');
  assert.equal(api.shiftFinanceAnchor('2026-10-31', 'quarter', 1), '2027-01-01');
  assert.equal(api.shiftFinanceAnchor('2024-02-29', 'year', 1), '2025-02-01');
  assert.throws(() => api.shiftFinanceAnchor('2000-01-01', 'month', -1));
  assert.throws(() => api.financePeriodRange('custom', '2026-01-01', { start_date: '2026-02-01', end_date: '2026-01-01' }));
  assert.throws(() => api.financePeriodRange('custom', '2026-01-01', { start_date: '2026-02-30', end_date: '2026-03-01' }));
  const custom = api.financePeriodRange('custom', '2026-01-01', { start_date: '2026-10-03', end_date: '2026-10-03' });
  assert.equal(custom.start_date, custom.end_date);
});
test('local personal API stays within its separate namespace and preserves payment idempotency', async () => {
  const f = fixture(); const input = { kind: 'expense', amount_minor: 48, account_id: 'synthetic-account', category_id: 'synthetic-category', entry_date: '2026-10-12', client_request_id: 'synthetic-uuid' };
  await f.api.personalFinanceApi.createEntry(input);
  await f.api.personalFinanceApi.payPlan('synthetic/plan', { account_id: 'synthetic-account', amount_minor: 48, entry_date: '2026-10-12', client_request_id: 'synthetic-uuid' });
  await f.api.personalFinanceApi.entries({ start_date: '2026-10-01', end_date: '2026-10-31', category_id: 'synthetic/a', status: 'void', page: 2, page_size: 20 });
  await f.api.personalFinanceApi.reorderCategories('expense', ['synthetic-b', 'synthetic-a']);
  assert.equal(f.requests[0].data.amount_minor, 48); assert.equal(f.requests[0].data.client_request_id, 'synthetic-uuid');
  assert.equal(f.requests[1].url, '/api/v1/private-workspace/personal-finance/plans/synthetic%2Fplan/pay');
  assert.equal(f.requests[1].data.client_request_id, 'synthetic-uuid');
  const query = new URL(f.requests[2].url, 'https://synthetic.example').searchParams;
  assert.equal(query.get('start_date'), '2026-10-01'); assert.equal(query.get('end_date'), '2026-10-31'); assert.equal(query.get('category_id'), 'synthetic/a'); assert.equal(query.get('status'), 'void');
  assert.equal(f.requests[3].url, '/api/v1/private-workspace/personal-finance/categories/reorder');
  assert.equal(f.requests[3].data.category_ids.join(','), 'synthetic-b,synthetic-a');
  assert.ok(f.requests.every(request => request.url.startsWith('/api/v1/private-workspace/personal-finance/')));
});
test('permission failures and account changes never display private transport error details', async () => {
  for (const status of [401, 403]) {
    const f = fixture(() => { throw { response: { status, data: { detail: 'synthetic private secret' } } }; });
    await assert.rejects(f.api.personalFinanceApi.state(), error => error.status === status && !error.message.includes('secret'));
  }
  const f = fixture(() => { throw { response: { status: 409, data: { detail: '账户余额不足' } } }; });
  await assert.rejects(f.api.personalFinanceApi.createEntry({}), /账户余额不足/);
});

test('a lost success response freezes the original payload and key until the same operation is replayed', async () => {
  const guard = api.createFinanceSubmissionGuard(); const receipts = new Map(); let debits = 0; let requests = 0;
  const original = { amount_minor: 4829, client_request_id: 'synthetic-original', note: 'first note' };
  const operation = { payload: original, work: async () => {
    requests++;
    if (!receipts.has(original.client_request_id)) { receipts.set(original.client_request_id, { id: 'synthetic-entry' }); debits += original.amount_minor; }
    if (requests === 1) throw new api.PersonalFinanceApiError('response lost', 0);
    return receipts.get(original.client_request_id);
  } };
  guard.begin(operation);
  try { await operation.work(); } catch (error) { assert.equal(api.financeOutcomeUnknown(error), true); guard.unknown(); }
  assert.equal(guard.locked(), true);
  assert.throws(() => guard.begin({ payload: { amount_minor: 4829, client_request_id: 'synthetic-edited', note: 'edited after timeout' } }));
  assert.equal(guard.retry().payload.client_request_id, 'synthetic-original');
  assert.equal(guard.retry().payload.note, 'first note');
  assert.equal((await guard.retry().work()).id, 'synthetic-entry'); guard.resolved();
  assert.equal(debits, 4829); assert.equal(requests, 2); assert.equal(guard.locked(), false);
  assert.equal(api.financeOutcomeUnknown(new api.PersonalFinanceApiError('insufficient', 409)), false);
  for (const status of [0, 408, 500, 503, 504]) assert.equal(api.financeOutcomeUnknown(new api.PersonalFinanceApiError('unknown', status)), true);
});

test('transaction navigation holds cannot be discarded by accepting the ordinary draft prompt', () => {
  const guardFile = resolve(dirname(file), 'use-unsaved-changes.ts');
  const guardSource = ts.transpileModule(readFileSync(guardFile, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} }; const cleanups = []; let confirmations = 0; let beforeUnload;
  const window = { confirm: () => { confirmations++; return true; }, addEventListener: (name, handler) => { if (name === 'beforeunload') beforeUnload = handler; } };
  const context = vm.createContext({ window });
  vm.runInContext(`(function(require,module,exports){${guardSource}\n})`, context, { filename: guardFile })(name => {
    assert.equal(name, 'react');
    return { useRef: value => ({ current: value }), useCallback: fn => fn, useLayoutEffect: fn => { const cleanup = fn(); if (cleanup) cleanups.push(cleanup); } };
  }, module, module.exports);
  const hooks = module.exports;
  const hold = hooks.useHardNavigationBlock(false); hold.lock();
  const draft = hooks.useUnsavedChanges(true);
  assert.equal(hooks.hasHardNavigationBlock(), true);
  for (let back = 0; back < 3; back++) {
    assert.equal(hooks.confirmDiscardAllChanges(), false);
    assert.equal(draft.confirmDiscard(), false);
    assert.equal(hooks.hasHardNavigationBlock(), true);
  }
  assert.equal(confirmations, 0);
  draft.markSaved(); assert.equal(hooks.hasUnsavedChanges(), true);
  let warning = false; beforeUnload({ preventDefault: () => { warning = true; } }); assert.equal(warning, true);
  hold.release(); assert.equal(hooks.hasHardNavigationBlock(), false); assert.equal(hooks.hasUnsavedChanges(), false);
  const regular = hooks.useUnsavedChanges(true); assert.equal(hooks.confirmDiscardAllChanges(), true); assert.equal(confirmations, 1);
  regular.markSaved(); cleanups.forEach(cleanup => cleanup());
});
