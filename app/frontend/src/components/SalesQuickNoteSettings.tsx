import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Plus } from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog, DialogDescription, DialogTitle,
  CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import {
  quickNoteIndustries, readSalesQuickNotes, saveSalesQuickNotes,
  type QuickNoteIndustry, type SalesQuickNotes, type SalesQuickNoteTemplate,
} from '@/lib/sales-quick-notes';

const industryOptions = Object.entries(quickNoteIndustries).map(([value, label]) => ({ value, label }));

function errorDetail(cause: unknown, fallback: string): string {
  const error = cause as { data?: { detail?: unknown }; message?: string };
  return typeof error?.data?.detail === 'string' ? error.data.detail : error?.message || fallback;
}

type Props = {
  onClose: () => void;
  onSaved: (config: SalesQuickNotes) => void;
};

// Mounted only while the owner has the editor open. Each opening fetches the
// current revision and a stale editor cannot overwrite another owner's save.
export default function SalesQuickNoteSettings({ onClose, onSaved }: Props) {
  const [config, setConfig] = useState<SalesQuickNotes | null>(null);
  const [templates, setTemplates] = useState<SalesQuickNoteTemplate[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [readAttempt, setReadAttempt] = useState(0);
  const mounted = useRef(false);
  const savingRef = useRef(false);
  const dirty = config !== null && JSON.stringify(templates) !== JSON.stringify(config.templates);
  const draft = useUnsavedChanges(dirty);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    setLoadError('');
    setSaveError('');
    setConflict(false);
    let current = true;
    void readSalesQuickNotes().then(value => {
      if (!current) return;
      setConfig(value);
      setTemplates(value.templates);
      setEditingId(null);
    }).catch(cause => {
      if (current) setLoadError(errorDetail(cause, '读取快捷备注失败，请重试。'));
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; mounted.current = false; };
  }, [readAttempt]);

  function close() {
    if (!savingRef.current && draft.confirmDiscard()) onClose();
  }

  function reload() {
    if (!savingRef.current && draft.confirmDiscard()) setReadAttempt(value => value + 1);
  }

  function update(id: string, changes: Partial<SalesQuickNoteTemplate>) {
    setTemplates(current => current.map(item => item.id === id ? { ...item, ...changes } : item));
    setSaveError('');
  }

  function move(id: string, offset: -1 | 1) {
    setTemplates(current => {
      const from = current.findIndex(item => item.id === id), to = from + offset;
      if (from < 0 || to < 0 || to >= current.length) return current;
      const reordered = [...current];
      [reordered[from], reordered[to]] = [reordered[to], reordered[from]];
      return reordered;
    });
  }

  function add() {
    if (templates.length >= 60) return;
    const id = `quick_${globalThis.crypto.randomUUID()}`;
    setTemplates(current => [...current, { id, label: '', text: '', industry: 'all', enabled: true, remind_do_not_contact: false }]);
    setEditingId(id);
    setSaveError('');
  }

  async function save() {
    if (!config || !dirty || loading || loadError || conflict || savingRef.current) return;
    const normalized = templates.map(item => ({ ...item, label: item.label.trim(), text: item.text.trim() }));
    const incomplete = normalized.find(item => !item.label || !item.text);
    if (incomplete) {
      setEditingId(incomplete.id);
      setSaveError('请填写按钮名称和备注正文。');
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setSaveError('');
    try {
      const saved = await saveSalesQuickNotes(config.revision, normalized);
      if (!mounted.current) return;
      draft.markSaved();
      onSaved(saved);
      toast.success('快捷备注已保存');
      onClose();
    } catch (cause) {
      if (!mounted.current) return;
      const error = cause as { response?: { status?: number }; data?: { status?: number }; status?: number };
      const status = error?.response?.status || error?.data?.status || error?.status;
      if (status === 409) {
        setConflict(true);
        setSaveError('快捷备注已由其他人更新。当前编辑已保留，请重新读取后再保存。');
      } else {
        setSaveError(errorDetail(cause, '保存快捷备注失败，请重试。'));
      }
    } finally {
      savingRef.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  return <Dialog open onOpenChange={open => { if (!open) close(); }}>
    <CrmFormDialogContent className="max-w-2xl" aria-busy={loading || saving}>
      <CrmFormDialogHeader>
        <DialogTitle>管理快捷备注</DialogTitle>
        <DialogDescription>销售勾选快捷备注时会填入对应文字。手机优先显示排在前面的备注。</DialogDescription>
      </CrmFormDialogHeader>
      <CrmFormDialogBody className="space-y-3">
        {loading ? <p role="status" className="py-5 text-sm text-muted-foreground">正在读取快捷备注…</p> :
          loadError ? <div className="space-y-3">
            <p role="alert">{loadError}</p>
            <Button variant="outline" onClick={reload}>重新读取</Button>
          </div> :
          <fieldset className="m-0 min-w-0 space-y-2 border-0 p-0" disabled={saving}>
            {templates.map((item, index) => {
              const label = item.label || '新快捷备注';
              const editing = editingId === item.id;
              const existing = config?.templates.some(saved => saved.id === item.id);
              return <div key={item.id} className="rounded-lg border border-border">
                <div className="flex min-w-0 flex-wrap items-center gap-1 p-1.5 sm:flex-nowrap">
                  <button type="button" onClick={() => setEditingId(editing ? null : item.id)} aria-expanded={editing} className="min-h-11 min-w-0 flex-1 rounded-md px-2 text-left text-sm hover:bg-muted">
                    <span className="block break-words font-medium">{label}</span>
                    <span className="text-xs text-muted-foreground">{quickNoteIndustries[item.industry]}{item.enabled ? '' : ' · 已停用'}</span>
                  </button>
                  <div className="flex items-center gap-1">
                    <Button type="button" size="icon" variant="ghost" className="h-11 w-11" disabled={index === 0} aria-label={`上移：${label}`} onClick={() => move(item.id, -1)}><ArrowUp size={16} /></Button>
                    <Button type="button" size="icon" variant="ghost" className="h-11 w-11" disabled={index === templates.length - 1} aria-label={`下移：${label}`} onClick={() => move(item.id, 1)}><ArrowDown size={16} /></Button>
                    <Button type="button" variant="outline" className="min-h-11" aria-label={`${item.enabled ? '停用' : '启用'}：${label}`} onClick={() => update(item.id, { enabled: !item.enabled })}>{item.enabled ? '停用' : '启用'}</Button>
                  </div>
                </div>
                {editing && <div className="grid gap-3 border-t border-border p-3 sm:grid-cols-2">
                  <Label className="min-w-0 space-y-2">按钮名称
                    <Input value={item.label} maxLength={24} onChange={event => update(item.id, { label: event.target.value })} />
                  </Label>
                  <Label className="space-y-2">适用行业
                    <NativeSelect value={item.industry} options={industryOptions} aria-label="适用行业" onChange={value => update(item.id, { industry: value as QuickNoteIndustry })} />
                  </Label>
                  <Label className="space-y-2 sm:col-span-2">备注正文
                    <Textarea value={item.text} maxLength={1000} rows={3} onChange={event => update(item.id, { text: event.target.value })} />
                  </Label>
                  <label className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2">
                    <input type="checkbox" checked={item.remind_do_not_contact} onChange={event => update(item.id, { remind_do_not_contact: event.target.checked })} />
                    使用时提示销售选择「禁止再联系」
                  </label>
                  {!existing && <Button type="button" variant="ghost" className="justify-self-start" onClick={() => { setTemplates(current => current.filter(entry => entry.id !== item.id)); setEditingId(null); setSaveError(''); }}>移除此未保存模板</Button>}
                </div>}
              </div>;
            })}
            <Button type="button" variant="outline" onClick={add} disabled={templates.length >= 60} className="min-h-11"><Plus size={16} />新增快捷备注</Button>
          </fieldset>}
        {saveError && <p role="alert" className="rounded-lg border border-border p-3 text-sm">{saveError}</p>}
        {conflict && <Button type="button" variant="outline" className="min-h-11" onClick={reload}>重新读取最新配置</Button>}
      </CrmFormDialogBody>
      <CrmFormDialogFooter>
        <Button type="button" variant="outline" className="min-h-11" disabled={saving} onClick={close}>取消</Button>
        <Button type="button" className="min-h-11" disabled={!dirty || loading || Boolean(loadError) || conflict || saving} onClick={() => void save()}>{saving ? '正在保存…' : '保存快捷备注'}</Button>
      </CrmFormDialogFooter>
    </CrmFormDialogContent>
  </Dialog>;
}
