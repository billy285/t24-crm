import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const jsx = (type, props) => ({ type, props });
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const compile = (file, imports) => {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    module, exports: module.exports, require: name => imports[name] || {},
  });
  return module.exports;
};
const catalog = compile('lib/crm-theme.ts', {});
const Picker = compile('components/CrmThemePicker.tsx', {
  react: { useId: () => 'synthetic-theme-picker' },
  'react/jsx-runtime': { jsx, jsxs: jsx },
  '@/lib/crm-theme': catalog,
  '@/components/ui/button': { Button: 'Button' },
  '@/components/ui/dialog': Object.fromEntries(['Dialog', 'DialogTitle', 'DialogDescription', 'CrmFormDialogContent', 'CrmFormDialogHeader', 'CrmFormDialogBody', 'CrmFormDialogFooter'].map(name => [name, name])),
}).default;

test('theme picker preserves six native radio options and changes only when selected', () => {
  const changes = [];
  const tree = Picker({ open: true, onOpenChange() {}, value: 'forest', onChange: id => changes.push(id) });
  const radios = nodes(tree).filter(node => node.type === 'input' && node.props.type === 'radio');
  assert.equal(radios.length, 6);
  assert.equal(new Set(radios.map(node => node.props.name)).size, 1);
  assert.deepEqual(radios.filter(node => node.props.checked).map(node => node.props.value), ['forest']);
  assert.ok(radios.every(node => node.props['aria-label'] && node.props['aria-describedby']));
  radios[1].props.onChange({ currentTarget: { checked: true } });
  radios[2].props.onChange({ currentTarget: { checked: false } });
  assert.deepEqual(changes, ['obsidian']);
});

test('all dialog close paths restore focus through the supplied callback', () => {
  const closed = []; let returns = 0;
  const tree = Picker({ open: true, onOpenChange: value => closed.push(value), value: 'blue', onChange() {}, onReturnFocus: () => { returns++; } });
  const content = nodes(tree).find(node => node.type === 'CrmFormDialogContent');
  const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  content.props.onCloseAutoFocus(event);
  assert.equal(event.defaultPrevented, true); assert.equal(returns, 1);
  nodes(tree).find(node => node.type === 'Button').props.onClick();
  assert.deepEqual(closed, [false]);
  const standalone = Picker({ open: true, onOpenChange() {}, value: 'blue', onChange() {} });
  assert.equal(nodes(standalone).find(node => node.type === 'CrmFormDialogContent').props.onCloseAutoFocus, undefined);
});
