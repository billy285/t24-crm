import { ArrowUpRight, PhoneCall, UserRound, Users, MessagesSquare } from 'lucide-react';
import { outcomeLabels, salesDate, type LeadInsight } from '@/lib/sales-intelligence';

export function SalesLeadPulse({ stats, report, days, onCalls, loading }: {
  stats: { total: number; assigned: number; unassigned: number };
  report: { summary: { provider_calls: number; connected: number; crm_records: number; interested: number; appointments: number }; period: { start_date: string; end_date: string } } | null;
  days: number; onCalls: () => void; loading: boolean;
}) {
  const period = days === 1 ? '今日' : `近 ${days} 天`;
  return <section className="sl-pulse" aria-label="销售数据一览" aria-busy={loading}>
    <article><div><Users size={15} />线索总量<span>当前范围</span></div><strong>{loading ? '…' : stats.total}<small>家</small></strong><p>{loading ? '正在读取线索统计…' : <>已分配 <b>{stats.assigned}</b> 家 · 待分配 <b>{stats.unassigned}</b> 家</>}</p></article>
    <article className={stats.unassigned ? 'sl-pulse-attention' : ''}><div><UserRound size={15} />待分配线索<span>当前存量</span></div><strong>{loading ? '…' : stats.unassigned}<small>家</small></strong><p>{loading ? '正在读取分配情况…' : stats.unassigned ? '分配负责人后进入销售跟进' : '当前线索均已安排负责人'}</p></article>
    <button type="button" onClick={onCalls} title={report ? `${report.period.start_date} 至 ${report.period.end_date}，点击查看通话明细` : '查看通话报告'}><div><PhoneCall size={15} />真实拨打<span>{period}</span><ArrowUpRight size={14} /></div><strong>{report ? report.summary.provider_calls : '—'}<small>次</small></strong><p>{report ? <>官方接通 <b>{report.summary.connected}</b> 次{report.summary.provider_calls > 0 && <> · 接通率 <b>{Math.round(report.summary.connected / report.summary.provider_calls * 100)}%</b></>}</> : '通话报告暂不可用'}</p></button>
    <button type="button" onClick={onCalls}><div><MessagesSquare size={15} />跟进记录<span>{period}</span><ArrowUpRight size={14} /></div><strong>{report ? report.summary.crm_records : '—'}<small>条</small></strong><p>{report ? <>意向 <b>{report.summary.interested}</b> · 预约 <b>{report.summary.appointments}</b><span className="sl-record-unit"> 条结果</span></> : '跟进报告暂不可用'}</p></button>
  </section>;
}

export function LeadContactSnapshot({ insight, loading }: { insight?: LeadInsight; loading: boolean }) {
  if (!insight) return <div className="sl-row-placeholder">{loading ? '累计数据加载中…' : '累计数据暂不可用'}</div>;
  return <div className="sl-contact-snapshot">
    <div className="sl-call-numbers"><span><b>{insight.calls}</b> 拨打</span><i>／</i><span><b>{insight.connected}</b> 接通</span></div>
    <div className="sl-record-count"><b>{insight.records}</b> 条跟进{insight.manual_records > 0 && <span> · {insight.manual_records} 条未关联通话</span>}</div>
    <div className="sl-outcomes">{Object.entries(insight.outcomes).filter(([, n]) => n > 0).slice(0, 3).map(([key, count]) => <span key={key} className={key === 'interested' || key === 'appointment' ? 'positive' : ''}>{outcomeLabels[key] || key} {count}</span>)}{insight.records === 0 && <span>尚无跟进结果</span>}</div>
  </div>;
}

export function LeadProgressSnapshot({ insight, loading }: { insight?: LeadInsight; loading: boolean }) {
  if (!insight) return <span className="sl-row-placeholder">{loading ? '加载中…' : '暂不可用'}</span>;
  return <div className="sl-progress-snapshot">
    <span className={`si-badge si-${insight.potential}`}>{insight.potential_label}</span>
    {insight.first_interest_record_number ? <><strong>第 {insight.first_interest_record_number} 条跟进有意向</strong><small>{insight.first_interest_call_number ? `对应第 ${insight.first_interest_call_number} 次官方拨打` : '对应拨打次数未知'}</small></> : <small>{insight.rationale[0]}</small>}
    {insight.turned_positive && <small className="sl-positive">曾拒绝，后转为有意向</small>}
  </div>;
}

export function LeadNextStep({ insight, nextAt, lastAt, stopped, converted }: { insight?: LeadInsight; nextAt?: string; lastAt?: string; stopped: boolean; converted: boolean }) {
  const lastContact = insight?.last_contact_at || lastAt;
  return <div className="sl-next-step">
    {stopped || converted ? <strong>{converted ? '已转正式客户' : '已停止联系'}</strong> : nextAt ? <strong className={insight?.overdue ? 'sl-overdue' : ''}>{insight?.overdue && <span>逾期 · </span>}{salesDate(nextAt)}</strong> : <strong className="sl-unplanned">待安排跟进</strong>}
    {insight?.profile.next_step && <span>{insight.profile.next_step}</span>}
    <small>{lastContact ? `最近联系 ${salesDate(lastContact)}` : '尚无联系时间'}</small>
  </div>;
}
