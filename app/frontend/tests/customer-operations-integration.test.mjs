import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/pages/Customers.tsx', import.meta.url), 'utf8');
const file = ts.createSourceFile('Customers.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const compile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const variables = new Map(), declarations = new Map(); let contactAction, renewalEmpty, countryChange, queueOpen, queueCustomers;
function scan(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) variables.set(node.name.text, node.initializer.getText(file));
  if (ts.isFunctionDeclaration(node) && node.name) declarations.set(node.name.text, node.getText(file));
  if (ts.isIfStatement(node) && node.expression.getText(file) === 'canManageContacts && contacts.length === 0 && !primaryContact') contactAction = node.getText(file);
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(file) === 'TabsContent') {
    const value = node.openingElement.attributes.properties.find(attr => ts.isJsxAttribute(attr) && attr.name.text === 'value');
    if (value?.initializer?.text === 'renewals') {
      function findEmpty(n) { if (ts.isConditionalExpression(n) && n.condition.getText(file).includes('length === 0')) renewalEmpty = n.condition.getText(file); ts.forEachChild(n, findEmpty); }
      findEmpty(node);
    }
  }
  if (ts.isJsxSelfClosingElement(node)) {
    const attrs = new Map(node.attributes.properties.filter(ts.isJsxAttribute).map(attr => [attr.name.text, attr.initializer?.expression?.getText(file)]));
    if (node.tagName.getText(file) === 'NativeSelect' && attrs.get('value') === 'form.country') countryChange = attrs.get('onChange');
    if (node.tagName.getText(file) === 'CustomerWorkQueue') { queueOpen = attrs.get('onOpenCustomer'); queueCustomers = attrs.get('customers'); }
  }
  ts.forEachChild(node, scan);
}
scan(file);
assert.ok(contactAction && renewalEmpty && countryChange && queueOpen);
const plain = value => JSON.parse(JSON.stringify(value));
function pure(path) { const context = { exports: {} }; vm.runInNewContext(compile(fs.readFileSync(new URL(path, import.meta.url), 'utf8')), context); return context.exports; }
const presentation = pure('../src/lib/customer-operations-presentation.ts');

test('existing primary contact suppresses the missing-contact action without creating or merging records', () => {
  for (const customer of [{ contact_name: 'coco', phone: '+14155550100' }, { contact_name: 'coco' }, { phone: '+14155550100' }]) {
    const actions = [], context = { canManageContacts: true, contacts: [], primaryContact: presentation.getCustomerPrimaryContact(customer), customer360Actions: actions };
    vm.runInNewContext(compile(contactAction), context); assert.equal(actions.length, 0);
  }
  const actions = [], context = { canManageContacts: true, contacts: [], primaryContact: null, customer360Actions: actions };
  vm.runInNewContext(compile(contactAction), context); assert.equal(actions.length, 1); assert.equal(actions[0].key, 'contact');
  context.canManageContacts = false; actions.length = 0; vm.runInNewContext(compile(contactAction), context); assert.equal(actions.length, 0);
});

test('renewal-only authorized data controls renewal empty state independently of delivery data', () => {
  for (const [renewalRows, subscriptions, expected] of [[[{ id: 7 }], [], false], [[], [{ id: 9 }], true], [[], [], true]]) {
    const context = { exports: {}, renewalRows, subscriptions };
    vm.runInNewContext(compile(`exports.empty = ${renewalEmpty};`), context); assert.equal(context.exports.empty, expected);
  }
});

test('new customer location and industry stay unverified rather than silently becoming US/CA/restaurant', () => {
  const context = { exports: {} }; vm.runInNewContext(compile(`exports.form = ${variables.get('emptyForm')};`), context);
  assert.equal(context.exports.form.country, ''); assert.equal(context.exports.form.state, ''); assert.equal(context.exports.form.industry, '');
});

test('editing preserves missing and unknown location/industry values and existing snapshots', async () => {
  for (const customer of [{ id: 1, business_name: '门店', contact_name: '负责人', phone: '+14155550100' }, { id: 1, business_name: '门店', contact_name: '负责人', phone: '+14155550100', country: 'old-country', state: 'old-state', industry: 'old-industry' }]) {
    let form;
    const context = { exports: {}, canEditBasic: () => true, originalCustomerForm: {current:null}, parseMultiValue: () => [], parsePackageSnapshot: () => ({ original: '原套餐快照' }), customerPackageLabels: {}, isOwner: false, setForm: value => { form = value; }, setManualCityInput() {}, setEditingId() {}, setDuplicateWarning() {}, setShowForm() {}, setCustomerProjectForms() {}, setCustomerProjectsLoading() {} };
    vm.runInNewContext(compile(`exports.open = ${variables.get('openEdit')};`), context); await context.exports.open(customer);
    assert.equal(form.country, customer.country || ''); assert.equal(form.state, customer.state || ''); assert.equal(form.industry, customer.industry || ''); assert.equal(form.interested_packages_snapshot.original, '原套餐快照');
  }
});

test('a late project response from an edited customer cannot populate a fresh new merchant', async () => {
  let respond;
  const edited = { id: 1, business_name: '原门店' };
  let projectRows = [], loading = false;
  const context = {
    exports: {}, canEditBasic: () => true, originalCustomerForm: {current:null}, parseMultiValue: () => [], parsePackageSnapshot: () => ({}),
    customerPackageLabels: {}, isOwner: true, customerMountedRef: {current:true},
    originalProjectForms: {current:new Map()}, customerActor: 'owner', customerActorRef: {current:'owner'}, customerProjectRead: {current:0},
    setForm() {}, setManualCityInput() {}, setEditingId() {}, setDuplicateWarning() {}, setShowForm() {},
    setCustomerProjectForms(rows) { projectRows = rows; }, setCustomerProjectsLoading(value) { loading = value; },
    invokeWithAuth: () => new Promise(resolve => { respond = resolve; }), emptyForm: {}, setCommissionPartnerId() {},
    setCommissionEffectiveFrom() {}, businessToday: '2026-11-14',
  };
  vm.runInNewContext(compile(`exports.edit = ${variables.get('openEdit')}; exports.create = ${variables.get('openCreate')};`), context);
  const pending = context.exports.edit(edited);
  assert.equal(loading, true);
  context.exports.create();
  assert.equal(loading, false);
  respond({data:{items:[{id:98, business_line_code:'beauty_os'}]}});
  await pending;
  assert.deepEqual(plain(projectRows), []);
});

test('unverified options retain their exact raw values and country changes never select the first state', () => {
  const context = { exports: {} }; vm.runInNewContext(compile(declarations.get('customerFormOptions') + '\nexports.options = customerFormOptions;'), context);
  const options = context.exports.options('legacy-state', [{ value: 'CA', label: 'CA' }], '待核实州/省');
  assert.deepEqual(plain(options.map(option => option.value)), ['', 'legacy-state', 'CA']); assert.match(options[1].label, /原资料.*待核实/);
  for (const initial of [{ country: '', state: '', city: '' }, { country: '', state: 'CA', city: 'LA' }]) {
    let next;
    const fixture = { exports: {}, form: initial, setManualCityInput() {}, getStatesForCountry: () => [{ code: 'AL' }, { code: 'CA' }], setForm: value => { next = value; } };
    vm.runInNewContext(compile(`exports.change = ${countryChange};`), fixture); fixture.exports.change('US');
    assert.equal(next.state, initial.state); assert.equal(next.city, initial.city); assert.notEqual(next.state, 'AL');
  }
});


test('service links carry exact task/progress IDs and a safe customer return path', () => {
  const context = { exports: {}, URLSearchParams }; vm.runInNewContext(compile(declarations.get('customerServiceTarget') + '\nexports.target = customerServiceTarget;'), context);
  const problem = new URL(context.exports.target(43, 7), 'https://crm.invalid');
  assert.equal(problem.pathname, '/service-board'); assert.equal(problem.searchParams.get('progress_id'), '7'); assert.equal(problem.searchParams.get('detail_tab'), 'overview'); assert.equal(problem.searchParams.get('returnTo'), '/customers?detail=43&tab=subscriptions');
  const task = new URL(context.exports.target(43, 7, 92), 'https://crm.invalid'); assert.equal(task.searchParams.get('detail_tab'), 'tasks'); assert.equal(task.searchParams.get('task_id'), '92');
  for (const ids of [[0, 7], [43, -1], [43, 7, NaN], [43, 7, 0]]) assert.equal(context.exports.target(...ids), null);
});

test('task links require an actually loaded same-customer parent progress and page permission', () => {
  const context = { exports: {}, URLSearchParams, c: { id: 43 }, serviceProgresses: [{ id: 7, customer_id: 43 }, { id: 8, customer_id: 90 }], canAccess: () => true };
  vm.runInNewContext(compile(declarations.get('customerServiceTarget') + `\nconst progressTarget = ${variables.get('progressTarget')}; const taskTarget = ${variables.get('taskTarget')}; Object.assign(exports,{progressTarget,taskTarget});`), context);
  assert.ok(context.exports.taskTarget({ id: 92, service_progress_id: 7 }).includes('task_id=92'));
  assert.equal(context.exports.taskTarget({ id: 92, service_progress_id: 8 }), null); assert.equal(context.exports.taskTarget({ id: 92, service_progress_id: 999 }), null);
  context.canAccess = () => false; assert.equal(context.exports.taskTarget({ id: 92, service_progress_id: 7 }), null);
});

test('cooperation owner names resolve only from the already authorized employee list', () => {
  const context = { exports: {}, employeesList: [{ id: 1, name: '已授权运营' }] }; vm.runInNewContext(compile(`exports.owner = ${variables.get('cooperationOwner')};`), context);
  assert.equal(context.exports.owner({ ownerId: 1 }), '已授权运营'); assert.equal(context.exports.owner({ ownerId: 2 }), '已指定负责人'); assert.equal(context.exports.owner({}), '服务负责人待确认');
});

test('the work queue receives all loaded shells and opens only an authorized current customer', () => {
  assert.equal(queueCustomers, 'customers');
  const calls = [], context = { exports: {}, customers: [{ id: 43, accessible: true }, { id: 90, accessible: false }], customerPermissions: customer => ({ access_level: customer.accessible ? 'read_only' : 'none' }), openDetail: (...args) => calls.push(args) };
  vm.runInNewContext(compile(`exports.open = ${queueOpen};`), context); context.exports.open(43, 'renewals'); context.exports.open(90); context.exports.open(999);
  assert.equal(calls.length, 1); assert.equal(calls[0][0].id, 43); assert.equal(calls[0][1], 'renewals');
});
