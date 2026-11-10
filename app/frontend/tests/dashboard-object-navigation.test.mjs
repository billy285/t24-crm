import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = readFileSync(new URL('../src/pages/Dashboard.tsx', import.meta.url), 'utf8');
const nodes = node => node == null || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
function render(role, reminders = []) {
  const destinations = [], writes = []; let state = 0;
  const data = { customers: [{ id: 89, business_name: 'LOCAL MERCHANT', contact_name: 'LOCAL', status: 'following' }], tasks: [{ id: 51, title: 'LOCAL TASK', status: 'pending' }, { id: 52, title: 'DONE TASK', status: 'completed' }], deals: [] };
  const react = { useState(initial) { const n = state++; return [n === 0 ? data : n === 1 ? reminders : n === 2 ? false : n === 4 ? true : typeof initial === 'function' ? initial() : initial, () => {}]; }, useEffect() {}, useMemo(fn) { return fn(); } };
  const fallback = new Proxy({}, { get: (_, name) => name === '__esModule' ? true : String(name) });
  const imports = { react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, 'react-router-dom': { useNavigate: () => path => destinations.push(path) }, '../lib/role-context': { useRole: () => ({ role, employee: { id: 8 }, isAdmin: false, canAccess: () => true }) }, '../lib/dict-config': { useBusinessDicts: () => ({ statuses: {} }) }, '../lib/use-auto-refresh': { useAutoRefresh() {} }, '../lib/tokenStore': { invokeWithAuth(value) { writes.push(value); throw Error('Rendering must not invoke APIs'); } }, '@/lib/phone-format': { formatPhoneNumber: () => '' } };
  const module = { exports: {} }, code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }, reportDiagnostics: true });
  assert.deepEqual(code.diagnostics?.filter(row => row.category === ts.DiagnosticCategory.Error), []);
  vm.runInNewContext(code.outputText, { module, exports: module.exports, require: name => imports[name] || fallback, URLSearchParams, Date, console });
  return { tree: module.exports.default(), destinations, writes };
}
test('recent customer is a native keyboard button and opens the exact customer with return context', () => {
  const app = render('sales'), row = nodes(app.tree).find(node => node.props?.['aria-label'] === '查看客户：LOCAL MERCHANT');
  assert.equal(row.type, 'button'); assert.equal(row.props.type, 'button'); row.props.onClick();
  const target = new URL(app.destinations[0], 'https://example.test'); assert.equal(target.pathname, '/customers'); assert.equal(target.searchParams.get('detail'), '89'); assert.equal(target.searchParams.get('returnTo'), '/'); assert.deepEqual(app.writes, []);
  assert.ok(nodes(app.tree).some(node => node.type === 'button' && node.props['aria-label'] === '查看我的客户'));
});
test('ops and design task rows go directly to the selected task and do not expose completed tasks', () => {
  for (const role of ['ops', 'design']) { const app = render(role), row = nodes(app.tree).find(node => node.props?.['aria-label'] === '查看任务：LOCAL TASK'); assert.equal(row.type, 'button'); row.props.onClick(); const target = new URL(app.destinations[0], 'https://example.test'); assert.equal(target.pathname, '/tasks'); assert.equal(target.searchParams.get('task_id'), '51'); assert.equal(target.searchParams.get('returnTo'), '/'); assert.equal(nodes(app.tree).some(node => node.props?.['aria-label'] === '查看任务：DONE TASK'), false); assert.deepEqual(app.writes, []); }
});
test('reminders remain native buttons with their original scoped destination and missing links are disabled', () => {
  const app = render('ops', [{ id: 'known', type: 'pending_task', title: 'KNOWN', description: '', urgency: 'low', link: '/tasks?task_id=51' }, { id: 'unknown', type: 'pending_task', title: 'UNKNOWN', description: '', urgency: 'low' }]);
  const reminder = nodes(app.tree).find(node => node.type === 'button' && text(node).includes('KNOWN') && !text(node).includes('UNKNOWN')); assert.ok(reminder); reminder.props.onClick(); assert.equal(app.destinations[0], '/tasks?task_id=51'); assert.equal(nodes(app.tree).find(node => node.type === 'button' && text(node).includes('UNKNOWN')).props.disabled, true); assert.deepEqual(app.writes, []);
});
