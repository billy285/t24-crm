import { useState, useEffect } from 'react';
import { client } from '../lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { Plus, Edit, Trash2 } from 'lucide-react';

export default function SystemOptions() {
  const [options, setOptions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingOption, setEditingOption] = useState<any>(null);
  const [form, setForm] = useState({ category: '', key: '', label: '', order: 0 });

  useEffect(() => {
    loadOptions();
  }, []);

  const loadOptions = async () => {
    setLoading(true);
    try {
      const res = await client.get('/api/v1/system-options');
      setOptions(res?.data || []);
    } catch (err) {
      console.error("Failed to load system options", err);
      toast.error('加载选项失败');
    }
    setLoading(false);
  };

  const handleSave = async () => {
    if (!form.category || !form.key || !form.label) {
      toast.error('请填写所有必填字段');
      return;
    }
    try {
      if (editingOption) {
        await client.put(`/api/v1/system-options/${editingOption.id}`, form);
        toast.success('选项已更新');
      } else {
        await client.post('/api/v1/system-options', form);
        toast.success('选项已创建');
      }
      setShowForm(false);
      setEditingOption(null);
      loadOptions();
    } catch (err) {
      toast.error('保存失败');
      console.error("Failed to save option", err);
    }
  };

  const openForm = (option: any = null) => {
    if (option) {
      setForm({ category: option.category, key: option.key, label: option.label, order: option.order || 0 });
      setEditingOption(option);
    } else {
      setForm({ category: '', key: '', label: '', order: 0 });
      setEditingOption(null);
    }
    setShowForm(true);
  };

  const groupedOptions = options.reduce((acc, option) => {
    (acc[option.category] = acc[option.category] || []).push(option);
    return acc;
  }, {} as Record<string, any[]>);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">系统选项管理</h2>
        <Button onClick={() => openForm()}><Plus className="w-4 h-4 mr-2" />新增选项</Button>
      </div>

      {loading ? <p>加载中...</p> : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {Object.entries(groupedOptions).map(([category, opts]) => (
            <Card key={category}>
              <CardHeader><CardTitle>{category}</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {opts.sort((a,b) => a.order - b.order).map(opt => (
                    <li key={opt.id} className="flex items-center justify-between p-2 rounded-md hover:bg-slate-50">
                      <span>{opt.label} <span className="text-xs text-slate-400">({opt.key})</span></span>
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openForm(opt)}><Edit className="w-4 h-4" /></Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editingOption ? '编辑选项' : '新增选项'}</DialogTitle></DialogHeader>
          <div className="space-y-4 py-4">
            <div><Label>分类 (Category)</Label><Input value={form.category} onChange={e => setForm({...form, category: e.target.value})} placeholder="e.g., customer_status" /></div>
            <div><Label>键 (Key)</Label><Input value={form.key} onChange={e => setForm({...form, key: e.target.value})} placeholder="e.g., new_lead" /></div>
            <div><Label>标签 (Label)</Label><Input value={form.label} onChange={e => setForm({...form, label: e.target.value})} placeholder="e.g., 新线索" /></div>
            <div><Label>排序 (Order)</Label><Input type="number" value={form.order} onChange={e => setForm({...form, order: Number(e.target.value)})} /></div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowForm(false)}>取消</Button>
            <Button onClick={handleSave}>保存</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
