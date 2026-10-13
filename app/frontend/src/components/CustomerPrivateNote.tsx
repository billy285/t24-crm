import { useEffect, useRef, useState } from 'react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { LockKeyhole } from 'lucide-react';
import { toast } from 'sonner';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';

export default function CustomerPrivateNote({customerId}: {customerId: number}) {
  const [note, setNote] = useState('');
  const [saved, setSaved] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const version = useRef(0);
  const draft = useUnsavedChanges(!loading && note !== saved);
  useEffect(() => {
    const current = ++version.current;
    setLoading(true); setNote(''); setSaved(''); setError('');
    invokeWithAuth({url:`/api/v1/entities/customers/${customerId}/private-note`,method:'GET'}).then(response => {
      if (current === version.current) { setNote(response.data?.private_notes || ''); setSaved(response.data?.private_notes || ''); }
    }).catch(() => { if (current === version.current) setError('私密备注读取失败，请刷新后重试。'); }).finally(() => { if (current === version.current) setLoading(false); });
    return () => { version.current++; };
  }, [customerId]);
  const save = async () => {
    if (loading || saving || error || note === saved) return;
    const current = version.current, snapshot = note;
    setSaving(true);
    try { await invokeWithAuth({url:`/api/v1/entities/customers/${customerId}/private-note`,method:'PUT',data:{private_notes:snapshot}}); if(current === version.current) { setSaved(snapshot); draft.markSaved(); toast.success('老板私密备注已保存'); } }
    catch { toast.error('私密备注未保存，请重试'); }
    finally { if(current === version.current) setSaving(false); }
  };
  return <section className="rounded-xl border border-violet-100 bg-violet-50/40 p-4" aria-label="老板私密备注"><div className="mb-2 flex items-center justify-between"><h3 className="flex items-center gap-2 text-sm font-medium text-slate-800"><LockKeyhole size={15} />老板私密备注</h3><span className="text-xs text-violet-700">仅老板</span></div><p className="mb-3 text-xs text-slate-500">独立保存，不进入团队备注、共享资料或导出。</p><Textarea aria-label="老板私密备注" value={note} onChange={e=>setNote(e.target.value)} disabled={loading || Boolean(error)} placeholder={loading ? '正在读取…' : '记录仅自己需要知道的信息'} rows={3} />{error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}<div className="mt-2 flex items-center justify-between"><span className="text-xs text-slate-500">{note !== saved ? '有未保存的备注' : ''}</span><Button size="sm" variant="outline" disabled={loading || saving || Boolean(error) || note===saved} onClick={save}>{saving ? '保存中…' : '保存私密备注'}</Button></div></section>;
}
