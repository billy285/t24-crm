import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const exports = {};
const source = readFileSync(new URL('../src/lib/sales-call-evidence.ts', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports });
const { callEvidenceState, reportEvidenceState } = exports;

test('unbound, expired and unverified zero counts do not imply no dialing', () => {
  assert.equal(callEvidenceState({ provider_calls: 0, connection_status: 'disconnected' }).label, '待接入');
  assert.equal(callEvidenceState({ provider_calls: 0, connection_status: 'attention', extension_number: '101' }).label, '待同步');
  assert.equal(callEvidenceState({ provider_calls: 0, connection_status: 'enabled', last_synced_at: '2026-11-10' }).available, false);
});

test('already synced records remain visible while connection needs repair', () => {
  assert.equal(callEvidenceState({ provider_calls: 7, connection_status: 'attention' }).available, true);
  assert.equal(reportEvidenceState({ summary: { provider_calls: 7 }, employees: [{ provider_calls: 7, connection_status: 'attention' }] }).available, true);
});

test('zero is displayed only with checked period evidence for every employee', () => {
  const checked = { provider_calls: 0, connection_status: 'enabled', last_synced_at: '2026-11-10', sync_coverage: { status: 'window_fetched', unverified_ranges: [] } };
  assert.equal(callEvidenceState(checked).available, true);
  assert.equal(reportEvidenceState({ summary: { provider_calls: 0 }, employees: [checked] }).available, true);
  assert.equal(reportEvidenceState({ summary: { provider_calls: 0 }, employees: [checked, { provider_calls: 0 }] }).available, false);
  assert.equal(callEvidenceState({ ...checked, sync_coverage: { ...checked.sync_coverage, needs_retry: true } }).available, false);
});
