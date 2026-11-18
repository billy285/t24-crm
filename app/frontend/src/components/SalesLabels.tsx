import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Tags } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogTitle, CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import { labelError, salesLabelIndustries, salesLabelKinds, salesLabelText, useSalesLabels, type SalesLabel, type SalesLabelIndustry, type SalesLabelKind } from '@/lib/sales-labels';

export function SalesLabelBadges({ labels = [], limit = 3 }: { labels?: SalesLabel[]; limit?: number }) {
  if (labels.length === 0) return null;
  const display = labels.slice(0, limit);
  return <span className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label="商家标签">
    {display.map(label => <Badge key={label.id} variant="outline" title={salesLabelText(label)} className="whitespace-normal">
      {salesLabelKinds[label.kind]} · {label.name}{label.kind === 'provider' ? label.confirmed ? ' · 已确认' : ' · 待确认' : ''}{label.archived ? ' · 已停用' : ''}
    </Badge>)}
    {display.length < labels.length && <small>另有 {labels.length - display.length} 个标签</small>}
  </span>;
}

export function SalesLabelFilter({ labels, value, onChange }: { labels: SalesLabel[]; value: string; onChange: (value: string) => void }) {
  return <NativeSelect aria-label="筛选标签" value={value} onChange={onChange} options={[
    { value: '', label: '全部标签' },
    ...labels.map(label => ({ value: String(label.id), label: salesLabelText(label) })),
  ]} />;
}

export function SalesLabelChoices({ labels, values, onChange, disabled, caption = '选择标签' }: {
  labels: SalesLabel[]; values: number[]; onChange: (values: number[]) => void; disabled?: boolean; caption?: string;
}) {
  const active = labels.filter(label => !label.archived);
  if (!active.length) return <p className="text-sm text-muted-foreground">暂无可用标签，可由老板在商家池的「管理标签」新增。</p>;
  return <fieldset className="grid gap-1 rounded-md border p-2" disabled={disabled}>
    <legend className="px-1 text-sm font-medium">{caption}</legend>
    <div className="grid max-h-48 gap-1 overflow-y-auto">
      {active.map(label => <label className="flex min-h-9 items-center gap-2 px-1 text-sm" key={label.id}>
        <input type="checkbox" checked={values.includes(label.id)} disabled={!values.includes(label.id) && values.length >= 20}
          onChange={event => onChange(event.target.checked ? [...values, label.id] : values.filter(id => id !== label.id))} />
        <span>{salesLabelText(label)} · {salesLabelIndustries[label.industry]}</span>
      </label>)}
    </div>
  </fieldset>;
}

export function SalesLabelEditor({ leadId, merchantId, onSaved, onClose }: {
  leadId?: number; merchantId?: number; onSaved?: () => void; onClose?: () => void;
}) {
  const { employee, role } = useRole();
  const [open, setOpen] = useState(Boolean(onClose));
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState(false);
  const catalog = useSalesLabels(open);
  const endpoint = leadId != null ? `/api/v1/sales-labels/leads/${leadId}` : `/api/v1/sales-labels/merchants/${merchantId}`;
  const current = useQuery<{items: SalesLabel[]; industry: string | null}>({
    queryKey: ['sales-label-links', endpoint, employee?.id, role],
    enabled: open && Boolean(employee?.id),
    queryFn: async () => (await invokeWithAuth({ url: endpoint, method: 'GET' })).data,
  });
  const applied = current.data?.items ?? [];
  const options = (catalog.data ?? []).filter(label =>
    !label.archived && !applied.some(item => item.id === label.id) &&
    (role !== 'sales' || label.kind !== 'source') &&
    (label.industry === 'all' || salesLabelIndustries[label.industry] === current.data?.industry));

  const chosen = options.find(label => String(label.id) === selectedId);

  async function change(id: number, action: 'add' | 'remove' | 'confirm') {
    setBusy(true);
    try {
      await invokeWithAuth({ url: endpoint, method: 'PUT', data: { label_id: id, action } });
      await current.refetch();
      setSelectedId('');
      onSaved?.();
    } catch (error) {
      toast.error(labelError(error));
    } finally {
      setBusy(false);
    }
  }

  function closeEditor() {
    setOpen(false);
    setSelectedId('');
    onClose?.();
  }

  return <>
    {!onClose && <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}><Tags size={15} />商家标签</Button>}
    <Dialog open={open} onOpenChange={value => { if (!busy && !value) closeEditor(); }}>
      <CrmFormDialogContent className="max-w-lg" aria-describedby={undefined}>
        <CrmFormDialogHeader><DialogTitle>商家标签</DialogTitle></CrmFormDialogHeader>
        <CrmFormDialogBody className="space-y-3">
          {current.isError || catalog.isError ? <p role="alert">标签暂时无法读取，请关闭重试。</p> : current.isPending || catalog.isPending ? <p role="status">正在读取标签…</p> : <>
            {applied.length ? <ul className="divide-y rounded-md border">
              {applied.map(label => <li key={label.id} className="flex flex-wrap items-center justify-between gap-2 p-2">
                <SalesLabelBadges labels={[label]} />
                <div className="flex flex-wrap items-center gap-1">
                  {label.kind === 'provider' && !label.confirmed && !label.archived && <Button size="sm" variant="outline" disabled={busy} onClick={() => void change(label.id, 'confirm')}>确认在用</Button>}
                  {(role !== 'sales' || label.kind !== 'source') && <Button size="sm" variant="ghost" aria-label={`移除 ${label.name}`} disabled={busy} onClick={() => void change(label.id, 'remove')}>移除</Button>}
                </div>
              </li>)}
            </ul> : <p className="text-sm text-muted-foreground">这家商家还没有标签。</p>}
            <div className="grid items-center gap-2 sm:grid-cols-[1fr_auto]">
              <NativeSelect aria-label="要添加的标签" disabled={busy} value={selectedId} onChange={setSelectedId} options={[{ value: '', label: '选择可用标签' }, ...options.map(label => ({ value: String(label.id), label: salesLabelText(label) }))]} />
              <Button disabled={!chosen || busy} onClick={() => chosen && void change(chosen.id, 'add')}>添加标签</Button>
            </div>
            {chosen?.kind === 'provider' && <p className="text-sm text-muted-foreground">添加后先显示待确认。与商家核实后可点「确认在用」。</p>}
          </>}
        </CrmFormDialogBody>
        <CrmFormDialogFooter><Button variant="outline" disabled={busy} onClick={closeEditor}>完成</Button></CrmFormDialogFooter>
      </CrmFormDialogContent>
    </Dialog>
  </>;
}

const newLabel = { name: '', kind: 'source' as SalesLabelKind, industry: 'all' as SalesLabelIndustry, archived: false };

export function SalesLabelManager({ onSaved }: { onSaved?: () => void }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<SalesLabel | null>(null);
  const [draft, setDraft] = useState(newLabel);
  const [busy, setBusy] = useState(false);
  const catalog = useSalesLabels(open);

  async function save(target: SalesLabel | null, value: typeof newLabel) {
    setBusy(true);
    try {
      await invokeWithAuth({
        url: target ? `/api/v1/sales-labels/catalog/${target.id}` : '/api/v1/sales-labels',
        method: target ? 'PUT' : 'POST',
        data: value,
      });
      await catalog.refetch();
      setEditing(null);
      setDraft(newLabel);
      toast.success('标签已保存');
      onSaved?.();
    } catch (error) {
      toast.error(labelError(error));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <Button type="button" variant="outline" onClick={() => setOpen(true)}><Tags size={16} />管理标签</Button>
    <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }}>
      <CrmFormDialogContent className="max-w-lg" aria-describedby={undefined}>
        <CrmFormDialogHeader><DialogTitle>管理销售标签</DialogTitle></CrmFormDialogHeader>
        <CrmFormDialogBody className="space-y-4">
          <form className="grid gap-2" onSubmit={event => { event.preventDefault(); if (!busy && draft.name.trim()) void save(editing, draft); }}>
            <label className="grid gap-1 text-sm">标签名称<Input maxLength={60} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} placeholder="例如 BeyondMenu、MenuSifu 或 DO ONE" /></label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <NativeSelect aria-label="标签类别" disabled={!!editing || busy} value={draft.kind} onChange={kind => setDraft({ ...draft, kind: kind as SalesLabelKind })} options={Object.entries(salesLabelKinds).map(([value, label]) => ({ value, label }))} />
              <NativeSelect aria-label="适用行业" disabled={!!editing || busy} value={draft.industry} onChange={industry => setDraft({ ...draft, industry: industry as SalesLabelIndustry })} options={Object.entries(salesLabelIndustries).map(([value, label]) => ({ value, label }))} />
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={!draft.name.trim() || busy}>{editing ? '保存名称' : '新增标签'}</Button>
              {editing && <Button type="button" variant="ghost" disabled={busy} onClick={() => { setEditing(null); setDraft(newLabel); }}>取消编辑</Button>}
            </div>
          </form>
          {catalog.isError ? <p role="alert">标签目录无法读取。</p> : <ul className="divide-y rounded-md border">
            {(catalog.data ?? []).map(label => <li key={label.id} className="flex flex-wrap items-center justify-between gap-2 p-2">
              <div className="min-w-0"><p className="break-words text-sm font-medium">{salesLabelText(label)}</p><small>{salesLabelIndustries[label.industry]}</small></div>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setEditing(label); setDraft(label); }}>改名</Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save(label, { ...label, archived: !label.archived })}>{label.archived ? '恢复' : '停用'}</Button>
              </div>
            </li>)}
          </ul>}
        </CrmFormDialogBody>
        <CrmFormDialogFooter><Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>完成</Button></CrmFormDialogFooter>
      </CrmFormDialogContent>
    </Dialog>
  </>;
}
