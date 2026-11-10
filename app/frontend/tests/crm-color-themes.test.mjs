import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import postcss from 'postcss';

const require = createRequire(import.meta.url);
const parseSelector = createRequire(require.resolve('tailwindcss'))('postcss-selector-parser');
const read = file => readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');
const theme = postcss.parse(read('components/crm-color-themes.css'));
const selectors = css => {
  const result = [];
  css.walkRules(rule => parseSelector(ast => ast.each(selector => result.push({ rule, selector }))).processSync(rule.selector));
  return result;
};
const themedRules = selectors(theme);

// This fixture evaluator covers the selector forms used by the CRM color layer.
// It checks the real old/new stylesheet cascade without a browser or network.
const element = (tag, classes = '', attrs = {}, parent = null, states = []) => {
  const node = { tag, classes: new Set(classes.split(/\s+/).filter(Boolean)), attrs, parent, states: new Set(states), children: [] };
  parent?.children.push(node);
  return node;
};
const pseudoMatches = (node, pseudo) => {
  if (pseudo.value.startsWith('::')) return node.pseudo === pseudo.value.slice(2);
  if (pseudo.value === ':is' || pseudo.value === ':where') return pseudo.nodes.some(selector => matches(node, selector));
  if (pseudo.value === ':not') return !pseudo.nodes.some(selector => matches(node, selector));
  if (pseudo.value === ':has') return false; // No :has is allowed in this color layer.
  if (pseudo.value === ':disabled') return 'disabled' in node.attrs;
  if (pseudo.value === ':enabled') return !('disabled' in node.attrs);
  return node.states.has(pseudo.value.slice(1));
};
const compoundMatches = (node, parts) => parts.every(part => {
  if (part.type === 'tag') return node.tag === part.value;
  if (part.type === 'class') return node.classes.has(part.value);
  if (part.type === 'universal') return true;
  if (part.type === 'id') return node.attrs.id === part.value;
  if (part.type === 'pseudo') return pseudoMatches(node, part);
  if (part.type === 'attribute') {
    const value = part.attribute === 'class' ? [...node.classes].join(' ') : node.attrs[part.attribute];
    if (value === undefined) return false;
    if (!part.operator) return true;
    if (part.operator === '=') return String(value) === part.value;
    if (part.operator === '*=') return String(value).includes(part.value);
    if (part.operator === '~=') return String(value).split(/\s+/).includes(part.value);
    if (part.operator === '^=') return String(value).startsWith(part.value);
    if (part.operator === '$=') return String(value).endsWith(part.value);
    return false;
  }
  return false;
});
function matches(node, selector) {
  const pseudoElement = selector.nodes.find(part => part.type === 'pseudo' && part.value.startsWith('::'));
  if (node.pseudo !== pseudoElement?.value.slice(2)) return false;
  function from(candidate, end) {
    if (!candidate) return false;
    let split = end;
    while (split >= 0 && selector.nodes[split].type !== 'combinator') split--;
    if (!compoundMatches(candidate, selector.nodes.slice(split + 1, end + 1))) return false;
    if (split < 0) return true;
    const relation = selector.nodes[split].value.trim();
    if (relation === '>') return from(candidate.parent, split - 1);
    if (!relation) {
      for (let ancestor = candidate.parent; ancestor; ancestor = ancestor.parent) if (from(ancestor, split - 1)) return true;
      return false;
    }
    return false;
  }
  return from(node, selector.nodes.length - 1);
}
const specificity = selector => selector.nodes.reduce((sum, node) => {
  if (node.type === 'id') return sum + 1_000_000;
  if (node.type === 'class' || node.type === 'attribute') return sum + 1_000;
  if (node.type === 'tag') return sum + 1;
  if (node.type === 'pseudo') {
    if (node.value === ':where') return sum;
    if ([':is', ':not', ':has'].includes(node.value)) return sum + Math.max(...node.nodes.map(specificity));
    return sum + (node.value.startsWith('::') ? 1 : 1_000);
  }
  return sum;
}, 0);
const cssFor = files => [...files.flatMap(file => selectors(postcss.parse(read(file)))), ...themedRules];
function cascade(node, rules, property) {
  const candidates = [];
  for (let order = 0; order < rules.length; order++) {
    const { rule, selector } = rules[order];
    if (!matches(node, selector)) continue;
    rule.walkDecls(declaration => {
      const prop = declaration.prop === 'background' ? 'background-color' : declaration.prop;
      if (prop === property) candidates.push({ value: declaration.value, weight: (declaration.important ? 1_000_000_000 : 0) + specificity(selector), order });
    });
  }
  candidates.sort((a, b) => a.weight - b.weight || a.order - b.order);
  return candidates.at(-1)?.value;
}
function fixture(themeId = 'amethyst') {
  const html = element('html', '', themeId ? { 'data-crm-theme': themeId } : {});
  const body = element('body', '', {}, html);
  const shell = element('div', 't24-system app-shell', { 'data-crm-polish': '20261026' }, body);
  const main = element('main', 'app-main crm-desktop-main', {}, shell);
  return { html, body, shell, main };
}
const deliveryFiles = ['components/delivery-center.css', 'pages/workspace-layout.css', 'pages/crm-customer-delivery-compact.css', 'pages/crm-delivery-refinement.css'];

test('theme rules stay opt-in, use bounded selectors and never change geometry or semantic series', () => {
  for (const { selector } of themedRules) assert.ok(selector.toString().trim().startsWith('html[data-crm-theme]:not([data-crm-theme="blue"])'), selector.toString());
  assert.doesNotMatch(theme.toString(), /:has\(|hue-rotate|\bfilter\s*:/);
  theme.walkDecls(declaration => {
    assert.doesNotMatch(declaration.prop, /^(width|height|min-width|min-height|max-width|max-height|padding|margin|display|position|transform|font-size|line-height|stroke|fill)$/);
    assert.ok(!['--fo-blue', '--owner-blue', '--dc-status-blue'].includes(declaration.prop));
  });
  for (const { selector } of themedRules) assert.doesNotMatch(selector.toString(), /\.dc-status-(?:blue|green|rose|amber)|\.recharts-|\.fo-cash-bar|\.fo-dot/);
});

test('sales primary view follows the palette with the current aria-current markup', () => {
  assert.match(read('pages/SalesLeads.tsx'), /className="slr-primary-views"/);
  const { main } = fixture();
  const page = element('div', 'slr-page', {}, main);
  const nav = element('nav', 'slr-primary-views', {}, page);
  const button = element('button', '', { 'aria-current': 'page' }, nav);
  const css = cssFor(['pages/sales-ui-clarity.css']);
  assert.equal(cascade(button, css, 'color'), 'var(--crm-accent)');
  assert.equal(cascade(button, css, 'border-bottom-color'), 'var(--crm-accent)');
});

test('desktop secondary navigation themes its active marker and icon while default blue stays unchanged', () => {
  const css = cssFor(['index.css', 'components/crm-visual-polish.css']);
  assert.match(read('components/DesktopBusinessNavigation.tsx'), /className=\{`app-secondary-link/);
  for (const themeId of ['obsidian', 'ocean', 'forest', 'amethyst', 'copper', null, 'blue']) {
    const { shell } = fixture(themeId);
    const nav = element('nav', 'app-sidebar-nav app-secondary-links', {}, shell);
    const link = element('a', 'app-secondary-link is-active', { 'aria-current': 'page' }, nav);
    const icon = element('svg', 'lucide', {}, link);
    const marker = { ...link, pseudo: 'before' };
    const themed = themeId && themeId !== 'blue';
    assert.equal(cascade(icon, css, 'color'), themed ? 'var(--crm-accent)' : '#3570e6', `${themeId}: active icon`);
    assert.equal(cascade(marker, css, 'background-color'), themed ? 'var(--crm-accent)' : '#3774ef', `${themeId}: active marker`);
    const inactive = element('a', 'app-secondary-link', {}, nav);
    const inactiveIcon = element('svg', 'lucide', {}, inactive);
    assert.equal(cascade(inactiveIcon, css, 'color'), '#93a1b6', `${themeId}: inactive icon`);
  }
});

test('operations active metric, filter and selected action beat the existing desktop and mobile overrides', () => {
  const { main } = fixture();
  const page = element('div', 'app-page calm-delivery-page calm-operations-page delivery-center-ui crm-delivery-refined dc-today', {}, main);
  const metric = element('button', 'dc-metric is-active', { 'aria-pressed': 'true' }, page);
  const toolbar = element('div', 'dc-today-toolbar', {}, page);
  const nav = element('nav', '', {}, toolbar);
  const filter = element('button', '', { 'aria-pressed': 'true' }, nav);
  const action = element('article', 'dc-action-card calm-action-selected', {}, page, ['hover']);
  const css = cssFor(deliveryFiles);
  for (const node of [metric, filter, action]) assert.equal(cascade(node, css, 'background-color'), 'var(--crm-accent-soft)');
  assert.equal(cascade(metric, css, 'box-shadow'), 'inset 0 -2px 0 var(--crm-accent)');
  assert.equal(cascade(filter, css, 'color'), 'var(--crm-accent)');
  assert.equal(cascade(action, css, 'border-color'), 'var(--crm-accent-border)');
});

test('custom operations navigation and shared Radix tabs use the same selected role', () => {
  const { main } = fixture();
  const page = element('div', 'app-page', {}, main);
  const nav = element('nav', 'sf-nav', {}, page);
  const custom = element('button', '', { 'aria-current': 'page' }, nav);
  const shared = element('button', 't24-tab', { role: 'tab', 'data-state': 'active' }, page);
  const css = cssFor(['components/service-follow-through.css', 'pages/workspace-layout.css']);
  for (const node of [custom, shared]) {
    assert.equal(cascade(node, css, 'background-color'), 'var(--crm-accent-soft)');
    assert.equal(cascade(node, css, 'color'), 'var(--crm-accent)');
  }
});

test('native primary actions are themed while status badges and chart keys keep their business colors', () => {
  const { main } = fixture();
  const page = element('div', 'delivery-center-ui dc-service', {}, main);
  const action = element('button', 'bg-blue-600 text-white', { 'aria-pressed': 'true' }, page);
  const status = element('span', 'dc-status dc-status-blue', {}, page);
  const css = cssFor(deliveryFiles);
  assert.equal(cascade(action, css, 'background-color'), 'var(--crm-accent)');
  assert.equal(cascade(action, css, 'color'), 'hsl(var(--primary-foreground))');
  assert.equal(cascade(status, css, 'color'), '#1d4ed8');
  assert.equal(cascade(status, css, 'background-color'), '#eff6ff');
});

test('mobile more, home actions and bottom navigation work inside the real app shell', () => {
  const { main } = fixture();
  const more = element('section', 'mobile-more-page', {}, main);
  const icon = element('span', 'mobile-more-brand', {}, more);
  const home = element('div', 'homepage-refined mobile-app-home', {}, main);
  const primary = element('button', 'home-primary-button', {}, home);
  const nav = element('nav', 'mobile-bottom-nav', {}, main);
  const selected = element('button', 'text-blue-700', { 'aria-current': 'page' }, nav);
  const css = cssFor(['components/mobile-more-page.css', 'components/homepage-refined.css']);
  assert.equal(cascade(more, css, 'background-color'), 'var(--crm-canvas)');
  assert.equal(cascade(icon, css, 'color'), 'var(--crm-accent)');
  assert.equal(cascade(primary, css, 'background-color'), 'var(--crm-accent)');
  assert.equal(cascade(selected, css, 'color'), 'var(--crm-accent)');
});

test('portals and native input focus are covered and validation colors remain excluded', () => {
  const { body } = fixture();
  const portal = element('div', 't24-ui-surface', { role: 'dialog' }, body);
  const valid = element('input', '', {}, portal, ['focus-visible']);
  const invalid = element('input', 'border-rose-500', { 'aria-invalid': 'true' }, portal, ['focus-visible']);
  assert.equal(cascade(portal, themedRules, 'background-color'), 'var(--crm-surface)');
  assert.equal(cascade(valid, themedRules, 'border-color'), 'var(--crm-accent)');
  assert.equal(cascade(invalid, themedRules, 'border-color'), undefined);
});

test('the default blue and a private-space cleanup with no html theme attribute match no color rules', () => {
  for (const themeId of [null, 'blue']) {
    const { main } = fixture(themeId);
    const page = element('div', 'app-page private-workspace-shell', {}, main);
    const action = element('button', 'bg-blue-600', {}, page);
    assert.equal(cascade(action, themedRules, 'background-color'), undefined);
  }
});
