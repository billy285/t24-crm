import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useRole } from '@/lib/role-context';
import { loadRemoteAppConfig, saveRemoteAppConfig } from '@/lib/app-config';
import { buildOptionKey, defaultBusinessDictConfig, normalizeDictConfig, parseDictEntries, serializeDictEntries, type BusinessDictConfig } from '@/lib/dict-config';
type Entry = { key: string; label: string; active: boolean };
export default function CustomerFollowUpStatusManager({ open, onOpenChange, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; onSaved: (entries: Record<string, string>) => void }) {
  const { isAdmin } = useRole();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [baseline, setBaseline] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!open || !isAdmin) return;
    let cancelled = false;
    setBusy(true); setLoaded(false); setName('');
    loadRemoteAppConfig<BusinessDictConfig>('dict_config', defaultBusinessDictConfig).then(value => {
      if (cancelled) return;
      const config = normalizeDictConfig(value);
      const active = parseDictEntries(config.customerFollowUpStatuses);
      setEntries([...Object.entries(active).map(([key, label]) => ({ key, label, active: true })), ...Object.entries(parseDictEntries(config.customerFollowUpStatusArchive)).filter(([key]) => !active[key]).map(([key, label]) => ({ key, label, active: false }))]);
      setBaseline(JSON.stringify([config.customerFollowUpStatuses, config.customerFollowUpStatusArchive])); setLoaded(true);
    }).catch(error => { if (!cancelled) toast.error(error.message || '加载失败'); }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [open, isAdmin]);
  const add = () => {
    const label = name.trim();
    if (!label) return;
    if (entries.some(entry => entry.label.trim() === label)) { toast.error('该状态已存在'); return; }
    setEntries([...entries, { key: buildOptionKey(label), label, active: true }]); setName('');
  };
  const move = (index: number, offset: number) => {
    const next = [...entries]; const target = index + offset;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]]; setEntries(next);
  };
  const save = async () => {
    if (!isAdmin || !loaded) return;
    if (!entries.some(entry => entry.active)) { toast.error('至少保留一个可用状态'); return; }
    const labels = entries.map(entry => entry.label.trim());
    if (labels.some(label => !label || label.length > 40 || /[,，:：]/.test(label)) || new Set(labels).size !== labels.length) { toast.error('状态名称须唯一，长度 1–40 字，不能包含逗号或冒号'); return; }
    setBusy(true);
    try {
      const latest = normalizeDictConfig(await loadRemoteAppConfig<BusinessDictConfig>('dict_config', defaultBusinessDictConfig));
      if (JSON.stringify([latest.customerFollowUpStatuses, latest.customerFollowUpStatusArchive]) !== baseline) throw new Error('状态已被其他管理员修改，请关闭后重新打开');
      const active = Object.fromEntries(entries.filter(entry => entry.active).map(entry => [entry.key, entry.label.trim()]));
      const archive = Object.fromEntries(entries.filter(entry => !entry.active).map(entry => [entry.key, entry.label.trim()]));
      await saveRemoteAppConfig('dict_config', { ...latest, customerFollowUpStatuses: serializeDictEntries(active), customerFollowUpStatusArchive: serializeDictEntries(archive) });
      onSaved(active); onOpenChange(false); toast.success('客户跟进状态已保存，团队共享使用');
    } catch (error: any) { toast.error(error.message || '保存失败'); } finally { setBusy(false); }
  };
  if (!isAdmin) return null;
  return <Dialog open={open} onOpenChange={value => { if (!busy) onOpenChange(value); }}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>管理客户跟进状态</DialogTitle></DialogHeader>
    <p className="text-sm text-slate-500">团队统一使用。删除会移出下拉选项，历史记录保留，可随时恢复。</p>
    <fieldset disabled={busy || !loaded} className="space-y-3">
      <div className="flex gap-2"><Input aria-label="新增状态名称" placeholder="输入新状态名称" maxLength={40} value={name} onChange={event => setName(event.target.value)} /><Button onClick={add} disabled={!name.trim()}>新增</Button></div>
      <div className="max-h-[45vh] overflow-y-auto space-y-2">{entries.map((entry, index) => <div key={entry.key} className="flex items-center gap-1">
        <Input aria-label={`状态名称 ${index + 1}`} maxLength={40} value={entry.label} onChange={event => setEntries(entries.map((item, position) => position === index ? { ...item, label: event.target.value } : item))} />
        <Button variant="ghost" size="sm" aria-label={`上移 ${entry.label}`} disabled={index === 0} onClick={() => move(index, -1)}>↑</Button><Button variant="ghost" size="sm" aria-label={`下移 ${entry.label}`} disabled={index === entries.length - 1} onClick={() => move(index, 1)}>↓</Button>
        <Button variant="outline" size="sm" onClick={() => setEntries(entries.map((item, position) => position === index ? { ...item, active: !item.active } : item))}>{entry.active ? '删除' : '恢复'}</Button>
      </div>)}</div>
      <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button onClick={save}>{busy ? '处理中...' : '保存状态'}</Button></div>
    </fieldset>
  </DialogContent></Dialog>;
}
