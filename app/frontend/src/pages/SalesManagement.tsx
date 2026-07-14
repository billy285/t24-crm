import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { client } from '@/lib/api';
import { useRole } from '@/lib/role-context';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Search, ArrowRight, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

const stageLabels: Record<string, string> = { new: '新线索', following: '跟进中', quoted: '已报价', negotiating: '谈判中', paused: '暂缓联系', lost: '未成交' };
const stageColors: Record<string, string> = { new: 'bg-blue-100 text-blue-700', following: 'bg-amber-100 text-amber-700', quoted: 'bg-cyan-100 text-cyan-700', negotiating: 'bg-orange-100 text-orange-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };

export default function SalesManagement() {
  const navigate = useNavigate();
  const { employee, dataScope } = useRole();
  const [customers, setCustomers] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const loadData = async () => {
    setLoading(true);
    try {
      let items = (await client.entities.customers.query({ limit: 1000, sort: '-updated_at' }))?.data?.items || [];
      if (dataScope === 'self' && employee) items = items.filter((item: any) => item.sales_person === employee.name || item.sales_employee_id === employee.id);
      setCustomers(items.filter((item: any) => item.status !== 'closed'));
    } catch (error: any) { toast.error(error?.message || '销售数据加载失败'); } finally { setLoading(false); }
  };
  useEffect(() => { loadData(); }, [dataScope, employee?.id]);
  const rows = useMemo(() => customers.filter(item => `${item.business_name || ''} ${item.contact_name || ''} ${item.phone || ''} ${item.city || ''}`.toLowerCase().includes(search.toLowerCase())), [customers, search]);
  return <div className="app-page space-y-5">
    <div className="app-page-title flex-col sm:flex-row items-start sm:items-center"><div><p className="text-xs font-medium uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Sales</p><h1 className="mt-1 text-2xl font-bold text-slate-900">销售管理</h1><p className="mt-1 text-sm text-slate-500">这里只管理成交前线索，成交后进入客户管理和成交管理</p></div><Button variant="outline" size="sm" onClick={loadData}><RefreshCw className={`mr-1 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button></div>
    <Card className="border-blue-100 bg-blue-50/60"><CardContent className="p-4"><div className="flex flex-wrap items-center gap-2 text-xs text-blue-800"><span className="font-semibold">销售流程</span><Badge className="bg-white text-blue-700">新线索</Badge><span>→</span><Badge className="bg-white text-blue-700">跟进中</Badge><span>→</span><Badge className="bg-white text-blue-700">已报价</Badge><span>→</span><Badge className="bg-white text-blue-700">确认成交</Badge><span>→</span><span className="font-medium">进入客户管理 + 成交管理</span></div></CardContent></Card>
    <Card><CardContent className="p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold text-slate-800">待转化线索</p><p className="mt-1 text-xs text-slate-500">共 {rows.length} 个，点击成交录入后才会进入正式成交流程</p></div><div className="relative w-full sm:w-80"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索商家、联系人、电话或城市" className="pl-9" /></div></div></CardContent></Card>
    {loading ? <div className="app-empty">正在加载销售线索...</div> : rows.length === 0 ? <div className="app-empty">暂无待转化线索</div> : <div className="grid gap-3 lg:grid-cols-2">{rows.map(customer => <Card key={customer.id} className="app-card-hover"><CardContent className="p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="truncate font-semibold text-slate-900">{customer.business_name || '未命名商家'}</h2><p className="mt-1 text-xs text-slate-500">{customer.contact_name || '暂无联系人'} · {customer.phone || '暂无电话'} · {customer.city || '城市未填写'}</p></div><Badge className={stageColors[customer.status] || 'bg-slate-100 text-slate-600'}>{stageLabels[customer.status] || customer.status || '待跟进'}</Badge></div><div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500"><span>负责人：{customer.sales_person || '未分配'}</span><span>来源：{customer.source || '未填写'}</span></div><div className="mt-4 flex justify-end"><Button size="sm" className="bg-blue-600 hover:bg-blue-700" onClick={() => navigate(`/deals?customer_id=${customer.id}`)}>进入成交录入 <ArrowRight className="ml-1 h-4 w-4" /></Button></div></CardContent></Card>)}</div>}
  </div>;
}
