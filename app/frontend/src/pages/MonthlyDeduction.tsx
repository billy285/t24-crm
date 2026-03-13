import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Table, TableHead, TableHeader, TableRow, TableBody, TableCell } from '@/components/ui/table';
import { Plus, Edit, Trash2, RefreshCw, Upload, Shield } from 'lucide-react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { getDefaultDeduction, updateDefaultDeduction, importMonthlyDeductions } from '@/lib/api';
import { useRole } from '@/lib/role-context';

type RateItem = { year_month: string; rate: number; created_at?: string; updated_at?: string };

export default function MonthlyDeduction() {
  const { isAdmin } = useRole();
  const [items, setItems] = useState<RateItem[]>([]);
  const [loading, setLoading] = useState(false);
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

  const load = async () => {
    setLoading(true);
    try {
      const res = await invokeWithAuth({ url: '/api/v1/deductions-monthly', method: 'GET' });
      setItems(res.data || []);
      const def = await getDefaultDeduction();
      const rate = Number(def?.data?.rate ?? 0.15);
      setDefaultRatePct(String(Math.round(rate * 100)));
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '加载失败';
      toast.error(detail);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditTarget(null);
    setYm('');
    setRatePct('15');
    setOpen(true);
  };

  const openEdit = (item: RateItem) => {
    setEditTarget(item);
    setYm(item.year_month);
    setRatePct(String(Math.round((item.rate || 0) * 100)));
    setOpen(true);
  };

  const save = async () => {
    if (!/^\d{4}-\d{2}$/.test(ym)) {
      toast.error('月份格式为 YYYY-MM');
      return;
    }
    const rate = Math.max(0, Math.min(100, Number(ratePct))) / 100;
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
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '保存失败';
      toast.error(detail);
    }
  };

  const del = async (ymStr: string) => {
    try {
      await invokeWithAuth({ url: `/api/v1/deductions-monthly/${ymStr}`, method: 'DELETE' });
      toast.success('已删除');
      await load();
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '删除失败';
      toast.error(detail);
    }
  };

  const saveDefault = async () => {
    setSavingDefault(true);
    try {
      const val = Math.max(0, Math.min(100, Number(defaultRatePct))) / 100;
      await updateDefaultDeduction(val);
      toast.success('默认扣点已更新');
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '更新失败';
      toast.error(detail);
    } finally {
      setSavingDefault(false);
    }
  };

  const doImport = async () => {
    if (!importFile) {
      toast.error('请选择 CSV 文件');
      return;
    }
    setImporting(true);
    try {
      const res = await importMonthlyDeductions(importFile, overwrite);
      toast.success(`导入完成: 共${res.data.total}条, 新增${res.data.inserted}, 更新${res.data.updated}, 跳过${res.data.skipped}`);
      setImportFile(null);
      await load();
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '导入失败';
      toast.error(detail);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">月度扣点比例</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          {isAdmin && (
            <Button onClick={openCreate}>
              <Plus className="w-4 h-4 mr-2" />
              新增月份
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>默认扣点（全局）</CardTitle>
          <div className="flex items-center text-slate-500 text-xs"><Shield className="w-4 h-4 mr-1" />仅管理员可修改</div>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-3">
            <div>
              <Label>默认扣点 (%)</Label>
              <Input type="number" min={0} max={100} value={defaultRatePct} onChange={(e) => setDefaultRatePct(e.target.value)} disabled={!isAdmin} />
            </div>
            {isAdmin && (
              <Button onClick={saveDefault} disabled={savingDefault}>
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
          <Table>
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
                  <TableCell>{it.year_month}</TableCell>
                  <TableCell>{Math.round((it.rate || 0) * 100)}%</TableCell>
                  <TableCell>{it.updated_at ? String(it.updated_at).slice(0, 19).replace('T', ' ') : '-'}</TableCell>
                  <TableCell className="text-right space-x-2">
                    {isAdmin && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => openEdit(it)}>
                          <Edit className="w-4 h-4 mr-1" /> 编辑
                        </Button>
                        <Button size="sm" variant="destructive" onClick={() => del(it.year_month)}>
                          <Trash2 className="w-4 h-4 mr-1" /> 删除
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-slate-500">暂无数据</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle>批量导入 (CSV)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col md:flex-row gap-3 md:items-end">
              <div className="flex-1">
                <Label>CSV 文件（列：year_month, rate）</Label>
                <Input type="file" accept=".csv" onChange={(e) => setImportFile(e.target.files?.[0] || null)} />
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="overwrite" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                <Label htmlFor="overwrite">覆盖同月</Label>
              </div>
              <Button onClick={doImport} disabled={importing || !importFile}>
                <Upload className="w-4 h-4 mr-2" />
                导入
              </Button>
              <a className="text-blue-600 hover:underline" href="/backend/mock_data/monthly_deduction_rates_sample.csv" target="_blank" rel="noreferrer">下载样例</a>
            </div>
          </CardContent>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editTarget ? '编辑月份' : '新增月份'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>月份 (YYYY-MM)</Label>
              <Input value={ym} onChange={(e) => setYm(e.target.value)} placeholder="例如 2026-03" />
            </div>
            <div>
              <Label>扣点比例 (%)</Label>
              <Input
                type="number"
                min={0}
                max={100}
                value={ratePct}
                onChange={(e) => setRatePct(e.target.value)}
                placeholder="例如 15"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
              <Button onClick={save} disabled={!isAdmin}>保存</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}