import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(body, imports = {}) { const module = { exports: {} }, fallback = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) }); vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: key => imports[key] || fallback, Date, Intl, Set, Map, AbortController }); return module.exports; }
const jsx = { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) };
const baseImports = { 'react/jsx-runtime': jsx, './ui/button': { Button: 'Button' }, './ui/input': { Input: 'Input' } };
const priorities = compile(source('../src/components/MediaWorkspacePriorities.tsx') + '\nexport { workspacePriorityData, workspacePriorityCount };', baseImports);
const toolbar = compile(source('../src/components/MediaWorkspaceToolbar.tsx'), baseImports);
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, predicate) => { const result = nodes(tree).find(predicate); assert.ok(result, 'Expected workspace presentation control'); return result; };
const card = (tree, name) => find(tree, node => node.type === 'button' && label(node).includes(name));
const merchant = (id, extra = {}) => ({ id, name: `LOCAL MERCHANT ${id}`, platforms: ['google_business'], can_create: false, can_edit: false, data_state: 'complete', issues: [{ code: 'review', label: '待审核', severity: 'medium' }], work_queue: { checks: [], next_action: { kind: 'review', label: '核对内容' } }, ...extra });
const projection = extra => ({ sources_complete: true, summary: { blocked: 2, unknown: 1, in_review: 8 }, portfolio: { summary: { merchants: 30, review: 9, attention: 5, unassigned: 1, no_schedule: 2 }, exceptions: [merchant(901), merchant(902)], sources_complete: true }, ...extra });
function priorityView(data = projection(), isOwner = true) { const filters = [], views = [], opened = []; const tree = priorities.default({ data, isOwner, onFilter: value => filters.push(value), onView: value => views.push(value), onMerchant: (...values) => opened.push(values) }); return { tree, filters, views, opened }; }

test('priority counts keep aggregate merchants distinct from record counts and paginated rows', () => {
  const data = projection({ items: [], total: 900, partial: true, next_cursor: 'next' }), value = priorities.workspacePriorityData(data);
  assert.equal(value.review, 9); assert.equal(value.attention, 5); assert.equal(value.exceptions, 3); assert.equal(value.merchants.length, 2);
  const { tree, filters, views } = priorityView(data);
  card(tree, '待审核商家').props.onClick(); card(tree, '需处理商家').props.onClick(); card(tree, '执行异常／待确认').props.onClick();
  assert.deepEqual(filters, ['review', 'attention']); assert.deepEqual(views, ['reports']); assert.match(label(card(tree, '待审核商家')), /9家/);
});
test('missing material entry never invents an aggregate number from the bounded exception list', () => {
  const data = projection(); data.portfolio.exceptions[0].work_queue.checks = [{ key: 'materials', state: 'missing', label: '照片待补齐' }];
  const { tree, filters } = priorityView(data), entry = card(tree, '菜单与配图');
  assert.match(label(entry), /逐家检查/); assert.doesNotMatch(label(entry), /[0-9]/); entry.props.onClick(); assert.deepEqual(filters, ['all']); assert.match(label(tree), /照片待补齐/);
});
test('unavailable or partial sources never substitute zero or claim all work completed', () => {
  assert.equal(priorities.workspacePriorityData(null), null); assert.equal(priorities.workspacePriorityCount(null, true), '待核对'); assert.equal(priorities.workspacePriorityCount(0, false), '待核对'); assert.equal(priorities.workspacePriorityCount(4, false), '4+'); assert.equal(priorities.workspacePriorityCount(0, true), '0');
  const data = projection({ sources_complete: false, summary: { blocked: 0, unknown: 0 }, portfolio: { summary: { review: 0, attention: 0 }, exceptions: [], sources_complete: false } });
  const { tree } = priorityView(data); assert.match(label(tree), /部分来源待核对/); assert.match(label(tree), /待办来源尚未完整/); assert.doesNotMatch(label(tree), /没有需优先处理/);
  assert.match(label(priorityView(null).tree), /尚未完整读取/);
});
test('highest actual risk is first and owner-only monthly actions do not reach staff shortcuts', () => {
  const low = merchant(901), high = merchant(902, { issues: [{ code: 'failed', label: '平台执行异常', severity: 'high' }], work_queue: { checks: [], next_action: { kind: 'monthly', platform: 'instagram', run_id: 7, label: '继续整月' } } });
  const data = projection(); data.portfolio.exceptions = [low, high]; assert.equal(priorities.workspacePriorityData(data).merchants[0].id, 902);
  const owner = priorityView(data), staff = priorityView(data, false);
  find(owner.tree, node => node.type === 'Button' && label(node) === '去处理').props.onClick(); find(staff.tree, node => node.type === 'Button' && label(node) === '去处理').props.onClick();
  assert.equal(owner.opened[0][1].run_id, 7); assert.equal(staff.opened[0][1], undefined); assert.equal(staff.opened[0][0].id, 902);
});
test('compact toolbar hides advanced controls by default and preserves active filters and month navigation', () => {
  const months = [], opened = [], cleared = [], props = { scopeControls: 'SCOPE/PLATFORM', month: '2026-11', dates: { from: '2026-11-01', to: '2026-11-30' }, busy: false, advancedOpen: false, onAdvanced: value => opened.push(value), onMonth: value => months.push(value), filters: [{ key: 'owner', label: 'LOCAL OPERATOR', onClear: () => cleared.push(true) }], children: 'ADVANCED DATES/OPERATOR/SAVE' };
  let tree = toolbar.default(props); assert.doesNotMatch(label(tree), /ADVANCED DATES/); assert.match(label(tree), /LOCAL OPERATOR/);
  find(tree, node => node.props?.['aria-controls'] === 'mwr-advanced-filters').props.onClick(); assert.deepEqual(opened, [true]);
  const monthInput = find(tree, node => node.props?.['aria-label'] === '运营工作月份'); monthInput.props.onChange({ target: { value: '2026-12' } }); monthInput.props.onChange({ target: { value: '2026-13' } }); assert.deepEqual(months, ['2026-12']);
  find(tree, node => node.props?.['aria-label'] === '清除筛选：LOCAL OPERATOR').props.onClick(); assert.equal(cleared.length, 1);
  tree = toolbar.default({ ...props, advancedOpen: true, month: null }); assert.match(label(tree), /ADVANCED DATES/); assert.match(label(tree), /自定义期间：2026-11-01 — 2026-11-30/);
});
test('busy toolbar makes scope-changing month, filter and clearing controls visibly unavailable', () => {
  const tree = toolbar.default({ scopeControls: 'SCOPE', month: '2026-11', dates: { from: '', to: '' }, busy: true, advancedOpen: false, onAdvanced() {}, onMonth() {}, filters: [{ key: 'state', label: '待审核', onClear() {} }], children: null });
  assert.equal(find(tree, node => node.props?.['aria-label'] === '运营工作月份').props.disabled, true); assert.equal(find(tree, node => node.props?.['aria-expanded'] === false).props.disabled, true); assert.equal(find(tree, node => node.props?.['aria-label'] === '清除筛选：待审核').props.disabled, true);
});
