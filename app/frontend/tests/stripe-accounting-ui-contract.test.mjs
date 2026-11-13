import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const file = ts.createSourceFile('StripeHistoryReconciliation.tsx', read('../src/components/StripeHistoryReconciliation.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const component = file.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'StripeHistoryReconciliation');
const variables = new Map(), controls = new Map(); let sourceBranch;
function scan(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) variables.set(node.name.text, node.initializer.getText(file));
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
    const attrs = (ts.isJsxElement(node) ? node.openingElement : node).attributes.properties.filter(ts.isJsxAttribute);
    const label = attrs.find(attr => attr.name.getText(file) === 'aria-label')?.initializer;
    if (label && ts.isStringLiteral(label)) controls.set(label.text, new Map(attrs.map(attr => [attr.name.getText(file), attr.initializer && ts.isJsxExpression(attr.initializer) ? attr.initializer.expression?.getText(file) : attr.initializer?.getText(file)])));
  }
  if (ts.isConditionalExpression(node) && node.condition.getText(file) === "selectedService?.binding_source === 'sales_handoff'") sourceBranch = node;
  ts.forEachChild(node, scan);
}
scan(component);
const lib = { exports: {}, require: () => ({ invokeWithAuth: () => { throw new Error('No real API allowed'); } }) };
vm.runInNewContext(compile(read('../src/lib/stripe-history-reconciliation.ts')), lib);
const { selectStripeService, stripeServiceSourceReady, canPreviewStripeService } = lib.exports;
const plain = value => JSON.parse(JSON.stringify(value));
const history = { customer_id: 7, customer_name: '门店', crm_subscription_id: 11, binding_source: 'history', source_ready: true };
const source = { ...history, binding_source: 'sales_handoff', source_ready: true, source_handoff_id: 8, stripe_subscription_id: 'sub_verified', source_income_type: 'website_fee' };
const draft = { crm_subscription_id: 2, source_handoff_id: 99, stripe_subscription_id: 'sub_previous', sync_from: '2026-11-13', income_type: 'management_fee' };

test('new source uses only server-verified handoff, subscription, and original income type', () => {
  const selected = selectStripeService(draft, source);
  assert.deepEqual(plain(selected), { crm_subscription_id: 11, source_handoff_id: 8, stripe_subscription_id: 'sub_verified', sync_from: '2026-11-13', income_type: 'website_fee' });
  assert.equal(canPreviewStripeService(source, selected), true);
  for (const patch of [{ source_handoff_id: 9 }, { stripe_subscription_id: 'sub_guessed' }, { income_type: 'management_fee' }, { crm_subscription_id: 3 }]) assert.equal(canPreviewStripeService(source, { ...selected, ...patch }), false);
  assert.equal(draft.stripe_subscription_id, 'sub_previous'); assert.equal(draft.source_handoff_id, 99);
});

test('unready, incomplete, or malformed new sources never fall back to manual guesses', () => {
  for (const patch of [{ source_ready: false }, { source_ready: undefined }, { source_handoff_id: 0 }, { source_handoff_id: '8' }, { stripe_subscription_id: '' }, { stripe_subscription_id: 'guessed' }, { source_income_type: undefined }, { source_income_type: 'advertising' }]) {
    const row = { ...source, ...patch }, selected = selectStripeService(draft, row);
    assert.equal(stripeServiceSourceReady(row), false); assert.equal(selected.source_handoff_id, undefined); assert.equal(selected.stripe_subscription_id, ''); assert.equal(selected.income_type, ''); assert.equal(canPreviewStripeService(row, selected), false);
  }
});

test('historical selection clears any previous handoff and keeps the original manual mapping path', () => {
  const selected = selectStripeService(draft, history);
  assert.equal(selected.source_handoff_id, undefined); assert.equal(selected.stripe_subscription_id, ''); assert.equal(selected.income_type, 'management_fee');
  assert.equal(canPreviewStripeService(history, { ...selected, stripe_subscription_id: 'sub_manual' }), true);
  assert.equal(canPreviewStripeService(history, { ...selected, stripe_subscription_id: 'sub_manual', source_handoff_id: 8 }), false);
  assert.equal(canPreviewStripeService({ ...history, source_ready: false }, { ...selected, stripe_subscription_id: 'sub_manual' }), false);
});

test('actual service selector adopts server source metadata and clears any prior preview', () => {
  let next, cleared = false;
  const context = { exports: {}, services: [source], selectStripeService, setDraft: update => { next = update(draft); }, setPreview: value => { cleared = value === null; } };
  vm.runInNewContext(compile(`exports.change = ${controls.get('CRM 客户服务').get('onChange')};`), context);
  context.exports.change({ target: { value: '11' } }); assert.equal(next.source_handoff_id, 8); assert.equal(next.income_type, 'website_fee'); assert.equal(cleared, true);
  context.exports.change({ target: { value: '' } }); assert.equal(next.crm_subscription_id, 0); assert.equal(next.source_handoff_id, undefined);
});

test('new source hides manual subscription entry and locks original income classification; historical remains editable', () => {
  assert.ok(sourceBranch); assert.doesNotMatch(sourceBranch.whenTrue.getText(file), /<Input|loadCandidates/); assert.match(sourceBranch.whenFalse.getText(file), /Stripe 订阅编号/);
  for (const [selectedService, expected] of [[source, true], [history, false]]) {
    const context = { exports: {}, selectedService }; vm.runInNewContext(compile(`exports.disabled = ${controls.get('公司账本收入类型').get('disabled')};`), context); assert.equal(context.exports.disabled, expected);
  }
});

test('actual preview handler rejects stale or tampered source data without making an API request', async () => {
  for (const patch of [{}, { servicesBusy: true }, { servicesError: 'unavailable' }, { isOwner: false }, { configured: false }, { selectedService: { ...source, source_ready: false } }, { draft: { ...selectStripeService(draft, source), income_type: 'management_fee' } }]) {
    const calls = [];
    const context = { exports: {}, isOwner: true, configured: true, servicesBusy: false, servicesError: '', selectedService: source, draft: selectStripeService(draft, source), canPreviewStripeService, mappingInFlight: { current: false }, setPreviewBusy() {}, setMappingError() {}, setMappingMessage() {}, setPreview() {}, clearSensitive() {}, stripeReconciliationDenied: () => false, stripeReconciliationError: () => 'error', api: async (...args) => { calls.push(args); return { token: 'safe' }; }, ...patch };
    vm.runInNewContext(compile(`exports.run = ${variables.get('requestPreview')};`), context); await context.exports.run();
    assert.equal(calls.length, Object.keys(patch).length ? 0 : 1);
    if (calls.length) { assert.equal(calls[0][0], '/bindings/preview'); assert.equal(calls[0][2].source_handoff_id, 8); assert.equal(calls[0][2].income_type, 'website_fee'); assert.equal('enabled' in calls[0][2], false); }
  }
});

test('binding confirmation remains owner-confirmed and token-only, without enabling automatic posting', async () => {
  const calls = [];
  const context = { exports: {}, mappingInFlight: { current: false }, setCommitToken() {}, setMappingError() {}, setMappingMessage() {}, setPreview() {}, setCart() {}, load: async () => {}, clearSensitive() {}, stripeReconciliationDenied: () => false, stripeReconciliationError: () => 'error', api: async (...args) => calls.push(args) };
  vm.runInNewContext(compile(`exports.confirm = ${variables.get('confirmBinding')};`), context);
  const entry = { verified: true, warnings: ['explicit'], preview: { token: 'preview-token', can_confirm: true, warnings: [{ code: 'explicit' }] } };
  await context.exports.confirm(entry); assert.equal(calls.length, 1); assert.equal(calls[0][0], '/bindings'); assert.deepEqual(plain(calls[0][2]), { token: 'preview-token', owner_verified: true, accepted_warning_codes: ['explicit'] });
  for (const patch of [{ verified: false }, { warnings: [] }, { preview: { ...entry.preview, can_confirm: false } }]) { calls.length = 0; await context.exports.confirm({ ...entry, ...patch }); assert.equal(calls.length, 0); }
});

test('payment, tax, Stripe net, and bank verification remain distinct in receipt details', () => {
  const dialog = file.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'HistoricalInvoiceDialog').getText(file);
  assert.match(dialog, /本页未读取银行流水匹配结果/); assert.match(dialog, /支付成功或公司记账不能代替银行流水核验/); assert.match(dialog, /stripe_view=bank/); assert.match(dialog, /含税支付总额/); assert.match(dialog, /税前服务费/); assert.match(dialog, /平台净额为含税实付减实际手续费/); assert.doesNotMatch(dialog, /平台净到账|真实到账、/);
});

test('finance copy leaves all original named accounting/refund callbacks and net amount expression unchanged', () => {
  const current = read('../src/pages/Finance.tsx');
  const prior = execFileSync('git', ['show', 'a65b85572cede1d5622497c731015a9af8e81919:app/frontend/src/pages/Finance.tsx'], { encoding: 'utf8' });
  function callbacks(text) {
    const parsed = ts.createSourceFile('Finance.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX), out = new Map();
    function visit(node) {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)) && /^(handle|save|open|calculate|getStored|submit|confirm)/i.test(node.name.text)) out.set(node.name.text, node.initializer.getText(parsed));
      ts.forEachChild(node, visit);
    } visit(parsed); return out;
  }
  assert.deepEqual(callbacks(current), callbacks(prior));
  const net = 'fmt(getStoredMoney(p.net_amount) ?? Math.max(Number(p.amount_paid || 0) - calculateStripePlatformFee(p), 0))';
  assert.equal(current.split(net).length, prior.split(net).length); assert.match(current, />渠道净额<\/th>/); assert.match(current, /退还服务费（税前）/); assert.match(current, /历史估算不代表平台实际净额/);
});
