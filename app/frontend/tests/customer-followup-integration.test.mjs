import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const compile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const helpersContext = { exports: {} };
vm.runInNewContext(compile(readFileSync(new URL('../src/lib/customer-followup-statuses.ts', import.meta.url), 'utf8')), helpersContext);
const helpers = helpersContext.exports;
const dictSource = readFileSync(new URL('../src/lib/dict-config.ts', import.meta.url), 'utf8');
const dictAst = ts.createSourceFile('dict-config.ts', dictSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
let defaults;
function findDefaults(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(dictAst) === 'defaultBusinessDictConfig') defaults = vm.runInNewContext(`(${node.initializer.getText(dictAst)})`);
  ts.forEachChild(node, findDefaults);
}
findDefaults(dictAst);
const source = readFileSync(new URL('../src/pages/Customers.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('Customers.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const initializers = new Map();
let managerSaved, stageDisabled, stageChange, badgeLabel;
function scan(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) initializers.set(node.name.text, node.initializer.getText(ast));
  if (ts.isJsxSelfClosingElement(node)) {
    const attrs = new Map(node.attributes.properties.filter(ts.isJsxAttribute).map(attr => [attr.name.text, attr.initializer?.expression?.getText(ast)]));
    if (node.tagName.getText(ast) === 'CustomerFollowUpStatusManager') managerSaved = attrs.get('onSaved');
    if (node.tagName.getText(ast) === 'NativeSelect' && attrs.get('value') === 'followForm.stage') { stageDisabled = attrs.get('disabled'); stageChange = attrs.get('onChange'); }
  }
  if (ts.isCallExpression(node) && node.expression.getText(ast) === 'getCustomerFollowUpStatusLabel' && node.arguments[1]?.getText(ast) === 'f.stage') badgeLabel = node.getText(ast);
  ts.forEachChild(node, scan);
}
scan(ast);
assert.ok(managerSaved && stageDisabled && stageChange && badgeLabel);
const bindings = ['emptyFollowForm', 'editingFollowRecord', 'linkedFollowOpportunityId', 'followStageOptions', 'openEditFollow', 'handleSaveFollow', 'canManageFollowStatuses'];
for (const name of bindings) assert.ok(initializers.has(name));
const plain = value => JSON.parse(JSON.stringify(value));

function fixture({ record, form = {}, config = defaults, role = 'admin', ...overrides } = {}) {
  const writes = [], errors = [], changes = [];
  const sandbox = {
    ...helpers, exports: {}, Date, URLSearchParams, dictConfig: config, systemRole: role,
    followUps: record ? [record] : [], editingFollowId: record?.id ?? null,
    followForm: { contact_method: 'phone', content: 'Synthetic follow-up content', customer_needs: '', customer_pain_points: '', has_quoted: false, quote_plan: '', close_probability: 30, stage: record?.stage ?? helpers.getDefaultCustomerFollowUpStatus(config), next_follow_date: '', ...form },
    selectedCustomer: { id: 20, status: 'closed' }, employee: { name: 'Synthetic operator' }, savingFollow: false, detailWriteBlocked: false, canEditFollowUp: true, canCreateFollowUp: true,
    client: { entities: { follow_ups: { create: async request => { writes.push({ method: 'create', ...plain(request) }); }, update: async request => { writes.push({ method: 'update', ...plain(request) }); } } } },
    toast: { error: value => errors.push(value), success: value => changes.push(['success', value]) }, logOperation: value => changes.push(['audit', plain(value)]), followDraft: { markSaved: () => changes.push(['markSaved']) },
    reloadFollowUps: async () => record ? [record] : [], searchParams: new URLSearchParams(), businessToday: '2026-11-13', setSearchParams() {},
    ...overrides,
  };
  for (const name of ['setFollowForm', 'setEditingFollowId', 'setShowFollowForm', 'setShowFollowStatusManager', 'setSavingFollow']) sandbox[name] = value => { const key = name[3].toLowerCase() + name.slice(4); sandbox[key] = typeof value === 'function' ? value(sandbox[key]) : value; changes.push([key]); };
  const code = bindings.map(name => `const ${name} = ${initializers.get(name)};`).join('\n') + `\nconst managerSaved = ${managerSaved}; const stageChange = ${stageChange}; const disabled = ${stageDisabled}; const renderLabel = f => ${badgeLabel}; Object.assign(exports,{${bindings.join(',')},managerSaved,stageChange,disabled,renderLabel});`;
  vm.runInNewContext(compile(code), sandbox);
  return { actions: sandbox.exports, sandbox, writes, errors, changes };
}

test('new manual service follow-up uses the first active configured stage without altering customer state', async () => {
  const config = { ...defaults, customerFollowUpStatuses: 'awaiting_reply:待客户回复,in_service:正常服务' };
  const f = fixture({ config });
  assert.equal(f.actions.emptyFollowForm.stage, 'awaiting_reply');
  assert.equal(f.actions.followStageOptions[0].value, 'awaiting_reply');
  await f.actions.handleSaveFollow();
  assert.equal(f.writes.length, 1); assert.equal(f.writes[0].method, 'create');
  assert.equal(f.writes[0].data.stage, 'awaiting_reply');
  assert.equal(f.writes[0].data.customer_id, 20);
  assert.ok(!Object.hasOwn(f.writes[0].data, 'opportunity_id'));
  assert.equal(f.sandbox.selectedCustomer.status, 'closed');
});

test('new records cannot save archived, legacy or unconfigured stages', async () => {
  for (const stage of ['communicating', 'retired', 'unknown_legacy', '']) {
    const f = fixture({ config: { ...defaults, customerFollowUpStatusArchive: 'retired:已停用阶段' }, form: { stage } });
    await f.actions.handleSaveFollow(); assert.equal(f.writes.length, 0); assert.ok(f.errors.some(message => message.includes('启用')));
  }
});

test('content-only edits preserve legacy and archived raw stages, with explicit history options', async () => {
  for (const stage of ['communicating', 'follow_later', 'retired', 'constructor']) {
    const record = { id: 101, stage, content: 'old body' };
    const f = fixture({ record, config: { ...defaults, customerFollowUpStatusArchive: 'retired:已停用阶段' } });
    assert.equal(f.actions.followStageOptions[0].value, stage);
    assert.match(f.actions.followStageOptions[0].label, /历史阶段|已停用/);
    await f.actions.handleSaveFollow(); assert.equal(f.writes.length, 1); assert.equal(f.writes[0].data.stage, stage);
  }
});

test('an old blank/null stage is readable and omitted from a content-only edit', async () => {
  const record = { id: 101, stage: null, content: 'Historical body to edit' };
  const f = fixture({ record, form: { stage: '' } });
  f.actions.openEditFollow(record);
  assert.equal(f.sandbox.followForm.stage, '');
  assert.equal(f.actions.followStageOptions[0].label, '历史阶段：未记录');
  await f.actions.handleSaveFollow();
  assert.equal(f.writes.length, 1); assert.ok(!Object.hasOwn(f.writes[0].data, 'stage'));
});

test('linked opportunity rows keep fixed semantics, disable stage changes and omit stage on update', async () => {
  const record = { id: 101, stage: 'quoted', opportunity_id: 55 };
  const f = fixture({ record });
  assert.equal(f.actions.disabled, true);
  assert.deepEqual(plain(f.actions.followStageOptions), [{ value: 'quoted', label: '已报价' }]);
  f.actions.stageChange('in_service');
  assert.equal(f.sandbox.followForm.stage, 'quoted');
  f.sandbox.followForm.stage = 'in_service'; // Even a stale/manipulated draft cannot overwrite a linked stage.
  await f.actions.handleSaveFollow();
  assert.equal(f.writes.length, 1); assert.ok(!Object.hasOwn(f.writes[0].data, 'stage'));
  assert.ok(!Object.hasOwn(f.writes[0].data, 'opportunity_id'));
  assert.equal(record.stage, 'quoted');
  assert.equal(f.actions.renderLabel(record), '已报价');
});

test('linked empty historical stages remain empty through body edits', async () => {
  const f = fixture({ record: { id: 101, opportunity_id: 55, stage: null }, form: { stage: '' } });
  assert.equal(f.actions.followStageOptions[0].label, '未记录');
  assert.equal(f.actions.renderLabel({ opportunity_id: 55, stage: null }), '未记录');
  await f.actions.handleSaveFollow(); assert.equal(f.writes.length, 1); assert.ok(!Object.hasOwn(f.writes[0].data, 'stage'));
});

test('explicit unlinked service changes accept only currently active stages', async () => {
  const allowed = fixture({ record: { id: 101, stage: 'communicating' }, form: { stage: 'in_service' } });
  await allowed.actions.handleSaveFollow(); assert.equal(allowed.writes[0].data.stage, 'in_service');
  const denied = fixture({ record: { id: 101, stage: 'communicating' }, form: { stage: 'unknown_legacy' } });
  await denied.actions.handleSaveFollow(); assert.equal(denied.writes.length, 0);
});

test('the original refresh/permission/save locks still block all follow-up writes', async () => {
  for (const overrides of [{ detailWriteBlocked: true }, { savingFollow: true }, { canCreateFollowUp: false }, { selectedCustomer: null }]) {
    const f = fixture(overrides); await f.actions.handleSaveFollow(); assert.equal(f.writes.length, 0);
  }
  const deniedEdit = fixture({ record: { id: 101, stage: 'in_service' }, canEditFollowUp: false });
  await deniedEdit.actions.handleSaveFollow(); assert.equal(deniedEdit.writes.length, 0);
  const vanished = fixture({ editingFollowId: 999 });
  await vanished.actions.handleSaveFollow(); assert.equal(vanished.writes.length, 0);
  assert.ok(vanished.errors.some(message => message.includes('尚未核实')));
});

test('saving the service manager updates only an invalid new draft, leaving old edits untouched', () => {
  const fields = { customerFollowUpStatuses: 'awaiting_reply:待客户回复', customerFollowUpStatusArchive: 'in_service:正常服务' };
  const fresh = fixture(); fresh.actions.managerSaved(fields); assert.equal(fresh.sandbox.followForm.stage, 'awaiting_reply');
  const edited = fixture({ record: { id: 101, stage: 'communicating' } }); edited.actions.managerSaved(fields); assert.equal(edited.sandbox.followForm.stage, 'communicating');
  const linked = fixture({ record: { id: 101, stage: 'quoted', opportunity_id: 55 } }); linked.actions.managerSaved(fields); assert.equal(linked.sandbox.followForm.stage, 'quoted');
});

test('only admin roles receive the manager entry and historical labels remain safe text', () => {
  for (const role of ['admin', 'super_admin']) assert.equal(fixture({ role }).actions.canManageFollowStatuses, true);
  for (const role of ['ops', 'sales', 'finance', 'sales_partner']) assert.equal(fixture({ role }).actions.canManageFollowStatuses, false);
  const f = fixture();
  for (const stage of ['__proto__', 'constructor', 'toString']) assert.equal(f.actions.renderLabel({ stage }), stage);
  assert.equal(f.actions.renderLabel({ stage: 'follow_later' }), '后续再跟进');
  assert.equal(f.actions.renderLabel({ stage: 'service_follow_later' }), '后续跟进');
});

test('customer form removes WeChat editing and all create/update paths omit it while retaining stored history', async () => {
  let editableInput = false, contactsDescription;
  function inspect(node) {
    if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
      const attrs = new Map(node.attributes.properties.filter(ts.isJsxAttribute).map(attr => [attr.name.text, attr.initializer]));
      if (node.tagName.getText(ast) === 'Input' && attrs.get('value')?.expression?.getText(ast) === 'form.wechat') editableInput = true;
      if (node.tagName.getText(ast) === 'CustomerFormSection' && attrs.get('id')?.text === 'customer-form-contacts') contactsDescription = attrs.get('description')?.text;
    }
    ts.forEachChild(node, inspect);
  }
  inspect(ast);
  assert.equal(editableInput, false); assert.equal(contactsDescription, '客户编号与邮箱');
  const permissionContext = { exports: {} };
  vm.runInNewContext(compile(readFileSync(new URL('../src/lib/customer-permissions.ts', import.meta.url), 'utf8')), permissionContext);
  for (const mode of ['owner-create', 'ordinary-create', 'project-update', 'ordinary-update']) {
    const editing = mode.endsWith('update'), writes = [], errors = [];
    const historical = { id: 99, business_name: '原客户', contact_name: '负责人', phone: '+1 415 555 0100', country: 'US', wechat: 'historical-contact-keep', status: 'closed' };
    let stored = { ...historical };
    const apply = (method, data) => { writes.push({ method, data: plain(data) }); stored = { ...stored, ...data }; return { data: stored }; };
    const form = { ...historical, customer_code: 'TEST-99', business_name: 'Edited synthetic customer', wechat: 'stale-draft-should-not-write', selected_platforms: [], interested_packages: [], interested_packages_snapshot: {}, sales_employee_id: '', monthly_orders: 0 };
    const sandbox = {
      exports: {}, Date, URLSearchParams, form, customers: editing ? [historical] : [], editingCustomer: historical, editingId: editing ? 99 : null, saving: false, customerProjectsLoading: false, customerProjectForms: [],
      canEditBasic: () => true, canAssignCustomer: () => false, canEditProjects: mode === 'project-update', isOwner: mode === 'owner-create' || mode === 'project-update', employee: { name: 'Synthetic operator' }, selectedCustomer: editing ? historical : null,
      parsePhoneNumber: () => ({ isValid: true }), activeCustomerProjectStatuses: new Set(), getPackageLabelForSnapshot: () => '', serializePackageSnapshot: () => '{}', editableCustomerPayload: permissionContext.exports.editableCustomerPayload,
      invokeWithAuth: async request => apply(request.method, request.data.customer), client: { entities: { customers: { create: async request => apply('POST', request.data), update: async request => apply('PUT', request.data) } } },
      toast: { error: value => errors.push(value), success() {} }, getErrorDetail: error => error.message, getNextAutoCode: () => 'TEST-99', commissionPartnerId: 'auto', commissionEffectiveFrom: '2026-11-13', customerCreationFeedback: () => ({ canOpen: true, message: 'created' }),
      setSaving() {}, setCustomers() {}, setShowForm() {}, customerDraft: { markSaved() {} }, loadCustomers: async () => {}, loadCustomerDetail: async () => {}, logOperation() {},
    };
    vm.runInNewContext(compile(`exports.save = ${initializers.get('handleSave')};`), sandbox);
    await sandbox.exports.save();
    assert.deepEqual(errors, [], mode); assert.equal(writes.length, 1, mode);
    assert.ok(!Object.hasOwn(writes[0].data, 'wechat'), mode);
    if (editing) assert.equal(stored.wechat, 'historical-contact-keep', mode);
    assert.equal(form.wechat, 'stale-draft-should-not-write', mode);
  }
});

test('phone and desktop share four primary destinations and permission-filtered More tools', () => {
  const evaluate = (isMobile, allowed = new Set(['subscriptions', 'opportunities', 'renewals', 'info', 'contacts', 'followups', 'deals', 'materials', 'ai_copy', 'media', 'logs']), finance = true, selected = 'opportunities') => {
    const sandbox = { exports: {}, isMobile, canViewFinanceStatus: finance, c: {}, contacts: [], followUps: [], deals: [], renewalRows: [], customerCanReadTab: (_, tab) => allowed.has(tab), selectedCustomerTab: selected };
    vm.runInNewContext(compile(['primaryDetailTabs', 'secondaryDetailTabs', 'secondaryDetailTabValues', 'activeSecondaryDetailTab'].map(name => `const ${name} = ${initializers.get(name)};`).join('\n') + '\nObject.assign(exports,{primaryDetailTabs,secondaryDetailTabs,activeSecondaryDetailTab});'), sandbox);
    return sandbox.exports;
  };
  const desktop = evaluate(false), mobile = evaluate(true);
  assert.deepEqual(plain(desktop.primaryDetailTabs.map(item => item.value)), ['overview', 'timeline', 'subscriptions', 'payments']);
  assert.deepEqual(plain(mobile.primaryDetailTabs.map(item => item.value)), plain(desktop.primaryDetailTabs.map(item => item.value)));
  assert.deepEqual(plain(desktop.primaryDetailTabs.map(item => item.label)), ['客户360', '时间线', '服务信息', '财务信息']);
  assert.deepEqual(plain(mobile.primaryDetailTabs.map(item => item.label)), ['概览', '动态', '服务', '财务']);
  assert.ok(desktop.secondaryDetailTabs.some(item => item.value === 'opportunities'));
  assert.ok(desktop.secondaryDetailTabs.some(item => item.value === 'renewals'));
  assert.equal(desktop.activeSecondaryDetailTab.label, '客户商机');
  const restricted = evaluate(false, new Set(['info']), false);
  assert.deepEqual(plain(restricted.primaryDetailTabs.map(item => item.value)), ['overview', 'timeline']);
  assert.deepEqual(plain(restricted.secondaryDetailTabs.map(item => item.value)), ['info']);
  assert.equal(restricted.activeSecondaryDetailTab, undefined);
});

test('the unified More control keeps selected values and the original tab-change callback', () => {
  let onChange, value;
  function inspect(node) {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === 'NativeSelect') {
      const attrs = new Map(node.attributes.properties.filter(ts.isJsxAttribute).map(attr => [attr.name.text, attr.initializer?.expression?.getText(ast)]));
      if (attrs.get('value')?.startsWith('secondaryDetailTabValues.has(')) { value = attrs.get('value'); onChange = attrs.get('onChange'); }
    }
    ts.forEachChild(node, inspect);
  }
  inspect(ast); assert.ok(onChange && value);
  const changed = [], sandbox = { exports: {}, secondaryDetailTabValues: new Set(['opportunities', 'renewals', 'followups']), selectedCustomerTab: 'renewals', handleDetailTabChange: next => changed.push(next) };
  vm.runInNewContext(compile(`exports.value = ${value}; exports.change = ${onChange};`), sandbox);
  assert.equal(sandbox.exports.value, 'renewals');
  sandbox.exports.change('followups'); sandbox.exports.change('');
  assert.deepEqual(changed, ['followups']);
});
