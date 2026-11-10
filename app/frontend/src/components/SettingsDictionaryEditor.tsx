import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { buildOptionKey, parseDictEntries, sanitizeDictLabel, serializeDictEntries } from '@/lib/dict-config';

export default function SettingsDictionaryEditor({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [newLabel, setNewLabel] = useState('');
  const [error, setError] = useState('');
  const [draftLabels, setDraftLabels] = useState<Record<string, string>>({});
  const entries = Object.entries(parseDictEntries(value));
  const update = (key: string, nextLabel: string) => {
    setDraftLabels(current => ({ ...current, [key]: nextLabel }));
    if (!nextLabel.trim()) return;
    // Keep the existing key stable: historical records continue to resolve.
    const next = entries.map(([entryKey, entryLabel]) => [entryKey, entryKey === key ? sanitizeDictLabel(nextLabel) : entryLabel]);
    onChange(next.map(([entryKey, entryLabel]) => `${entryKey}:${entryLabel}`).join(','));
  };
  const add = () => {
    const nextLabel = sanitizeDictLabel(newLabel);
    if (!nextLabel) return;
    if (entries.some(([, entryLabel]) => entryLabel === nextLabel)) { setError('已有同名选项，请编辑原条目。'); return; }
    const existing = Object.fromEntries(entries);
    let key = buildOptionKey(nextLabel);
    while (Object.prototype.hasOwnProperty.call(existing, key)) key = `${key}_new`;
    onChange(serializeDictEntries({ ...existing, [key]: nextLabel }));
    setNewLabel(''); setError('');
  };
  return <details className="settings-dictionary-group rounded-xl border border-slate-200 bg-white">
    <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-slate-800"><span>{label}</span><span className="text-xs font-normal text-slate-500">{entries.length} 个选项</span></summary>
    <div className="space-y-3 border-t border-slate-100 p-4">
      <p className="text-xs text-slate-500">修改显示名称不会改变历史记录。已有选项暂不提供删除，以免历史记录失去名称。</p>
      <div className="grid gap-2 sm:grid-cols-2">{entries.map(([key, entryLabel]) => <label key={key} className="min-w-0"><span className="mb-1 block text-xs text-slate-500">{label}选项</span><Input aria-label={`${label}：${entryLabel || key}`} value={draftLabels[key] ?? entryLabel} onChange={event => update(key, event.target.value)} onBlur={event => { if (!event.target.value.trim()) { setDraftLabels(current => ({ ...current, [key]: entryLabel })); setError('已有选项名称不能为空，已保留原名称。'); } }} /></label>)}</div>
      <div className="flex items-end gap-2"><Label className="min-w-0 flex-1"><span className="mb-1 block">新增{label}</span><Input value={newLabel} aria-label={`新增${label}`} placeholder="输入显示名称" onChange={event => { setNewLabel(event.target.value); setError(''); }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); add(); } }} /></Label><Button type="button" variant="outline" disabled={!newLabel.trim()} onClick={add}>添加选项</Button></div>
      {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
    </div>
  </details>;
}
