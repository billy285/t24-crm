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
  Sparkles,
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
  { value: 'yelp', label: 'Yelp' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'brand_website', label: '品牌官网' },
  { value: 'ads_campaign', label: '广告投放' },
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

const itemTypeOptions = [
  { value: 'dish', label: '菜品' },
  { value: 'service', label: '服务项目' },
  { value: 'product', label: '产品' },
  { value: 'package', label: '套餐' },
  { value: 'other', label: '其他' },
];

const itemStatusOptions = [
  { value: 'active', label: '启用' },
  { value: 'paused', label: '暂停' },
  { value: 'archived', label: '归档' },
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
  linked_item_id: '',
  file_url: '',
  thumbnail_url: '',
  usage_status: 'unused',
  approval_status: 'pending',
  copyright_status: 'owned',
  notes: '',
};

const emptyItemForm = {
  name: '',
  item_type: 'dish',
  category: '',
  price: '',
  selling_points: '',
  suitable_platforms: [] as string[],
  is_featured: false,
  status: 'active',
  notes: '',
};

const labelOf = (options: Array<{ value: string; label: string }>, value?: string) => (
  options.find(item => item.value === value)?.label || value || '-'
);

function parsePlatformList(value?: string | string[] | null): string[] {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) return parsed.filter(Boolean);
  } catch {
    // Fall back to comma splitting for older or manually edited records.
  }
  return String(value).split(',').map(item => item.trim()).filter(Boolean);
}

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
  const [menuItems, setMenuItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formMode, setFormMode] = useState<'upload' | 'link'>('link');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [showItemForm, setShowItemForm] = useState(false);
  const [editingItemId, setEditingItemId] = useState<number | null>(null);
  const [itemForm, setItemForm] = useState(emptyItemForm);
  const [itemSaving, setItemSaving] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleteItemTarget, setDeleteItemTarget] = useState<any>(null);
  const [search, setSearch] = useState('');
  const [filterPlatform, setFilterPlatform] = useState('all');
  const [filterType, setFilterType] = useState('all');
  const [filterUsage, setFilterUsage] = useState('all');
  const [filterLinkedItem, setFilterLinkedItem] = useState('all');
  const [aiMatching, setAiMatching] = useState(false);
  const [aiMatchResult, setAiMatchResult] = useState<any>(null);

  useEffect(() => {
    void loadMaterials();
    void loadMenuItems();
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
      const text = [item.title, item.file_name, item.notes, item.file_url, item.linked_item_snapshot].filter(Boolean).join(' ').toLowerCase();
      if (keyword && !text.includes(keyword)) return false;
      if (filterPlatform !== 'all' && item.platform !== filterPlatform) return false;
      if (filterType !== 'all' && item.material_type !== filterType) return false;
      if (filterUsage !== 'all' && item.usage_status !== filterUsage) return false;
      if (filterLinkedItem === 'unbound' && item.linked_item_id) return false;
      if (!['all', 'unbound'].includes(filterLinkedItem) && String(item.linked_item_id || '') !== filterLinkedItem) return false;
      return true;
    });
  }, [materials, search, filterPlatform, filterType, filterUsage, filterLinkedItem]);

  const materialTitleMap = useMemo(() => (
    Object.fromEntries(materials.map(item => [String(item.id), item.title || item.file_name || `素材 #${item.id}`]))
  ), [materials]);

  const menuItemMap = useMemo(() => (
    Object.fromEntries(menuItems.map(item => [String(item.id), item]))
  ), [menuItems]);

  const linkedItemOptions = useMemo(() => [
    { value: '', label: '不绑定具体菜品/项目' },
    ...menuItems.map(item => ({
      value: String(item.id),
      label: `${item.name}${item.category ? ` · ${item.category}` : ''}`,
    })),
  ], [menuItems]);

  const activePlatformOptions = useMemo(() => (
    platformOptions.filter(item => !['general', 'other'].includes(item.value))
  ), []);

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

  const loadMenuItems = async () => {
    setItemsLoading(true);
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_menu_items',
        method: 'GET',
        data: { query: JSON.stringify({ customer_id: customerId }), sort: '-updated_at', limit: 300 },
      });
      setMenuItems(res?.data?.items || []);
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '加载菜单/服务项目失败'));
    } finally {
      setItemsLoading(false);
    }
  };

  const refreshAll = () => {
    void loadMaterials();
    void loadMenuItems();
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
      linked_item_id: item.linked_item_id ? String(item.linked_item_id) : '',
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

  const openCreateItem = () => {
    setItemForm(emptyItemForm);
    setEditingItemId(null);
    setShowItemForm(true);
  };

  const openEditItem = (item: any) => {
    setItemForm({
      name: item.name || '',
      item_type: item.item_type || 'dish',
      category: item.category || '',
      price: item.price || '',
      selling_points: item.selling_points || '',
      suitable_platforms: parsePlatformList(item.suitable_platforms),
      is_featured: Boolean(item.is_featured),
      status: item.status || 'active',
      notes: item.notes || '',
    });
    setEditingItemId(item.id);
    setShowItemForm(true);
  };

  const toggleItemPlatform = (platform: string) => {
    setItemForm(prev => {
      const current = new Set(prev.suitable_platforms || []);
      if (current.has(platform)) {
        current.delete(platform);
      } else {
        current.add(platform);
      }
      return { ...prev, suitable_platforms: Array.from(current) };
    });
  };

  const saveMenuItem = async () => {
    if (!itemForm.name.trim()) {
      toast.error('请填写菜品/服务项目名称');
      return;
    }
    setItemSaving(true);
    try {
      const payload = {
        ...itemForm,
        name: itemForm.name.trim(),
        suitable_platforms: JSON.stringify(itemForm.suitable_platforms || []),
        customer_id: customerId,
        updated_at: new Date().toISOString(),
      };
      if (editingItemId) {
        const res = await invokeWithAuth({
          url: `/api/v1/entities/customer_menu_items/${editingItemId}`,
          method: 'PUT',
          data: payload,
        });
        setMenuItems(prev => prev.map(item => (item.id === editingItemId ? res.data : item)));
        toast.success('项目已更新');
      } else {
        const res = await invokeWithAuth({
          url: '/api/v1/entities/customer_menu_items',
          method: 'POST',
          data: { ...payload, created_at: new Date().toISOString() },
        });
        setMenuItems(prev => [res.data, ...prev]);
        toast.success('项目已保存');
      }
      setShowItemForm(false);
      setEditingItemId(null);
      setItemForm(emptyItemForm);
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '保存菜单/服务项目失败'));
    } finally {
      setItemSaving(false);
    }
  };

  const handleDeleteItem = async () => {
    if (!deleteItemTarget) return;
    try {
      await invokeWithAuth({ url: `/api/v1/entities/customer_menu_items/${deleteItemTarget.id}`, method: 'DELETE' });
      setMenuItems(prev => prev.filter(item => item.id !== deleteItemTarget.id));
      setMaterials(prev => prev.map(item => (
        item.linked_item_id === deleteItemTarget.id
          ? { ...item, linked_item_id: null, linked_item_snapshot: deleteItemTarget.name }
          : item
      )));
      setDeleteItemTarget(null);
      toast.success('项目已删除，历史素材会保留原绑定名称');
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, '删除菜单/服务项目失败'));
    }
  };

  const materialPayload = () => ({
    ...form,
    linked_item_id: form.linked_item_id ? Number(form.linked_item_id) : null,
  });

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
          data: { ...materialPayload(), updated_at: new Date().toISOString() },
        });
        setMaterials(prev => prev.map(item => (item.id === editingId ? res.data : item)));
        toast.success('素材已更新');
      } else if (formMode === 'upload') {
        const data = new FormData();
        data.append('customer_id', String(customerId));
        data.append('title', form.title);
        data.append('material_type', form.material_type);
        data.append('platform', form.platform);
        if (form.linked_item_id) data.append('linked_item_id', form.linked_item_id);
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
            ...materialPayload(),
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

  const generateAiMatch = async () => {
    if (materials.length === 0) {
      toast.error('请先上传或添加客户素材');
      return;
    }
    setAiMatching(true);
    try {
      const targetPlatforms = Array.from(new Set(
        materials
          .map(item => item.platform)
          .filter(platform => platform && !['general', 'other'].includes(platform))
      ));
      const res = await invokeWithAuth({
        url: '/api/v1/entities/customer_materials/ai-match',
        method: 'POST',
        data: {
          customer_id: customerId,
          target_platforms: targetPlatforms,
          extra_requirements: '请优先根据素材绑定的菜品/服务项目匹配平台；不要让素材不相关，不要未经确认直接发布，重复素材需要换角度使用。',
        },
      });
      setAiMatchResult(res.data);
      if (res.data?.ai_used) {
        toast.success('AI素材匹配已生成');
      } else {
        toast.warning(res.data?.warning || '已生成基础素材匹配建议');
      }
    } catch (err: any) {
      console.error(err);
      toast.error(getErrorDetail(err, 'AI素材匹配失败'));
    } finally {
      setAiMatching(false);
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
                先录菜单/服务项目，再把图片、菜单、视频和设计稿绑定到具体项目，AI 匹配会更准。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={refreshAll} disabled={loading || itemsLoading}>
                <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
                刷新
              </Button>
              <Button variant="outline" size="sm" onClick={generateAiMatch} disabled={loading || aiMatching || materials.length === 0} className="border-emerald-200 text-emerald-700 hover:bg-emerald-50">
                <Sparkles className={`w-3.5 h-3.5 mr-1 ${aiMatching ? 'animate-pulse' : ''}`} />
                {aiMatching ? '匹配中...' : 'AI匹配素材'}
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

          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 space-y-3">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <h4 className="text-sm font-semibold text-slate-800">菜单/服务项目库</h4>
                <p className="text-xs text-slate-500 mt-1">
                  餐饮录菜品，美业录项目。素材绑定后，运营不会把不相关图片乱用。
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={openCreateItem} className="self-start">
                <Plus className="w-3.5 h-3.5 mr-1" />
                新增项目
              </Button>
            </div>

            {showItemForm && (
              <div className="rounded-lg border border-blue-200 bg-white p-3 space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div className="md:col-span-2">
                    <Label className="text-xs">名称 *</Label>
                    <Input value={itemForm.name} onChange={e => setItemForm({ ...itemForm, name: e.target.value })} placeholder="例如：招牌牛肉面 / 美甲单色款 / 皮肤管理" />
                  </div>
                  <div>
                    <Label className="text-xs">类型</Label>
                    <NativeSelect value={itemForm.item_type} onChange={v => setItemForm({ ...itemForm, item_type: v })} options={itemTypeOptions} />
                  </div>
                  <div>
                    <Label className="text-xs">状态</Label>
                    <NativeSelect value={itemForm.status} onChange={v => setItemForm({ ...itemForm, status: v })} options={itemStatusOptions} />
                  </div>
                  <div>
                    <Label className="text-xs">分类</Label>
                    <Input value={itemForm.category} onChange={e => setItemForm({ ...itemForm, category: e.target.value })} placeholder="主食 / 招牌 / 美甲 / 护肤" />
                  </div>
                  <div>
                    <Label className="text-xs">价格</Label>
                    <Input value={itemForm.price} onChange={e => setItemForm({ ...itemForm, price: e.target.value })} placeholder="$9.99 / 视项目而定" />
                  </div>
                  <div className="md:col-span-2">
                    <Label className="text-xs">卖点</Label>
                    <Input value={itemForm.selling_points} onChange={e => setItemForm({ ...itemForm, selling_points: e.target.value })} placeholder="例如：分量足、适合午餐、客户最常点、节日主推" />
                  </div>
                </div>
                <div>
                  <Label className="text-xs">适合平台</Label>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {activePlatformOptions.map(option => {
                      const selected = itemForm.suitable_platforms.includes(option.value);
                      return (
                        <Button
                          key={option.value}
                          type="button"
                          size="sm"
                          variant={selected ? 'default' : 'outline'}
                          className={selected ? 'h-8 bg-blue-600 hover:bg-blue-700' : 'h-8'}
                          onClick={() => toggleItemPlatform(option.value)}
                        >
                          {option.label}
                        </Button>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <Label className="text-xs">备注</Label>
                  <Textarea value={itemForm.notes} onChange={e => setItemForm({ ...itemForm, notes: e.target.value })} rows={2} placeholder="可以写客户要求、禁忌、季节性、是否真实图片等..." />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant={itemForm.is_featured ? 'default' : 'outline'}
                    className={itemForm.is_featured ? 'bg-amber-500 hover:bg-amber-600' : ''}
                    onClick={() => setItemForm({ ...itemForm, is_featured: !itemForm.is_featured })}
                  >
                    {itemForm.is_featured ? '已设为主推' : '设为主推'}
                  </Button>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setShowItemForm(false); setEditingItemId(null); setItemForm(emptyItemForm); }}>取消</Button>
                    <Button size="sm" onClick={saveMenuItem} disabled={itemSaving} className="bg-blue-600 hover:bg-blue-700">
                      {itemSaving ? '保存中...' : '保存项目'}
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {itemsLoading ? (
              <p className="text-xs text-slate-400">正在加载项目库...</p>
            ) : menuItems.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 bg-white py-6 text-center">
                <p className="text-sm text-slate-500">还没有菜单/服务项目，建议先录入主推项目。</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {menuItems.slice(0, 8).map(item => {
                  const platforms = parsePlatformList(item.suitable_platforms);
                  return (
                    <div key={item.id} className="rounded-lg bg-white border border-slate-200 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-medium text-sm text-slate-800 truncate">{item.name}</span>
                            {item.is_featured && <Badge className="bg-amber-100 text-amber-700">主推</Badge>}
                            <Badge variant="secondary">{labelOf(itemTypeOptions, item.item_type)}</Badge>
                          </div>
                          <p className="text-xs text-slate-500 mt-1">
                            {[item.category, item.price].filter(Boolean).join(' · ') || '未填写分类/价格'}
                          </p>
                        </div>
                        <div className="flex gap-1">
                          <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-blue-600 hover:bg-blue-50" onClick={() => openEditItem(item)}>
                            <Edit className="w-3.5 h-3.5" />
                          </Button>
                          <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-red-600 hover:bg-red-50" onClick={() => setDeleteItemTarget(item)}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>
                      {item.selling_points && <p className="text-xs text-slate-600 mt-2 line-clamp-2">{item.selling_points}</p>}
                      {platforms.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {platforms.slice(0, 5).map(platform => (
                            <Badge key={platform} variant="outline" className="text-[10px]">{labelOf(platformOptions, platform)}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {menuItems.length > 8 && <p className="text-xs text-slate-400">已显示前 8 个项目，素材绑定下拉中可选择全部项目。</p>}
          </div>

          {aiMatchResult && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 space-y-4">
              <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-emerald-600" />
                    <h4 className="text-sm font-semibold text-emerald-800">AI素材智能匹配</h4>
                    <Badge className={aiMatchResult.ai_used ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}>
                      {aiMatchResult.ai_used ? 'AI生成' : '规则建议'}
                    </Badge>
                  </div>
                  <p className="text-sm text-slate-700 mt-2">{aiMatchResult.summary}</p>
                  {aiMatchResult.warning && <p className="text-xs text-amber-700 mt-1">{aiMatchResult.warning}</p>}
                </div>
                <Button variant="ghost" size="sm" className="self-start text-slate-500" onClick={() => setAiMatchResult(null)}>收起</Button>
              </div>

              {Array.isArray(aiMatchResult.platform_matches) && aiMatchResult.platform_matches.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-600 mb-2">平台匹配</p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {aiMatchResult.platform_matches.slice(0, 6).map((item: any, idx: number) => (
                      <div key={`${item.platform || idx}`} className="rounded-lg bg-white border border-emerald-100 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium text-slate-800">{item.platform_label || labelOf(platformOptions, item.platform)}</span>
                          <Badge variant="outline" className="text-xs">{Number(item.score || 0)}分</Badge>
                        </div>
                        <p className="text-xs text-slate-500 mt-1">{item.reason}</p>
                        {Array.isArray(item.matched_material_ids) && item.matched_material_ids.length > 0 && (
                          <p className="text-[11px] text-emerald-700 mt-2">
                            可用素材：{item.matched_material_ids.slice(0, 4).map((id: any) => materialTitleMap[String(id)] || `#${id}`).join('、')}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(aiMatchResult.material_suggestions) && aiMatchResult.material_suggestions.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-600 mb-2">素材使用建议</p>
                  <div className="space-y-2">
                    {aiMatchResult.material_suggestions.slice(0, 8).map((item: any, idx: number) => (
                      <div key={`${item.material_id || idx}`} className="rounded-lg bg-white border border-slate-100 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-slate-800">{item.title || materialTitleMap[String(item.material_id)] || `素材 #${item.material_id}`}</span>
                          {(item.recommended_platform_labels || []).slice(0, 4).map((label: string) => (
                            <Badge key={label} variant="secondary" className="text-[10px]">{label}</Badge>
                          ))}
                        </div>
                        <p className="text-xs text-slate-600 mt-1">{item.usage_idea}</p>
                        {item.risk_note && <p className="text-[11px] text-amber-700 mt-1">注意：{item.risk_note}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Array.isArray(aiMatchResult.cautions) && aiMatchResult.cautions.length > 0 && (
                  <div className="rounded-lg bg-amber-50 border border-amber-100 p-3">
                    <p className="text-xs font-medium text-amber-800 mb-1">风险提醒</p>
                    <ul className="space-y-1 text-xs text-amber-700">
                      {aiMatchResult.cautions.slice(0, 6).map((item: string, idx: number) => <li key={idx}>- {item}</li>)}
                    </ul>
                  </div>
                )}
                {Array.isArray(aiMatchResult.next_actions) && aiMatchResult.next_actions.length > 0 && (
                  <div className="rounded-lg bg-blue-50 border border-blue-100 p-3">
                    <p className="text-xs font-medium text-blue-800 mb-1">下一步动作</p>
                    <ul className="space-y-1 text-xs text-blue-700">
                      {aiMatchResult.next_actions.slice(0, 6).map((item: string, idx: number) => <li key={idx}>- {item}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}

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
                  <Label className="text-xs">关联菜品/服务项目</Label>
                  <NativeSelect value={form.linked_item_id} onChange={v => setForm({ ...form, linked_item_id: v })} options={linkedItemOptions} />
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

          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            <div className="relative md:col-span-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input className="pl-9" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索素材名称、备注、链接..." />
            </div>
            <NativeSelect value={filterPlatform} onChange={setFilterPlatform} options={[{ value: 'all', label: '全部平台' }, ...platformOptions]} />
            <NativeSelect value={filterUsage} onChange={setFilterUsage} options={[{ value: 'all', label: '全部状态' }, ...usageStatusOptions]} />
            <NativeSelect value={filterType} onChange={setFilterType} options={[{ value: 'all', label: '全部类型' }, ...materialTypeOptions]} />
            <NativeSelect
              value={filterLinkedItem}
              onChange={setFilterLinkedItem}
              options={[
                { value: 'all', label: '全部项目' },
                { value: 'unbound', label: '未绑定项目' },
                ...linkedItemOptions.filter(option => option.value),
              ]}
            />
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
                const linkedItemName = item.linked_item_id
                  ? (menuItemMap[String(item.linked_item_id)]?.name || item.linked_item_snapshot)
                  : item.linked_item_snapshot;
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
                          {linkedItemName && <Badge className="bg-indigo-100 text-indigo-700">关联：{linkedItemName}</Badge>}
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
      <ConfirmDialog
        open={!!deleteItemTarget}
        onOpenChange={open => !open && setDeleteItemTarget(null)}
        title="确认删除菜单/服务项目"
        description={deleteItemTarget ? `确定要删除「${deleteItemTarget.name}」吗？已绑定素材会保留历史名称，但不再关联到当前项目。` : ''}
        confirmText="删除"
        variant="destructive"
        onConfirm={handleDeleteItem}
      />
    </div>
  );
}
