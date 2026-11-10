import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { test } from 'node:test';
import vm from 'node:vm';
const requireNative = createRequire(new URL('../package.json', import.meta.url));
const ts = requireNative('typescript');
const src = new URL('../src/', import.meta.url).pathname;
const flush = async () => { for (let n = 0; n < 4; n++) await new Promise(done => setImmediate(done)); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
const card = (scope = 'beautyos', overrides = {}) => ({ id: scope === 'beautyos' ? 1 : 2, product_scope: scope, title: scope === 'beautyos' ? '合成美业口径' : '合成通用口径', category: '首拨核验', standard_answer: '已核对的完整答复', phone_answer: '独立电话短版', status: 'published', revision: 2, is_sensitive: false, action_steps: [], related_links: [], tags: [], sort_order: 1, ...overrides });
const response = items => ({ data: { items, categories: ['首拨核验'] } });

function fixture(handler, { component = 'pages/SalesKnowledge.tsx', props = {}, mobile = false } = {}) {
  const slots = [], effects = [], timers = new Map(), requests = [], copied = [], cache = new Map();
  let cursor = 0, tree, timerId = 0, actor = { employee: { id: 10 }, role: 'sales_manager', isAdmin: false }, currentProps = props;
  const storage = new Map();
  const react = {
    useState(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: typeof initial === 'function' ? initial() : initial }; return [slots[i].value, value => { slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: { current: initial } }; return slots[i].value; },
    useMemo(fn) { cursor++; return fn(); },
    useEffect(callback, deps) { const i = cursor++, old = slots[i]; if (old && deps && deps.every((value, n) => Object.is(value, old.deps?.[n]))) return; slots[i] = { deps }; effects.push(() => { old?.cleanup?.(); slots[i].cleanup = callback(); }); },
  };
  const window = { setTimeout: fn => { timers.set(++timerId, fn); return timerId; }, clearTimeout: id => timers.delete(id), confirm: () => true };
  function require(name) {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' };
    if (name === 'react-router-dom') return { useNavigate: () => () => {} };
    if (name === '@/lib/role-context') return { useRole: () => actor };
    if (name === '@/hooks/use-mobile') return { useIsMobile: () => mobile };
    if (name === '@/lib/tokenStore') return { invokeWithAuth: request => { requests.push(request); return handler(request, actor); } };
    if (name === '@/lib/use-unsaved-changes') return { useUnsavedChanges: () => ({ confirmDiscard: () => true, markSaved() {} }) };
    if (name === '@/lib/sales-knowledge') return load(resolve(src, 'lib/sales-knowledge.ts'));
    if (name === 'sonner') return { toast: { success() {}, error() {} } };
    if (name === '@/components/ui/input') return { Input: 'input' };
    if (name === '@/components/ui/textarea') return { Textarea: 'textarea' };
    if (name === '@/components/ui/native-select') return { NativeSelect: 'select' };
    if (name === '@/components/ui/button') return { Button: 'button' };
    return new Proxy({}, { get: (_target, key) => String(key) });
  }
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const module = { exports: {} };
    const code = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(`(function(require,module,exports){${code}\n})`, { window, URLSearchParams, navigator: { clipboard: { writeText: async value => copied.push(value) } }, sessionStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) }, console })(require, module, module.exports);
    cache.set(file, module.exports); return module.exports;
  }
  const Component = load(resolve(src, component)).default;
  const runEffects = () => { while (effects.length) effects.shift()(); };
  const render = ({ effects: run = true, account, nextProps } = {}) => { if (account) actor = { ...actor, employee: { id: account } }; if (nextProps) currentProps = nextProps; cursor = 0; tree = Component(currentProps); if (run) runEffects(); return tree; };
  const find = predicate => nodes(tree).find(predicate);
  return { requests, copied, render, runEffects, content: () => text(tree), find,
    button(label) { const button = find(n => n.type === 'button' && text(n) === label); assert.ok(button, label); return button; },
    select(label, value) { const select = find(n => n.type === 'select' && n.props['aria-label'] === label); assert.ok(select, label); select.props.onChange(value); render(); },
    timers() { for (const [id, fn] of [...timers]) { timers.delete(id); fn(); } },
    async settle() { await flush(); render(); await flush(); render(); },
    byId(id) { const value = find(n => n.props?.id === id); assert.ok(value, id); return value; },
  };
}
function handlerFor(list, update) {
  return request => {
    if (request.method === 'PUT') return update(request);
    if (request.url.startsWith('/api/v1/sales-knowledge/articles')) return list(new URL('http://local' + request.url).searchParams, request);
    return Promise.resolve({ data: { items: [] } });
  };
}

test('switching product hides old results immediately and rejects a late old response', async () => {
  const old = deferred();
  const app = fixture(handlerFor(query => query.get('product_scope') === 'beautyos' ? old.promise : Promise.resolve(response([card('general')]))));
  app.render(); app.timers();
  app.select('筛选适用产品', 'general'); app.timers(); await app.settle();
  assert.match(app.content(), /合成通用口径/);
  old.resolve(response([card()])); await app.settle();
  assert.match(app.content(), /合成通用口径/); assert.doesNotMatch(app.content(), /合成美业口径/);
  assert.ok(app.requests.every(request => !request.url.includes('articles?') || request.url.includes('include_general=false')));
});

test('render-to-effect gap rejects old-account knowledge before the next request dispatches', async () => {
  const old = deferred(); let calls = 0;
  const app = fixture(handlerFor(() => ++calls === 1 ? old.promise : Promise.resolve(response([card('beautyos', { title: '新账号已核对口径' })]))));
  app.render(); app.timers();
  app.render({ effects: false, account: 11 });
  old.resolve(response([card('beautyos', { title: '旧账号不能回写的口径' })])); await flush();
  app.render({ effects: false }); assert.doesNotMatch(app.content(), /旧账号不能回写/);
  app.runEffects(); app.timers(); await app.settle(); assert.match(app.content(), /新账号已核对口径/);
});

test('409 edit preserves entered public and internal text and sends the reviewed revision', async () => {
  const app = fixture(handlerFor(() => Promise.resolve(response([card()])), () => Promise.reject({ response: { status: 409, data: { detail: 'revision conflict' } } })));
  app.render(); app.timers(); await app.settle();
  const detail = app.find(n => n.type?.name === 'KnowledgeArticleDetail'); assert.ok(detail); detail.props.onEdit(detail.props.article); app.render();
  app.byId('knowledge-standard-answer').props.onChange({ target: { value: '当前尚未保存的对外修改' } }); app.render();
  app.byId('knowledge-internal').props.onChange({ target: { value: '当前内部备注不可丢失' } }); app.render();
  app.button('保存知识卡').props.onClick(); await app.settle();
  assert.equal(app.byId('knowledge-standard-answer').props.value, '当前尚未保存的对外修改');
  assert.equal(app.byId('knowledge-internal').props.value, '当前内部备注不可丢失');
  assert.match(app.content(), /内容已被其他人更新，当前输入已保留/);
  const update = app.requests.find(request => request.method === 'PUT'); assert.equal(update.data.expected_revision, 2);
  assert.equal(app.requests.filter(request => request.url.endsWith('/publish')).length, 0);
});

test('call assistant uses explicit BeautyOS scope and rejects unrelated guidance returned by a source', async () => {
  const app = fixture(handlerFor(() => Promise.resolve(response([card(), card('managed_service', { title: '不应出现的代运营卡' })]))), { component: 'components/SalesKnowledgeAssistant.tsx', props: { contextCategory: '首拨核验', productScope: 'beautyos' } });
  app.render(); app.timers(); await app.settle();
  assert.match(app.content(), /合成美业口径/); assert.doesNotMatch(app.content(), /不应出现的代运营卡/);
  const read = app.requests[0]; assert.match(read.url, /product_scope=beautyos/); assert.match(read.url, /include_general=false/);
  app.button('复制短版').props.onClick(); await app.settle(); assert.equal(app.copied[0], '独立电话短版');
  app.button('复制完整答复').props.onClick(); await app.settle(); assert.equal(app.copied[1], '已核对的完整答复');
});
