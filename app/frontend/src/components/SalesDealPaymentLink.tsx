import { useEffect, useRef, useState } from 'react';
import { Copy, Link2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { salesDealPaymentApi, salesHandoffError, salesHandoffMoney, salesPaymentCadence, salesPaymentRequestUrl, type SalesDealHandoff, type SalesPaymentRequestState } from '@/lib/sales-deal-handoff';

/** Sharing a payment request never confirms collection or expands customer access. */
export default function SalesDealPaymentLink({ item }: { item: SalesDealHandoff }) {
  const [state, setState] = useState<SalesPaymentRequestState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const sequence = useRef(0);
  const lock = useRef(false);
  const allowed = item.can_request_payment === true;
  const read = async (create: boolean) => {
    if (!allowed || lock.current) return;
    const request = ++sequence.current;
    lock.current = true; setLoading(true); setError(''); setCopied(false);
    try {
      const next = await salesDealPaymentApi<SalesPaymentRequestState>(`/${item.id}/request`, create ? 'POST' : 'GET');
      if (sequence.current !== request) return;
      if (!next || typeof next.can_create !== 'boolean') throw new Error('付款信息暂不可用，请刷新后重试。');
      if (next.payment_request && !salesPaymentRequestUrl(next.payment_request)) throw new Error('付款链接关联未通过核对，暂不能复制，请联系老板。');
      if (next.payment_request && (next.payment_request.amount !== item.amount || next.payment_request.currency !== item.currency || next.payment_request.billing_cycle !== item.billing_cycle || next.payment_request.tax_mode !== 'exclusive' || next.payment_request.automatic_renewal !== true)) throw new Error('付款链接金额、币种或周期与本单不一致，暂不能复制，请联系老板核对。');
      setState(next);
    } catch (problem) { if (sequence.current === request) setError(salesHandoffError(problem, '付款链接读取失败。')); }
    finally { if (sequence.current === request) { lock.current = false; setLoading(false); } }
  };
  useEffect(() => {
    lock.current = false; setState(null); setError(''); setCopied(false);
    if (allowed) void read(false);
    return () => { sequence.current += 1; };
    // Access is explicit and scoped to this handoff; no reads for collaborators.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, allowed]);
  if (!allowed) return null;
  const payment = state?.payment_request;
  const url = salesPaymentRequestUrl(payment || null);
  const text = payment && url ? [
    `${item.business_name || '您好'}，这是 ${item.package_name || 'T24 代运营服务'} 的 Stripe 订阅付款信息：`,
    `每期服务费：${salesHandoffMoney(payment.amount, payment.currency)}；${payment.cadence_label || salesPaymentCadence(payment.billing_cycle)}。`,
    '如适用，税额将由 Stripe 结账页另行显示并加收。订阅自动续费，直到取消。',
    '如您已有此项服务的订阅，请先与我们核对，避免重复订阅。',
    '请在官方结账页核对 PIXELPATE INC、套餐与周期，填写商家名称和邮箱后付款。',
    url,
  ].join('\n') : '';
  const copy = async () => {
    if (!text) return;
    try { await navigator.clipboard.writeText(text); setCopied(true); setError(''); }
    catch { setCopied(false); setError('未能自动复制，请在下方付款信息中全选后复制。'); }
  };
  return <section className="sdh-payment-link" aria-label="本单付款链接" aria-busy={loading}>
    <div className="sdh-card-heading"><div><h4><Link2 size={15}/>本单付款链接</h4><p>链接关联此次成交，复制后由销售发送给客户。</p></div>{payment && <Button type="button" variant="ghost" size="icon" aria-label="刷新本单付款链接" disabled={loading} onClick={() => void read(false)}><RefreshCw size={14}/></Button>}</div>
    {error && <p className="sdh-note sdh-error" role="alert">{error}</p>}
    {payment && url ? <>
      <dl className="sdh-summary"><div><dt>每期服务费</dt><dd>{salesHandoffMoney(payment.amount, payment.currency)}</dd></div><div><dt>扣款周期</dt><dd>{payment.cadence_label || salesPaymentCadence(payment.billing_cycle)}</dd></div><div><dt>本单关联编号</dt><dd>{payment.reference}</dd></div></dl>
      <p className="sdh-payment-guidance">适用税额另计 · 自动续费直到取消 · 收款仍待老板核对</p>
      {(payment.duplicate_warnings || []).map((warning, index) => <p key={index} className="sdh-note sdh-warning">{warning}</p>)}
      <details className="sdh-payment-scope"><summary>重复订阅核查范围</summary><p>{payment.duplicate_scope || '仅核查本系统已记录的在服服务和本接入收到的付款记录，不能确认 Stripe 全部历史订阅。'} 老客户付款前请由老板再核对。</p></details>
      <label className="sdh-field">可发送给客户的付款信息<Textarea aria-label="可发送给客户的付款信息" readOnly value={text} rows={6}/></label>
      <div className="sdh-receipt-actions"><Button type="button" size="sm" disabled={loading} onClick={() => void copy()}><Copy size={14}/>{copied ? '已复制付款信息' : '复制本单付款信息'}</Button></div>
      {copied && <p className="sdh-payment-guidance" role="status">已复制完整链接。复制和客户打开链接都不会将本单标记为已收款。</p>}
    </> : <>
      <p className="sdh-payment-guidance">每期按已登记套餐收费，适用税额另计。现有客户需先核查订阅，避免重复扣款；不会更改原订阅。</p>
      <Button type="button" size="sm" disabled={loading || state?.can_create === false} onClick={() => void read(true)}>{loading ? '正在读取…' : '获取本单付款链接'}</Button>
      {state?.read_only_reason && <p className="sdh-payment-guidance">{state.read_only_reason}</p>}
    </>}
  </section>;
}
