import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';

const require = createRequire(import.meta.url);
const Button = props => React.createElement('button', props);
const NativeSelect = () => null;
const exports = {};
const source = readFileSync(new URL('../src/components/DeliveryListTools.tsx', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
  exports,
  require: name => name === '@/components/ui/button' ? { Button } : name === '@/components/ui/native-select' ? { NativeSelect } : require(name),
});
const { DeliveryFilterSummary, DeliveryPagination } = exports;
const elements = node => Array.isArray(node) ? node.flatMap(elements) : React.isValidElement(node) ? [node, ...elements(node.props.children)] : [];
const text = node => Array.isArray(node) ? node.map(text).join('') : React.isValidElement(node) ? text(node.props.children) : node == null || typeof node === 'boolean' ? '' : String(node);

test('each visible filter clears only its own condition, and clear-all is separate', () => {
  const cleared = [];
  const tree = DeliveryFilterSummary({ scope: '本人回访', count: 8, filters: [
    { key: 'status', label: '状态：待回访', onClear: () => cleared.push('status') },
    { key: 'customer', label: '客户：门店 A', onClear: () => cleared.push('customer') },
  ], onClearAll: () => cleared.push('all') });
  const nodes = elements(tree);
  nodes.find(node => node.props['aria-label'] === '取消筛选：客户：门店 A').props.onClick();
  assert.deepEqual(cleared, ['customer']);
  nodes.find(node => node.type === Button && text(node) === '清空筛选').props.onClick();
  assert.deepEqual(cleared, ['customer', 'all']);
  assert.match(text(tree), /当前范围：本人回访/);
  assert.match(text(tree), /当前结果 8 条/);
});

test('loading and stale results are distinguished from a current zero-result list', () => {
  const props = { scope: '授权任务', count: 0, filters: [], onClearAll() {} };
  assert.match(text(DeliveryFilterSummary({ ...props, loading: true })), /正在读取/);
  assert.doesNotMatch(text(DeliveryFilterSummary({ ...props, loading: true })), /当前结果 0/);
  assert.match(text(DeliveryFilterSummary({ ...props, count: 12, stale: true })), /最近读取 12 条/);
});

test('shared pagination keeps edge controls disabled and dispatches page/size changes', () => {
  const pages = [], sizes = [];
  const tree = DeliveryPagination({ info: { total: 65, start: 1, end: 20, page: 1, totalPages: 4 }, pageSize: 20, sizes: [20, 50, 100], onPage: value => pages.push(value), onPageSize: value => sizes.push(value), label: '回访记录' });
  const nodes = elements(tree);
  assert.equal(nodes.find(node => node.type === Button && text(node) === '上一页').props.disabled, true);
  nodes.find(node => node.type === Button && text(node) === '下一页').props.onClick();
  assert.deepEqual(pages, [2]);
  const select = nodes.find(node => node.type === NativeSelect);
  assert.equal(select.props['aria-label'], '回访记录每页显示');
  select.props.onChange('50');
  assert.deepEqual(sizes, [50]);
  assert.equal(DeliveryPagination({ info: { total: 0 }, sizes: [], onPage() {}, onPageSize() {}, label: '任务' }), null);
});
