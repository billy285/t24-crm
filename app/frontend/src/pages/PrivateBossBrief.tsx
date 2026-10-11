import type { ReactNode } from 'react';
import { ArrowUpRight, ChevronRight, CircleCheck, CreditCard, FileText, Landmark, LoaderCircle, Mail, Megaphone, Plus, Sparkles } from 'lucide-react';
import type { PrivateSourceId } from '@/lib/private-workspace-api';
import {
  PRIVATE_BOSS_PERIOD_NAMES, PRIVATE_BOSS_SOURCE_NAMES,
  bossBriefAIAction, bossBriefAIReferences, bossBriefBudget, bossBriefConclusion, bossBriefCoverageLabel, bossBriefForPeriod, bossBriefFreshnessLabel, bossBriefIssues, bossBriefIssueView, bossBriefNotice, bossBriefReadableText, bossBriefSources, bossBriefStateLabel, bossBriefTaskDraft, bossBriefTime,
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
  fundsPreview?: ReactNode;
  onPeriodChange: (period: PrivateBossPeriod) => void;
  onExplain: () => void;
  onRefresh: () => void;
  onOpenSource: (source: PrivateSourceId) => void;
  onOpenItem: (id: string) => void;
  onCreateTask: (draft: PrivateBossTaskDraft) => void;
}
const sourceIcons = { gmail: Mail, google_ads: Megaphone, stripe: CreditCard, bofa: Landmark, bofa_bank: Landmark, manual: FileText };

export default function PrivateBossBrief({ data, period, loading, error = '', busy = false, aiConfigured, aiBusy, aiNotice = '', fundsPreview, onPeriodChange, onExplain, onRefresh, onOpenSource, onOpenItem, onCreateTask }: PrivateBossBriefProps) {
  const current = bossBriefForPeriod(data, period);
  const issues = bossBriefIssues(current);
  const sources = bossBriefSources(current);
  const references = bossBriefAIReferences(current);
  const aiAction = bossBriefAIAction(current);
  const hasAI = references.length > 0;
  const configured = (aiConfigured ?? current?.capabilities?.configured) === true;
  const budget = configured ? bossBriefBudget(current) : null;
  const unavailable = !loading && current && !configured ? bossBriefNotice(current.capabilities?.code || 'not_configured') : '';
  const aiStatus = aiBusy ? '正在整理中文解读，系统简报仍可查看…' : aiNotice || (current?.ai?.state === 'ready' && !hasAI ? '中文解读缺少可追溯依据，请重新解读。' : current?.ai?.state && current.ai.state !== 'ready' ? bossBriefNotice(current.ai.code || (current.ai.state === 'pending' ? 'pending' : undefined)) : unavailable);
  const limitations = Array.isArray(current?.limitations) ? current.limitations.filter(value => typeof value === 'string' && value.trim()).slice(0, 6) : [];
  const suggestion = aiAction?.explanation || '先核对引用来源的覆盖范围，再决定下一步。';

  return <div className="pw-boss-brief">
    <header className="pw-boss-header">
      <div>{current ? <time dateTime={current.generated_at} title="北京时间">简报更新 {bossBriefTime(current.generated_at)}</time> : <span>系统简报</span>}</div>
      <div className="pw-boss-periods" aria-label="经营简报期间">{(['today', 'last7days'] as const).map(value => <button type="button" key={value} aria-pressed={period === value} disabled={busy || aiBusy} onClick={() => onPeriodChange(value)}>{PRIVATE_BOSS_PERIOD_NAMES[value]}</button>)}</div>
    </header>
    {loading ? <div className="pw-boss-loading" role="status"><LoaderCircle aria-hidden="true" />正在整理系统简报…</div> : error ? <div className="pw-boss-error" role="alert"><p>{error}</p><button type="button" className="pw-button" disabled={busy} onClick={onRefresh}>重新读取</button></div> : !current ? <div className="pw-boss-empty"><CircleCheck aria-hidden="true" /><h3>简报尚未就绪</h3><p>重新读取后查看当前期间的工作。</p></div> : <>
      <div className="pw-boss-main">
        <section className="pw-boss-system" aria-label="系统经营简报">
          <div className="pw-boss-conclusion"><span>现在先做什么</span><h3>{bossBriefConclusion(current)}</h3><p>判断来自本期已取得的记录；各来源的覆盖与时间见来源依据。</p></div>
          {issues.length > 0 && <div className="pw-boss-section-heading"><h3>优先事项</h3><span>最多显示三项</span></div>}
          {issues.length ? <div className="pw-boss-priorities">{issues.map((issue, index) => {
            const Icon = sourceIcons[issue.source_id];
            const view = bossBriefIssueView(issue, current);
            return <article key={issue.id} className="pw-boss-issue">
              <div className="pw-boss-issue-rank" aria-hidden="true">{index + 1}</div>
              <div className="pw-boss-issue-copy">
                <div className="pw-boss-issue-meta"><span><Icon aria-hidden="true" />{PRIVATE_BOSS_SOURCE_NAMES[issue.source_id]}</span><strong className={view.kind === 'verification' ? 'is-verification' : ''}>{view.kind === 'verification' ? '核实数据' : '待处理'}</strong></div>
                <h4>{view.title}</h4>
                <p className="pw-boss-reason"><span>原因</span>{view.reason}</p>
                <p className="pw-boss-next"><span>下一步</span>{view.nextAction}</p>
                <div className="pw-boss-issue-actions">
                  <button type="button" className="pw-text-button" disabled={busy || aiBusy} onClick={() => issue.item_id ? onOpenItem(issue.item_id) : onOpenSource(issue.source_id)}>查看来源<ArrowUpRight aria-hidden="true" /></button>
                  <button type="button" className="pw-text-button" disabled={busy || aiBusy} onClick={() => onCreateTask(bossBriefTaskDraft(issue))}><Plus aria-hidden="true" />加入个人事项</button>
                  <details className="pw-boss-issue-evidence"><summary>依据<ChevronRight aria-hidden="true" /></summary><p>{view.trust} · 记录时间 {bossBriefTime(issue.observed_at)}</p>{issue.summary && <p>{bossBriefReadableText(issue.summary)}</p>}</details>
                </div>
              </div>
            </article>;
          })}</div> : <p className="pw-boss-no-priorities">有新记录或补齐来源后，重新读取简报再确认。</p>}
        </section>
        {configured || hasAI || aiBusy ? <section className={`pw-boss-ai${hasAI ? ' has-explanation' : ''}`} aria-label="AI中文解读">
          <div className="pw-boss-ai-heading"><div><Sparkles aria-hidden="true" /><h3>{hasAI ? 'AI 三行解读' : '中文解读'}</h3></div><button type="button" className="pw-text-button" disabled={!configured || !current.snapshot_id || busy || aiBusy} onClick={onExplain}>{aiBusy ? '正在解读…' : hasAI ? '重新解读' : '中文解读'}</button></div>
          {hasAI && <div className="pw-boss-ai-lines">
            <p><span>判断</span>{bossBriefReadableText(current.ai!.summary, 1200)}</p>
            <div className="pw-boss-ai-action"><span>下一步</span><div><p>{bossBriefReadableText(suggestion, 800)}</p>{aiAction && <button type="button" disabled={busy || aiBusy} onClick={() => aiAction.issue.item_id ? onOpenItem(aiAction.issue.item_id) : onOpenSource(aiAction.issue.source_id)}>来源：{PRIVATE_BOSS_SOURCE_NAMES[aiAction.issue.source_id]}<ArrowUpRight aria-hidden="true" /></button>}</div></div>
            <div className="pw-boss-ai-references"><span>依据</span><div>{references.map(source => <button type="button" key={source.source_id} disabled={busy || aiBusy} onClick={() => onOpenSource(source.source_id)}>{PRIVATE_BOSS_SOURCE_NAMES[source.source_id]}<ArrowUpRight aria-hidden="true" /></button>)}</div></div>
          </div>}
          {aiStatus && <p className="pw-boss-ai-status" role="status">{aiBusy && <LoaderCircle aria-hidden="true" />}{aiStatus}</p>}
          {hasAI && <p className="pw-boss-ai-label">AI 阅读建议 · 数字与状态以系统依据为准</p>}
        </section> : <p className="pw-boss-ai-quiet" role="status"><Sparkles aria-hidden="true" />{aiStatus || '中文解读尚待接入'}</p>}
        {(limitations.length > 0 || budget) && <details className="pw-boss-limits"><summary>数据范围与依据<ChevronRight aria-hidden="true" /></summary>{limitations.map((limitation, index) => <p key={`${index}-${limitation}`}>{bossBriefReadableText(limitation)}</p>)}<p>期间：{PRIVATE_BOSS_PERIOD_NAMES[current.period]} · 北京时间</p>{budget && <p>邮件与简报共用每月 US${budget.limit} 额度；本月可用 US${budget.remaining}。</p>}</details>}
      </div>
      <aside className="pw-boss-context" aria-label="资金与来源">
        {fundsPreview && <div className="pw-boss-funds-preview">{fundsPreview}</div>}
        <section className="pw-boss-sources" aria-label="经营简报来源"><div className="pw-boss-section-heading"><h3>来源依据</h3><span>覆盖与新鲜度</span></div><div className="pw-boss-source-grid">{sources.map(source => {
          const Icon = sourceIcons[source.source_id];
          return <details className="pw-boss-source" key={source.source_id}><summary>
            <span className="pw-boss-source-icon"><Icon aria-hidden="true" /></span>
            <span className="pw-boss-source-copy"><span className="pw-boss-source-name"><strong>{PRIVATE_BOSS_SOURCE_NAMES[source.source_id]}</strong><span className={`pw-boss-source-status is-${source.data_state}`}>{bossBriefStateLabel(source)}</span></span><small>{bossBriefCoverageLabel(source)} · {bossBriefFreshnessLabel(source)}</small></span>
            <ChevronRight className="pw-boss-source-chevron" aria-hidden="true" />
          </summary><div className="pw-boss-source-body"><p className="pw-boss-source-time">最后成功同步：{bossBriefTime(source.last_sync)}（北京时间）</p><p>{source.summary || '当前来源暂无可用依据'}</p>{source.facts.length > 0 && <ul>{source.facts.map((fact, index) => <li key={`${index}-${fact}`}>{fact}</li>)}</ul>}<button type="button" className="pw-text-button" disabled={busy || aiBusy} onClick={() => onOpenSource(source.source_id)}>打开{PRIVATE_BOSS_SOURCE_NAMES[source.source_id]}<ArrowUpRight aria-hidden="true" /></button></div></details>;
        })}</div></section>
      </aside>
    </>}
  </div>;
}
