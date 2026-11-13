import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/customer-operations-presentation.ts', import.meta.url), 'utf8');
const context = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context);
const { buildCustomerCooperationRows: build, getCustomerPrimaryContact: contact } = context.exports;
const plain = value => JSON.parse(JSON.stringify(value));
// All records in this suite are synthetic, including merchant/contact identifiers.
const project = (id, fields = {}) => ({ id, customer_id: 101, package_name: `合成合作项目${id}`, status: 'active_paid', ...fields });
const subscription = (id, fields = {}) => ({ id, customer_id: 101, package_name: `合成服务${id}`, status: 'active', ...fields });
const deal = (id, fields = {}) => ({ id, customer_id: 101, package_name: `合成成交${id}`, is_paid: true, ...fields });

test('one cooperation project absorbs all explicit subscriptions and deals without duplicated cards', () => {
  const rows = build({ customerId: 101, projects: [project(1)], subscriptions: [subscription(2, { engagement_id: 1 }), subscription(3, { engagement_id: '1' })], deals: [deal(4, { engagement_id: 1 }), deal(5, { engagement_id: 1 })] });
  assert.equal(rows.length, 1);
  assert.deepEqual(plain(rows[0].subscriptionIds), [2, 3]);
  assert.deepEqual(plain(rows[0].dealIds), [4, 5]);
  assert.equal(rows[0].source, 'project'); assert.equal(rows[0].unlinked, false);
});

test('a one-time project with no subscription remains a cooperation row', () => {
  const rows = build({ customerId: 101, projects: [project(1, { business_line: { code: 'one_time_project' }, status: 'completed' })] });
  assert.equal(rows.length, 1); assert.equal(rows[0].statusKind, 'ended');
  assert.deepEqual(plain(rows[0].subscriptionIds), []);
});

test('customer-scoped project endpoint may omit customer_id, but explicit mismatch and other unscoped records are excluded', () => {
  const rows = build({ customerId: 101, projects: [{ id: 1, product_name: '合成已授权项目', status: 'active' }, project(2, { customer_id: 202 })], subscriptions: [{ id: 3, status: 'active' }, subscription(4, { customer_id: 202 })], deals: [{ id: 5 }, deal(6, { customer_id: 202 })] });
  assert.equal(rows.length, 1); assert.equal(rows[0].title, '合成已授权项目'); assert.equal(rows[0].statusLabel, '服务中');
});

test('legacy same-name records remain separate without explicit foreign keys', () => {
  const rows = build({ customerId: 101, projects: [project(1, { package_name: '同名合成套餐' })], subscriptions: [subscription(2, { package_name: '同名合成套餐' })], deals: [deal(3, { package_name: '同名合成套餐' })] });
  assert.equal(rows.length, 3);
  assert.deepEqual(plain(rows.map(row => row.source)), ['project', 'legacy_subscription', 'legacy_deal']);
});

test('explicit legacy subscription/deal link produces one row and does not infer service from payment', () => {
  const rows = build({ customerId: 101, subscriptions: [subscription(2, { deal_id: 3, computed_status: 'paused' })], deals: [deal(3)] });
  assert.equal(rows.length, 1); assert.equal(rows[0].source, 'legacy_subscription');
  assert.equal(rows[0].statusKind, 'paused'); assert.deepEqual(plain(rows[0].dealIds), [3]);
  const dealOnly = build({ customerId: 101, deals: [deal(3, { is_paid: true })] })[0];
  assert.equal(dealOnly.statusKind, 'unknown'); assert.equal(dealOnly.statusLabel, '合作状态待核对');
});

test('a subscription can follow its visible deal explicit project association', () => {
  const rows = build({ customerId: 101, projects: [project(1)], subscriptions: [subscription(2, { deal_id: 3 })], deals: [deal(3, { engagement_id: 1 })] });
  assert.equal(rows.length, 1); assert.deepEqual(plain(rows[0].subscriptionIds), [2]); assert.deepEqual(plain(rows[0].dealIds), [3]);
});

test('an unlinked deal may join the single project explicitly referenced by its subscriptions', () => {
  const rows = build({ customerId: 101, projects: [project(1)], subscriptions: [subscription(2, { engagement_id: 1, deal_id: 3 })], deals: [deal(3)] });
  assert.equal(rows.length, 1); assert.deepEqual(plain(rows[0].dealIds), [3]);
});

test('conflicting project references never move a deal or subscription into another project', () => {
  const rows = build({ customerId: 101, projects: [project(1), project(2)], subscriptions: [subscription(3, { engagement_id: 1, deal_id: 4 })], deals: [deal(4, { engagement_id: 2 })] });
  assert.deepEqual(plain(rows[0].subscriptionIds), [3]); assert.deepEqual(plain(rows[0].dealIds), []);
  assert.deepEqual(plain(rows[1].subscriptionIds), []); assert.deepEqual(plain(rows[1].dealIds), [4]);
});

test('inaccessible explicit engagement does not fall through a visible deal to another project', () => {
  const rows = build({ customerId: 101, projects: [project(1)], subscriptions: [subscription(2, { engagement_id: 999, deal_id: 3 })], deals: [deal(3, { engagement_id: 1 })] });
  assert.equal(rows.length, 2); assert.deepEqual(plain(rows[0].subscriptionIds), []);
  assert.equal(rows[1].source, 'legacy_subscription'); assert.equal(rows[1].unlinked, true);
});

test('ambiguous shared deal does not arbitrarily select one of two explicitly linked projects', () => {
  const rows = build({ customerId: 101, projects: [project(1), project(2)], subscriptions: [subscription(3, { engagement_id: 1, deal_id: 5 }), subscription(4, { engagement_id: 2, deal_id: 5 })], deals: [deal(5)] });
  assert.equal(rows.length, 3); assert.equal(rows[2].source, 'legacy_deal');
  assert.deepEqual(plain(rows[0].dealIds), []); assert.deepEqual(plain(rows[1].dealIds), []);
});

test('decorated subscription status wins while unknown/prototype values never become active', () => {
  assert.equal(build({ customerId: 101, subscriptions: [subscription(1, { status: 'active', computed_status: 'expired' })] })[0].statusKind, 'ended');
  for (const value of ['unknown_future', '__proto__', 'constructor', 'toString', '']) {
    for (const rows of [build({ customerId: 101, projects: [project(1, { status: value })] }), build({ customerId: 101, subscriptions: [subscription(1, { status: value })] })]) {
      assert.equal(rows[0].statusKind, 'unknown'); assert.equal(typeof rows[0].statusLabel, 'string');
    }
  }
});

test('current linked subscription wins over earlier expired period without losing either source ID', () => {
  const rows = build({ customerId: 101, projects: [project(1)], subscriptions: [subscription(2, { engagement_id: 1, computed_status: 'expired', start_date: '2026-01-01', end_date: '2026-02-01', renewal_person: '合成旧运营' }), subscription(3, { engagement_id: 1, computed_status: 'active', start_date: '2026-11-01', end_date: '2026-12-01', renewal_person: '合成现运营' })] });
  assert.equal(rows.length, 1); assert.equal(rows[0].subscription.id, 3); assert.equal(rows[0].endDate, '2026-12-01');
  assert.equal(rows[0].renewalOwner, '合成现运营'); assert.deepEqual(plain(rows[0].subscriptionIds), [2, 3]);
});

test('multiple equally current subscriptions with different periods are explicitly uncertain', () => {
  const rows = build({ customerId: 101, subscriptions: [subscription(1, { deal_id: 3, start_date: '2026-11-01', end_date: '2026-12-01' }), subscription(2, { deal_id: 3, start_date: '2026-11-15', end_date: '2026-12-15', computed_status: 'expiring_soon' })], deals: [deal(3, { service_end_date: '2026-01-01' })] });
  assert.equal(rows.length, 1); assert.equal(rows[0].periodConflict, true);
  assert.equal(rows[0].endDate, undefined); assert.equal(rows[0].startDate, undefined);
  assert.equal(rows[0].statusKind, 'unknown'); assert.match(rows[0].statusLabel, /不一致/);
});

test('an unknown legacy period stays visible for review rather than inheriting an ended period status', () => {
  const [row] = build({ customerId: 101, subscriptions: [subscription(1, { deal_id: 3, computed_status: 'expired' }), subscription(2, { deal_id: 3, computed_status: 'unknown_future' })], deals: [deal(3)] });
  assert.equal(row.statusKind, 'unknown'); assert.match(row.statusLabel, /待核对.*unknown_future/);
  assert.equal(row.subscription.id, 2); assert.deepEqual(plain(row.subscriptionIds), [1, 2]);
});

test('source dates and responsible people are carried without creating dates or financial display properties', () => {
  const rows = build({ customerId: 101, projects: [project(1, { owner_employee_id: 7, sales_employee_id: 8, paid_started_at: '2026-10-29T00:00:00Z', trial_started_at: '2026-10-01T00:00:00Z' })], subscriptions: [subscription(2, { engagement_id: 1, renewal_person: '合成运营', start_date: '2026-11-01T00:00:00Z', end_date: '2026-12-01T00:00:00Z', package_price: 123 })], deals: [deal(3, { engagement_id: 1, deal_amount: 123 })] });
  assert.equal(rows[0].startDate, '2026-11-01T00:00:00Z'); assert.equal(rows[0].endDate, '2026-12-01T00:00:00Z');
  assert.equal(rows[0].ownerId, 7); assert.equal(rows[0].salesOwnerId, 8); assert.equal(rows[0].renewalOwner, '合成运营');
  assert.ok(!Object.hasOwn(rows[0], 'amount')); assert.ok(!Object.hasOwn(rows[0], 'package_price'));
  assert.equal(build({ customerId: 101, projects: [project(1, { paid_started_at: '2026-11-01', trial_started_at: '2026-10-01' })] })[0].startDate, undefined);
});

test('building rows does not mutate inputs and duplicate database IDs do not duplicate associations', () => {
  const input = { customerId: '101', projects: [project(1)], subscriptions: [subscription(2, { engagement_id: 1 }), subscription(2, { engagement_id: 1 })], deals: [deal(3, { engagement_id: 1 })] };
  const before = JSON.stringify(input);
  const rows = build(input); assert.equal(JSON.stringify(input), before);
  assert.equal(rows[0].project, input.projects[0]); assert.deepEqual(plain(rows[0].subscriptionIds), [2]);
  for (const customerId of [0, -1, '101x', null, '__proto__']) assert.equal(build({ ...input, customerId }).length, 0);
});

test('primary contact respects basic-module visibility and uses real nonempty fields only', () => {
  const customer = { contact_name: ' 合成联系人 ', phone: ' +1 202 555 0123 ', email: ' synth@example.invalid ' };
  assert.deepEqual(plain(contact(customer)), { name: '合成联系人', phone: '+1 202 555 0123', email: 'synth@example.invalid' });
  assert.equal(contact(customer, false), null); assert.equal(contact({ email: 'synth@example.invalid' }), null);
  assert.equal(contact({ contact_name: {}, phone: 123 }), null);
});
