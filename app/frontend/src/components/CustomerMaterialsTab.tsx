import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  Copy,
  Download,
  Edit,
  ExternalLink,
  FileImage,
  FileText,
  Heart,
  Link2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import { getToken, refreshToken, invokeWithAuth } from '../lib/tokenStore';

const platformOptions = [
  { value: 'general', label: '通用' },
  { value: 'google_business', label: 'Google商家' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'x', label: 'X' },
  { value: 'yelp', label: 'Yelp' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'website', label: '网站' },
  { value: 'other', label: '其他' },
];

const materialTypeOptions = [
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
  { value: 'logo', label: 'Logo' },
  { value: 'menu', label: '菜单' },
  { value: 'screenshot', label: '截图' },
  { value: 'document', label: '文档' },
  { value: 'design', label: '设计稿' },
  { value: 'post', label: '发布素材' },
  { value: 'other', label: '其他' },
];

const usageStatusOptions = [
  { value: 'unused', label: '未使用' },
  { value: 'planned', label: '计划使用' },
  { value: 'used', label: '已使用' },
  { value: 'archived', label: '已归档' },
];

const approvalStatusOptions = [
  { value: 'pending', label: '待确认' },
  { value: 'approved', label: '已确认' },
  { value: 'needs_revision', label: '需修改' },
  { value: 'rejected', label: '已拒绝' },
];

const copyrightStatusOptions = [
  { value: 'owned', label: '自有素材' },
  { value: 'client_provided', label: '客户提供' },
  { value: 'licensed', label: '已授权' },
  { value: 'ai_generated', label: 'AI生成' },
  { value: 'unknown', label: '待确认版权' },
];

const usageColors: Record<string, string> = {
  unused: 'bg-slate-100 text-slate-700',
  planned: 'bg-blue-100 text-blue-700',
  used: 'bg-green-100 text-green-700',
  archived: 'bg-amber-100 text-amber-700',
};

const approvalColors: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-700',
  approved: 'bg-green-100 text-green-700',
  needs_revision: 'bg-orange-100 text-orange-700',
  rejected: 'bg-red-100 text-red-700',
};

const emptyForm = {
  title: '',
  material_type: 'image',
  platform: 'general',
  file_url: '',
  thumbnail_url: '',
  usage_status: 'unused',
  approval_status: 'pending',
  copyright_status: 'owned',
  notes: '',
};

const labelOf = (options: Array<{ value: string; label: string }>, value?: string) => (
  options.find(item => item.value === value)?.label || value || '-'
);

function formatFileSize(size?: number | null) {
  const bytes = Number(size || 0);
  if (!bytes) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function getErrorDetail(err: any, fallback: string) {
  return err?.data?.detail || err?.response?.data?.detail || err?.message || fallback;
}

async function authedFetch(url: string, init: RequestInit = {}, retry = true) {
  const token = getToken();
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });

  if (response.status === 401 && retry) {
    const nextToken = await refreshToken();
    if (nextToken) {
      return authedFetch(url, init, false);
    }
  }
  return response;
}

interface Props {
  customerId: number;
  customerName: string;
}

export default function CustomerMaterialsTab({ customerId, customerName }: Props) {
  const [materials, setMaterials] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formMode, setFormMode] = useState<'upload' | 'link'>('link');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [search, setSearch] = useState('');
  const [filterPlatform, setFilterPlatform] = useState('all');
  const [filterType, setFilterType] = useState('all');
  const [filterUsage, setFilterUsage] = useState('all');

  useEffect(() => {
    void loadMaterials();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const stats = useMemo(() => ({
    total: materials.length,
    approved: materials.filter(item => item.approval_status === 'approved').length,
    unused: materials.filter(item => item.usage_status === 'unused').length,
    used: materials.filter(item => item.usage_status === 'used').length,
  }), [materials]);

  const filteredMaterials = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return materials.filter(item => {
      const text = [item.title, item.file_name, item.notes, item.file_url].filter(Boolean).join(' ').toLowerCase();
      if (keyword && !text.includes(keyword)) return false;
      if (filterPlatform !== 'all' && item.platform !== filterPlatform) return false;
      if (filterType !== 'all' && item.material_type !== filterType) return false;
      if (filterUsage !== 'all' && item.usage_status !== filterUsage) return false;
      return true;
    });
  }, [materials, search, filterPlatform, filterType, filterUsage]);

  const loadMaterials = async () => {
    setLoading(true);
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_materials',
        method: 'GET',
        data: { query: JSON.stringify({ customer_id: customerId }), sort: '-created_at', limit: 200 },
      });
      setMaterials(res?.data?.items || []);
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '加载素材失败'));
    } finally {
      setLoading(false);
    }
  };

  const openCreate = (mode: 'upload' | 'link' = 'link') => {
    setForm(emptyForm);
    setSelectedFile(null);
    setFormMode(mode);
    setEditingId(null);
    setShowForm(true);
  };

  const openEdit = (item: any) => {
    setForm({
      title: item.title || '',
      material_type: item.material_type || 'image',
      platform: item.platform || 'general',
      file_url: item.file_url || '',
      thumbnail_url: item.thumbnail_url || '',
      usage_status: item.usage_status || 'unused',
      approval_status: item.approval_status || 'pending',
      copyright_status: item.copyright_status || 'owned',
      notes: item.notes || '',
    });
    setSelectedFile(null);
    setFormMode(item.source_type === 'upload' ? 'upload' : 'link');
    setEditingId(item.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.title.trim()) {
      toast.error('请填写素材名称');
      return;
    }
    if (!editingId && formMode === 'upload' && !selectedFile) {
      toast.error('请选择要上传的文件');
      return;
    }
    if (formMode === 'link' && !form.file_url.trim()) {
      toast.error('请填写素材链接');
      return;
    }

    setSaving(true);
    try {
      if (editingId) {
        const res = await invokeWithAuth({
          url: `/api/v1/entities/customer_materials/${editingId}`,
          method: 'PUT',
          data: { ...form, updated_at: new Date().toISOString() },
        });
        setMaterials(prev => prev.map(item => (item.id === editingId ? res.data : item)));
        toast.success('素材已更新');
      } else if (formMode === 'upload') {
        const data = new FormData();
        data.append('customer_id', String(customerId));
        data.append('title', form.title);
        data.append('material_type', form.material_type);
        data.append('platform', form.platform);
        data.append('usage_status', form.usage_status);
        data.append('approval_status', form.approval_status);
        data.append('copyright_status', form.copyright_status);
        data.append('notes', form.notes || '');
        data.append('thumbnail_url', form.thumbnail_url || '');
        data.append('file', selectedFile as File);

        const response = await authedFetch('/api/v1/entities/customer_materials/upload', {
          method: 'POST',
          body: data,
        });
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail || '上传失败');
        }
        setMaterials(prev => [body, ...prev]);
        toast.success('素材已上传');
      } else {
        const res = await invokeWithAuth({
          url: '/api/v1/entities/customer_materials',
          method: 'POST',
          data: {
            ...form,
            customer_id: customerId,
            source_type: 'external_link',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        });
        setMaterials(prev => [res.data, ...prev]);
        toast.success('素材链接已保存');
      }
      setShowForm(false);
      setEditingId(null);
      setSelectedFile(null);
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, err?.message || '保存素材失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await invokeWithAuth({ url: `/api/v1/entities/customer_materials/${deleteTarget.id}`, method: 'DELETE' });
      setMaterials(prev => prev.filter(item => item.id !== deleteTarget.id));
      setDeleteTarget(null);
      toast.success('素材已删除');
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '删除素材失败'));
    }
  };

  const quickUpdate = async (item: any, patch: Record<string, any>, message: string) => {
    try {
      const res = await invokeWithAuth({
        url: `/api/v1/entities/customer_materials/${item.id}`,
        method: 'PUT',
        data: { ...patch, updated_at: new Date().toISOString() },
      });
      setMaterials(prev => prev.map(row => (row.id === item.id ? res.data : row)));
      toast.success(message);
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '更新素材失败'));
    }
  };

  const duplicateMaterial = async (item: any) => {
    try {
      const res = await invokeWithAuth({
        url: `/api/v1/entities/customer_materials/${item.id}/duplicate`,
        method: 'POST',
      });
      setMaterials(prev => [res.data, ...prev]);
      toast.success('素材副本已创建');
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '复制素材失败'));
    }
  };

  const copyText = async (text?: string) => {
    if (!text) {
      toast.error('暂无可复制内容');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast.success('已复制');
    } catch {
      toast.error('复制失败');
    }
  };

  const openMaterial = async (item: any) => {
    if (item.file_url) {
      window.open(item.file_url, '_blank', 'noopener,noreferrer');
      return;
    }
    if (!item.file_path) {
      toast.error('暂无素材文件');
      return;
    }
    try {
      const response = await authedFetch(`/api/v1/entities/customer_materials/${item.id}/download`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || '下载失败');
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err: any) {
      console.error(err);
      toast.error(err?.message || '打开素材失败');
    }
  };

  const previewUrl = (item: any) => item.thumbnail_url || item.file_url || '';

  return (
    <div className="space-y-4">
      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <FileImage className="w-4 h-4 text-blue-600" />
                素材管理
              </CardTitle>
              <p className="text-xs text-slate-500 mt-1">
                归档 {customerName} 的图片、菜单、视频、设计稿和发布素材，后续可接 AI 生图。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={loadMaterials} disabled={loading}>
                <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
                刷新
              </Button>
              <Button variant="outline" size="sm" onClick={() => openCreate('upload')}>
                <Upload className="w-3.5 h-3.5 mr-1" />
                上传素材
              </Button>
              <Button size="sm" onClick={() => openCreate('link')} className="bg-blue-600 hover:bg-blue-700">
                <Plus className="w-3.5 h-3.5 mr-1" />
                添加链接
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">素材总数</p><p className="text-xl font-semibold text-slate-800">{stats.total}</p></div>
            <div className="rounded-lg bg-green-50 p-3"><p className="text-xs text-green-700">已确认</p><p className="text-xl font-semibold text-green-700">{stats.approved}</p></div>
            <div className="rounded-lg bg-blue-50 p-3"><p className="text-xs text-blue-700">未使用</p><p className="text-xl font-semibold text-blue-700">{stats.unused}</p></div>
            <div className="rounded-lg bg-amber-50 p-3"><p className="text-xs text-amber-700">已使用</p><p className="text-xl font-semibold text-amber-700">{stats.used}</p></div>
          </div>

          {showForm && (
            <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-4 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-blue-700">
                  {editingId ? '编辑素材' : formMode === 'upload' ? '上传素材' : '添加素材链接'}
                </span>
                {!editingId && (
                  <div className="flex gap-2">
                    <Button size="sm" variant={formMode === 'link' ? 'default' : 'outline'} onClick={() => setFormMode('link')}>链接</Button>
                    <Button size="sm" variant={formMode === 'upload' ? 'default' : 'outline'} onClick={() => setFormMode('upload')}>上传</Button>
                  </div>
                )}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs">素材名称 *</Label>
                  <Input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="例如：餐厅门头照片 / 七月活动海报" />
                </div>
                <div>
                  <Label className="text-xs">平台用途</Label>
                  <NativeSelect value={form.platform} onChange={v => setForm({ ...form, platform: v })} options={platformOptions} />
                </div>
                <div>
                  <Label className="text-xs">素材类型</Label>
                  <NativeSelect value={form.material_type} onChange={v => setForm({ ...form, material_type: v })} options={materialTypeOptions} />
                </div>
                <div>
                  <Label className="text-xs">使用状态</Label>
                  <NativeSelect value={form.usage_status} onChange={v => setForm({ ...form, usage_status: v })} options={usageStatusOptions} />
                </div>
                <div>
                  <Label className="text-xs">确认状态</Label>
                  <NativeSelect value={form.approval_status} onChange={v => setForm({ ...form, approval_status: v })} options={approvalStatusOptions} />
                </div>
                <div>
                  <Label className="text-xs">版权/来源</Label>
                  <NativeSelect value={form.copyright_status} onChange={v => setForm({ ...form, copyright_status: v })} options={copyrightStatusOptions} />
                </div>
              </div>
              {!editingId && formMode === 'upload' ? (
                <div>
                  <Label className="text-xs">选择文件 *</Label>
                  <Input type="file" onChange={e => setSelectedFile(e.target.files?.[0] || null)} />
                  <p className="text-xs text-slate-500 mt-1">支持图片、视频、PDF、Office 文档，单个文件最大 30MB。</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">素材链接 *</Label>
                    <Input value={form.file_url} onChange={e => setForm({ ...form, file_url: e.target.value })} placeholder="https://..." />
                  </div>
                  <div>
                    <Label className="text-xs">缩略图链接</Label>
                    <Input value={form.thumbnail_url} onChange={e => setForm({ ...form, thumbnail_url: e.target.value })} placeholder="可选，用于预览图片" />
                  </div>
                </div>
              )}
              <div>
                <Label className="text-xs">备注</Label>
                <Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={3} placeholder="素材来源、客户要求、发布时间、适合平台等..." />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => { setShowForm(false); setEditingId(null); }}>取消</Button>
                <Button size="sm" onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700">{saving ? '保存中...' : '保存素材'}</Button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="relative md:col-span-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input className="pl-9" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索素材名称、备注、链接..." />
            </div>
            <NativeSelect value={filterPlatform} onChange={setFilterPlatform} options={[{ value: 'all', label: '全部平台' }, ...platformOptions]} />
            <NativeSelect value={filterUsage} onChange={setFilterUsage} options={[{ value: 'all', label: '全部状态' }, ...usageStatusOptions]} />
            <NativeSelect value={filterType} onChange={setFilterType} options={[{ value: 'all', label: '全部类型' }, ...materialTypeOptions]} className="md:col-span-1" />
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-10">
              <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-blue-600" />
            </div>
          ) : filteredMaterials.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 py-10 text-center">
              <FileText className="w-10 h-10 mx-auto text-slate-300" />
              <p className="text-sm text-slate-400 mt-2">暂无素材，先上传文件或添加素材链接</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {filteredMaterials.map(item => {
                const url = previewUrl(item);
                const isImagePreview = url && /\.(png|jpe?g|webp|gif)(\?.*)?$/i.test(url);
                return (
                  <div key={item.id} className="rounded-xl border border-slate-200 bg-white p-3">
                    <div className="flex gap-3">
                      <div className="w-24 h-24 shrink-0 rounded-lg bg-slate-100 border border-slate-200 overflow-hidden flex items-center justify-center">
                        {isImagePreview ? (
                          <img src={url} alt={item.title} className="w-full h-full object-cover" />
                        ) : (
                          <FileImage className="w-8 h-8 text-slate-300" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="font-medium text-sm text-slate-800 truncate">{item.title}</p>
                            <p className="text-xs text-slate-500 mt-0.5 truncate">
                              {item.file_name || item.file_url || '内部素材'} · {formatFileSize(item.file_size)}
                            </p>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className={`h-7 w-7 p-0 ${item.is_favorite ? 'text-red-500' : 'text-slate-400'}`}
                            onClick={() => quickUpdate(item, { is_favorite: !item.is_favorite }, item.is_favorite ? '已取消收藏' : '已收藏')}
                          >
                            <Heart className={`w-4 h-4 ${item.is_favorite ? 'fill-current' : ''}`} />
                          </Button>
                        </div>
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          <Badge variant="secondary" className="text-xs">{labelOf(platformOptions, item.platform)}</Badge>
                          <Badge variant="outline" className="text-xs">{labelOf(materialTypeOptions, item.material_type)}</Badge>
                          <Badge className={usageColors[item.usage_status] || usageColors.unused}>{labelOf(usageStatusOptions, item.usage_status)}</Badge>
                          <Badge className={approvalColors[item.approval_status] || approvalColors.pending}>{labelOf(approvalStatusOptions, item.approval_status)}</Badge>
                        </div>
                        {item.notes && <p className="text-xs text-slate-500 mt-2 line-clamp-2">{item.notes}</p>}
                      </div>
                    </div>
                    <div className="flex flex-wrap justify-between gap-2 mt-3 pt-3 border-t border-slate-100">
                      <div className="flex flex-wrap gap-1.5">
                        <Button size="sm" variant="outline" className="h-8" onClick={() => openMaterial(item)}>
                          {item.file_url ? <ExternalLink className="w-3.5 h-3.5 mr-1" /> : <Download className="w-3.5 h-3.5 mr-1" />}
                          {item.file_url ? '打开' : '下载'}
                        </Button>
                        {item.file_url && <Button size="sm" variant="outline" className="h-8" onClick={() => copyText(item.file_url)}><Copy className="w-3.5 h-3.5 mr-1" />复制链接</Button>}
                        <Button size="sm" variant="outline" className="h-8" onClick={() => duplicateMaterial(item)}><Link2 className="w-3.5 h-3.5 mr-1" />复制素材</Button>
                      </div>
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 text-green-600 hover:text-green-700 hover:bg-green-50"
                          onClick={() => quickUpdate(item, { usage_status: item.usage_status === 'used' ? 'unused' : 'used', used_at: item.usage_status === 'used' ? null : new Date().toISOString() }, item.usage_status === 'used' ? '已标记为未使用' : '已标记为已使用')}
                        >
                          {item.usage_status === 'used' ? '取消使用' : '标记使用'}
                        </Button>
                        <Button size="sm" variant="ghost" className="h-8 text-blue-600 hover:bg-blue-50" onClick={() => openEdit(item)}><Edit className="w-3.5 h-3.5" /></Button>
                        <Button size="sm" variant="ghost" className="h-8 text-red-600 hover:bg-red-50" onClick={() => setDeleteTarget(item)}><Trash2 className="w-3.5 h-3.5" /></Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={open => !open && setDeleteTarget(null)}
        title="确认删除素材"
        description={deleteTarget ? `确定要删除「${deleteTarget.title}」吗？如果是上传文件，文件也会一并移除。` : ''}
        confirmText="删除"
        variant="destructive"
        onConfirm={handleDelete}
      />
    </div>
  );
}
