import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { countries, getStatesForCountry, getCitiesForState, getCountryLabel, getStateLabel } from '../lib/country-state-data';
import { logOperation } from '../lib/operation-log-helper';
import { allStageLabels, issueStatusColors, issueStatusLabels, priorityColors, priorityLabels, serviceTypeLabels, taskStatusColors, taskStatusLabels, taskTypeLabels } from '../lib/service-board-config';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus, Search, ArrowLeft, Phone, Mail, MapPin, Globe, Edit, Trash2, SlidersHorizontal, X, MessageSquarePlus, Columns3, AlertCircle, UserPlus, Users, ArrowRightLeft, RefreshCw } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ExportButton from '@/components/ExportButton';
import ImportCustomers from '@/components/ImportCustomers';
import ConfirmDialog from '@/components/ConfirmDialog';
import MediaAccountsTab from '@/components/MediaAccountsTab';
import OperationLogsTab from '@/components/OperationLogsTab';
import { loadSettings, generateNextCode, type CustomerCodeSettings } from '../lib/customer-code-settings';
import { saveRemoteAppConfig } from '../lib/app-config';
import { buildOptionKey, serializeDictEntries, useBusinessDicts, useDictConfig } from '../lib/dict-config';
import { getPaymentMethodLabel, getPaymentModeLabel } from '../lib/payment-utils';
import {
  computeSubscriptionStatus,
  decorateEffectiveSubscriptions,
  getSubscriptionRemainingDays,
} from '../lib/subscription-utils';

const statusColors: Record<string, string> = { new: 'bg-blue-100 text-blue-700', following: 'bg-amber-100 text-amber-700', closed: 'bg-green-100 text-green-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };
const levelColors: Record<string, string> = { high: 'bg-orange-100 text-orange-700', normal: 'bg-slate-100 text-slate-600', low: 'bg-gray-100 text-gray-500', vip: 'bg-purple-100 text-purple-700' };
const subStatusColors: Record<string, string> = { active: 'bg-green-100 text-green-700', expiring_soon: 'bg-amber-100 text-amber-700', expired: 'bg-red-100 text-red-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };
const contactRoleLabels: Record<string, string> = { boss: '老板', manager: '经理', staff: '员工', other: '其他' };
const defaultLevelColorClass = 'bg-slate-100 text-slate-700';

const emptyForm = {
  customer_code: '', business_name: '', contact_name: '', phone: '', wechat: '', email: '',
  address: '', city: '', state: 'CA', country: 'US', industry: 'restaurant', website: '',
  google_business_link: '', facebook_link: '', instagram_link: '', yelp_link: '', tiktok_link: '',
  has_ordering_system: false, current_platform: '无', interested_packages: [] as string[], monthly_orders: 0,
  source: 'phone', sales_person: '', sales_employee_id: '' as string | number, level: 'normal', status: 'new', notes: '',
};

const allColumns = [
  { key: 'customer_code', label: '编号', d: true }, { key: 'business_name', label: '商家名称', d: true },
  { key: 'contact_name', label: '联系人', d: true }, { key: 'phone', label: '电话', d: true },
  { key: 'state', label: '州/省', d: true }, { key: 'country', label: '国家', d: true },
  { key: 'industry', label: '行业', d: true }, { key: 'city', label: '城市', d: false },
  { key: 'status', label: '状态', d: true }, { key: 'level', label: '等级', d: true },
  { key: 'sales_person', label: '负责人', d: true }, { key: 'email', label: '邮箱', d: false },
  { key: 'wechat', label: '微信', d: false }, { key: 'source', label: '来源', d: false },
];

const COLS_KEY = 'crm_visible_columns';
const legacyDefaultColumns = ['customer_code', 'business_name', 'contact_name', 'phone', 'city', 'industry', 'status', 'level', 'sales_person'];
const preferredDefaultColumns = allColumns.filter(c => c.d).map(c => c.key);

function loadCols(): string[] {
  try {
    const s = localStorage.getItem(COLS_KEY);
    if (s) {
      const parsed = JSON.parse(s);
      if (Array.isArray(parsed)) {
        const validKeys = new Set(allColumns.map(col => col.key));
        const sanitized = parsed.filter((key): key is string => typeof key === 'string' && validKeys.has(key));
        const isLegacyDefault = sanitized.length === legacyDefaultColumns.length
          && legacyDefaultColumns.every(key => sanitized.includes(key))
          && !sanitized.includes('state')
          && !sanitized.includes('country');
        if (isLegacyDefault) {
          localStorage.setItem(COLS_KEY, JSON.stringify(preferredDefaultColumns));
          return preferredDefaultColumns;
        }
        return sanitized;
      }
    }
  } catch { /* */ }
  return preferredDefaultColumns;
}

const emptyAdvancedFilters = {
  customer_code: '',
  business_name: '',
  contact_name: '',
  phone: '',
  city: '',
  industry: '',
  status: '',
  level: '',
  sales_person: '',
  source: '',
  wechat: '',
  email: '',
  country: '',
  state: '',
};

const inlineSelectClassName = 'h-8 w-full min-w-[110px] rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60';
const inlineInputClassName = 'h-8 w-full min-w-[110px] rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60';
const customerDetailTabValues = new Set(['info', 'contacts', 'followups', 'deals', 'subscriptions', 'payments', 'renewals', 'media', 'logs']);
const customerReminderMessages: Record<string, { title: string; description: string }> = {
  follow_up_today: { title: '今日跟进提醒', description: '这位客户今天需要继续跟进，已为你直接打开跟进记录。' },
  follow_up_overdue: { title: '逾期跟进提醒', description: '这位客户的计划跟进时间已过，建议尽快补跟进并更新下一次时间。' },
  no_follow_7d: { title: '长期未跟进提醒', description: '这位客户最近 7 天没有新的跟进记录，建议先补充沟通情况。' },
  renewal_due: { title: '续费提醒', description: '这位客户的服务临近到期，已为你打开续费信息方便处理。' },
  overdue_payment: { title: '欠费提醒', description: '这位客户存在未结清款项，已为你打开财务信息方便核对。' },
};

function buildInlineOptions(value: string | undefined, labels: Record<string, string>) {
  const options = Object.entries(labels).map(([key, label]) => ({ value: key, label }));
  if (value && !labels[value]) {
    options.unshift({ value, label: value });
  }
  return options;
}

function getLevelColorClass(level?: string) {
  return levelColors[level || ''] || defaultLevelColorClass;
}

function parseMultiValue(value?: string | null) {
  return (value || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);
}

function getErrorDetail(err: any, fallback: string) {
  return err?.data?.detail || err?.response?.data?.detail || err?.message || fallback;
}

function formatCurrency(value: number) {
  return `$${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

function computeSubscriptionState(subscription: any) {
  return computeSubscriptionStatus(subscription);
}

export default function Customers() {
  const { role, employee, hasPermission, isAdmin, dataScope, canViewFinance } = useRole();
  const dictConfig = useDictConfig();
  const businessDicts = useBusinessDicts();
  const industryLabels = businessDicts.industries;
  const statusLabels = businessDicts.statuses;
  const levelLabels = businessDicts.levels;
  const sourceLabels = businessDicts.sources;
  const stageLabels = businessDicts.followUpStages;
  const productLabels = businessDicts.products;
  const customerPackageLabels = businessDicts.customerPackages;
  const cycleLabels = businessDicts.billingCycles;
  const payModeLabels = businessDicts.paymentModes;
  const payMethodLabels = businessDicts.paymentMethods;
  const subStatusLabels = businessDicts.subscriptionStatuses;
  const methodLabels = businessDicts.followUpMethods;
  const canManageDict = isAdmin || hasPermission('settings_edit');
  const [searchParams, setSearchParams] = useSearchParams();
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterIndustry, setFilterIndustry] = useState('all');
  const [filterLevel, setFilterLevel] = useState('all');
  const [filterSource, setFilterSource] = useState('all');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advFilters, setAdvFilters] = useState(emptyAdvancedFilters);
  const advFilterCount = Object.values(advFilters).filter(v => v.trim()).length;
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [manualCityInput, setManualCityInput] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<any>(null);
  const [selectedCustomerTab, setSelectedCustomerTab] = useState('info');
  const [followUps, setFollowUps] = useState<any[]>([]);
  const [deals, setDeals] = useState<any[]>([]);
  const [payments, setPayments] = useState<any[]>([]);
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [serviceProgresses, setServiceProgresses] = useState<any[]>([]);
  const [serviceTasks, setServiceTasks] = useState<any[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
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
  const [showAddIndustry, setShowAddIndustry] = useState(false);
  const [newIndustryName, setNewIndustryName] = useState('');
  const [showLevelManager, setShowLevelManager] = useState(false);
  const [newLevelName, setNewLevelName] = useState('');
  const [levelDrafts, setLevelDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [savingLevels, setSavingLevels] = useState(false);
  const [showPackageManager, setShowPackageManager] = useState(false);
  const [newPackageName, setNewPackageName] = useState('');
  const [packageDrafts, setPackageDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [savingPackages, setSavingPackages] = useState(false);

  const handleAddIndustry = async () => {
    const name = newIndustryName.trim();
    if (!name) { toast.error('请输入行业名称'); return; }
    if (!canManageDict) {
      toast.error('仅管理员可新增全局行业，请在系统设置中维护');
      return;
    }
    let key = buildOptionKey(name);
    if (industryLabels[key]) {
      key = `${key}_${Date.now()}`;
    }
    if (Object.values(industryLabels).includes(name)) {
      toast.error('该行业已存在'); return;
    }
    try {
      const nextDictConfig = {
        ...dictConfig,
        industries: serializeDictEntries({ ...industryLabels, [key]: name }),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      setForm({ ...form, industry: key });
      setNewIndustryName('');
      setShowAddIndustry(false);
      toast.success(`已添加行业「${name}」`);
    } catch {
      toast.error('新增行业失败');
    }
  };

  const openLevelManager = () => {
    setLevelDrafts(Object.entries(levelLabels).map(([key, label]) => ({ key, label })));
    setNewLevelName('');
    setShowLevelManager(true);
  };

  const handleAddLevelDraft = () => {
    const label = newLevelName.trim();
    if (!label) { toast.error('请输入等级名称'); return; }
    if (levelDrafts.some(item => item.label.trim() === label)) {
      toast.error('该等级已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (levelDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setLevelDrafts(prev => [...prev, { key, label }]);
    setNewLevelName('');
  };

  const handleRemoveLevelDraft = (key: string) => {
    if (levelDrafts.length <= 1) {
      toast.error('至少保留一个客户等级');
      return;
    }
    if (customers.some(customer => customer.level === key)) {
      toast.error('该等级已有客户在使用，请先调整客户等级后再删除');
      return;
    }
    const remaining = levelDrafts.filter(item => item.key !== key);
    setLevelDrafts(remaining);
    if (form.level === key) {
      setForm(prev => ({ ...prev, level: remaining[0]?.key || '' }));
    }
  };

  const handleSaveLevels = async () => {
    const normalizedEntries = levelDrafts.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});

    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个客户等级');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('客户等级名称不能重复');
      return;
    }

    setSavingLevels(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        levels: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      const firstLevelKey = Object.keys(normalizedEntries)[0] || '';
      if (!normalizedEntries[form.level]) {
        setForm(prev => ({ ...prev, level: firstLevelKey }));
      }
      setShowLevelManager(false);
      setNewLevelName('');
      toast.success('客户等级已更新');
    } catch (err: any) {
      toast.error(getErrorDetail(err, '保存客户等级失败'));
    } finally {
      setSavingLevels(false);
    }
  };

  const openPackageManager = () => {
    setPackageDrafts(Object.entries(customerPackageLabels).map(([key, label]) => ({ key, label })));
    setNewPackageName('');
    setShowPackageManager(true);
  };

  const handleAddPackageDraft = () => {
    const label = newPackageName.trim();
    if (!label) { toast.error('请输入套餐名称'); return; }
    if (packageDrafts.some(item => item.label.trim() === label)) {
      toast.error('该套餐已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (packageDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setPackageDrafts(prev => [...prev, { key, label }]);
    setNewPackageName('');
  };

  const handleRemovePackageDraft = (key: string) => {
    if (packageDrafts.length <= 1) {
      toast.error('至少保留一个客户意向套餐');
      return;
    }
    if (customers.some(customer => parseMultiValue(customer.interested_packages).includes(key))) {
      toast.error('该套餐已有客户在使用，请先调整客户资料后再删除');
      return;
    }
    const remaining = packageDrafts.filter(item => item.key !== key);
    setPackageDrafts(remaining);
    setForm(prev => ({ ...prev, interested_packages: prev.interested_packages.filter(item => item !== key) }));
  };

  const handleSavePackages = async () => {
    const pendingLabel = newPackageName.trim();
    let draftsToSave = packageDrafts;
    if (pendingLabel) {
      if (packageDrafts.some(item => item.label.trim() === pendingLabel)) {
        toast.error('该套餐已存在');
        return;
      }
      let key = buildOptionKey(pendingLabel);
      while (packageDrafts.some(item => item.key === key)) {
        key = `${key}_${Date.now()}`;
      }
      draftsToSave = [...packageDrafts, { key, label: pendingLabel }];
    }

    const normalizedEntries = draftsToSave.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});

    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个客户意向套餐');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('套餐名称不能重复');
      return;
    }

    setSavingPackages(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        customerPackages: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      setForm(prev => ({
        ...prev,
        interested_packages: prev.interested_packages.filter(item => normalizedEntries[item]),
      }));
      setShowPackageManager(false);
      setNewPackageName('');
      toast.success('客户意向套餐已更新');
    } catch (err: any) {
      toast.error(getErrorDetail(err, '保存客户意向套餐失败'));
    } finally {
      setSavingPackages(false);
    }
  };

  const toggleInterestedPackage = (key: string, checked: boolean) => {
    setForm(prev => ({
      ...prev,
      interested_packages: checked
        ? [...prev.interested_packages, key]
        : prev.interested_packages.filter(item => item !== key),
    }));
  };

  // Employees list for sales person dropdown
  const [employeesList, setEmployeesList] = useState<any[]>([]);
  // Assign dialog state
  const [showAssignDialog, setShowAssignDialog] = useState(false);
  const [assignTarget, setAssignTarget] = useState<any>(null);
  const [assignEmployeeId, setAssignEmployeeId] = useState('');
  const [assigning, setAssigning] = useState(false);
  const [inlineSavingKey, setInlineSavingKey] = useState('');
  const [cityDrafts, setCityDrafts] = useState<Record<number, string>>({});
  const salesPersonOptions = useMemo(() => {
    const names = new Set<string>();
    customers.forEach(customer => {
      const name = customer.sales_person?.trim();
      if (name) names.add(name);
    });
    employeesList.forEach(emp => {
      const name = emp.name?.trim();
      if (name) names.add(name);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b, 'zh-CN')).map(name => ({ value: name, label: name }));
  }, [customers, employeesList]);

  // Advanced filter cascading state
  const advStates = advFilters.country ? getStatesForCountry(advFilters.country) : [];
  const advCities = advFilters.country && advFilters.state ? getCitiesForState(advFilters.country, advFilters.state) : [];
  const activeReminder = searchParams.get('reminder') || '';
  const activeReminderMessage = customerReminderMessages[activeReminder];
  const normalizeCustomerDetailTab = (tab?: string | null) => {
    if (tab === 'payments' && !canViewFinance) return 'info';
    return tab && customerDetailTabValues.has(tab) ? tab : 'info';
  };

  useEffect(() => {
    const sp = searchParams.get('status');
    if (sp && statusLabels[sp]) setFilterStatus(sp);
    // Handle deep link from Sales page
    const detailId = searchParams.get('detail');
    const nextTab = normalizeCustomerDetailTab(searchParams.get('tab'));
    if (detailId && customers.length > 0) {
      const target = customers.find(c => c.id === Number(detailId));
      if (target) {
        setSelectedCustomerTab(nextTab);
        if (selectedCustomer?.id !== target.id) {
          openDetail(target, nextTab);
        }
      }
    }
  }, [searchParams, customers, selectedCustomer?.id, statusLabels, canViewFinance]);

  const toggleCol = (key: string) => {
    const nc = visibleCols.includes(key) ? visibleCols.filter(c => c !== key) : [...visibleCols, key];
    setVisibleCols(nc);
    localStorage.setItem(COLS_KEY, JSON.stringify(nc));
  };

  const reloadFollowUps = async (cid: number) => {
    const r = await client.entities.follow_ups.query({ query: { customer_id: cid }, sort: '-created_at', limit: 50 });
    const items = r?.data?.items || [];
    setFollowUps(items);
    return items;
  };

  const reloadContacts = async (cid: number) => {
    try {
      const r = await client.entities.customer_contacts.queryAll({ query: { customer_id: cid }, sort: '-created_at', limit: 50 });
      setContacts(r?.data?.items || []);
    } catch (err) { console.error('Load contacts error:', err); setContacts([]); }
  };

  const loadCustomerDetail = async (customerId: number, fallbackCustomer?: any) => {
    setDetailLoading(true);
    try {
      const [customerRes, fuRes, dRes, pRes, sRes, progressRes, taskRes] = await Promise.all([
        client.entities.customers.query({ query: { id: customerId }, limit: 1 }),
        client.entities.follow_ups.query({ query: { customer_id: customerId }, sort: '-created_at', limit: 50 }),
        client.entities.deals.query({ query: { customer_id: customerId }, sort: '-deal_date', limit: 50 }),
        canViewFinance
          ? client.entities.payments.queryAll({ query: { customer_id: customerId }, sort: '-payment_date', limit: 100 })
          : Promise.resolve({ data: { items: [] } }),
        client.entities.subscriptions.query({ query: { customer_id: customerId }, sort: '-created_at', limit: 50 }),
        client.entities.service_progresses.queryAll({ query: { customer_id: customerId }, sort: '-last_update_time', limit: 50 }),
        client.entities.service_tasks.queryAll({ query: { customer_id: customerId }, sort: '-created_at', limit: 200 }),
      ]);

      const latestCustomer = customerRes?.data?.items?.[0] || fallbackCustomer || null;
      if (latestCustomer) {
        setSelectedCustomer(latestCustomer);
        setCustomers(prev => prev.map(item => (item.id === latestCustomer.id ? { ...item, ...latestCustomer } : item)));
      }
      setFollowUps(fuRes?.data?.items || []);
      setDeals(dRes?.data?.items || []);
      setPayments(pRes?.data?.items || []);
      setSubscriptions(decorateEffectiveSubscriptions(sRes?.data?.items || []));
      setServiceProgresses(progressRes?.data?.items || []);
      setServiceTasks(taskRes?.data?.items || []);
      await reloadContacts(customerId);
    } catch (err) {
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
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
      const nextFollowUps = await reloadFollowUps(selectedCustomer.id);
      const followReminderType = searchParams.get('reminder') || '';
      if (['follow_up_today', 'follow_up_overdue', 'no_follow_7d'].includes(followReminderType)) {
        const nextParams = new URLSearchParams(searchParams);
        let shouldClearReminder = followReminderType === 'no_follow_7d';

        if (!shouldClearReminder) {
          const latestFollowUp = nextFollowUps[0];
          const latestNextDate = latestFollowUp?.next_follow_date?.slice(0, 10) || '';
          const todayStr = new Date().toISOString().slice(0, 10);
          if (followReminderType === 'follow_up_today') {
            shouldClearReminder = latestNextDate !== todayStr;
          } else if (followReminderType === 'follow_up_overdue') {
            shouldClearReminder = !latestNextDate || latestNextDate >= todayStr;
          }
        }

        if (shouldClearReminder) {
          nextParams.delete('reminder');
          setSearchParams(nextParams);
        }
      }
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

  useEffect(() => {
    setLoading(true);
    void loadCustomers();
    void loadEmployees();
  }, [dataScope, employee?.id, employee?.name]);

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
      const ma = (!af.customer_code || (c.customer_code || '').toLowerCase().includes(af.customer_code.toLowerCase()))
        && (!af.business_name || (c.business_name || '').toLowerCase().includes(af.business_name.toLowerCase()))
        && (!af.contact_name || (c.contact_name || '').toLowerCase().includes(af.contact_name.toLowerCase()))
        && (!af.phone || (c.phone || '').includes(af.phone))
        && (!af.city || (c.city || '').toLowerCase().includes(af.city.toLowerCase()))
        && (!af.industry || c.industry === af.industry)
        && (!af.status || c.status === af.status)
        && (!af.level || c.level === af.level)
        && (!af.sales_person || c.sales_person === af.sales_person)
        && (!af.source || c.source === af.source)
        && (!af.wechat || (c.wechat || '').toLowerCase().includes(af.wechat.toLowerCase()))
        && (!af.email || (c.email || '').toLowerCase().includes(af.email.toLowerCase()))
        && (!af.country || c.country === af.country)
        && (!af.state || c.state === af.state);
      return ms && mst && mi && ml && mso && ma;
    });
  }, [customers, search, filterStatus, filterIndustry, filterLevel, filterSource, advFilters]);

  const openCreate = () => { setForm({ ...emptyForm, interested_packages: [] }); setManualCityInput(false); setEditingId(null); setDuplicateWarning(null); setShowForm(true); };
  const openEdit = (c: any) => {
    setForm({ customer_code: c.customer_code || '', business_name: c.business_name || '', contact_name: c.contact_name || '', phone: c.phone || '', wechat: c.wechat || '', email: c.email || '', address: c.address || '', city: c.city || '', state: c.state || 'CA', country: c.country || 'US', industry: c.industry || 'restaurant', website: c.website || '', google_business_link: c.google_business_link || '', facebook_link: c.facebook_link || '', instagram_link: c.instagram_link || '', yelp_link: c.yelp_link || '', tiktok_link: c.tiktok_link || '', has_ordering_system: c.has_ordering_system || false, current_platform: c.current_platform || '无', interested_packages: parseMultiValue(c.interested_packages), monthly_orders: c.monthly_orders || 0, source: c.source || 'phone', sales_person: c.sales_person || '', sales_employee_id: c.sales_employee_id || '', level: c.level || 'normal', status: c.status || 'new', notes: c.notes || '' });
    setManualCityInput(false);
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
      const payload = {
        ...form,
        interested_packages: form.interested_packages.join(','),
        sales_employee_id: form.sales_employee_id === '' ? null : Number(form.sales_employee_id),
        monthly_orders: String(form.monthly_orders ?? '').trim() === '' ? null : Number(form.monthly_orders || 0),
      };
      if (editingId) {
        const updatedRes = await client.entities.customers.update({ id: String(editingId), data: { ...payload, updated_at: now } });
        const updatedCustomer = updatedRes?.data || { ...payload, id: editingId, updated_at: now };
        setCustomers(prev => prev.map(item => (item.id === editingId ? { ...item, ...updatedCustomer } : item)));
        toast.success('客户信息已更新');
        logOperation({ customerId: editingId, actionType: 'edit_customer', actionDetail: `编辑客户: ${form.business_name}`, operatorName: op });
      } else {
        const code = form.customer_code.trim() || getNextAutoCode(form.industry);
        if (customers.some(c => c.customer_code === code)) { toast.error(`编号「${code}」已存在`); setSaving(false); return; }
        const res = await client.entities.customers.create({ data: { ...payload, customer_code: code, created_at: now, updated_at: now } });
        if (res?.data) {
          setCustomers(prev => [res.data, ...prev]);
        }
        toast.success('客户创建成功');
        logOperation({ customerId: res?.data?.id, actionType: 'create_customer', actionDetail: `新增客户: ${form.business_name}`, operatorName: op });
      }
      setShowForm(false);
      await loadCustomers();
      if (editingId && selectedCustomer?.id === editingId) {
        await loadCustomerDetail(editingId, { ...selectedCustomer, ...payload, updated_at: now });
      }
    } catch (err: any) { toast.error(getErrorDetail(err, '保存失败')); } finally { setSaving(false); }
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

  const syncCustomerState = (customerId: number, updates: Record<string, any>) => {
    setCustomers(prev => prev.map(item => (item.id === customerId ? { ...item, ...updates } : item)));
    setSelectedCustomer(prev => (prev?.id === customerId ? { ...prev, ...updates } : prev));
  };

  const handleInlineCustomerUpdate = async (
    customer: any,
    updates: Record<string, any>,
    successMessage: string,
    actionDetail: string,
  ) => {
    const nextUpdates = Object.fromEntries(
      Object.entries(updates).filter(([key, value]) => (customer[key] ?? '') !== (value ?? '')),
    );
    if (Object.keys(nextUpdates).length === 0) {
      return;
    }

    const savingKey = `${customer.id}:${Object.keys(nextUpdates).join(',')}`;
    setInlineSavingKey(savingKey);
    try {
      await client.entities.customers.update({
        id: String(customer.id),
        data: { ...nextUpdates, updated_at: new Date().toISOString() },
      });
      syncCustomerState(customer.id, nextUpdates);
      toast.success(successMessage);
      logOperation({
        customerId: customer.id,
        actionType: 'edit_customer',
        actionDetail,
        operatorName: employee?.name || '管理员',
      });
    } catch (err) {
      console.error(err);
      toast.error('更新失败');
      throw err;
    } finally {
      setInlineSavingKey(current => (current === savingKey ? '' : current));
    }
  };

  const handleInlineCitySave = async (customer: any) => {
    const nextCity = (cityDrafts[customer.id] ?? customer.city ?? '').trim();
    try {
      await handleInlineCustomerUpdate(
        customer,
        { city: nextCity },
        '城市已更新',
        `快捷更新城市: ${customer.business_name} -> ${nextCity || '未填写'}`,
      );
      setCityDrafts(prev => {
        const next = { ...prev };
        delete next[customer.id];
        return next;
      });
    } catch {
      setCityDrafts(prev => ({ ...prev, [customer.id]: customer.city || '' }));
    }
  };

  const openDetail = async (c: any, nextTab = 'info') => {
    setSelectedCustomerTab(normalizeCustomerDetailTab(nextTab));
    setSelectedCustomer(c);
    await loadCustomerDetail(c.id, c);
  };

  const closeDetail = () => {
    setSelectedCustomer(null);
    setSelectedCustomerTab('info');
    if (searchParams.get('detail') || searchParams.get('tab') || searchParams.get('reminder')) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete('detail');
      nextParams.delete('tab');
      nextParams.delete('reminder');
      setSearchParams(nextParams);
    }
  };

  const handleDetailTabChange = (nextTab: string) => {
    const safeTab = normalizeCustomerDetailTab(nextTab);
    setSelectedCustomerTab(safeTab);
    if (searchParams.get('detail')) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('tab', safeTab);
      setSearchParams(nextParams);
    }
  };

  const countryStates = getStatesForCountry(form.country);
  const formCities = getCitiesForState(form.country, form.state);
  const formCityLabels = new Set(formCities.map(city => city.label));
  const isCustomFormCity = Boolean(form.city && formCities.length > 0 && !formCityLabels.has(form.city));
  const showManualCityField = formCities.length === 0 || manualCityInput || isCustomFormCity;
  const sharedCustomerDialogs = (
    <>
      <ConfirmDialog open={!!deleteTarget} onOpenChange={v => { if (!v) setDeleteTarget(null); }} title="确认删除客户" description={`确定要删除「${deleteTarget?.business_name}」吗？`} onConfirm={handleDelete} loading={deleting} />
      <ConfirmDialog open={!!deleteFollowTarget} onOpenChange={v => { if (!v) setDeleteFollowTarget(null); }} title="确认删除跟进记录" description="确定要删除这条跟进记录吗？" onConfirm={handleDeleteFollow} loading={deletingFollow} />
      <ConfirmDialog open={!!deleteContactTarget} onOpenChange={v => { if (!v) setDeleteContactTarget(null); }} title="确认删除联系人" description={`确定要删除联系人「${deleteContactTarget?.contact_name}」吗？`} onConfirm={handleDeleteContact} loading={deletingContact} />

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
            <div><Label>国家</Label><NativeSelect value={form.country} onChange={v => { setManualCityInput(false); setForm({ ...form, country: v, state: getStatesForCountry(v)[0]?.code || '', city: '' }); }} options={countries.map(c => ({ value: c.code, label: `${c.labelCn} (${c.label})` }))} /></div>
            <div><Label>州/省</Label><NativeSelect value={form.state} onChange={v => { setManualCityInput(false); setForm({ ...form, state: v, city: '' }); }} options={countryStates.length > 0 ? countryStates.map(s => ({ value: s.code, label: s.code })) : [{ value: '', label: '请先选择国家' }]} /></div>
            <div>
              <Label>城市</Label>
              {formCities.length > 0 && (
                <NativeSelect
                  value={formCityLabels.has(form.city) && !manualCityInput ? form.city : ''}
                  onChange={v => {
                    if (v === '__manual__') {
                      setManualCityInput(true);
                      return;
                    }
                    setManualCityInput(false);
                    setForm({ ...form, city: v });
                  }}
                  options={[
                    { value: '', label: '请选择城市' },
                    ...formCities.map(ct => ({ value: ct.label, label: ct.label })),
                    { value: '__manual__', label: '列表没有，手动输入其他城市' },
                  ]}
                />
              )}
              {showManualCityField && (
                <Input
                  value={form.city}
                  onChange={e => setForm({ ...form, city: e.target.value })}
                  placeholder={formCities.length > 0 ? '输入其他城市名' : '输入城市名'}
                  className={formCities.length > 0 ? 'mt-2' : ''}
                />
              )}
            </div>
            <div><Label>地址</Label><Input value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} /></div>
            <div><Label>来源</Label><NativeSelect value={form.source} onChange={v => setForm({ ...form, source: v })} options={Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div>
              <Label>等级</Label>
              <div className="flex gap-1.5">
                <NativeSelect value={form.level} onChange={v => setForm({ ...form, level: v })} options={Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))} className="flex-1" />
                <Button type="button" size="sm" variant="outline" className="shrink-0 h-10 px-2 text-xs text-blue-600 hover:text-blue-700" onClick={openLevelManager}><Plus className="w-3.5 h-3.5" /></Button>
              </div>
              {showLevelManager && (
                <div className="mt-2 p-3 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <Label className="text-xs text-blue-700">管理客户等级</Label>
                    <Button type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => { setShowLevelManager(false); setNewLevelName(''); }}>
                      <X className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {levelDrafts.map((item) => (
                      <div key={item.key} className="flex items-center gap-2">
                        <Input
                          value={item.label}
                          onChange={e => setLevelDrafts(prev => prev.map(level => (level.key === item.key ? { ...level, label: e.target.value } : level)))}
                          className="h-8 text-sm flex-1"
                          placeholder="等级名称"
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-8 w-8 p-0 text-slate-500 hover:text-red-600"
                          onClick={() => handleRemoveLevelDraft(item.key)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={newLevelName}
                      onChange={e => setNewLevelName(e.target.value)}
                      placeholder="新增等级，例如：A类客户"
                      className="h-8 text-sm flex-1"
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleAddLevelDraft();
                        }
                      }}
                    />
                    <Button type="button" size="sm" className="h-8 bg-blue-600 hover:bg-blue-700 text-xs" onClick={handleAddLevelDraft}>添加</Button>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button type="button" size="sm" variant="outline" className="h-8 text-xs" onClick={() => { setShowLevelManager(false); setNewLevelName(''); }}>取消</Button>
                    <Button type="button" size="sm" className="h-8 bg-blue-600 hover:bg-blue-700 text-xs" onClick={handleSaveLevels} disabled={savingLevels}>{savingLevels ? '保存中...' : '保存等级'}</Button>
                  </div>
                </div>
              )}
            </div>
            <div><Label>状态</Label><NativeSelect value={form.status} onChange={v => setForm({ ...form, status: v })} options={Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div className="col-span-2">
              <Label>客户意向套餐</Label>
              <div className="mt-1 space-y-2">
                <div className="flex items-start gap-1.5">
                  <div className="flex-1 rounded-md border border-slate-200 bg-slate-50 p-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {Object.entries(customerPackageLabels).map(([key, label]) => (
                        <label key={key} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={form.interested_packages.includes(key)}
                            onChange={e => toggleInterestedPackage(key, e.target.checked)}
                            className="rounded"
                          />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                    <p className="text-xs text-slate-500 mt-3">
                      已选: {form.interested_packages.length > 0 ? form.interested_packages.map(item => customerPackageLabels[item] || item).join('、') : '未选择'}
                    </p>
                  </div>
                  <Button type="button" size="sm" variant="outline" className="shrink-0 h-10 px-2 text-xs text-blue-600 hover:text-blue-700" onClick={openPackageManager}><Plus className="w-3.5 h-3.5" /></Button>
                </div>
                {showPackageManager && (
                  <div className="p-3 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <Label className="text-xs text-blue-700">管理客户意向套餐</Label>
                      <Button type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => { setShowPackageManager(false); setNewPackageName(''); }}>
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                    <div className="space-y-2">
                      {packageDrafts.map((item) => (
                        <div key={item.key} className="flex items-center gap-2">
                          <Input
                            value={item.label}
                            onChange={e => setPackageDrafts(prev => prev.map(pkg => (pkg.key === item.key ? { ...pkg, label: e.target.value } : pkg)))}
                            className="h-8 text-sm flex-1"
                            placeholder="套餐名称"
                          />
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-8 w-8 p-0 text-slate-500 hover:text-red-600"
                            onClick={() => handleRemovePackageDraft(item.key)}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Input
                        value={newPackageName}
                        onChange={e => setNewPackageName(e.target.value)}
                        placeholder="新增套餐，例如：Google商家管理"
                        className="h-8 text-sm flex-1"
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddPackageDraft();
                          }
                        }}
                      />
                      <Button type="button" size="sm" className="h-8 bg-blue-600 hover:bg-blue-700 text-xs" onClick={handleAddPackageDraft}>添加</Button>
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button type="button" size="sm" variant="outline" className="h-8 text-xs" onClick={() => { setShowPackageManager(false); setNewPackageName(''); }}>取消</Button>
                      <Button type="button" size="sm" className="h-8 bg-blue-600 hover:bg-blue-700 text-xs" onClick={handleSavePackages} disabled={savingPackages}>{savingPackages ? '保存中...' : '保存套餐'}</Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
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
    </>
  );

  // ========== DETAIL VIEW ==========
  if (selectedCustomer) {
    const c = selectedCustomer;
    const detailAddress = [
      c.address,
      c.city,
      c.country && c.state ? getStateLabel(c.country, c.state) : (c.state || ''),
      c.country ? getCountryLabel(c.country) : '',
    ].filter(Boolean).join(', ');
    const totalDealAmount = deals.reduce((sum, item) => sum + Number(item.deal_amount || 0), 0);
    const totalAmountDue = payments.reduce((sum, item) => sum + Number(item.amount_due || 0), 0);
    const totalAmountPaid = payments.reduce((sum, item) => sum + Number(item.amount_paid || 0), 0);
    const totalOutstanding = payments.reduce((sum, item) => sum + Number(item.outstanding_amount || 0), 0);
    const latestPaymentDate = payments[0]?.payment_date?.slice(0, 10) || '-';
    const latestDealDate = deals[0]?.deal_date?.slice(0, 10) || '-';
    const serviceRecordCount = serviceProgresses.length > 0 ? serviceProgresses.length : subscriptions.length;
    const activeSubscriptionCount = subscriptions.filter(item => computeSubscriptionState(item) === 'active').length;
    const pendingServiceTasks = serviceTasks.filter(item => !['completed', 'cancelled'].includes(item.status || '')).length;
    const overdueServiceTasks = serviceTasks.filter(item => item.due_date && item.due_date < new Date().toISOString().slice(0, 10) && !['completed', 'cancelled'].includes(item.status || '')).length;
    const openServiceIssues = serviceProgresses.filter(item => item.issue_status && item.issue_status !== 'none' && !item.issue_resolved).length;
    const renewalRows = subscriptions
      .map(item => {
        const status = computeSubscriptionState(item);
        const daysLeft = getSubscriptionRemainingDays(item);
        return { ...item, computed_status: status, days_left: daysLeft };
      })
      .sort((a, b) => {
        const aTime = a.end_date ? new Date(a.end_date).getTime() : Number.MAX_SAFE_INTEGER;
        const bTime = b.end_date ? new Date(b.end_date).getTime() : Number.MAX_SAFE_INTEGER;
        return aTime - bTime;
      });
    const upcomingRenewalCount = renewalRows.filter(item => item.computed_status === 'expiring_soon').length;
    const autoRenewCount = renewalRows.filter(item => item.auto_renew).length;

    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="ghost" size="sm" onClick={closeDetail}><ArrowLeft className="w-4 h-4 mr-1" /> 返回列表</Button>
          <h2 className="text-lg font-semibold">{c.business_name}</h2>
          <Badge className={statusColors[c.status]}>{statusLabels[c.status]}</Badge>
          <Badge className={getLevelColorClass(c.level)}>{levelLabels[c.level]}</Badge>
          <Button variant="outline" size="sm" className="ml-auto" onClick={() => loadCustomerDetail(c.id, c)} disabled={detailLoading}>
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${detailLoading ? 'animate-spin' : ''}`} /> 刷新数据
          </Button>
        </div>
        {activeReminderMessage && (
          <Card className="border-blue-200 bg-blue-50">
            <CardContent className="p-4">
              <p className="text-sm font-medium text-blue-700">{activeReminderMessage.title}</p>
              <p className="text-xs text-blue-600 mt-1">{activeReminderMessage.description}</p>
            </CardContent>
          </Card>
        )}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">累计成交</p><p className="text-2xl font-semibold text-slate-800 mt-1">{formatCurrency(totalDealAmount)}</p><p className="text-xs text-slate-400 mt-1">最近成交: {latestDealDate}</p></CardContent></Card>
          {canViewFinance && <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">累计实收</p><p className="text-2xl font-semibold text-green-600 mt-1">{formatCurrency(totalAmountPaid)}</p><p className="text-xs text-slate-400 mt-1">最近收款: {latestPaymentDate}</p></CardContent></Card>}
          {canViewFinance && <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">当前尾款</p><p className="text-2xl font-semibold text-red-600 mt-1">{formatCurrency(totalOutstanding)}</p><p className="text-xs text-slate-400 mt-1">累计应收: {formatCurrency(totalAmountDue)}</p></CardContent></Card>}
          <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">服务概况</p><p className="text-2xl font-semibold text-blue-600 mt-1">{serviceRecordCount}</p><p className="text-xs text-slate-400 mt-1">在服 {activeSubscriptionCount} · 待处理任务 {pendingServiceTasks}</p></CardContent></Card>
        </div>
        <Tabs value={selectedCustomerTab} onValueChange={handleDetailTabChange} className="w-full">
          <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
            <TabsTrigger value="info" className="text-xs">基础信息</TabsTrigger>
            <TabsTrigger value="contacts" className="text-xs">联系人 ({contacts.length})</TabsTrigger>
            <TabsTrigger value="followups" className="text-xs">跟进记录 ({followUps.length})</TabsTrigger>
            <TabsTrigger value="deals" className="text-xs">成交记录 ({deals.length})</TabsTrigger>
            <TabsTrigger value="subscriptions" className="text-xs">服务信息 ({serviceRecordCount})</TabsTrigger>
            {canViewFinance && <TabsTrigger value="payments" className="text-xs">财务信息 ({payments.length})</TabsTrigger>}
            <TabsTrigger value="renewals" className="text-xs">续费信息 ({renewalRows.length})</TabsTrigger>
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
                <div className="flex gap-2 col-span-2"><span className="text-slate-500 w-24 shrink-0">意向套餐:</span><span>{parseMultiValue(c.interested_packages).length > 0 ? parseMultiValue(c.interested_packages).map(item => customerPackageLabels[item] || item).join('、') : '-'}</span></div>
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

          {canViewFinance && (
            <TabsContent value="payments">
              <Card className="border-slate-200"><CardContent className="p-5">
                {payments.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无财务记录</p> : (
                  <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-slate-500"><th className="pb-2 font-medium">产品</th><th className="pb-2 font-medium">应收</th><th className="pb-2 font-medium">实收</th><th className="pb-2 font-medium">欠款</th><th className="pb-2 font-medium">模式</th><th className="pb-2 font-medium">方式</th><th className="pb-2 font-medium">日期</th></tr></thead>
                  <tbody>{payments.map((p: any) => (<tr key={p.id} className="border-b border-slate-100"><td className="py-2">{p.product_name}</td><td className="py-2">${p.amount_due}</td><td className="py-2 text-green-600">${p.amount_paid}</td><td className="py-2">{(p.outstanding_amount || 0) > 0 ? <span className="text-red-600">${p.outstanding_amount}</span> : '-'}</td><td className="py-2">{getPaymentModeLabel(p, payModeLabels)}</td><td className="py-2">{getPaymentMethodLabel(p, payMethodLabels)}</td><td className="py-2 text-slate-500">{p.payment_date?.slice(0, 10)}</td></tr>))}</tbody></table></div>
                )}
              </CardContent></Card>
            </TabsContent>
          )}

          <TabsContent value="renewals">
            <Card className="border-slate-200"><CardContent className="p-5">
              {subscriptions.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无续费信息</p> : (
                <div className="space-y-3">{subscriptions.map((s: any) => {
                  const computedStatus = computeSubscriptionState(s);
                  const remainDays = getSubscriptionRemainingDays(s);
                  return (<div key={s.id} className={`p-3 rounded-lg border ${computedStatus === 'expired' ? 'border-red-200 bg-red-50' : computedStatus === 'expiring_soon' ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
                    <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{s.package_name}</span><Badge className={computedStatus === 'expired' ? 'bg-red-100 text-red-700' : computedStatus === 'expiring_soon' ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'}>{computedStatus === 'expired' ? '已到期' : computedStatus === 'expiring_soon' ? '即将到期' : '正常'}</Badge></div>
                    <div className="grid grid-cols-2 gap-1 text-xs text-slate-500"><span>到期: {s.end_date?.slice(0, 10) || '-'}</span><span>自动续费: {s.auto_renew ? '是' : '否'}</span><span>续费负责: {s.renewal_person || '-'}</span><span>下次付款: {s.next_payment_date?.slice(0, 10) || '-'}</span></div>
                    <div className={`text-xs mt-2 ${
                      remainDays == null
                        ? 'text-slate-400'
                        : remainDays <= 0
                          ? 'text-red-600 font-medium'
                          : remainDays <= 7
                            ? 'text-amber-600 font-medium'
                            : 'text-slate-500'
                    }`}>
                      {remainDays == null
                        ? '剩余: -'
                        : remainDays <= 0
                          ? `已逾期 ${Math.abs(remainDays)} 天`
                          : `剩余 ${remainDays} 天`}
                    </div>
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
        {sharedCustomerDialogs}
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

      <div className="flex gap-2 flex-wrap">{Object.entries(statusLabels).map(([k, v]) => (
        <Button key={k} variant={filterStatus === k ? 'default' : 'outline'} size="sm" className={`h-7 text-xs ${filterStatus === k ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`} onClick={() => setFilterStatus(filterStatus === k ? 'all' : k)}>{v}</Button>
      ))}</div>

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
            <div className="flex items-center justify-between mb-3"><span className="text-sm font-medium text-slate-600">精确筛选</span>{advFilterCount > 0 && <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:text-red-600 gap-1" onClick={() => setAdvFilters(emptyAdvancedFilters)}><X className="w-3 h-3" /> 清除</Button>}</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <div><label className="text-xs text-slate-500 mb-1 block">编号</label><Input placeholder="客户编号" value={advFilters.customer_code} onChange={e => setAdvFilters({ ...advFilters, customer_code: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">商家名称</label><Input placeholder="商家名称" value={advFilters.business_name} onChange={e => setAdvFilters({ ...advFilters, business_name: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">联系人</label><Input placeholder="联系人" value={advFilters.contact_name} onChange={e => setAdvFilters({ ...advFilters, contact_name: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">电话</label><Input placeholder="电话" value={advFilters.phone} onChange={e => setAdvFilters({ ...advFilters, phone: e.target.value })} className="h-9 text-sm" /></div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">行业</label>
                <NativeSelect value={advFilters.industry} onChange={v => setAdvFilters({ ...advFilters, industry: v })} options={[{ value: '', label: '全部行业' }, ...Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">状态</label>
                <NativeSelect value={advFilters.status} onChange={v => setAdvFilters({ ...advFilters, status: v })} options={[{ value: '', label: '全部状态' }, ...Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">等级</label>
                <NativeSelect value={advFilters.level} onChange={v => setAdvFilters({ ...advFilters, level: v })} options={[{ value: '', label: '全部等级' }, ...Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">负责人</label>
                <NativeSelect value={advFilters.sales_person} onChange={v => setAdvFilters({ ...advFilters, sales_person: v })} options={[{ value: '', label: '全部负责人' }, ...salesPersonOptions]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">来源</label>
                <NativeSelect value={advFilters.source} onChange={v => setAdvFilters({ ...advFilters, source: v })} options={[{ value: '', label: '全部来源' }, ...Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div><label className="text-xs text-slate-500 mb-1 block">微信</label><Input placeholder="微信" value={advFilters.wechat} onChange={e => setAdvFilters({ ...advFilters, wechat: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">邮箱</label><Input placeholder="邮箱" value={advFilters.email} onChange={e => setAdvFilters({ ...advFilters, email: e.target.value })} className="h-9 text-sm" /></div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">国家</label>
                <NativeSelect value={advFilters.country} onChange={v => setAdvFilters({ ...advFilters, country: v, state: '', city: '' })} options={[{ value: '', label: '全部国家' }, ...countries.map(c => ({ value: c.code, label: `${c.labelCn} (${c.label})` }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">州/省</label>
                <NativeSelect value={advFilters.state} onChange={v => setAdvFilters({ ...advFilters, state: v, city: '' })} options={[{ value: '', label: advFilters.country ? '全部州/省' : '请先选择国家' }, ...advStates.map(s => ({ value: s.code, label: s.code }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">城市</label>
                {advCities.length > 0 ? (
                  <NativeSelect value={advFilters.city} onChange={v => setAdvFilters({ ...advFilters, city: v })} options={[{ value: '', label: '全部城市' }, ...advCities.map(ct => ({ value: ct.label, label: ct.label }))]} />
                ) : (
                  <Input placeholder={advFilters.state ? '输入城市名' : '请先选择州/省'} value={advFilters.city} onChange={e => setAdvFilters({ ...advFilters, city: e.target.value })} className="h-9 text-sm" />
                )}
              </div>
            </div>
          </div>
        )}
      </CardContent></Card>

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
            {visibleCols.includes('state') && <th className="px-4 py-3 font-medium hidden md:table-cell">州/省</th>}
            {visibleCols.includes('country') && <th className="px-4 py-3 font-medium hidden md:table-cell">国家</th>}
            {visibleCols.includes('industry') && <th className="px-4 py-3 font-medium hidden md:table-cell">行业</th>}
            {visibleCols.includes('city') && <th className="px-4 py-3 font-medium hidden md:table-cell">城市</th>}
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
              {visibleCols.includes('state') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.state || '-'}</td>}
              {visibleCols.includes('country') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.country || '-'}</td>}
              {visibleCols.includes('industry') && (
                <td className="px-4 py-3 hidden md:table-cell" onClick={() => !hasPermission('customer_edit') && openDetail(c)}>
                  {hasPermission('customer_edit') ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      <select
                        value={c.industry || ''}
                        disabled={inlineSavingKey === `${c.id}:industry`}
                        onChange={e => {
                          const nextValue = e.target.value;
                          void handleInlineCustomerUpdate(
                            c,
                            { industry: nextValue },
                            '行业已更新',
                            `快捷更新行业: ${c.business_name} -> ${industryLabels[nextValue] || nextValue}`,
                          );
                        }}
                        className={inlineSelectClassName}
                      >
                        {buildInlineOptions(c.industry, industryLabels).map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    industryLabels[c.industry] || c.industry || '-'
                  )}
                </td>
              )}
              {visibleCols.includes('city') && (
                <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => !hasPermission('customer_edit') && openDetail(c)}>
                  {hasPermission('customer_edit') ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      {getCitiesForState(c.country || 'US', c.state || '').length > 0 ? (
                        <select
                          value={c.city || ''}
                          disabled={inlineSavingKey === `${c.id}:city`}
                          onChange={e => {
                            void handleInlineCustomerUpdate(
                              c,
                              { city: e.target.value },
                              '城市已更新',
                              `快捷更新城市: ${c.business_name} -> ${e.target.value || '未填写'}`,
                            );
                          }}
                          className={inlineSelectClassName}
                        >
                          <option value="">请选择城市</option>
                          {getCitiesForState(c.country || 'US', c.state || '').map(city => (
                            <option key={city.label} value={city.label}>{city.label}</option>
                          ))}
                        </select>
                      ) : (
                        <Input
                          value={cityDrafts[c.id] ?? c.city ?? ''}
                          disabled={inlineSavingKey === `${c.id}:city`}
                          onChange={e => setCityDrafts(prev => ({ ...prev, [c.id]: e.target.value }))}
                          onBlur={() => { void handleInlineCitySave(c); }}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              void handleInlineCitySave(c);
                            }
                          }}
                          className={inlineInputClassName}
                          placeholder="输入城市"
                        />
                      )}
                    </div>
                  ) : (
                    c.city || '-'
                  )}
                </td>
              )}
              {visibleCols.includes('status') && (
                <td className="px-4 py-3" onClick={() => !hasPermission('customer_edit') && openDetail(c)}>
                  {hasPermission('customer_edit') ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      <select
                        value={c.status || ''}
                        disabled={inlineSavingKey === `${c.id}:status`}
                        onChange={e => {
                          const nextValue = e.target.value;
                          void handleInlineCustomerUpdate(
                            c,
                            { status: nextValue },
                            '状态已更新',
                            `快捷更新状态: ${c.business_name} -> ${statusLabels[nextValue] || nextValue}`,
                          );
                        }}
                        className={`${inlineSelectClassName} ${statusColors[c.status] || ''}`}
                      >
                        {buildInlineOptions(c.status, statusLabels).map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <Badge className={`text-xs ${statusColors[c.status]}`}>{statusLabels[c.status]}</Badge>
                  )}
                </td>
              )}
              {visibleCols.includes('level') && (
                <td className="px-4 py-3 hidden lg:table-cell" onClick={() => !hasPermission('customer_edit') && openDetail(c)}>
                  {hasPermission('customer_edit') ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      <select
                        value={c.level || ''}
                        disabled={inlineSavingKey === `${c.id}:level`}
                        onChange={e => {
                          const nextValue = e.target.value;
                          void handleInlineCustomerUpdate(
                            c,
                            { level: nextValue },
                            '等级已更新',
                            `快捷更新等级: ${c.business_name} -> ${levelLabels[nextValue] || nextValue}`,
                          );
                        }}
                        className={`${inlineSelectClassName} ${getLevelColorClass(c.level)}`}
                      >
                        {buildInlineOptions(c.level, levelLabels).map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <Badge className={`text-xs ${getLevelColorClass(c.level)}`}>{levelLabels[c.level]}</Badge>
                  )}
                </td>
              )}
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

      {sharedCustomerDialogs}
    </div>
  );
}
