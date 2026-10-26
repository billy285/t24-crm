import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, ChevronRight, ExternalLink, LockKeyhole } from 'lucide-react';
import { Button } from '@/components/ui/button';
import CustomerCombobox from '@/components/CustomerCombobox';
import SalesDealPaymentLink from '@/components/SalesDealPaymentLink';
import { invokeWithAuth } from '@/lib/tokenStore';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { businessDateKey } from '@/lib/business-date';
import { useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { dealHandoffApi, salesCollectionMethods, salesDealCycles, salesDealPeriodEnd, salesDealPlatforms, salesHandoffError, salesHandoffHistoryUrl, salesHandoffMoney, salesPaymentCadence, type SalesDealCatalog, type SalesDealHandoff, type SalesDealLeadState } from '@/lib/sales-deal-handoff';
import './sales-deal-handoff.css';

type Props = { leadId: number | null; onClose: () => void; onRegistered?: (handoff: SalesDealHandoff) => void | Promise<void>; onOpenDossier?: (leadId: number) => void };
const newForm = () => ({ plan_id: '', selected_platforms: [] as string[], service_start_date: businessDateKey(), service_end_date: '', collection_method: 'check', operations_owner_employee_id: '', customer_goal: '', handoff_notes: '', special_commitments: '', confirmation_notes: '', existing_customer_id: '' });
const quoteStatuses: Record<string, string> = { approved: '历史已批准', submitted: '历史待审批', rejected: '历史已驳回', superseded: '历史已失效' };

export default function SalesDealHandoffDialog({ leadId, onClose, onRegistered, onOpenDossier }: Props) {
  const navigate = useNavigate();
  const [state, setState] = useState<SalesDealLeadState | null>(null);
  const [catalog, setCatalog] = useState<SalesDealCatalog | null>(null);
  const [form, setForm] = useState(newForm);
  const baseline = useRef('');
  const [step, setStep] = useState(0);
  const [existingMode, setExistingMode] = useState(false);
  const [existingCustomers, setExistingCustomers] = useState<{ id: number; business_name?: string; customer_code?: string }[]>([]);
  const [existingCustomersError, setExistingCustomersError] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [catalogError, setCatalogError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [receipt, setReceipt] = useState<SalesDealHandoff | null>(null);
  const sequence = useRef(0);
  const activeLead = useRef(leadId);
  activeLead.current = leadId;
  const submitLock = useRef(false);
  const submission = useRef<{ signature: string; key: string } | null>(null);
  const dirty = Boolean(leadId && state && !receipt && JSON.stringify(form) !== baseline.current);
  const draft = useUnsavedChanges(dirty);
  const transaction = useHardNavigationBlock(saving);
  const selectedPlan = catalog?.plans.find(plan => String(plan.id) === form.plan_id);
  const groupedPlans = useMemo(() => (catalog?.plans || []).map(plan => {
    const product = catalog?.products.find(item => item.id === plan.product_id);
    return { value: String(plan.id), label: [product?.name, plan.name, salesDealCycles[plan.default_billing_cycle] || plan.default_billing_cycle, salesHandoffMoney(plan.standard_price, plan.default_currency)].filter(Boolean).join(' · ') };
  }), [catalog]);
  const ready = Boolean(state?.lead?.id === leadId);
  const editable = ready && state?.can_register === true && !state.registered && !receipt;

  const readState = async (initialize: boolean) => {
    if (!leadId) return;
    const id = leadId;
    const request = ++sequence.current;
    setLoading(true); setError('');
    try {
      const next = await dealHandoffApi<SalesDealLeadState>(`/leads/${id}`);
      if (sequence.current !== request || activeLead.current !== id) return;
      if (next.lead?.id !== id) throw new Error('商家资料与当前登记对象不一致，请重新读取。');
      setState(next);
      if (next.registered && next.handoff) {
        setReceipt(next.handoff); draft.markSaved();
      } else if (initialize) {
        const initial = { ...newForm(), customer_goal: next.customer_goal || '' };
        baseline.current = JSON.stringify(initial); setForm(initial);
      }
    } catch (problem) {
      if (sequence.current === request && activeLead.current === id) setError(salesHandoffError(problem, '成交资料读取失败，请重试。'));
    } finally { if (sequence.current === request && activeLead.current === id) setLoading(false); }
  };
  const readCatalog = async () => {
    const id = leadId;
    setCatalogError('');
    try {
      const next = await dealHandoffApi<SalesDealCatalog>('/catalog');
      if (activeLead.current !== id) return;
      if (![next.business_lines, next.products, next.plans].every(Array.isArray)) throw new Error('统一套餐目录不完整。');
      setCatalog(next); setConfirmed(false);
      setForm(current => {
        const plan = next.plans.find(item => String(item.id) === current.plan_id);
        if (!plan) return current;
        return { ...current, collection_method: plan.required_collection_method === 'stripe_auto' ? 'stripe_auto' : current.collection_method === 'stripe_auto' ? 'check' : current.collection_method, service_end_date: plan.default_billing_cycle === 'one_time' ? current.service_end_date : salesDealPeriodEnd(current.service_start_date, plan) };
      });
    } catch (problem) { if (activeLead.current === id) setCatalogError(salesHandoffError(problem, '统一套餐读取失败。')); }
  };
  useEffect(() => {
    setState(null); setCatalog(null); setReceipt(null); setError(''); setCatalogError(''); setStep(0); setConfirmed(false);
    setForm(newForm()); baseline.current = ''; submission.current = null; setExistingMode(false); setExistingCustomers([]); setExistingCustomersError('');
    if (leadId) { void readState(true); void readCatalog(); }
    return () => { sequence.current += 1; };
    // Each lead owns a fresh, memory-only draft. Background refresh never overwrites it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leadId]);
  const loadExistingCustomers = async () => {
    if (catalog?.can_manage_catalog !== true) return;
    const id = leadId;
    setExistingCustomersError('');
    try {
      const result = await invokeWithAuth({ url: '/api/v1/entities/customers?limit=1000', method: 'GET' });
      if (activeLead.current !== id) return;
      if (!Array.isArray(result.data?.items)) throw new Error('已有客户列表读取失败。');
      setExistingCustomers(result.data.items.map((customer: any) => ({ id: customer.id, business_name: customer.business_name, customer_code: customer.customer_code })));
    } catch (problem) { if (activeLead.current === id) setExistingCustomersError(salesHandoffError(problem, '已有客户列表读取失败。')); }
  };
  const update = (patch: Partial<ReturnType<typeof newForm>>) => {
    if (!editable || saving) return;
    setForm(current => ({ ...current, ...patch })); setConfirmed(false); setError('');
  };
  const close = () => { if (!submitLock.current && draft.confirmDiscard()) onClose(); };
  const openDossier = () => { if (leadId && !submitLock.current && draft.confirmDiscard()) { onClose(); onOpenDossier?.(leadId); } };
  const validate = (nextStep: number) => {
    if (!selectedPlan || !selectedPlan.catalog_token) return '请选择已发布的统一套餐。';
    if (existingMode && !form.existing_customer_id) return '请选择需要新增项目的已有客户。';
    if (selectedPlan.required_collection_method === 'stripe_auto' ? form.collection_method !== 'stripe_auto' : form.collection_method === 'stripe_auto') return '收款方式必须与所选套餐的统一价格类型一致。';
    if (!form.service_start_date) return '请填写服务开始日期。';
    if (selectedPlan.default_billing_cycle !== 'one_time' && !form.service_end_date) return '周期服务请填写服务结束日期。';
    if (form.service_end_date && form.service_end_date <= form.service_start_date) return '服务结束日期必须晚于开始日期。';
    if (selectedPlan.platform_limit && form.selected_platforms.length > selectedPlan.platform_limit) return `这个套餐最多选择 ${selectedPlan.platform_limit} 个平台。`;
    if (nextStep > 1 && !form.operations_owner_employee_id) return '请选择运营接收负责人。';
    if (nextStep > 1 && form.customer_goal.trim().length < 3) return '请写明客户希望达成的目标。';
    return '';
  };
  const next = () => { const problem = validate(step + 1); if (problem) { setError(problem); return; } setError(''); setStep(current => Math.min(2, current + 1)); };
  const register = async () => {
    if (!leadId || !editable || submitLock.current || !selectedPlan) return;
    const problem = validate(2);
    if (problem || !confirmed) { setError(problem || '请确认成交与收款分别登记。'); return; }
    const id = leadId;
    const payload = {
      plan_id: selectedPlan.id, catalog_token: selectedPlan.catalog_token, selected_platforms: form.selected_platforms,
      service_start_date: form.service_start_date, service_end_date: form.service_end_date || null,
      collection_method: form.collection_method, operations_owner_employee_id: Number(form.operations_owner_employee_id),
      ...(existingMode && catalog?.can_manage_catalog === true ? { existing_customer_id: Number(form.existing_customer_id) } : {}),
      customer_goal: form.customer_goal.trim(), handoff_notes: form.handoff_notes.trim(), special_commitments: form.special_commitments.trim(), confirmation_notes: form.confirmation_notes.trim(),
    };
    if (payload.confirmation_notes.length < 3) { setError('请填写至少 3 个字的成交确认说明。'); return; }
    const signature = JSON.stringify(payload);
    if (!submission.current || submission.current.signature !== signature) submission.current = { signature, key: crypto.randomUUID() };
    submitLock.current = true; transaction.lock(); setSaving(true); setError('');
    try {
      const result = await dealHandoffApi<SalesDealLeadState>(`/leads/${id}`, 'POST', { ...payload, idempotency_key: submission.current.key });
      if (activeLead.current !== id) return;
      if (!result.registered || !result.handoff || result.handoff.lead_id !== id) throw new Error('登记结果尚未核对，请点击“核对登记结果”，勿重复登记。');
      const saved = { ...result.handoff, can_view_customer: result.handoff.can_view_customer ?? result.can_view_customer };
      setState(current => current ? { ...current, ...result, lead: current.lead } : current); setReceipt(saved); draft.markSaved();
      await onRegistered?.(saved);
    } catch (problem) {
      if (activeLead.current === id) setError(`${salesHandoffError(problem, '登记未完成。')} 输入已保留，可先核对登记结果再重试。`);
    } finally { submitLock.current = false; transaction.release(); setSaving(false); }
  };
  const registered = receipt || (state?.registered ? state.handoff : null);
  const historyUrl = state ? salesHandoffHistoryUrl(state) : null;

  return <Dialog open={leadId !== null} onOpenChange={open => { if (!open) close(); }}>
    <DialogContent className="sdh-dialog sales-center-ui" aria-describedby="sdh-description">
      <DialogHeader className="sdh-header"><DialogTitle>登记成交{state?.lead?.business_name ? ` · ${state.lead.business_name}` : ''}</DialogTitle><DialogDescription id="sdh-description">统一套餐直接登记，售前资料随项目交接；收款由老板另行核对。</DialogDescription></DialogHeader>
      {!registered && editable && <nav className="sdh-steps" aria-label="成交登记步骤">{['统一套餐', '售前交接', '确认登记'].map((label, index) => <button type="button" key={label} aria-current={step === index ? 'step' : undefined} disabled={saving || index > step} onClick={() => { setStep(index); setError(''); }}>{index + 1}. {label}</button>)}</nav>}
      <div className="sdh-body" aria-busy={loading || saving}>
        {error && <div className="sdh-note sdh-error" role="alert">{error}<div className="mt-2"><Button type="button" size="sm" variant="outline" disabled={saving || loading} onClick={() => void readState(!state)}>核对登记结果</Button></div></div>}
        {loading ? <p className="py-10 text-center text-sm text-slate-500" role="status">正在读取最新成交资料…</p> : registered ? <>
          <div className="sdh-success" role="status"><CheckCircle2 className="shrink-0" size={22}/><div><strong>成交已登记</strong><p>已创建客户项目，售前资料已保留。{registered.payment_status === 'paid' || registered.receipt_review_status === 'owner_verified' ? '老板已完成收款核对。' : registered.payment_status || registered.receipt_review_status === 'pending_owner_review' ? '收款待老板核对，尚未标记为已核对。' : '财务独立核对，收款详情按授权查看。'}</p></div></div>
          <dl className="sdh-summary mt-4"><div><dt>套餐</dt><dd>{registered.package_name}</dd></div><div><dt>统一成交价</dt><dd>{salesHandoffMoney(registered.amount, registered.currency) || '金额按独立授权查看'}</dd></div><div><dt>运营负责人</dt><dd>{registered.operations_owner_name || '待确认'}</dd></div><div><dt>运营接收</dt><dd>{registered.operations_status === 'accepted' ? '已确认接收' : registered.operations_access_status === 'authorized' ? '待负责人本人确认' : '待老板邀请授权'}</dd></div></dl>
          <SalesDealPaymentLink item={{ ...registered, business_name: state?.lead.business_name }}/>
          {registered.operations_access_status !== 'authorized' && <p className="sdh-note sdh-warning mt-4">指定运营负责人不会自动开放客户资料。请老板在客户中心邀请并授予服务交付权限后，由负责人本人确认接收。</p>}
          <p className="mt-4 text-xs leading-5 text-slate-500">此条售前线索已完成登记；后续新增合作项目请在客户中心处理，避免重复转入。</p>
          <div className="sdh-receipt-actions">{registered.can_view_customer === true && <Button type="button" variant="outline" onClick={() => navigate(`/customers?detail=${registered.customer_id}&returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`)}>查看客户与交接<ChevronRight size={14}/></Button>}{registered.can_view_customer !== true && <span className="sdh-note">客户资料待老板邀请；你仍可查看本次登记回执。</span>}</div>
        </> : ready && !editable ? <div className="sdh-note sdh-warning" role="status">{state?.read_only_reason || '当前账号不能登记此商家成交，请联系老板核对归属或客户关联。'}{onOpenDossier && <div className="mt-2"><Button type="button" variant="outline" size="sm" onClick={openDossier}>查看并完善商家档案</Button></div>}</div> : ready && editable ? <fieldset disabled={saving} className="min-w-0">
          {step === 0 && <div className="sdh-grid">
            {catalogError && <div className="sdh-note sdh-warning sdh-wide" role="alert">{catalogError}<Button type="button" size="sm" variant="ghost" onClick={() => void readCatalog()}>重新读取统一套餐</Button></div>}
            {catalog && !catalog.plans.length && <div className="sdh-note sdh-warning sdh-wide" role="status">{catalog.message || '暂无已发布的统一价格套餐。'}{catalog.can_manage_catalog === true && <a className="mt-2 block text-blue-700" href="/settings?tab=products">前往设置维护产品套餐</a>}</div>}
            {catalog?.can_manage_catalog === true && <div className="sdh-field sdh-wide"><span>客户归档方式</span><NativeSelect aria-label="客户归档方式" value={existingMode ? 'existing' : 'new'} onChange={value => { setExistingMode(value === 'existing'); update({ existing_customer_id: '' }); if (value === 'existing') void loadExistingCustomers(); }} options={[{ value: 'new', label: '新建客户与合作项目' }, { value: 'existing', label: '归入已有客户，新增合作项目（老板确认）' }]}/>{existingMode && <><CustomerCombobox customers={existingCustomers} value={form.existing_customer_id} onValueChange={value => update({ existing_customer_id: value })} placeholder="选择归入的已有客户"/>{existingCustomersError && <span role="alert" className="text-xs text-rose-700">{existingCustomersError}<Button type="button" variant="ghost" size="sm" onClick={() => void loadExistingCustomers()}>重试</Button></span>}<span className="text-xs font-normal text-slate-500">仅老板可确认关联已有客户；此次只新增合作项目，不重复建客户。</span></>}</div>}
            <label className="sdh-field sdh-wide">统一套餐 *<NativeSelect aria-label="统一套餐" value={form.plan_id} onChange={value => { const plan = catalog?.plans.find(item => String(item.id) === value); update({ plan_id: value, selected_platforms: [], collection_method: plan?.required_collection_method === 'stripe_auto' ? 'stripe_auto' : form.collection_method === 'stripe_auto' ? 'check' : form.collection_method, service_end_date: plan ? salesDealPeriodEnd(form.service_start_date, plan) : '' }); }} options={[{ value: '', label: catalog ? catalog.plans.length ? '请选择已发布套餐' : '暂无已发布套餐，请老板维护后再登记' : '正在读取统一套餐…' }, ...groupedPlans]}/></label>
            <Button type="button" className="self-start sdh-wide" size="sm" variant="ghost" onClick={() => void readCatalog()}>刷新已发布套餐（保留交接输入）</Button>
            {selectedPlan && <div className="sdh-price sdh-wide"><span className="text-xs text-blue-700"><LockKeyhole size={12} className="mr-1 inline"/>{selectedPlan.required_collection_method === 'stripe_auto' ? 'Stripe 自动订阅统一价' : '人工收款统一价'}</span><span className="mt-2 block text-sm font-semibold text-blue-900">{selectedPlan.name}</span><strong>{salesHandoffMoney(selectedPlan.standard_price, selectedPlan.default_currency)}</strong><p>{selectedPlan.default_billing_cycle === 'one_time' ? '一次性服务 · 本次费用' : `周期服务 · ${salesDealCycles[selectedPlan.default_billing_cycle] || selectedPlan.default_billing_cycle}每期费用`}；金额与账期由已发布套餐确定，不按月均价推算其他周期。</p>{selectedPlan.required_collection_method === 'stripe_auto' && <><p className="sdh-price-billing">{selectedPlan.payment_link?.cadence_label || salesPaymentCadence(selectedPlan.default_billing_cycle)} · 每期一次收取上述服务费 · 适用税额另计</p><p>登记后可直接获取关联本单的付款链接。现有客户请先核对原订阅，避免重复订阅；原订阅和价格不会改变。</p>{!selectedPlan.payment_link && <p className="sdh-payment-unavailable">该套餐付款链接尚未就绪，登记后请联系老板核对，勿使用其他套餐链接。</p>}</>}</div>}
            {selectedPlan && <div className="sdh-field sdh-wide"><span>交付平台{selectedPlan.platform_limit ? `（最多 ${selectedPlan.platform_limit} 个）` : ''}</span><div className="sdh-platforms">{(catalog?.platform_options || salesDealPlatforms).map(platform => <label key={platform}><input type="checkbox" checked={form.selected_platforms.includes(platform)} onChange={event => update({ selected_platforms: event.target.checked ? [...form.selected_platforms, platform] : form.selected_platforms.filter(value => value !== platform) })}/>{platform}</label>)}</div></div>}
            <label className="sdh-field">服务开始 *<Input aria-label="服务开始" type="date" value={form.service_start_date} onChange={event => update({ service_start_date: event.target.value, ...(selectedPlan && selectedPlan.default_billing_cycle !== 'one_time' ? { service_end_date: salesDealPeriodEnd(event.target.value, selectedPlan) } : {}) })}/></label><label className="sdh-field">服务结束<Input aria-label="服务结束" type="date" value={form.service_end_date} min={form.service_start_date} readOnly={selectedPlan?.default_billing_cycle !== 'one_time'} onChange={event => update({ service_end_date: event.target.value })}/>{selectedPlan && selectedPlan.default_billing_cycle !== 'one_time' && <span className="text-xs font-normal text-slate-500">按套餐账期自动计算。</span>}</label>
            <label className="sdh-field sdh-wide">约定收款方式{selectedPlan?.required_collection_method === 'stripe_auto' ? <Input aria-label="约定收款方式" readOnly value="Stripe 自动订阅（该套餐固定）"/> : <NativeSelect aria-label="约定收款方式" value={form.collection_method} onChange={value => update({ collection_method: value })} options={salesCollectionMethods.filter(option => option.value !== 'stripe_auto')}/>}<span className="text-xs font-normal text-slate-500">人工收款价与 Stripe 自动订阅价分别锁定；这里只记录约定，不创建扣款、不代表款项到账。</span></label>
          </div>}
          {step === 1 && <div className="sdh-grid">
            <div className="sdh-field sdh-wide"><span>承接联系人</span><div className="sdh-contacts">{state?.contacts?.length ? state.contacts.map((contact, index) => <div key={contact.id || index} className="sdh-contact"><strong>{contact.name || '联系人待补充'}{contact.role ? ` · ${contact.role}` : ''}</strong><p>{[contact.phone, contact.email, contact.wechat].filter(Boolean).join(' · ') || '联系方式待补充'}</p></div>) : <p className="sdh-note">{state?.lead?.contact_name || '未补充联系人'} · {state?.lead?.phone || '电话待补充'}</p>}</div>{onOpenDossier && <Button type="button" className="self-start" size="sm" variant="ghost" onClick={openDossier}>去商家档案完善资料</Button>}<span className="text-xs font-normal text-slate-500">登记时保存最新联系人和沟通资料快照，原始采集与累计记录保留。</span></div>
            <label className="sdh-field sdh-wide">客户目标 *<Textarea aria-label="客户目标" rows={3} maxLength={4000} value={form.customer_goal} onChange={event => update({ customer_goal: event.target.value })} placeholder="客户希望解决什么问题，交付优先做什么"/></label>
            <label className="sdh-field sdh-wide">运营接收负责人 *<NativeSelect aria-label="运营接收负责人" value={form.operations_owner_employee_id} onChange={value => update({ operations_owner_employee_id: value })} options={[{ value: '', label: '请选择运营负责人' }, ...(state?.operations_candidates || []).map(item => ({ value: String(item.id), label: item.name }))]}/><span className="text-xs font-normal text-slate-500">仅指定承接人；客户权限仍由老板邀请授予。</span></label>
            <label className="sdh-field sdh-wide">特殊承诺 / 注意事项<Textarea aria-label="特殊承诺 / 注意事项" rows={2} maxLength={4000} value={form.special_commitments} onChange={event => update({ special_commitments: event.target.value })}/></label>
            <label className="sdh-field sdh-wide">交接补充<Textarea aria-label="交接补充" rows={2} maxLength={4000} value={form.handoff_notes} onChange={event => update({ handoff_notes: event.target.value })} placeholder="素材、账号权限、沟通习惯或尚未解决的问题"/></label>
          </div>}
          {step === 2 && <div className="space-y-4"><dl className="sdh-summary"><div><dt>商家</dt><dd>{state?.lead?.business_name}</dd></div>{existingMode && <div><dt>归入已有客户</dt><dd>{existingCustomers.find(customer => String(customer.id) === form.existing_customer_id)?.business_name || `客户 #${form.existing_customer_id}`}</dd></div>}<div><dt>统一套餐</dt><dd>{selectedPlan?.name}</dd></div><div><dt>标准成交价</dt><dd>{salesHandoffMoney(selectedPlan?.standard_price, selectedPlan?.default_currency)} · {salesDealCycles[selectedPlan?.default_billing_cycle || ''] || selectedPlan?.default_billing_cycle}</dd></div><div><dt>服务时间</dt><dd>{form.service_start_date} 至 {form.service_end_date || '按套餐约定'}</dd></div><div><dt>客户目标</dt><dd>{form.customer_goal}</dd></div><div><dt>运营负责人</dt><dd>{state?.operations_candidates.find(item => String(item.id) === form.operations_owner_employee_id)?.name}</dd></div></dl><div className="sdh-note sdh-warning"><p>{existingMode ? '登记后归入已选客户并新增合作项目' : '登记后创建客户与合作项目'}，收款保持“待核对”，不会把成交金额当作实收收入。</p><p>运营负责人须先获老板邀请授权，再由本人确认接收；此操作不会自动开放客户或财务权限。</p></div><label className="sdh-field">成交确认说明 *<Textarea aria-label="成交确认说明" rows={2} maxLength={1000} value={form.confirmation_notes} onChange={event => update({ confirmation_notes: event.target.value })}/></label><label className="sdh-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>我已核对套餐和交接内容，确认登记成交；实际收款另由老板核对。</label></div>}
        </fieldset> : null}
        {state?.legacy_quotes?.length ? <details className="sdh-legacy"><summary>历史报价与审核 · {state.legacy_quotes.length} 条（只读）</summary>{state.legacy_quotes.map(quote => <article key={quote.id}><strong>{quote.package_name} · {salesHandoffMoney(quote.final_amount, quote.currency)}</strong><p>{quoteStatuses[quote.status || ''] || quote.status || '历史记录'}{quote.reviewed_by_name ? ` · ${quote.reviewed_by_name}` : ''}</p>{quote.review_notes && <p>审核备注：{quote.review_notes}</p>}</article>)}</details> : null}
        {historyUrl && <a onClick={event => { if (submitLock.current || !draft.confirmDiscard()) event.preventDefault(); }} className="mt-4 inline-flex items-center gap-1 text-xs text-blue-600" href={historyUrl}>查看售前来源与累计历史<ExternalLink size={12}/></a>}
      </div>
      <footer className="sdh-footer"><Button type="button" variant="ghost" disabled={saving} onClick={close}>{registered ? '完成' : '取消'}</Button>{!registered && editable && <div>{step > 0 && <Button type="button" variant="outline" disabled={saving} onClick={() => { setStep(current => current - 1); setError(''); }}>上一步</Button>}{step < 2 ? <Button type="button" disabled={saving || loading || !selectedPlan || Boolean(catalogError)} onClick={next}>下一步<ChevronRight size={14}/></Button> : <Button type="button" disabled={saving || !confirmed} onClick={() => void register()}>{saving ? '正在登记…' : '确认登记成交'}</Button>}</div>}</footer>
    </DialogContent>
  </Dialog>;
}
