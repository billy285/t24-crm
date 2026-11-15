import { useEffect, useRef, useState } from 'react';
import { ChevronRight, Download } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader, Dialog, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { addBusinessDateDays, businessDateKey } from '@/lib/business-date';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';

type StatementStatus = 'scheduled' | 'ready' | 'needs_review' | 'paid';
type Statement = {
  id: number; month: string; partner_id: number; partner_name: string; currency: string;
  issue_date: string; due_date: string; status: StatementStatus; revision: string;
  entry_count: number; total_amount: number; deferred_count: number; deferred_amount: number;
  issues: string[]; payout_reference?: string | null; paid_at?: string | null;
};
type StatementEntry = {
  entry_id: number; customer_id: number; customer_name?: string | null; payment_id: number;
  refund_id?: number | null; entry_type: string; source_month: string; eligible_service_amount: number;
  commission_amount: number; contract_rate: number; due_date?: string | null;
};
type StatementDetail = Statement & { entries: StatementEntry[]; deferred_entries: StatementEntry[] };
type StatementList = {
  month: string; items: Statement[];
  issues: { description: string; payment_id?: number; partner_id?: number; currency?: string }[];
  schedule?: { last_completed_date: string | null };
};
type Partner = { id: number; name: string; partner_code: string; partner_type: string };
type Props = {
  monthParam: string; setMonth: (value: string) => void; partners: Partner[]; canSettle: boolean;
  refreshKey: number; onSettled: () => void;
};

const endpoint = '/api/v1/commissions/statements';
const statusLabel = { scheduled: '未到结算日', ready: '待登记付款', needs_review: '需核对', paid: '已结清' };
function statementStatus(row: Statement) {
  if (row.status === 'scheduled' && !row.entry_count) return row.deferred_count > 0 ? '本期顺延' : '本期无应付';
  return statusLabel[row.status];
}
const typeLabel: Record<string, string> = { first_order: '首期佣金', renewal: '续费佣金', refund_reversal: '退款冲回' };
const validMonth = (month: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(month);
const defaultMonth = () => addBusinessDateDays(businessDateKey().slice(0, 7) + '-01', -1).slice(0, 7);
const amount = (value: number, currency: string) => new Intl.NumberFormat('zh-CN', {
  style: 'currency', currency, currencyDisplay: 'code', minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(value);
const message = (error: any) => {
  const detail = error?.response?.data?.detail ?? error?.data?.detail;
  return typeof detail === 'string' ? detail : error?.message || '连接失败，请重试。';
};

async function exportStatements(month: string, rows: Statement[]) {
  const { exportCSV } = await import('@/lib/export');
  const safeText = (text: string) => /^\s*[=+@-]/.test(text) ? "'" + text : text;
  exportCSV({
    filename: '渠道月结单_' + month,
    columns: [
      { key: 'number', label: '月结单号' }, { key: 'month', label: '账期' }, { key: 'partner_name', label: '渠道' },
      { key: 'currency', label: '币种' }, { key: 'entry_count', label: '应结笔数' }, { key: 'total_amount', label: '本单金额' },
      { key: 'deferred_amount', label: '顺延金额' }, { key: 'status', label: '状态' }, { key: 'due_date', label: '结算日' },
      { key: 'payout_reference', label: '付款凭证' },
    ],
    data: rows.map(row => ({ ...row, number: row.id, partner_name: safeText(row.partner_name), status: statementStatus(row),
      payout_reference: safeText(row.payout_reference || '') })),
  });
}

function DetailEntries({ rows, currency }: { rows: StatementEntry[]; currency: string }) {
  return <ul className="statement-entries">
    {rows.map(row => <li key={row.entry_id}>
      <div><strong>{row.customer_name || '客户 #' + row.customer_id}</strong><b>{amount(row.commission_amount, currency)}</b></div>
      <p>{typeLabel[row.entry_type] || row.entry_type} · 来源月份 {row.source_month} · 收款 #{row.payment_id}
        {row.refund_id ? ' · 退款 #' + row.refund_id : ''}</p>
      <p>计佣基数 {amount(row.eligible_service_amount, currency)} · 合同比例 {Number((row.contract_rate * 100).toFixed(4))}%
        {row.due_date ? ' · 可结日 ' + row.due_date : ''}</p>
    </li>)}
  </ul>;
}

function StatementDialog({ id, canSettle, onClose, onSettled }: {
  id: number; canSettle: boolean; onClose: () => void; onSettled: () => void;
}) {
  const [detail, setDetail] = useState<StatementDetail | null>(null);
  const [reference, setReference] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [timestamp, refresh] = useState(0);
  const [reading, setReading] = useState(true);
  const [posting, setPosting] = useState(false);
  const busy = useRef(false);
  const alive = useRef(false);
  const { confirmDiscard, markSaved } = useUnsavedChanges(Boolean(reference.trim()) && detail?.status !== 'paid');

  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setReading(true); setError('');
    invokeWithAuth({ url: endpoint + '/' + id, method: 'GET', options: { signal: controller.signal } }).then(response => {
      if (controller.signal.aborted) return;
      if (response.data?.id !== id || !Array.isArray(response.data.entries) || !Array.isArray(response.data.deferred_entries)) throw new Error('月结单明细未完整返回。');
      setDetail(response.data);
      if (response.data.status === 'paid') setNotice(previous => previous ? '已从台账核实整单已结清，请核对付款凭证。' : '');
    }).catch(reason => { if (!controller.signal.aborted) setError(message(reason)); })
      .finally(() => { if (!controller.signal.aborted) setReading(false); });
    return () => controller.abort();
  }, [id, timestamp]);

  const close = () => { if (!busy.current && confirmDiscard()) onClose(); };
  const settle = async () => {
    const ref = reference.trim();
    if (!detail || detail.status !== 'ready' || !canSettle || !ref || reading || error || busy.current) return;
    busy.current = true; setPosting(true); setNotice('');
    try {
      const response = await invokeWithAuth({ url: endpoint + '/' + id + '/settle', method: 'POST', data: {
        payout_reference: ref, expected_total: detail.total_amount, expected_entry_count: detail.entry_count, revision: detail.revision,
      } });
      if (!alive.current) return;
      if (response.data?.id !== id || response.data.status !== 'paid') throw new Error('结清回执未完整返回。');
      setDetail(response.data); setReference(''); markSaved(); onSettled(); toast.success('已登记付款，整单已结清');
    } catch (reason) {
      if (!alive.current) return;
      setNotice(message(reason) + ' 请核对最新单据及付款凭证。');
      setReading(true); refresh(value => value + 1);
      onSettled();
    } finally {
      busy.current = false;
      if (alive.current) setPosting(false);
    }
  };

  return <Dialog open onOpenChange={open => { if (!open) close(); }}>
    <CrmFormDialogContent className="financial-workspace-form statement-dialog">
      <CrmFormDialogHeader><DialogTitle>月结单详情</DialogTitle></CrmFormDialogHeader>
      <CrmFormDialogBody>
        {notice && <p role="status" className="statement-note">{notice}</p>}
        {reading && <p role="status">正在读取月结单…</p>}
        {error && <div role="alert" className="statement-note">{error} <Button size="sm" variant="outline" onClick={() => refresh(value => value + 1)}>重新读取</Button></div>}
        {detail && <div className="statement-detail">
          <div className="statement-title"><div><h3>{detail.partner_name}</h3><p>{detail.month} 账期 · 单号 #{id}</p></div>
            <span className={'statement-status is-' + detail.status}>{statementStatus(detail)}</span></div>
          <dl className="statement-amounts">
            <div><dt>{detail.status === 'paid' ? '整单已结' : '本单应付'}</dt><dd>{amount(detail.total_amount, detail.currency)}</dd></div>
            <div><dt>顺延金额</dt><dd>{amount(detail.deferred_amount, detail.currency)}</dd></div>
          </dl>
          <p className="statement-dates">出单日 {detail.issue_date} · 结算日 {detail.due_date}</p>
          {detail.issues.length > 0 && <div className="statement-note"><strong>需要核对</strong><ul>{detail.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul></div>}
          {detail.status === 'paid' && <div className="statement-proof"><strong>付款凭证</strong><p>{detail.payout_reference}</p>{detail.paid_at && <small>登记于 {new Date(detail.paid_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}（北京时间）</small>}</div>}
          <details className="statement-lines" open><summary>本单明细 · {detail.entry_count} 笔</summary>
            {detail.entries.length ? <DetailEntries rows={detail.entries} currency={detail.currency} /> : <p>本期没有可结佣金。</p>}</details>
          {detail.deferred_entries.length > 0 && <details className="statement-lines"><summary>顺延明细 · {detail.deferred_count} 笔</summary>
            <DetailEntries rows={detail.deferred_entries} currency={detail.currency} /></details>}
          {canSettle && detail.status === 'ready' && <div className="statement-payout">
            <Label htmlFor="statement-reference">实际付款流水号或凭证编号</Label>
            <Input id="statement-reference" value={reference} maxLength={160} disabled={posting || reading || Boolean(error)}
              onChange={event => setReference(event.target.value)} autoComplete="off" placeholder="完成付款后填写" />
            <p>确认后，本单 {detail.entry_count} 笔佣金共用这份付款凭证。</p>
          </div>}
        </div>}
      </CrmFormDialogBody>
      <CrmFormDialogFooter>
        <Button type="button" variant="outline" disabled={posting} onClick={close}>关闭</Button>
        {canSettle && detail?.status === 'ready' && <Button type="button" onClick={() => void settle()} disabled={!reference.trim() || posting || reading || Boolean(error)}>{posting ? '正在登记…' : '登记付款并结清整单'}</Button>}
      </CrmFormDialogFooter>
    </CrmFormDialogContent>
  </Dialog>;
}

export default function CommissionStatements({ monthParam, setMonth, partners, canSettle, refreshKey, onSettled }: Props) {
  const month = validMonth(monthParam) ? monthParam : defaultMonth();
  const [partnerId, setPartnerId] = useState('all');
  const scope = month + '/' + partnerId;
  const [result, setResult] = useState<{ scope: string; value: StatementList } | null>(null);
  const [failure, setFailure] = useState<{ scope: string; message: string } | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [attempt, refresh] = useState(0);
  const list = result?.scope === scope ? result.value : null;
  const error = failure?.scope === scope ? failure.message : '';
  useEffect(() => {
    const controller = new AbortController();
    setFailure(null);
    const params = new URLSearchParams({ month });
    if (partnerId !== 'all') params.set('partner_id', partnerId);
    invokeWithAuth({ url: endpoint + '?' + params.toString(), method: 'GET', options: { signal: controller.signal } }).then(response => {
      if (controller.signal.aborted) return;
      if (response.data?.month !== month || !Array.isArray(response.data.items) || !Array.isArray(response.data.issues)) throw new Error('月结单列表未完整返回。');
      setResult({ scope, value: response.data });
    }).catch(reason => {
      if (!controller.signal.aborted) { setResult(null); setFailure({ scope, message: message(reason) }); }
    });
    return () => controller.abort();
  }, [scope, month, partnerId, attempt, refreshKey]);

  return <section className="commission-statements" aria-label="渠道月结单">
    <div className="statement-filters">
      <label><span>账期</span><Input type="month" aria-label="结算月份" value={month} onChange={event => { if (validMonth(event.target.value)) { setDetailId(null); setMonth(event.target.value); } }} /></label>
      <label><span>渠道</span><NativeSelect aria-label="结算渠道" value={partnerId} onChange={value => { setDetailId(null); setPartnerId(value); }}
        options={[{ value: 'all', label: '全部渠道' }, ...partners.filter(p => p.partner_type !== 'direct').map(p => ({ value: String(p.id), label: p.name + ' · ' + p.partner_code }))]} /></label>
      <Button variant="outline" size="sm" disabled={!list?.items.length} onClick={() => void exportStatements(month, list!.items).catch(() => toast.error('导出失败，请重试'))}>
        <Download size={15} aria-hidden="true" />导出结算 CSV
      </Button>
    </div>
    <p className="statement-calendar">每月 1 日出上月账单，15 日结算，以北京时间为准。
      {list?.schedule && <span>{list.schedule.last_completed_date
        ? '最近自动核算 ' + list.schedule.last_completed_date : '尚无自动核算完成记录'}</span>}
    </p>
    {error ? <div role="alert" className="statement-note">月结单读取失败：{error} <Button size="sm" variant="outline" onClick={() => refresh(v => v + 1)}>重试</Button></div>
      : !list ? <p role="status" className="statement-empty">正在读取月结单…</p> : <>
        {list.issues.length > 0 && <details className="statement-note"><summary>待核对事项 · {list.issues.length} 项</summary>
          <ul>{list.issues.map((issue, i) => <li key={i}>{issue.description}</li>)}</ul></details>}
        {list.items.length === 0 ? <p className="statement-empty">该账期及渠道暂无月结单。</p>
          : <div className="statement-list">
            {list.items.map(row => <button key={row.id} type="button" className="statement-row" aria-label={'查看 ' + row.partner_name + ' ' + row.currency + ' 月结单 #' + row.id} onClick={() => setDetailId(row.id)}>
              <span className="statement-identity"><strong>{row.partner_name}</strong><small>{row.month} · 单号 #{row.id}</small></span>
              <span className="statement-money"><small>{row.status === 'paid' ? '整单已结' : '本单应付'}</small><b>{amount(row.total_amount, row.currency)}</b></span>
              <span className="statement-money"><small>顺延 · {row.deferred_count} 笔</small><b>{amount(row.deferred_amount, row.currency)}</b></span>
              <span className={'statement-status is-' + row.status}>{statementStatus(row)}</span>
              <ChevronRight size={16} className="statement-chevron" aria-hidden="true" />
              {row.issues.length > 0 && <span className="statement-row-issue">{row.issues[0]}{row.issues.length > 1 ? ' · 共 ' + row.issues.length + ' 项需核对' : ''}</span>}
            </button>)}
          </div>}
      </>}
    {detailId !== null && <StatementDialog key={detailId} id={detailId} canSettle={canSettle} onClose={() => setDetailId(null)}
      onSettled={() => { refresh(v => v + 1); onSettled(); }} />}
  </section>;
}
