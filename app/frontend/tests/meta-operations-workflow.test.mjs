import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = name => fs.readFileSync(new URL(name, import.meta.url), 'utf8');
const apiSource = source('../src/lib/meta-operations-api.ts'), componentSource = source('../src/components/MetaOperationsWorkspace.tsx');
function compile(body, imports = {}, extra = {}) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { module, exports: module.exports, require: name => name === '@/lib/media-provider-scope' ? compile(source('../src/lib/media-provider-scope.ts')) : imports[name] || {}, URL, URLSearchParams, Date, Set, Map, Blob, FormData, TextEncoder, TextDecoder, Uint8Array, DataView, crypto: webcrypto, btoa: value => Buffer.from(value, 'binary').toString('base64'), console, ...extra });
  return module.exports;
}
const images = compile(source('../src/lib/media-publication-images.ts')), api = compile(apiSource, { './media-publication-images': images });
const stamp = '2026-11-01T01:00:00Z', hash = 'a'.repeat(64), imageId = 'b'.repeat(32), commentRef = 'c'.repeat(32), postRef = 'd'.repeat(32);
const caps = extra => ({ can_publish: false, can_reply: false, can_read_posts: false, can_read_comments: false, can_schedule: false, blocked_reasons: ['Synthetic permission pending'], ...extra });
const binding = extra => ({ id: 5, connection_id: 1, customer_id: 7, customer_name: 'Synthetic merchant', platform: 'facebook', asset_name: 'Synthetic Page', revision: 1, operations_active: true, can_pause: true, paused: false, capabilities: caps(), ...extra });
const authorization = extra => ({ provider: 'Meta', flow: 'Facebook Login for Business', client_id: '123456789012345', config_id: '987654321098765', graph_version: 'v26.0', token_type: 'user', requested_scopes: [...api.META_OPS_REQUIRED_SCOPES], redirect_uri: api.META_OPS_CALLBACK_URI, token_storage: 'Synthetic storage', purpose: 'Synthetic operations', asset_types: ['Facebook Page'], ...extra });
const status = extra => ({ is_owner: true, pilot_label: 'Synthetic merchant', write_configured: false, setup_missing: [], scheduler: { enabled: false, activation_from: null }, authorization: null, bindings: [binding()], ...extra });
const draft = extra => ({ id: 12, binding_id: 5, kind: 'post', title: 'Synthetic draft', content: 'Synthetic text', media_id: null, target_ref: null, expected_target_version: null, status: 'draft', revision: 1, preview_hash: null, approved_at: null, created_at: stamp, updated_at: stamp, ...extra });
const approved = () => draft({ status: 'approved', revision: 2, preview_hash: hash, approved_at: stamp });
const media = extra => ({ id: imageId, sha256: hash, byte_size: 16, width: 640, height: 640, preview_path: `/api/v1/meta-operations/media/${imageId}/preview`, created_at: stamp, ...extra });
const workspace = extra => ({ binding: binding(), drafts: [], actions: [], schedules: [], media: [], ...extra });
const preview = (item = draft(), extra = {}) => ({ draft: item, preview_hash: hash, target: { customer_name: 'Synthetic merchant', platform: 'facebook', asset_name: 'Synthetic Page' }, media: null, warnings: [], ready_for_publish: false, reply_to: null, ...extra });
const action = extra => ({ id: 22, binding_id: 5, draft_id: 12, kind: 'post', request_id: '00000000-0000-4000-8000-000000000001', status: 'succeeded', revision: 1, can_continue: false, submitted_draft: { title: 'Synthetic draft', content: 'Synthetic text', media_id: null, kind: 'post', target_ref: null, draft_revision: 2, preview_hash: hash }, media: null, target: { customer_name: 'Synthetic merchant', platform: 'facebook', asset_name: 'Synthetic Page' }, message: 'Synthetic provider confirmed', provider_url: null, created_at: stamp, updated_at: stamp, ...extra });
const schedule = () => ({ id: 33, binding_id: 5, draft_id: 12, draft_revision: 2, planned_at: '2090-01-01T15:00:00Z', timezone: 'America/New_York', status: 'prepared', revision: 1, preview_hash: hash, submitted_draft: { title: 'Frozen planned text', content: 'Frozen planned content', media_id: null, kind: 'post', target_ref: null, draft_revision: 2, preview_hash: hash }, media: null, target: { customer_name: 'Synthetic merchant', platform: 'facebook', asset_name: 'Synthetic Page' }, message: 'Plan only', action_id: null, created_at: stamp });
const oauth = () => { const u = new URL(`https://www.facebook.com/${authorization().graph_version}/dialog/oauth`); u.search = new URLSearchParams({ client_id: authorization().client_id, redirect_uri: authorization().redirect_uri, response_type: 'code', state: 'synthetic-state-012345678901234567890', config_id: authorization().config_id }).toString(); return u.href; };

test('operations OAuth is bound to the distinct callback, exact app/config and user token', () => {
  assert.equal(api.metaOpsAuthorizationUrl(oauth(), authorization()), oauth());
  for (const change of [u => u.hostname = 'facebook.com.attacker.test', u => u.searchParams.set('redirect_uri', 'https://t24-crm.com/api/v1/meta-business/oauth/callback'), u => u.searchParams.set('config_id', '11111111111111'), u => u.searchParams.append('state', 'extra'), u => u.searchParams.set('scope', 'business_management')]) { const u = new URL(oauth()); change(u); assert.equal(api.metaOpsAuthorizationUrl(u.href, authorization()), null); }
  assert.equal(api.metaOpsAuthorizationUrl(oauth(), authorization({ token_type: 'system' })), null);
  assert.throws(() => api.verifiedMetaOpsStatus(status({ authorization: authorization({ requested_scopes: ['pages_show_list', 'pages_read_engagement', 'instagram_basic'] }) })));
  assert.equal(api.metaOpsAuthorizationUrl(oauth(), authorization({ requested_scopes: ['pages_show_list'] })), null);
  assert.equal(api.verifiedMetaOpsStatus(status({ authorization: authorization() })).authorization.requested_scopes.length, 8);
});
test('returned workspaces, previews and image paths cannot silently cross scope or change approved content', () => {
  assert.equal(api.verifiedMetaOpsStatus(status()).bindings.length, 1); assert.throws(() => api.verifiedMetaOpsStatus(status({ is_owner: false })));
  assert.throws(() => api.verifiedMetaOpsWorkspace(workspace({ drafts: [draft({ binding_id: 8 })] }), 5));
  assert.throws(() => api.verifiedMetaOpsMedia(media({ preview_path: 'https://attacker.test/a.jpg' })));
  for (const value of [preview(draft(), { draft: draft({ content: 'Changed' }) }), preview(draft(), { draft: approved() }), preview(draft(), { target: { customer_name: 'Wrong', platform: 'facebook', asset_name: 'Synthetic Page' } })]) assert.throws(() => api.verifiedMetaOpsPreview(value, draft(), binding()));
  const reply = draft({ kind: 'reply', target_ref: commentRef, expected_target_version: hash }); assert.throws(() => api.verifiedMetaOpsPreview(preview(reply), reply, binding()));
  assert.equal(api.verifiedMetaOpsPreview(preview(reply, { reply_to: { content: 'Comment', author_name: 'User', created_at: stamp, version: hash } }), reply, binding()).reply_to.content, 'Comment');
});
test('private JPEG preview checks bytes, dimensions and hash before producing a data URL', async () => {
  const bytes = new Uint8Array([255,216,255,192,0,11,8,0,10,0,12,1,1,17,0,255,217]), blob = new Blob([bytes]);
  const sha = Buffer.from(await webcrypto.subtle.digest('SHA-256', bytes)).toString('hex'), item = media({ sha256: sha, byte_size: bytes.length, width: 12, height: 10 });
  assert.match(await api.metaOpsImageDataUrl(item, blob), /^data:image\/jpeg;base64,/); await assert.rejects(() => api.metaOpsImageDataUrl(media({ ...item, sha256: hash }), blob)); await assert.rejects(() => api.metaOpsImageDataUrl(media({ ...item, width: 13 }), blob));
});
test('history must retain the original snapshot and external results stay on Meta hosts', () => {
  assert.equal(api.verifiedMetaOpsAction(action(), 5).submitted_draft.content, 'Synthetic text'); assert.throws(() => api.verifiedMetaOpsAction(action({ submitted_draft: null }), 5));
  assert.equal(api.metaOpsPublicUrl('https://www.instagram.com/p/example/'), 'https://www.instagram.com/p/example/'); for (const value of ['https://instagram.com.attacker.test/p', 'http://facebook.com/p', 'https://user:pass@facebook.com/p']) assert.equal(api.metaOpsPublicUrl(value), null);
});

const tick = () => new Promise(resolve => setImmediate(resolve));
const label = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(label).join('') : label(node.props?.children);
const nodes = node => node == null || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
function find(tree, predicate) { const result = nodes(tree).find(predicate); assert.ok(result, 'Expected component control'); return result; }
const button = (tree, text) => find(tree, node => node.type === 'Button' && label(node) === text), control = (tree, name) => find(tree, node => node.props?.['aria-label'] === name);
const privateImage = tree => find(tree, node => typeof node.type === 'function' && node.type.name === 'MetaPrivateImage');
const confirmation = tree => find(tree, node => node.type === 'input' && node.props.type === 'checkbox');
const consent = h => { find(h.render(), node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({ target: { checked: true } }); return h.render(); };
function harness({ search = '' } = {}) {
  const states = [], refs = [], effects = [], callbacks = [], queue = [], requests = [], navigation = []; let si = 0, ri = 0, ei = 0, ci = 0, ids = 0, held = false;
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const hooks = { useState(initial) { const i = si++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial; return [states[i], value => states[i] = typeof value === 'function' ? value(states[i]) : value]; }, useRef(initial) { const i = ri++; if (!(i in refs)) refs[i] = { current: initial }; return refs[i]; }, useCallback(fn, deps) { const i = ci++; if (!callbacks[i] || !equal(callbacks[i].deps, deps)) callbacks[i] = { fn, deps }; return callbacks[i].fn; }, useEffect(run, deps) { const i = ei++, old = effects[i]; if (!old || !equal(old.deps, deps)) queue.push(() => { old?.cleanup?.(); effects[i] = { deps, cleanup: run() }; }); } };
  const invokeWithAuth = options => new Promise((resolve, reject) => requests.push({ options, resolve, reject }));
  const lib = compile(apiSource, { './tokenStore': { invokeWithAuth }, './media-publication-images': images }), meta = compile(source('../src/lib/meta-business-api.ts'));
  const fallback = new Proxy({}, { get: (_, name) => name === '__esModule' ? true : String(name) });
  const imports = new Proxy({ react: hooks, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/lib/meta-operations-api': lib, '@/lib/meta-business-api': meta, '@/lib/media-publication-images': images, '@/lib/tokenStore': { invokeWithAuth }, '@/lib/media-operations-api': { mediaError: (e, m) => e?.message || m, mediaErrorStatus: e => e?.status, mediaRequestId: () => `00000000-0000-4000-8000-${String(++ids).padStart(12, '0')}`, mediaTimezones: [{ value: 'America/Denver', label: '美国山地时间' }, { value: 'America/New_York', label: '美东时间' }], mediaLocalToUtc: (v, zone) => new Date(v + (zone === 'America/New_York' ? ':00-05:00' : zone === 'America/Denver' ? ':00-07:00' : ':00+08:00')).toISOString(), mediaUtcToLocal: v => v }, '@/lib/use-unsaved-changes': { useUnsavedChanges: () => ({ markSaved() {}, confirmDiscard: () => true }), useHardNavigationBlock: () => ({ lock() { held = true; }, release() { held = false; } }) } }, { get: (value, name) => value[name] || fallback });
  const components = compile(componentSource, imports, { window: { location: { search, assign: url => navigation.push(url) } } });
  const resetHooks = () => { si = 0; ri = 0; ei = 0; ci = 0; };
  return { requests, navigation, get held() { return held; }, render(scope = 'owner:1', isOwner = true, target = {}) { resetHooks(); return components.default({ scope, isOwner, ...target }); }, renderImage(props) { resetHooks(); return components.MetaPrivateImage(props); }, effects() { while (queue.length) queue.shift()(); } };
}
async function ready(h, s = status(), w = workspace()) { h.render(); h.effects(); h.requests[0].resolve({ data: s }); await tick(); h.render(); h.effects(); assert.equal(h.requests[1].options.url, '/api/v1/meta-operations/bindings/5/workspace'); h.requests[1].resolve({ data: w }); await tick(); return h.render(); }
async function openPreview(h, item, opts = {}) { await ready(h, opts.status || status(), workspace({ drafts: [item] })); find(h.render(), node => typeof node.type === 'function' && node.type.name === 'DraftRows').props.onPreview(item); h.requests[2].resolve({ data: opts.preview || preview(item) }); await tick(); return h.render(); }
async function newDraft(h, text = 'New text') { button(await ready(h), '新建帖文').props.onClick(); control(h.render(), 'Meta 草稿正文').props.onChange({ target: { value: text } }); return h.render(); }

test('employee branch has no owner controls and makes zero Meta operations requests', () => { const h = harness(), tree = h.render('ops:2', false); h.effects(); assert.equal(h.requests.length, 0); assert.match(label(tree), /仅由老板操作/); assert.equal(nodes(tree).some(n => n.type === 'Button'), false); });
test('saving a write-gated draft sends only one internal request on double click', async () => { const h = harness(); const save = button(await newDraft(h), '仅保存草稿'); save.props.onClick(); save.props.onClick(); assert.equal(h.requests.length, 3); assert.equal(h.requests[2].options.url, '/api/v1/meta-operations/bindings/5/drafts'); h.requests[2].resolve({ data: draft({ content: 'New text' }) }); await tick(); assert.match(label(h.render()), /尚未公开发布/); assert.equal(h.requests.some(r => /publish$|continue$|schedules$/.test(r.options.url)), false); });
test('unknown creation queries the original request and cannot silently create a duplicate', async () => { const h = harness(); button(await newDraft(h), '仅保存草稿').props.onClick(); const original = h.requests[2].options; h.requests[2].reject({ status: 503 }); await tick(); assert.equal(h.held, true); button(h.render(), '查询原请求结果').props.onClick(); assert.equal(h.requests[3].options.url, `/api/v1/meta-operations/requests/${original.data.request_id}`); h.requests[3].reject({ status: 404 }); await tick(); button(h.render(), '沿用原编号确认').props.onClick(); assert.deepEqual(JSON.parse(JSON.stringify(h.requests[4].options)), JSON.parse(JSON.stringify(original))); h.requests[4].resolve({ data: draft() }); await tick(); assert.equal(h.held, false); });
test('preview and internal approval never publish, and approval needs its own explicit confirmation', async () => { const h = harness(); let approve = button(await openPreview(h, draft()), '确认审核当前版本'); assert.equal(label(h.render()).includes('原评论'), false); assert.match(label(h.render()), /本次纯文字正文/); assert.equal(approve.props.disabled, true); approve = button(consent(h), '确认审核当前版本'); approve.props.onClick(); assert.equal(h.requests[3].options.url, '/api/v1/meta-operations/drafts/12/approve'); h.requests[3].resolve({ data: approved() }); await tick(); assert.match(label(h.render()), /真实发布仍需重新核对预览/); assert.equal(h.requests.some(r => /publish$/.test(r.options.url)), false); });
test('write-gated approved content remains unpublishable even if old consent is forced', async () => { const h = harness(); await openPreview(h, approved()); const publish = button(consent(h), '确认公开发布'); assert.equal(publish.props.disabled, true); publish.props.onClick(); assert.equal(h.requests.some(r => /publish$/.test(r.options.url)), false); });
test('real confirmed publish uses the exact approved revision/hash and one stable request ID', async () => { const h = harness(), item = approved(); await openPreview(h, item, { status: status({ write_configured: true, bindings: [binding({ capabilities: caps({ can_publish: true }) })] }), preview: preview(item, { ready_for_publish: true }) }); const publish = button(consent(h), '确认公开发布'); publish.props.onClick(); publish.props.onClick(); assert.equal(h.requests.length, 4); const sent = h.requests[3].options; assert.equal(sent.data.expected_revision, 2); assert.equal(sent.data.preview_hash, hash); h.requests[3].resolve({ data: action({ request_id: sent.data.request_id }) }); await tick(); assert.match(label(h.render()), /平台已确认/); });
test('worker OFF saves only a confirmed future plan and changing time resets consent', async () => { const h = harness(); await openPreview(h, approved()); button(h.render(), '设置发布计划').props.onClick(); control(h.render(), 'Meta 计划发布时间').props.onChange({ target: { value: '2090-01-01T10:00' } }); consent(h); control(h.render(), 'Meta 计划时区').props.onChange('America/New_York'); assert.equal(button(h.render(), '保存发布计划（暂不执行）').props.disabled, true); button(consent(h), '保存发布计划（暂不执行）').props.onClick(); const sent = h.requests[3].options; assert.equal(sent.url, '/api/v1/meta-operations/drafts/12/schedules'); assert.equal(sent.data.timezone, 'America/New_York'); assert.equal(sent.data.execute_confirmed, false); h.requests[3].resolve({ data: schedule() }); await tick(); assert.equal(h.requests.some(r => /enable|dispatch|publish$/.test(r.options.url)), false); });
test('a late owner preview is discarded after switching to a staff identity', async () => { const h = harness(); await ready(h, status(), workspace({ drafts: [draft()] })); find(h.render(), node => typeof node.type === 'function' && node.type.name === 'DraftRows').props.onPreview(draft()); const request = h.requests[2]; h.render('ops:2', false); h.effects(); request.resolve({ data: preview() }); await tick(); const staff = h.render('ops:2', false); assert.match(label(staff), /仅由老板操作/); assert.equal(label(staff).includes('Synthetic text'), false); assert.equal(h.requests.some(r => /publish$/.test(r.options.url)), false); });
test('comment inbox stays gated when no actual platform-read capability exists', async () => { const h = harness(); await ready(h); find(h.render(), n => n.type === 'button' && label(n) === '评论回复').props.onClick(); assert.match(label(h.render()), /读取权限尚未就绪/); assert.equal(h.requests.some(r => /\/posts/.test(r.options.url)), false); });
test('reply drafts retain the selected comment reference and exact source version', async () => { const h = harness(); await ready(h, status({ bindings: [binding({ capabilities: caps({ can_read_posts: true, can_read_comments: true }) })] })); find(h.render(), n => n.type === 'button' && label(n) === '评论回复').props.onClick(); h.requests[2].resolve({ data: { items: [{ target_ref: postRef, content: 'Original post', created_at: stamp, permalink: null }], next_cursor: null } }); await tick(); control(h.render(), 'Meta 评论所属帖文').props.onChange(postRef); h.requests[3].resolve({ data: { items: [{ target_ref: commentRef, post_ref: postRef, content: 'Original comment', author_name: 'User', created_at: stamp, version: hash }], next_cursor: null } }); await tick(); button(h.render(), '准备回复').props.onClick(); control(h.render(), 'Meta 草稿正文').props.onChange({ target: { value: 'Reply only' } }); button(h.render(), '仅保存草稿').props.onClick(); assert.equal(h.requests[4].options.data.kind, 'reply'); assert.equal(h.requests[4].options.data.target_ref, commentRef); assert.equal(h.requests[4].options.data.expected_target_version, hash); assert.equal(h.requests.some(r => /publish$/.test(r.options.url)), false); });

test('an approved record with a changed preview fingerprint requires approval again before publication', async () => {
  const h = harness(), item = approved(), changed = 'e'.repeat(64);
  await openPreview(h, item, { status: status({ write_configured: true, bindings: [binding({ capabilities: caps({ can_publish: true }) })] }), preview: preview(item, { preview_hash: changed, ready_for_publish: true }) });
  const tree = h.render(); assert.match(label(tree), /请重新审核当前预览/); assert.ok(button(tree, '确认审核当前版本')); assert.equal(nodes(tree).some(node => node.type === 'Button' && label(node) === '确认公开发布'), false); assert.equal(h.requests.some(row => /publish$/.test(row.options.url)), false);
});
test('prepared schedule activation stays unavailable when worker execution is OFF', async () => {
  const h = harness(); await ready(h, status(), workspace({ schedules: [schedule()] })); find(h.render(), node => node.type === 'button' && label(node) === '发布排期').props.onClick();
  const activate = button(h.render(), '启用此排期'); assert.equal(activate.props.disabled, true); assert.equal(h.requests.some(row => /activate$/.test(row.options.url)), false);
});
test('enabling one prepared plan needs original frozen content and separate explicit execution consent', async () => {
  const h = harness(), s = status({ write_configured: true, scheduler: { enabled: true, activation_from: stamp }, bindings: [binding({ capabilities: caps({ can_publish: true, can_schedule: true }) })] });
  await ready(h, s, workspace({ schedules: [schedule()] })); find(h.render(), node => node.type === 'button' && label(node) === '发布排期').props.onClick(); button(h.render(), '启用此排期').props.onClick();
  assert.match(label(h.render()), /Frozen planned content/); assert.equal(button(h.render(), '确认启用此排期').props.disabled, true); button(consent(h), '确认启用此排期').props.onClick();
  assert.equal(h.requests[2].options.url, '/api/v1/meta-operations/schedules/33/activate'); assert.equal(h.requests[2].options.data.expected_revision, 1); assert.equal(h.requests[2].options.data.confirmed, true); h.requests[2].resolve({ data: { ...schedule(), status: 'scheduled', revision: 2 } }); await tick(); assert.equal(h.requests.some(row => /publish$/.test(row.options.url)), false);
});
test('a reserved pending action continues only the original request after confirming its frozen snapshot', async () => {
  const h = harness(), reserved = action({ status: 'pending', can_continue: true }); await ready(h, status({ write_configured: true, bindings: [binding({ capabilities: caps({ can_publish: true }) })] }), workspace({ actions: [reserved] })); find(h.render(), node => node.type === 'button' && label(node) === '操作记录').props.onClick(); button(h.render(), '查看原结果').props.onClick();
  h.requests[2].resolve({ data: reserved }); await tick(); assert.match(label(h.render()), /Synthetic text/); assert.equal(button(h.render(), '检查并继续原请求').props.disabled, true); button(consent(h), '检查并继续原请求').props.onClick(); assert.equal(h.requests[3].options.url, '/api/v1/meta-operations/actions/22/continue'); assert.equal(h.requests[3].options.data.expected_revision, 1);
  h.requests[3].reject({ status: 503 }); await tick(); button(h.render(), '读取实际操作状态').props.onClick(); assert.equal(h.requests[4].options.url, '/api/v1/meta-operations/actions/22'); h.requests[4].resolve({ data: action({ status: 'unknown' }) }); await tick(); assert.equal(h.requests.filter(row => /continue$/.test(row.options.url)).length, 1); assert.equal(h.requests.some(row => /publish$/.test(row.options.url)), false);
});

test('unknown operations OAuth recovers the direct saved URL using the original request ID', async () => {
  const h = harness(); await ready(h, status({ write_configured: true, authorization: authorization() })); button(h.render(), '补充运营授权').props.onClick(); button(consent(h), '前往 Meta 运营授权').props.onClick(); const id = h.requests[2].options.data.request_id;
  h.requests[2].reject({ status: 503 }); await tick(); button(h.render(), '查询原请求结果').props.onClick(); assert.equal(h.requests[3].options.url, `/api/v1/meta-operations/oauth/requests/${id}`); h.requests[3].resolve({ data: { authorization_url: oauth(), expires_in: 590 } }); await tick(); assert.deepEqual(h.navigation, [oauth()]); assert.equal(h.requests.filter(row => row.options.url.endsWith('/oauth/start')).length, 1);
});
test('an expired unknown OAuth rereads current state and exits the navigation hold without starting another flow', async () => {
  const h = harness(), s = status({ write_configured: true, authorization: authorization() }); await ready(h, s); button(h.render(), '补充运营授权').props.onClick(); button(consent(h), '前往 Meta 运营授权').props.onClick(); h.requests[2].reject({ status: 503 }); await tick(); button(h.render(), '查询原请求结果').props.onClick(); h.requests[3].reject({ status: 409 }); await tick(); button(h.render(), '读取实际状态并结束本次授权').props.onClick(); assert.equal(h.requests[4].options.url, '/api/v1/meta-operations/status'); h.requests[4].resolve({ data: s }); await tick(); assert.equal(h.held, false); assert.equal(h.navigation.length, 0); assert.equal(h.requests.filter(row => row.options.url.endsWith('/oauth/start')).length, 1);
});

test('pausing independent operations needs target-specific consent and leaves old read endpoints untouched', async () => {
  const h = harness(); await ready(h); button(h.render(), '暂停此账号操作').props.onClick(); assert.match(label(h.render()), /只读连接、已公开内容与历史记录保留/); const save = button(h.render(), '确认暂停此账号操作'); assert.equal(save.props.disabled, true); button(consent(h), '确认暂停此账号操作').props.onClick(); assert.equal(h.requests[2].options.url, '/api/v1/meta-operations/bindings/5/disconnect'); assert.equal(h.requests[2].options.data.expected_revision, 1);
  h.requests[2].resolve({ data: binding({ operations_active: false, can_pause: false, paused: true, revision: 2 }) }); await tick(); assert.match(label(h.render()), /独立运营操作已暂停/); assert.equal(h.requests.some(row => row.options.url.startsWith('/api/v1/meta-business')), false); h.requests[3].resolve({ data: workspace({ binding: binding({ operations_active: false, can_pause: false, paused: true, revision: 2 }) }) }); await tick(); assert.equal(button(h.render(), '新建帖文').props.disabled, true);
});
test('unknown pause rereads only independent authority state rather than repeating the pause request', async () => {
  const h = harness(); await ready(h); button(h.render(), '暂停此账号操作').props.onClick(); button(consent(h), '确认暂停此账号操作').props.onClick(); h.requests[2].reject({ status: 503 }); await tick(); button(h.render(), '读取实际操作状态').props.onClick(); assert.equal(h.requests[3].options.url, '/api/v1/meta-operations/status'); h.requests[3].resolve({ data: status({ bindings: [binding({ operations_active: false, can_pause: false, paused: true, revision: 2 })] }) }); await tick(); assert.equal(h.requests.filter(row => /disconnect$/.test(row.options.url)).length, 1); assert.equal(h.held, false);
});

test('abandoning an unuploaded image keeps the written draft and restores text-only saving', async () => {
  const h = harness(); await newDraft(h, 'Keep this written draft'); control(h.render(), 'Meta 试点 JPEG 图片').props.onChange({ target: { files: [{ name: 'local-test.jpg', size: 100 }] } }); assert.equal(button(h.render(), '仅保存草稿').props.disabled, true); button(h.render(), '放弃所选图片').props.onClick(); assert.equal(control(h.render(), 'Meta 草稿正文').props.value, 'Keep this written draft'); assert.equal(button(h.render(), '仅保存草稿').props.disabled, false); assert.equal(h.requests.length, 2);
});


test('an already loaded private image is revalidated when preview becomes a schedule', async () => {
  const h = harness(), item = { ...approved(), media_id: imageId };
  await openPreview(h, item, { preview: preview(item, { media: media() }) });
  const before = privateImage(h.render()); assert.equal(confirmation(h.render()).props.disabled, true);
  before.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, false);
  button(h.render(), '设置发布计划').props.onClick();
  const planned = privateImage(h.render()); assert.notEqual(planned.props.scope, before.props.scope);
  assert.equal(planned.props.image.id, before.props.image.id); assert.equal(confirmation(h.render()).props.disabled, true);
  before.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, true, 'stale preview load cannot approve the new operation');
  planned.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, false);
  control(h.render(), 'Meta 计划发布时间').props.onChange({ target: { value: '2090-01-01T10:00' } });
  button(consent(h), '保存发布计划（暂不执行）').props.onClick();
  assert.equal(h.requests[3].options.data.execute_confirmed, false); assert.equal(h.requests[3].options.data.preview_hash, hash);
  assert.equal(h.requests.some(row => /publish$/.test(row.options.url)), false);
});

test('reading an unchanged original action renews image verification without creating another publish', async () => {
  const h = harness(), reserved = action({ status: 'pending', can_continue: true, media: media(), submitted_draft: { ...action().submitted_draft, media_id: imageId } });
  await ready(h, status({ write_configured: true, bindings: [binding({ capabilities: caps({ can_publish: true }) })] }), workspace({ actions: [reserved] }));
  find(h.render(), node => node.type === 'button' && label(node) === '操作记录').props.onClick(); button(h.render(), '查看原结果').props.onClick();
  h.requests[2].resolve({ data: reserved }); await tick(); const before = privateImage(h.render()); before.props.onReady(true);
  assert.equal(button(consent(h), '检查并继续原请求').props.disabled, false);
  button(h.render(), '查询原结果').props.onClick(); h.requests[3].resolve({ data: reserved }); await tick();
  const refreshed = privateImage(h.render()); assert.notEqual(refreshed.props.scope, before.props.scope); assert.equal(confirmation(h.render()).props.disabled, true);
  before.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, true);
  refreshed.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, false); assert.equal(button(h.render(), '检查并继续原请求').props.disabled, true, 'fresh explicit consent is still required');
  assert.equal(h.requests.filter(row => /publish$|continue$/.test(row.options.url)).length, 0);
});

test('a rejected approval renews the same mounted image and requires fresh confirmation', async () => {
  const h = harness(), item = draft({ media_id: imageId });
  await openPreview(h, item, { preview: preview(item, { media: media() }) }); const before = privateImage(h.render()); before.props.onReady(true);
  button(consent(h), '确认审核当前版本').props.onClick(); h.requests[3].reject({ status: 409, message: 'Synthetic revision changed' }); await tick();
  h.requests[4].resolve({ data: workspace({ drafts: [item], media: [media()] }) }); await tick();
  const refreshed = privateImage(h.render()); assert.notEqual(refreshed.props.scope, before.props.scope); assert.equal(confirmation(h.render()).props.disabled, true);
  before.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, true);
  refreshed.props.onReady(true); assert.equal(confirmation(h.render()).props.disabled, false);
  assert.equal(button(h.render(), '确认审核当前版本').props.disabled, true); assert.equal(button(consent(h), '确认审核当前版本').props.disabled, false);
  assert.equal(h.requests.filter(row => /approve$/.test(row.options.url)).length, 1); assert.equal(h.requests.some(row => /publish$/.test(row.options.url)), false);
});

test('an upload conflict refreshes an existing private preview while preserving the draft and selected media', async () => {
  const h = harness(), item = draft({ media_id: imageId }), w = workspace({ drafts: [item], media: [media()] });
  await ready(h, status(), w); find(h.render(), node => typeof node.type === 'function' && node.type.name === 'DraftRows').props.onEdit(item);
  const before = privateImage(h.render()); control(h.render(), 'Meta 草稿正文').props.onChange({ target: { value: 'Keep my edited text after upload conflict' } });
  assert.equal(privateImage(h.render()).props.scope, before.props.scope, 'typing does not repeatedly reload immutable bytes');
  const bytes = new Uint8Array([255,216,255,192,0,11,8,0,10,0,12,1,1,17,0,255,217]);
  const file = Object.assign(new Blob([bytes], { type: 'image/jpeg' }), { name: 'local-test.jpg' });
  control(h.render(), 'Meta 试点 JPEG 图片').props.onChange({ target: { files: [file] } }); confirmation(h.render()).props.onChange({ target: { checked: true } });
  button(h.render(), '保存私有图片版本').props.onClick(); await tick(); assert.equal(h.requests[2].options.url, '/api/v1/meta-operations/bindings/5/media');
  h.requests[2].reject({ status: 409, message: 'Synthetic upload conflict' }); await tick(); h.requests[3].resolve({ data: w }); await tick();
  assert.notEqual(privateImage(h.render()).props.scope, before.props.scope); assert.equal(control(h.render(), 'Meta 草稿固定图片').props.value, imageId);
  assert.equal(control(h.render(), 'Meta 草稿正文').props.value, 'Keep my edited text after upload conflict');
  assert.equal(button(h.render(), '仅保存草稿').props.disabled, true); button(h.render(), '放弃所选图片').props.onClick();
  assert.equal(button(h.render(), '仅保存草稿').props.disabled, false); assert.equal(h.requests.filter(row => /\/media$/.test(row.options.url)).length, 1);
  assert.equal(h.requests.some(row => /publish$|approve$/.test(row.options.url)), false);
});

test('the actual private-image effect rechecks the same bytes on a new verification scope and ignores the old load', async () => {
  const h = harness(), changes = [], bytes = new Uint8Array([255,216,255,192,0,11,8,0,10,0,12,1,1,17,0,255,217]);
  const sha = Buffer.from(await webcrypto.subtle.digest('SHA-256', bytes)).toString('hex'), item = media({ sha256: sha, byte_size: bytes.length, width: 12, height: 10 });
  const props = { image: item, scope: 'owner:1:preview:1', onReady: value => changes.push(value) };
  h.renderImage(props); h.effects(); assert.deepEqual(changes, [false]); h.requests[0].resolve({ data: new Blob([bytes]) });
  for (let i = 0; i < 5; i++) await tick();
  const before = find(h.renderImage(props), node => node.type === 'img'); before.props.onLoad(); assert.deepEqual(changes, [false, true]);
  const next = { ...props, scope: 'owner:1:schedule:2' }; h.renderImage(next); h.effects(); assert.deepEqual(changes, [false, true, false]);
  before.props.onLoad(); assert.deepEqual(changes, [false, true, false]); assert.equal(h.requests.length, 2);
  h.requests[1].resolve({ data: new Blob([bytes]) }); for (let i = 0; i < 5; i++) await tick();
  find(h.renderImage(next), node => node.type === 'img').props.onLoad(); assert.deepEqual(changes, [false, true, false, true]);
});


test('a saved operations grant is shown as connected while public execution remains disabled', async () => {
  const h = harness({ search: '?meta_ops=connected' }), item = approved();
  const granted = binding({ capabilities: caps({ can_read_posts: true, can_read_comments: true, blocked_reasons: ['真实发布和回复尚未启用，可先准备并核对内容'] }) });
  await ready(h, status({ write_configured: true, bindings: [granted] }), workspace({ binding: granted, drafts: [item] }));
  let tree = h.render(); assert.match(label(tree), /独立运营授权已建立。公开提交仍取决于下方执行状态/);
  const strip = label(control(tree, '当前 Meta 操作能力'));
  assert.match(strip, /帖文：暂不可执行，原因见下方/); assert.match(strip, /评论：暂不可执行，原因见下方/); assert.match(strip, /排期：仅保存计划，执行未启用/);
  assert.equal(/待开通发布权限|待开通回复权限|请核对账号授权/.test(label(tree)), false);
  assert.match(label(tree), /真实发布和回复尚未启用/);
  find(tree, node => typeof node.type === 'function' && node.type.name === 'DraftRows').props.onPreview(item);
  h.requests[2].resolve({ data: preview(item) }); await tick();
  const publish = button(consent(h), '确认公开发布'); assert.equal(publish.props.disabled, true); publish.props.onClick();
  assert.equal(h.requests.some(row => /publish$|continue$|activate$/.test(row.options.url)), false);
});

test('callback query success alone does not claim an operations grant or enable public actions', async () => {
  const h = harness({ search: '?meta_ops=connected' }), ungranted = binding({ operations_active: false, can_pause: false });
  await ready(h, status({ write_configured: true, bindings: [ungranted] }), workspace({ binding: ungranted }));
  const tree = h.render(), strip = label(control(tree, '当前 Meta 操作能力'));
  assert.match(label(tree), /尚未确认有效的独立运营授权/); assert.match(strip, /帖文：待运营授权/); assert.match(strip, /评论：待运营授权/);
  assert.equal(label(tree).includes('独立运营授权已建立。'), false); assert.equal(h.requests.some(row => /publish$|continue$|activate$/.test(row.options.url)), false);
});

test('paused operations is labelled separately from a grant waiting for execution', async () => {
  const h = harness(), paused = binding({ operations_active: false, can_pause: false, paused: true });
  await ready(h, status({ write_configured: true, bindings: [paused] }), workspace({ binding: paused }));
  const strip = label(control(h.render(), '当前 Meta 操作能力'));
  assert.match(strip, /运营已暂停/); assert.match(strip, /帖文：操作已暂停/); assert.match(strip, /评论：操作已暂停/);
  assert.equal(button(h.render(), '新建帖文').props.disabled, true); assert.equal(h.requests.some(row => /publish$|continue$|activate$/.test(row.options.url)), false);
});


test('merchant and platform scope cannot select another customer or fall back to the first account', async () => {
  const h = harness(), render = () => h.render('owner:1', true, { customerId: 8, platformFilter: 'instagram' });
  render(); h.effects(); h.requests[0].resolve({ data: status({ bindings: [binding(), binding({ id: 6, customer_id: 8, platform: 'facebook' })] }) });
  await tick(); const tree = render(); h.effects();
  assert.equal(h.requests.length, 1); assert.match(label(tree), /先绑定/); assert.doesNotMatch(label(tree), /Synthetic Page/);
});
test('merchant scope selects only its matching platform and invalidates old workspace replies', async () => {
  const h = harness(), render = customerId => h.render('owner:1', true, { customerId, platformFilter: 'instagram' });
  render(8); h.effects(); h.requests[0].resolve({ data: status({ bindings: [binding(), binding({ id: 6, customer_id: 8, platform: 'instagram' })] }) });
  await tick(); render(8); h.effects(); assert.equal(h.requests[1].options.url, '/api/v1/meta-operations/bindings/6/workspace');
  render(9); h.effects(); h.requests[1].resolve({ data: workspace({ binding: binding({ id: 6, customer_id: 8, platform: 'instagram' }), drafts: [draft({ binding_id: 6, title: 'Old merchant confidential draft' })] }) });
  await tick(); assert.doesNotMatch(label(render(9)), /Old merchant confidential draft/);
  assert.equal(h.requests.filter(row => row.options.method !== 'GET').length, 0);
});
