import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import { spawnSync } from 'node:child_process';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const backend = resolve(root, '../../backend');
function validateApiPayload(request) {
  const model = request.url.endsWith('/agreements') ? 'AgreementInput' : /\/attributions(?:\/preview)?$/.test(request.url) ? 'AttributionInput' : null;
  if (request.method !== 'POST' || !model) return;
  // Import the actual backend Pydantic model, including extra=forbid and validators.
  // Isolated test configuration prevents a real database or network dependency.
  const result = spawnSync(process.env.T24_TEST_PYTHON || 'python3', ['-c', `import json,sys
from routers.commissions import AgreementInput, AttributionInput
model={'AgreementInput':AgreementInput,'AttributionInput':AttributionInput}[sys.argv[1]]
model.model_validate(json.load(sys.stdin))
print('validated')`, model], {
    cwd: backend, input: JSON.stringify(request.data), encoding: 'utf8',
    env: {...process.env, APP_ENV: 'test', DATABASE_URL: 'sqlite+aiosqlite:///:memory:', PYTHONPATH: '.:..'},
  });
  assert.equal(result.status, 0, `Actual ${model} rejected frontend payload. Set T24_TEST_PYTHON to the backend test interpreter.\n${result.stderr || result.error || ''}`);
}

const jsx = (type, props) => ({ type, props });
const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)); };

// Execute the real components with controlled hooks and synthetic API replies.
// Browser/UI libraries are replaced with element nodes; no transport or credentials exist.
function fixture(page, handler, mobile = false, routeParams = {}) {
  const state = [], effects = [], cache = new Map(), requests = [], notices = [];
  let cursor = 0, autoRefresh, tree;
  const react = {
    useState(initial) { const i = cursor++; if (!state[i]) state[i] = { value: typeof initial === 'function' ? initial() : initial }; return [state[i].value, value => { state[i].value = typeof value === 'function' ? value(state[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; if (!state[i]) state[i] = { value: { current: initial } }; return state[i].value; },
    useMemo(factory, deps) { const i = cursor++; if (!state[i] || !same(state[i].deps, deps)) state[i] = { value: factory(), deps }; return state[i].value; },
    useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!state[i] || !same(state[i].deps, deps)) { state[i] = { deps }; effects.push(fn); } },
  };
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative);
    const module = { exports: {} };
    const compiled = ts.transpileModule(readFileSync(resolve(root, relative), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const require = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
      if (name.endsWith('.css')) return {};
      if (name === '@/lib/commission-presentation') return load('lib/commission-presentation.ts');
      if (name === '@/lib/tokenStore') return { invokeWithAuth: async request => { requests.push(request); validateApiPayload(request); return { data: await handler(request) }; } };
      if (name === '@/hooks/use-mobile') return { useIsMobile: () => mobile };
      if (name === '@/lib/use-auto-refresh') return { useAutoRefresh: callback => { autoRefresh = callback; } };
      if (name === '@/lib/use-unsaved-changes') return { useUnsavedChanges: () => ({ confirmDiscard: () => true }) };
      if (name === '@/lib/load-utils') return { getLoadErrorMessage: error => error.message };
      if (name === 'react-router-dom') return { useNavigate: () => () => {}, useSearchParams: () => [new URLSearchParams(routeParams)], Link: 'Link' };
      if (name.endsWith('lib/role-context')) return { useRole: () => ({ isAdmin: true, employee: {id:1,name:'合成管理员'}, hasPermission: () => true }), roleLabels:{sales_partner:'销售合伙人'},empStatusLabels:{active:'在职'},empStatusColors:{},departmentLabels:{sales:'销售'},positionLabels:{specialist:'专员'} };
      if (name.endsWith('lib/permissions')) return {systemRoleLabels:{sales_partner:'销售合伙人',sales:'销售'}};
      if (name.endsWith('lib/dict-config')) return {useBusinessDicts: () => ({statuses:{},taskStatuses:{}})};
      if (name.endsWith('lib/use-dialog-draft')) return {useDialogDraft: () => ({confirmDiscard:()=>true,markSaved:()=>{}})};
      if (name.endsWith('lib/phone-format')) return {parsePhoneNumber:()=>({isValid:true}),formatPhoneNumber:value=>value,parsePhoneNumberForDisplay:()=>({isValid:true}),phoneSearchMatches:()=>false};
      if (name === '../lib/api') return {client:{entities:{employees:{queryAll:async()=>({data:{items:[]}}),create:async args=>{const request={url:'/api/v1/entities/employees',method:'POST',data:args.data};requests.push(request);return {data:await handler(request)};}}}}};
      if (name === '../lib/tokenStore') return {invokeWithAuth:async request=>{requests.push(request);return {data:await handler(request)};}};
      if (name.endsWith('lib/use-auto-refresh')) return {useAutoRefresh: callback=>{autoRefresh=callback;}};
      if (name.endsWith('lib/operation-log-helper')) return {actionTypeLabels:{},logOperation:()=>{}};
      if (name === 'sonner') return { toast: { success: text => notices.push(text), error: text => notices.push(text) } };
      return new Proxy({ default: name }, { get: (target, property) => target[property] || String(property) });
    };
    vm.runInNewContext(`(function(require,module,exports){${compiled}\n})`, { Intl, Date, console, URL, URLSearchParams, Blob })(require, module, module.exports);
    cache.set(relative, module.exports);
    return module.exports;
  }
  const Component = load(`pages/${page}.tsx`).default;
  const render = () => { cursor = 0; tree = Component(); while (effects.length) effects.shift()(); return tree; };
  const settle = async () => { await flush(); render(); await flush(); render(); };
  const walk = (node, predicate) => {
    if (!node) return [];
    if (Array.isArray(node)) return node.flatMap(child => walk(child, predicate));
    if (typeof node !== 'object') return [];
    return [...(predicate(node) ? [node] : []), ...walk(node.props?.children, predicate)];
  };
  const all = predicate => walk(tree, predicate);
  const text = node => node == null || typeof node === 'boolean' ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join(' ') : text(node.props?.children);
  return { render, settle, all, text, requests, notices, modules: load, auto: () => autoRefresh?.(), tree: () => tree,
    byLabel: label => all(node => node.props?.['aria-label'] === label)[0],
    button: label => all(node => node.type === 'Button' && text(node).trim() === label)[0],
  };
}
const entry = (id, overrides = {}) => ({ id, partner_id: 1, partner_name: '同名代理', customer_id: 1, customer_name: '合成客户', payment_id: id, entry_type: 'renewal', status: 'confirmed', service_month: '2026-10', occurred_at: '2026-10-05', currency: 'USD', gross_receipt_amount: 100, eligible_service_amount: 100, contract_rate: .2, activity_multiplier: 1, inactivity_months: 0, commission_amount: 20, ...overrides });
const portal = (mode = 'partner') => ({ portal_mode: mode, available_partners: mode === 'owner_readonly' ? [{id:1,name:'渠道A',partner_code:'A',status:'active'}, {id:2,name:'渠道B',partner_code:'B',status:'active'}] : [], partner:{id:1,name:'渠道A',partner_code:'A',status:'active',joined_at:'2026-01-01'}, summary:{active_customer_count:1,cooperation_customer_count:1,renewal_attention_count:0,stopped_customer_count:0,ledger_count:2,currencies:{USD:{pending:0,confirmed:120,payable:0,paid:0}},status_updated_at:'2026-10-01'}, agreements:[],customers:[],entries:[entry(1),entry(2,{service_month:'2026-09',commission_amount:100})] });

for (const mode of ['partner', 'owner_readonly']) test(`${mode}: manual and automatic refresh preserve server scope`, async () => {
  const app = fixture('PartnerPortal', () => portal(mode)); app.render(); await app.settle();
  assert.equal(app.requests[0].data, undefined);
  await app.button('刷新').props.onClick(); await app.settle();
  await app.auto(); await app.settle();
  for (const request of app.requests.slice(1)) assert.equal(JSON.stringify(request.data), mode === 'partner' ? undefined : '{"partner_id":1}');
});

test('portal summary and ledger use the selected month rather than all-time totals', async () => {
  const app = fixture('PartnerPortal', () => portal()); app.render(); await app.settle();
  app.byLabel('分润明细月份').props.onChange({target:{value:'2026-10'}}); app.render();
  const summary = app.text(app.byLabel('期间分润摘要'));
  assert.match(summary, /2026-10/); assert.match(summary, /USD 20.00/); assert.doesNotMatch(summary, /120.00|100.00/);
  assert.doesNotMatch(app.text(app.tree()), /2026-09 · 合成客户/);
});

test('same-name partners remain separate; refunds are not double-counted as paid expense', () => {
  const app = fixture('PartnerPortal', () => portal());
  const {groupCommissionSettlements, summarizeCommissionEntries} = app.modules('lib/commission-presentation.ts');
  const rows = [entry(1), entry(2,{partner_id:2,commission_amount:70}), entry(3,{entry_type:'refund_reversal',commission_amount:-5,status:'paid'}),entry(4,{status:'reversed',commission_amount:999})];
  const grouped = groupCommissionSettlements(rows);
  assert.equal(grouped.length,2); assert.equal(grouped[0].confirmed,15); assert.equal(grouped[1].confirmed,70);
  const summary = summarizeCommissionEntries(rows).USD;
  assert.equal(summary.confirmed,85); assert.equal(summary.paid,-5); assert.equal(summary.adjustments,-5); assert.equal(summary.entry_count,3);
  assert.equal(groupCommissionSettlements([entry(5,{partner_id:undefined}),entry(6,{partner_id:undefined})]).length,2);
});

function commissionResponse(request) {
  if (request.url.includes('/dashboard')) return {summary:{partner_count:1,active_partner_count:1,pending_count:0,currencies:{},quality:{issue_count:0}},partners:[{id:1,partner_code:'A',name:'合成代理',partner_type:'agency',status:'active',joined_at:'2026-01-01'}],agreements:[],attributions:[],entries:[],quality_issues:[]};
  if (request.url.includes('/partner-login-options')) return {items:[]};
  if (request.url.endsWith('/options')) return {employees:[],customers:[{id:1,name:'合成客户'}],business_lines:[],products:[],engagements:[]};
  if (request.url.endsWith('/preview')) return {blocked:false,conflicts:[],affected_pending_count:1,legacy_count:1,message:'预览成功'};
  return {};
}
test('new protocol uses fixed renewal and never submits legacy decay settings', async () => {
  const app = fixture('Commissions', commissionResponse); app.render(); await app.settle();
  const menu = app.all(node => node.type === 'DropdownMenuItem' && app.text(node) === '新增协议版本')[0]; menu.props.onSelect(); app.render();
  const dialog = app.all(node => node.type === 'Dialog' && node.props.open)[0];
  const selects = [];
  const visit = node => { if(Array.isArray(node)) return node.forEach(visit); if(!node || typeof node !== 'object') return; if(node.type === 'NativeSelect') selects.push(node); visit(node.props?.children); }; visit(dialog);
  selects[0].props.onChange('1'); app.render();
  await app.button('保存协议版本').props.onClick(); await app.settle();
  const request = app.requests.find(request => request.url.endsWith('/agreements'));
  assert.equal(request.data.renewal_policy,'fixed'); assert.equal(Object.hasOwn(request.data, 'calculation_version'),false); assert.equal(request.data.activity_decay[6],1);
  assert.equal(request.data.first_order_rate,.5); assert.equal(request.data.renewal_rate,.2);
});

test('renewal-only requires history, previews before save, and invalidates preview after editing', async () => {
  const app = fixture('Commissions', commissionResponse); app.render(); await app.settle();
  app.all(node => node.type === 'DropdownMenuItem' && app.text(node) === '设置客户归属')[0].props.onSelect(); app.render();
  app.byLabel('归属客户').props.onChange('1'); app.byLabel('归属渠道').props.onChange('1'); app.render();
  app.byLabel('客户计佣方式').props.onChange('renewal_only'); app.render();
  app.byLabel('客户实际服务起始日').props.onChange({target:{value:'2026-01-01'}}); app.render();
  assert.equal(app.button('预览影响').props.disabled,true);
  app.byLabel('历史首期依据').props.onChange({target:{value:'首期历史凭证 SYNTH-1'}}); app.render();
  assert.equal(app.button('预览影响').props.disabled,false);
  assert.equal(app.button('确认保存归属').props.disabled,true);
  await app.button('预览影响').props.onClick(); await app.settle();
  assert.equal(app.button('确认保存归属').props.disabled,false);
  app.byLabel('历史首期依据').props.onChange({target:{value:'首期历史凭证 SYNTH-2'}}); app.render();
  assert.equal(app.button('确认保存归属').props.disabled,true);
  await app.button('预览影响').props.onClick(); await app.settle();
  await app.button('确认保存归属').props.onClick(); await app.settle();
  const request=app.requests.find(row=>row.url.endsWith('/attributions'));
  assert.equal(request.data.commission_mode,'renewal_only'); assert.equal(request.data.history_basis,'首期历史凭证 SYNTH-2'); assert.equal(request.data.first_service_start,'2026-01-01');
  assert.ok(request.data.commission_start_date);
});

test('locked-ledger conflict cannot submit through the attribution dialog', async () => {
  const app=fixture('Commissions',request=>request.url.endsWith('/preview')?{blocked:true,conflicts:[{entry_id:7,status:'confirmed'}],affected_pending_count:0,legacy_count:1,message:'影响已确认佣金'}:commissionResponse(request)); app.render(); await app.settle();
  app.all(node=>node.type==='DropdownMenuItem'&&app.text(node)==='设置客户归属')[0].props.onSelect(); app.render();
  app.byLabel('归属客户').props.onChange('1');app.byLabel('归属渠道').props.onChange('1');app.render();
  app.byLabel('客户计佣方式').props.onChange('none');app.render();
  await app.button('预览影响').props.onClick();await app.settle();
  assert.equal(app.button('确认保存归属').props.disabled,true);
  await app.button('确认保存归属').props.onClick(); await app.settle();
  assert.equal(app.requests.some(row=>row.url.endsWith('/attributions')),false);
});

test('explicit existing-channel account creation keeps the selected profile ID', async () => {
  const app=fixture('Employees',request=>request.url.endsWith('/unbound-partners')?{items:[{id:42,partner_code:'AGENCY-42',name:'已有代理',partner_type:'agency',contact_email:'synthetic@example.test'}]}:request.url==='/api/v1/entities/employees'?{id:901}:{},false, {create_partner_account:'42'});
  app.render();await app.settle();
  assert.equal(app.byLabel('新账号绑定渠道').props.value,'42');
  await app.button('保存').props.onClick();await app.settle();
  const request=app.requests.find(row=>row.url==='/api/v1/entities/employees');
  assert.equal(request.data.existing_partner_id,42);assert.equal(request.data.role,'sales_partner');
  assert.equal(app.requests.filter(row=>row.url==='/api/v1/entities/employees').length,1);
});

test('invalid explicit channel does not fall back to creating an unrelated profile', async () => {
  const app=fixture('Employees',()=>({items:[]}),false,{create_partner_account:'999'});app.render();await app.settle();
  assert.equal(app.all(node=>node.type==='Dialog'&&node.props.open).length,0);
  assert.match(app.notices.join(' '),/此渠道不存在/);
  assert.equal(app.requests.some(row=>row.method==='POST'),false);
});


test('historical renewal can preview without knowing the original first-service date', async () => {
  const app=fixture('Commissions',commissionResponse);app.render();await app.settle();
  app.all(node=>node.type==='DropdownMenuItem'&&app.text(node)==='设置客户归属')[0].props.onSelect();app.render();
  app.byLabel('归属客户').props.onChange('1');app.byLabel('归属渠道').props.onChange('1');app.render();
  app.byLabel('客户计佣方式').props.onChange('renewal_only');app.render();
  app.byLabel('历史首期依据').props.onChange({target:{value:'首期已系统外结清，原始日期未知；从本日仅续费'}});app.render();
  assert.equal(app.button('预览影响').props.disabled,false);
  await app.button('预览影响').props.onClick();await app.settle();
  const request=app.requests.find(row=>row.url.endsWith('/attributions/preview'));
  assert.equal(request.data.first_service_start,null);assert.equal(request.data.commission_mode,'renewal_only');
});
