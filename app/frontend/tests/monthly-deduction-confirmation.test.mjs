import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the page's real confirmation callbacks against a synthetic transport.
// No browser, financial service, or persistent record is used.
const source = readFileSync(new URL('../src/pages/MonthlyDeduction.tsx', import.meta.url), 'utf8');
const file = ts.createSourceFile('MonthlyDeduction.tsx', source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
const names = ['save', 'del', 'saveDefault', 'doImport'];
const declarations = new Map();
function visit(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && names.includes(node.name.text)) declarations.set(node.name.text, node.initializer.getText(file));
  ts.forEachChild(node, visit);
}
visit(file);
assert.equal(declarations.size, 4);
const code = names.map(name => `const ${name} = ${declarations.get(name)};`).join('\n') + '\nObject.assign(exports, {save,del,saveDefault,doImport});';

function fixture(overrides = {}) {
  const writes = [], errors = [];
  let confirmation;
  const context = {
    exports: {}, isAdmin: true, unavailable: false, saving: false, savingDefault: false, importing: false,
    ym: '2026-11', ratePct: '20', editTarget: { rate: 0.15 }, defaultBaseline: '15', defaultRatePct: '20', importFile: { name: 'rates.csv' }, overwrite: true,
    displayRate: rate => String(rate * 100),
    toast: { error: message => { errors.push(message); return 'toast-id'; }, success() {} },
    setConfirmation: value => { confirmation = value; },
    setSaving() {}, setSavingDefault() {}, setImporting() {}, setOpen() {}, setDefaultBaseline() {}, setImportFile() {},
    load: async () => {},
    invokeWithAuth: async value => { writes.push(value); return {}; },
    updateDefaultDeduction: async rate => { writes.push({ defaultRate: rate }); },
    importMonthlyDeductions: async () => { writes.push({ import: true }); return { data: { total: 1, inserted: 1, updated: 0, skipped: 0 } }; },
    ...overrides,
  };
  vm.runInNewContext(ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
  return { actions: context.exports, writes, errors, get confirmation() { return confirmation; } };
}

test('edit/default/import wait for explicit confirmation before any write', async () => {
  for (const name of ['save', 'saveDefault', 'doImport']) {
    const f = fixture();
    assert.equal(await f.actions[name](), false);
    assert.equal(f.writes.length, 0);
    assert.ok(f.confirmation?.description);
    assert.equal(await f.confirmation.run(), true);
    assert.equal(f.writes.length, 1);
  }
});

test('validation and permission guards return false rather than toast ids or implicit success', async () => {
  const invalid = fixture({ ratePct: '', defaultRatePct: 'bad', importFile: null });
  assert.equal(await invalid.actions.save(true), false);
  assert.equal(await invalid.actions.saveDefault(true), false);
  assert.equal(await invalid.actions.doImport(true), false);
  assert.equal(invalid.writes.length, 0);
  const denied = fixture({ isAdmin: false });
  for (const name of ['save', 'saveDefault', 'doImport', 'del']) assert.equal(await denied.actions[name](true), false);
  assert.equal(denied.writes.length, 0);
});

test('failed requests keep confirmation open; only successful writes return true', async () => {
  const reject = async () => { throw new Error('temporary failure'); };
  for (const name of ['save', 'saveDefault', 'doImport', 'del']) {
    const f = fixture({ invokeWithAuth: reject, updateDefaultDeduction: reject, importMonthlyDeductions: reject });
    assert.equal(await f.actions[name](name === 'del' ? '2026-11' : true), false);
    assert.equal(f.errors.length, 1);
  }
  const success = fixture();
  assert.equal(await success.actions.del('2026-11'), true);
});
