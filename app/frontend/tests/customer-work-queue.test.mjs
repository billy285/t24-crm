import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/customer-work-queue.ts', import.meta.url), 'utf8');
const context = { exports: {}, URL, AbortController };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context);
const { buildCustomerWorkQueueItems: build, CustomerWorkQueueRequestGuard: Guard } = context.exports;
const visibleCustomers = [{ id: 101, business_name: '合成已授权商家' }];
const plain = value => JSON.parse(JSON.stringify(value));

test('owner queue counts only explicit authorized items and never customer lifecycle guesses', () => {
  const result = build({ source: 'owner', visibleCustomers: [{ ...visibleCustomers[0], status: 'active' }], items: [
    { id: 'pending_receipt-1', kind: 'pending_receipt', customer_id: 101, handoff_id: 1, title: '合成待核款' },
    { id: 'kickoff_missing-1', kind: 'kickoff_missing', customer_id: 101, handoff_id: 1, title: '合成待开工' },
    { id: 'renewal-1', kind: 'renewal_attention', customer_id: 101, href: '/customers?detail=101&tab=renewals', title: '合成续费待核对' },
    { id: 'private', kind: 'pending_receipt', customer_id: 202, handoff_id: 2, title: '合成未授权内容' },
    { id: 'unknown', kind: 'future_invented', customer_id: 101, title: '合成未知来源' },
  ] });
  assert.equal(result.length, 3); assert.deepEqual(plain(result.map(item => item.category)), ['handoff', 'delivery', 'renewal']);
  assert.ok(result.every(item => item.customerName === '合成已授权商家'));
  assert.equal(build({ source: 'owner', visibleCustomers, items: [] }).length, 0);
});

test('handoff queue uses explicit booleans, with separate tasks per real pending responsibility', () => {
  const result = build({ source: 'handoffs', visibleCustomers, items: [
    { id: 1, customer_id: 101, pending_operations: true, operations_owner_name: '合成运营', pending_payment: true },
    { id: 2, customer_id: 101, pending_operations: 'true', pending_payment: false, status: 'pending', is_paid: false },
    { id: 3, customer_id: 202, pending_operations: true },
  ] });
  assert.equal(result.length, 2); assert.ok(result.every(item => item.category === 'handoff'));
  assert.match(result[1].title, /合成运营/); assert.ok(!result.some(item => /待我/.test(item.title)));
  assert.ok(result.every(item => !item.href.includes('action=ack')));
});

test('scope shrink removes previously loaded customer queue items immediately on projection', () => {
  const items = [{ id: 1, customer_id: 101, pending_operations: true }];
  assert.equal(build({ source: 'handoffs', visibleCustomers, items }).length, 1);
  assert.equal(build({ source: 'handoffs', visibleCustomers: [], items }).length, 0);
});

test('owner handoff and kickoff links preserve exact referenced records', () => {
  const result = build({ source: 'owner', visibleCustomers, items: [
    { id: 'receipt-1', kind: 'pending_receipt', customer_id: 101, handoff_id: 9 },
    { id: 'access-1', kind: 'pending_access', customer_id: 101 },
    { id: 'kickoff-1', kind: 'kickoff_blocked', customer_id: 101, handoff_id: 9 },
  ] });
  assert.equal(result[0].href, '/sales-leads?view=handoffs&status=pending_payment&handoff=9&action=finance');
  assert.equal(result[1].href, '/customers?detail=101&access=invite');
  assert.equal(result[2].href, '/operations-workbench?view=kickoffs&handoff=9');
});

test('renewal actions reject external links, mismatched customer/record links and unsupported destinations', () => {
  for (const href of ['https://example.invalid/', '//example.invalid/', '/customers?detail=202&tab=renewals', '/sales-leads?view=handoffs&handoff=99', '/settings', '/\\evil', '/customers\n?detail=101&tab=renewals']) {
    const [item] = build({ source: 'owner', visibleCustomers, items: [{ id: 'renewal-1', kind: 'renewal_attention', customer_id: 101, handoff_id: 9, href }] });
    assert.equal(item.href, '', href);
  }
  const [valid] = build({ source: 'owner', visibleCustomers, items: [{ id: 'renewal-1', kind: 'renewal_attention', customer_id: 101, handoff_id: 9, href: '/sales-leads?view=handoffs&handoff=9' }] });
  assert.equal(valid.href, '/sales-leads?view=handoffs&handoff=9');
  const [historical] = build({ source: 'owner', visibleCustomers, items: [{ id: 'renewal-historical-1', kind: 'renewal_attention', customer_id: 101, href: '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=77' }] });
  assert.equal(historical.href, '/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=77');
});

test('malformed or prototype-like source fields never create unexpected tasks', () => {
  const result = build({ source: 'owner', visibleCustomers, items: [null, {}, { id: '1', customer_id: 101, kind: '__proto__' }, { id: {}, customer_id: 101, kind: 'pending_access' }] });
  assert.equal(result.length, 0);
});

test('duplicate queue items do not double counts and input records remain untouched', () => {
  const item = { id: 1, customer_id: 101, pending_operations: true, waiting_days: 2 };
  const args = { source: 'handoffs', visibleCustomers, items: [item, item] }, before = JSON.stringify(args);
  const result = build(args); assert.equal(result.length, 1); assert.equal(result[0].waitingDays, 2); assert.equal(JSON.stringify(args), before);
});

test('starting a same-scope refresh aborts superseded request and only new result can commit', async () => {
  const guard = new Guard(), committed = [];
  const first = guard.begin('actor-1/scope-A', 'session-1');
  const second = guard.begin('actor-1/scope-A', 'session-1');
  await Promise.resolve();
  if (guard.current(first, 'actor-1/scope-A', 'session-1')) committed.push('old');
  if (guard.current(second, 'actor-1/scope-A', 'session-1')) committed.push('fresh');
  assert.equal(first.signal.aborted, true); assert.deepEqual(committed, ['fresh']);
});

test('account, permission scope, and session changes independently reject late replies', () => {
  const guard = new Guard(), request = guard.begin('actor-1/scope-A', 'session-1');
  assert.equal(guard.current(request, 'actor-2/scope-A', 'session-1'), false);
  assert.equal(guard.current(request, 'actor-1/scope-B', 'session-1'), false);
  assert.equal(guard.current(request, 'actor-1/scope-A', 'session-2'), false);
  assert.equal(guard.current(request, 'actor-1/scope-A', 'session-1'), true);
});

test('unmount or permission revocation aborts active request even when transport later resolves', () => {
  const guard = new Guard(), request = guard.begin('actor-1/scope-A', 'session-1');
  guard.invalidate(); assert.equal(request.signal.aborted, true);
  assert.equal(guard.current(request, 'actor-1/scope-A', 'session-1'), false);
});
