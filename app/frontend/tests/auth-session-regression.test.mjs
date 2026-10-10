import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';
import { createClient as createRealSdkClient } from '@metagptx/web-sdk';

// These tests execute the actual TypeScript auth modules. Only browser storage,
// React rendering, and the Axios transport adapter are synthetic; no request can
// reach a real account or network. SDK request/response behavior remains real.
const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const employeeA = { id: 101, name: 'Synthetic Sales A', role: 'sales', status: 'active' };
const employeeB = { id: 102, name: 'Synthetic Sales B', role: 'sales', status: 'active' };
const defer = () => {
  let resolvePromise;
  const promise = new Promise(resolve => { resolvePromise = resolve; });
  return { promise, resolve: resolvePromise };
};
const flush = async () => { for (let n = 0; n < 8; n++) await new Promise(resolve => setImmediate(resolve)); };

function storage() {
  const entries = new Map();
  return {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, String(value)),
    removeItem: key => entries.delete(key),
    key: index => [...entries.keys()][index] ?? null,
    get length() { return entries.size; },
  };
}

function fixture(handler, persistedLocalStorage) {
  const listeners = new Map();
  const localStorage = persistedLocalStorage || storage();
  const sessionStorage = storage();
  const window = {
    localStorage, sessionStorage, postMessage() {}, location: { origin: 'http://isolated.invalid', pathname: '/apps' }, name: '',
    addEventListener(type, callback) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(callback); },
    removeEventListener(type, callback) { listeners.get(type)?.delete(callback); },
    dispatchEvent(event) { for (const callback of listeners.get(event.type) || []) callback(event); },
  };
  window.self = window; window.top = window;
  globalThis.window = window;
  globalThis.localStorage = localStorage;
  const requests = [];
  const cache = new Map();
  const state = [];
  const effects = [];
  let hookIndex = 0;
  let didMount = false;
  const react = {
    createContext: value => ({ Provider: 'SyntheticProvider', value }),
    useContext: context => context.value,
    useState(initial) {
      const index = hookIndex++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    },
    useEffect(callback) { if (!didMount) effects.push(callback); },
    useCallback: callback => callback,
  };
  const context = vm.createContext({ window, localStorage, sessionStorage, atob, console, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } }, Event: class { constructor(type) { this.type = type; } }, Date, Math, setTimeout, clearTimeout });
  function load(path) {
    const file = resolve(sourceRoot, `${path}${path.endsWith('role-context') ? '.tsx' : '.ts'}`);
    if (cache.has(file)) return cache.get(file).exports;
    const module = { exports: {} };
    cache.set(file, module);
    const source = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
    const require = specifier => {
      if (specifier === 'react') return react;
      if (specifier === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
      if (specifier === '@metagptx/web-sdk') return {
        createClient: config => createRealSdkClient({ ...config, adapter: async request => {
          const entry = { path: request.url, method: request.method, authorization: request.headers.get('Authorization'), data: request.data };
          requests.push(entry);
          const answer = await handler(entry, requests);
          const response = { data: answer.data, status: answer.status ?? 200, statusText: '', config: request, headers: {} };
          if (response.status >= 400) {
            const error = new Error(`Synthetic HTTP ${response.status}`);
            error.response = response;
            throw error;
          }
          return response;
        } }),
      };
      if (specifier.endsWith('/config') || specifier === './config') return { getAPIBaseURL: () => 'http://isolated.invalid' };
      if (specifier === './sales-workspace-view-state') return { clearSalesWorkspaceViewState() {} };
      if (specifier.startsWith('@/')) return load(specifier.slice(2));
      return load(resolve(dirname(file), specifier));
    };
    vm.runInContext(`(function(require,module,exports){${source}\n})`, context, { filename: file })(require, module, module.exports);
    return module.exports;
  }
  const auth = load('lib/auth-storage');
  const api = load('lib/api');
  const tokens = load('lib/tokenStore');
  const config = load('lib/app-config');
  return {
    auth, api, tokens, config, window, localStorage, sessionStorage, requests, state, load,
    seed(employee = employeeA, token = 'synthetic-A') { tokens.setToken(token, 'session'); auth.storeEmployee(employee, 'session'); },
    mountRole() {
      hookIndex = 0;
      const tree = load('lib/role-context').RoleProvider({ children: null });
      if (!didMount) { didMount = true; for (const effect of effects) effect(); }
      return tree.props.value;
    },
  };
}

for (const cached of [true, false]) {
  test(`verified sales identity survives config 503 (${cached ? 'cached' : 'uncached'} profile)`, async () => {
    const f = fixture(async ({ path }) => path.endsWith('/me') ? { data: employeeA } : { status: 503, data: { detail: 'Synthetic config outage' } });
    f.seed();
    if (!cached) f.auth.clearStoredEmployee();
    f.localStorage.setItem('crm_role_permissions', JSON.stringify({ sales: { sensitiveFields: { viewFinance: true } } }));
    f.mountRole(); await flush();
    assert.equal(f.state[0]?.id, employeeA.id);
    assert.equal(f.state[1], 'sales');
    assert.equal(f.state[2], false);
    assert.equal(f.tokens.getToken(), 'synthetic-A');
    assert.equal(f.config.readCachedAppConfig('role_permissions', null), null);
    assert.equal(f.mountRole().canViewFinance, false);
  });
}

test('authoritative identity rejection fails closed after refresh rejection', async () => {
  const f = fixture(async () => ({ status: 401, data: {} })); f.seed(); f.mountRole(); await flush();
  assert.equal(f.state[0], null); assert.equal(f.state[1], ''); assert.equal(f.state[2], false);
  assert.equal(f.tokens.getToken(), ''); assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
});

test('business 403 does not refresh or invalidate the employee', async () => {
  const f = fixture(async () => ({ status: 403, data: { detail: 'Not permitted' } })); f.seed();
  await assert.rejects(f.api.client.apiCall.invoke({ url: '/api/v1/forbidden', method: 'GET' }), /Synthetic HTTP 403/);
  assert.equal(f.requests.length, 1); assert.equal(f.tokens.getToken(), 'synthetic-A');
});

test('20 concurrent SDK 401 requests share one refresh and each retry exactly once', async () => {
  const pending = defer(); let refreshCount = 0;
  const f = fixture(async ({ path, authorization }) => {
    if (path.endsWith('/refresh')) { refreshCount++; await pending.promise; return { data: { access_token: 'synthetic-rotated-A' } }; }
    return authorization === 'Bearer synthetic-A' ? { status: 401, data: {} } : { data: { employee_id: 101 } };
  }); f.seed();
  const calls = Array.from({ length: 20 }, () => f.api.client.apiCall.invoke({ url: '/api/v1/synthetic-records', method: 'GET' }));
  await flush(); assert.equal(refreshCount, 1); pending.resolve();
  const responses = await Promise.all(calls);
  assert.equal(responses.length, 20); assert.equal(refreshCount, 1);
  assert.equal(f.requests.filter(r => r.path.endsWith('/synthetic-records')).length, 40);
});

test('actual SDK entity methods resolve the new Axios instance on retry', async () => {
  const f = fixture(async ({ path, authorization }) => path.endsWith('/refresh')
    ? { data: { access_token: 'synthetic-new-A' } }
    : authorization === 'Bearer synthetic-A' ? { status: 401, data: {} } : { data: { items: [{ owner: 101 }] } });
  f.seed(); const result = await f.api.client.entities.customers.query({ limit: 5 });
  assert.equal(result.data.items[0].owner, 101);
  assert.equal(f.requests.filter(r => r.path.endsWith('/refresh')).length, 1);
  assert.equal(f.requests.at(-1).authorization, 'Bearer synthetic-new-A');
});

test('late refresh response cannot restore a logged-out token', async () => {
  const pending = defer(); const f = fixture(async () => { await pending.promise; return { data: { access_token: 'synthetic-old-A' } }; }); f.seed();
  const refresh = f.tokens.refreshToken(); await flush(); f.auth.markExplicitLogout(); f.tokens.clearToken(); pending.resolve();
  assert.equal(await refresh, null); assert.equal(f.tokens.getToken(), ''); assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
});

test('late A refresh cannot overwrite a newly logged-in sales B token', async () => {
  const pending = defer(); const f = fixture(async () => { await pending.promise; return { data: { access_token: 'synthetic-old-A' } }; }); f.seed();
  const refresh = f.tokens.refreshToken(); await flush(); f.seed(employeeB, 'synthetic-B'); pending.resolve();
  assert.equal(await refresh, null); assert.equal(f.tokens.getToken(), 'synthetic-B');
  assert.equal(JSON.parse(f.auth.getStoredEmployee()).id, 102);
});

for (const status of [200, 401, 403]) {
  test(`late sales A business response ${status} cannot affect sales B`, async () => {
    const pending = defer(); const f = fixture(async () => { await pending.promise; return { status, data: { owner: 101 } }; }); f.seed();
    const oldRequest = f.api.client.apiCall.invoke({ url: '/api/v1/synthetic-records', method: 'GET' });
    const rejected = assert.rejects(oldRequest, { name: 'AuthSessionChangedError' });
    await flush(); f.seed(employeeB, 'synthetic-B'); pending.resolve(); await rejected;
    assert.equal(f.tokens.getToken(), 'synthetic-B'); assert.equal(f.requests.length, 1);
  });
}

test('late A config does not write A permissions into B cache', async () => {
  const pending = defer(); const f = fixture(async () => { await pending.promise; return { data: { items: { role_permissions: { value: { sales: { sensitiveFields: { viewFinance: true } } } } } } }; }); f.seed();
  const oldConfig = f.config.syncAppConfigCache(); const rejected = assert.rejects(oldConfig, { name: 'AuthSessionChangedError' });
  await flush(); f.seed(employeeB, 'synthetic-B'); f.config.clearCachedAppConfig(); pending.resolve(); await rejected;
  assert.equal(f.config.readCachedAppConfig('role_permissions', null), null);
});

test('late A /me cannot replace current B profile or loading state', async () => {
  const pending = defer(); const f = fixture(async ({ path }) => { if (path.endsWith('/me')) { await pending.promise; return { data: employeeA }; } return { data: { items: {} } }; });
  f.seed(); const role = f.mountRole(); await flush(); await role.login('synthetic-B', employeeB, false); pending.resolve(); await flush();
  assert.equal(f.state[0].id, 102); assert.equal(f.state[1], 'sales'); assert.equal(f.state[2], false);
  assert.equal(JSON.parse(f.auth.getStoredEmployee()).id, 102);
});

test('POST network failure is never repeated', async () => {
  const f = fixture(async () => { throw new Error('Synthetic timeout after server may have accepted write'); }); f.seed();
  await assert.rejects(f.api.client.apiCall.invoke({ url: '/api/v1/synthetic-write', method: 'POST', data: { id: 1 } }), /Synthetic timeout/);
  assert.equal(f.requests.length, 1);
});

test('login 401 never calls refresh with a previous account cookie', async () => {
  const f = fixture(async () => ({ status: 401, data: {} })); f.seed();
  await assert.rejects(f.api.client.apiCall.invoke({ url: '/api/v1/emp-auth/login', method: 'POST', data: { email: 'synthetic@example.invalid', password: 'synthetic-test-only' } }));
  assert.equal(f.requests.length, 1); assert.equal(f.tokens.getToken(), 'synthetic-A');
});

test('legacy token migrates from persistent browser-readable storage', async () => {
  const f = fixture(async () => ({ data: {} })); f.localStorage.setItem('emp_auth_token', 'synthetic-legacy');
  assert.equal(f.tokens.getToken(), 'synthetic-legacy'); assert.equal(f.localStorage.getItem('emp_auth_token'), null);
  assert.equal(f.sessionStorage.getItem('emp_auth_token'), 'synthetic-legacy');
});

test('identity boundary in another tab invalidates this tab token and profile UI', async () => {
  const f = fixture(async ({ path }) => path.endsWith('/me') ? { data: employeeA } : { data: { items: {} } }); f.seed(); f.mountRole(); await flush();
  f.localStorage.setItem(f.auth.AUTH_SESSION_EPOCH_KEY, 'synthetic-other-tab-B');
  f.window.dispatchEvent({ type: 'storage', key: f.auth.AUTH_SESSION_EPOCH_KEY });
  assert.equal(f.state[0], null); assert.equal(f.state[1], ''); assert.equal(f.tokens.getToken(), '');
  const requestCount = f.requests.length;
  await assert.rejects(f.api.client.apiCall.invoke({ url: '/api/v1/synthetic-records', method: 'GET' }), { name: 'AuthSessionChangedError' });
  await assert.rejects(f.api.client.entities.customers.query({ limit: 5 }), { name: 'AuthSessionChangedError' });
  assert.equal(f.requests.length, requestCount);
});

test('unverified and disabled identities never get permissive frontend defaults', async () => {
  const f = fixture(async () => ({ data: {} })); const unverified = f.mountRole();
  assert.equal(unverified.isAdmin, false); assert.equal(unverified.canViewFinance, false); assert.equal(unverified.canAccess('/finance'), false);
  await unverified.login('synthetic-disabled', { ...employeeA, status: 'disabled' }, false);
  const disabled = f.mountRole(); assert.equal(disabled.isLoggedIn, false); assert.equal(disabled.canAccess('/sales-leads'), false);
});


test('logout revokes bearer sid when no refresh cookie was established', async () => {
  const f = fixture(async ({ path }) => path.endsWith('/me') ? { data: employeeA } : { data: { items: {} } }); f.seed(); f.mountRole(); await flush();
  await f.mountRole().logout();
  const request = f.requests.find(r => r.path.endsWith('/logout'));
  assert.equal(request.authorization, 'Bearer synthetic-A');
  assert.equal(f.tokens.getToken(), ''); assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
  assert.equal(f.requests.some(r => r.path.includes('operation_logs')), false);
});

test('readable but write-blocked storage cannot defeat account epoch changes', async () => {
  const pending = defer(); const f = fixture(async () => { await pending.promise; return { data: { access_token: 'synthetic-late-A' } }; }); f.seed();
  const refresh = f.tokens.refreshToken(); await flush();
  const previousEpoch = f.auth.getAuthSessionEpoch();
  f.localStorage.setItem = () => { throw new Error('Synthetic quota'); };
  f.seed(employeeB, 'synthetic-B');
  assert.notEqual(f.auth.getAuthSessionEpoch(), previousEpoch);
  pending.resolve(); assert.equal(await refresh, null); assert.equal(f.tokens.getToken(), 'synthetic-B');
});

test('unremovable previous-account permission cache remains suppressed', async () => {
  const f = fixture(async () => ({ data: {} })); f.seed();
  f.localStorage.setItem('crm_security_config', JSON.stringify({ passwordViewRoles: ['sales'] }));
  f.localStorage.removeItem = () => { throw new Error('Synthetic storage removal blocked'); };
  f.config.clearCachedAppConfig();
  assert.equal(f.config.readCachedAppConfig('security_config', null), null);
});


test('old A and new B refresh serialize cookie requests and keep B promise isolated', async () => {
  const a = defer(); const b = defer(); let calls = 0;
  const f = fixture(async () => { const index = ++calls; await (index === 1 ? a : b).promise; return { data: { access_token: index === 1 ? 'synthetic-stale-A' : 'synthetic-current-B' } }; }); f.seed();
  const oldRefresh = f.tokens.refreshToken(); await flush(); f.seed(employeeB, 'synthetic-B');
  const newRefresh = f.tokens.refreshToken(); const sharedNewRefresh = f.tokens.refreshToken(); await flush();
  assert.equal(calls, 1); a.resolve(); assert.equal(await oldRefresh, null); await flush(); assert.equal(calls, 2);
  b.resolve(); assert.equal(await newRefresh, 'synthetic-current-B'); assert.equal(await sharedNewRefresh, 'synthetic-current-B');
  assert.equal(f.tokens.getToken(), 'synthetic-current-B'); assert.equal(JSON.parse(f.auth.getStoredEmployee()).id, 102);
});

test('superseded queued cookie request is not sent and a failure cannot poison the queue', async () => {
  const first = defer(); let calls = 0;
  const f = fixture(async () => { if (++calls === 1) { await first.promise; return { status: 503, data: {} }; } return { data: {} }; }); f.seed();
  const invoke = () => f.api.client.apiCall.invoke({ url: '/api/v1/emp-auth/set_refresh', method: 'POST', options: { withCredentials: true } });
  const active = invoke(); const activeRejected = assert.rejects(active, /Synthetic HTTP 503/); await flush();
  const obsolete = invoke(); const obsoleteRejected = assert.rejects(obsolete, { name: 'AuthSessionChangedError' });
  f.seed(employeeB, 'synthetic-B'); const current = invoke();
  first.resolve(); await activeRejected; await obsoleteRejected; await current;
  assert.equal(calls, 2); assert.equal(f.tokens.getToken(), 'synthetic-B');
});

test('401 after a successful refresh stops after one retry and invalidates identity', async () => {
  const f = fixture(async ({ path }) => path.endsWith('/refresh') ? { data: { access_token: 'synthetic-rejected-A' } } : { status: 401, data: {} }); f.seed();
  await assert.rejects(f.api.client.apiCall.invoke({ url: '/api/v1/synthetic-records', method: 'GET' }), /Synthetic HTTP 401/);
  assert.equal(f.requests.length, 3); assert.equal(f.tokens.getToken(), ''); assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
});


test('config-specific 403 keeps the verified sales identity with safe defaults', async () => {
  const f = fixture(async ({ path }) => path.endsWith('/me') ? { data: employeeA } : { status: 403, data: {} }); f.seed(); f.mountRole(); await flush();
  assert.equal(f.state[0]?.id, 101); assert.equal(f.tokens.getToken(), 'synthetic-A');
  assert.equal(f.mountRole().canViewFinance, false);
});

test('authoritative /me 403 removes cached identity without an unnecessary refresh', async () => {
  const f = fixture(async () => ({ status: 403, data: {} })); f.seed(); f.mountRole(); await flush();
  assert.equal(f.state[0], null); assert.equal(f.tokens.getToken(), '');
  assert.equal(f.requests.filter(r => r.path.endsWith('/refresh')).length, 0);
});

test('compatibility logout helper clears role context immediately while offline', async () => {
  const f = fixture(async ({ path }) => path.endsWith('/me') ? { data: employeeA } : path.endsWith('/logout') ? Promise.reject(new Error('Synthetic offline')) : { data: { items: {} } }); f.seed(); f.mountRole(); await flush();
  f.load('lib/authClient').logout(); await flush();
  assert.equal(f.state[0], null); assert.equal(f.tokens.getToken(), ''); assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
});

test('transient /me 503 preserves credentials and closes permissions until retry succeeds', async () => {
  let available = false;
  const f = fixture(async ({ path }) => path.endsWith('/me') && !available ? { status: 503, data: {} } : path.endsWith('/me') ? { data: employeeA } : { data: { items: {} } }); f.seed();
  f.mountRole(); await new Promise(resolve => setTimeout(resolve, 350)); await flush();
  assert.equal(f.state[0], null); assert.equal(f.state[1], ''); assert.equal(f.tokens.getToken(), 'synthetic-A');
  assert.equal(f.state[2], false); assert.match(f.state[5], /暂时无法验证/);
  assert.equal(f.mountRole().canAccess('/sales-leads'), false);
  assert.equal(f.requests.filter(r => r.path.endsWith('/me')).length, 2);
  available = true; await f.mountRole().retryAuth();
  assert.equal(f.state[0].id, 101); assert.equal(f.state[5], ''); assert.equal(f.state[2], false);
});

test('transient refresh outage preserves remembered login without trusting cached profile', async () => {
  const f = fixture(async () => ({ status: 503, data: {} }));
  f.localStorage.setItem('emp_auth_remembered', '1'); f.auth.storeEmployee(employeeA, 'persistent'); f.mountRole(); await flush();
  assert.equal(f.state[0], null); assert.equal(f.state[1], ''); assert.equal(f.state[2], false);
  assert.match(f.state[5], /暂时无法验证/); assert.equal(f.localStorage.getItem('emp_auth_remembered'), '1');
  assert.equal(f.auth.wasExplicitlyLoggedOut(), false);
});

test('network failure during /me closes access but does not erase the bearer token', async () => {
  const f = fixture(async () => { throw new Error('Synthetic Network Error'); }); f.seed(); f.mountRole();
  await new Promise(resolve => setTimeout(resolve, 350)); await flush();
  assert.equal(f.tokens.getToken(), 'synthetic-A'); assert.equal(f.state[0], null); assert.equal(f.state[1], '');
  assert.match(f.state[5], /暂时无法验证/); assert.equal(f.requests.length, 2);
});


const syntheticJwt = (emp_id, sid) => `synthetic.${Buffer.from(JSON.stringify({ emp_id, sid })).toString('base64url')}.test-only-signature`;

test('cold refresh cookie for another employee never combines with the cached profile', async () => {
  const f = fixture(async () => ({ data: { access_token: syntheticJwt(102, 'B-session') } }));
  f.auth.storeEmployee(employeeA, 'persistent');
  assert.equal(await f.tokens.refreshToken(), null); assert.equal(f.tokens.getToken(), '');
  assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
});

test('refresh cannot silently switch a known bearer sid', async () => {
  const f = fixture(async () => ({ data: { access_token: syntheticJwt(101, 'A-other-session') } })); f.seed(employeeA, syntheticJwt(101, 'A-session'));
  assert.equal(await f.tokens.refreshToken(), null); assert.equal(f.tokens.getToken(), '');
});

test('normal refresh for the same known employee and sid remains usable', async () => {
  const token = syntheticJwt(101, 'A-session'); const f = fixture(async () => ({ data: { access_token: token } })); f.seed(employeeA, token);
  assert.equal(await f.tokens.refreshToken(), token); assert.equal(f.tokens.getToken(), token);
});

test('late login response cannot apply after a newer B login identity boundary', async () => {
  const pending = defer(); const f = fixture(async () => { await pending.promise; return { data: { token: 'synthetic-A', employee: employeeA } }; });
  const request = f.api.client.apiCall.invoke({ url: '/api/v1/emp-auth/login', method: 'POST', data: { email: 'synthetic@example.invalid', password: 'synthetic' } });
  const rejected = assert.rejects(request, { name: 'AuthSessionChangedError' }); await flush(); f.seed(employeeB, 'synthetic-B'); pending.resolve(); await rejected;
  assert.equal(f.tokens.getToken(), 'synthetic-B');
});

test('login callback rejects after logout while its optional config is pending', async () => {
  const pending = defer(); const f = fixture(async ({ path }) => { if (path === '/api/v1/app-config') await pending.promise; return { data: { items: {} } }; });
  const role = f.mountRole(); await flush();
  const login = role.login('synthetic-A', employeeA, false);
  const rejected = assert.rejects(login, { name: 'AuthSessionChangedError' }); await flush(); await f.mountRole().logout(); pending.resolve(); await rejected;
  assert.equal(f.tokens.getToken(), ''); assert.equal(f.state[0], null);
});


test('mixed cold cookie rejection survives reload until explicit login', async () => {
  const handler = async () => ({ data: { access_token: syntheticJwt(101, 'A-session') } });
  const f = fixture(handler); f.auth.storeEmployee(employeeB, 'persistent');
  f.config.writeCachedAppConfig('security_config', { passwordViewRoles: ['sales'] });
  assert.equal(await f.tokens.refreshToken(), null); assert.equal(f.auth.wasExplicitlyLoggedOut(), true);
  assert.equal(f.auth.getStoredEmployee(), ''); assert.equal(f.config.readCachedAppConfig('security_config', null), null);
  const reloaded = fixture(handler, f.localStorage);
  assert.equal(await reloaded.tokens.refreshToken(), null); assert.equal(reloaded.requests.length, 0);
  assert.equal(reloaded.auth.wasExplicitlyLoggedOut(), true); assert.equal(reloaded.tokens.getToken(), '');
  reloaded.seed(employeeB, 'synthetic-explicit-B'); assert.equal(reloaded.auth.wasExplicitlyLoggedOut(), false);
});
