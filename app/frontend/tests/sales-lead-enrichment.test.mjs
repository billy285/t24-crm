import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import ts from 'typescript';

const requireNode = createRequire(import.meta.url);
const source = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const backend = resolve(source, '../../backend');
const json = value => JSON.parse(JSON.stringify(value));
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)); };
const same = (a, b) => a && b && a.length === b.length && a.every((item, index) => Object.is(item, b[index]));

function fixture(overrides = {}, mobile = false) {
  const states = [], effects = [], cache = new Map(), drafts = [], saves = [], closes = [];
  let cursor = 0, tree, props;
  const react = {
    useState(initial) { const i = cursor++; if (!states[i]) states[i] = { value: typeof initial === 'function' ? initial() : initial }; return [states[i].value, value => { states[i].value = typeof value === 'function' ? value(states[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; if (!states[i]) states[i] = { value: { current: initial } }; return states[i].value; },
    useEffect(callback, deps) { const i = cursor++; if (!states[i] || !same(states[i].deps, deps)) { states[i] = { deps }; effects.push(callback); } },
  };
  function load(path) {
    if (cache.has(path)) return cache.get(path);
    const mod = { exports: {} };
    const code = ts.transpileModule(readFileSync(resolve(source, path), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const req = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'Fragment' };
      if (name === '@/hooks/use-mobile') return { useIsMobile: () => mobile };
      if (name === '@/lib/sales-lead-enrichment') return load('lib/sales-lead-enrichment.ts');
      if (name === '@/lib/phone-format') return load('lib/phone-format.ts');
      if (name === 'libphonenumber-js/max') {
        const phone = requireNode(name);
        // Keep library option objects in its realm (its argument parser uses instanceof Object).
        return { ...phone, parsePhoneNumberWithError: (text, options) => phone.parsePhoneNumberWithError(text, { ...options }) };
      }
      if (name.endsWith('.css')) return {};
      return new Proxy({}, { get: (_target, key) => String(key) });
    };
    vm.runInNewContext(`(function(require,module,exports){${code}\n})`, { Date, Intl, console, crypto: webcrypto })(req, mod, mod.exports);
    cache.set(path, mod.exports);
    return mod.exports;
  }
  const lib = load('lib/sales-lead-enrichment.ts');
  const data = {
    lead_id: 101, revision: 2, lead_updated_at: '2026-10-14T03:00:00Z', business_name: '合成餐厅', industry: '餐饮',
    city: 'Los Angeles', state: 'CA', country: 'US', address: null, website: null, store_phone: '+12135550123',
    contacts: [], preferred_contact_id: null, interest_product_ids: [1], need_summary: '了解网站方案', best_contact_time: null,
    verification: 'confirmed', updated_by_name: '合成销售', updated_at: '2026-10-14T03:00:00Z', can_edit: true, read_only_reason: null, warnings: [],
  };
  props = {
    open: true, onOpenChange: next => closes.push(next), leadId: 101, value: data, draft: lib.toEnrichmentUpdate(data),
    onDraftChange: next => { drafts.push(next); props.draft = next; }, onSave: async next => { saves.push(next); return true; },
    saving: false, loading: false, catalog: [{ id: 1, name: '网站服务' }, { id: 2, name: '广告投放' }], history: null,
    ...overrides,
  };
  const Component = load('components/SalesLeadQuickEdit.tsx').default;
  const render = (next = {}) => { props = { ...props, ...next }; cursor = 0; tree = Component(props); while (effects.length) effects.shift()(); return tree; };
  const settle = async () => { await flush(); render(); await flush(); render(); };
  const walk = (node, predicate) => !node ? [] : Array.isArray(node) ? node.flatMap(item => walk(item, predicate)) : typeof node !== 'object' ? [] : [...(predicate(node) ? [node] : []), ...walk(typeof node.type === 'function' ? node.type(node.props) : node.props?.children, predicate)];
  const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join(' ') : typeof node.type === 'function' ? text(node.type(node.props)) : text(node.props?.children);
  const all = predicate => walk(tree, predicate);
  return { render, settle, all, text, lib, data, saves, drafts, closes, tree: () => tree, props: () => props,
    byLabel: label => all(node => node.props?.['aria-label'] === label)[0],
    button: label => all(node => ['Button', 'button'].includes(node.type) && text(node).trim() === label)[0],
  };
}

function validateBackend(payload) {
  const result = spawnSync(process.env.T24_TEST_PYTHON || 'python3', ['-c', 'import json,sys\nfrom schemas.sales_enrichment import SalesEnrichmentUpdate\nSalesEnrichmentUpdate.model_validate(json.load(sys.stdin))\nprint("validated")'], {
    cwd: backend, input: JSON.stringify(payload), encoding: 'utf8', env: { ...process.env, APP_ENV: 'test', DATABASE_URL: 'sqlite+aiosqlite:///:memory:', PYTHONPATH: '.:..' },
  });
  assert.equal(result.status, 0, `Actual backend model rejected frontend payload: ${result.stderr || result.error || ''}`);
}

test('editable snapshots whitelist fields and preserve optimistic-lock values and stable contact IDs', () => {
  const app = fixture();
  const response = { ...app.data, employee_id: 55, is_owner: true, warnings: ['duplicate other-private-name'], contacts: [{ ...app.lib.createEnrichmentContact(), name: '合成老板' }] };
  const draft = app.lib.toEnrichmentUpdate(response, 'manual');
  const normalized = app.lib.normalizeEnrichmentUpdate({ ...draft, can_edit: true, owner_id: 77 });
  assert.equal(normalized.expected_revision, 2); assert.equal(normalized.expected_lead_updated_at, app.data.lead_updated_at);
  assert.equal(normalized.contacts[0].id, response.contacts[0].id); assert.notEqual(app.lib.createEnrichmentContact().id, response.contacts[0].id);
  for (const key of ['employee_id', 'owner_id', 'can_edit', 'warnings', 'revision', 'lead_id']) assert.equal(Object.hasOwn(normalized, key), false, key);
  validateBackend(normalized);
});

test('phone validation permits pending input but blocks confirmed invalid numbers without guessing a country', () => {
  const app = fixture(); const draft = { ...app.props().draft, store_phone: '2135550123', country: null, verification: 'pending' };
  assert.equal(app.lib.validateEnrichmentUpdate(draft).length, 0);
  assert.match(app.lib.validateEnrichmentUpdate({ ...draft, verification: 'confirmed' }).join(' '), /门店号码无效/);
  assert.equal(app.lib.normalizeEnrichmentUpdate(draft).store_phone, '2135550123');
  const contact = { ...app.lib.createEnrichmentContact(), name: '合成老板', phone: '123', verification: 'confirmed' };
  assert.match(app.lib.validateEnrichmentUpdate({ ...draft, contacts: [contact] }).join(' '), /联系人 1 电话无效/);
  assert.match(app.lib.validateEnrichmentUpdate({ ...draft, contacts: [{ ...contact, phone: '', verification: 'pending', email: 'not-email' }] }).join(' '), /邮箱格式/);
});

test('desktop opens from right, mobile from bottom, and the footer stays outside the scroll body', () => {
  for (const mobile of [false, true]) {
    const app = fixture({}, mobile); app.render();
    assert.equal(app.all(node => node.type === 'SheetContent')[0].props.side, mobile ? 'bottom' : 'right');
    assert.equal(app.all(node => node.type === 'footer').length, 1);
    assert.ok(app.button('保存资料，继续沟通'));
  }
});

test('contact edits use stable IDs; removing the preferred contact safely resets preference', () => {
  const app = fixture(); app.render(); app.button('添加联系人').props.onClick(); app.render();
  const firstId = app.props().draft.contacts[0].id;
  app.byLabel('联系人 1 姓名').props.onChange({ target: { value: '张经理' } }); app.render();
  app.byLabel('首选联系人 1').props.onChange(); app.render(); assert.equal(app.props().draft.preferred_contact_id, firstId);
  app.button('添加联系人').props.onClick(); app.render(); app.byLabel('联系人 2 姓名').props.onChange({ target: { value: '李老板' } }); app.render();
  const secondId = app.props().draft.contacts[1].id;
  assert.equal(app.props().draft.contacts[0].id, firstId); assert.notEqual(firstId, secondId);
  app.byLabel('移除联系人 1').props.onClick(); app.render();
  assert.equal(app.props().draft.preferred_contact_id, null); assert.equal(app.props().draft.contacts[0].id, secondId);
  validateBackend(app.props().draft);
});

test('product multi-select and collapsed details remain part of the saved whitelist', async () => {
  const app = fixture(); app.render();
  app.byLabel('意向产品 广告投放').props.onChange({ target: { checked: true } }); app.render();
  app.byLabel('真实需求').props.onChange({ target: { value: '合成需求与预算' } }); app.render();
  app.byLabel('城市').props.onChange({ target: { value: 'San Francisco' } }); app.render();
  app.byLabel('资料来源').props.onChange('manual'); app.render(); app.button('保存资料，继续沟通').props.onClick(); await app.settle();
  assert.deepEqual(json(app.saves[0].interest_product_ids), [1, 2]); assert.equal(app.saves[0].need_summary, '合成需求与预算'); assert.equal(app.saves[0].city, 'San Francisco'); assert.equal(app.saves[0].source, 'manual');
  validateBackend(app.saves[0]); assert.deepEqual(app.closes, []);
});

test('closing a dirty sheet preserves controlled input without saving or navigating', () => {
  const app = fixture(); app.render(); app.byLabel('商家名称').props.onChange({ target: { value: '刚沟通确认的名字' } }); app.render();
  assert.equal(app.props().draft.verification, 'pending'); app.button('暂存并关闭').props.onClick();
  assert.deepEqual(app.closes, [false]); assert.equal(app.props().draft.business_name, '刚沟通确认的名字'); assert.equal(app.saves.length, 0);
});

test('save rejection preserves every field and revision and never closes the sheet', async () => {
  const app = fixture({ onSave: async () => { throw new Error('409 stale'); } }); app.render();
  app.byLabel('真实需求').props.onChange({ target: { value: '不能丢失的本次需求' } }); app.render();
  app.button('保存资料，继续沟通').props.onClick(); await app.settle();
  assert.equal(app.props().draft.need_summary, '不能丢失的本次需求'); assert.equal(app.props().draft.expected_revision, 2);
  assert.match(app.text(app.tree()), /输入已保留/); assert.deepEqual(app.closes, []);
});

test('pending save is single-flight and prevents closing; successful save does not auto-advance', async () => {
  let finish, calls = 0; const app = fixture({ onSave: () => { calls++; return new Promise(resolve => { finish = resolve; }); } });
  app.render(); const save = app.button('保存资料，继续沟通'); save.props.onClick(); save.props.onClick(); app.render();
  app.all(node => node.type === 'Sheet')[0].props.onOpenChange(false); assert.equal(calls, 1); assert.deepEqual(app.closes, []);
  finish(true); await app.settle(); assert.deepEqual(app.closes, []);
});

test('read-only or converted leads cannot edit or save, and mismatched lead responses are not displayed', () => {
  const app = fixture(); app.render({ value: { ...app.data, can_edit: false, read_only_reason: '已转为客户，请在客户中心维护' } });
  assert.equal(app.button('保存资料，继续沟通').props.disabled, true); assert.match(app.text(app.tree()), /已转为客户/);
  app.byLabel('商家名称').props.onChange({ target: { value: '未经授权修改' } }); app.button('保存资料，继续沟通').props.onClick(); assert.equal(app.drafts.length, 0); assert.equal(app.saves.length, 0);
  app.render({ leadId: 202 }); assert.equal(app.byLabel('商家名称'), undefined); assert.doesNotMatch(app.text(app.tree()), /合成餐厅/);
});

test('duplicate warnings cannot disclose another lead even if a response contains its name', () => {
  const app = fixture(); app.render({ value: { ...app.data, warnings: ['duplicate: 敏感其他客户名称 电话 +19999999999'] } });
  assert.match(app.text(app.tree()), /号码可能与现有资料重复/); assert.doesNotMatch(app.text(app.tree()), /敏感其他客户名称|19999999999/);
  const inactive = app.lib.enrichmentWarningText(['有意向产品已停用，请重新选择后保存']);
  assert.match(inactive, /取消目录外产品/); assert.doesNotMatch(inactive, /号码/);
});

test('history is loaded explicitly and shows audited field changes without altering the draft', async () => {
  let reads = 0; const app = fixture({ history: [], onLoadHistory: async () => { reads++; } }); app.render(); assert.equal(reads, 0);
  app.button('修改历史').props.onClick(); app.render(); await app.settle(); assert.equal(reads, 1);
  app.render({ history: [{ id: 1, revision: 2, source: 'call', actor_name: '合成销售', created_at: '2026-10-14T03:00:00Z', changed_fields: ['business_name', 'unauthorized_company_profit'], before: { business_name: '旧名称', unauthorized_company_profit: 99999 }, after: { business_name: '新名称', unauthorized_company_profit: 88888 } }] });
  const text = app.text(app.tree()); assert.match(text, /通话补全/); assert.match(text, /旧名称/); assert.match(text, /新名称/); assert.doesNotMatch(text, /99999|88888|unauthorized_company_profit/); assert.equal(app.drafts.length, 0); assert.equal(app.saves.length, 0);
});

test('a version conflict never reloads automatically; explicit reload requires confirmation', () => {
  let reloads = 0; const app = fixture({ error: '资料已被其他同事更新，请核对', onReload: () => { reloads++; }, draftNotice: '草稿仅保留在当前页签' });
  app.render(); assert.equal(reloads, 0); assert.match(app.text(app.tree()), /草稿仅保留在当前页签/);
  app.button('重新读取资料（放弃未保存修改）').props.onClick(); app.render(); assert.equal(reloads, 0); assert.ok(app.button('确认重新读取'));
  app.button('保留修改').props.onClick(); app.render(); assert.equal(app.button('确认重新读取'), undefined);
  app.button('重新读取资料（放弃未保存修改）').props.onClick(); app.render(); app.button('确认重新读取').props.onClick(); assert.equal(reloads, 1);
});

test('the contact limit blocks additions but still allows editing existing contacts', () => {
  const app = fixture(); const contacts = Array.from({ length: 20 }, (_, index) => ({ ...app.lib.createEnrichmentContact(), name: `联系人${index + 1}` }));
  app.render({ draft: { ...app.props().draft, contacts } }); assert.equal(app.button('添加联系人').props.disabled, true);
  app.byLabel('联系人 1 姓名').props.onChange({ target: { value: '可修正的联系人' } }); app.render(); assert.equal(app.props().draft.contacts[0].name, '可修正的联系人');
});
