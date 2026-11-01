import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const module = { exports: {} };
vm.runInNewContext(ts.transpileModule(fs.readFileSync(new URL('../src/lib/media-workspace-api.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module, exports: module.exports, require: () => ({}), URLSearchParams, Date, Set, Map });
const { verifiedWorkspaceProjection } = module.exports;
const query = { customerId: null, platform: null, view: 'review', start: '2026-10-31T16:00:00Z', end: '2026-11-30T16:00:00Z', limit: 20 };
const monthlyRun = extra => ({ id: 'monthly_run:7', kind: 'monthly_run', customer_id: 20, customer_name: 'LOCAL TEST Northern', platform: 'google_business', title: '2026-11 · 12 candidate drafts', content: 'LOCAL TEST owner preview only', status: 'generated', at: '2026-11-01T01:00:00Z', time_basis: 'record_created', timezone: 'America/Chicago', revision: 1, version: null, source_id: 7, binding_id: null, binding_revision: null, account_label: null, review_eligible: false, navigation: { workspace: 'monthly', run_id: 7 }, ...extra });
const monthlyItem = extra => monthlyRun({ id: 'monthly_item:31', kind: 'monthly_item', source_id: 31, at: '2026-11-03T17:00:00Z', time_basis: 'proposed_publish', ...extra });
const projection = (items = [monthlyRun()], extra = {}, expected = query) => ({ items, total: items.length, next_cursor: null, partial: false, sources: ['tasks', 'google', 'meta', 'monthly'].map(key => ({ key, state: 'ready', message: 'LOCAL TEST local projection' })), observed_at: '2026-11-01T01:00:00Z', scope: { customer_id: expected.customerId, platform: expected.platform, view: expected.view }, range: { start: expected.start, end: expected.end }, summary: { tasks: 0, drafts: 0, in_review: 0, ready: 0, scheduled: 0, blocked: 0, unknown: 0, inbox: 0, review_candidates: 0 }, capabilities: { is_owner: true, meta_owner_only: true }, ...extra });
const reject = row => assert.throws(() => verifiedWorkspaceProjection(projection([row]), query));

test('owner monthly run retains explicit merchant/run navigation in all-merchant and exact-merchant scope', () => {
  assert.equal(verifiedWorkspaceProjection(projection(), query).items[0].navigation.run_id, 7);
  const scoped = { ...query, customerId: 20, platform: 'google_business' };
  assert.equal(verifiedWorkspaceProjection(projection([monthlyRun()], {}, scoped), scoped).items[0].customer_id, 20);
});
test('monthly projection rejects staff even when a response claims a valid month and merchant', () => {
  for (const row of [monthlyRun(), monthlyItem()]) assert.throws(() => verifiedWorkspaceProjection(projection([row], { capabilities: { is_owner: false, meta_owner_only: true } }), query));
});
test('monthly records accept each owner authorized positive merchant and supported platforms but reject wrong selected merchant or unsupported platforms', () => {
  for (const customer_id of [21, 31]) {
    assert.equal(verifiedWorkspaceProjection(projection([monthlyRun({customer_id})]),query).items[0].customer_id,customer_id);
    const selected={...query,customerId:customer_id,platform:'google_business'};
    assert.equal(verifiedWorkspaceProjection(projection([monthlyRun({customer_id})],{},selected),selected).items[0].customer_id,customer_id);
    assert.throws(()=>verifiedWorkspaceProjection(projection([monthlyRun({customer_id:customer_id+1})],{},selected),selected));
  }
  for (const extra of [{ customer_id: 0 }, { customer_id: -1 }, { customer_id: '31' }, { platform: 'tiktok' }, { platform: 'all' }]) { reject(monthlyRun(extra)); reject(monthlyItem(extra)); }
});
test('monthly records require monthly navigation with a positive numeric run ID', () => {
  for (const navigation of [{ workspace: 'monthly' }, { workspace: 'monthly', run_id: 0 }, { workspace: 'monthly', run_id: -1 }, { workspace: 'monthly', run_id: '7' }, { workspace: 'tasks', task_id: 7 }, { workspace: 'google', binding_id: 7 }, { workspace: 'meta', binding_id: 7 }]) { reject(monthlyRun({ navigation })); reject(monthlyItem({ navigation })); }
});
test('monthly run source ID is the exact run ID, without string coercion or unrelated source IDs', () => {
  for (const source_id of [8, '7', 'arbitrary']) reject(monthlyRun({ source_id }));
  assert.equal(verifiedWorkspaceProjection(projection([monthlyItem()]), query).items[0].source_id, 31);
});
test('monthly item dates are proposed publication time and cannot masquerade as actual schedules', () => {
  assert.equal(verifiedWorkspaceProjection(projection([monthlyItem()]), query).items[0].time_basis, 'proposed_publish');
  for (const time_basis of ['scheduled_publish', 'platform_created', 'task_due', 'record_created']) reject(monthlyItem({ time_basis }));
});
test('monthly candidates are never eligible for native one-click approval', () => {
  reject(monthlyRun({ review_eligible: true })); reject(monthlyItem({ review_eligible: true }));
});
test('native task, Google and Meta records cannot navigate into a monthly run', () => {
  for (const kind of ['task', 'google_schedule', 'google_reply_draft', 'google_action', 'meta_draft', 'meta_schedule', 'meta_comment', 'meta_post', 'meta_action']) reject(monthlyRun({ id: `${kind}:7`, kind }));
});
test('monthly additions preserve strict source uniqueness and loaded scope/date boundaries', () => {
  assert.throws(() => verifiedWorkspaceProjection(projection([monthlyRun(), monthlyRun()]), query));
  assert.throws(() => verifiedWorkspaceProjection(projection([monthlyRun()], { sources: [{ key: 'monthly', state: 'ready', message: '' }, { key: 'monthly', state: 'ready', message: '' }] }), query));
  assert.throws(() => verifiedWorkspaceProjection(projection([monthlyRun()], { scope: { customer_id: 21, platform: null, view: 'review' } }), query));
  assert.throws(() => verifiedWorkspaceProjection(projection([monthlyRun()], { range: { start: '2026-11-02T00:00:00Z', end: query.end } }), query));
});

test('Meta monthly navigation retains exact platform and refuses cross-platform selected scope', () => {
  for (const platform of ['facebook','instagram']) {
    const selected={...query,customerId:31,platform};
    for (const make of [monthlyRun,monthlyItem]) assert.equal(verifiedWorkspaceProjection(projection([make({customer_id:31,platform})],{},selected),selected).items[0].platform,platform);
    assert.throws(()=>verifiedWorkspaceProjection(projection([monthlyRun({customer_id:31,platform:platform==='facebook'?'instagram':'facebook'})],{},selected),selected));
  }
});
