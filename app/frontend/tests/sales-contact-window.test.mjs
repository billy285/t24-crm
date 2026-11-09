import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the actual hook, refresh-event module and refresh subscription logic.
// Only React's state/effect lifecycle and the read-only API transport are synthetic.
const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const flush = async () => { for (let n = 0; n < 6; n++) await new Promise(resolve => setImmediate(resolve)); };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const insight = timezone => ({ profile: { timezone: false }, contact_timezone: { timezone, timezone_group: 'pacific', timezone_basis: 'address_city', timezone_needs_confirmation: true }, config: { default_contact_start: 9, default_contact_end: 18 } });

function fixture(handler) {
  const state = [], refs = [], effects = [], pending = [], intervals = new Map(), requests = [], cache = new Map();
  let cursor = 0, intervalId = 0;
  const window = Object.assign(new EventTarget(), {
    setInterval(callback) { intervals.set(++intervalId, callback); return intervalId; },
    clearInterval(id) { intervals.delete(id); },
    setTimeout() { throw new Error('Mount refresh is not requested'); }, clearTimeout() {},
  });
  const document = Object.assign(new EventTarget(), { visibilityState: 'visible' });
  class CustomEvent extends Event { constructor(type, options) { super(type); this.detail = options?.detail; } }
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    },
    useRef(initial) { const index = cursor++; return refs[index] ||= { current: initial }; },
    useEffect(callback, deps) {
      const index = cursor++, previous = effects[index];
      if (previous && deps.length === previous.deps.length && deps.every((value, n) => Object.is(value, previous.deps[n]))) return;
      pending.push(() => { previous?.cleanup?.(); effects[index] = { deps, cleanup: callback() }; });
    },
  };
  const files = {
    '@/lib/contact-timezone': 'lib/contact-timezone.ts',
    '@/lib/use-auto-refresh': 'lib/use-auto-refresh.ts',
    './data-refresh': 'lib/data-refresh.ts',
    '@/lib/data-refresh': 'lib/data-refresh.ts',
  };
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {}; cache.set(file, exports);
    const compiled = ts.transpileModule(readFileSync(resolve(sourceRoot, file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const require = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx() {}, jsxs() {} };
      if (name === '@/lib/sales-intelligence') return { salesApi(path, ...args) { requests.push({ path, args }); return Promise.resolve(handler(path)); } };
      if (files[name]) return load(files[name]);
      throw new Error(`Unexpected dependency ${name}`);
    };
    vm.runInNewContext(compiled, { exports, require, window, document, CustomEvent, Date, Intl, console }, { filename: file });
    return exports;
  }
  const hooks = load('components/SalesLocalTime.tsx');
  const refresh = load('lib/data-refresh.ts');
  return {
    render(leadId) { cursor = 0; hooks.useSalesContactWindow(leadId); while (pending.length) pending.shift()(); },
    get context() { return JSON.parse(JSON.stringify(state[0])); },
    refresh() { refresh.requestBusinessDataRefresh('manual'); },
    tick() { for (const run of intervals.values()) run(); },
    focus() { window.dispatchEvent(new Event('focus')); },
    unmount() { effects.forEach(effect => effect?.cleanup?.()); },
    requests, intervals,
  };
}

test('same lead refreshes from the existing business event, visible poll and focus without writes', async () => {
  let latest = insight('America/New_York');
  const app = fixture(() => latest);
  app.render(501); await flush();
  assert.equal(app.context.timezone, 'America/New_York');
  latest = insight('America/Los_Angeles'); app.refresh(); await flush();
  assert.equal(app.context.timezone, 'America/Los_Angeles');
  assert.equal(app.context.timezone_basis, 'address_city');
  latest = insight('America/Phoenix'); app.tick(); await flush();
  assert.equal(app.context.timezone, 'America/Phoenix');
  latest = insight('America/Chicago'); app.focus(); await flush();
  assert.equal(app.context.timezone, 'America/Chicago');
  assert.equal(app.requests.length, 4);
  assert.ok(app.requests.every(request => request.path === '/leads/501' && request.args.length === 0));
  app.unmount(); assert.equal(app.intervals.size, 0);
  app.refresh(); app.focus(); await flush();
  assert.equal(app.requests.length, 4);
});

test('old responses cannot overwrite a newer refresh, changed lead or unmounted hook', async () => {
  const initial = deferred(), switched = deferred(); let count = 0;
  const app = fixture(path => {
    if (path === '/leads/501' && count++ === 0) return initial.promise;
    if (path === '/leads/502') return switched.promise;
    return insight('America/Los_Angeles');
  });
  app.render(501); app.refresh(); await flush();
  assert.equal(app.context.timezone, 'America/Los_Angeles');
  initial.resolve(insight('America/New_York')); await flush();
  assert.equal(app.context.timezone, 'America/Los_Angeles');
  app.render(502); assert.equal(app.context.timezone, undefined);
  app.render(503); await flush();
  assert.equal(app.context.timezone, 'America/Los_Angeles');
  switched.resolve(insight('America/Chicago')); await flush();
  assert.equal(app.context.timezone, 'America/Los_Angeles');
  app.unmount();
  const pending = deferred(), unmounted = fixture(() => pending.promise);
  unmounted.render(504); unmounted.unmount();
  pending.resolve(insight('America/New_York')); await flush();
  assert.deepEqual(unmounted.context, {});
});
