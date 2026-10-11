import { ArrowUpRight, ChevronRight, CircleCheck, CreditCard, FileText, Landmark, LoaderCircle, Mail, Megaphone, Plus, Sparkles } from 'lucide-react';
import type { PrivateSourceId } from '@/lib/private-workspace-api';
import {
  PRIVATE_BOSS_PERIOD_NAMES, PRIVATE_BOSS_SOURCE_NAMES,
  bossBriefAINotes, bossBriefBudget, bossBriefForPeriod, bossBriefIssues, bossBriefNotice, bossBriefSources, bossBriefStateLabel, bossBriefTaskDraft, bossBriefTime,
  type PrivateBossBriefData, type PrivateBossPeriod, type PrivateBossTaskDraft,
} from '@/lib/private-boss-brief';
import './private-boss-brief.css';

export interface PrivateBossBriefProps {
  data: PrivateBossBriefData | null;
  period: PrivateBossPeriod;
  loading: boolean;
  error?: string;
  busy?: boolean;
  aiConfigured?: boolean;
  aiBusy: boolean;
  aiNotice?: string;
  onPeriodChange: (period: PrivateBossPeriod) => void;
  onExplain: () => void;
  onRefresh: () => void;
  onOpenSource: (source: PrivateSourceId) => void;
  onOpenItem: (id: string) => void;
  onCreateTask: (draft: PrivateBossTaskDraft) => void;
}
const sourceIcons = { gmail: Mail, google_ads: Megaphone, stripe: CreditCard, bofa: Landmark, manual: FileText };

export default function PrivateBossBrief({ data, period, loading, error = '', busy = false, aiConfigured, aiBusy, aiNotice = '', onPeriodChange, onExplain, onRefresh, onOpenSource, onOpenItem, onCreateTask }: PrivateBossBriefProps) {
  const current = bossBriefForPeriod(data, period);
  const issues = bossBriefIssues(current);
  const sources = bossBriefSources(current);
  const notes = bossBriefAINotes(current);
  const hasAI = current?.ai?.state === 'ready' && typeof current.ai.summary === 'string' && Boolean(current.ai.summary.trim());
  const configured = (aiConfigured ?? current?.capabilities?.configured) === true;
  const budget = configured ? bossBriefBudget(current) : null;
  const unavailable = !loading && current && !configured ? bossBriefNotice(current.capabilities?.code || 'not_configured') : '';
  const aiStatus = aiBusy ? '正在整理中文解读，系统简报仍可查看…' : aiNotice || (current?.ai?.state && current.ai.state !== 'ready' ? bossBriefNotice(current.ai.code || (current.ai.state === 'pending' ? 'pending' : undefined)) : unavailable);
  const limitations = Array.isArray(current?.limitations) ? current.limitations.filter(value => typeof value === 'string' && value.trim()).slice(0, 6) : [];

  return <div className="pw-boss-brief">
    <header className="pw-boss-header"><div>{current ? <time dateTime={current.generated_at} title="北京时间">更新 {bossBriefTime(current.generated_at)}</time> : <span>系统简报</span>}</div><div className="pw-boss-periods" aria-label="经营简报期间">{(['today', 'last7days'] as const).map(value => <button type="button" key={value} aria-pressed={period === value} disabled={busy || aiBusy} onClick={() => onPeriodChange(value)}>{PRIVATE_BOSS_PERIOD_NAMES[value]}</button>)}</div></header>
    {loading ? <div className="pw-boss-loading" role="status"><LoaderCircle aria-hidden="true" />正在整理系统简报…</div> : error ? <div className="pw-boss-error" role="alert"><p>{error}</p><button type="button" className="pw-button" disabled={busy} onClick={onRefresh}>重新读取</button></div> : !current ? <div className="pw-boss-empty"><CircleCheck aria-hidden="true" /><h3>简报尚未就绪</h3><p>重新读取后查看当前期间的工作。</p></div> : <>
      <section className="pw-boss-system" aria-label="系统经营简报"><div className="pw-boss-section-heading"><h3>{issues.length ? '先处理最重要的事' : '当前没有已确认的优先事项'}</h3><span>系统简报</span></div>{issues.length ? <div className="pw-boss-priorities">{issues.map((issue, index) => {
        const Icon = sourceIcons[issue.source_id];
        return <article key={issue.id} className="pw-boss-issue"><div className="pw-boss-issue-rank" aria-hidden="true">{String(index + 1).padStart(2, '0')}</div><div className="pw-boss-issue-copy"><div className="pw-boss-issue-meta"><span><Icon aria-hidden="true" />{PRIVATE_BOSS_SOURCE_NAMES[issue.source_id]}</span><time>{bossBriefTime(issue.observed_at)}</time>{issue.priority === 'urgent' && <strong>优先处理</strong>}</div><h4>{issue.title}</h4><p className="pw-boss-next"><span>下一步</span>{issue.next_action || '查看原始来源后再决定。'}</p><div className="pw-boss-issue-actions"><button type="button" className="pw-text-button" disabled={busy || aiBusy} onClick={() => issue.item_id ? onOpenItem(issue.item_id) : onOpenSource(issue.source_id)}>查看来源<ArrowUpRight aria-hidden="true" /></button><button type="button" className="pw-text-button" disabled={busy || aiBusy} onClick={() => onCreateTask(bossBriefTaskDraft(issue))}><Plus aria-hidden="true" />加入个人事项</button>{issue.summary && <details className="pw-boss-issue-evidence"><summary>依据<ChevronRight aria-hidden="true" /></summary><p>{issue.summary}</p></details>}</div></div></article>;
      })}</div> : <div className="pw-boss-empty"><CircleCheck aria-hidden="true" /><p>查看下方来源状态，缺少依据的工作仍需核实。</p></div>}</section>
      <section className="pw-boss-ai" aria-label="AI中文解读"><div className="pw-boss-ai-heading"><div><Sparkles aria-hidden="true" /><h3>AI 中文解读</h3></div><button type="button" className="pw-button" disabled={!configured || !current.snapshot_id || loading || busy || aiBusy} onClick={onExplain}><Sparkles aria-hidden="true" />{aiBusy ? '正在解读…' : hasAI ? '重新解读' : '中文解读'}</button></div>{hasAI && <><p className="pw-boss-ai-summary">{current.ai!.summary}</p>{notes.length > 0 && <details className="pw-boss-ai-notes"><summary>展开建议<ChevronRight aria-hidden="true" /></summary>{notes.map(({ issue, explanation }) => <div key={issue.id}><h4>{issue.title}</h4><p>{explanation}</p></div>)}</details>}<p className="pw-boss-ai-label">AI 阅读建议 · 数字与状态以系统依据为准</p></>}{aiStatus && <p className="pw-boss-ai-status" role="status">{aiBusy && <LoaderCircle aria-hidden="true" />}{aiStatus}</p>}</section>
      <section className="pw-boss-sources" aria-label="经营简报来源"><div className="pw-boss-section-heading"><h3>按来源查看</h3><span>展开明细</span></div><div className="pw-boss-source-grid">{sources.map(source => {
        const Icon = sourceIcons[source.source_id];
        return <details className="pw-boss-source" key={source.source_id}><summary><span className="pw-boss-source-icon"><Icon aria-hidden="true" /></span><span className="pw-boss-source-copy"><strong>{PRIVATE_BOSS_SOURCE_NAMES[source.source_id]}</strong><small>{source.summary || '当前来源暂无可用依据'}</small></span><span className={`pw-boss-source-status is-${source.data_state}`}>{source.source_id === 'bofa' && ['ready', 'partial'].includes(source.data_state) && source.status === 'connected' ? '待核实' : bossBriefStateLabel(source)}</span><ChevronRight className="pw-boss-source-chevron" aria-hidden="true" /></summary><div className="pw-boss-source-body"><p className="pw-boss-source-time">最后成功同步：{bossBriefTime(source.last_sync)}（北京时间）</p>{source.summary && <p>{source.summary}</p>}{source.facts.length > 0 && <ul>{source.facts.map((fact, index) => <li key={`${index}-${fact}`}>{fact}</li>)}</ul>}<button type="button" className="pw-text-button" disabled={busy || aiBusy} onClick={() => onOpenSource(source.source_id)}>打开{PRIVATE_BOSS_SOURCE_NAMES[source.source_id]}<ArrowUpRight aria-hidden="true" /></button></div></details>;
      })}</div></section>
      {(limitations.length > 0 || budget) && <details className="pw-boss-limits"><summary>数据范围与依据<ChevronRight aria-hidden="true" /></summary>{limitations.map((limitation, index) => <p key={`${index}-${limitation}`}>{limitation}</p>)}<p>期间：{PRIVATE_BOSS_PERIOD_NAMES[current.period]} · 北京时间</p>{budget && <p>邮件与简报共用每月 US${budget.limit} 额度；本月可用 US${budget.remaining}。</p>}</details>}
    </>}
  </div>;
}
