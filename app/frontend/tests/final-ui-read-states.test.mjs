import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const sources = new Map();
const source = name => {
  if (!sources.has(name)) sources.set(name, fs.readFileSync(new URL(`../src/pages/${name}.tsx`, import.meta.url), 'utf8'));
  return sources.get(name);
};
const parse = name => ts.createSourceFile(`${name}.tsx`, source(name), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const text = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(text).join('') : text(value.props?.children);
const find = (tree, predicate) => { const node = nodes(tree).find(predicate); assert.ok(node, 'Expected presentation control'); return node; };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function evaluate(code, context = {}) {
  const module = { exports: {} }, jsx = { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }), Fragment: 'Fragment' };
  const compiled = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(compiled, { ...context, module, exports: module.exports, require: name => name === 'react/jsx-runtime' ? jsx : {}, console: { error() {} }, URLSearchParams, Set, Map });
  return module.exports;
}
function initializer(name, variable) {
  const file = parse(name); let found;
  const visit = node => { if (ts.isVariableDeclaration(node) && node.name.getText(file) === variable) found = node.initializer; ts.forEachChild(node, visit); };
  visit(file); assert.ok(found, `${name}.${variable}`); return found.getText(file);
}
function alertExpression(name, message) {
  const file = parse(name); let found;
  const visit = node => {
    if (ts.isJsxExpression(node) && node.expression && node.expression.getText(file).includes(message)
      && node.expression.getText(file).startsWith('loadError &&')) found = node.expression;
    ts.forEachChild(node, visit);
  };
  visit(file); assert.ok(found, `${name} stale alert`); return found.getText(file);
}
function readFixture(name) {
  const state = { rows: [{ id: 91, business_name: 'VERIFIED OLD CUSTOMER' }], deals: [{ id: 92, customer_name: 'VERIFIED OLD DEAL' }], customers: [{ id: 91 }], data: { summary: { pending_count: 0 }, entries: [] }, loadError: null, loading: false, refreshing: false, loadedDashboardScope: 'owner:all' };
  const requests = [], scope = { current: 'owner:all' }, sequence = { current: 0 }, actor = { current: 'owner' };
  const transport = (entity, options) => { const pending = deferred(); requests.push({ entity, options, ...pending }); return pending.promise; };
  const context = {
    loadSequence: sequence, loadRequestSeqRef: sequence, readScope: 'owner:all', readScopeRef: scope,
    dashboardReadScope: 'owner:all', dashboardReadScopeRef: scope, actorRef: actor, actorKey: 'owner',
    month: '', dataScope: 'all', employee: { id: 1, name: 'Synthetic Owner' }, canViewFinance: true,
    loadWithRetry: fn => fn(), decorateEffectiveSubscriptions: rows => rows,
    getLoadErrorMessage: error => error.message, errorMessage: error => error.message,
    client: { entities: Object.fromEntries(['customers', 'deals', 'subscriptions', 'payments'].map(entity => [entity, { query: options => transport(entity, options), queryAll: options => transport(entity, options) }])) },
    invokeWithAuth: options => transport('dashboard', options), loadAuxiliaryOptions() {},
  };
  for (const field of Object.keys(state)) context[`set${field[0].toUpperCase()}${field.slice(1)}`] = value => { state[field] = typeof value === 'function' ? value(state[field]) : value; };
  const run = evaluate(`module.exports = ${initializer(name, name === 'Commissions' ? 'load' : 'loadData')};`, context);
  return { state, context, scope, sequence, actor, requests, run: () => run(false), resolveBatch: from => requests.slice(from).forEach(request => request.resolve({ data: { items: [] } })) };
}
function salesAlert(name, fixture) {
  const context = { Button: 'button', rows: fixture.state.rows, deals: fixture.state.deals, loadError: fixture.state.loadError, refreshing: fixture.state.refreshing, loadData: fixture.run };
  return evaluate(`module.exports = () => (${alertExpression(name, '数据可能已过期')});`, context)();
}

for (const name of ['Sales', 'Deals']) {
  test(`${name}: transient read failure preserves the prior snapshot, labels it stale, and offers GET retry`, async () => {
    const f = readFixture(name), prior = f.state[name === 'Sales' ? 'rows' : 'deals'];
    const pending = f.run(); f.requests[0].reject({ status: 503, message: 'Synthetic temporary read failure' }); await pending;
    assert.equal(f.state[name === 'Sales' ? 'rows' : 'deals'], prior);
    const alert = salesAlert(name, f); assert.equal(alert.props.role, 'alert'); assert.match(text(alert), /数据可能已过期/); assert.match(text(alert), /Synthetic temporary read failure/);
    const retry = find(alert, node => node.type === 'button' && text(node) === '重新读取'); retry.props.onClick();
    assert.equal(f.state.refreshing, true); assert.ok(f.requests.length > (name === 'Sales' ? 4 : 2));
    f.resolveBatch(name === 'Sales' ? 4 : 2); await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.state.loadError, null); assert.equal(f.state[name === 'Sales' ? 'rows' : 'deals'].length, 0);
    assert.ok(f.requests.every(request => request.options.limit === 1000));
  });
  for (const status of [401, 403, 404]) {
    test(`${name}: authorization failure ${status} withdraws retained records`, async () => {
      const f = readFixture(name), pending = f.run(); f.requests[0].reject({ response: { status }, message: 'Synthetic denied read' }); await pending;
      assert.equal(f.state[name === 'Sales' ? 'rows' : 'deals'].length, 0);
      assert.equal(salesAlert(name, f), false);
      assert.match(f.state.loadError, /denied read/);
    });
  }
  test(`${name}: a late earlier success cannot replace a newer failed-read warning`, async () => {
    const f = readFixture(name), first = f.run(), oldCount = f.requests.length, second = f.run();
    f.requests[oldCount].reject({ status: 503, message: 'NEWER READ FAILED' }); await second;
    f.requests.slice(0, oldCount).forEach(request => request.resolve({ data: { items: [] } })); await first;
    assert.equal(f.state.loadError, 'NEWER READ FAILED'); assert.equal(f.state[name === 'Sales' ? 'rows' : 'deals'].length, 1);
  });
  test(`${name}: pending results from a prior account scope are ignored`, async () => {
    const f = readFixture(name), pending = f.run(); f.scope.current = 'sales:2'; f.state.rows = []; f.state.deals = [];
    f.requests[0].reject({ status: 503, message: 'OLD ACCOUNT ERROR' }); await pending;
    assert.equal(f.state.loadError, null); assert.equal(f.state.rows.length, 0); assert.equal(f.state.deals.length, 0);
  });
}

function commissionReadGuard(state, currentScope = 'owner:all') {
  const code = source('Commissions'), start = code.indexOf('  const hasCurrentDashboard ='), end = code.indexOf('  return <div className="financial-workspace', start);
  assert.ok(start > 0 && end > start);
  return evaluate(`module.exports = () => { ${code.slice(start, end)} return { type: 'dashboard' }; };`, { ...state, dashboardReadScope: currentScope, PageLoadState: 'PageLoadState', load() {} })();
}

test('Commissions: first GET failure renders only failure/retry, without a zero count or empty-record claim', async () => {
  const f = readFixture('Commissions'); f.state.data = null; f.state.loadedDashboardScope = '';
  const pending = f.run(); f.requests[0].reject({ status: 503, message: 'FIRST DASHBOARD FAILED' }); await pending;
  const tree = commissionReadGuard(f.state); assert.notEqual(tree.type, 'dashboard');
  const failure = find(tree, node => node.type === 'PageLoadState'); assert.match(failure.props.error, /当前范围尚未成功读取/); assert.equal(typeof failure.props.onRetry, 'function');
  assert.doesNotMatch(text(tree), /暂无记录|0 笔|共 0 条/);
});

test('Commissions: verified empty response is a real zero dashboard, not a read failure', async () => {
  const f = readFixture('Commissions'), pending = f.run();
  f.requests[0].resolve({ data: { summary: { pending_count: 0 }, entries: [] } }); await pending;
  assert.equal(f.state.loadError, null); assert.equal(f.state.loadedDashboardScope, 'owner:all'); assert.equal(commissionReadGuard(f.state).type, 'dashboard');
});

test('Commissions: transient refresh keeps same-scope old data while a new month cannot claim that snapshot', async () => {
  const f = readFixture('Commissions'), prior = f.state.data, pending = f.run();
  f.requests[0].reject({ status: 503, message: 'DASHBOARD REFRESH FAILED' }); await pending;
  assert.equal(f.state.data, prior); assert.equal(commissionReadGuard(f.state).type, 'dashboard');
  const newMonth = commissionReadGuard(f.state, 'owner:2026-12'); assert.notEqual(newMonth.type, 'dashboard');
  const alert = evaluate(`module.exports = () => (${alertExpression('Commissions', '上次分润结果')});`, { Button: 'button', loadError: f.state.loadError, loading: false, load: f.run })();
  assert.match(text(alert), /上次分润结果/); assert.match(text(alert), /暂不能修改/); assert.equal(find(alert, node => node.type === 'button').props.disabled, false);
});

for (const status of [401, 403, 404]) {
  test(`Commissions: authorization failure ${status} clears dashboard and scope proof`, async () => {
    const f = readFixture('Commissions'), pending = f.run(); f.requests[0].reject({ status, message: 'Synthetic dashboard denied' }); await pending;
    assert.equal(f.state.data, null); assert.equal(f.state.loadedDashboardScope, ''); assert.notEqual(commissionReadGuard(f.state).type, 'dashboard');
  });
}

test('Finance: mobile stale warning retries the existing read handler and preserves its busy indication', () => {
  let reads = 0, busy = false;
  const context = { loadError: 'Synthetic finance source unavailable', hasFinanceData: true, loading: false, Button: 'button', setLoading: value => { busy = value; }, loadData: async () => { reads++; } };
  const render = () => evaluate(`module.exports = () => (${alertExpression('Finance', '上次核对结果')});`, { ...context, loading: busy })();
  const alert = render(); assert.match(text(alert), /数据可能已过期/); find(alert, node => node.type === 'button').props.onClick();
  assert.equal(reads, 1); assert.equal(busy, true); assert.equal(find(render(), node => node.type === 'button').props.disabled, true);
});

function dealCard(editable = true, overrides = {}) {
  const file = parse('Deals'); let renderer;
  const visit = node => { if (ts.isArrowFunction(node) && node.body.getText(file).includes('deal-mobile-primary-actions') && node.parameters.length === 1 && node.parameters[0].name.getText(file) === 'd') renderer = node; ts.forEachChild(node, visit); };
  visit(file); assert.ok(renderer);
  const called = [], d = { id: 7, customer_id: 91, customer_name: 'Synthetic Merchant', deal_date: '2026-11-13', deal_amount: 123, package_name: 'Synthetic Plan' };
  const context = { duplicateDealIds: new Set(), getPackageClassification: () => ({ currentLabel: 'Synthetic Plan' }), hasPermission: () => editable, productLabels: {}, cycleLabels: {}, generatingBoardId: null, boardsLoading: false, boardsError: false, existingBoard: () => null, Button: 'button', Badge: 'badge', DropdownMenu: 'menu', DropdownMenuTrigger: 'trigger', DropdownMenuContent: 'content', DropdownMenuItem: 'menuitem', DropdownMenuSeparator: 'separator', MoreHorizontal: 'icon', Edit: 'icon', ExternalLink: 'icon', ClipboardCheck: 'icon', navigate: url => called.push(['customer', url]), openBoard: value => called.push(['board', value.id]), openHandoff: value => called.push(['handoff', value.id]), openEditDeal: value => called.push(['edit', value.id]), window: { location: { pathname: '/deals', search: '?sales=1' } }, ...overrides };
  const tree = evaluate(`module.exports = ${renderer.getText(file)};`, context)(d);
  return { tree, called };
}

test('Deals: editable mobile card has one primary action and a complete more menu with unchanged callbacks', () => {
  const { tree, called } = dealCard(), actions = find(tree, node => node.props?.className?.includes('deal-mobile-primary-actions'));
  const buttons = nodes(actions).filter(node => node.type === 'button'); assert.equal(buttons.length, 2);
  find(actions, node => node.type === 'button' && text(node) === '交接安排').props.onClick();
  const menu = nodes(actions).filter(node => node.type === 'menuitem'); assert.deepEqual(menu.map(text), ['客户详情', '生成看板', '编辑成交']);
  menu[0].props.onSelect(); menu[1].props.onSelect(); menu[2].props.onSelect();
  assert.equal(called[0][0], 'handoff'); assert.equal(called[0][1], 7); assert.match(called[1][1], /detail=91&tab=deals&returnTo=/); assert.deepEqual(called.slice(2), [['board', 7], ['edit', 7]]);
  assert.ok(buttons.every(node => node.props.className.includes('min-h-11')));
});

test('Deals: read-only mobile card exposes customer detail without edit/handoff/board actions', () => {
  const { tree, called } = dealCard(false), actions = find(tree, node => node.props?.className?.includes('deal-mobile-primary-actions'));
  assert.equal(nodes(actions).filter(node => node.type === 'button').length, 1); assert.equal(nodes(actions).some(node => node.type === 'menuitem'), false);
  find(actions, node => node.type === 'button').props.onClick(); assert.equal(called.length, 1); assert.equal(called[0][0], 'customer');
});

for (const [flag, value] of [['boardsLoading', true], ['boardsError', true], ['generatingBoardId', 7]]) {
  test(`Deals: more-menu board action preserves its ${flag} lock`, () => {
    const { tree } = dealCard(true, { [flag]: value });
    const board = nodes(tree).find(node => node.type === 'menuitem' && /生成中|查看中|看板暂不可用/.test(text(node)));
    assert.ok(board); assert.equal(board.props.disabled, true);
  });
}
