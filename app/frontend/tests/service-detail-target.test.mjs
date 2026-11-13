import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/lib/service-detail-target.ts', import.meta.url), 'utf8');
const module = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: module.exports, URLSearchParams });
const read = value => module.exports.readServiceDetailTarget(new URLSearchParams(value));

test('existing progress links still open the authorized task-list location', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(read('progress_id=42'))), { progressId: 42, tab: 'tasks', taskId: null, key: '42:tasks:' });
});

test('a problem link selects service overview without treating an incidental task as an action', () => {
  const result = read('progress_id=42&detail_tab=overview&task_id=77');
  assert.equal(result.tab, 'overview');
  assert.equal(result.taskId, null);
});

test('a task link identifies a task only within its explicit parent service', () => {
  const result = read('progress_id=42&detail_tab=tasks&task_id=77');
  assert.equal(result.progressId, 42);
  assert.equal(result.taskId, 77);
  assert.notEqual(result.key, read('progress_id=43&task_id=77').key);
});

test('switching tabs or targets changes the navigation identity while return path does not', () => {
  assert.notEqual(read('progress_id=42&detail_tab=overview').key, read('progress_id=42&detail_tab=timeline').key);
  assert.equal(read('progress_id=42&returnTo=%2Fcustomers').key, read('progress_id=42').key);
});

for (const id of ['', '0', '-1', '1.2', '1e3', '01', 'Infinity', '9007199254740992', '../42']) {
  test(`malformed or unsafe progress ID ${JSON.stringify(id)} cannot produce a target`, () => {
    assert.equal(read(`progress_id=${encodeURIComponent(id)}&task_id=77`), null);
  });
}

test('unknown tab and invalid task preserve the safe existing task-list view', () => {
  const result = read('progress_id=42&detail_tab=delete&task_id=-1');
  assert.equal(result.tab, 'tasks');
  assert.equal(result.taskId, null);
});
