import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Loader2, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { googleBusinessApi, type GbpReview } from '@/lib/google-business-api';
import { googleReviewNeedsOwner, readGbpAiDrafts, readGbpAiStatus, verifiedAiDraft, verifiedAiStatus, type GbpAiDraft, type GbpAiStatus } from '@/lib/google-business-ai-api';
import { mediaError, mediaRequestId } from '@/lib/media-operations-api';

const riskLabels: Record<string, string> = { food_safety: '食品安全或过敏投诉', discrimination: '歧视或骚扰投诉', legal: '法律争议', compensation: '退款或补偿承诺', privacy: '个人隐私信息', owner_review: '需要老板复核' };
type Props = { scope: string; bindingId: number; customerName: string; review: GbpReview; reply: string; isOwner: boolean; onReply: (value: string) => void; onApproval: (draft: GbpAiDraft | null) => void; onBusy: (value: boolean) => void };
export default function GoogleReviewAssistant({ scope, bindingId, customerName, review, reply, isOwner, onReply, onApproval, onBusy }: Props) {
  const [status, setStatus] = useState<GbpAiStatus | null>(null);
  const [drafts, setDrafts] = useState<GbpAiDraft[]>([]);
  const [selected, setSelected] = useState<GbpAiDraft | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [saved, setSaved] = useState(false);
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const busyRef = useRef(false), sequence = useRef(0), generateRequest = useRef('');
  const sensitive = !!review.requires_owner_review || googleReviewNeedsOwner(review.comment, reply) || !!selected?.sensitive;
  const selectedCurrent = selected && selected.reply === reply && selected.review_version === review.version;
  const selectedApproved = !!selectedCurrent && selected.approved;
  const load = useCallback(async () => {
    const seq = ++sequence.current, identity = scope;
    setLoading(true); setError('');
    const [ai, history] = await Promise.allSettled([readGbpAiStatus(bindingId), readGbpAiDrafts(bindingId, review.name)]);
    if (seq !== sequence.current || scopeRef.current !== identity) return;
    if (ai.status === 'fulfilled') setStatus(ai.value); else { setStatus(null); setError(mediaError(ai.reason, 'AI 配置暂时无法读取，仍可手动编辑回复。')); }
    if (history.status === 'fulfilled') setDrafts(history.value); else setDrafts([]);
    setLoading(false);
  }, [bindingId, review.name, scope]);
  useEffect(() => { busyRef.current = false; setBusy(false); onBusy(false); setSelected(null); setDrafts([]); setConsent(false); setSaved(false); generateRequest.current = ''; void load(); return () => { sequence.current++; }; }, [load]);
  useEffect(() => () => { onBusy(false); }, [onBusy]);
  function choose(draft: GbpAiDraft) { setSelected(draft); onReply(draft.reply); onApproval(draft); setSaved(false); }
  async function perform(kind: 'consent' | 'generate' | 'save' | 'approve') {
    if (busyRef.current) return;
    if (kind === 'consent' && (!isOwner || !consent || !status?.enabled)) return;
    if (kind === 'generate' && (!status?.enabled || !status.owner_consented)) return;
    if ((kind === 'save' || kind === 'approve') && !reply.trim()) { setError('先填写要审核的回复内容。'); return; }
    if (kind === 'approve' && (!isOwner || !selected)) return;
    const identity = scope; busyRef.current = true; setBusy(true); onBusy(true); setError(''); setSaved(false);
    try {
      if (kind === 'consent') {
        await googleBusinessApi('/ai/consent', 'POST', { confirmed: true, runtime_fingerprint: status!.runtime_fingerprint, enabled: true });
        if (scopeRef.current !== identity) return;
        setStatus(verifiedAiStatus(await googleBusinessApi<GbpAiStatus>('/ai/status'))); setConsent(false); return;
      }
      let result: GbpAiDraft;
      if (kind === 'generate') {
        generateRequest.current ||= mediaRequestId();
        result = verifiedAiDraft(await googleBusinessApi<GbpAiDraft>(`/bindings/${bindingId}/ai-reply-drafts`, 'POST', { confirmed: true, request_id: generateRequest.current, review_name: review.name, expected_version: review.version, runtime_fingerprint: status!.runtime_fingerprint }));
      } else if (kind === 'save') {
        result = verifiedAiDraft(await googleBusinessApi<GbpAiDraft>(`/bindings/${bindingId}/reply-drafts`, 'POST', { confirmed: true, request_id: mediaRequestId(), review_name: review.name, expected_version: review.version, reply: reply.trim() }));
      } else {
        result = verifiedAiDraft(await googleBusinessApi<GbpAiDraft>(`/bindings/${bindingId}/reply-drafts/${selected!.id}/approve`, 'POST', { confirmed: true, expected_version: review.version, reply: reply.trim() }));
      }
      if (scopeRef.current !== identity) return;
      if (result.review_version !== review.version) throw new Error('评论已有更新，请重新读取评论后处理。');
      setDrafts(rows => [result, ...rows.filter(row => row.id !== result.id)]); setSelected(result); onReply(result.reply); onApproval(result); setSaved(kind === 'save'); generateRequest.current = '';
    } catch (cause) { if (scopeRef.current === identity) setError(mediaError(cause, kind === 'generate' ? '暂未取得本次 AI 草稿。可读取已存草稿，或以同一编号重新获取。' : '操作暂时未确认，请读取已存草稿后核对。')); }
    finally { if (scopeRef.current === identity) { busyRef.current = false; setBusy(false); onBusy(false); } }
  }
  return <section aria-label={`${customerName}的评论理解与回复草稿`} className="gpm-ai-section">
    {error && <div className="gpm-alert" role="alert"><AlertCircle aria-hidden="true"/><div>{error}</div></div>}
    <div className="gpm-ai-tools"><p>{loading ? '正在读取 AI 和当前评论的草稿状态…' : status?.enabled ? `AI 仅接收去除联系方式后的本条公开评论与评分，在 ${status.destination_host || status.provider} 生成建议；生成后仍需人工确认发送。` : 'AI 尚未配置或暂不可用，可继续手动编辑并保存回复草稿。'}</p><Button variant="outline" disabled={loading || busy || !status?.enabled || !status.owner_consented} onClick={() => void perform('generate')}>{busy ? <Loader2 className="animate-spin" aria-hidden="true"/> : <Sparkles aria-hidden="true"/>}{generateRequest.current ? '获取本次 AI 草稿' : '生成针对性回复'}</Button></div>
    {!loading && status?.enabled && !status.owner_consented && (isOwner ? <div className="gpm-ai-analysis"><p><ShieldCheck aria-hidden="true" style={{ width: 15, height: 15, display: 'inline', marginRight: 5 }}/><strong>先确认 AI 数据使用范围</strong></p><p>发送去除联系方式后的本条公开评论与评分至 {status.destination_host || status.provider}，使用 {status.model}。不包含客户财务、私人资料或 Google 凭据。此确认只启用拟稿，不会自动公开回复。</p><label className="gpm-checkbox"><input type="checkbox" checked={consent} disabled={busy} onChange={event => setConsent(event.target.checked)}/>我确认上述 AI 服务和数据范围，允许生成评论回复草稿。</label><Button variant="outline" disabled={!consent || busy} onClick={() => void perform('consent')}>确认启用 AI 拟稿</Button></div> : <p className="gpm-ai-disclaimer">需要老板先确认 AI 服务的数据使用范围。</p>)}
    {(drafts.length > 0 || !loading) && <div className="gpm-draft-tools"><NativeSelect aria-label="选择当前评论的回复草稿" value={selected ? String(selected.id) : ''} disabled={busy} onChange={value => { const draft = drafts.find(row => String(row.id) === value); if (draft) choose(draft); }} options={[{ value: '', label: drafts.length ? `已存草稿 ${drafts.length} 条，选择后载入` : '本条评论暂无已存草稿' }, ...drafts.map(row => ({ value: String(row.id), label: `草稿 ${row.id.slice(0, 8)} · ${row.approved ? '已批准' : row.requires_owner_approval ? '待老板审核' : '可编辑'}${row.actor_name ? ` · ${row.actor_name}` : ''}` }))]}/><Button variant="ghost" aria-label="刷新当前评论草稿" disabled={busy || loading} onClick={() => void load()}><RefreshCw aria-hidden="true"/></Button></div>}
    {selected && (selected.summary || selected.issues?.length || selected.risk_flags?.length) ? <div className="gpm-ai-analysis">{selected.summary && <p><strong>评论理解：</strong>{selected.summary}</p>}{!!selected.issues?.length && <p><strong>需要回应：</strong>{selected.issues.join('；')}</p>}{!!selected.risk_flags?.length && <p className="warning"><strong>需核实：</strong>{selected.risk_flags.map(flag => riskLabels[flag] || '需要人工核对').join('；')}</p>}</div> : null}
    {sensitive && <div className="gpm-ai-analysis"><p className={selectedApproved ? '' : 'warning'}><strong>{selectedApproved ? '当前文本已获老板批准' : isOwner ? '请核对敏感投诉和回复事实' : '这条回复需要老板核对'}</strong>。{isOwner ? '你核对正文后可直接确认公开回复，也可批准这份草稿交运营发送。' : '修改正文后需重新核对。'}</p>{isOwner ? <Button variant="outline" disabled={busy || !reply.trim()} onClick={() => void perform(selected ? 'approve' : 'save')}>{busy && <Loader2 className="animate-spin" aria-hidden="true"/>}{selected ? '批准当前回复文本' : '保存当前回复供核对'}</Button> : <Button variant="outline" disabled={busy || !reply.trim() || selectedApproved} onClick={() => void perform('save')}>保存并交老板复核</Button>}</div>}
    {saved && <p className="gpm-ai-disclaimer"><CheckCircle2 aria-hidden="true" style={{ width: 13, height: 13, display: 'inline', marginRight: 5 }}/>当前文本已保存，老板可在同一评论的草稿列表中核对。</p>}
    <p className="gpm-ai-disclaimer">请核实回复中的事实、联系方式和补偿承诺。AI 草稿可修改；保存草稿不会向 Google 公开内容。</p>
  </section>;
}
