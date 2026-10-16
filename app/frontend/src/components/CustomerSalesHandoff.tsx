import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ExternalLink, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import SalesDealPaymentLink from '@/components/SalesDealPaymentLink';
import SalesDealPaymentEvidence from '@/components/SalesDealPaymentEvidence';
import { formatBusinessDateTimeInput } from '@/lib/business-date';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { dealHandoffApi, salesCollectionMethods, salesDealCycles, salesHandoffError, salesHandoffHistoryUrl, salesHandoffMoney, salesPaymentReconciliation, type SalesDealHandoff, type SalesPaymentObservation } from '@/lib/sales-deal-handoff';
import './sales-deal-handoff.css';

export function HandoffRecord({ item, onChanged, onBusyChange, initialAction }: { item: SalesDealHandoff; onChanged: () => Promise<void>; onBusyChange?: (busy: boolean) => void; initialAction?: 'ack' | 'finance' | null }) {
  const [action, setAction] = useState<'ack' | 'finance' | null>(() => initialAction === 'ack' && item.can_operations_ack === true ? 'ack' : initialAction === 'finance' && item.can_finance_confirm === true ? 'finance' : null);
  const [note, setNote] = useState('');
  const newPayment = () => ({ amount_received: '', payment_date: '', payment_method: item.collection_method === 'stripe_auto' ? 'stripe' : item.collection_method || 'bank_transfer', transaction_reference: '', tax_amount: '', fee_amount: '', gross_amount: '', net_amount: '', stripe_observation_id: null as number | null });
  const [payment, setPayment] = useState(newPayment);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const lock = useRef(false);
  const transaction = useHardNavigationBlock(busy);
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);
  const dirty = Boolean(action && (action === 'ack' ? note.trim() : payment.amount_received || payment.transaction_reference || payment.tax_amount || payment.fee_amount || payment.gross_amount || payment.net_amount));
  const draft = useUnsavedChanges(dirty);
  const historyUrl = salesHandoffHistoryUrl(item);
  const source = item.source || {};
  const contacts = source.contacts || item.contacts || [];
  const customerGoal = source.customer_goal || item.customer_goal;
  const commitments = source.special_commitments || item.special_commitments;
  const handoffNotes = source.handoff_notes || item.handoff_notes;
  const serviceStart = source.service_start_date || item.service_start_date;
  const serviceEnd = source.service_end_date || item.service_end_date;
  const isStripe = payment.payment_method === 'stripe';
  const reconciliation = salesPaymentReconciliation({ service_amount: item.amount ?? '', tax_amount: payment.tax_amount, fee_amount: payment.fee_amount, gross_amount: payment.gross_amount, net_amount: payment.net_amount }, item.amount);
  const updatePayment = (patch: Partial<ReturnType<typeof newPayment>>) => { setConfirmed(false); setPayment(current => ({ ...current, ...patch })); setError(''); };
  const useObservation = (observation: SalesPaymentObservation) => {
    if (busy || item.can_finance_confirm !== true || observation.status !== 'paid_observed' || !observation.paid_at || observation.match_issues?.length || observation.service_amount !== item.amount || observation.currency !== item.currency) return;
    if (action && !draft.confirmDiscard()) return;
    setAction('finance'); setConfirmed(false); setError('');
    setPayment({ ...newPayment(), payment_method: 'stripe', amount_received: String(item.amount ?? ''), tax_amount: String(observation.tax_amount ?? ''), gross_amount: String(observation.gross_amount ?? ''), payment_date: formatBusinessDateTimeInput(observation.paid_at).slice(0, 10), transaction_reference: observation.payment_intent_id || observation.invoice_id || observation.session_id || '', stripe_observation_id: observation.id });
  };
  const cancel = () => { if (!lock.current && draft.confirmDiscard()) { setAction(null); setError(''); } };
  const submit = async () => {
    if (lock.current || !action || !confirmed || (action === 'ack' ? item.can_operations_ack !== true : item.can_finance_confirm !== true)) return;
    if (action === 'ack' && note.trim().length < 3) { setError('请填写至少 3 个字的本人接收备注。'); return; }
    if (action === 'finance' && !item.currency) { setError('收款币种待核实，请刷新状态后重试。'); return; }
    if (action === 'finance' && isStripe && !reconciliation.valid) { setError(reconciliation.message); return; }
    if (action === 'finance' && ((!isStripe && (!payment.amount_received.trim() || !Number.isFinite(Number(payment.amount_received)) || Number(payment.amount_received) <= 0)) || !payment.payment_date || !payment.transaction_reference.trim())) {
      setError('请填写核实到账的金额、日期和交易凭据编号。'); return;
    }
    lock.current = true; transaction.lock(); setBusy(true); setError(''); setSuccess('');
    try {
      await dealHandoffApi(`/${item.id}/${action === 'ack' ? 'operations-acknowledgment' : 'finance-confirmation'}`, 'POST', action === 'ack' ? { note: note.trim() } : { amount_received: isStripe ? item.amount : Number(payment.amount_received), payment_date: payment.payment_date, currency: item.currency, payment_method: payment.payment_method, transaction_reference: payment.transaction_reference.trim(), ...(isStripe ? { service_amount: item.amount, tax_amount: Number(payment.tax_amount), fee_amount: Number(payment.fee_amount), gross_amount: Number(payment.gross_amount), net_amount: Number(payment.net_amount), ...(payment.stripe_observation_id ? { stripe_observation_id: payment.stripe_observation_id } : {}) } : {}) });
      draft.markSaved(); setAction(null); setConfirmed(false); setNote(''); setPayment(newPayment());
      setSuccess(action === 'ack' ? '本人已确认接收交接。' : '全额收款已核对并登记。');
      await onChanged();
    } catch (problem) { setError(`${salesHandoffError(problem, '操作尚未完成。')} 输入已保留，请刷新状态核对后再重试。`); }
    finally { lock.current = false; transaction.release(); setBusy(false); }
  };
  return <article className="sdh-record" aria-label={`售前承接 ${item.package_name || '资料'}`}>
    <div className="sdh-record-heading"><div><strong>{item.package_name || '售前承接资料'}</strong><div className="sdh-statuses">{item.payment_status ? <span>{item.payment_status === 'paid' ? '收款已核对' : '收款待核对'}</span> : item.receipt_review_status && <span>{item.receipt_review_status === 'owner_verified' ? '老板已完成核对' : '待老板核对收款'}</span>}{item.operations_status && <span>{item.operations_status === 'accepted' ? '运营已接收' : item.operations_access_status === 'authorized' ? '运营待接收' : '待老板邀请授权'}</span>}{item.created_at && <span>{item.created_at.slice(0, 10)}</span>}</div></div>{typeof item.amount === 'number' && <strong>{salesHandoffMoney(item.amount, item.currency)}</strong>}</div>
    <dl className="sdh-summary">{customerGoal && <div><dt>客户目标</dt><dd>{customerGoal}</dd></div>}{item.operations_owner_name && <div><dt>运营负责人</dt><dd>{item.operations_owner_name}</dd></div>}{serviceStart && <div><dt>服务时间</dt><dd>{serviceStart} 至 {serviceEnd || '按套餐约定'}</dd></div>}{item.billing_cycle && <div><dt>服务周期</dt><dd>{salesDealCycles[item.billing_cycle] || item.billing_cycle}</dd></div>}{commitments && <div><dt>特别承诺</dt><dd>{commitments}</dd></div>}{handoffNotes && <div><dt>交接补充</dt><dd>{handoffNotes}</dd></div>}{source.lead_notes && <div><dt>沟通摘要</dt><dd>{source.lead_notes}</dd></div>}</dl>
    {contacts.length ? <details><summary>承接联系人 · {contacts.length} 位</summary><div className="sdh-contacts">{contacts.map((contact, index) => <div className="sdh-contact" key={contact.id || index}><strong>{contact.name || '联系人'}{contact.role ? ` · ${contact.role}` : ''}</strong><p>{[contact.phone, contact.email, contact.wechat].filter(Boolean).join(' · ') || '联系方式待补充'}</p></div>)}</div></details> : null}
    {source.summary && Object.entries(source.summary).some(([, value]) => typeof value === 'string' && value) && <details><summary>售前重点摘要</summary><dl className="sdh-summary">{Object.entries(source.summary).filter(([, value]) => typeof value === 'string' && value).map(([key, value]) => <div key={key}><dt>{{ latest_conclusion: '最近结论', objections: '主要顾虑', promises: '已作承诺', next_step: '下一步', need_summary: '需求', decision_maker: '决策人', best_contact_time: '联系时间', concerns: '主要顾虑', next_action: '下一步' }[key] || '售前记录'}</dt><dd>{String(value)}</dd></div>)}</dl></details>}
    {source.history?.length ? <details><summary>售前沟通记录 · {source.history.length} 条</summary><div className="sdh-contacts">{[...source.history].reverse().slice(0, 20).map(record => <div key={record.id} className="sdh-contact"><strong>{record.sales_employee_name || '销售记录'} · {record.called_at?.slice(0, 10) || '日期待确认'}</strong><p className="whitespace-pre-wrap">{record.notes || '未填写沟通内容'}</p></div>)}</div></details> : null}
    {historyUrl && <a onClick={event => { if (!confirmDiscardAllChanges()) event.preventDefault(); }} href={historyUrl} className="mt-3 inline-flex items-center gap-1 text-xs text-blue-600">查看售前来源与累计历史<ExternalLink size={12}/></a>}
    {item.operations_access_status === 'pending' && <p className="sdh-note sdh-warning">运营接收权限待老板邀请。指定负责人不会自动开放客户资料或财务信息。</p>}
    {item.operations_acknowledged_at && <p className="mt-3 text-xs text-slate-500">{item.operations_owner_name} 已确认接收 · {item.operations_acknowledged_at.slice(0, 10)}</p>}
    <SalesDealPaymentLink item={item}/>
    <SalesDealPaymentEvidence item={item} onUse={item.can_finance_confirm === true ? useObservation : undefined}/>
    {success && <p className="sdh-note mt-3" role="status"><CheckCircle2 size={14} className="mr-1 inline"/>{success}</p>}
    {error && <p className="sdh-note sdh-error mt-3" role="alert">{error}</p>}
    {!action && (item.can_operations_ack === true || item.can_finance_confirm === true) && <div className="sdh-receipt-actions">{item.can_operations_ack === true && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setAction('ack'); setConfirmed(false); setError(''); }}>确认本人接收</Button>}{item.can_finance_confirm === true && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setAction('finance'); setConfirmed(false); setError(''); }}>核对全额收款</Button>}</div>}
    {action && <fieldset disabled={busy} className="sdh-record-form">
      {action === 'ack' ? <><p className="sdh-note">请本人核对客户目标、联系人与特别承诺后接收。此操作不代表确认收款。</p><label className="sdh-field">接收备注<Textarea aria-label="接收备注" value={note} rows={2} maxLength={2000} onChange={event => setNote(event.target.value)}/></label></> : <>
        <p className="sdh-note sdh-warning">仅支持一次全额核款。请按真实交易和结算凭据填写，订金不能标记为全额收入；平台通知不会自动确认收款。</p>
        <div className="sdh-finance-grid">
          <label className="sdh-field">实际收款方式<NativeSelect aria-label="实际收款方式" value={payment.payment_method} onChange={value => updatePayment({ payment_method: value, stripe_observation_id: null })} options={salesCollectionMethods.map(option => option.value === 'stripe_auto' ? { value: 'stripe', label: 'Stripe' } : option)}/></label>
          <label className="sdh-field">实际到账日期 *<Input aria-label="实际到账日期" type="date" value={payment.payment_date} onChange={event => updatePayment({ payment_date: event.target.value })}/></label>
          {isStripe ? <>
            <label className="sdh-field">服务费（统一成交价）<Input aria-label="服务费（统一成交价）" value={salesHandoffMoney(item.amount, item.currency)} readOnly/></label>
            <label className="sdh-field">税额 *<Input aria-label="税额" type="number" min="0" step="0.01" placeholder="无税请填写 0" value={payment.tax_amount} onChange={event => updatePayment({ tax_amount: event.target.value })}/></label>
            <label className="sdh-field">客户支付总额 *<Input aria-label="客户支付总额" type="number" min="0.01" step="0.01" placeholder="服务费 + 税" value={payment.gross_amount} onChange={event => updatePayment({ gross_amount: event.target.value })}/></label>
            <label className="sdh-field">Stripe 手续费 *<Input aria-label="Stripe 手续费" type="number" min="0" step="0.01" placeholder="按真实结算凭据" value={payment.fee_amount} onChange={event => updatePayment({ fee_amount: event.target.value })}/></label>
            <label className="sdh-field">净到账金额 *<Input aria-label="净到账金额" type="number" min="0" step="0.01" placeholder="总额 − 手续费" value={payment.net_amount} onChange={event => updatePayment({ net_amount: event.target.value })}/></label>
          </> : <label className="sdh-field">实际到账金额 *<Input aria-label="实际到账金额" type="number" min="0.01" step="0.01" value={payment.amount_received} onChange={event => updatePayment({ amount_received: event.target.value })}/></label>}
          <label className="sdh-field sdh-wide">交易号 / 凭据编号 *<Input aria-label="交易号 / 凭据编号" value={payment.transaction_reference} maxLength={200} onChange={event => updatePayment({ transaction_reference: event.target.value })}/></label>
        </div>
        {isStripe && <div className={`sdh-note ${reconciliation.complete && !reconciliation.valid ? 'sdh-error' : ''}`} role="status"><p>{reconciliation.message}</p><p>本单服务费仍按 {salesHandoffMoney(item.amount, item.currency)} 记录；税与到账拆分单独留存，公司原有利润计算和关账条件不变。</p>{payment.stripe_observation_id && <p>已带入平台记录 #{payment.stripe_observation_id}，请补齐并核实手续费和净到账。</p>}</div>}
      </>}
      <label className="sdh-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>{action === 'ack' ? '我已查看上述交接资料，确认由本人接收。' : '我已核对真实到账凭据，确认本项目已全额收款。'}</label>
      <div><Button type="button" variant="ghost" disabled={busy} onClick={cancel}>取消</Button><Button type="button" disabled={busy || !confirmed || (action === 'finance' && isStripe && !reconciliation.valid)} onClick={() => void submit()}>{busy ? '提交中…' : action === 'ack' ? '确认接收' : '确认全额到账'}</Button></div>
    </fieldset>}
  </article>;
}

export default function CustomerSalesHandoff({ customerId, refreshKey, onChanged }: { customerId: number; refreshKey?: string | number | null; onChanged?: () => Promise<void> }) {
  const [items, setItems] = useState<SalesDealHandoff[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const load = async () => {
    const request = ++sequence.current;
    setLoading(true); setError('');
    try {
      const data = await dealHandoffApi<{ items: SalesDealHandoff[] }>(`/customers/${customerId}`);
      if (sequence.current !== request) return;
      if (!Array.isArray(data.items)) throw new Error('承接资料暂不可用。');
      setItems(data.items);
    } catch (problem: any) {
      if (sequence.current !== request) return;
      setItems([]);
      const status = problem?.status || problem?.response?.status;
      if (status !== 403 && status !== 404) setError(salesHandoffError(problem, '售前承接资料读取失败。'));
    } finally { if (sequence.current === request) setLoading(false); }
  };
  useEffect(() => { void load(); return () => { sequence.current += 1; }; }, [customerId, refreshKey]);
  if (!loading && !items.length && !error) return null;
  return <section className="sdh-customer-card" aria-label="售前承接"><div className="sdh-card-heading"><div><h3>售前承接</h3><p>按已授权范围查看销售承诺、联系人与运营接收。</p></div><Button type="button" variant="ghost" size="icon" aria-label="刷新售前承接" disabled={loading} onClick={() => void load()}><RefreshCw size={14}/></Button></div>{error ? <p className="sdh-note sdh-error mt-3" role="alert">{error}</p> : loading && !items.length ? <p className="mt-3 text-sm text-slate-500" role="status">正在读取承接资料…</p> : items.map(item => <HandoffRecord key={item.id} item={item} onChanged={async () => { await load(); await onChanged?.(); }}/>)}</section>;
}
