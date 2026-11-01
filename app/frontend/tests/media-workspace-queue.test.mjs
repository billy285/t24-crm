import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('typescript');
const source = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(body, imports = {}) { const module = { exports: {} }; vm.runInNewContext(ts.transpileModule(body, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module, exports: module.exports, require: name => imports[name] || {}, URLSearchParams, Date, Set, Map, DOMException, console }); return module.exports; }
const api = compile(source('../src/lib/media-workspace-api.ts'));
const queue = compile(source('../src/lib/media-workspace-queue.ts'), { './media-workspace-api': api });
const scope = { platform: 'google_business', status: 'review', operatorId: 9, from: '2026-11-01', to: '2026-11-30', search: 'Restaurant' };
const baseQueue = { month: '2026-11', basis: 'monthly_plan', target: 12, prepared: 12, in_review: 12, scheduled: 0, published: 0, readiness: 'ready', checks: [{ key: 'account', label: '账号已绑定', state: 'ready' }], next_action: { kind: 'monthly', label: '审核本月内容', run_id: 2 }, can_prepare_monthly: true };
const merchant = id => ({ id, name: `Restaurant ${id}`, platforms: ['google_business'], can_create: false, can_edit: false, work_queue: { ...baseQueue } });
const page = (items, next = null, extra = {}) => ({ items, total: 36, next_cursor: next, partial: !!next, observed_at: '2026-11-02T12:00:00Z', sources: [], sources_complete: true, ...extra });
function reader(items, requests) { return async path => { const query = new URL(path, 'https://local.test').searchParams, cursor = query.get('cursor'), index = cursor ? Number(cursor.split('-')[1]) : 0; requests.push(query); return page(items.slice(index, index + 12), index + 12 < items.length ? `page-${index + 12}` : null); }; }
const label = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(label).join('') : label(node.props?.children);
const nodes = node => node == null || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const panels = compile(source('../src/components/MediaPortfolioPanels.tsx'), { react: { useState: value => [value, () => {}], useEffect() {} }, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/lib/media-workspace-api': api, '@/lib/media-operations-api': { mediaUtcToLocal: value => value }, 'lucide-react': new Proxy({}, { get: (_, name) => name }), '@/components/ui/button': { Button: 'Button' }, '@/components/ui/native-select': { NativeSelect: 'NativeSelect' } });

test('next merchant crosses the 30-shop queue retaining every filter and the exact destination page', async () => {
  const requests = [], all = Array.from({ length: 36 }, (_, i) => merchant(i + 1));
  const result = await queue.readNextQueueMerchant(scope, 24, new Set(Array.from({ length: 24 }, (_, i) => i + 1)), undefined, reader(all, requests));
  assert.equal(result.merchant.id, 25); assert.equal(result.cursor, 'page-24'); assert.deepEqual([...result.history], [null, 'page-12']);
  assert.equal(requests.length, 3);
  for (const query of requests) { assert.equal(query.get('q'), 'Restaurant'); assert.equal(query.get('status'), 'review'); assert.equal(query.get('platform'), 'google_business'); assert.equal(query.get('operator_id'), '9'); assert.equal(query.get('start'), '2026-10-31T16:00:00.000Z'); assert.equal(query.get('end'), '2026-11-30T16:00:00.000Z'); }
});
test('resolved or revoked current merchant is never reused from cache; next comes from fresh matching scope', async () => {
  const requests = [], live = [merchant(3), merchant(30), merchant(34)];
  const result = await queue.readNextQueueMerchant(scope, 29, new Set([3, 29]), undefined, reader(live, requests));
  assert.equal(result.merchant.id, 30); assert.equal(requests.length, 1);
  assert.equal(await queue.readNextQueueMerchant(scope, 29, new Set([3, 29, 30, 34]), undefined, reader(live, [])), null);
});
test('next merchant refuses duplicate pagination, cursor cycles, malformed readiness and cancelled reads', async () => {
  await assert.rejects(queue.readNextQueueMerchant(scope, 4, new Set([1, 2, 3, 4]), undefined, async () => page([merchant(1)], 'again')), /分页|变化/);
  await assert.rejects(queue.readNextQueueMerchant(scope, 4, new Set(), undefined, async () => page([{ ...merchant(1), work_queue: { ...baseQueue, readiness: 'ready', target: -1 } }])), /不完整/);
  const controller = new AbortController(); controller.abort(); let calls = 0;
  await assert.rejects(queue.readNextQueueMerchant(scope, 4, new Set(), controller.signal, async () => { calls++; return page([]); }), { name: 'AbortError' }); assert.equal(calls, 0);
});
test('exact editorial month is only derived for a complete valid calendar month', () => {
  assert.equal(queue.queueMonth('2026-11-01', '2026-11-30'), '2026-11'); assert.equal(queue.queueMonth('2028-02-01', '2028-02-29'), '2028-02');
  for (const range of [['2026-11-02', '2026-11-30'], ['2026-11-01', '2026-11-29'], ['2026-02-01', '2026-02-29'], ['2026-11-01', '2026-12-31']]) assert.equal(queue.queueMonth(...range), null);
});
test('thirty shops display distinct progress and actions without authorizing a write', () => {
  const opened = [], items = Array.from({ length: 30 }, (_, i) => ({ ...merchant(i + 1), work_queue: { ...baseQueue, prepared: i, in_review: 30 - i } }));
  const tree = panels.MerchantStatusList({ items, isOwner: true, onChoose: row => opened.push(row.id), onAction: (row, action) => opened.push([row.id, action.kind]) });
  assert.equal(nodes(tree).filter(node => node.props?.className === 'mw-operation-row').length, 30); assert.match(label(tree), /目标 12 篇/); assert.match(label(tree), /已准备/); assert.match(label(tree), /已确认发布/);
  const actions = nodes(tree).filter(node => node.type === 'Button'); actions[29].props.onClick(); assert.deepEqual(opened, [[30, 'monthly']]);
  assert.equal(nodes(tree).some(node => node.type === 'Button' && /确认发布|启用|转派|授权/.test(label(node))), false);
});
test('staff never receives monthly action buttons; unknown readiness never promises ready or zero target', () => {
  const staff = panels.MerchantStatusList({ items: [merchant(1)], isOwner: false, onChoose() {}, onAction() {} });
  assert.equal(label(staff).includes('审核本月内容'), false); assert.match(label(staff), /进入工作台/);
  const unknown = panels.MerchantStatusList({ items: [{ ...merchant(1), work_queue: undefined }], onChoose() {} }); assert.match(label(unknown), /目标待确认/); assert.match(label(unknown), /来源待核对/); assert.equal(label(unknown).includes('目标 0 篇'), false);
  const readiness = panels.MerchantReadiness({ merchant: { ...merchant(1), work_queue: { ...baseQueue, readiness: 'unknown', checks: [{ key: 'source', state: 'unknown', label: '门店资料待读取' }] } } });
  assert.match(label(readiness), /就绪情况待核对/); assert.match(label(readiness), /门店资料待读取/); assert.equal(label(readiness).includes('可以继续准备'), false);
});
test('monthly action cannot pass response validation without owner preparation capability', () => {
  assert.throws(() => api.verifiedWorkspaceMerchants(page([{ ...merchant(1), work_queue: { ...baseQueue, can_prepare_monthly: false } }])), /不完整/);
  assert.throws(() => api.verifiedWorkspaceMerchants(page([{ ...merchant(1), work_queue: { ...baseQueue, checks: [baseQueue.checks[0], baseQueue.checks[0]] } }])), /不完整/);
});

test('thirty merchants expose ninety exact platform-month entry points without combining their batches', () => {
  const opened=[],month='2026-11',platforms=['google_business','facebook','instagram'];
  const items=Array.from({length:30},(_,i)=>({...merchant(i+1),platforms,work_queue:{...baseQueue,platform:null,platforms,basis:'multi_platform_monthly',target:36,platform_progress:platforms.map((platform,index)=>({platform,month,run_id:(i+1)*10+index+1,status:index===0?'prepared':index===1?'reviewed':'schedule_prepared',target:12,prepared:12,in_review:index===0?12:0,schedule_prepared:index===2?12:0,scheduled:0,published:0,can_prepare_monthly:true}))}}));
  api.verifiedWorkspaceMerchants(page(items));
  const tree=panels.MerchantStatusList({items,isOwner:true,onChoose(){},onAction:(row,action)=>opened.push({customer:row.id,...action})});
  const pills=nodes(tree).filter(node=>node.type==='button'&&node.props?.children?.[0]?.type==='strong'&&platforms.some(platform=>label(node).startsWith(api.workspacePlatformLabels[platform])));
  assert.equal(pills.length,90);pills.at(-1).props.onClick();assert.deepEqual(opened,[{customer:30,kind:'monthly',platform:'instagram',month,run_id:303,label:'Instagram整月内容'}]);
  assert.match(label(tree),/待发布确认 12/);assert.match(label(tree),/目标 36 篇/);
  const staff=panels.MerchantStatusList({items,isOwner:false,onChoose(){},onAction(){throw new Error('Staff action forbidden');}});assert.equal(nodes(staff).some(node=>node.type==='button'&&node.props?.children?.[0]?.type==='strong'),false);
  for(const invalid of [{...items[0].work_queue,platform_progress:[items[0].work_queue.platform_progress[0],items[0].work_queue.platform_progress[0]]},{...items[0].work_queue,platform_progress:[{...items[0].work_queue.platform_progress[0],month:'2026-12'}]},{...items[0].work_queue,platform_progress:[{...items[0].work_queue.platform_progress[0],platform:'all'}]}])assert.throws(()=>api.verifiedWorkspaceMerchants(page([{...items[0],work_queue:invalid}])));
});

test('narrow monthly action separates platform from a short next step and preserves exact navigation',()=>{
 for(const platform of ['facebook','instagram','google_business'])for(const run_id of [undefined,72]){
  const action={kind:'monthly',platform,label:run_id?`继续${platform}本月清单`:`准备${platform}本月内容`,...(run_id?{run_id}:{})},opened=[],item={...merchant(1),work_queue:{...baseQueue,next_action:action}};
  const tree=panels.MerchantStatusList({items:[item],isOwner:true,onChoose(){},onAction:(row,value)=>opened.push([row.id,value])});
  const primary=nodes(tree).find(node=>node.props?.className==='mw-queue-primary');assert.ok(primary);assert.equal(primary.props.title,action.label);const copy=nodes(primary).find(node=>node.props?.className==='mw-queue-action-copy');const lines=copy.props.children;assert.equal(label(lines[0]),platform==='google_business'?'Google':api.workspacePlatformLabels[platform]);assert.equal(label(lines[1]),run_id?'继续整月':'准备整月');assert.equal(label(copy).split(api.workspacePlatformLabels[platform]).length<=2,true);primary.props.onClick();assert.equal(opened[0][1],action);
 }
 const css=source('../src/components/media-merchant-workspace.css');assert.match(css,/button\.mw-queue-primary\{display:grid;grid-template-columns:minmax\(0,1fr\) 12px/);assert.match(css,/\.mw-queue-action-copy\{display:grid/);
});
