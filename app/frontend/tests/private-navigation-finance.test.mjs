import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const filename = fileURLToPath(new URL('../src/lib/private-workspace-navigation.ts', import.meta.url));
const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = { exports: {} };
vm.runInNewContext(`(function(module,exports){${compiled}\n})`, { URLSearchParams })(module, module.exports);
const nav = module.exports;

test('personal books are private navigation only, while existing imported sources retain their identity', () => {
  assert.ok(nav.PRIVATE_WORKSPACE_VIEWS.includes('personal_finance'));
  for (const view of ['personal_finance', 'today', 'funds', 'connections', 'crm_finance', 'not_a_source']) {
    assert.equal(nav.privateWorkspaceItemSource(view), null);
  }
  for (const view of ['gmail', 'google_ads', 'stripe', 'bofa_bank', 'bofa', 'manual']) {
    assert.equal(nav.privateWorkspaceItemSource(view), view);
  }
});

test('cross-view finance navigation cleanup removes future pf keys and preserves original source and detail IDs', () => {
  const current = new URLSearchParams('view=gmail&item=mail-id&panel=preferences&pf_tab=analysis&pf_edit=entry&pf_detail=record-id&pf_future=stale');
  const clean = nav.withoutPersonalFinanceNavigation(current);
  assert.equal(clean.toString(), 'view=gmail&item=mail-id&panel=preferences');
  assert.equal(current.get('pf_tab'), 'analysis');
});

test('history accepts a finance parent only in this owner session and strips private amounts and note fields', () => {
  const value = { privateWorkspace: { session: 'owner-session', parentKey: 'private-route', parentView: 'personal_finance', amount_minor: 10000, note: 'PRIVATE NOTE', token: 'PRIVATE SECRET' } };
  const accepted = nav.privateNavigationState(value, 'owner-session');
  assert.deepEqual(JSON.parse(JSON.stringify(accepted)), { session: 'owner-session', parentKey: 'private-route', parentView: 'personal_finance' });
  assert.equal(nav.privateNavigationState(value, 'new-owner-session'), null);
  assert.deepEqual(JSON.parse(JSON.stringify(nav.privateBackTarget(accepted, new Set(['private-route'])))), { history: true, view: 'personal_finance' });
  assert.deepEqual(JSON.parse(JSON.stringify(nav.privateBackTarget(accepted, new Set()))), { history: false, view: 'today' });
});
