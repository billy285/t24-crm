import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const stamp = '2026-11-02T02:00:00Z', hash = 'a'.repeat(64), uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
function compile(body, imports = {}) { const module = { exports: {} }; vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: key => imports[key] || {}, Date, Intl, Set, Map, AbortController, structuredClone, window: { setTimeout: callback => { callback(); return 1; }, clearTimeout() {} } }); return module.exports; }
const monthly = compile(source('../src/lib/media-monthly-api.ts'));
const api = compile(source('../src/lib/media-automation-settings-api.ts'), { './media-monthly-api': monthly });
const rules = extra => ({ weekdays: [2, 4, 6], local_time: '11:00', language: 'en', include_prices: false, forbidden_claims: [], content_mix: { featured: 50, discovery: 30, business: 20 }, tone: 'friendly', ...extra });
const document = extra => ({ industry: 'restaurant', timezone: 'America/Denver', defaults: rules(), platform_overrides: {}, template_key: 'restaurant', template_revision: 1, ...extra });
const template = extra => ({ id: 'restaurant', revision: 1, name: '餐厅 · 合成模板', builtin: true, document: document({ timezone: null }), ...extra });
const settings = extra => ({ customer: { id: 901, name: 'SYNTHETIC SOURCE', cooperation_active: true }, revision: 0, version: null, effective_version: null, document: document(), sources: ['google_business', 'facebook', 'instagram'].map(platform => ({ platform, profile_ready: true, menu_count: 4, image_count: 3, timezone: 'America/Denver' })), month: '2026-11', new_batches_only: true, publications_changed: false, ...extra });
const previewBody = extra => ({ request_id: uuid(1), kind: 'edit', month: '2026-11', customer_id: 901, expected_revision: 0, document: document(), target_ids: [], platforms: [], groups: [], ...extra });
const impact = (id = 901, extra = {}) => ({ customer_id: id, name: `SYNTHETIC ${id}`, before_revision: 0, after_revision: 1, effective_from_month: '2026-11', document_after: document(), changed_fields: ['instagram.tone'], platforms: ['google_business', 'facebook', 'instagram'].map(platform => ({ platform, before_count: 12, proposed_count: 12, timezone: 'America/Denver', existing_batches: 1, source_ready: true, content_mix: { featured: 50, discovery: 30, business: 20 } })), protected: { batches: 3, reviewed: 1, scheduled: 1 }, auto_policies_need_reconfirmation: 2, accounts_materials_permissions_copied: false, ...extra });
const preview = (body = previewBody(), extra = {}) => ({ id: uuid(90), request_id: body.request_id, preview_hash: hash, expires_at: '2030-11-02T02:00:00Z', kind: body.kind, month: body.month, targets: (body.kind === 'edit' ? [body.customer_id] : body.target_ids).map(id => impact(id)), new_batches_only: true, publications_changed: false, menus_images_accounts_permissions_copied: false, ...extra });
const saved = (value, body) => ({ request_id: body.request_id, preview_id: value.id, saved: value.targets.map(row => ({ customer_id: row.customer_id, revision: row.after_revision, effective_from_month: row.effective_from_month })), new_batches_only: true, existing_batches_changed: false, publications_changed: false });
const label = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(label).join('') : label(value.props?.children);
const nodes = value => value == null || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const find = (tree, predicate) => { const value = nodes(tree).find(predicate); assert.ok(value, 'Expected unified settings control'); return value; };
const button = (tree, name) => find(tree, value => (value.type === 'Button' || value.type === 'button') && label(value) === name);
const input = (tree, name) => find(tree, value => value.props?.['aria-label'] === name);
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(extra = {}) {
  let si = 0, ri = 0, ei = 0, held = false, nextId = 1;
  const states = [], refs = [], effects = [], queue = [], requests = [], changed = [];
  const props = { scope: 'owner:1', isOwner: true, customerId: 901, customerName: 'SYNTHETIC SOURCE', month: '2026-11', onChanged: () => changed.push(true), ...extra };
  const hooks = { useState(value) { const i = si++; if (!(i in states)) states[i] = typeof value === 'function' ? value() : value; return [states[i], next => states[i] = typeof next === 'function' ? next(states[i]) : next]; }, useRef(value) { const i = ri++; if (!(i in refs)) refs[i] = { current: value }; return refs[i]; }, useEffect(callback, deps) { const i = ei++, old = effects[i]; if (!old || !old.deps || old.deps.some((value, n) => value !== deps[n])) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: callback() }; }); } };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const scopedApi = compile(source('../src/lib/media-automation-settings-api.ts'), { './media-monthly-api': monthly, './tokenStore': { invokeWithAuth } });
  const fallback = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props, key) => ({ type, props, key }), jsxs: (type, props, key) => ({ type, props, key }) }, '@/components/ui/button': { Button: 'Button' }, '@/components/ui/input': { Input: 'Input' }, '@/components/ui/textarea': { Textarea: 'Textarea' }, '@/components/ui/native-select': { NativeSelect: 'NativeSelect' }, '@/lib/media-monthly-api': monthly, '@/lib/media-automation-settings-api': scopedApi, '@/lib/media-operations-api': { mediaError: (cause, message) => cause?.message || message, mediaErrorStatus: cause => cause?.status, mediaRequestId: () => uuid(nextId++), mediaTimezones: [{ value: 'America/Denver', label: 'Denver' }], mediaUtcToLocal: value => value.slice(0, 16) }, '@/lib/use-unsaved-changes': { confirmDiscardAllChanges: () => !held, useUnsavedChanges: () => ({ markSaved() {} }), useHardNavigationBlock: () => ({ lock() { held = true; }, release() { held = false; } }) } }, { get: (value, key) => value[key] || fallback });
  const mod = compile(source('../src/components/MediaUnifiedAutomationSettings.tsx') + '\nexport { SettingsEditor, ImpactPreview };', imports);
  return { props, requests, changed, get held() { return held; }, render() { si = ri = ei = 0; return mod.SettingsEditor(props); }, outer() { return mod.default(props); }, previewRender(value, confirmed = false, disabled = false, onApply = () => {}) { return mod.ImpactPreview({ value, confirmed, disabled, onConfirm() {}, onApply }); }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); } };
}
async function ready(h, value = settings()) { h.render(); h.effects(); assert.equal(h.requests.length, 2); h.requests[0].resolve({ data: value }); h.requests[1].resolve({ data: { items: [template()], templates_are_copied_not_live_linked: true } }); await tick(); return h.render(); }
function changeTone(h, tone = 'professional') { input(h.render(), '自动化文案语气').props.onChange(tone); }

test('rules and documents reject invalid mixes, weekdays, private fields and invalid zones', () => {
  assert.equal(api.verifiedSettingsDocument(document()).timezone, 'America/Denver');
  for (const value of [rules({ weekdays: [] }), rules({ weekdays: [2, 2] }), rules({ weekdays: [0] }), rules({ content_mix: { featured: 50, discovery: 30, business: 30 } }), rules({ forbidden_claims: [''] }), rules({ local_time: '29:00' }), rules({ auto_publish: true })]) assert.throws(() => api.verifiedSettingsRules(value));
  for (const value of [document({ timezone: 'Bad/Zone' }), document({ finance: { profit: 10 } }), document({ platform_overrides: { linkedin: {} } }), document({ platform_overrides: { instagram: { include_prices: 1 } } })]) assert.throws(() => api.verifiedSettingsDocument(value));
});
test('templates create independent rule copies and preserve merchant timezone without carrying authority', () => {
  const value = api.copySettingsTemplate(template(), document({ timezone: 'America/Chicago' }));
  assert.equal(value.timezone, 'America/Chicago'); value.defaults.weekdays.push(7); assert.deepEqual(template().document.defaults.weekdays, [2, 4, 6]);
  assert.throws(() => api.verifiedSettingsTemplate(template({ document: document() })));
  assert.throws(() => api.verifiedSettingsTemplate(template({ document: document({ timezone: null, execution_enabled: true }) })));
  assert.deepEqual(api.resolvedSettingsRules(document({ platform_overrides: { instagram: { tone: 'professional' } } }), 'instagram').tone, 'professional');
});
test('copy payload whitelist preserves scope and refuses source, >30 targets or authorization groups', () => {
  const good = { request_id: uuid(1), kind: 'copy', month: '2026-11', customer_id: 901, expected_revision: 0, target_ids: [902], platforms: ['instagram'], groups: ['writing'] };
  assert.equal(api.verifiedSettingsPreviewBody(good).target_ids.length, 1);
  for (const patch of [{ target_ids: [901] }, { target_ids: [902, 902] }, { target_ids: Array.from({ length: 31 }, (_, i) => i + 902) }, { document: document() }, { timezone: 'America/New_York' }, { platforms: ['linkedin'] }, { groups: ['permissions'] }, { groups: [] }]) assert.throws(() => api.verifiedSettingsPreviewBody({ ...good, ...patch }));
});
test('read and impact responses cannot cross merchants/months, widen targets or claim live changes', () => {
  assert.equal(api.verifiedUnifiedSettings(settings(), 901, '2026-11').revision, 0);
  for (const value of [settings({ month: '2026-12' }), settings({ publications_changed: true }), settings({ customer: { id: 902, name: 'OTHER', cooperation_active: true } })]) assert.throws(() => api.verifiedUnifiedSettings(value, 901, '2026-11'));
  const body = previewBody(); assert.equal(api.verifiedSettingsPreview(preview(body), body).targets.length, 1);
  for (const value of [preview(body, { request_id: uuid(2) }), preview(body, { targets: [impact(902)] }), preview(body, { publications_changed: true }), preview(body, { menus_images_accounts_permissions_copied: true })]) assert.throws(() => api.verifiedSettingsPreview(value, body));
});
test('apply and template receipts match original request, revisions and preserved-content guarantees', () => {
  const value = preview(), body = { request_id: uuid(3), preview_hash: hash, confirmed: true }, result = saved(value, body);
  assert.equal(api.verifiedSettingsSaved(result, value, body).saved[0].revision, 1);
  for (const patch of [{ request_id: uuid(4) }, { preview_id: uuid(4) }, { existing_batches_changed: true }, { saved: [{ customer_id: 902, revision: 1, effective_from_month: '2026-11' }] }]) assert.throws(() => api.verifiedSettingsSaved({ ...result, ...patch }, value, body));
  const templateBody = { request_id: uuid(4), name: 'PRIVATE', document: document({ timezone: null }) }, templateResult = { request_id: uuid(4), template: template({ id: uuid(5), name: 'PRIVATE', builtin: false }), customers_changed: false };
  assert.equal(api.verifiedSettingsTemplateSaved(templateResult, templateBody).customers_changed, false);
  assert.throws(() => api.verifiedSettingsTemplateSaved({ ...templateResult, customers_changed: true }, templateBody));
});
test('owner and valid-customer guard prevent staff settings reads', () => {
  for (const props of [{ isOwner: false }, { customerId: 0 }, { customerId: -1 }]) { const h = harness(props); assert.equal(h.outer(), null); h.effects(); assert.equal(h.requests.length, 0); }
});
test('initial reads are parallel GETs only and invalid content ratio prevents a preview write', async () => {
  const h = harness(); await ready(h); assert.equal(h.requests[0].options.method, 'GET'); assert.equal(h.requests[1].options.method, 'GET');
  input(h.render(), '主推产品／服务比例').props.onChange({ target: { value: '70' } }); const tree = h.render(); assert.match(label(tree), /合计 120%/); assert.equal(button(tree, '预览本商家影响').props.disabled, true); assert.equal(h.requests.length, 2);
});
test('platform overrides and template copy remain local drafts without enabling publish or AI grants', async () => {
  const h = harness(); await ready(h); button(h.render(), 'Instagram继承').props.onClick(); let tree = h.render(); const independent = find(tree, node => node.type === 'label' && label(node) === '此平台独立设置'); find(independent, node => node.type === 'input').props.onChange({ target: { checked: true } }); changeTone(h); assert.equal(h.requests.length, 2);
  button(h.render(), '预览本商家影响').props.onClick(); const body = h.requests[2].options.data; assert.equal(body.document.platform_overrides.instagram.tone, 'professional'); assert.equal(body.document.defaults.tone, 'friendly'); assert.equal(body.document.timezone, 'America/Denver'); assert.ok(!('automatic_publish' in body.document));
  h.requests[2].resolve({ data: preview(body) }); await tick(); tree = h.render(); assert.ok(nodes(tree).some(node => node.props?.value?.targets?.length === 1));
});
test('impact preview explicitly preserves reviewed/scheduled content and needs confirmation before apply', async () => {
  const h = harness(); await ready(h); changeTone(h); button(h.render(), '预览本商家影响').props.onClick(); const body = h.requests[2].options.data, value = preview(body); h.requests[2].resolve({ data: value }); await tick();
  const form = find(h.render(), node => node.props?.value?.id === value.id); assert.equal(form.props.confirmed, false);
  const unchecked = h.previewRender(value); assert.match(label(unchecked), /已审核 1 批、已排期 1 批全部保留/); assert.equal(button(unchecked, '确认保存1家商家设置').props.disabled, true);
  form.props.onConfirm(true); find(h.render(), node => node.props?.value?.id === value.id).props.onApply(); assert.equal(h.requests.length, 4); const write = h.requests[3]; assert.equal(write.options.method, 'POST'); assert.equal(write.options.url, `/api/v1/media-automation-settings/previews/${value.id}/apply`); assert.notEqual(write.options.data.request_id, body.request_id); assert.equal(write.options.data.confirmed, true); assert.equal(h.held, true);
  write.resolve({ data: saved(value, write.options.data) }); await tick(); assert.equal(h.held, false); assert.equal(h.changed.length, 1); assert.ok(h.requests.every(row => !/publish|schedule|oauth|delivery-policy/.test(row.options.url)));
});
test('unknown preview is recovered by GET same request and never automatically reposted', async () => {
  const h = harness(); await ready(h); changeTone(h); button(h.render(), '预览本商家影响').props.onClick(); const body = h.requests[2].options.data; h.requests[2].reject(new Error('response lost')); await tick(); assert.equal(h.held, true); let tree = h.render(); assert.match(label(tree), /先不要重复提交/); button(tree, '查询原请求结果').props.onClick(); assert.equal(h.requests[3].options.method, 'GET'); assert.equal(h.requests[3].options.url, `/api/v1/media-automation-settings/requests/${body.request_id}`); h.requests[3].resolve({ data: preview(body) }); await tick(); assert.equal(h.held, false); assert.equal(h.requests.filter(row => row.options.method === 'POST').length, 1);
});
test('each new impact preview receives focus and scroll once without checking confirmation', async () => {
  const h = harness(); await ready(h); changeTone(h); button(h.render(), '预览本商家影响').props.onClick(); const value = preview(h.requests[2].options.data); h.requests[2].resolve({ data: value }); await tick();
  const control = find(h.render(), node => node.props?.value?.id === value.id), actions = [];
  control.props.focusRef.current = { focus: options => actions.push(['focus', options]), scrollIntoView: options => actions.push(['scroll', options]) };
  h.effects(); assert.equal(actions.length, 2); assert.equal(actions[0][1].preventScroll, true); assert.equal(actions[1][1].block, 'start'); assert.equal(actions[1][1].behavior, 'auto');
  h.render(); h.effects(); assert.equal(actions.length, 2); assert.equal(find(h.render(), node => node.props?.value?.id === value.id).props.confirmed, false);
  assert.equal(h.previewRender(value).props.tabIndex, -1);
});
test('unknown apply recovers immutable receipt without posting another settings version', async () => {
  const h = harness(); await ready(h); changeTone(h); button(h.render(), '预览本商家影响').props.onClick(); const value = preview(h.requests[2].options.data); h.requests[2].resolve({ data: value }); await tick(); let control = find(h.render(), node => node.props?.value?.id === value.id); control.props.onConfirm(true); control = find(h.render(), node => node.props?.value?.id === value.id); control.props.onApply(); const apply = h.requests[3]; apply.reject(new Error('response lost')); await tick(); button(h.render(), '查询原请求结果').props.onClick(); assert.equal(h.requests[4].options.url, `/api/v1/media-automation-settings/requests/${apply.options.data.request_id}`); h.requests[4].resolve({ data: saved(value, apply.options.data) }); await tick(); assert.equal(h.held, false); assert.equal(h.requests.filter(row => /\/apply$/.test(row.options.url)).length, 1);
});
test('saving a private template strips timezone and unknown save recovers same request', async () => {
  const h = harness(); await ready(h); input(h.render(), '私有自动化模板名称').props.onChange({ target: { value: 'PRIVATE RULES' } }); button(h.render(), '保存私有模板').props.onClick(); const post = h.requests[2]; assert.equal(post.options.data.document.timezone, null); assert.equal(post.options.url, '/api/v1/media-automation-settings/templates'); post.reject(new Error('response lost')); await tick(); button(h.render(), '查询原请求结果').props.onClick(); h.requests[3].resolve({ data: { request_id: post.options.data.request_id, template: template({ id: uuid(77), name: 'PRIVATE RULES', builtin: false }), customers_changed: false } }); await tick(); assert.equal(h.held, false); assert.equal(h.changed.length, 0); assert.equal(h.requests.filter(row => row.options.method === 'POST').length, 1); assert.match(label(h.render()), /未更改任何商家设置/);
});
test('batch copy caps selection at30 and sends only selected platforms and rule groups', async () => {
  const h = harness(); await ready(h); const opener = find(h.render(), node => node.props?.className === 'mas-copy-toggle'); opener.props.onClick(); h.render(); h.effects(); assert.equal(h.requests.length, 3); h.requests[2].resolve({ data: { items: Array.from({ length: 31 }, (_, i) => ({ id: 902 + i, name: `TARGET ${i}`, industry: 'restaurant' })), next_after: null } }); await tick();
  for (let i = 0; i < 31; i++) { const row = find(h.render(), node => node.type === 'label' && label(node).startsWith(`TARGET ${i}`)); find(row, node => node.type === 'input').props.onChange({ target: { checked: true } }); }
  assert.match(label(h.render()), /每次最多复制到30家/); button(h.render(), '预览30家商家影响').props.onClick(); const body = h.requests[3].options.data; assert.equal(body.target_ids.length, 30); assert.equal(body.kind, 'copy'); assert.ok(!('document' in body)); assert.ok(!('timezone' in body)); assert.deepEqual(Array.from(body.platforms), ['google_business', 'facebook', 'instagram']); assert.deepEqual(Array.from(body.groups), ['cadence', 'writing', 'content']);
});
test('late reads and retained write actions cannot affect unmounted or changed owner scopes', async () => {
  const h = harness(); await ready(h); changeTone(h); const trigger = button(h.render(), '预览本商家影响'); h.unmount(); trigger.props.onClick(); assert.equal(h.requests.length, 2);
  const next = harness(); await ready(next); changeTone(next); const old = button(next.render(), '预览本商家影响'); next.props.scope = 'owner:2'; next.render(); old.props.onClick(); assert.equal(next.requests.length, 2);
  const late = harness(); late.render(); late.effects(); late.unmount(); assert.equal(late.requests[0].options.options.signal.aborted, true); late.requests[0].resolve({ data: settings({ customer: { id: 902, name: 'OTHER MERCHANT', cooperation_active: true } }) }); await tick(); assert.doesNotMatch(label(late.render()), /OTHER MERCHANT/);
});
