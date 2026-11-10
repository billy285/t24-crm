import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = name => fs.readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8');
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const find = (tree, predicate) => { const node = nodes(tree).find(predicate); assert.ok(node, 'Expected navigation control'); return node; };
const navigation = tree => find(tree, node => node.type === 'DesktopBusinessNavigation');
const shell = tree => find(tree, node => node.props?.['data-crm-polish']);
const mainWrapper = tree => find(tree, node => node.type === 'div' && node.props?.className === 'flex min-h-0 min-w-0 flex-1 flex-col');
const backdrop = tree => nodes(tree).find(node => node.props?.['aria-label'] === '关闭业务导航遮罩');

function harness({ path = '/media-ops', width = 1280, preference = '0', canAccess = () => true, role = 'ops' } = {}) {
  let si = 0, ri = 0, ei = 0, ci = 0;
  const states = [], refs = [], effects = [], callbacks = [], queue = [], documents = new Map(), media = new Map(), writes = [], api = [], prefetched = [];
  const location = { pathname: path, search: '', state: null };
  const roleState = { employee: { id: 7, name: 'Synthetic operator', role }, role, loading: false, authError: null, isLoggedIn: true, isDisabled: false, canAccess, retryAuth() {}, logout() {} };
  const document = { activeElement: null, addEventListener(type, fn) { const set = documents.get(type) || new Set(); set.add(fn); documents.set(type, set); }, removeEventListener(type, fn) { documents.get(type)?.delete(fn); }, querySelector: () => sidebar };
  class Element {
    constructor(name) { this.name = name; this.scrollTop = 0; this.scrollLeft = 0; this.disabled = false; this.visible = true; }
    focus() { if (!this.inert && !this.inertRoot?.inert) document.activeElement = this; }
    getClientRects() { return this.visible ? [{}] : []; }
    hasAttribute(name) { return name === 'disabled' && this.disabled; }
    scrollTo(value) { this.scrollTop = value.top; this.scrollLeft = value.left; }
    closest() { return null; }
    scrollIntoView() {}
  }
  const first = new Element('first'), last = new Element('last'), outside = new Element('outside'), disabled = new Element('disabled'); disabled.disabled = true;
  const sidebar = new Element('sidebar'); sidebar.querySelectorAll = () => [first, disabled, last]; sidebar.contains = element => [sidebar, first, disabled, last].includes(element);
  const shellDom = new Element('shell'); shellDom.querySelector = () => sidebar;
  const main = new Element('main'), backgroundInput = new Element('main-input'); backgroundInput.inertRoot = main; document.activeElement = outside;
  const matches = query => (!query.includes('min-width') || width >= Number(query.match(/min-width:\s*(\d+)/)?.[1] || 0)) && (!query.includes('max-width') || width <= Number(query.match(/max-width:\s*(\d+)/)?.[1] || Infinity));
  const window = { location: { href: 'https://synthetic.test/media-ops' }, localStorage: { getItem: () => preference, setItem: (key, value) => writes.push([key, value]) }, matchMedia(query) { if (!media.has(query)) media.set(query, { get matches() { return matches(query); }, listeners: new Set(), addEventListener(_, fn) { this.listeners.add(fn); }, removeEventListener(_, fn) { this.listeners.delete(fn); } }); return media.get(query); }, addEventListener() {}, removeEventListener() {}, requestAnimationFrame(fn) { fn(); return 1; }, cancelAnimationFrame() {} };
  const same = (a, b) => a?.length === b?.length && a.every((value, index) => Object.is(value, b[index]));
  const hooks = { useState(value) { const index = si++; if (!(index in states)) states[index] = typeof value === 'function' ? value() : value; return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }]; }, useRef(value) { const index = ri++; if (!(index in refs)) refs[index] = { current: value }; return refs[index]; }, useEffect(fn, deps) { const index = ei++, old = effects[index]; if (!old || !same(old.deps, deps)) queue.push(() => { old?.cleanup?.(); effects[index] = { deps, cleanup: fn() }; }); }, useCallback(fn, deps) { const index = ci++; if (!callbacks[index] || !same(callbacks[index].deps, deps)) callbacks[index] = { deps, fn }; return callbacks[index].fn; } };
  const jsx = (type, props, key) => {
    if (props?.ref && typeof type === 'string') props.ref.current = type === 'main' ? main : new Element(props['aria-label'] || type);
    // Model the browser's native inert focus exclusion, driven only by the
    // attribute emitted on the actual Layout main wrapper (no CSS inference).
    if (type === 'div' && props?.className === 'flex min-h-0 min-w-0 flex-1 flex-col') main.inert = props.inert !== undefined && props.inert !== false;
    return { type, props, key };
  };
  const sections = [{ label: '任务与交付', railLabel: '交付', description: 'Synthetic navigation', paths: ['/media-ops'], icon: 'Icon', items: [{ label: '代运营中心', path: '/media-ops', group: '运营', icon: 'Icon' }] }, { label: '销售中心', railLabel: '销售', paths: ['/sales-workbench', '/merchant-pool'], icon: 'Icon', items: [{ label: '今日拨打', path: '/sales-workbench', group: '销售', icon: 'Icon' }] }];
  const fallback = new Proxy({ __esModule: true, default: 'Stub' }, { get: (object, key) => object[key] || String(key) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'Fragment' }, 'react-router-dom': { Link: 'Link', Navigate: 'Navigate', useLocation: () => location, useNavigate: () => () => {} }, '../lib/role-context': { useRole: () => roleState, roleLabels: { ops: '运营', super_admin: '老板' } }, '../lib/permissions': { pageLabels: {} }, '@/lib/app-navigation': { appNavigationItems: [{ path: '/media-ops', label: '代运营中心' }, { path: '/customers', label: '客户' }], getDesktopNavigationSections: allow => sections.filter(section => section.items.some(item => allow(item.path))), getRoleTodayPath: () => '/today', getDesktopNavigationHref: item => item.path, isDesktopNavigationItemActive: (item, pathname) => item.path === pathname }, '@/components/DesktopBusinessNavigation': { __esModule: true, default: 'DesktopBusinessNavigation' }, '@/components/SalesCenterNavigation': { __esModule: true, default: 'SalesCenterNavigation', salesWorkspacePaths: ['/sales-workbench', '/merchant-pool'] }, '@/lib/navigation-state': { getSafeInternalPath: value => value || '' }, '@/lib/finance-navigation': { getFinanceNavigationItem: () => ({ tab: 'income', label: '收入管理' }) }, '@/lib/auth-storage': { getAuthSessionEpoch: () => 'synthetic' }, '@/lib/tokenStore': { getToken: () => 'synthetic' }, './crm-route-modules': { prefetchCrmRoute: (...args) => prefetched.push(args) }, '@/lib/api': { client: { apiCall: { invoke: value => api.push(value) } } } }, { get: (object, key) => object[key] || fallback });
  // Navigation tests use no DOM theme engine; its behavior is covered separately.
  imports['@/lib/use-crm-theme'] = { useCrmTheme: () => ({ themeId: 'blue', setTheme: () => true }) };
  imports['@/lib/crm-theme'] = { getCrmTheme: () => ({ name: '经典蓝' }) };
  function compile(name) { const module = { exports: {} }; vm.runInNewContext(ts.transpileModule(source(name), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: key => imports[key], window, document, navigator: { onLine: true }, HTMLElement: Element, Element, Map, Set, URL, URLSearchParams, Date, console }); return module.exports.default; }
  const Layout = compile('Layout.tsx'), Desktop = compile('DesktopBusinessNavigation.tsx');
  const renderComponent = (Component, props) => { si = ri = ei = ci = 0; return Component(props); };
  const flush = () => { while (queue.length) queue.shift()(); };
  const result = { location, roleState, writes, api, prefetched, document, sidebar, shellDom, first, last, outside, backgroundInput, sections, flush, render: () => renderComponent(Layout, { children: 'AUTHORIZED_CHILD' }), renderDesktop: props => renderComponent(Desktop, { sections, pathname: '/media-ops', search: '', homePath: '/today', roleLabel: '运营', open: false, collapsed: true, onClose() {}, onCollapsedChange() {}, onLogout() {}, ...props }), settle() { let tree = result.render(); flush(); tree = result.render(); flush(); return tree; }, resize(next) { width = next; for (const query of media.values()) for (const fn of query.listeners) fn(); }, dispatch(key, extra = {}) { const event = { key, defaultPrevented: false, shiftKey: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...extra }; for (const fn of documents.get('keydown') || []) fn(event); return event; }, unmount() { effects.forEach(effect => effect?.cleanup?.()); } };
  return result;
}

test('media starts collapsed despite expanded global preference and performs no grant/API writes', () => {
  const h = harness(); const tree = h.settle();
  assert.equal(navigation(tree).props.collapsed, true); assert.equal(navigation(tree).props.open, false); assert.equal(navigation(tree).props.modal, false);
  assert.equal(mainWrapper(tree).props['aria-hidden'], undefined); assert.equal(mainWrapper(tree).props.inert, undefined); assert.equal(backdrop(tree), undefined); assert.deepEqual(h.writes, [['t24_sidebar_collapsed', '0']]); assert.equal(h.api.length, 0);
});

for (const width of [1024, 1280, 1599]) test(`media ${width}px expands route-local overlay, hides main from assistive tech and closes by backdrop`, () => {
  const h = harness({ width }); let tree = h.settle(); const originalWrites = h.writes.length;
  navigation(tree).props.onCollapsedChange(false); tree = h.settle();
  assert.equal(navigation(tree).props.collapsed, false); assert.equal(navigation(tree).props.open, true); assert.equal(navigation(tree).props.modal, true); assert.equal(mainWrapper(tree).props['aria-hidden'], true); assert.equal(mainWrapper(tree).props.inert, '');
  backdrop(tree).props.onClick(); tree = h.settle();
  assert.equal(navigation(tree).props.collapsed, true); assert.equal(navigation(tree).props.modal, false); assert.equal(backdrop(tree), undefined); assert.equal(mainWrapper(tree).props['aria-hidden'], undefined); assert.equal(mainWrapper(tree).props.inert, undefined); assert.equal(h.writes.length, originalWrites);
});

test('media modal emits native inert so late background focus cannot escape until the overlay closes', () => {
  const h = harness(); let tree = h.settle();
  h.backgroundInput.focus(); assert.equal(h.document.activeElement, h.backgroundInput);
  navigation(tree).props.onCollapsedChange(false); tree = h.settle(); assert.equal(mainWrapper(tree).props.inert, '');
  h.first.focus(); h.backgroundInput.focus(); assert.equal(h.document.activeElement, h.first);
  backdrop(tree).props.onClick(); tree = h.settle(); assert.equal(mainWrapper(tree).props.inert, undefined);
  h.backgroundInput.focus(); assert.equal(h.document.activeElement, h.backgroundInput);
});

test('media overlay Escape document handler closes and Tab cannot focus background controls', () => {
  const h = harness(); let tree = h.settle(); navigation(tree).props.onCollapsedChange(false); tree = h.settle();
  h.outside.focus(); assert.equal(h.dispatch('Tab').defaultPrevented, true); assert.equal(h.document.activeElement, h.first);
  h.outside.focus(); h.dispatch('Tab', { shiftKey: true }); assert.equal(h.document.activeElement, h.last);
  const ignored = h.dispatch('Escape', { defaultPrevented: true }); assert.equal(ignored.defaultPrevented, true); assert.equal(navigation(h.render()).props.open, true);
  assert.equal(h.dispatch('Escape').defaultPrevented, true); tree = h.settle(); assert.equal(navigation(tree).props.open, false); assert.equal(mainWrapper(tree).props['aria-hidden'], undefined);
});

test('media overlay shell trap cycles first/last visible enabled controls and Escape closes', () => {
  const h = harness(); let tree = h.settle(); navigation(tree).props.onCollapsedChange(false); tree = h.settle();
  const event = (key, extra = {}) => ({ key, currentTarget: h.shellDom, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...extra });
  h.last.focus(); const forward = event('Tab'); shell(tree).props.onKeyDown(forward); assert.equal(forward.defaultPrevented, true); assert.equal(h.document.activeElement, h.first);
  const reverse = event('Tab', { shiftKey: true }); shell(tree).props.onKeyDown(reverse); assert.equal(h.document.activeElement, h.last);
  const escape = event('Escape'); shell(tree).props.onKeyDown(escape); assert.equal(escape.defaultPrevented, true); assert.equal(navigation(h.settle()).props.open, false);
});

test('media 1600px docks on expansion; resize to narrow becomes overlay and back restores dock without changing global preference', () => {
  const h = harness({ width: 1600 }); let tree = h.settle(); navigation(tree).props.onCollapsedChange(false); tree = h.settle();
  assert.equal(navigation(tree).props.collapsed, false); assert.equal(navigation(tree).props.open, false); assert.equal(navigation(tree).props.modal, false); assert.equal(backdrop(tree), undefined); assert.equal(mainWrapper(tree).props['aria-hidden'], undefined); assert.equal(mainWrapper(tree).props.inert, undefined);
  h.resize(1599); tree = h.settle(); assert.equal(navigation(tree).props.open, true); assert.equal(navigation(tree).props.modal, true);
  h.resize(1600); tree = h.settle(); assert.equal(navigation(tree).props.open, false); assert.equal(mainWrapper(tree).props['aria-hidden'], undefined); assert.deepEqual(h.writes, [['t24_sidebar_collapsed', '0']]);
});

test('navigation close is route-local and nonmedia restores original focused/general behavior', () => {
  const h = harness({ preference: '1' }); let tree = h.settle(); navigation(tree).props.onCollapsedChange(false); tree = h.settle(); navigation(tree).props.onClose(); h.settle();
  h.location.pathname = '/customers'; tree = h.settle(); assert.equal(navigation(tree).props.collapsed, true); assert.equal(navigation(tree).props.modal, false); assert.equal(mainWrapper(tree).props['aria-hidden'], undefined);
  h.location.pathname = '/unfocused'; tree = h.settle(); assert.equal(navigation(tree).props.collapsed, true); navigation(tree).props.onCollapsedChange(false); tree = h.settle(); assert.equal(navigation(tree).props.collapsed, false);
  h.location.pathname = '/media-ops'; tree = h.settle(); assert.equal(navigation(tree).props.collapsed, true); assert.deepEqual(h.writes, [['t24_sidebar_collapsed', '1'], ['t24_sidebar_collapsed', '0']]);
});

test('sales existing 1024–1359 overlay stays nonmodal and wider sales remains docked', () => {
  const h = harness({ path: '/sales-workbench', width: 1280 }); let tree = h.settle(); navigation(tree).props.onCollapsedChange(false); tree = h.settle();
  assert.equal(navigation(tree).props.open, true); assert.equal(navigation(tree).props.modal, false); assert.equal(mainWrapper(tree).props['aria-hidden'], undefined); assert.equal(mainWrapper(tree).props.inert, undefined); assert.ok(backdrop(tree));
  h.dispatch('Escape'); tree = h.settle(); assert.equal(navigation(tree).props.collapsed, true);
  h.resize(1360); navigation(tree).props.onCollapsedChange(false); tree = h.settle(); assert.equal(navigation(tree).props.open, false); assert.equal(navigation(tree).props.collapsed, false); assert.equal(navigation(tree).props.modal, false); assert.equal(backdrop(tree), undefined);
});

test('denied access remains denied after visual navigation expands and no role/grant state is mutated', () => {
  const h = harness({ canAccess: () => false }); let tree = h.settle();
  assert.equal(label(tree).includes('AUTHORIZED_CHILD'), false); assert.match(label(tree), /无权限访问/); assert.deepEqual(navigation(tree).props.sections, []);
  navigation(tree).props.onCollapsedChange(false); tree = h.settle(); assert.equal(label(tree).includes('AUTHORIZED_CHILD'), false); assert.equal(h.roleState.role, 'ops'); assert.equal(h.api.length, 0);
});

test('real secondary navigation modal semantics and focus return apply only to explicit media modal', () => {
  const h = harness(); const previous = h.outside; previous.focus();
  let tree = h.renderDesktop({ open: true, collapsed: false, modal: true }); const close = find(tree, node => node.props?.['aria-label'] === '关闭业务导航'); h.flush();
  assert.equal(tree.type, 'aside'); assert.equal(tree.props.role, 'dialog'); assert.equal(tree.props['aria-modal'], true); assert.equal(h.document.activeElement, close.props.ref.current);
  tree = h.renderDesktop({ open: false, collapsed: true, modal: false }); h.flush(); assert.equal(h.document.activeElement, previous); assert.equal(tree.props.role, undefined); assert.equal(tree.props['aria-modal'], undefined);
});

test('private-space chrome bypass is preserved and creates no media navigation', () => {
  const h = harness({ path: '/private-workspace' }); const tree = h.settle();
  assert.equal(tree.props.className, 'private-workspace-shell'); assert.equal(label(tree), 'AUTHORIZED_CHILD'); assert.equal(nodes(tree).some(node => node.type === 'DesktopBusinessNavigation'), false); assert.equal(h.api.length, 0);
});

test('desktop theme dialog suppresses closing menu focus and returns to its account entry', () => {
  const h = harness(); let tree = h.settle();
  h.document.querySelectorAll = () => [];
  const account = find(tree, node => node.props?.title === '我的账户').props.ref.current;
  account.isConnected = true;
  find(tree, node => node.props?.onSelect && label(node).startsWith('颜色主题')).props.onSelect();
  tree = h.settle();
  const menu = find(tree, node => node.props?.align === 'end' && node.props.onCloseAutoFocus);
  const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  menu.props.onCloseAutoFocus(event); assert.equal(event.defaultPrevented, true);
  const theme = find(tree, node => typeof node.props?.onReturnFocus === 'function');
  assert.equal(theme.props.open, true);
  theme.props.onOpenChange(false); h.settle(); h.outside.focus(); theme.props.onReturnFocus();
  assert.equal(h.document.activeElement, account);
});

for (const path of ['/more', '/apps']) test(`${path} theme dialog returns to the original profile opener or a visible account fallback`, () => {
  const h = harness({ path, width: 390 }); let tree = h.settle();
  h.outside.isConnected = true; h.first.isConnected = true;
  h.document.querySelectorAll = () => [h.first];
  h.outside.focus();
  find(tree, node => typeof node.props?.onOpenProfile === 'function').props.onOpenProfile();
  tree = h.settle();
  find(tree, node => node.type === 'Button' && label(node).startsWith('颜色主题')).props.onClick();
  tree = h.settle();
  const profile = find(tree, node => node.props?.className?.includes('rounded-t-[28px]') && node.props.onCloseAutoFocus);
  const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  profile.props.onCloseAutoFocus(event); assert.equal(event.defaultPrevented, true);
  const theme = find(tree, node => typeof node.props?.onReturnFocus === 'function');
  theme.props.onOpenChange(false); h.settle(); h.first.focus(); theme.props.onReturnFocus();
  assert.equal(h.document.activeElement, h.outside);
  // The saved opener can disappear or become hidden after a viewport change.
  h.outside.visible = false; theme.props.onReturnFocus();
  assert.equal(h.document.activeElement, h.first);
});
