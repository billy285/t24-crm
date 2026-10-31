import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url), ts = require('typescript');
const source = name => fs.readFileSync(new URL(name, import.meta.url), 'utf8');
const apiSource = source('../src/lib/meta-business-api.ts');
const componentSource = source('../src/components/MetaBusinessWorkspace.tsx');
function compile(body, imports = {}, extra = {}) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { module, exports: module.exports, require: name => imports[name] || {}, URL, URLSearchParams, Date, Set, Map, console, ...extra });
  return module.exports;
}
const api = compile(apiSource);
const auth = () => ({ provider: 'Meta', flow: 'Facebook Login for Business', client_id: '123456789012345', config_id: '987654321098765', graph_version: 'v24.0', token_type: 'user', requested_scopes: ['pages_show_list', 'pages_read_engagement', 'instagram_basic'], redirect_uri: api.META_CALLBACK_URI, token_storage: 'Synthetic encrypted server storage', purpose: 'Synthetic read-only account discovery', asset_types: ['Facebook Page', '关联的Instagram专业账号'] });
const connection = overrides => ({ id: 31, label: 'Synthetic owner connection', active: true, needs_reconnect: false, connected_at: '2026-11-01T08:00:00Z', last_error: null, revision: 2, ...overrides });
const binding = overrides => ({ id: 99, customer_id: 7, customer_name: 'Synthetic customer A', connection_id: 31, platform: 'facebook', asset_name: 'Synthetic Page A', asset_username: 'synthetic.a', active: true, revision: 1, publishing_implemented: false, comments_implemented: false, ...overrides });
const asset = overrides => ({ asset_ref: 'opaque-synthetic-asset-a', platform: 'facebook', name: 'Synthetic Page A', username: 'synthetic.a', linked_page_name: null, capability_observations: [], publishing_implemented: false, comments_implemented: false, ...overrides });
const status = overrides => ({ enabled: true, configured: true, setup_missing: [], is_owner: true, phase: 'connection', publishing_implemented: false, comments_implemented: false, connections: [connection()], bindings: [], capability_observations: [], authorization: auth(), ...overrides });
const oauth = () => { const u = new URL(`https://www.facebook.com/${auth().graph_version}/dialog/oauth`); u.search = new URLSearchParams({ client_id: auth().client_id, redirect_uri: api.META_CALLBACK_URI, response_type: 'code', state: 'synthetic-state-012345678901234567890', config_id: auth().config_id }).toString(); return u.href; };

test('only the exact configured Meta Business Login URL is accepted', () => {
  assert.equal(api.metaAuthorizationUrl(oauth(), auth()), oauth());
  for (const alter of [u => { u.hostname = 'facebook.com.attacker.test'; }, u => { u.protocol = 'http:'; }, u => { u.username = 'attacker'; }, u => { u.pathname = '/dialog/oauth'; }, u => { u.pathname = '/v25.0/dialog/oauth'; }, u => { u.searchParams.set('redirect_uri', 'https://attacker.test/callback'); }, u => { u.searchParams.set('config_id', '11111111111111'); }, u => { u.searchParams.set('client_id', '11111111111111'); }, u => { u.searchParams.set('scope', 'pages_manage_posts'); }, u => { u.searchParams.set('override_default_response_type', 'token'); }, u => { u.searchParams.set('response_type', 'token'); }, u => { u.searchParams.append('state', 'another-state'); }, u => { u.hash = 'fragment'; }]) {
    const u = new URL(oauth()); alter(u); assert.equal(api.metaAuthorizationUrl(u.href, auth()), null);
  }
});
test('connection-only metadata cannot silently enable publishing or employee access', () => {
  assert.equal(api.verifiedMetaStatus(status()).phase, 'connection');
  assert.throws(() => api.verifiedMetaStatus(status({ publishing_implemented: true })));
  assert.throws(() => api.verifiedMetaStatus(status({ is_owner: false })));
  assert.equal(api.verifiedMetaStatus(status({ configured: false, is_owner: false, connections: [], bindings: [], authorization: null })).connections.length, 0);
  assert.throws(() => api.verifiedMetaStatus(status({ authorization: { ...auth(), token_type: 'system' } })));
  assert.throws(() => api.verifiedMetaStatus(status({ authorization: { ...auth(), redirect_uri: 'https://attacker.test/callback' } })));
});
test('asset discovery requires opaque references and explicit connection-only capabilities', () => {
  assert.equal(api.verifiedMetaAssets({ items: [asset()], truncated: false }).items.length, 1);
  for (const row of [asset({ asset_ref: '' }), asset({ platform: 'google_business' }), asset({ comments_implemented: true }), asset({ publishing_implemented: true })]) assert.throws(() => api.verifiedMetaAssets({ items: [row], truncated: false }));
  assert.throws(() => api.verifiedMetaAssets({ items: [asset(), asset()], truncated: false }));
});

const tick = () => new Promise(resolve => setImmediate(resolve));
const label = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(label).join('') : label(node.props?.children);
const nodes = node => node == null || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
function find(tree, predicate) { const value = nodes(tree).find(predicate); assert.ok(value, 'Expected component control'); return value; }
const button = (tree, text) => find(tree, node => node.type === 'Button' && label(node) === text);
const control = (tree, name) => find(tree, node => node.props?.['aria-label'] === name);
function harness(kind = 'workspace') {
  const body = kind === 'workspace' ? componentSource : source('../src/components/MediaPlatformCapabilities.tsx');
  const states = [], refs = [], effects = [], queue = [], requests = [], navigation = [], changes = [];
  let stateIndex = 0, refIndex = 0, effectIndex = 0, requestId = 0, hold = false;
  const hooks = { useState(initial) { const i = stateIndex++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; }, useRef(initial) { const i = refIndex++; if (!(i in refs)) refs[i] = { current: initial }; return refs[i]; }, useCallback: value => value,
    useEffect(run, deps) { const i = effectIndex++, old = effects[i]; if (!old || deps.some((value, n) => value !== old.deps[n])) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: run() }; }); } };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth } });
  const fallback = new Proxy({}, { get: (_, name) => name === '__esModule' ? true : String(name) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/lib/meta-business-api': lib,
    '@/lib/media-operations-api': { mediaError: (cause, fallback) => cause.message || fallback, mediaErrorStatus: cause => cause.status || cause.response?.status, mediaRequestId: () => `00000000-0000-4000-8000-${String(++requestId).padStart(12, '0')}` },
    '@/lib/use-unsaved-changes': { useUnsavedChanges: () => ({ markSaved() {}, confirmDiscard: () => true }), useHardNavigationBlock: () => ({ lock() { hold = true; }, release() { hold = false; } }) },
    '@/lib/google-business-api': { googleBusinessApi: path => invokeWithAuth({ url: '/google' + path }).then(response => response.data), verifiedGbpStatus: value => value },
  }, { get: (value, name) => value[name] || fallback });
  const mod = compile(body, imports, { window: { location: { search: '', assign(url) { navigation.push(url); } } } });
  return { requests, navigation, changes, get held() { return hold; }, render(scope = 'owner:1', isOwner = true) { stateIndex = 0; refIndex = 0; effectIndex = 0; return mod.default({ scope, isOwner, onChanged: () => changes.push(true), onOpenMeta() {} }); }, effects() { while (queue.length) queue.shift()(); }, unmount() { effects.forEach(effect => effect?.cleanup?.()); } };
}
async function ownerReady(h, value = status()) { h.render(); h.effects(); assert.equal(h.requests[0].options.url, '/api/v1/meta-business/status'); h.requests[0].resolve({ data: value }); await tick(); return h.render(); }
function consent(h) { const tree = h.render(); find(tree, node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({ target: { checked: true } }); return h.render(); }
async function openBinding(h, initialStatus = status()) {
  button(await ownerReady(h, initialStatus), '绑定客户账号').props.onClick();
  h.requests[1].resolve({ data: { customers: [{ id: 7, name: 'Synthetic customer A' }, { id: 8, name: 'Synthetic customer B' }] } }); await tick();
  control(h.render(), 'Meta 绑定客户').props.onChange('7'); control(h.render(), 'Meta 绑定连接').props.onChange('31');
  h.requests[2].resolve({ data: { items: [asset()], truncated: false } }); await tick();
  control(h.render(), 'Meta 绑定平台账号').props.onChange(asset().asset_ref); return consent(h);
}

test('actual employee workspace performs no Meta read and exposes no owner account data', () => {
  const h = harness(); const tree = h.render('ops:2', false); h.effects();
  assert.equal(h.requests.length, 0); assert.match(label(tree), /连接阶段仅向老板开放/); assert.equal(nodes(tree).some(x => x.type === 'Button'), false);
});
test('actual incomplete configuration does not offer usable authorization or binding actions', async () => {
  const h = harness(); const tree = await ownerReady(h, status({ enabled: false, configured: false, setup_missing: ['T24_META_CLIENT_ID'], connections: [], authorization: null }));
  assert.equal(button(tree, '连接 Meta').props.disabled, true); assert.equal(button(tree, '绑定客户账号').props.disabled, true); assert.match(label(tree), /配置待完成/);
  button(tree, '连接 Meta').props.onClick(); const submit = button(h.render(), '前往 Meta 授权'); assert.equal(submit.props.disabled, true); submit.props.onClick(); assert.equal(h.requests.length, 1);
});
test('actual connection UI requires specific consent and opens one exact OAuth request on double click', async () => {
  const h = harness(); button(await ownerReady(h), '连接 Meta').props.onClick(); let tree = h.render();
  const before = button(tree, '前往 Meta 授权'); assert.equal(before.props.disabled, true); before.props.onClick(); assert.equal(h.requests.length, 1);
  tree = consent(h); const submit = button(tree, '前往 Meta 授权'); submit.props.onClick(); submit.props.onClick(); assert.equal(h.requests.length, 2);
  const data = h.requests[1].options.data; assert.equal(data.confirmed, true); assert.match(data.request_id, /^[0-9a-f-]{36}$/);
  h.requests[1].resolve({ data: { authorization_url: oauth(), expires_in: 600 } }); await tick(); assert.deepEqual(h.navigation, [oauth()]);
});
test('actual unknown OAuth start recovers the original UUID and never generates a second request', async () => {
  const h = harness(); button(await ownerReady(h), '连接 Meta').props.onClick(); button(consent(h), '前往 Meta 授权').props.onClick();
  const original = h.requests[1].options.data; h.requests[1].reject({ status: 503 }); await tick(); let tree = h.render(); assert.equal(h.held, true);
  find(tree, x => x.type === 'Dialog').props.onOpenChange(false); assert.ok(button(h.render(), '查询原请求'));
  button(tree, '查询原请求').props.onClick(); assert.equal(h.requests[2].options.url, `/api/v1/meta-business/oauth/requests/${original.request_id}`); h.requests[2].reject({ status: 404 }); await tick();
  button(h.render(), '沿用原编号确认').props.onClick(); assert.deepEqual(JSON.parse(JSON.stringify(h.requests[3].options.data)), JSON.parse(JSON.stringify(original)));
  h.requests[3].resolve({ data: { authorization_url: oauth(), expires_in: 590 } }); await tick(); assert.equal(h.navigation.length, 1);
});
test('actual rejected OAuth destinations never navigate and retain recoverable original identity', async () => {
  const h = harness(); button(await ownerReady(h), '连接 Meta').props.onClick(); button(consent(h), '前往 Meta 授权').props.onClick();
  h.requests[1].resolve({ data: { authorization_url: 'https://attacker.test/', expires_in: 600 } }); await tick(); assert.equal(h.navigation.length, 0); assert.ok(button(h.render(), '查询原请求'));
});
test('actual expired OAuth recovery rereads saved status without creating another authorization request', async () => {
  const h = harness(); button(await ownerReady(h), '连接 Meta').props.onClick(); button(consent(h), '前往 Meta 授权').props.onClick(); h.requests[1].reject({ status: 503 }); await tick();
  button(h.render(), '查询原请求').props.onClick(); h.requests[2].reject({ status: 409 }); await tick(); button(h.render(), '读取实际状态并结束本次请求').props.onClick();
  assert.equal(h.requests[3].options.url, '/api/v1/meta-business/status'); h.requests[3].resolve({ data: status() }); await tick();
  assert.equal(h.requests.filter(x => x.options.url === '/api/v1/meta-business/oauth/start').length, 1); assert.equal(h.held, false); assert.equal(h.navigation.length, 0);
  button(h.render(), '连接 Meta').props.onClick(); assert.equal(button(h.render(), '前往 Meta 授权').props.disabled, true);
});
test('actual late authorization response cannot navigate after owner switches to a staff account', async () => {
  const h = harness(); button(await ownerReady(h), '连接 Meta').props.onClick(); button(consent(h), '前往 Meta 授权').props.onClick();
  const tree = h.render('ops:2', false); h.effects(); h.requests[1].resolve({ data: { authorization_url: oauth(), expires_in: 600 } }); await tick();
  assert.equal(h.navigation.length, 0); assert.match(label(tree), /仅向老板开放/);
});
test('actual binding needs a verified customer, selected asset and explicit preview consent', async () => {
  const h = harness(); let tree = await openBinding(h); assert.match(label(tree), /Synthetic customer A/); assert.match(label(tree), /Synthetic Page A/);
  const save = button(tree, '确认绑定客户账号'); assert.equal(Boolean(save.props.disabled), false); save.props.onClick(); save.props.onClick(); assert.equal(h.requests.length, 4);
  const sent = h.requests[3].options; assert.equal(sent.url, '/api/v1/meta-business/bindings'); assert.equal(sent.data.customer_id, 7); assert.equal(sent.data.connection_id, 31); assert.equal(sent.data.asset_ref, asset().asset_ref);
  assert.equal(Object.keys(sent.data).some(key => /token|password|secret/.test(key)), false);
  h.requests[3].resolve({ data: binding() }); await tick(); assert.equal(h.changes.length, 1); assert.equal(h.requests.filter(x => x.options.method === 'POST').length, 1); assert.match(label(h.render()), /尚未开放发帖、评论或员工操作/);
});
test('actual uncertain binding reads the original result without resubmitting a new binding', async () => {
  const h = harness(); button(await openBinding(h), '确认绑定客户账号').props.onClick(); const original = h.requests[3].options.data.request_id;
  h.requests[3].reject({ status: 503 }); await tick(); button(h.render(), '查询原请求').props.onClick(); assert.equal(h.requests[4].options.url, `/api/v1/meta-business/requests/${original}`);
  h.requests[4].resolve({ data: binding() }); await tick(); assert.equal(h.requests.filter(x => x.options.method === 'POST').length, 1); assert.equal(h.changes.length, 1);
});
test('actual existing customer platform binding blocks duplicate submission even if old consent is forced', async () => {
  const h = harness(); await openBinding(h, status({ bindings: [binding()] })); const tree = h.render(); const submit = button(tree, '确认绑定客户账号');
  assert.equal(submit.props.disabled, true); assert.match(label(tree), /已有有效绑定/); submit.props.onClick(); assert.equal(h.requests.filter(x => x.options.method === 'POST').length, 0);
});
test('actual customer A to B to A changes discard old asset discoveries and previous consent', async () => {
  const h = harness(); await openBinding(h);
  control(h.render(), 'Meta 绑定客户').props.onChange('8'); const b = h.requests.at(-1);
  control(h.render(), 'Meta 绑定客户').props.onChange('7'); const a = h.requests.at(-1);
  b.resolve({ data: { items: [asset({ name: 'Stale B asset', asset_ref: 'stale-b' })], truncated: false } }); await tick(); assert.equal(label(h.render()).includes('Stale B asset'), false);
  a.resolve({ data: { items: [asset({ name: 'Fresh A asset', asset_ref: 'fresh-a' })], truncated: false } }); await tick();
  const tree = h.render(); assert.equal(button(tree, '确认绑定客户账号').props.disabled, true); assert.equal(control(tree, 'Meta 绑定平台账号').props.value, ''); assert.equal(nodes(tree).find(x => x.type === 'input' && x.props.type === 'checkbox').props.checked, false);
});
test('actual disconnection rereads actual status and does not touch public content endpoints', async () => {
  const h = harness(); let tree = await ownerReady(h, status({ bindings: [binding()] })); button(tree, '断开绑定').props.onClick(); button(consent(h), '确认断开').props.onClick();
  assert.equal(h.requests[1].options.url, '/api/v1/meta-business/bindings/99/disconnect'); assert.equal(h.requests[1].options.data.expected_revision, 1);
  h.requests[1].resolve({ data: {} }); await tick(); assert.equal(h.requests[2].options.url, '/api/v1/meta-business/status'); h.requests[2].resolve({ data: status({ bindings: [binding({ active: false, revision: 2 })] }) }); await tick();
  assert.match(label(h.render()), /已核对断开后的实际状态/); assert.equal(h.requests.some(x => /posts|comments|password/.test(x.options.url)), false);
});
test('actual connection disconnect carries the displayed revision and stale state forces a fresh confirmation', async () => {
  const h = harness(); button(await ownerReady(h), '断开').props.onClick(); button(consent(h), '确认断开').props.onClick();
  assert.equal(h.requests[1].options.url, '/api/v1/meta-business/connections/31/disconnect'); assert.equal(h.requests[1].options.data.expected_revision, 2);
  h.requests[1].reject({ status: 409 }); await tick(); assert.equal(h.requests[2].options.url, '/api/v1/meta-business/status');
  h.requests[2].resolve({ data: status({ connections: [connection({ revision: 3 })] }) }); await tick();
  assert.equal(h.requests.filter(x => x.options.method === 'POST').length, 1); button(h.render(), '断开').props.onClick(); assert.equal(button(h.render(), '确认断开').props.disabled, true);
});
test('platform capability strip keeps Google working independently of Meta errors and skips employee Meta fetches', async () => {
  const h = harness('capabilities'); h.render(); h.effects();
  const google = h.requests.find(x => x.options.url === '/google/status'), meta = h.requests.find(x => x.options.url === '/api/v1/meta-business/status');
  google.resolve({ data: { enabled: true, configured: true, is_owner: true, connections: [], bindings: [{ active: true }] } }); meta.reject(new Error('Synthetic Meta error')); await tick();
  const text = label(h.render()); assert.match(text, /已授权 · 1 家门店/); assert.match(text, /读取失败/); assert.match(text, /人工交付/);
  const staff = harness('capabilities'); staff.render('ops:2', false); staff.effects(); assert.equal(staff.requests.some(x => x.options.url === '/api/v1/meta-business/status'), false);
});
