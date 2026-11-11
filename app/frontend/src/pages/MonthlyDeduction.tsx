import './crm-org-compact.css';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Table, TableHead, TableHeader, TableRow, TableBody, TableCell } from '@/components/ui/table';
import { Plus, Edit, Trash2, RefreshCw, Upload, Shield, MoreHorizontal } from 'lucide-react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { getDefaultDeduction, updateDefaultDeduction, importMonthlyDeductions } from '@/lib/api';
import { useRole } from '@/lib/role-context';
import './mobile-payroll-settings.css';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import PageLoadState from '@/components/PageLoadState';
import ConfirmDialog from '@/components/ConfirmDialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';

const displayRate = (rate: number) => String(Number((rate * 100).toFixed(6)));
type RateItem = { year_month: string; rate: number; created_at?: string; updated_at?: string };

export default function MonthlyDeduction() {
  const { isAdmin } = useRole();
  const [items, setItems] = useState<RateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [defaultBaseline, setDefaultBaseline] = useState('');
  const [editBaseline, setEditBaseline] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{ title: string; description: string; run: () => Promise<boolean | void> } | null>(null);
  const [open, setOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<RateItem | null>(null);
  const [ym, setYm] = useState<string>('');
  const [ratePct, setRatePct] = useState<string>('15');

  // Default rate
  const [defaultRatePct, setDefaultRatePct] = useState<string>('15');
  const [savingDefault, setSavingDefault] = useState(false);

  // Import
  const [importFile, setImportFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState<boolean>(true);
  const [importing, setImporting] = useState(false);
  const unavailable = loading || Boolean(loadError) || !hasLoaded;
  const { confirmDiscard } = useUnsavedChanges((hasLoaded && defaultBaseline !== defaultRatePct) || (open && editBaseline !== JSON.stringify([ym, ratePct])) || Boolean(importFile));
  const closeEditor = (next: boolean) => { if (!next && (saving || !confirmDiscard())) return; setOpen(next); };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [res, def] = await Promise.all([
        invokeWithAuth({ url: '/api/v1/deductions-monthly', method: 'GET' }), getDefaultDeduction(),
      ]);
      const rate = Number(def?.data?.rate);
      if (!Number.isFinite(rate)) throw new Error('默认扣点未读取，请重新加载');
      const value = displayRate(rate);
      setItems(res.data || []); setDefaultRatePct(value); setDefaultBaseline(value); setHasLoaded(true); setLoadError(null);
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '加载失败';
      setLoadError(detail);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditTarget(null);
    setYm('');
    setRatePct('15');
    setEditBaseline(JSON.stringify(['', '15']));
    setOpen(true);
  };

  const openEdit = (item: RateItem) => {
    setEditTarget(item);
    setYm(item.year_month);
    const percent = displayRate(item.rate || 0);
    setRatePct(percent); setEditBaseline(JSON.stringify([item.year_month, percent]));
    setOpen(true);
  };

  const save = async (confirmed = false): Promise<boolean> => {
    if (!isAdmin || unavailable || saving) return false;
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(ym)) {
      toast.error('月份格式为 YYYY-MM');
      return false;
    }
    const percent = Number(ratePct);
    if (!Number.isFinite(percent) || percent < 0 || percent > 100 || !ratePct.trim()) { toast.error('请输入 0 至 100 的扣点比例'); return false; }
    const rate = Math.max(0, Math.min(100, percent)) / 100;
    if (editTarget && rate !== editTarget.rate && !confirmed) {
      setConfirmation({ title: '确认调整月度扣点', description: `将 ${ym} 扣点从 ${displayRate(editTarget.rate)}% 改为 ${ratePct}%。这会影响该月份财务展示，请核对后保存。`, run: () => save(true) });
      return false;
    }
    setSaving(true);
    try {
      if (editTarget) {
        await invokeWithAuth({ url: `/api/v1/deductions-monthly/${ym}`, method: 'PUT', data: { rate } });
        toast.success('已更新');
      } else {
        await invokeWithAuth({ url: '/api/v1/deductions-monthly', method: 'POST', data: { year_month: ym, rate } });
        toast.success('已创建');
      }
      setOpen(false);
      await load();
      return true;
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '保存失败';
      toast.error(detail);
      return false;
    } finally { setSaving(false); }
  };

  const del = async (ymStr: string): Promise<boolean> => {
    if (!isAdmin || unavailable) return false;
    try {
      await invokeWithAuth({ url: `/api/v1/deductions-monthly/${ymStr}`, method: 'DELETE' });
      toast.success('已删除');
      await load();
      return true;
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '删除失败';
      toast.error(detail);
      return false;
    }
  };

  const saveDefault = async (confirmed = false): Promise<boolean> => {
    if (!isAdmin || unavailable || savingDefault) return false;
    const percent = Number(defaultRatePct);
    if (!Number.isFinite(percent) || percent < 0 || percent > 100 || !defaultRatePct.trim()) { toast.error('请输入 0 至 100 的扣点比例'); return false; }
    if (defaultBaseline !== defaultRatePct && !confirmed) {
      setConfirmation({ title: '确认调整默认扣点', description: `默认扣点从 ${defaultBaseline}% 改为 ${defaultRatePct}%。未单独设置比例的月份将使用新默认值，请核对后保存。`, run: () => saveDefault(true) });
      return false;
    }
    setSavingDefault(true);
    try {
      const val = Math.max(0, Math.min(100, Number(defaultRatePct))) / 100;
      await updateDefaultDeduction(val);
      toast.success('默认扣点已更新'); setDefaultBaseline(defaultRatePct);
      return true;
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '更新失败';
      toast.error(detail);
      return false;
    } finally {
      setSavingDefault(false);
    }
  };

  const doImport = async (confirmed = false): Promise<boolean> => {
    if (!isAdmin || unavailable || importing) return false;
    if (!importFile) {
      toast.error('请选择 CSV 文件');
      return false;
    }
    if (!confirmed) {
      setConfirmation({ title: '确认导入月度扣点', description: `导入 ${importFile.name}，${overwrite ? '会覆盖 CSV 中同月份现有比例' : '保留同月份现有比例'}。请确认月份和比例已核对。`, run: () => doImport(true) });
      return false;
    }
    setImporting(true);
    try {
      const res = await importMonthlyDeductions(importFile, overwrite);
      toast.success(`导入完成: 共${res.data.total}条, 新增${res.data.inserted}, 更新${res.data.updated}, 跳过${res.data.skipped}`);
      setImportFile(null);
      await load();
      return true;
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '导入失败';
      toast.error(detail);
      return false;
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="crm-order-customer-org crm-order-deduction crm-org-compact deduction-settings-page t24-settings-page calm-report-page app-page space-y-5">
      <div className="app-page-title flex items-center justify-between">
        <div><p className="app-page-kicker">T24 Marketing · Finance Settings</p><h1 className="app-page-heading">月度扣点比例</h1><p className="app-page-description">统一管理每月平台扣点比例，修改后影响对应月份财务口径。</p></div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { if (confirmDiscard()) void load(); }} disabled={loading || saving || savingDefault}>
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          {isAdmin && (
            <Button onClick={openCreate} disabled={unavailable}>
              <Plus className="w-4 h-4 mr-2" />
              新增月份
            </Button>
          )}
        </div>
      </div>

      {loadError && <PageLoadState error={`扣点设置读取失败：${loadError}`} onRetry={() => void load()} />}
      {!hasLoaded && loading && <p role="status">正在读取扣点设置…</p>}
      <Card>
        <CardHeader className="deduction-card-heading flex flex-row items-center justify-between">
          <CardTitle>默认扣点（全局）</CardTitle>
          <div className="flex items-center text-slate-500 text-xs"><Shield className="w-4 h-4 mr-1" />仅管理员可修改</div>
        </CardHeader>
        <CardContent>
          <div className="deduction-default-form flex items-end gap-3">
            <div>
              <Label htmlFor="default-deduction-rate">默认扣点 (%)</Label>
              <Input id="default-deduction-rate" type="number" min={0} max={100} value={hasLoaded ? defaultRatePct : ''} onChange={(e) => setDefaultRatePct(e.target.value)} disabled={!isAdmin || unavailable} />
            </div>
            {isAdmin && (
              <Button onClick={() => void saveDefault()} disabled={savingDefault || unavailable || defaultBaseline === defaultRatePct}>
                保存默认
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>配置列表</CardTitle>
        </CardHeader>
        <CardContent>
          <Table className="deduction-responsive-table">
            <TableHeader>
              <TableRow>
                <TableHead>月份</TableHead>
                <TableHead>扣点比例</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it) => (
                <TableRow key={it.year_month}>
                  <TableCell data-label="月份">{it.year_month}</TableCell>
                  <TableCell data-label="扣点比例">{displayRate(it.rate || 0)}%</TableCell>
                  <TableCell data-label="更新时间">{it.updated_at ? String(it.updated_at).slice(0, 19).replace('T', ' ') : '-'}</TableCell>
                  <TableCell data-label="操作" className="text-right space-x-2">
                    {isAdmin && (
                      <>
                        <Button size="sm" variant="outline" disabled={unavailable} onClick={() => openEdit(it)}>
                          <Edit className="w-4 h-4 mr-1" /> 编辑
                        </Button>
                        <DropdownMenu><DropdownMenuTrigger asChild><Button size="sm" variant="ghost" disabled={unavailable} aria-label={`${it.year_month} 更多操作`}><MoreHorizontal className="w-4 h-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem className="text-red-600" onSelect={() => setDeleteTarget(it.year_month)}><Trash2 className="w-4 h-4 mr-2" />删除月度配置</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {hasLoaded && !loading && !loadError && items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-slate-500">暂无数据</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {isAdmin && (
        <details className="calm-secondary-panel">
          <summary>批量维护 · CSV 导入</summary>
        <Card>
          <CardHeader>
            <CardTitle>批量导入 (CSV)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col md:flex-row gap-3 md:items-end">
              <div className="flex-1">
                <Label htmlFor="deduction-import">CSV 文件（月份、扣点比例）</Label>
                <p className="mb-2 text-xs text-slate-500">请按下载样例填写：year_month 为月份，rate 为小数比例（如 0.15 表示 15%）。</p>
                <Input id="deduction-import" type="file" accept=".csv" onChange={(e) => setImportFile(e.target.files?.[0] || null)} />
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="overwrite" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                <Label htmlFor="overwrite">覆盖同月</Label>
              </div>
              <Button onClick={() => void doImport()} disabled={importing || unavailable || !importFile}>
                <Upload className="w-4 h-4 mr-2" />
                导入
              </Button>
              <a className="text-blue-600 hover:underline" href="/backend/mock_data/monthly_deduction_rates_sample.csv" target="_blank" rel="noreferrer">下载样例</a>
            </div>
          </CardContent>
        </Card>
        </details>
      )}

      <Dialog open={open} onOpenChange={closeEditor}>
        <DialogContent className="deduction-editor">
          <DialogHeader>
            <DialogTitle>{editTarget ? '编辑月份' : '新增月份'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="deduction-month">月份 (YYYY-MM)</Label>
              <Input id="deduction-month" type="month" disabled={Boolean(editTarget)} value={ym} onChange={(e) => setYm(e.target.value)} placeholder="例如 2026-03" />
            </div>
            <div>
              <Label htmlFor="deduction-rate">扣点比例 (%)</Label>
              <Input
                id="deduction-rate"
                type="number"
                min={0}
                max={100}
                value={ratePct}
                onChange={(e) => setRatePct(e.target.value)}
                placeholder="例如 15"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => closeEditor(false)}>取消</Button>
              <Button onClick={() => void save()} disabled={!isAdmin || unavailable || saving}>{saving ? '保存中…' : '保存'}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={Boolean(confirmation)} onOpenChange={next => { if (!next) setConfirmation(null); }} title={confirmation?.title} description={confirmation?.description} destructive={false} confirmLabel="确认执行" loadingLabel="处理中…" onConfirm={() => confirmation?.run()} />
      <ConfirmDialog open={Boolean(deleteTarget)} onOpenChange={next => { if (!next) setDeleteTarget(null); }} title="确认删除月度扣点配置" description={`删除 ${deleteTarget || ''} 的专属扣点后，该月份将使用全局默认比例。确认已核对影响？`} onConfirm={async () => { if (!deleteTarget) return false; return del(deleteTarget); }} />
    </div>
  );
}
