import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const exports = {};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/lib/operations-read-state.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports });
const { operationsReadState, operationsMetric } = exports;
const ok = { status: 'fulfilled', value: [] }, failed = { status: 'rejected', reason: 'synthetic unavailable' };
test('a failed action source never turns an unknown zero into a confirmed zero', () => {
  const state = operationsReadState([ok, failed, ok, ok]);
  assert.equal(state.actionsIncomplete, true);
  assert.match(state.message, /回访/);
  assert.equal(operationsMetric(0, state.actionsIncomplete), '待重试');
  assert.equal(operationsMetric(8, state.actionsIncomplete), '8 · 待核对');
});
test('successful zero is retained and a name lookup failure does not invalidate action totals', () => {
  assert.equal(operationsMetric(0, operationsReadState([ok, ok, ok, ok]).actionsIncomplete), 0);
  const state = operationsReadState([ok, ok, ok, failed]);
  assert.equal(state.actionsIncomplete, false);
  assert.match(state.message, /客户资料/);
  assert.equal(operationsMetric(0, state.actionsIncomplete), 0);
});
