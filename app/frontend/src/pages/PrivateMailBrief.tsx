import { useState } from 'react';
import { ChevronRight, LoaderCircle, Sparkles } from 'lucide-react';
import { type PrivateItem } from '@/lib/private-workspace-api';

export default function PrivateMailBrief({ item, busy, configured, loading, notice, onOrganize }: {
  item: PrivateItem;
  busy: boolean;
  configured: boolean;
  loading: boolean;
  notice: string;
  onOrganize: () => void;
}) {
  const [view, setView] = useState<'brief' | 'original'>('brief');
  const brief = item.mail_brief;
  const ready = brief?.state === 'ready';
  const original = typeof brief?.original_body === 'string' ? brief.original_body : '';
  const points = Array.isArray(brief?.key_points) ? brief.key_points.filter(point => typeof point === 'string' && point.trim()).slice(0, 4) : [];
  const evidence = Array.isArray(brief?.source_evidence) ? brief.source_evidence.filter(value => typeof value === 'string' && value.trim()).slice(0, 4) : [];
  const preview = brief?.source_scope === 'preview';
  const status = busy ? '正在读取邮件并整理中文重点，原文仍可查看…' : loading ? '正在检查智能整理服务…' : notice;

  return <section className="pw-mail-brief" aria-label="智能邮件整理">
    <div className="pw-mail-brief-toolbar">
      <span><Sparkles aria-hidden="true" />中文工作简报</span>
      <div className="pw-mail-language" aria-label="邮件阅读方式"><button type="button" aria-pressed={view === 'brief'} onClick={() => setView('brief')}>重点</button><button type="button" aria-pressed={view === 'original'} onClick={() => setView('original')}>原文</button></div>
    </div>
    {view === 'brief' && ready ? <>
      <div className="pw-mail-brief-headline"><span>发生了什么{preview && ' · 依据摘要'}</span><p>{brief.summary_zh || '尚未提取到明确内容，请结合原文查看。'}</p></div>
      {points.length > 0 && <ul className="pw-mail-key-points">{points.map((point, index) => <li key={`${index}-${point}`}>{point}</li>)}</ul>}
      <div className="pw-mail-next-action"><span>{brief.needs_action === false ? '了解即可' : '建议下一步'}</span><p>{brief.next_action || '暂未提取到明确行动，请核对原文。'}</p><div className="pw-mail-brief-deadline"><span>时间</span><strong>{brief.deadline?.text || '待确认'}</strong>{brief.deadline?.text && !brief.deadline.confirmed && <small>待确认</small>}</div></div>
      {brief.relevance && <div className="pw-mail-brief-relevance"><span>与你有关</span><p>{brief.relevance}</p></div>}
      {(evidence.length > 0 || brief.deadline?.evidence) && <details className="pw-mail-brief-evidence"><summary>查看摘要依据<ChevronRight aria-hidden="true" /></summary>{evidence.map((value, index) => <p key={`${index}-${value}`}>{value}</p>)}{brief.deadline?.evidence && !evidence.includes(brief.deadline.evidence) && <p>{brief.deadline.evidence}</p>}</details>}
      <p className="pw-mail-brief-note">AI 阅读整理{preview ? ' · 仅依据标题与摘要' : ' · 依据已读取正文'}{brief.truncated && ' · 正文未完整读取'}{brief.evidence_limited && ' · 部分依据不足'}。建议请结合原文核对。</p>
    </> : <div className="pw-mail-brief-original">
      <h3>{item.title}</h3>
      <span>{original ? '邮件原文' : '原始摘要'}{original && brief?.truncated && ' · 部分正文'}</span>
      <p>{original || item.summary || '邮件没有可展示摘要，可在 Gmail 查看完整内容。'}</p>
      {ready && !original && <p className="pw-mail-brief-note">当前为原始摘要，完整邮件可在 Gmail 查看。</p>}
    </div>}
    {status && <p className="pw-mail-brief-status" role="status">{(busy || loading) && <LoaderCircle aria-hidden="true" />}{status}</p>}
    {(!ready || (!original && !preview)) && <button type="button" className="pw-button pw-button-primary pw-mail-organize" disabled={busy || loading || !configured} onClick={onOrganize}><Sparkles aria-hidden="true" />{busy ? '正在整理…' : ready ? '查看原文正文' : brief?.state === 'failed' ? '重新整理这封邮件' : '整理这封邮件'}</button>}
  </section>;
}
