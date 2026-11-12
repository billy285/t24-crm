import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { createRequire } from 'node:module';

// Reuse the existing real-workspace hook/API fixture without running its tests.
const fixtureUrl = new URL('./media-merchant-workflow.test.mjs', import.meta.url);
const fixture = fs.readFileSync(fixtureUrl, 'utf8').split('\ntest(')[0]
  .replace(/^import[^\n]+\n/, '')
  .replaceAll('import.meta.url', JSON.stringify(fixtureUrl.href));
const context = { assert, fs, vm, webcrypto, createRequire, URL, URLSearchParams, Date, Set, Map, AbortController, setImmediate, console };
vm.runInNewContext(fixture + '\nglobalThis.fixture = { harness, shellReady, projection, page, merchant, row, query, label, nodes, button, child, find, tick };', context);
const { harness, shellReady, projection, page, merchant, row, query, label, nodes, button, child, find, tick } = context.fixture;
const isProjection = node => Boolean(node.props?.data?.items && node.props?.onView && node.props?.onFilter);
const currentProjection = tree => find(tree, isProjection).props.data;
const hasProjection = tree => nodes(tree).some(isProjection);
const hasMerchants = tree => nodes(tree).some(node => typeof node.type === 'function' && node.type.name === 'MerchantList' && !node.props.compact);
const refresh = h => { button(h.render(), '刷新当前运营范围').props.onClick(); h.render(); h.effects(); return h.requests.at(-1); };
const assertReadOnly = h => assert.ok(h.requests.every(request => request.options.method === 'GET'));
function responseFor(request, items = [row()]) {
  const url = new URL(request.options.url, 'http://local');
  const q = { ...query, customerId: Number(url.searchParams.get('customer_id')) || null, platform: url.searchParams.get('platform'), view: url.searchParams.get('view'), start: url.searchParams.get('start'), end: url.searchParams.get('end') };
  return { data: projection(q, items) };
}
async function merchantsReady(h) {
  await shellReady(h);
  button(h.render(), '运营清单').props.onClick(); h.render(); h.effects();
  h.requests.at(-1).resolve({ data: page([merchant(1)]) }); await tick();
  return child(h.render(), 'MerchantList').props.page;
}

test('same-scope projection reload retains the verified tree until its new response arrives', async () => {
  const h = harness(); await shellReady(h);
  const previous = currentProjection(h.render()), request = refresh(h);
  assert.equal(currentProjection(h.render()), previous);
  assert.equal(find(h.render(), node => node.type === 'fieldset' && node.props['aria-label'] === '已读取运营记录').props.disabled, true);
  assert.match(label(h.render()), /正在更新当前范围/);
  request.resolve(responseFor(request, [row(12, { title: 'UPDATED LOCAL TASK' })])); await tick();
  assert.notEqual(currentProjection(h.render()), previous);
  assert.equal(currentProjection(h.render()).items[0].source_id, 12);
  assert.equal(find(h.render(), node => node.type === 'fieldset' && node.props['aria-label'] === '已读取运营记录').props.disabled, false);
  assertReadOnly(h);
});

test('transient projection reload failure retains the last verified same-scope snapshot and error', async () => {
  const h = harness(); await shellReady(h); const previous = currentProjection(h.render());
  refresh(h).reject({ status: 500, message: 'Synthetic refresh unavailable' }); await tick();
  assert.equal(currentProjection(h.render()), previous);
  assert.match(label(h.render()), /Synthetic refresh unavailable/);
  assert.match(label(h.render()), /保留上次读取的结果/);
  assert.equal(find(h.render(), node => node.type === 'fieldset' && node.props['aria-label'] === '已读取运营记录').props.disabled, true);
  assertReadOnly(h);
});

for (const status of [401, 403, 404]) {
  test(`projection authorization failure ${status} withdraws the retained snapshot`, async () => {
    const h = harness(); await shellReady(h);
    refresh(h).reject({ status, message: 'Synthetic permission revoked' }); await tick();
    assert.equal(hasProjection(h.render()), false);
    assert.match(label(h.render()), /Synthetic permission revoked/);
    assertReadOnly(h);
  });
}

test('changing range hides the prior projection before the new range is read', async () => {
  const h = harness(); await shellReady(h);
  const toolbar = find(h.render(), node => typeof node.props?.onMonth === 'function');
  toolbar.props.onMonth('2026-12');
  assert.equal(hasProjection(h.render()), false);
  h.effects(); const request = h.requests.at(-1);
  request.resolve(responseFor(request)); await tick();
  assert.equal(hasProjection(h.render()), true); assertReadOnly(h);
});

test('identity changes clear snapshots and reject a late prior-identity reload result', async () => {
  const h = harness(); await shellReady(h); const late = refresh(h);
  h.setProps({ scope: 'ops:2', isOwner: false });
  assert.match(label(h.render()), /确认当前账号/); h.effects();
  assert.equal(late.options.options.signal.aborted, true);
  late.resolve(responseFor(late)); await tick();
  assert.equal(hasProjection(h.render()), false); assertReadOnly(h);
});

test('merchant-list reload retains the same verified page while pending and after a network error', async () => {
  const h = harness(), previous = await merchantsReady(h), request = refresh(h);
  assert.equal(child(h.render(), 'MerchantList').props.page, previous);
  assert.equal(child(h.render(), 'MerchantList').props.onAction, undefined);
  assert.equal(find(h.render(), node => node.type === 'fieldset' && node.props['aria-label'] === '已读取商家清单').props.disabled, true);
  assert.match(label(h.render()), /正在更新清单/);
  request.reject({ status: 500, message: 'Synthetic merchant refresh unavailable' }); await tick();
  assert.equal(child(h.render(), 'MerchantList').props.page, previous);
  assert.equal(child(h.render(), 'MerchantList').props.onAction, undefined);
  assert.match(label(h.render()), /保留上次读取的清单/); assertReadOnly(h);
});

test('retained review rows cannot be selected or opened for approval while refreshing or after an error', async () => {
  const h = harness(); await shellReady(h);
  button(h.render(), '审核台').props.onClick(); h.render(); h.effects();
  let request = h.requests.at(-1); request.resolve(responseFor(request)); await tick();
  let selectAll = find(h.render(), node => node.props?.['aria-label'] === '选择本页可审核任务（最多10条）');
  assert.equal(selectAll.props.disabled, false);
  request = refresh(h);
  for (const failed of [false, true]) {
    if (failed) { request.reject({ status: 500, message: 'Synthetic review refresh unavailable' }); await tick(); }
    const tree = h.render();
    selectAll = find(tree, node => node.props?.['aria-label'] === '选择本页可审核任务（最多10条）');
    const selectOne = find(tree, node => node.type === 'input' && /^选择 LOCAL TEST/.test(node.props?.['aria-label'] || ''));
    assert.equal(selectAll.props.disabled, true); assert.equal(selectOne.props.disabled, true);
    selectAll.props.onChange({ target: { checked: true } }); selectOne.props.onChange({ target: { checked: true } });
    const review = button(h.render(), '核对所选内容（不发布）'); assert.equal(review.props.disabled, true); review.props.onClick();
    assert.equal(nodes(h.render()).some(node => node.props?.contextKey && Array.isArray(node.props.rows)), false);
    assertReadOnly(h);
  }
  request = refresh(h); request.resolve(responseFor(request)); await tick();
  selectAll = find(h.render(), node => node.props?.['aria-label'] === '选择本页可审核任务（最多10条）');
  assert.equal(selectAll.props.disabled, false);
  selectAll.props.onChange({ target: { checked: true } });
  assert.equal(button(h.render(), '核对所选内容（不发布）').props.disabled, false);
  assertReadOnly(h);
});

for (const status of [401, 403, 404]) {
  test(`merchant-list authorization failure ${status} withdraws the retained page`, async () => {
    const h = harness(); await merchantsReady(h);
    refresh(h).reject({ status, message: 'Synthetic merchant permission revoked' }); await tick();
    assert.equal(hasMerchants(h.render()), false);
    assert.match(label(h.render()), /Synthetic merchant permission revoked/); assertReadOnly(h);
  });
}

test('merchant page/filter/identity changes never display an old authorized page as the new range', async () => {
  const h = harness(); await merchantsReady(h);
  find(h.render(), node => node.type === 'OperationalFilters').props.onStatus('review');
  assert.equal(hasMerchants(h.render()), false); h.effects();
  const old = h.requests.at(-1); h.setProps({ scope: 'ops:2', isOwner: false }); h.render(); h.effects();
  old.resolve({ data: page([merchant(1)]) }); await tick();
  assert.equal(hasMerchants(h.render()), false); assertReadOnly(h);
});

test('service cards use a pure render helper inside stable keyed fragments instead of a per-render component type', () => {
  const require = createRequire(import.meta.url), ts = require('typescript');
  const source = fs.readFileSync(new URL('../src/pages/ServiceBoard.tsx', import.meta.url), 'utf8');
  const file = ts.createSourceFile('ServiceBoard.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let helper, keyedCalls = 0; const dynamicCards = [];
  const visit = node => {
    if (ts.isVariableDeclaration(node) && node.name.getText(file) === 'renderProgressCard') helper = node.initializer;
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(file) === 'ProgressCard') dynamicCards.push(node);
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(file) === 'Fragment'
      && node.openingElement.attributes.properties.some(prop => ts.isJsxAttribute(prop) && prop.name.text === 'key')
      && node.children.some(child => ts.isJsxExpression(child) && child.expression && ts.isCallExpression(child.expression) && child.expression.expression.getText(file) === 'renderProgressCard')) keyedCalls++;
    ts.forEachChild(node, visit);
  };
  visit(file); assert.ok(helper); assert.equal(dynamicCards.length, 0); assert.equal(keyedCalls, 2);
  const hookCalls = []; const inspect = node => { if (ts.isCallExpression(node) && /^use[A-Z]/.test(node.expression.getText(file))) hookCalls.push(node); ts.forEachChild(node, inspect); };
  inspect(helper); assert.equal(hookCalls.length, 0, 'render helper must remain hook-free');
  assert.match(helper.getText(file), /<details className="mfocus-delivery-card-details/);
});
