import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
const source = fs.readFileSync(new URL('../src/lib/stripe-bank-reconciliation.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const bank = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const token = 'A'.repeat(43), hash = 'a'.repeat(64);
const row = { row_index: 2, date: '2026-11-13', amount_minor: 9651, currency: 'USD', description: 'STRIPE TRANSFER', reference: 'bank-123', ambiguous: false };
const payout = { id: 'po_verified', amount_minor: 9651, currency: 'USD', arrival_date: '2026-11-13', status: 'paid', automatic: true, eligible: true };
const statement = { token, expires_at: '2026-11-14T00:00:00', account_label: '公司运营账户', currency: 'USD', file_sha256: hash, rows: [row], writes_ledger: false };
const preview = { token, payout, bank_row: row, account_label: '公司运营账户', transaction_count: 3, writes_ledger: false, requires_owner_confirmation: true };
const overview = { items: [], total: 0, currency: 'USD', bank_connection: 'statement_upload', provider_writes: false, ledger_writes: false };
const compile = text => ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const componentSource = fs.readFileSync(new URL('../src/components/StripeBankReconciliation.tsx', import.meta.url), 'utf8');
const file = ts.createSourceFile('StripeBankReconciliation.tsx', componentSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const component = file.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'BankWorkspace');
const variables = new Map();
function scan(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
    const value = ts.isCallExpression(node.initializer) && node.initializer.expression.getText(file) === 'useCallback' ? node.initializer.arguments[0] : node.initializer;
    variables.set(node.name.text, value.getText(file));
  }
  ts.forEachChild(node, scan);
} scan(component);
const plain = value => JSON.parse(JSON.stringify(value));
function runtime(extra = {}) {
  const events = [], context = { exports: {}, guard: { current: new bank.BankRequestGuard() }, inFlight: { current: null }, liveScope: { current: { key: 'owner:sessionA', allowed: true } }, scope: 'owner:sessionA', session: 'sessionA', getAuthSessionEpoch: () => 'sessionA', uncertain: false, operationBlocked: { current: false }, statusCode: error => error.status || 0, stripeReconciliationError: (error, fallback) => fallback, clearWorkflow: () => events.push(['clear']), Error, ...extra };
  for (const name of ['setBusy', 'setError', 'setMessage', 'setOverview', 'setOverviewError', 'setDenied', 'setUncertain', 'setVerified', 'setVoidVerified', 'setPreview', 'setVoidTarget', 'setPayoutFresh']) context[name] ||= value => events.push([name, value]);
  vm.runInNewContext(compile(`exports.execute = ${variables.get('execute')};`), context); context.execute = context.exports.execute;
  return { context, events };
}

test('only a selected unambiguous positive bank row and explicitly eligible payout can preview', () => {
  assert.equal(bank.bankMatchReady(statement, row, payout), true);
  for (const candidate of [undefined, { ...row }, { ...row, ambiguous: true }, { ...row, amount_minor: 0 }]) assert.equal(bank.bankMatchReady(statement, candidate, payout), false);
  for (const patch of [{ amount_minor: 9652 }, { eligible: false }, { status: 'pending' }, { automatic: false }, { currency: 'CAD' }]) assert.equal(bank.bankMatchReady(statement, row, { ...payout, ...patch }), false);
  assert.equal(bank.bankMatchReady(null, row, payout), false);
});

test('owner confirmation needs an explicit checkbox, meaningful note and unchanged valid evidence', () => {
  assert.equal(bank.bankMatchConfirmReady(preview, true, '公司流水核对完成'), true);
  for (const [item, checked, note] of [[preview, false, '核对完成'], [preview, true, '  '], [preview, true, 'ab'], [preview, true, 'x'.repeat(1001)], [{ ...preview, writes_ledger: true }, true, '核对完成'], [{ ...preview, payout: { ...payout, status: 'failed' } }, true, '核对完成'], [{ ...preview, bank_row: { ...row, ambiguous: true } }, true, '核对完成']]) assert.equal(bank.bankMatchConfirmReady(item, checked, note), false);
});

test('statement mapping requires distinct real columns and an explicit company account marker', () => {
  const headers = ['Date', 'Amount', 'Description', 'ID'];
  const columns = { account_label: '公司运营', currency: 'USD', date_format: 'mdy', date_column: 'Date', amount_column: 'Amount', description_column: 'Description', reference_column: 'ID' };
  assert.equal(bank.bankColumnsError(columns, headers), '');
  for (const patch of [{ account_label: 'x' }, { amount_column: 'Description' }, { date_column: '' }, { reference_column: 'Date' }, { currency: 'CAD' }, { date_format: 'dmy' }]) assert.notEqual(bank.bankColumnsError({ ...columns, ...patch }, headers), '');
});

test('CSV accepts UTF-8 bytes only and enforces extension and 1 MB before any API', () => {
  const bytes = new TextEncoder().encode('日期,金额,摘要\n2026-11-13,96.51,Stripe').buffer;
  assert.match(bank.decodeBankCsv('公司流水.CSV', bytes), /Stripe/);
  for (const [name, value] of [['statement.pdf', bytes], ['empty.csv', new ArrayBuffer(0)], ['large.csv', new ArrayBuffer(bank.BANK_CSV_MAX_BYTES + 1)], ['bad.csv', new Uint8Array([0xff, 0xfe, 0x80]).buffer]]) assert.throws(() => bank.decodeBankCsv(name, value));
});

test('missing or malformed response values are never converted to zero or verified bank receipts', () => {
  assert.deepEqual(bank.readBankOverview(overview), overview); assert.equal(bank.bankMoney(9651), 'USD 96.51');
  for (const amount of [undefined, null, 0, -1, 1.5, '9651']) assert.equal(bank.bankMoney(amount), '金额待确认');
  for (const value of [undefined, { ...overview, total: null }, { ...overview, ledger_writes: true }]) assert.throws(() => bank.readBankOverview(value));
  assert.equal(bank.readBankStatement(statement).rows[0].ambiguous, false);
  for (const value of [{ ...statement, rows: [row, row] }, { ...statement, token: 'wrong' }, { ...statement, rows: [{ ...row, currency: 'CAD' }] }]) assert.throws(() => bank.readBankStatement(value));
  assert.throws(() => bank.readBankPayoutPage({ items: [payout], has_more: true, next_cursor: null, read_only: true, bank_deposit_proven: false }));
  assert.throws(() => bank.readBankMatchPreview({ ...preview, requires_owner_confirmation: false }));
  assert.throws(() => bank.readBankMatchPreview({ ...preview, bank_row: { ...row, date: '2026-02-30' } }));
  assert.doesNotThrow(() => bank.readBankInspection({ headers: ['Date', 'Amount'], sample: [[], ['2026-11-13', '96.51']], row_count: 2, currency: 'USD', writes_ledger: false }));
});

test('actor, role, session and latest request changes reject replies before effect cleanup', () => {
  const guard = new bank.BankRequestGuard(), ticket = guard.begin('ownerA:super_admin', 'sessionA');
  assert.equal(guard.current(ticket, 'ownerA:super_admin', 'sessionA'), true);
  assert.equal(guard.current(ticket, 'ownerA:operations', 'sessionA'), false);
  assert.equal(guard.current(ticket, 'ownerB:super_admin', 'sessionA'), false);
  assert.equal(guard.current(ticket, 'ownerA:super_admin', 'sessionB'), false);
  guard.begin('ownerA:super_admin', 'sessionA'); assert.equal(guard.current(ticket, 'ownerA:super_admin', 'sessionA'), false);
  const latest = guard.begin('ownerA:super_admin', 'sessionA'); guard.invalidate(); assert.equal(guard.current(latest, 'ownerA:super_admin', 'sessionA'), false);
});

test('actual workspace entry reads local matches only and never reads Stripe payouts automatically', async () => {
  const calls = [], { context } = runtime({ api: async path => { calls.push(path); return overview; }, readBankOverview: bank.readBankOverview });
  vm.runInNewContext(compile(`exports.load = ${variables.get('loadOverview')};`), context); await context.exports.load();
  assert.deepEqual(calls, ['/bank/overview']);
  assert.equal(componentSource.includes('useAutoRefresh'), false);
});

test('deferred local reply cannot repopulate data after role or session changes in the same mounted render gap', async () => {
  for (const change of ['role', 'actor', 'session']) {
    let resolve; const { context, events } = runtime({ api: () => new Promise(done => { resolve = done; }), readBankOverview: bank.readBankOverview });
    vm.runInNewContext(compile(`exports.load = ${variables.get('loadOverview')};`), context); const pending = context.exports.load();
    if (change === 'role') context.liveScope.current.allowed = false;
    if (change === 'actor') context.liveScope.current.key = 'ownerB:sessionA';
    if (change === 'session') context.getAuthSessionEpoch = () => 'sessionB';
    resolve(overview); await pending; assert.equal(events.some(([name]) => name === 'setOverview'), false);
  }
});

test('permission failures clear all sensitive sources and mutation uncertainty requires rereading', async () => {
  for (const status of [401, 403, 404]) {
    const { context, events } = runtime(); await context.exports.execute('payouts', async () => { throw { status }; });
    assert.equal(events.some(([name, value]) => name === 'setOverview' && value === null), true); assert.equal(events.some(([name]) => name === 'clear'), true); assert.equal(events.some(([name, value]) => name === 'setDenied' && value === true), true);
  }
  const { context, events } = runtime(); await context.exports.execute('confirm', async () => { throw { status: 503 }; }, true); assert.equal(events.some(([name, value]) => name === 'setUncertain' && value === true), true);
  let retried = false; await context.exports.execute('confirm', async () => { retried = true; }); assert.equal(retried, false);
  await context.exports.execute('overview', async () => { retried = true; }); assert.equal(retried, true);
});

test('StrictMode remount or a newer operation cannot be unlocked by an old late promise', async () => {
  const { context } = runtime(); let oldResolve, newResolve;
  const old = context.exports.execute('overview', () => new Promise(resolve => { oldResolve = resolve; }));
  context.guard.current.invalidate(); context.inFlight.current = null;
  const latest = context.exports.execute('payouts', () => new Promise(resolve => { newResolve = resolve; }));
  const latestLock = context.inFlight.current; oldResolve(); await old; assert.equal(context.inFlight.current, latestLock);
  newResolve(); await latest; assert.equal(context.inFlight.current, null);
});

test('actual confirmation sends only the server token, owner acknowledgment and note; never an income write', async () => {
  let pending; const calls = [];
  const context = { exports: {}, preview, denied: false, uncertain: false, payoutFresh: true, verified: true, note: '公司流水核对完成', bankMatchConfirmReady: bank.bankMatchConfirmReady, bankEvidenceScope: bank.bankEvidenceScope, readBankOverview: bank.readBankOverview, setOverview() {}, clearWorkflow() {}, setMessage() {}, api: async (...args) => { calls.push(args); return { item: { id: 9, payout_id: payout.id, amount_minor: 9651, currency: 'USD', account_label: '公司运营', bank_date: row.date, bank_reference: 'bank-123', payment_ids: [], review_ids: [], status: 'statement_manually_matched', note: '核对完成' }, ledger_writes: false }; } };
  context.execute = (kind, fn) => { assert.equal(kind, 'confirm'); pending = fn(() => true); };
  vm.runInNewContext(compile(`exports.confirm = ${variables.get('confirm')};`), context); context.exports.confirm(); await pending;
  assert.equal(calls.length, 1); assert.equal(calls[0][0], '/bank/matches/confirm'); assert.deepEqual(plain(calls[0][2]), { token, owner_verified: true, note: '公司流水核对完成' });
  calls.length = 0; context.verified = false; context.exports.confirm(); assert.equal(calls.length, 0);
});

test('payout pages preserve reported noncredit exclusions without inventing a zero for old responses', () => {
  const page = { items: [payout], has_more: true, next_cursor: 'po_noncredit_last', read_only: true, bank_deposit_proven: false };
  assert.equal(Object.hasOwn(bank.readBankPayoutPage(page), 'excluded_noncredit_count'), false);
  for (const count of [0, 1, 10, Number.MAX_SAFE_INTEGER]) assert.equal(bank.readBankPayoutPage({ ...page, excluded_noncredit_count: count }).excluded_noncredit_count, count);
  for (const count of [undefined, null, -1, 0.5, '1', true, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => bank.readBankPayoutPage({ ...page, excluded_noncredit_count: count }));
  assert.throws(() => bank.readBankPayoutPage({ ...page, items: [{ ...payout, amount_minor: -100 }], excluded_noncredit_count: 1 }));
  assert.equal(bank.readBankPayoutPage({ ...page, items: [], excluded_noncredit_count: 10 }).next_cursor, 'po_noncredit_last');
});

test('only an explicit positive safe exclusion count produces a page-scoped notice, never a bank receipt claim', () => {
  const notice = bank.bankPayoutExclusionNotice(1);
  assert.match(notice, /本页.*1.*零额或负数/); assert.match(notice, /这里只核对银行入账/); assert.doesNotMatch(notice, /已经到账|已匹配|累计/);
  for (const value of [undefined, null, 0, -1, 0.5, '1', NaN, Infinity]) assert.equal(bank.bankPayoutExclusionNotice(value), null);
});

test('actual owner-triggered payout reader preserves the provider cursor and uses the latest page exclusion count rather than summing pages', async () => {
  const calls = [], counts = [], pages = [
    { items: Array.from({ length: 9 }, (_, index) => ({ ...payout, id: `po_credit${index}` })), has_more: true, next_cursor: 'po_noncredit_last', excluded_noncredit_count: 1, read_only: true, bank_deposit_proven: false },
    { items: [], has_more: false, next_cursor: null, excluded_noncredit_count: 2, read_only: true, bank_deposit_proven: false },
    { items: [payout], has_more: false, next_cursor: null, read_only: true, bank_deposit_proven: false },
  ];
  let pending, retained = [];
  const context = { exports: {}, overview, overviewError: false, denied: false, uncertain: false, payoutFresh: false, cursor: null, readBankPayoutPage: bank.readBankPayoutPage, setPayouts: update => { retained = update(retained); }, setExcludedNoncreditCount: value => counts.push(value), setPayoutFresh: value => { context.payoutFresh = value; }, setPayoutMore() {}, setCursor: value => { context.cursor = value; }, setPayoutId() {}, clearConfirmation() {}, api: async path => { calls.push(path); return pages.shift(); }, execute: (kind, action) => { assert.equal(kind, 'payouts'); pending = action(() => true); } };
  vm.runInNewContext(compile(`exports.read = ${variables.get('loadPayouts')};`), context);
  context.exports.read(); await pending; assert.equal(retained.length, 9); assert.equal(counts[0], 1); assert.equal(context.cursor, 'po_noncredit_last');
  context.exports.read(true); await pending; assert.equal(calls[1], '/bank/payouts?starting_after=po_noncredit_last'); assert.equal(retained.length, 9); assert.equal(counts[1], 2);
  context.exports.read(); await pending; assert.equal(retained.length, 1); assert.equal(counts[2], undefined); assert.equal(bank.bankPayoutExclusionNotice(counts[2]), null);
});

test('manual payouts require explicit payout-only scope while automatic complete scope stays separate', () => {
  const manual = { ...payout, automatic: false, evidence_scope: 'payout_only' };
  const automatic = { ...payout, evidence_scope: 'complete_transactions' };
  const page = items => ({ items, has_more: false, next_cursor: null, read_only: true, bank_deposit_proven: false, excluded_noncredit_count: 0 });
  assert.equal(bank.readBankPayoutPage(page([manual, automatic])).items.length, 2);
  assert.equal(bank.bankPayoutEligible(manual), true); assert.equal(bank.bankMatchReady(statement, row, manual), true);
  for (const candidate of [{ ...manual, evidence_scope: undefined }, { ...manual, evidence_scope: 'complete_transactions' }, { ...automatic, evidence_scope: 'payout_only' }, { ...automatic, evidence_scope: 'unknown' }, { ...automatic, evidence_scope: 'bad' }, { ...manual, eligible: false }]) {
    assert.equal(bank.bankPayoutEligible(candidate), false); assert.throws(() => bank.readBankPayoutPage(page([candidate])));
  }
  const missing = { ...payout, automatic: false }; assert.equal(bank.bankPayoutEligible(missing), false); assert.throws(() => bank.readBankPayoutPage(page([missing])));
  assert.equal(bank.bankPayoutEligible(payout), true); assert.equal(bank.bankEvidenceScope(payout), 'unknown');
});

test('preview scope cannot be downgraded or fabricated: manual has zero transactions and no payment links; auto has positive complete detail', () => {
  const manual = { ...preview, payout: { ...payout, automatic: false, evidence_scope: 'payout_only' }, evidence_scope: 'payout_only', transaction_count: 0 };
  const automatic = { ...preview, payout: { ...payout, evidence_scope: 'complete_transactions' }, evidence_scope: 'complete_transactions' };
  assert.equal(bank.readBankMatchPreview(manual).transaction_count, 0); assert.equal(bank.bankMatchConfirmReady(manual, true, '核对银行整笔'), true);
  assert.equal(bank.readBankMatchPreview(automatic).transaction_count, 3);
  for (const candidate of [{ ...manual, transaction_count: 1 }, { ...manual, transaction_count: null }, { ...manual, transaction_count: '0' }, { ...manual, payment_ids: [7] }, { ...manual, review_ids: [8] }, { ...manual, payout: { ...manual.payout, automatic: true } }, { ...manual, evidence_scope: 'complete_transactions' }, { ...manual, evidence_scope: undefined }, { ...automatic, transaction_count: 0 }, { ...automatic, evidence_scope: 'payout_only' }, { ...automatic, payout }, { ...preview, evidence_scope: 'unknown' }]) assert.throws(() => bank.readBankMatchPreview(candidate));
  assert.equal(bank.readBankMatchPreview(preview).transaction_count, 3); assert.equal(bank.bankEvidenceScope(preview), 'unknown');
  assert.throws(() => bank.readBankMatchPreview({ ...preview, transaction_count: 0 }));
});

test('saved manual bank evidence can never carry customer payment/review associations; legacy scope stays unknown', () => {
  const saved = { id: 9, payout_id: payout.id, amount_minor: 9651, currency: 'USD', account_label: '公司运营', bank_date: row.date, bank_reference: 'bank-123', payment_ids: [], review_ids: [], status: 'statement_manually_matched', note: '只核对整笔金额', evidence_scope: 'payout_only' };
  const read = value => bank.readBankOverview({ ...overview, items: [value], total: 1 });
  assert.equal(read(saved).items[0].evidence_scope, 'payout_only');
  for (const patch of [{ payment_ids: [7] }, { review_ids: [8] }, { evidence_scope: null }, { evidence_scope: 'unsupported' }]) assert.throws(() => read({ ...saved, ...patch }));
  const legacy = { ...saved }; delete legacy.evidence_scope;
  assert.equal(bank.bankEvidenceScope(read(legacy).items[0]), 'unknown');
  assert.equal(bank.bankEvidenceScope(read({ ...legacy, evidence_scope: 'unknown', payment_ids: [7] }).items[0]), 'unknown');
  assert.match(bank.bankSavedEvidenceLabel(legacy), /未记录/); assert.doesNotMatch(bank.bankSavedEvidenceLabel(legacy), /完整.*已核验/);
});

test('manual and historical copy never claim per-customer receipt verification or zero verified transactions', () => {
  const manual = { ...preview, payout: { ...payout, automatic: false, evidence_scope: 'payout_only' }, evidence_scope: 'payout_only', transaction_count: 0 };
  assert.match(bank.bankPayoutEvidenceLabel(manual.payout), /手动结算.*仅核对银行整笔金额.*未核验所含客户收款/);
  assert.match(bank.bankMatchEvidenceLabel(manual), /未核验所含客户收款/); assert.doesNotMatch(bank.bankMatchEvidenceLabel(manual), /已核验 0/);
  assert.match(bank.bankOwnerConfirmation(manual), /整笔金额.*不代表已核验客户收款.*不关联或新增收入/);
  assert.match(bank.bankMatchEvidenceLabel(preview), /范围未记录/); assert.doesNotMatch(bank.bankMatchEvidenceLabel(preview), /已核验 3/);
  assert.match(bank.bankOwnerConfirmation(preview), /历史预览未记录/);
});

test('actual manual confirmation still submits token only and rejects a result that adds any payment link or changes scope', async () => {
  const manual = { ...preview, payout: { ...payout, automatic: false, evidence_scope: 'payout_only' }, evidence_scope: 'payout_only', transaction_count: 0 };
  const saved = { id: 9, payout_id: payout.id, amount_minor: 9651, currency: 'USD', account_label: '公司运营', bank_date: row.date, bank_reference: 'bank-123', payment_ids: [], review_ids: [], status: 'statement_manually_matched', note: '核对整笔', evidence_scope: 'payout_only' };
  for (const patch of [{}, { payment_ids: [99] }, { review_ids: [98] }, { evidence_scope: 'complete_transactions' }, { evidence_scope: 'unknown' }]) {
    let pending, changed = false; const calls = [];
    const context = { exports: {}, preview: manual, denied: false, uncertain: false, payoutFresh: true, verified: true, note: '只核对整笔金额', bankMatchConfirmReady: bank.bankMatchConfirmReady, bankEvidenceScope: bank.bankEvidenceScope, readBankOverview: bank.readBankOverview, setOverview() { changed = true; }, clearWorkflow() {}, setMessage() {}, api: async (...args) => { calls.push(args); return { item: { ...saved, ...patch }, ledger_writes: false }; }, execute: (kind, fn) => { assert.equal(kind, 'confirm'); pending = fn(() => true); } };
    vm.runInNewContext(compile(`exports.confirm = ${variables.get('confirm')};`), context); context.exports.confirm();
    if (Object.keys(patch).length) { await assert.rejects(pending); assert.equal(changed, false); } else { await pending; assert.equal(changed, true); }
    assert.equal(calls[0][0], '/bank/matches/confirm'); assert.deepEqual(plain(calls[0][2]), { token, owner_verified: true, note: '只核对整笔金额' }); assert.equal('evidence_scope' in calls[0][2], false);
  }
});
