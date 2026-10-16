import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatBusinessDateTimeInput } from '@/lib/business-date';
import { salesDealPaymentApi, salesHandoffError, salesHandoffMoney, type SalesDealHandoff, type SalesPaymentObservation, type SalesPaymentObservations } from '@/lib/sales-deal-handoff';

const observationStatuses: Record<string, string> = { paid_observed: '平台付款成功 · 待老板核对', processing: '支付处理中', failed: '付款失败', needs_review: '关联或金额待核实', expired: '结账已过期' };
const matchIssueLabels: Record<string, string> = { cross_request_identity: '该订阅或交易关联其他成交单', service_amount_mismatch: '服务费与本单不一致', currency_mismatch: '付款币种与本单不一致', gross_tax_mismatch: '服务费、税和支付总额不一致', unexpected_discount_or_shipping: '出现未约定的折扣或运费', subscription_identity_missing: '缺少可核实的订阅编号' };

export default function SalesDealPaymentEvidence({ item, onUse }: { item: SalesDealHandoff; onUse?: (observation: SalesPaymentObservation) => void }) {
  const [data, setData] = useState<SalesPaymentObservations | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const allowed = item.can_view_payment_observations === true;
  const load = async () => {
    const request = ++sequence.current;
    setLoading(true); setError('');
    try {
      const result = await salesDealPaymentApi<SalesPaymentObservations>(`/${item.id}/observations`);
      if (sequence.current !== request) return;
      if (!Array.isArray(result.items)) throw new Error('平台付款观察暂不可用。');
      setData(result);
    } catch (problem) { if (sequence.current === request) { setData(null); setError(salesHandoffError(problem, '平台付款记录读取失败，请重试。')); } }
    finally { if (sequence.current === request) setLoading(false); }
  };
  useEffect(() => {
    setData(null); setError('');
    if (allowed) void load();
    return () => { sequence.current += 1; };
    // No observations endpoint is called without explicit owner-only capability.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, allowed, item.payment_status]);
  if (!allowed) return null;
  const evidence = data?.receipt_evidence;
  return <section className="sdh-payment-evidence" aria-label="老板付款核对依据" aria-busy={loading}>
    <div className="sdh-card-heading"><div><h4>平台付款与核对依据</h4><p>仅老板可见。平台通知提供线索，实际收款仍由你确认。</p></div><Button type="button" variant="ghost" size="icon" aria-label="刷新平台付款记录" disabled={loading} onClick={() => void load()}><RefreshCw size={14}/></Button></div>
    {loading && !data && <p className="sdh-payment-guidance" role="status">正在读取平台付款记录…</p>}
    {error && <p className="sdh-note sdh-error" role="alert">{error}</p>}
    {(data?.duplicate_warnings || []).map((warning, index) => <p key={index} className="sdh-note sdh-warning">{warning}</p>)}
    {!loading && data && !data.items.length && <p className="sdh-payment-guidance">尚未收到本单的平台付款通知。请核对 Stripe 真实交易记录，客户提供截图不代表已到账。</p>}
    {data?.items.map(observation => {
      const canUse = Boolean(onUse && item.can_finance_confirm && observation.status === 'paid_observed' && observation.paid_at && !observation.match_issues?.length && observation.service_amount === item.amount && observation.currency === item.currency);
      return <article key={observation.id} className="sdh-observation"><div className="sdh-record-heading"><strong>{observationStatuses[observation.status] || '平台付款待核实'}</strong><span>#{observation.id}</span></div><dl className="sdh-summary"><div><dt>服务费</dt><dd>{salesHandoffMoney(observation.service_amount, observation.currency) || '待核实'}</dd></div><div><dt>税</dt><dd>{salesHandoffMoney(observation.tax_amount, observation.currency) || '待核实'}</dd></div><div><dt>客户支付总额</dt><dd>{salesHandoffMoney(observation.gross_amount, observation.currency) || '待核实'}</dd></div>{observation.paid_at && <div><dt>平台支付时间（北京时间）</dt><dd>{formatBusinessDateTimeInput(observation.paid_at).replace('T', ' ')}</dd></div>}</dl>{(observation.payer_business_name || observation.payer_name || observation.payer_email) && <div className="sdh-payer"><strong>付款人核验</strong><p>{[observation.payer_business_name, observation.payer_name, observation.payer_email].filter(Boolean).join(' · ')}</p><p>请确认与本单商家一致；关联编号不能证明付款人身份。</p></div>}{observation.match_issues?.length > 0 && <p className="sdh-note sdh-warning">{observation.match_issues.map(issue => matchIssueLabels[issue] || '平台记录存在待核实项目，请到 Stripe 核对').join('；')}</p>}<details><summary>查看平台交易编号</summary><dl className="sdh-summary">{[['结账单', observation.session_id], ['付款', observation.payment_intent_id], ['账单', observation.invoice_id], ['订阅', observation.subscription_id]].filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></details>{canUse && <Button type="button" size="sm" variant="outline" onClick={() => onUse?.(observation)}>带入核款，仍需本人确认</Button>}</article>;
    })}
    {evidence && <details className="sdh-receipt-evidence"><summary>已核对收款的金额拆分</summary><dl className="sdh-summary">{[['服务费', evidence.service_amount], ['税', evidence.tax_amount], ['手续费', evidence.fee_amount], ['客户支付总额', evidence.gross_amount], ['净到账', evidence.net_amount]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{salesHandoffMoney(Number(value), evidence.currency || item.currency)}</dd></div>)}</dl></details>}
    {data?.duplicate_scope && <p className="sdh-payment-guidance">核查范围：{data.duplicate_scope}</p>}
  </section>;
}
