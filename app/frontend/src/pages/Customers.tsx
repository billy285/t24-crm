import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { countries, getStatesForCountry, getCitiesForState, getCountryLabel, getStateLabel } from '../lib/country-state-data';
import { logOperation } from '../lib/operation-log-helper';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus, Search, ArrowLeft, Phone, Mail, MapPin, Globe, Edit, Trash2, SlidersHorizontal, X, MessageSquarePlus, Columns3, AlertCircle, UserPlus, Users, ArrowRightLeft } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ExportButton from '@/components/ExportButton';
import ImportCustomers from '@/components/ImportCustomers';
import ConfirmDialog from '@/components/ConfirmDialog';
import MediaAccountsTab from '@/components/MediaAccountsTab';
import OperationLogsTab from '@/components/OperationLogsTab';
import { loadSettings, generateNextCode, type CustomerCodeSettings } from '../lib/customer-code-settings';

const defaultIndustryLabels: Record<string, string> = { restaurant: '餐厅', beauty_services: '美业', retail: '零售', education: '教育', other: '其他' };

// For Customer Status
const customerStatusOptions = [
  { value: '', label: '请选择客户状态' },
  { value: 'potential_customer', label: '潜在客户' },
  { value: 'new_customer', label: '新客户' },
  { value: 'in_service', label: '服务中' },
  { value: 'paused_service', label: '暂停服务' },
  { value: 'lost_customer', label: '已流失' },
];

// For Customer Level
const customerLevelOptions = [
  { value: '', label: '请选择客户等级' },
  { value: 'normal', label: '普通' },
  { value: 'important', label: '重要' },
  { value: 'vip', label: 'VIP' },
];

// For Customer Source
const customerSourceOptions = [
  { value: '', label: '请选择客户来源' },
  { value: 'phone_sales', label: '电话销售' },
  { value: 'customer_referral', label: '客户推荐' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'google_ads', label: 'Google' },
  { value: 'website_consultation', label: '网站咨询' },
  { value: 'other', label: '其他' },
];
const CUSTOM_INDUSTRIES_KEY = 'crm_custom_industries';
function loadIndustryLabels(): Record<string, string> {
  try {
    const stored = localStorage.getItem(CUSTOM_INDUSTRIES_KEY);
    if (stored) {
      const custom = JSON.parse(stored) as Record<string, string>;
      return { ...defaultIndustryLabels, ...custom };
    }
  } catch { /* ignore */ }
  return { ...defaultIndustryLabels };
}
function saveCustomIndustry(key: string, label: string) {
  try {
    const stored = localStorage.getItem(CUSTOM_INDUSTRIES_KEY);
    const custom = stored ? JSON.parse(stored) : {};
    custom[key] = label;
    localStorage.setItem(CUSTOM_INDUSTRIES_KEY, JSON.stringify(custom));
  } catch { /* ignore */ }
}
const statusLabels: Record<string, string> = { new: '新线索', following: '跟进中', closed: '已成交', paused: '暂停', lost: '流失' };
const statusColors: Record<string, string> = { new: 'bg-blue-100 text-blue-700', following: 'bg-amber-100 text-amber-700', closed: 'bg-green-100 text-green-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };
const levelLabels: Record<string, string> = { high: '高意向', normal: '普通', low: '低意向', vip: 'VIP' };
const levelColors: Record<string, string> = { high: 'bg-orange-100 text-orange-700', normal: 'bg-slate-100 text-slate-600', low: 'bg-gray-100 text-gray-500', vip: 'bg-purple-100 text-purple-700' };
const sourceLabels: Record<string, string> = { phone: '电话销售', referral: '转介绍', ads: '广告', private: '私域', returning: '老客户', other: '其他' };
const stageLabels: Record<string, string> = { new_lead: '新线索', contacted: '已联系', communicating: '沟通中', quoted: '已报价', considering: '考虑中', pending_close: '待成交', closed: '已成交', not_closed: '未成交', lost: '流失', follow_later: '后续再跟进' };
const productLabels: Record<string, string> = { ordering_system: '线上点餐系统', social_media: '新媒体代运营', ads: '广告投放', website: '网站设计', combo: '组合套餐' };
const cycleLabels: Record<string, string> = { monthly: '月付', quarterly: '季付', semi_annual: '半年付', annual: '年付' };
const payMethodLabels: Record<string, string> = { cash: '现金', check: '支票', zelle: 'Zelle', wire: '电汇', credit_card: '信用卡', other: '其他' };
const subStatusLabels: Record<string, string> = { active: '正常', expiring_soon: '即将到期', expired: '已到期', paused: '暂停', lost: '流失' };
const subStatusColors: Record<string, string> = { active: 'bg-green-100 text-green-700', expiring_soon: 'bg-amber-100 text-amber-700', expired: 'bg-red-100 text-red-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };
const methodLabels: Record<string, string> = { phone: '电话', wechat: '微信', sms: '短信', email: '邮件' };
const contactRoleLabels: Record<string, string> = { boss: '老板', manager: '经理', staff: '员工', other: '其他' };

const emptyForm = {
  customer_code: '', business_name: '', contact_name: '', phone: '', wechat: '', email: '',
  address: '', city: '', state: 'CA', country: 'US',
  industry: '', // Default to empty for "请选择"
  website: '',
  google_business_link: '', facebook_link: '', instagram_link: '', yelp_link: '', tiktok_link: '',
  has_ordering_system: false, current_platform: '无', monthly_orders: 0,
  customer_source: '', // New field
  sales_person: '', sales_employee_id: '' as string | number,
  customer_level: '', // New field
  customer_status: '', // New field
  notes: '',
};

const allColumns = [
  { key: 'customer_code', label: '编号', d: true }, { key: 'business_name', label: '商家名称', d: true },
  { key: 'contact_name', label: '联系人', d: true }, { key: 'phone', label: '电话', d: true },
  { key: 'city', label: '城市', d: true }, { key: 'industry', label: '行业', d: true },
  { key: 'status', label: '状态', d: true }, { key: 'level', label: '等级', d: true },
  { key: 'sales_person', label: '负责人', d: true }, { key: 'country', label: '国家', d: false },
  { key: 'state', label: '州/省', d: false }, { key: 'email', label: '邮箱', d: false },
  { key: 'wechat', label: '微信', d: false }, { key: 'source', label: '来源', d: false },
];

const COLS_KEY = 'crm_visible_columns';
function loadCols(): string[] {
  try { const s = localStorage.getItem(COLS_KEY); if (s) return JSON.parse(s); } catch { /* */ }
  return allColumns.filter(c => c.d).map(c => c.key);
}

export default function Customers() {
  const { role, employee, hasPermission, isAdmin, dataScope } = useRole();
  const [searchParams] = useSearchParams();
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterIndustry, setFilterIndustry] = useState('all');
  const [filterLevel, setFilterLevel] = useState('all');
  const [filterSource, setFilterSource] = useState('all');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advFilters, setAdvFilters] = useState({ business_name: '', contact_name: '', phone: '', wechat: '', email: '', country: '', state: '', city: '' });
  const advFilterCount = Object.values(advFilters).filter(v => v.trim()).length;
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [selectedCustomer, setSelectedCustomer] = useState<any>(null);
  const [followUps, setFollowUps] = useState<any[]>([]);
  const [deals, setDeals] = useState<any[]>([]);
  const [payments, setPayments] = useState<any[]>([]);
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [codeSettings, setCodeSettings] = useState<CustomerCodeSettings>(loadSettings());
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null);
  const [visibleCols, setVisibleCols] = useState<string[]>(loadCols());
  const [showColPicker, setShowColPicker] = useState(false);
  const [showFollowForm, setShowFollowForm] = useState(false);
  const [savingFollow, setSavingFollow] = useState(false);
  const [editingFollowId, setEditingFollowId] = useState<number | null>(null);
  const [deleteFollowTarget, setDeleteFollowTarget] = useState<any>(null);
  const [deletingFollow, setDeletingFollow] = useState(false);
  const emptyFollowForm = { contact_method: 'phone', content: '', customer_needs: '', customer_pain_points: '', has_quoted: false, quote_plan: '', close_probability: 30, stage: 'communicating', next_follow_date: '' };
  const [followForm, setFollowForm] = useState(emptyFollowForm);

  // Owner contacts state
  const [contacts, setContacts] = useState<any[]>([]);
  const [showContactForm, setShowContactForm] = useState(false);
  const [editingContactId, setEditingContactId] = useState<number | null>(null);
  const [savingContact, setSavingContact] = useState(false);
  const [deleteContactTarget, setDeleteContactTarget] = useState<any>(null);
  const [deletingContact, setDeletingContact] = useState(false);
  const emptyContactForm = { contact_name: '', contact_phone: '', contact_role: 'boss', notes: '' };
  const [contactForm, setContactForm] = useState(emptyContactForm);

  // Dynamic industry labels
  const [industryLabels, setIndustryLabels] = useState<Record<string, string>>(loadIndustryLabels);
  const [showAddIndustry, setShowAddIndustry] = useState(false);
  const [newIndustryName, setNewIndustryName] = useState('');

  const handleAddIndustry = () => {
    const name = newIndustryName.trim();
    if (!name) { toast.error('请输入行业名称'); return; }
    // Generate a key from the name (use pinyin-like or just the name itself as key)
    const key = 'custom_' + name.toLowerCase().replace(/\s+/g, '_');
    if (industryLabels[key] || Object.values(industryLabels).includes(name)) {
      toast.error('该行业已存在'); return;
    }
    saveCustomIndustry(key, name);
    const updated = loadIndustryLabels();
    setIndustryLabels(updated);
    setForm({ ...form, industry: key });
    setNewIndustryName('');
    setShowAddIndustry(false);
    toast.success(`已添加行业「${name}」`);
  };

  // Employees list for sales person dropdown
  const [employeesList, setEmployeesList] = useState<any[]>([]);
  // Assign dialog state
  const [showAssignDialog, setShowAssignDialog] = useState(false);
  const [assignTarget, setAssignTarget] = useState<any>(null);
  const [assignEmployeeId, setAssignEmployeeId] = useState('');
  const [assigning, setAssigning] = useState(false);

  // Advanced filter cascading state
  const advStates = advFilters.country ? getStatesForCountry(advFilters.country) : [];
  const advCities = advFilters.country && advFilters.state ? getCitiesForState(advFilters.country, advFilters.state) : [];

  useEffect(() => {
    const sp = searchParams.get('status');
    if (sp && statusLabels[sp]) setFilterStatus(sp);
    // Handle deep link from Sales page
    const detailId = searchParams.get('detail');
    if (detailId && customers.length > 0) {
      const target = customers.find(c => c.id === Number(detailId));
      if (target) openDetail(target);
    }
  }, [searchParams, customers]);

  const toggleCol = (key: string) => {
    const nc = visibleCols.includes(key) ? visibleCols.filter(c => c !== key) : [...visibleCols, key];
    setVisibleCols(nc);
    localStorage.setItem(COLS_KEY, JSON.stringify(nc));
  };

  const reloadFollowUps = async (cid: number) => {
    const r = await client.entities.follow_ups.query({ query: { customer_id: cid }, sort: '-created_at', limit: 50 });
    setFollowUps(r?.data?.items || []);
  };

  const reloadContacts = async (cid: number) => {
    try {
      const r = await client.entities.customer_contacts.queryAll({ query: { customer_id: cid }, sort: '-created_at', limit: 50 });
      setContacts(r?.data?.items || []);
    } catch (err) { console.error('Load contacts error:', err); setContacts([]); }
  };

  const openEditFollow = (f: any) => {
    setFollowForm({ contact_method: f.contact_method || 'phone', content: f.content || '', customer_needs: f.customer_needs || '', customer_pain_points: f.customer_pain_points || '', has_quoted: f.has_quoted || false, quote_plan: f.quote_plan || '', close_probability: f.close_probability ?? 30, stage: f.stage || 'communicating', next_follow_date: f.next_follow_date ? f.next_follow_date.slice(0, 10) : '' });
    setEditingFollowId(f.id);
    setShowFollowForm(true);
  };

  const handleSaveFollow = async () => {
    if (!followForm.content.trim()) { toast.error('请填写跟进内容'); return; }
    if (!selectedCustomer) return;
    setSavingFollow(true);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';
      if (editingFollowId) {
        await client.entities.follow_ups.update({ id: String(editingFollowId), data: { contact_method: followForm.contact_method, content: followForm.content, customer_needs: followForm.customer_needs, customer_pain_points: followForm.customer_pain_points, has_quoted: followForm.has_quoted, quote_plan: followForm.quote_plan, close_probability: followForm.close_probability, stage: followForm.stage, next_follow_date: followForm.next_follow_date || null, updated_at: now } });
        toast.success('跟进记录已更新');
        logOperation({ customerId: selectedCustomer.id, actionType: 'edit_follow_up', actionDetail: '编辑跟进记录', operatorName: op });
      } else {
        await client.entities.follow_ups.create({ data: { customer_id: selectedCustomer.id, contact_method: followForm.contact_method, content: followForm.content, customer_needs: followForm.customer_needs, customer_pain_points: followForm.customer_pain_points, has_quoted: followForm.has_quoted, quote_plan: followForm.quote_plan, close_probability: followForm.close_probability, stage: followForm.stage, next_follow_date: followForm.next_follow_date || null, employee_name: employee?.name || '', created_at: now } });
        toast.success('跟进记录已添加');
        logOperation({ customerId: selectedCustomer.id, actionType: 'create_follow_up', actionDetail: '新增跟进记录', operatorName: op });
      }
      setShowFollowForm(false); setEditingFollowId(null); setFollowForm(emptyFollowForm);
      await reloadFollowUps(selectedCustomer.id);
    } catch { toast.error('保存失败'); } finally { setSavingFollow(false); }
  };

  const handleDeleteFollow = async () => {
    if (!deleteFollowTarget || !selectedCustomer) return;
    setDeletingFollow(true);
    try {
      await client.entities.follow_ups.delete({ id: String(deleteFollowTarget.id) });
      toast.success('跟进记录已删除');
      logOperation({ customerId: selectedCustomer.id, actionType: 'delete_follow_up', actionDetail: '删除跟进记录', operatorName: employee?.name || '管理员' });
      setDeleteFollowTarget(null);
      await reloadFollowUps(selectedCustomer.id);
    } catch { toast.error('删除失败'); } finally { setDeletingFollow(false); }
  };

  // Contact CRUD
  const handleSaveContact = async () => {
    if (!contactForm.contact_name.trim()) { toast.error('请填写联系人姓名'); return; }
    if (!selectedCustomer) return;
    setSavingContact(true);
    try {
      if (editingContactId) {
        await client.entities.customer_contacts.update({ id: String(editingContactId), data: { contact_name: contactForm.contact_name, contact_phone: contactForm.contact_phone, contact_role: contactForm.contact_role, notes: contactForm.notes } });
        toast.success('联系人已更新');
      } else {
        await client.entities.customer_contacts.create({ data: { customer_id: selectedCustomer.id, contact_name: contactForm.contact_name, contact_phone: contactForm.contact_phone, contact_role: contactForm.contact_role, notes: contactForm.notes, created_at: new Date().toISOString() } });
        toast.success('联系人已添加');
      }
      setShowContactForm(false); setEditingContactId(null); setContactForm(emptyContactForm);
      await reloadContacts(selectedCustomer.id);
    } catch (err) { console.error(err); toast.error('保存失败'); } finally { setSavingContact(false); }
  };

  const handleDeleteContact = async () => {
    if (!deleteContactTarget || !selectedCustomer) return;
    setDeletingContact(true);
    try {
      await client.entities.customer_contacts.delete({ id: String(deleteContactTarget.id) });
      toast.success('联系人已删除');
      setDeleteContactTarget(null);
      await reloadContacts(selectedCustomer.id);
    } catch { toast.error('删除失败'); } finally { setDeletingContact(false); }
  };

  useEffect(() => { loadCustomers(); loadEmployees(); }, []);
  useEffect(() => { if (showForm) setCodeSettings(loadSettings()); }, [showForm]);

  const loadEmployees = async () => {
    try {
      const res = await client.entities.employees.queryAll({ query: { status: 'active' }, limit: 100 });
      setEmployeesList(res?.data?.items || []);
    } catch (err) { console.error('Load employees error:', err); }
  };

  const loadCustomers = async () => {
    try {
      const res = await client.entities.customers.query({ limit: 200, sort: '-created_at' });
      let items = res?.data?.items || [];
      if (dataScope === 'self' && employee) items = items.filter((c: any) => c.sales_person === employee.name || c.sales_employee_id === employee.id);
      setCustomers(items);
    } catch (err) { console.error(err); } finally { setLoading(false); }
  };

  const checkDuplicate = (name: string, phone: string) => {
    if (!name && !phone) { setDuplicateWarning(null); return; }
    const dupes = customers.filter(c => {
      if (editingId && c.id === editingId) return false;
      return (name && c.business_name?.toLowerCase() === name.toLowerCase()) || (phone && c.phone === phone);
    });
    setDuplicateWarning(dupes.length > 0 ? `检测到可能重复: ${dupes.map((d: any) => d.business_name).join(', ')}` : null);
  };

  const filtered = useMemo(() => {
    return customers.filter(c => {
      let ms = true;
      if (search) {
        const q = search.toLowerCase().trim();
        ms = [c.customer_code, c.business_name, c.contact_name, c.phone, c.city, c.email, c.wechat, c.address, c.sales_person, c.country, c.state].some(f => (f || '').toLowerCase().includes(q));
      }
      const mst = filterStatus === 'all' || c.status === filterStatus;
      const mi = filterIndustry === 'all' || c.industry === filterIndustry;
      const ml = filterLevel === 'all' || c.level === filterLevel;
      const mso = filterSource === 'all' || c.source === filterSource;
      const af = advFilters;
      const ma = (!af.business_name || (c.business_name || '').toLowerCase().includes(af.business_name.toLowerCase())) && (!af.contact_name || (c.contact_name || '').toLowerCase().includes(af.contact_name.toLowerCase())) && (!af.phone || (c.phone || '').includes(af.phone)) && (!af.wechat || (c.wechat || '').toLowerCase().includes(af.wechat.toLowerCase())) && (!af.email || (c.email || '').toLowerCase().includes(af.email.toLowerCase())) && (!af.country || c.country === af.country) && (!af.state || c.state === af.state) && (!af.city || (c.city || '').toLowerCase().includes(af.city.toLowerCase()));
      return ms && mst && mi && ml && mso && ma;
    });
  }, [customers, search, filterStatus, filterIndustry, filterLevel, filterSource, advFilters]);

  const openCreate = () => { setForm(emptyForm); setEditingId(null); setDuplicateWarning(null); setShowForm(true); };
  const openEdit = (c: any) => {
    setForm({ customer_code: c.customer_code || '', business_name: c.business_name || '', contact_name: c.contact_name || '', phone: c.phone || '', wechat: c.wechat || '', email: c.email || '', address: c.address || '', city: c.city || '', state: c.state || 'CA', country: c.country || 'US', industry: c.industry || 'restaurant', website: c.website || '', google_business_link: c.google_business_link || '', facebook_link: c.facebook_link || '', instagram_link: c.instagram_link || '', yelp_link: c.yelp_link || '', tiktok_link: c.tiktok_link || '', has_ordering_system: c.has_ordering_system || false, current_platform: c.current_platform || '无', monthly_orders: c.monthly_orders || 0, customer_source: c.customer_source || '', sales_person: c.sales_person || '', sales_employee_id: c.sales_employee_id || '', customer_level: c.customer_level || '', customer_status: c.customer_status || '', notes: c.notes || '' });
    setEditingId(c.id); setDuplicateWarning(null); setShowForm(true);
  };

  const getNextAutoCode = (industry?: string) => {
    const ind = industry || form.industry || 'restaurant';
    return generateNextCode(codeSettings, ind, customers.map(c => c.customer_code).filter(Boolean));
  };

  const handleSave = async () => {
    if (!form.business_name || !form.contact_name || !form.phone) { toast.error('请填写必填字段'); return; }
    setSaving(true);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';

      // Prepare data for saving
      const dataToSave: any = { ...form };
      if (dataToSave.sales_employee_id === '') {
        dataToSave.sales_employee_id = null;
      }

      if (editingId) {
        await client.entities.customers.update({ id: String(editingId), data: { ...dataToSave, updated_at: now } });
        toast.success('客户信息已更新');
        logOperation({ customerId: editingId, actionType: 'edit_customer', actionDetail: `编辑客户: ${form.business_name}`, operatorName: op });
      } else {
        const code = form.customer_code.trim() || getNextAutoCode(form.industry);
        if (customers.some(c => c.customer_code === code)) { toast.error(`编号「${code}」已存在`); setSaving(false); return; }
        const res = await client.entities.customers.create({ data: { ...dataToSave, customer_code: code, created_at: now, updated_at: now } });
        toast.success('客户创建成功');
        logOperation({ customerId: res?.data?.id, actionType: 'create_customer', actionDetail: `新增客户: ${form.business_name}`, operatorName: op });
      }
      setShowForm(false); loadCustomers();
    } catch (error) { console.error('保存客户失败:', error); toast.error('保存失败: ' + (error instanceof Error ? error.message : String(error))); } finally { setSaving(false); }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.customers.delete({ id: String(deleteTarget.id) });
      toast.success('客户已删除');
      logOperation({ customerId: deleteTarget.id, actionType: 'delete_customer', actionDetail: `删除客户: ${deleteTarget.business_name}`, operatorName: employee?.name || '管理员' });
      setDeleteTarget(null);
      if (selectedCustomer?.id === deleteTarget.id) setSelectedCustomer(null);
      loadCustomers();
    } catch { toast.error('删除失败'); } finally { setDeleting(false); }
  };

  const openAssign = (c: any) => {
    setAssignTarget(c);
    setAssignEmployeeId(c.sales_employee_id ? String(c.sales_employee_id) : '');
    setShowAssignDialog(true);
  };

  const handleAssign = async () => {
    if (!assignTarget || !assignEmployeeId) { toast.error('请选择负责人'); return; }
    setAssigning(true);
    try {
      const emp = employeesList.find(e => e.id === Number(assignEmployeeId));
      if (!emp) { toast.error('员工不存在'); setAssigning(false); return; }
      const now = new Date().toISOString();
      const oldPerson = assignTarget.sales_person || '无';
      await client.entities.customers.update({
        id: String(assignTarget.id),
        data: { sales_person: emp.name, sales_employee_id: emp.id, updated_at: now },
      });
      toast.success(`已将「${assignTarget.business_name}」分配给 ${emp.name}`);
      logOperation({
        customerId: assignTarget.id,
        actionType: 'other',
        actionDetail: `分配负责人: ${oldPerson} → ${emp.name}`,
        operatorName: employee?.name || '管理员',
      });
      setShowAssignDialog(false);
      setAssignTarget(null);
      // Update selected customer if in detail view
      if (selectedCustomer?.id === assignTarget.id) {
        setSelectedCustomer({ ...selectedCustomer, sales_person: emp.name, sales_employee_id: emp.id });
      }
      loadCustomers();
    } catch { toast.error('分配失败'); } finally { setAssigning(false); }
  };

  const openDetail = async (c: any) => {
    setSelectedCustomer(c);
    try {
      const [fuRes, dRes, pRes, sRes] = await Promise.all([
        client.entities.follow_ups.query({ query: { customer_id: c.id }, sort: '-created_at', limit: 50 }),
        client.entities.deals.query({ query: { customer_id: c.id }, sort: '-deal_date', limit: 50 }),
        client.entities.payments.query({ query: { customer_id: c.id }, sort: '-payment_date', limit: 50 }),
        client.entities.subscriptions.query({ query: { customer_id: c.id }, sort: '-created_at', limit: 50 }),
      ]);
      setFollowUps(fuRes?.data?.items || []); setDeals(dRes?.data?.items || []);
      setPayments(pRes?.data?.items || []); setSubscriptions(sRes?.data?.items || []);
    } catch (err) { console.error(err); }
    // Load contacts
    reloadContacts(c.id);
  };

  const countryStates = getStatesForCountry(form.country);
  const formCities = getCitiesForState(form.country, form.state);

  // ========== DETAIL VIEW ==========
  if (selectedCustomer) {
    const c = selectedCustomer;
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="ghost" size="sm" onClick={() => setSelectedCustomer(null)}><ArrowLeft className="w-4 h-4 mr-1" /> 返回列表</Button>
          <h2 className="text-lg font-semibold">{c.business_name}</h2>
          <Badge className={statusColors[c.status]}>{statusLabels[c.status]}</Badge>
          <Badge className={levelColors[c.level]}>{levelLabels[c.level]}</Badge>
        </div>
        <Tabs defaultValue="info" className="w-full">
          <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
            <TabsTrigger value="info" className="text-xs">基础信息</TabsTrigger>
            <TabsTrigger value="contacts" className="text-xs">联系人 ({contacts.length})</TabsTrigger>
            <TabsTrigger value="followups" className="text-xs">跟进记录 ({followUps.length})</TabsTrigger>
            <TabsTrigger value="deals" className="text-xs">成交记录 ({deals.length})</TabsTrigger>
            <TabsTrigger value="subscriptions" className="text-xs">服务信息 ({subscriptions.length})</TabsTrigger>
            <TabsTrigger value="payments" className="text-xs">财务信息 ({payments.length})</TabsTrigger>
            <TabsTrigger value="renewals" className="text-xs">续费信息</TabsTrigger>
            <TabsTrigger value="media" className="text-xs">媒体账号</TabsTrigger>
            <TabsTrigger value="logs" className="text-xs">操作日志</TabsTrigger>
          </TabsList>

          <TabsContent value="info">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="flex justify-end mb-4 gap-2">
                {hasPermission('customer_assign') && <Button size="sm" variant="outline" className="text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50" onClick={() => openAssign(c)}><ArrowRightLeft className="w-3 h-3 mr-1" /> 分配负责人</Button>}
                {hasPermission('customer_edit') && <Button size="sm" variant="outline" onClick={() => openEdit(c)}><Edit className="w-3 h-3 mr-1" /> 编辑</Button>}
                {hasPermission('customer_delete') && <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700 hover:bg-red-50" onClick={() => setDeleteTarget(c)}><Trash2 className="w-3 h-3 mr-1" /> 删除</Button>}
              </div>
              <div className="grid md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">客户编号:</span><span>{c.customer_code}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">行业类型:</span><span>{industryLabels[c.industry] || c.industry}</span></div>
                <div className="flex gap-2 items-center"><Phone className="w-3 h-3 text-slate-400" /><span>{c.phone}</span></div>
                <div className="flex gap-2 items-center"><Mail className="w-3 h-3 text-slate-400" /><span>{c.email || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">微信:</span><span>{c.wechat || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">来源:</span><span>{sourceLabels[c.source] || c.source}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">国家:</span><span>{c.country ? getCountryLabel(c.country) : '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">州/省:</span><span>{c.country && c.state ? getStateLabel(c.country, c.state) : (c.state || '-')}</span></div>
                <div className="flex gap-2 items-center col-span-2"><MapPin className="w-3 h-3 text-slate-400" /><span>{[c.address, c.city, c.state, c.country].filter(Boolean).join(', ')}</span></div>
                {c.website && <div className="flex gap-2 items-center col-span-2"><Globe className="w-3 h-3 text-slate-400" /><a href={c.website} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{c.website}</a></div>}
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">负责销售:</span><span>{c.sales_person || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">当前平台:</span><span>{c.current_platform || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">月订单量:</span><span>{c.monthly_orders || 0}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">已有点餐:</span><span>{c.has_ordering_system ? '是' : '否'}</span></div>
              </div>
              <div className="mt-4 pt-4 border-t border-slate-100">
                <h4 className="text-sm font-medium text-slate-600 mb-2">社交媒体链接</h4>
                <div className="grid md:grid-cols-2 gap-2 text-sm">
                  {c.facebook_link && <a href={c.facebook_link} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Facebook</a>}
                  {c.instagram_link && <a href={c.instagram_link} target="_blank" rel="noreferrer" className="text-pink-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Instagram</a>}
                  {c.google_business_link && <a href={c.google_business_link} target="_blank" rel="noreferrer" className="text-green-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Google Business</a>}
                  {c.yelp_link && <a href={c.yelp_link} target="_blank" rel="noreferrer" className="text-red-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Yelp</a>}
                  {c.tiktok_link && <a href={c.tiktok_link} target="_blank" rel="noreferrer" className="text-slate-800 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> TikTok</a>}
                  {!c.facebook_link && !c.instagram_link && !c.google_business_link && !c.yelp_link && !c.tiktok_link && <span className="text-slate-400">暂无</span>}
                </div>
              </div>
              {c.notes && <div className="mt-4 p-3 bg-slate-50 rounded text-slate-600 text-sm">{c.notes}</div>}
            </CardContent></Card>
          </TabsContent>

          {/* ========== CONTACTS TAB ========== */}
          <TabsContent value="contacts">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-slate-600 flex items-center gap-2"><Users className="w-4 h-4" /> 联系人信息</span>
                <Button size="sm" onClick={() => { setContactForm(emptyContactForm); setEditingContactId(null); setShowContactForm(true); }} className="bg-blue-600 hover:bg-blue-700"><UserPlus className="w-3.5 h-3.5 mr-1" /> 添加联系人</Button>
              </div>
              {showContactForm && (
                <div className="mb-4 p-4 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                  <span className="text-sm font-medium text-blue-700">{editingContactId ? '编辑联系人' : '添加联系人'}</span>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label className="text-xs">姓名 *</Label><Input value={contactForm.contact_name} onChange={e => setContactForm({ ...contactForm, contact_name: e.target.value })} placeholder="联系人姓名" /></div>
                    <div><Label className="text-xs">手机号</Label><Input value={contactForm.contact_phone} onChange={e => setContactForm({ ...contactForm, contact_phone: e.target.value })} placeholder="手机号码" /></div>
                    <div><Label className="text-xs">角色</Label><NativeSelect value={contactForm.contact_role} onChange={v => setContactForm({ ...contactForm, contact_role: v })} options={Object.entries(contactRoleLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
                    <div><Label className="text-xs">备注</Label><Input value={contactForm.notes} onChange={e => setContactForm({ ...contactForm, notes: e.target.value })} placeholder="备注信息" /></div>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setShowContactForm(false); setEditingContactId(null); }}>取消</Button>
                    <Button size="sm" onClick={handleSaveContact} disabled={savingContact} className="bg-blue-600 hover:bg-blue-700">{savingContact ? '保存中...' : '保存'}</Button>
                  </div>
                </div>
              )}
              {contacts.length === 0 && !showContactForm ? <p className="text-sm text-slate-400 text-center py-8">暂无联系人信息，点击"添加联系人"开始添加</p> : (
                <div className="space-y-3">{contacts.map((ct: any) => (
                  <div key={ct.id} className="p-3 bg-slate-50 rounded-lg group">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-medium text-sm">{(ct.contact_name || '?')[0]}</div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm">{ct.contact_name}</span>
                            <Badge variant="secondary" className="text-xs">{contactRoleLabels[ct.contact_role] || ct.contact_role}</Badge>
                          </div>
                          <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                            {ct.contact_phone && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{ct.contact_phone}</span>}
                            {ct.notes && <span>{ct.notes}</span>}
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-400 hover:text-blue-600" onClick={() => { setContactForm({ contact_name: ct.contact_name || '', contact_phone: ct.contact_phone || '', contact_role: ct.contact_role || 'boss', notes: ct.notes || '' }); setEditingContactId(ct.id); setShowContactForm(true); }}><Edit className="w-3 h-3" /></Button>
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-400 hover:text-red-600" onClick={() => setDeleteContactTarget(ct)}><Trash2 className="w-3 h-3" /></Button>
                      </div>
                    </div>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="followups">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-slate-600">跟进记录</span>
                <Button size="sm" onClick={() => { setFollowForm(emptyFollowForm); setEditingFollowId(null); setShowFollowForm(true); }} className="bg-blue-600 hover:bg-blue-700"><MessageSquarePlus className="w-3.5 h-3.5 mr-1" /> 新增跟进</Button>
              </div>
              {showFollowForm && (
                <div className="mb-4 p-4 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                  <span className="text-sm font-medium text-blue-700">{editingFollowId ? '编辑跟进' : '新增跟进'}</span>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label className="text-xs">方式</Label><NativeSelect value={followForm.contact_method} onChange={v => setFollowForm({ ...followForm, contact_method: v })} options={Object.entries(methodLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
                    <div><Label className="text-xs">阶段</Label><NativeSelect value={followForm.stage} onChange={v => setFollowForm({ ...followForm, stage: v })} options={Object.entries(stageLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
                  </div>
                  <div><Label className="text-xs">内容 *</Label><Textarea value={followForm.content} onChange={e => setFollowForm({ ...followForm, content: e.target.value })} rows={3} placeholder="跟进详情..." /></div>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label className="text-xs">需求</Label><Input value={followForm.customer_needs} onChange={e => setFollowForm({ ...followForm, customer_needs: e.target.value })} /></div>
                    <div><Label className="text-xs">痛点</Label><Input value={followForm.customer_pain_points} onChange={e => setFollowForm({ ...followForm, customer_pain_points: e.target.value })} /></div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label className="text-xs">成交概率 ({followForm.close_probability}%)</Label><Input type="range" min={0} max={100} step={10} value={followForm.close_probability} onChange={e => setFollowForm({ ...followForm, close_probability: Number(e.target.value) })} /></div>
                    <div><Label className="text-xs">下次跟进</Label><Input type="date" value={followForm.next_follow_date} onChange={e => setFollowForm({ ...followForm, next_follow_date: e.target.value })} /></div>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={followForm.has_quoted} onChange={e => setFollowForm({ ...followForm, has_quoted: e.target.checked })} className="rounded" />已报价</label>
                    {followForm.has_quoted && <Input placeholder="报价方案" value={followForm.quote_plan} onChange={e => setFollowForm({ ...followForm, quote_plan: e.target.value })} className="flex-1 h-8 text-sm" />}
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setShowFollowForm(false); setEditingFollowId(null); }}>取消</Button>
                    <Button size="sm" onClick={handleSaveFollow} disabled={savingFollow} className="bg-blue-600 hover:bg-blue-700">{savingFollow ? '保存中...' : '保存'}</Button>
                  </div>
                </div>
              )}
              {followUps.length === 0 && !showFollowForm ? <p className="text-sm text-slate-400 text-center py-8">暂无跟进记录</p> : (
                <div className="space-y-4">{followUps.map((f: any) => (
                  <div key={f.id} className="border-l-2 border-blue-300 pl-4 py-2 group">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs text-slate-500">{f.created_at?.slice(0, 16)}</span>
                      <Badge variant="secondary" className="text-xs">{stageLabels[f.stage] || f.stage}</Badge>
                      <span className="text-xs text-slate-400">{f.employee_name} · {methodLabels[f.contact_method] || f.contact_method}</span>
                      <div className="ml-auto flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-slate-400 hover:text-blue-600" onClick={() => openEditFollow(f)}><Edit className="w-3 h-3" /></Button>
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-slate-400 hover:text-red-600" onClick={() => setDeleteFollowTarget(f)}><Trash2 className="w-3 h-3" /></Button>
                      </div>
                    </div>
                    <p className="text-sm text-slate-700">{f.content}</p>
                    {f.customer_needs && <p className="text-xs text-slate-500 mt-1">需求: {f.customer_needs}</p>}
                    {f.customer_pain_points && <p className="text-xs text-slate-500 mt-1">痛点: {f.customer_pain_points}</p>}
                    {f.close_probability != null && <p className="text-xs text-slate-500 mt-1">概率: {f.close_probability}%</p>}
                    {f.has_quoted && <p className="text-xs text-green-600 mt-1">已报价: {f.quote_plan}</p>}
                    {f.next_follow_date && <p className="text-xs text-amber-600 mt-1">下次跟进: {f.next_follow_date.slice(0, 10)}</p>}
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="deals">
            <Card className="border-slate-200"><CardContent className="p-5">
              {deals.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无成交记录</p> : (
                <div className="space-y-3">{deals.map((d: any) => (
                  <div key={d.id} className="p-3 bg-slate-50 rounded-lg">
                    <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{d.package_name}</span><span className="text-green-600 font-bold">${d.deal_amount}</span></div>
                    <div className="grid grid-cols-2 gap-1 text-xs text-slate-500">
                      <span>产品: {productLabels[d.product_type] || d.product_type}</span><span>周期: {cycleLabels[d.billing_cycle] || d.billing_cycle}</span>
                      <span>成交日: {d.deal_date?.slice(0, 10)}</span><span>销售: {d.sales_name}</span>
                      <span>付款: {d.is_paid ? '✅ 已付' : '❌ 未付'}</span><span>交接: {d.is_handed_over ? '✅ 已交接' : '⏳ 待交接'}</span>
                    </div>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="subscriptions">
            <Card className="border-slate-200"><CardContent className="p-5">
              {subscriptions.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无套餐</p> : (
                <div className="space-y-3">{subscriptions.map((s: any) => (
                  <div key={s.id} className="p-3 bg-slate-50 rounded-lg">
                    <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{s.package_name}</span><Badge className={subStatusColors[s.status]}>{subStatusLabels[s.status] || s.status}</Badge></div>
                    <div className="grid grid-cols-2 gap-1 text-xs text-slate-500">
                      <span>价格: ${s.package_price}/{cycleLabels[s.billing_cycle] || s.billing_cycle}</span><span>自动续费: {s.auto_renew ? '是' : '否'}</span>
                      <span>开始: {s.start_date?.slice(0, 10)}</span><span>到期: {s.end_date?.slice(0, 10)}</span>
                    </div>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="payments">
            <Card className="border-slate-200"><CardContent className="p-5">
              {payments.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无财务记录</p> : (
                <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-slate-500"><th className="pb-2 font-medium">产品</th><th className="pb-2 font-medium">应收</th><th className="pb-2 font-medium">实收</th><th className="pb-2 font-medium">欠款</th><th className="pb-2 font-medium">方式</th><th className="pb-2 font-medium">日期</th></tr></thead>
                <tbody>{payments.map((p: any) => (<tr key={p.id} className="border-b border-slate-100"><td className="py-2">{p.product_name}</td><td className="py-2">${p.amount_due}</td><td className="py-2 text-green-600">${p.amount_paid}</td><td className="py-2">{(p.outstanding_amount || 0) > 0 ? <span className="text-red-600">${p.outstanding_amount}</span> : '-'}</td><td className="py-2">{payMethodLabels[p.payment_method] || p.payment_method}</td><td className="py-2 text-slate-500">{p.payment_date?.slice(0, 10)}</td></tr>))}</tbody></table></div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="renewals">
            <Card className="border-slate-200"><CardContent className="p-5">
              {subscriptions.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无续费信息</p> : (
                <div className="space-y-3">{subscriptions.map((s: any) => {
                  const isExp = s.end_date && new Date(s.end_date) < new Date();
                  const isSoon = s.end_date && !isExp && new Date(s.end_date) <= new Date(Date.now() + 30 * 86400000);
                  return (<div key={s.id} className={`p-3 rounded-lg border ${isExp ? 'border-red-200 bg-red-50' : isSoon ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
                    <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{s.package_name}</span><Badge className={isExp ? 'bg-red-100 text-red-700' : isSoon ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'}>{isExp ? '已到期' : isSoon ? '即将到期' : '正常'}</Badge></div>
                    <div className="grid grid-cols-2 gap-1 text-xs text-slate-500"><span>到期: {s.end_date?.slice(0, 10) || '-'}</span><span>自动续费: {s.auto_renew ? '是' : '否'}</span><span>续费负责: {s.renewal_person || '-'}</span><span>下次付款: {s.next_payment_date?.slice(0, 10) || '-'}</span></div>
                  </div>);
                })}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="media">
            <Card className="border-slate-200"><CardContent className="p-5"><MediaAccountsTab customerId={c.id} customerName={c.business_name} /></CardContent></Card>
          </TabsContent>

          <TabsContent value="logs">
            <Card className="border-slate-200"><CardContent className="p-5"><OperationLogsTab customerId={c.id} /></CardContent></Card>
          </TabsContent>
        </Tabs>
      </div>
    );
  }

  // ========== LIST VIEW ==========
  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-slate-800">客户管理</h2>
        <div className="flex gap-2 flex-wrap">
          {hasPermission('customer_create') && <ImportCustomers existingCustomers={customers} onImportComplete={loadCustomers} />}
          {hasPermission('customer_export') && <ExportButton data={filtered.map(c => ({ ...c, industry_label: industryLabels[c.industry] || c.industry, status_label: statusLabels[c.status] || c.status, level_label: levelLabels[c.level] || c.level, source_label: sourceLabels[c.source] || c.source, country_label: c.country ? getCountryLabel(c.country) : '' }))}
            columns={[{ key: 'customer_code', label: '编号' }, { key: 'business_name', label: '商家名称' }, { key: 'contact_name', label: '联系人' }, { key: 'phone', label: '电话' }, { key: 'email', label: '邮箱' }, { key: 'industry_label', label: '行业' }, { key: 'city', label: '城市' }, { key: 'state', label: '州' }, { key: 'country_label', label: '国家' }, { key: 'status_label', label: '状态' }, { key: 'level_label', label: '等级' }, { key: 'source_label', label: '来源' }, { key: 'sales_person', label: '负责销售' }, { key: 'facebook_link', label: 'Facebook' }, { key: 'instagram_link', label: 'Instagram' }, { key: 'google_business_link', label: 'Google Business' }, { key: 'yelp_link', label: 'Yelp' }, { key: 'tiktok_link', label: 'TikTok' }, { key: 'notes', label: '备注' }]}
            filename={`客户列表_${new Date().toISOString().slice(0, 10)}`} sheetName="客户列表" />}
          <Button variant="outline" size="sm" className="h-10 gap-1.5" onClick={() => setShowColPicker(!showColPicker)}><Columns3 className="w-4 h-4" /> 列设置</Button>
          {hasPermission('customer_create') && <Button onClick={openCreate} className="bg-blue-600 hover:bg-blue-700"><Plus className="w-4 h-4 mr-1" /> 新增客户</Button>}
        </div>
      </div>

      {showColPicker && (
        <Card className="border-slate-200"><CardContent className="p-3">
          <div className="flex items-center justify-between mb-2"><span className="text-sm font-medium text-slate-600">自定义显示列</span><Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setShowColPicker(false)}><X className="w-3 h-3" /></Button></div>
          <div className="flex flex-wrap gap-2">{allColumns.map(col => (<label key={col.key} className="flex items-center gap-1.5 text-xs cursor-pointer"><input type="checkbox" checked={visibleCols.includes(col.key)} onChange={() => toggleCol(col.key)} className="rounded" />{col.label}</label>))}</div>
        </CardContent></Card>
      )}



      {!selectedCustomer && !showForm && (
      <Card className="border-slate-200"><CardContent className="p-3 space-y-3">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" /><Input placeholder="搜索编号、名称、联系人、电话..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" /></div>
          <NativeSelect value={filterStatus} onChange={setFilterStatus} className="w-[120px]" options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterIndustry} onChange={setFilterIndustry} className="w-[120px]" options={[{ value: 'all', label: '全部行业' }, ...Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterLevel} onChange={setFilterLevel} className="w-[120px]" options={[{ value: 'all', label: '全部等级' }, ...Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterSource} onChange={setFilterSource} className="w-[120px]" options={[{ value: 'all', label: '全部来源' }, ...Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <Button variant={showAdvanced ? 'default' : 'outline'} size="sm" className={`h-10 shrink-0 gap-1.5 ${showAdvanced ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`} onClick={() => setShowAdvanced(!showAdvanced)}>
            <SlidersHorizontal className="w-4 h-4" /> 高级{advFilterCount > 0 && <Badge className="ml-1 bg-white text-blue-600 hover:bg-white h-5 min-w-[20px] px-1.5 text-xs">{advFilterCount}</Badge>}
          </Button>
        </div>
        {showAdvanced && (
          <div className="border-t border-slate-200 pt-3">
            <div className="flex items-center justify-between mb-3"><span className="text-sm font-medium text-slate-600">精确筛选</span>{advFilterCount > 0 && <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:text-red-600 gap-1" onClick={() => setAdvFilters({ business_name: '', contact_name: '', phone: '', wechat: '', email: '', country: '', state: '', city: '' })}><X className="w-3 h-3" /> 清除</Button>}</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <div><label className="text-xs text-slate-500 mb-1 block">商家名称</label><Input placeholder="商家名称" value={advFilters.business_name} onChange={e => setAdvFilters({ ...advFilters, business_name: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">联系人</label><Input placeholder="联系人" value={advFilters.contact_name} onChange={e => setAdvFilters({ ...advFilters, contact_name: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">电话</label><Input placeholder="电话" value={advFilters.phone} onChange={e => setAdvFilters({ ...advFilters, phone: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">微信</label><Input placeholder="微信" value={advFilters.wechat} onChange={e => setAdvFilters({ ...advFilters, wechat: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">邮箱</label><Input placeholder="邮箱" value={advFilters.email} onChange={e => setAdvFilters({ ...advFilters, email: e.target.value })} className="h-9 text-sm" /></div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">国家</label>
                <NativeSelect value={advFilters.country} onChange={v => setAdvFilters({ ...advFilters, country: v, state: '', city: '' })} options={[{ value: '', label: '全部国家' }, ...countries.map(c => ({ value: c.code, label: `${c.labelCn} (${c.label})` }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">州/省</label>
                <NativeSelect value={advFilters.state} onChange={v => setAdvFilters({ ...advFilters, state: v, city: '' })} options={[{ value: '', label: advFilters.country ? '全部州/省' : '请先选择国家' }, ...advStates.map(s => ({ value: s.code, label: s.label }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">城市</label>
                {advCities.length > 0 ? (
                  <NativeSelect value={advFilters.city} onChange={v => setAdvFilters({ ...advFilters, city: v })} options={[{ value: '', label: '全部城市' }, ...advCities.map(ct => ({ value: ct.label, label: ct.label }))]} />
                ) : (
                  <Input placeholder={advFilters.state ? '输入城市名' : '请先选择州/省'} value={advFilters.city} onChange={e => setAdvFilters({ ...advFilters, city: e.target.value })} className="h-9 text-sm" />
                )}
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">等级</label>
                <NativeSelect value={filterLevel} onChange={setFilterLevel} options={[{ value: 'all', label: '全部等级' }, ...Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
            </div>
          </div>
        )}
      </CardContent></Card>
      )}

      <div className="text-xs text-slate-500">共 {filtered.length} 条{filtered.length !== customers.length ? ` (筛选自 ${customers.length} 条)` : ''}</div>

      <Card className="border-slate-200"><CardContent className="p-0">
        {loading ? <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>
        : filtered.length === 0 ? <p className="text-center text-slate-400 py-12">暂无匹配的客户</p>
        : (
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b bg-slate-50 text-left text-slate-500">
            {visibleCols.includes('customer_code') && <th className="px-4 py-3 font-medium">编号</th>}
            {visibleCols.includes('business_name') && <th className="px-4 py-3 font-medium">商家名称</th>}
            {visibleCols.includes('contact_name') && <th className="px-4 py-3 font-medium">联系人</th>}
            {visibleCols.includes('phone') && <th className="px-4 py-3 font-medium">电话</th>}
            {visibleCols.includes('city') && <th className="px-4 py-3 font-medium hidden md:table-cell">城市</th>}
            {visibleCols.includes('country') && <th className="px-4 py-3 font-medium hidden md:table-cell">国家</th>}
            {visibleCols.includes('state') && <th className="px-4 py-3 font-medium hidden md:table-cell">州/省</th>}
            {visibleCols.includes('industry') && <th className="px-4 py-3 font-medium hidden md:table-cell">行业</th>}
            {visibleCols.includes('status') && <th className="px-4 py-3 font-medium">状态</th>}
            {visibleCols.includes('level') && <th className="px-4 py-3 font-medium hidden lg:table-cell">等级</th>}
            {visibleCols.includes('sales_person') && <th className="px-4 py-3 font-medium hidden lg:table-cell">负责人</th>}
            {visibleCols.includes('email') && <th className="px-4 py-3 font-medium hidden lg:table-cell">邮箱</th>}
            {visibleCols.includes('wechat') && <th className="px-4 py-3 font-medium hidden lg:table-cell">微信</th>}
            {visibleCols.includes('source') && <th className="px-4 py-3 font-medium hidden lg:table-cell">来源</th>}
            <th className="px-4 py-3 font-medium w-24">操作</th>
          </tr></thead>
          <tbody>{filtered.map(c => (
            <tr key={c.id} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors">
              {visibleCols.includes('customer_code') && <td className="px-4 py-3 text-slate-500 text-xs font-mono" onClick={() => openDetail(c)}>{c.customer_code || '-'}</td>}
              {visibleCols.includes('business_name') && <td className="px-4 py-3 font-medium text-blue-600" onClick={() => openDetail(c)}>{c.business_name}</td>}
              {visibleCols.includes('contact_name') && <td className="px-4 py-3" onClick={() => openDetail(c)}>{c.contact_name}</td>}
              {visibleCols.includes('phone') && <td className="px-4 py-3 text-slate-500" onClick={() => openDetail(c)}>{c.phone}</td>}
              {visibleCols.includes('city') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.city}</td>}
              {visibleCols.includes('country') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.country || '-'}</td>}
              {visibleCols.includes('state') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.state || '-'}</td>}
              {visibleCols.includes('industry') && <td className="px-4 py-3 hidden md:table-cell" onClick={() => openDetail(c)}>{industryLabels[c.industry] || c.industry}</td>}
              {visibleCols.includes('status') && <td className="px-4 py-3" onClick={() => openDetail(c)}><Badge className={`text-xs ${statusColors[c.status]}`}>{statusLabels[c.status]}</Badge></td>}
              {visibleCols.includes('level') && <td className="px-4 py-3 hidden lg:table-cell" onClick={() => openDetail(c)}><Badge className={`text-xs ${levelColors[c.level]}`}>{levelLabels[c.level]}</Badge></td>}
              {visibleCols.includes('sales_person') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{c.sales_person || '-'}</td>}
              {visibleCols.includes('email') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{c.email || '-'}</td>}
              {visibleCols.includes('wechat') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{c.wechat || '-'}</td>}
              {visibleCols.includes('source') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{sourceLabels[c.source] || c.source}</td>}
              <td className="px-4 py-3"><div className="flex gap-1">
                {hasPermission('customer_assign') && <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-indigo-600" title="分配负责人" onClick={e => { e.stopPropagation(); openAssign(c); }}><ArrowRightLeft className="w-3.5 h-3.5" /></Button>}
                {hasPermission('customer_edit') && <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-blue-600" onClick={e => { e.stopPropagation(); openEdit(c); }}><Edit className="w-3.5 h-3.5" /></Button>}
                {hasPermission('customer_delete') && <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={e => { e.stopPropagation(); setDeleteTarget(c); }}><Trash2 className="w-3.5 h-3.5" /></Button>}
              </div></td>
            </tr>
          ))}</tbody></table></div>
        )}
      </CardContent></Card>

      <ConfirmDialog open={!!deleteTarget} onOpenChange={v => { if (!v) setDeleteTarget(null); }} title="确认删除客户" description={`确定要删除「${deleteTarget?.business_name}」吗？`} onConfirm={handleDelete} loading={deleting} />
      <ConfirmDialog open={!!deleteFollowTarget} onOpenChange={v => { if (!v) setDeleteFollowTarget(null); }} title="确认删除跟进记录" description="确定要删除这条跟进记录吗？" onConfirm={handleDeleteFollow} loading={deletingFollow} />
      <ConfirmDialog open={!!deleteContactTarget} onOpenChange={v => { if (!v) setDeleteContactTarget(null); }} title="确认删除联系人" description={`确定要删除联系人「${deleteContactTarget?.contact_name}」吗？`} onConfirm={handleDeleteContact} loading={deletingContact} />

      {/* Assign dialog */}
      <Dialog open={showAssignDialog} onOpenChange={v => { if (!v) { setShowAssignDialog(false); setAssignTarget(null); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>分配负责人</DialogTitle></DialogHeader>
          {assignTarget && (
            <div className="space-y-4">
              <div className="p-3 bg-slate-50 rounded-lg">
                <p className="text-sm font-medium">{assignTarget.business_name}</p>
                <p className="text-xs text-slate-500 mt-1">当前负责人: {assignTarget.sales_person || '未分配'}</p>
              </div>
              <div>
                <Label>选择新负责人</Label>
                <NativeSelect
                  value={assignEmployeeId}
                  onChange={setAssignEmployeeId}
                  options={[{ value: '', label: '请选择员工' }, ...employeesList.map(e => ({ value: String(e.id), label: `${e.name}${e.department ? ' - ' + e.department : ''}${e.role ? ' (' + e.role + ')' : ''}` }))]}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => { setShowAssignDialog(false); setAssignTarget(null); }}>取消</Button>
                <Button onClick={handleAssign} disabled={assigning || !assignEmployeeId} className="bg-indigo-600 hover:bg-indigo-700">{assigning ? '分配中...' : '确认分配'}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑客户' : '新增客户'}</DialogTitle></DialogHeader>
          {duplicateWarning && <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700"><AlertCircle className="w-4 h-4 flex-shrink-0" />{duplicateWarning}</div>}
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <Label>客户编号</Label>
              <div className="flex gap-2 items-center">
                <Input value={form.customer_code} onChange={e => setForm({ ...form, customer_code: e.target.value })} placeholder={editingId ? '修改编号' : `留空自动生成`} className="font-mono" />
                {!editingId && <Button type="button" size="sm" variant="outline" className="shrink-0 text-xs" onClick={() => setForm({ ...form, customer_code: getNextAutoCode(form.industry) })}>自动生成</Button>}
              </div>
            </div>
            <div><Label>商家名称 *</Label><Input value={form.business_name} onChange={e => { setForm({ ...form, business_name: e.target.value }); checkDuplicate(e.target.value, form.phone); }} /></div>
            <div><Label>联系人 *</Label><Input value={form.contact_name} onChange={e => setForm({ ...form, contact_name: e.target.value })} /></div>
            <div><Label>电话 *</Label><Input value={form.phone} onChange={e => { setForm({ ...form, phone: e.target.value }); checkDuplicate(form.business_name, e.target.value); }} /></div>
            <div><Label>微信/WhatsApp</Label><Input value={form.wechat} onChange={e => setForm({ ...form, wechat: e.target.value })} /></div>
            <div><Label>邮箱</Label><Input value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></div>
            <div>
              <Label>行业</Label>
              <div className="flex gap-1.5">
                <NativeSelect value={form.industry} onChange={v => setForm({ ...form, industry: v })} options={Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))} className="flex-1" />
                <Button type="button" size="sm" variant="outline" className="shrink-0 h-10 px-2 text-xs text-blue-600 hover:text-blue-700" onClick={() => setShowAddIndustry(true)}><Plus className="w-3.5 h-3.5" /></Button>
              </div>
              {showAddIndustry && (
                <div className="mt-2 p-3 border border-blue-200 bg-blue-50/50 rounded-lg space-y-2">
                  <Label className="text-xs text-blue-700">添加新行业分类</Label>
                  <div className="flex gap-2">
                    <Input value={newIndustryName} onChange={e => setNewIndustryName(e.target.value)} placeholder="输入行业名称，如：教育" className="h-8 text-sm flex-1" onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddIndustry(); } }} />
                    <Button type="button" size="sm" className="h-8 bg-blue-600 hover:bg-blue-700 text-xs" onClick={handleAddIndustry}>添加</Button>
                    <Button type="button" size="sm" variant="ghost" className="h-8 text-xs" onClick={() => { setShowAddIndustry(false); setNewIndustryName(''); }}>取消</Button>
                  </div>
                </div>
              )}
            </div>
            <div><Label>国家</Label><NativeSelect value={form.country} onChange={v => { setForm({ ...form, country: v, state: getStatesForCountry(v)[0]?.code || '', city: '' }); }} options={countries.map(c => ({ value: c.code, label: `${c.labelCn} (${c.label})` }))} /></div>
            <div><Label>州/省</Label><NativeSelect value={form.state} onChange={v => setForm({ ...form, state: v, city: '' })} options={countryStates.length > 0 ? countryStates.map(s => ({ value: s.code, label: s.label })) : [{ value: '', label: '请先选择国家' }]} /></div>
            <div>
              <Label>城市</Label>
              {formCities.length > 0 ? (
                <NativeSelect value={form.city} onChange={v => setForm({ ...form, city: v })} options={[{ value: '', label: '请选择城市' }, ...formCities.map(ct => ({ value: ct.label, label: ct.label }))]} />
              ) : (
                <Input value={form.city} onChange={e => setForm({ ...form, city: e.target.value })} placeholder="输入城市名" />
              )}
            </div>
            <div><Label>地址</Label><Input value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} /></div>
            <div><Label>来源</Label><NativeSelect value={form.customer_source} onChange={v => setForm({ ...form, customer_source: v })} options={Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div><Label>等级</Label><NativeSelect value={form.customer_level} onChange={v => setForm({ ...form, customer_level: v })} options={Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div><Label>状态</Label><NativeSelect value={form.customer_status} onChange={v => setForm({ ...form, customer_status: v })} options={Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div><Label>负责销售</Label><NativeSelect value={form.sales_employee_id ? String(form.sales_employee_id) : ''} onChange={v => { const emp = employeesList.find(e => e.id === Number(v)); setForm({ ...form, sales_person: emp?.name || '', sales_employee_id: v ? Number(v) : '' }); }} options={[{ value: '', label: '请选择负责人' }, ...employeesList.map(e => ({ value: String(e.id), label: `${e.name}${e.department ? ' - ' + e.department : ''}` }))]} /></div>
            <div><Label>官网</Label><Input value={form.website} onChange={e => setForm({ ...form, website: e.target.value })} /></div>
            <div><Label>当前平台</Label><Input value={form.current_platform} onChange={e => setForm({ ...form, current_platform: e.target.value })} /></div>
            <div className="col-span-2 border-t border-slate-200 pt-3 mt-1">
              <h4 className="text-sm font-medium text-slate-600 mb-3">社交媒体链接</h4>
              <div className="grid grid-cols-2 gap-3">
                <div><Label className="text-xs">Facebook</Label><Input value={form.facebook_link} onChange={e => setForm({ ...form, facebook_link: e.target.value })} placeholder="https://facebook.com/..." /></div>
                <div><Label className="text-xs">Instagram</Label><Input value={form.instagram_link} onChange={e => setForm({ ...form, instagram_link: e.target.value })} placeholder="https://instagram.com/..." /></div>
                <div><Label className="text-xs">Google Business</Label><Input value={form.google_business_link} onChange={e => setForm({ ...form, google_business_link: e.target.value })} placeholder="https://business.google.com/..." /></div>
                <div><Label className="text-xs">Yelp</Label><Input value={form.yelp_link} onChange={e => setForm({ ...form, yelp_link: e.target.value })} placeholder="https://yelp.com/biz/..." /></div>
                <div><Label className="text-xs">TikTok</Label><Input value={form.tiktok_link} onChange={e => setForm({ ...form, tiktok_link: e.target.value })} placeholder="https://tiktok.com/@..." /></div>
              </div>
            </div>
            <div className="col-span-2"><Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowForm(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700">{saving ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}