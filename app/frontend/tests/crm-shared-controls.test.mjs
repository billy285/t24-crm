import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';
const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
const deferred = () => { let resolve, reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; };
const click = () => ({ prevented: false, preventDefault() { this.prevented = true; } });
function compile(relative, imports) {
  const module = { exports: {} };
  const code = ts.transpileModule(readFileSync(resolve(src, relative), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }, reportDiagnostics: true });
  assert.deepEqual(code.diagnostics?.filter(item => item.category === ts.DiagnosticCategory.Error), []);
  vm.runInNewContext(`(function(require,module,exports){${code.outputText}\n})`, { Error })(name => {
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
    return imports[name] || new Proxy({}, { get: (_, key) => String(key) });
  }, module, module.exports);
  return module.exports;
}
function confirmFixture(onConfirm) {
  const slots = [], effects = [], changes = []; let cursor = 0, tree, mounted = true, lateWrites = 0;
  let props = { open: true, onConfirm, onOpenChange: value => changes.push(value), loadingLabel: '处理中…' };
  const react = {
    useState(initial) { const i = cursor++; slots[i] ||= { value: initial }; return [slots[i].value, value => { if (!mounted) lateWrites++; slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; slots[i] ||= { value: { current: initial } }; return slots[i].value; },
    useEffect(callback, deps) { const i = cursor++, old = slots[i]; if (old && deps.every((value, n) => Object.is(value, old.deps[n]))) return; slots[i] = { deps }; effects.push(() => { old?.cleanup?.(); slots[i].cleanup = callback(); }); },
  };
  const component = compile('components/ConfirmDialog.tsx', { react }).default;
  const render = (next = {}) => { props = { ...props, ...next }; cursor = 0; tree = component(props); while (effects.length) effects.shift()(); return tree; };
  const get = type => { const result = nodes(tree).find(node => node.type === type); assert.ok(result, type); return result; };
  return { render, get, changes, content: () => text(tree), lateWrites: () => lateWrites, unmount() { mounted = false; slots.forEach(item => item?.cleanup?.()); } };
}
test('async confirmation keeps its target open, blocks stale double-clicks and permits retry after failure', async () => {
  const request = deferred(); let calls = 0; const app = confirmFixture(() => { calls++; return request.promise; });
  app.render(); const action = app.get('AlertDialogAction'); const event = click(); const running = action.props.onClick(event); await action.props.onClick(click());
  assert.equal(event.prevented, true); assert.equal(calls, 1); assert.deepEqual(app.changes, []);
  app.render(); assert.equal(app.get('AlertDialogAction').props.disabled, true); assert.equal(app.get('AlertDialogCancel').props.disabled, true); assert.match(app.content(), /处理中/);
  app.get('AlertDialog').props.onOpenChange(false); assert.deepEqual(app.changes, []);
  const escape = click(); app.get('AlertDialogContent').props.onEscapeKeyDown(escape); assert.equal(escape.prevented, true);
  request.reject(new Error('当前记录已变化，请重新核对')); await running; app.render(); assert.match(app.content(), /当前记录已变化，请重新核对/); assert.equal(app.get('AlertDialogAction').props.disabled, false);
  app.render({ onConfirm: async () => true }); await app.get('AlertDialogAction').props.onClick(click()); assert.deepEqual(app.changes, [false]);
});
test('a caller-handled failure does not close an employee-style confirmation, while parent success still closes', async () => {
  const app = confirmFixture(async () => undefined); app.render(); await app.get('AlertDialogAction').props.onClick(click()); app.render();
  assert.deepEqual(app.changes, []); assert.match(app.content(), /操作未完成/);
  app.get('AlertDialog').props.onOpenChange(false); assert.deepEqual(app.changes, [false]);
  app.render({ open: false }); app.render({ open: true }); assert.doesNotMatch(app.content(), /操作未完成/);
  const request = deferred(); app.render({ onConfirm: () => request.promise }); const running = app.get('AlertDialogAction').props.onClick(click()); app.render({ open: false }); request.resolve(); await running; app.render(); assert.doesNotMatch(app.content(), /操作未完成/);
});
test('external loading prevents confirmations and late completion after unmount performs no writes', async () => {
  const request = deferred(); let calls = 0; const app = confirmFixture(() => { calls++; return request.promise; });
  app.render({ loading: true }); await app.get('AlertDialogAction').props.onClick(click()); assert.equal(calls, 0); app.get('AlertDialog').props.onOpenChange(false); assert.deepEqual(app.changes, []);
  app.render({ loading: false }); const running = app.get('AlertDialogAction').props.onClick(click()); app.unmount(); request.resolve(true); await running; assert.equal(app.lateWrites(), 0); assert.deepEqual(app.changes, []);
});
test('native select owns one density for its wrapper and control even with legacy wrapper height classes', () => {
  const { NativeSelect } = compile('components/ui/native-select.tsx', { '@/lib/utils': { cn: (...values) => values.filter(Boolean).join(' ') } }); const values = [];
  for (const [density, token] of [['default', '--t24-control-height'], ['compact', '--t24-control-compact'], ['comfortable', '--t24-control-large']]) {
    const tree = NativeSelect({ value: 'a', onChange: value => values.push(value), options: [{ value: 'a', label: '全部' }], density, className: 'h-8 w-24', controlClassName: 'test-control', 'aria-label': '筛选范围', disabled: true });
    assert.equal(tree.props.style.height, `var(${token})`); assert.equal(tree.props.style.minHeight, `var(${token})`);
    const select = nodes(tree).find(node => node.type === 'select'); assert.equal(select.props.style.height, '100%'); assert.equal(select.props.style.minHeight, '100%'); assert.equal(select.props['aria-label'], '筛选范围'); assert.equal(select.props.disabled, true); assert.match(select.props.className, /test-control/); select.props.onChange({ target: { value: 'b' } });
  }
  assert.deepEqual(values, ['b', 'b', 'b']);
});
