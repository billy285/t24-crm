import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Download, FileUp, History, RefreshCw, Undo2 } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getToken, invokeWithAuth, refreshToken } from '@/lib/tokenStore';
import { formatPhoneNumber } from '@/lib/phone-format';

const headers = ['商家名称', '商家电话', '商家位置', '地区', '来源'];
const statusNames: Record<string, string> = { preview: '待确认', committed: '已入池', reverted: '已撤销', pending: '待核对', no_phone: '电话待补齐', duplicate: '重复隔离', existing_customer: '正式客户隔离', closed: '停业隔离', error: '不导入' };
type ImportRow = { row: number; business_name: string; phone: string; phone_country?: string; normalized_phone?: string; status: string; reason: string; warnings: string[]; raw: Record<string, string>; merchant_id?: number };
type ImportBatch = { id: string; filename: string; status: string; row_count: number; created_at: string; duplicate_upload?: boolean; summary: { pending: number; isolated: number; errors: number; importable: number }; rows?: ImportRow[] };

function errorMessage(error: unknown): string {
  const e = error as { data?: { detail?: unknown }; response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e?.data?.detail || e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String(detail.message);
  return e?.message || '导入操作未完成，请重试';
}

async function authenticatedFetch(url: string, options: RequestInit = {}) {
  const run = (token: string) => fetch(url, { ...options, credentials: 'same-origin', headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  let response = await run(getToken());
  if (response.status === 401) {
    const token = await refreshToken();
    if (token) response = await run(token);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || '文件操作失败，请重试');
  }
  return response;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  URL.revokeObjectURL(url);
}

export default function MerchantImportDialog({ open, onOpenChange, onImported }: { open: boolean; onOpenChange: (open: boolean) => void; onImported: () => void | Promise<void> }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [history, setHistory] = useState<ImportBatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState(false);
  const [visibleCount, setVisibleCount] = useState(30);
  const [rowFilter, setRowFilter] = useState('all');

  const loadHistory = async () => {
    try {
      const response = await invokeWithAuth({ url: '/api/v1/merchant-imports?limit=10', method: 'GET' });
      setHistory(Array.isArray(response.data?.items) ? response.data.items : []);
      setHistoryError(false);
    } catch { setHistoryError(true); }
  };
  useEffect(() => { if (open) void loadHistory(); }, [open]);

  const showBatch = (value: ImportBatch) => { setBatch(value); setVisibleCount(30); setRowFilter('all'); };
  const preview = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || busy) return;
    if (!/\.(csv|xlsx)$/i.test(file.name)) { setError('请上传 CSV 或 Excel（.xlsx）文件'); return; }
    if (file.size > 10 * 1024 * 1024) { setError('文件超过 10MB，请拆分后上传'); return; }
    setBusy(true); setError(''); setBatch(null);
    try {
      const data = new FormData(); data.append('file', file);
      const response = await authenticatedFetch('/api/v1/merchant-imports/preview', { method: 'POST', body: data });
      showBatch(await response.json());
      await loadHistory();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const openBatch = async (id: string) => {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const response = await invokeWithAuth({ url: `/api/v1/merchant-imports/${id}`, method: 'GET' });
      showBatch(response.data);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const perform = async (action: 'confirm' | 'revert') => {
    if (!batch || busy) return;
    if (action === 'revert' && !window.confirm('撤销此导入批次？仅未修改、未分析、未转线索且没有后续关联的记录可撤销；有冲突时整批不会变动。')) return;
    setBusy(true); setError('');
    try {
      const response = await invokeWithAuth({ url: `/api/v1/merchant-imports/${batch.id}/${action}`, method: 'POST' });
      showBatch(response.data);
      toast.success(action === 'confirm' ? '批次已入池，请继续核对商家资料' : '批次已撤销，原导入结果仍可追溯');
      await Promise.all([loadHistory(), onImported()]);
    } catch (e) {
      setError(errorMessage(e));
      // A lost POST response can still be a successful commit. Read its receipt;
      // retrying confirmation is also idempotent on the same batch ID.
      try {
        const receipt = await invokeWithAuth({ url: `/api/v1/merchant-imports/${batch.id}`, method: 'GET' });
        showBatch(receipt.data);
        if ((action === 'confirm' && receipt.data.status === 'committed') || (action === 'revert' && receipt.data.status === 'reverted')) {
          setError(''); toast.success('已读取服务器处理结果'); await Promise.all([loadHistory(), onImported()]);
        }
      } catch { /* Keep the failed action and explicit retry visible. */ }
    } finally { setBusy(false); }
  };
  const downloadIssues = async () => {
    if (!batch) return;
    try {
      const response = await authenticatedFetch(`/api/v1/merchant-imports/${batch.id}/errors.csv`);
      downloadBlob(await response.blob(), `商家导入问题行-${batch.id}.csv`);
    } catch (e) { setError(errorMessage(e)); }
  };
  const rows = (batch?.rows || []).filter(row => rowFilter === 'all' || (rowFilter === 'error' ? row.status === 'error' : row.status !== 'pending' && row.status !== 'error'));
  const previewing = batch?.status === 'preview';

  return <Dialog open={open} onOpenChange={value => !busy && onOpenChange(value)}>
    <DialogContent className="mi-import-dialog max-h-[90dvh] max-w-4xl overflow-y-auto">
      <DialogHeader><DialogTitle>按固定模板导入商家</DialogTitle></DialogHeader>
      <div className="space-y-5">
        <ol aria-label="商家导入步骤" className="grid grid-cols-3 gap-2 text-sm">
          {['选择文件', '预检确认', '入池结果'].map((label, index) => <li key={label} className={`rounded-lg border px-3 py-2 ${index === (!batch ? 0 : previewing ? 1 : 2) ? 'border-blue-200 bg-blue-50 font-semibold text-blue-800' : 'border-slate-200 text-slate-500'}`}>{index + 1}. {label}</li>)}
        </ol>
        <section className="rounded-xl border border-slate-200 p-4">
          <p className="font-semibold text-slate-900">固定五列，不改变原名单格式</p>
          <p className="mt-1 text-sm text-slate-600">商家名称、商家电话、商家位置、地区、来源</p>
          <p className="mt-2 text-xs leading-5 text-slate-500">CSV 或 .xlsx，每次最多 2000 条、10MB。地区填写“城市, 州/省, 国家”，例如 Los Angeles, CA, US；国家不明确时保留待核对。号码与原始资料都会保留。</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy} onClick={() => downloadBlob(new Blob([`\uFEFF${headers.join(',')}\r\n`], { type: 'text/csv;charset=utf-8' }), 'T24商家导入固定模板.csv')}><Download className="mr-2 h-4 w-4" />下载固定模板</Button>
            <input ref={fileRef} className="hidden" type="file" accept=".csv,.xlsx" aria-label="商家导入文件" onChange={preview} disabled={busy} />
            <Button disabled={busy} onClick={() => fileRef.current?.click()}><FileUp className="mr-2 h-4 w-4" />{busy ? '正在处理…' : batch ? '选择另一个文件' : '选择文件并预检'}</Button>
          </div>
          {!batch && <p className="mt-3 text-xs text-blue-700">预检只保存导入草稿，确认前不会写入商家池或分配销售。</p>}
        </section>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
        {batch && <section aria-label="商家导入批次结果" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><div className="min-w-0"><p className="break-words font-semibold text-slate-900">{batch.filename}</p><p className="mt-1 break-all text-xs text-slate-500">批次 {batch.id}</p></div><Badge>{statusNames[batch.status] || '处理中'}</Badge></div>
          {batch.duplicate_upload && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">这份文件已有导入批次，已打开原结果，避免重复入池。</div>}
          <div className="grid grid-cols-3 gap-2">{[['待核对', batch.summary.pending], ['隔离待处理', batch.summary.isolated], ['格式错误不导入', batch.summary.errors]].map(([label, count]) => <div key={label} className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold text-slate-900">{count}</p></div>)}</div>
          <p className="text-sm leading-6 text-slate-600">{previewing ? `确认后将 ${batch.summary.importable} 条记录写入商家池；隔离记录也会保留，格式错误行不会入池。正式客户和财务不会变动。` : batch.status === 'reverted' ? '本批入池记录已撤销，批次原始资料和处理结果仍保留。' : '本批记录已入池。待核对记录仍需人工核对并选择销售负责人，才能转为销售线索。'}</p>
          <div className="flex flex-wrap items-center gap-2"><div aria-label="导入行筛选" className="flex gap-1">{[['all', '全部行'], ['isolated', '隔离行'], ['error', '格式错误']].map(([value, label]) => <Button key={value} size="sm" variant={rowFilter === value ? 'default' : 'outline'} onClick={() => { setRowFilter(value); setVisibleCount(30); }}>{label}</Button>)}</div>{batch.summary.errors + batch.summary.isolated > 0 && <Button size="sm" variant="outline" onClick={() => void downloadIssues()}><Download className="mr-1 h-4 w-4" />下载问题行</Button>}</div>
          <div className="max-h-80 overflow-auto rounded-xl border border-slate-200"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs text-slate-600"><tr><th className="p-3">原行号</th><th className="p-3">商家资料</th><th className="p-3">处理结果</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.slice(0, visibleCount).map(row => <tr key={row.row}><td className="p-3 align-top text-slate-500">{row.row}</td><td className="p-3 align-top"><p className="break-words font-medium text-slate-900">{row.business_name || '名称为空'}</p><p className="mt-1 break-words text-slate-600">{row.phone ? formatPhoneNumber(row.phone, row.phone_country) : '无电话'}</p><p className="mt-1 break-words text-xs text-slate-500">{row.raw['商家位置']} · {row.raw['地区']} · {row.raw['来源'] || 'CSV 导入'}</p></td><td className="p-3 align-top"><Badge className={row.status === 'pending' ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-800'}>{statusNames[row.status] || row.status}</Badge><p className="mt-1 text-xs leading-5 text-slate-600">{row.reason}</p>{row.warnings?.map(warning => <p key={warning} className="mt-1 text-xs text-amber-700">{warning}</p>)}</td></tr>)}</tbody></table>{!rows.length && <p className="p-5 text-center text-sm text-slate-500">没有此类记录</p>}</div>
          {rows.length > visibleCount && <Button variant="outline" onClick={() => setVisibleCount(count => count + 100)}>显示更多行（已显示 {visibleCount}/{rows.length}）</Button>}
          <div className="flex flex-wrap justify-end gap-2">{previewing && <Button disabled={busy || !batch.summary.importable} onClick={() => void perform('confirm')}>确认入池 {batch.summary.importable} 条</Button>}{batch.status === 'committed' && <Button variant="outline" disabled={busy} onClick={() => void perform('revert')}><Undo2 className="mr-2 h-4 w-4" />撤销本批导入</Button>}</div>
        </section>}
        <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-700"><History className="mr-2 inline h-4 w-4" />最近导入批次</summary><div className="mt-3 space-y-2">{historyError ? <div role="alert" className="text-sm text-amber-800">批次历史暂时未能读取。<Button size="sm" variant="ghost" onClick={() => void loadHistory()}><RefreshCw className="mr-1 h-4 w-4" />重试</Button></div> : history.length ? history.map(item => <Button key={item.id} variant="ghost" className="h-auto w-full justify-between gap-3 whitespace-normal border px-3 py-3 text-left" disabled={busy} onClick={() => void openBatch(item.id)}><span className="min-w-0 break-words">{item.filename}<small className="mt-1 block font-normal text-slate-500">{item.row_count} 行 · {item.created_at?.slice(0, 16).replace('T', ' ')}</small></span><Badge>{statusNames[item.status] || '处理中'}</Badge></Button>) : <p className="text-sm text-slate-500">暂无导入批次</p>}</div></details>
      </div>
    </DialogContent>
  </Dialog>;
}
