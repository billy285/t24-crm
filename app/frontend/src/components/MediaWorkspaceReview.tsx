import { useEffect, useRef, useState } from 'react';
import { Loader2, ShieldCheck, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogTitle, DialogDescription, CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { PublicationImagePreview } from '@/components/MediaPublicationImage';
import MediaPublicationPreview from '@/components/MediaPublicationPreview';
import { invokeWithAuth } from '@/lib/tokenStore';
import { mediaError, mediaErrorStatus, mediaOperationsApi, mediaRequestId, mediaUtcToLocal, verifiedMediaTask, type MediaTask } from '@/lib/media-operations-api';
import { publicationEquivalent } from '@/components/media-publication';
import { useHardNavigationBlock } from '@/lib/use-unsaved-changes';
import { verifiedReviewTask, workspacePlatformLabels, type WorkspaceRow } from '@/lib/media-workspace-api';

type ReviewItem = { row: WorkspaceRow; task: MediaTask | null; requestId: string; status: 'prepared' | 'succeeded' | 'failed' | 'unknown'; message: string };
type Props = { scope: string; contextKey: string; isOwner: boolean; rows: WorkspaceRow[]; onClose: () => void; onChanged: () => void; onOpenTask: (id: number) => void };
const uncertain = (error: unknown) => !mediaErrorStatus(error) || [408, 429].includes(mediaErrorStatus(error) || 0) || (mediaErrorStatus(error) || 0) >= 500;
const exactResult = (raw: MediaTask, frozen: MediaTask) => {
  const result = verifiedMediaTask(raw, frozen.id);
  if (result.customer_id !== frozen.customer_id || result.platform !== frozen.platform || result.title !== frozen.title || result.content !== frozen.content || (result.image_version_id || null) !== (frozen.image_version_id || null) || (result.material_id || null) !== (frozen.material_id || null) || result.due_at !== frozen.due_at || result.timezone !== frozen.timezone || !publicationEquivalent(result.publication, frozen.publication) || result.status !== 'ready' || result.revision < frozen.revision + 1) throw new Error('原审核结果与本次核对内容不一致，请保留原编号查询。');
  return result;
};
export default function MediaWorkspaceReview({ scope, contextKey, isOwner, rows, onClose, onChanged, onOpenTask }: Props) {
  const identity = `${scope}:${contextKey}:${isOwner ? 'owner' : 'staff'}`, live = useRef(identity); live.current = identity;
  const ownerRef = useRef(isOwner); ownerRef.current = isOwner;
  const [resolved, setResolved] = useState(identity), [items, setItems] = useState<ReviewItem[]>([]), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [confirmed, setConfirmed] = useState(false), [error, setError] = useState('');
  const [imageReady, setImageReady] = useState<Record<number, boolean>>({}), [unknownId, setUnknownId] = useState<string | null>(null), [retryReady, setRetryReady] = useState(false), [imageEpoch, setImageEpoch] = useState(0);
  const imageEpochRef = useRef(0);
  const itemsRef = useRef<ReviewItem[]>([]), busyRef = useRef(false), mounted = useRef(true), pending = useRef<{ index: number; body: { action: 'approve'; expected_revision: number; request_id: string } } | null>(null);
  const hold = useHardNavigationBlock(busy || !!unknownId);
  const authorized = () => mounted.current && ownerRef.current && live.current === identity;
  function replace(next: ReviewItem[]) { itemsRef.current = next; setItems(next); }
  function update(id: string, patch: Partial<ReviewItem>) { replace(itemsRef.current.map(item => item.row.id === id ? { ...item, ...patch } : item)); }
  useEffect(() => {
    mounted.current = true; busyRef.current = false; setBusy(false); const controller = new AbortController(); setResolved(identity); replace([]); setLoading(true); setConfirmed(false); setError(''); setImageReady({}); setUnknownId(null); pending.current = null;
    if (!isOwner || !rows.length || rows.length > 10 || rows.some(row => row.kind !== 'task' || !row.review_eligible)) { setError('本次只支持老板对最多10条可审核运营任务逐项核对。'); setLoading(false); return () => { mounted.current = false; controller.abort(); }; }
    void (async () => {
      const results = await Promise.allSettled(rows.map(async row => {
        const response = await invokeWithAuth({ url: `/api/v1/media-operations/${row.navigation.task_id || row.source_id}`, method: 'GET', options: { signal: controller.signal } });
        return verifiedReviewTask(response.data as MediaTask, row);
      }));
      if (!authorized() || controller.signal.aborted) return;
      replace(rows.map((row, index) => ({ row, task: results[index].status === 'fulfilled' ? (results[index] as PromiseFulfilledResult<MediaTask>).value : null, requestId: mediaRequestId(), status: results[index].status === 'fulfilled' ? 'prepared' : 'failed', message: results[index].status === 'fulfilled' ? '等待本次内部审核确认' : mediaError((results[index] as PromiseRejectedResult).reason, (results[index] as PromiseRejectedResult).reason instanceof Error ? (results[index] as PromiseRejectedResult).reason.message : '该项暂时无法核对，未提交审核。') })));
      setLoading(false);
    })();
    return () => { mounted.current = false; controller.abort(); };
    // rows are the frozen selection captured when opening this review tray.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, isOwner]);
  const prepared = items.filter(item => item.status === 'prepared' && item.task);
  const imagesVerified = prepared.every(item => !item.task?.image_version_id || imageReady[item.task.id] === true);
  function lock() { busyRef.current = true; setBusy(true); hold.lock(); }
  function unlock() { busyRef.current = false; setBusy(false); if (!pending.current) hold.release(); }
  function close() { if (busyRef.current || unknownId) return; onClose(); }
  async function sendOne(index: number, retry = false): Promise<boolean> {
    const item = itemsRef.current[index]; if (!authorized() || !item?.task || !retry && item.status !== 'prepared') return false;
    const body = retry && pending.current ? pending.current.body : { action: 'approve' as const, expected_revision: item.task.revision, request_id: item.requestId };
    pending.current = { index, body };
    try {
      const raw = await mediaOperationsApi<MediaTask>(`/${item.task.id}/transition`, 'POST', body);
      if (!authorized()) return false;
      exactResult(raw, item.task); update(item.row.id, { status: 'succeeded', message: '已确认内部审核通过 · 未发布' }); pending.current = null; setUnknownId(null); setRetryReady(false); return true;
    } catch (cause) {
      if (!authorized()) return false;
      if (uncertain(cause)) { update(item.row.id, { status: 'unknown', message: '原审核请求结果待确认；后续条目尚未提交。' }); setUnknownId(item.requestId); setConfirmed(false); setError('请重新核对原请求。服务器按原编号返回已保存的结果，系统不会自动继续后续条目。'); return false; }
      update(item.row.id, { status: 'failed', message: mediaError(cause, cause instanceof Error ? cause.message : '该项未审核通过，请重新核对。') }); pending.current = null; setUnknownId(null); setConfirmed(false); return true;
    }
  }
  async function approve() {
    if (!authorized() || busyRef.current || unknownId || !confirmed || !imagesVerified || !prepared.length) return;
    lock(); setError('');
    try { for (let index = 0; index < itemsRef.current.length; index++) { if (!authorized()) return; if (itemsRef.current[index].status === 'prepared' && !await sendOne(index)) break; } if (authorized()) { setConfirmed(false); onChanged(); } }
    finally { if (authorized()) unlock(); }
  }
  async function recover() {
    if (!authorized() || busyRef.current || !pending.current || !unknownId || !retryReady || !confirmed || !imageReadyForOriginal()) return;
    const original = pending.current;
    lock(); setError('');
    try { await sendOne(original.index, true); if (authorized() && !pending.current) onChanged(); }
    finally { if (authorized()) { setConfirmed(false); unlock(); } }
  }
  function imageReadyForOriginal() {
    const original = pending.current && itemsRef.current[pending.current.index];
    return !original?.task?.image_version_id || imageReady[original.task.id] === true;
  }
  function prepareRecovery() {
    if (!authorized() || busyRef.current || !pending.current) return;
    setRetryReady(true); setConfirmed(false); setImageReady({}); imageEpochRef.current++; setImageEpoch(imageEpochRef.current);
    setError('请重新核对冻结的正文、素材与原请求编号。确认后系统仅重送同一个审核请求；已完成的请求由服务器返回原结果，不会创建新请求。');
  }
  const visible = resolved === identity && isOwner;
  return <Dialog open onOpenChange={value => { if (!value) close(); }}><CrmFormDialogContent className="mw-review-dialog"><CrmFormDialogHeader><DialogTitle>核对所选内容 · 仅内部审核</DialogTitle><DialogDescription>逐项核对客户、平台、实际正文、固定配图和时间。审核通过不会发布内容，也不会创建或启用排期。</DialogDescription></CrmFormDialogHeader><CrmFormDialogBody>
    {!visible ? <p role="status">正在确认当前审核范围…</p> : loading ? <p role="status"><Loader2 className="animate-spin"/>正在并行读取本次所选任务的实际版本…</p> : <><p className="mw-caption">本次 {items.length} 条 · {new Set(items.map(item => item.row.customer_id)).size} 家商家。失败或无法核对的条目不会提交。</p>{items.map(item => <article className="mw-review-card" key={item.row.id}><header><strong>{item.row.customer_name} · {workspacePlatformLabels[item.row.platform] || item.row.platform}</strong><span className={`mw-status ${item.status === 'succeeded' ? 'success' : item.status === 'failed' ? 'danger' : ''}`}>{item.message}</span></header><p className="mw-caption">{item.row.account_label || (item.row.binding_id ? `已关联平台账号 #${item.row.binding_id}` : '平台账号尚未在此清单核对 · 本次只审核客户内容')} · 原任务 #{item.row.source_id}{item.task ? ` · 版本 ${item.task.revision}` : ''}</p>{item.task ? <><h3>{item.task.title}</h3><p className="mw-full-copy">{item.task.content || '此任务未填写正文，请逐项核对任务要求。'}</p>{item.task.publication_image && <PublicationImagePreview image={item.task.publication_image} key={`${item.task.id}:${imageEpoch}`} scope={`${identity}:${item.task.id}:${item.task.revision}:${imageEpoch}`} onStateChange={value => { if (!authorized() || imageEpoch !== imageEpochRef.current) return; setImageReady(previous => ({ ...previous, [item.task!.id]: value === 'ready' })); if (value !== 'ready') setConfirmed(false); }}/>}<p className="mw-caption">任务准备截止：{mediaUtcToLocal(item.task.due_at, item.task.timezone).replace('T', ' ')} · {item.task.timezone}<br/>北京时间：{mediaUtcToLocal(item.task.due_at, 'Asia/Shanghai').replace('T', ' ')}。这是准备目标，尚未安排公开发布时间。</p>{item.task.publication && <MediaPublicationPreview publication={item.task.publication} timezone={item.task.timezone}/>}</> : <Button variant="outline" disabled={busy || !!unknownId} onClick={() => { close(); onOpenTask(item.row.navigation.task_id || Number(item.row.source_id)); }}>打开原任务核对</Button>}{item.status === 'unknown' && <p className="mw-caption">原请求编号：{item.requestId}</p>}</article>)}</>}
    {error && <p className="mw-alert" role="alert"><AlertCircle/>{error}</p>}{visible && !loading && (prepared.length > 0 || retryReady) && <label className="mw-check"><input type="checkbox" checked={confirmed} disabled={busy || !imagesVerified || !!unknownId && !imageReadyForOriginal()} onChange={event => setConfirmed(event.target.checked)}/><span>{unknownId ? '我已重新核对原商家、内容和原请求编号，确认只沿用同一个审核请求。' : `我已逐项核对本次就绪的 ${prepared.length} 条内容、配图和客户归属，确认仅进行内部审核；失败项跳过，不发布、不排期。`}</span></label>}
  </CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" disabled={busy || !!unknownId} onClick={close}>关闭</Button>{unknownId ? <><Button variant="outline" disabled={busy} onClick={prepareRecovery}>重新核对原审核请求</Button>{retryReady && <Button disabled={busy || !confirmed || !imageReadyForOriginal()} onClick={() => void recover()}>沿用原编号确认结果</Button>}</> : <Button aria-label={busy ? '正在逐项审核…' : `审核通过就绪的 ${prepared.length} 条（不发布）`} disabled={!visible || loading || busy || !confirmed || !imagesVerified || !prepared.length} onClick={() => void approve()}><ShieldCheck/><span className="hidden sm:inline">{busy ? '正在逐项审核…' : `审核通过就绪的 ${prepared.length} 条（不发布）`}</span><span className="sm:hidden">{busy ? '审核中…' : `仅审核 ${prepared.length} 条`}</span></Button>}</CrmFormDialogFooter></CrmFormDialogContent></Dialog>;
}
