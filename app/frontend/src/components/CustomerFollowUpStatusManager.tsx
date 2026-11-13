import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogDescription, DialogTitle, CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { client, isAuthSessionCurrent } from '@/lib/api';
import { getAuthSessionEpoch } from '@/lib/auth-storage';
import { readCachedAppConfig, writeCachedAppConfig } from '@/lib/app-config';
import { defaultBusinessDictConfig } from '@/lib/dict-config';
import { useRole } from '@/lib/role-context';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { createCustomerFollowUpStatusKey, getCustomerFollowUpStatusEntries, serializeCustomerFollowUpStatusEntries, validateCustomerFollowUpStatusEntries, type CustomerFollowUpStatusEntry, type CustomerFollowUpStatusFields } from '@/lib/customer-followup-statuses';

const endpoint = '/api/v1/app-config/dict_config/customer-followup-statuses';
interface StatusResponse { active: string; archive: string; revision: string }

function readStatusResponse(value: unknown): StatusResponse {
  const data = value as Partial<StatusResponse> | null;
  if (!data || typeof data.active !== 'string' || typeof data.archive !== 'string' || typeof data.revision !== 'string' || !/^[a-f0-9]{64}$/.test(data.revision)) throw new Error('服务阶段配置格式异常，请重新读取。');
  return data as StatusResponse;
}

function errorStatus(error: unknown): number {
  const data = error as { status?: number; response?: { status?: number }; data?: { status?: number } };
  return data?.response?.status || data?.data?.status || data?.status || 0;
}

function errorMessage(error: unknown, fallback: string): string {
  const data = error as { message?: string; data?: { detail?: unknown }; response?: { data?: { detail?: unknown } } };
  const detail = data?.data?.detail ?? data?.response?.data?.detail;
  return typeof detail === 'string' ? detail : data?.message || fallback;
}

export default function CustomerFollowUpStatusManager({ open, onOpenChange, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; onSaved?: (fields: CustomerFollowUpStatusFields) => void }) {
  const { systemRole, employee } = useRole();
  const canManage = systemRole === 'admin' || systemRole === 'super_admin';
  const actorEpoch = getAuthSessionEpoch();
  const managerScope = `${employee?.id ?? ''}:${systemRole || ''}:${actorEpoch}`;
  const scopeRef = useRef({ key: managerScope, allowed: canManage });
  scopeRef.current = { key: managerScope, allowed: canManage };
  const [entries, setEntries] = useState<CustomerFollowUpStatusEntry[]>([]);
  const [revision, setRevision] = useState('');
  const [baseline, setBaseline] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [reload, setReload] = useState(0);
  const requestId = useRef({ value: 0 });
  const saveLock = useRef(false);
  const dirty = Boolean(revision) && (JSON.stringify(entries) !== baseline || Boolean(newLabel.trim()));
  const draft = useUnsavedChanges(open && dirty);

  useEffect(() => {
    const session = requestId.current;
    const request = ++session.value;
    if (!open || !canManage) { setEntries([]); setRevision(''); setLoading(false); setSaving(false); return; }
    const current = () => session.value === request && isAuthSessionCurrent(actorEpoch) && scopeRef.current.key === managerScope && scopeRef.current.allowed;
    setLoading(true); setLoadError(''); setSaveError(''); setConflict(false); setRevision(''); setEntries([]); setNewLabel('');
    void client.apiCall.invoke({ url: endpoint, method: 'GET', options: { withCredentials: true, headers: { 'Cache-Control': 'no-cache' } } }).then(response => {
      if (!current()) return;
      const data = readStatusResponse(response.data);
      const next = getCustomerFollowUpStatusEntries({ customerFollowUpStatuses: data.active, customerFollowUpStatusArchive: data.archive });
      const error = validateCustomerFollowUpStatusEntries(next);
      if (error) throw new Error(error);
      setEntries(next); setBaseline(JSON.stringify(next)); setRevision(data.revision);
    }).catch(error => { if (current()) setLoadError(errorMessage(error, '读取客户服务阶段失败，请重试。')); }).finally(() => { if (current()) setLoading(false); });
    return () => { session.value++; };
  }, [open, canManage, actorEpoch, managerScope, reload]);

  const close = (next: boolean) => {
    if (saving || saveLock.current) return;
    if (!next && !draft.confirmDiscard()) return;
    onOpenChange(next);
  };
  const reread = () => { if (!saving && draft.confirmDiscard()) setReload(value => value + 1); };
  const update = (key: string, patch: Partial<CustomerFollowUpStatusEntry>) => {
    setSaveError(''); setEntries(current => current.map(entry => entry.key === key ? { ...entry, ...patch } : entry));
  };
  const move = (key: string, offset: number) => {
    setEntries(current => {
      const index = current.findIndex(entry => entry.key === key), target = index + offset;
      if (index < 0 || target < 0 || target >= current.length || current[index].active !== current[target].active) return current;
      const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next;
    });
  };
  const add = () => {
    const nextLabel = newLabel.trim();
    const next = [...entries.filter(entry => entry.active), { key: createCustomerFollowUpStatusKey(entries, nextLabel), label: nextLabel, active: true }, ...entries.filter(entry => !entry.active)];
    const error = validateCustomerFollowUpStatusEntries(next);
    if (error) { setSaveError(error); return; }
    setEntries(next); setNewLabel(''); setSaveError('');
  };
  const toggle = (entry: CustomerFollowUpStatusEntry) => {
    if (entry.active && entries.filter(item => item.active).length <= 1) { setSaveError('至少保留一个启用的客户服务阶段。'); return; }
    const changed = { ...entry, active: !entry.active };
    const rest = entries.filter(item => item.key !== entry.key);
    setEntries(changed.active ? [...rest.filter(item => item.active), changed, ...rest.filter(item => !item.active)] : [...rest, changed]); setSaveError('');
  };
  const save = async () => {
    if (!canManage || !scopeRef.current.allowed || scopeRef.current.key !== managerScope || !isAuthSessionCurrent(actorEpoch) || loading || loadError || !revision || conflict || saveLock.current) return;
    if (newLabel.trim()) { setSaveError('请先添加输入的新阶段，或清空新增名称后再保存。'); return; }
    const error = validateCustomerFollowUpStatusEntries(entries);
    if (error) { setSaveError(error); return; }
    const fields = serializeCustomerFollowUpStatusEntries(entries);
    const request = requestId.current.value;
    const current = () => request === requestId.current.value && isAuthSessionCurrent(actorEpoch) && scopeRef.current.key === managerScope && scopeRef.current.allowed;
    saveLock.current = true; setSaving(true); setSaveError('');
    try {
      const response = await client.apiCall.invoke({ url: endpoint, method: 'PATCH', data: { active: fields.customerFollowUpStatuses, archive: fields.customerFollowUpStatusArchive, expected_revision: revision }, options: { withCredentials: true } });
      if (!current()) return;
      const data = readStatusResponse(response.data);
      const saved = { customerFollowUpStatuses: data.active, customerFollowUpStatusArchive: data.archive };
      const next = getCustomerFollowUpStatusEntries(saved);
      const validationError = validateCustomerFollowUpStatusEntries(next);
      if (validationError) throw new Error(validationError);
      writeCachedAppConfig('dict_config', { ...readCachedAppConfig('dict_config', defaultBusinessDictConfig), ...saved });
      setEntries(next); setBaseline(JSON.stringify(next)); setRevision(data.revision); draft.markSaved();
      onSaved?.(saved); toast.success('客户服务阶段已保存'); onOpenChange(false);
    } catch (error) {
      if (!current()) return;
      if (errorStatus(error) === 409) { setConflict(true); setSaveError('其他管理员已修改服务阶段。本次草稿已保留，请重新读取最新配置后再编辑。'); }
      else if ([401, 403].includes(errorStatus(error))) { setEntries([]); setRevision(''); setLoadError('当前账号无法管理服务阶段，请确认登录身份和权限。'); }
      else setSaveError(errorMessage(error, '保存失败，本次修改已保留，请重试。'));
    } finally { saveLock.current = false; if (current()) setSaving(false); }
  };
  const active = entries.filter(entry => entry.active), archived = entries.filter(entry => !entry.active);
  const disabled = loading || saving || Boolean(loadError) || !revision;

  return <Dialog open={open && canManage} onOpenChange={close}><CrmFormDialogContent className="customer-followup-status-manager max-w-2xl" aria-busy={loading || saving}>
    <CrmFormDialogHeader><DialogTitle>客户服务阶段</DialogTitle><DialogDescription>用于成交后的客户服务跟进，与销售跟进阶段分开。停用后不供新增，历史记录仍保留。</DialogDescription></CrmFormDialogHeader>
    <CrmFormDialogBody className="space-y-4">
    {loading ? <p role="status" className="py-6 text-sm text-muted-foreground">正在读取服务阶段…</p> : loadError ? <div role="alert" className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><p>{loadError}</p><Button className="min-h-11" variant="outline" onClick={reread}>重新读取</Button></div> : <>
      <fieldset disabled={disabled} className="m-0 min-w-0 space-y-4 border-0 p-0">
        <section aria-label="启用的客户服务阶段"><div className="mb-2 flex items-center justify-between text-sm"><h3 className="font-semibold">启用中</h3><span className="text-muted-foreground">{active.length} 个</span></div><div className="space-y-2">{active.map((entry, index) => <div key={entry.key} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-2 rounded-lg border border-border p-2"><Label className="col-span-2 min-w-0"><span className="sr-only">客户服务阶段：{entry.label}</span><Input className="min-h-11" value={entry.label} onChange={event => update(entry.key, { label: event.target.value })} aria-label={`客户服务阶段：${entry.label}`} /></Label><div className="flex min-w-0 items-center gap-1"><Button className="h-11 w-11 p-0" size="icon" variant="ghost" disabled={index === 0} aria-label={`上移${entry.label}`} onClick={() => move(entry.key, -1)}><ArrowUp className="h-4 w-4" /></Button><Button className="h-11 w-11 p-0" size="icon" variant="ghost" disabled={index === active.length - 1} aria-label={`下移${entry.label}`} onClick={() => move(entry.key, 1)}><ArrowDown className="h-4 w-4" /></Button><span className="text-xs text-muted-foreground">第 {index + 1} 项{index === 0 ? ' · 新增默认' : ''}</span></div><Button className="min-h-11" variant="outline" disabled={active.length <= 1} onClick={() => toggle(entry)}>停用</Button></div>)}</div></section>
        <div className="flex min-w-0 items-end gap-2"><Label className="min-w-0 flex-1"><span className="mb-2 block text-sm">新增服务阶段</span><Input className="min-h-11" value={newLabel} onChange={event => { setNewLabel(event.target.value); setSaveError(''); }} placeholder="1–40 个字" onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); add(); } }} /></Label><Button className="min-h-11" variant="outline" disabled={!newLabel.trim()} onClick={add}><Plus className="mr-1 h-4 w-4" />添加</Button></div>
        {archived.length > 0 && <details className="rounded-lg border border-border"><summary className="min-h-11 cursor-pointer px-3 py-3 text-sm">已停用 · {archived.length} 个</summary><div className="space-y-2 border-t border-border p-2">{archived.map(entry => <div key={entry.key} className="flex min-w-0 items-center gap-2"><Input className="min-h-11 min-w-0 flex-1" value={entry.label} aria-label={`已停用阶段：${entry.label}`} onChange={event => update(entry.key, { label: event.target.value })} /><Button className="min-h-11 shrink-0" variant="outline" onClick={() => toggle(entry)}><RotateCcw className="mr-1 h-4 w-4" />恢复</Button></div>)}</div></details>}
      </fieldset>
      {saveError && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{saveError}</p>}
      {conflict && <Button className="min-h-11" variant="outline" onClick={reread}>重新读取最新配置</Button>}
    </>}
    </CrmFormDialogBody>
    <CrmFormDialogFooter><Button className="min-h-11" variant="outline" disabled={saving} onClick={() => close(false)}>取消</Button><Button className="min-h-11" disabled={disabled || conflict || !dirty} onClick={() => void save()}>{saving ? '保存中…' : '保存服务阶段'}</Button></CrmFormDialogFooter>
  </CrmFormDialogContent></Dialog>;
}
