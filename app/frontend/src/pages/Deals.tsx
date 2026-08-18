import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  client,
  finalizeDeal,
  type DealFinalizeRequest,
  type DealFinalizeResponse,
} from '../lib/api';
import { useRole } from '../lib/role-context';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { Plus, Search, Edit, Trash2, ClipboardCheck, AlertTriangle, ExternalLink } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ExportButton from '@/components/ExportButton';
import ConfirmDialog from '@/components/ConfirmDialog';
import { saveRemoteAppConfig } from '../lib/app-config';
import {
  buildOptionKey,
  classifyPackageDisplay,
  inferPackagePlatforms,
  platformLabels,
  sanitizeDictLabel,
  serializeDictEntries,
  serializePackagePlatformEntries,
  useBusinessDicts,
  useDictConfig,
} from '../lib/dict-config';
import { useAutoRefresh } from '../lib/use-auto-refresh';
import PageLoadState from '@/components/PageLoadState';
import CustomerCombobox from '@/components/CustomerCombobox';
import { getLoadErrorMessage, loadWithRetry } from '../lib/load-utils';
import { useIsMobile } from '@/hooks/use-mobile';
import { businessDateKey } from '@/lib/business-date';

function parseMultiValue(value?: string | null) {
  return (value || '').split(',').map(item => item.trim()).filter(Boolean);
}

type PackageDraft = { key: string; label: string; platforms: string[] };

type PendingFinalizeStep = {
  key: string;
  label: string;
  message: string;
};

type PendingDealFinalize = {
  request: DealFinalizeRequest;
  steps: PendingFinalizeStep[];
  retryable: boolean;
};

const finalizeStepLabels: Record<string, string> = {
  subscription: '订阅',
  customer: '客户状态',
  service_board: '服务看板',
  request: '交接请求',
};

const pendingFinalizeStorageKey = (employeeId: string | number) => (
  `t24:deal-finalize-pending:${employeeId}`
);

function parsePendingFinalizations(raw: string | null): Record<number, PendingDealFinalize> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const result: Record<number, PendingDealFinalize> = {};
    Object.entries(parsed).slice(0, 100).forEach(([rawDealId, value]) => {
      const dealId = Number(rawDealId);
      const candidate = value as any;
      if (!Number.isSafeInteger(dealId) || dealId <= 0 || !candidate?.request || !Array.isArray(candidate.steps)) return;
      const steps = candidate.steps.slice(0, 4).flatMap((step: any) => {
        if (!step || typeof step.key !== 'string' || typeof step.label !== 'string' || typeof step.message !== 'string') return [];
        return [{
          key: step.key.slice(0, 40),
          label: step.label.slice(0, 40),
          message: step.message.slice(0, 300),
        }];
      });
      if (steps.length === 0) return;
      result[dealId] = {
        request: {
          ensure_subscription: candidate.request.ensure_subscription === true,
          auto_renew: candidate.request.auto_renew === true,
          create_service_board: candidate.request.create_service_board === true,
        },
        steps,
        retryable: candidate.retryable !== false,
      };
    });
    return result;
  } catch {
    return {};
  }
}

function normalizePackageLabel(label: string) {
  return sanitizeDictLabel(label).replace(/\s+/g, ' ').trim();
}

function parsePackageNameInput(value: string) {
  return value
    .split(/[\n,，;；]+/)
    .map(normalizePackageLabel)
    .filter(Boolean);
}

function buildUniquePackageKey(label: string, usedKeys: Set<string>) {
  const baseKey = buildOptionKey(label);
  let key = baseKey;
  while (usedKeys.has(key)) {
    key = `${baseKey}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  }
  usedKeys.add(key);
  return key;
}

function appendPackageDrafts(baseDrafts: PackageDraft[], rawInput: string) {
  const labels = parsePackageNameInput(rawInput);
  const nextDrafts = [...baseDrafts];
  const usedKeys = new Set(nextDrafts.map(item => item.key));
  const seenLabels = new Set(
    nextDrafts
      .map(item => normalizePackageLabel(item.label).toLowerCase())
      .filter(Boolean)
  );
  const duplicates: string[] = [];

  labels.forEach(label => {
    const normalizedKey = label.toLowerCase();
    if (seenLabels.has(normalizedKey)) {
      if (!duplicates.includes(label)) duplicates.push(label);
      return;
    }
    seenLabels.add(normalizedKey);
    nextDrafts.push({ key: buildUniquePackageKey(label, usedKeys), label, platforms: inferPackagePlatforms(label) });
  });

  return {
    drafts: nextDrafts,
    addedCount: nextDrafts.length - baseDrafts.length,
    duplicates,
  };
}

function parseDealPackageLabels(value?: string | null) {
  return (value || '').split(/[、,，]/).map(item => item.trim()).filter(Boolean);
}

const normalizeSearchText = (value?: string | null) => (value || '').toLowerCase().replace(/\s+/g, '');
const getDealDuplicateKey = (deal: any) => [
  Number(deal.customer_id || 0),
  normalizeSearchText(deal.package_name),
  deal.product_type || '',
  Number(deal.deal_amount || 0).toFixed(2),
  deal.billing_cycle || '',
  deal.deal_date?.slice(0, 10) || '',
].join('|');
const PAGE_SIZE_OPTIONS = [20, 50, 100];

const paginateList = <T,>(items: T[], page: number, pageSize: number) => {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page || 1, 1), totalPages);
  const offset = (safePage - 1) * pageSize;
  return {
    items: items.slice(offset, offset + pageSize),
    page: safePage,
    total,
    totalPages,
    start: total === 0 ? 0 : offset + 1,
    end: Math.min(offset + pageSize, total),
  };
};

type OnboardingStep = {
  task_name: string;
  task_type: string;
  platform?: string | null;
  dueOffsetDays: number;
  priority?: 'high' | 'medium' | 'low';
  notes: string;
};

const commonOnboardingSteps: OnboardingStep[] = [
  {
    task_name: '建立客户服务群',
    task_type: 'setup_group',
    platform: null,
    dueOffsetDays: 0,
    priority: 'high',
    notes: '成交后前期交接：拉客户联系人、销售、运营负责人进入服务群。',
  },
  {
    task_name: '发送运营说明与素材清单',
    task_type: 'confirm_service',
    platform: null,
    dueOffsetDays: 1,
    priority: 'high',
    notes: '向客户说明服务范围、每周更新节奏、周总结规则，并一次性发送素材/权限清单。',
  },
];

const platformOnboardingSteps: Record<string, Omit<OnboardingStep, 'platform'>[]> = {
  google_business: [
    {
      task_name: 'Google商家 权限对接',
      task_type: 'bind_google',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认 Google Business Profile 管理权限、账号归属、验证码或邀请流程。',
    },
    {
      task_name: 'Google商家 基础信息完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善名称、地址、电话、营业时间、服务项目、菜单、图片等基础资料。',
    },
    {
      task_name: 'Google商家 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
  facebook: [
    {
      task_name: 'Facebook 权限对接',
      task_type: 'open_facebook',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认 Facebook Page / Business Suite 权限、主页管理员和资产归属。',
    },
    {
      task_name: 'Facebook 主页资料完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善主页简介、联系方式、营业时间、菜单/服务、头像封面和行动按钮。',
    },
    {
      task_name: 'Facebook 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
  instagram: [
    {
      task_name: 'Instagram 权限对接',
      task_type: 'open_instagram',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认 Instagram 账号登录方式、授权方式，以及是否已与 Facebook 主页关联。',
    },
    {
      task_name: 'Instagram 主页资料完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善头像、简介、联系方式、营业地址、链接和精选展示。',
    },
    {
      task_name: 'Instagram 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
  yelp: [
    {
      task_name: 'Yelp 权限对接',
      task_type: 'other',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认 Yelp 商家页认领、管理员权限、登录方式和店铺归属。',
    },
    {
      task_name: 'Yelp 基础信息完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善地址、电话、营业时间、分类、服务项目、菜单/图片等资料。',
    },
    {
      task_name: 'Yelp 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
  tiktok: [
    {
      task_name: 'TikTok 账号/权限对接',
      task_type: 'other',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认 TikTok 账号登录方式、企业资料、管理员权限和素材授权。',
    },
    {
      task_name: 'TikTok 主页资料完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善头像、简介、联系方式、链接、店铺定位和内容方向。',
    },
    {
      task_name: 'TikTok 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
  xiaohongshu: [
    {
      task_name: '小红书 账号/权限对接',
      task_type: 'other',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认小红书账号登录方式、店铺/品牌信息、管理员权限和素材授权。',
    },
    {
      task_name: '小红书 店铺资料完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善头像、简介、店铺定位、服务项目、联系方式和内容方向。',
    },
    {
      task_name: '小红书 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
  x: [
    {
      task_name: 'X 账号/权限对接',
      task_type: 'other',
      dueOffsetDays: 2,
      priority: 'high',
      notes: '确认 X 账号登录方式、管理员权限、品牌资料和素材授权。',
    },
    {
      task_name: 'X 主页资料完善',
      task_type: 'update_info',
      dueOffsetDays: 3,
      priority: 'medium',
      notes: '完善头像、简介、联系方式、链接、品牌语气和内容方向。',
    },
    {
      task_name: 'X 正式运营启动',
      task_type: 'publish_content',
      dueOffsetDays: 5,
      priority: 'medium',
      notes: '进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。',
    },
  ],
};

function addDaysDateInput(offsetDays: number) {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function buildOnboardingSteps(platforms: string[]) {
  const platformSteps = platforms.flatMap(platform =>
    (platformOnboardingSteps[platform] || []).map(step => ({ ...step, platform }))
  );
  if (platformSteps.length === 0) return [];
  return [
    ...commonOnboardingSteps,
    ...platformSteps,
    {
      task_name: '首周运营总结汇报',
      task_type: 'submit_report',
      platform: null,
      dueOffsetDays: 7,
      priority: 'medium' as const,
      notes: '前期运营启动后，整理首周执行情况、素材使用情况、卡点和下周计划。',
    },
  ];
}

function getTodayDateInput() {
  return businessDateKey();
}

function buildEmptyDealForm() {
  return {
    customer_id: '',
    product_type: 'ordering_system',
    package_name: '',
    package_keys: [] as string[],
    billing_cycle: 'monthly',
    deal_amount: '',
    deal_date: getTodayDateInput(),
    is_paid: false,
    service_start_date: '',
    service_end_date: '',
    auto_renew: false,
    create_service_board: false,
    needs_group: false,
    is_handed_over: false,
    is_transferred_ops: false,
    notes: '',
  };
}

export default function Deals() {
  const { employee, dataScope, hasPermission } = useRole();
  const isMobile = useIsMobile();
  const dictConfig = useDictConfig();
  const {
    products: productLabels,
    billingCycles: cycleLabels,
    customerPackages: customerPackageLabels,
    customerPackagePlatforms,
  } = useBusinessDicts();
  const navigate = useNavigate();
  const [deals, setDeals] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filterProduct, setFilterProduct] = useState('all');
  const [filterPaid, setFilterPaid] = useState('all');
  const [filterCycle, setFilterCycle] = useState('all');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [filterDatePreset, setFilterDatePreset] = useState('all');
  const [showDuplicatesOnly, setShowDuplicatesOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [showPackageManager, setShowPackageManager] = useState(false);
  const [newPackageName, setNewPackageName] = useState('');
  const [packageDrafts, setPackageDrafts] = useState<PackageDraft[]>([]);
  const [savingPackages, setSavingPackages] = useState(false);
  const [packageOverrideLabels, setPackageOverrideLabels] = useState<Record<string, string>>({});
  const [generatingBoardId, setGeneratingBoardId] = useState<number | null>(null);
  const [pendingFinalizations, setPendingFinalizations] = useState<Record<number, PendingDealFinalize>>({});
  const [finalizingDealIds, setFinalizingDealIds] = useState<Set<number>>(() => new Set());
  const loadRequestSeqRef = useRef(0);
  const pendingStorageOwnerRef = useRef<string | null>(null);
  const pendingStorageSnapshotRef = useRef('{}');
  const pendingStorageHydratingRef = useRef(false);
  const emptyDealForm = buildEmptyDealForm();
  const [form, setForm] = useState(emptyDealForm);
  const dealPackageLabels = { ...customerPackageLabels, ...packageOverrideLabels };
  const dealPackageOptions = Object.entries(dealPackageLabels).map(([value, label]) => ({ value, label }));
  const getPackageClassification = (packageName?: string | null) => (
    classifyPackageDisplay(packageName, dealPackageLabels)
  );

  const loadData = async () => {
    const requestSeq = ++loadRequestSeqRef.current;
    try {
      const [dRes, cRes] = await loadWithRetry(() => Promise.all([
        client.entities.deals.query({ limit: 1000, sort: '-deal_date' }),
        client.entities.customers.query({ limit: 1000 }),
      ]));
      let dealItems = dRes?.data?.items || [];
      const custItems = cRes?.data?.items || [];

      // Filter deals by data scope: sales role only sees their own deals
      if (dataScope === 'self' && employee) {
        // Build a set of customer IDs that belong to this sales person
        const myCustomerIds = new Set(
          custItems
            .filter((c: any) => c.sales_person === employee.name || c.sales_employee_id === employee.id)
            .map((c: any) => c.id)
        );
        dealItems = dealItems.filter((d: any) =>
          d.sales_name === employee.name || myCustomerIds.has(d.customer_id)
        );
      }

      if (requestSeq !== loadRequestSeqRef.current) return;
      setDeals(dealItems);
      setCustomers(custItems);
      setLoadError(null);
    } catch (err) {
      if (requestSeq !== loadRequestSeqRef.current) return;
      console.error(err);
      setLoadError(getLoadErrorMessage(err));
    } finally {
      if (requestSeq === loadRequestSeqRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    void loadData();
  }, [dataScope, employee?.id, employee?.name]);

  useEffect(() => () => {
    loadRequestSeqRef.current += 1;
  }, []);

  useEffect(() => {
    const employeeId = employee?.id;
    if (!employeeId || typeof window === 'undefined') {
      pendingStorageOwnerRef.current = null;
      pendingStorageHydratingRef.current = false;
      setPendingFinalizations({});
      return;
    }
    const ownerKey = String(employeeId);
    const restored = parsePendingFinalizations(
      window.sessionStorage.getItem(pendingFinalizeStorageKey(ownerKey)),
    );
    pendingStorageOwnerRef.current = ownerKey;
    pendingStorageSnapshotRef.current = JSON.stringify(restored);
    pendingStorageHydratingRef.current = true;
    setPendingFinalizations(restored);
  }, [employee?.id]);

  useEffect(() => {
    const employeeId = employee?.id ? String(employee.id) : null;
    if (!employeeId || pendingStorageOwnerRef.current !== employeeId || typeof window === 'undefined') return;
    const serialized = JSON.stringify(pendingFinalizations);
    if (pendingStorageHydratingRef.current) {
      if (serialized === pendingStorageSnapshotRef.current) {
        pendingStorageHydratingRef.current = false;
      }
      return;
    }
    const storageKey = pendingFinalizeStorageKey(employeeId);
    if (Object.keys(pendingFinalizations).length === 0) {
      window.sessionStorage.removeItem(storageKey);
    } else {
      window.sessionStorage.setItem(storageKey, serialized);
    }
  }, [employee?.id, pendingFinalizations]);

  useAutoRefresh(loadData, {
    intervalMs: 30000,
    enabled: !showForm && !showPackageManager,
  });

  // Build a customer lookup map for quick access to phone, email, zip etc.
  const customerMap = new Map<number, any>();
  customers.forEach(c => customerMap.set(c.id, c));

  const duplicateKeyCounts = deals.reduce<Record<string, number>>((acc, deal) => {
    const key = getDealDuplicateKey(deal);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const duplicateDealIds = new Set(
    deals.filter(deal => duplicateKeyCounts[getDealDuplicateKey(deal)] > 1).map(deal => deal.id)
  );
  const duplicateGroupCount = Object.values(duplicateKeyCounts).filter(count => count > 1).length;

  const setDealFinalizeBusy = (dealId: number, busy: boolean) => {
    setFinalizingDealIds(previous => {
      const next = new Set(previous);
      if (busy) next.add(dealId);
      else next.delete(dealId);
      return next;
    });
  };

  const rememberFinalizeFailure = (
    dealId: number,
    request: DealFinalizeRequest,
    steps: PendingFinalizeStep[],
    retryable = true,
  ) => {
    setPendingFinalizations(previous => ({
      ...previous,
      [dealId]: { request, steps, retryable },
    }));
    const summary = steps.map(step => `${step.label}：${step.message}`).join('；');
    toast.warning(`成交 #${dealId} 已保存，未完成：${summary}`);
  };

  const runDealFinalize = async (
    dealId: number,
    request: DealFinalizeRequest,
    source: 'create' | 'retry' = 'create',
  ) => {
    setDealFinalizeBusy(dealId, true);
    try {
      const response = await finalizeDeal(dealId, request);
      const result = ((response as any)?.data || response) as DealFinalizeResponse;
      if (!result || typeof result.complete !== 'boolean' || !result.steps) {
        throw new Error('服务器未返回完整的交接状态');
      }
      if (result.complete) {
        setPendingFinalizations(previous => {
          const next = { ...previous };
          delete next[dealId];
          return next;
        });
        toast.success(source === 'retry' ? `成交 #${dealId} 的交接已继续完成` : `成交 #${dealId} 已保存并完成交接`);
        return true;
      }

      const failedSteps = Object.entries(result.steps)
        .filter(([, step]) => step.status === 'failed')
        .map(([key, step]) => ({
          key,
          label: finalizeStepLabels[key] || key,
          message: step.message || '未完成，请重试',
        }));
      rememberFinalizeFailure(
        dealId,
        request,
        failedSteps.length > 0
          ? failedSteps
          : [{ key: 'request', label: finalizeStepLabels.request, message: '未完成，请重试' }],
        result.retryable !== false,
      );
      return false;
    } catch (error: any) {
      const message = error?.data?.detail || error?.response?.data?.detail || error?.message || '请求失败，请重试';
      rememberFinalizeFailure(dealId, request, [{
        key: 'request',
        label: finalizeStepLabels.request,
        message: String(message),
      }], true);
      return false;
    } finally {
      setDealFinalizeBusy(dealId, false);
    }
  };

  const retryDealFinalize = async (dealId: number) => {
    const pending = pendingFinalizations[dealId];
    if (!pending || pending.retryable === false || finalizingDealIds.has(dealId)) return;
    await runDealFinalize(dealId, pending.request, 'retry');
    await loadData();
  };

  const ensureOnboardingBoardForDeal = async (deal: any, cust: any, dealId?: number | null) => {
    const platforms = parseMultiValue(deal.package_platforms).length > 0
      ? parseMultiValue(deal.package_platforms)
      : inferPackagePlatforms(deal.package_name, dealPackageLabels, customerPackagePlatforms);
    const steps = buildOnboardingSteps(platforms);
    if (!cust || steps.length === 0) {
      return { platforms, createdCount: 0 };
    }

    const now = new Date().toISOString();
    const actor = employee?.name || '系统自动';
    const customerId = Number(cust.id || deal.customer_id);
    const customerName = cust.business_name || deal.customer_name || '';
    const packageName = deal.package_name || '';
    const normalizedPackageName = normalizeSearchText(packageName);
    const progressRes = await client.entities.service_progresses.queryAll({
      query: { customer_id: customerId },
      limit: 200,
      sort: '-created_at',
    });
    const existingProgresses = progressRes?.data?.items || [];
    let progress = existingProgresses.find((item: any) =>
      item.service_stage !== 'ended' && normalizeSearchText(item.package_name) === normalizedPackageName
    );

    if (!progress) {
      const progressPayload = {
        customer_id: customerId,
        customer_name: customerName,
        service_type: 'social_media',
        service_stage: 'deal_handover',
        progress_percent: 10,
        sales_person: cust.sales_person || deal.sales_name || '',
        ops_person: cust.ops_person || '',
        design_person: '',
        package_name: packageName,
        package_platforms: platforms.join(','),
        industry: cust.industry || '',
        country: cust.country || '',
        state: cust.state || '',
        city: cust.city || '',
        service_start_date: deal.service_start_date || deal.deal_date || null,
        service_end_date: deal.service_end_date || null,
        last_update_time: now,
        last_update_person: actor,
        last_work_summary: '成交后按开关生成前期运营流程',
        issue_status: 'none',
        issue_description: '',
        issue_found_date: null,
        issue_owner: '',
        issue_resolved: true,
        issue_resolved_date: null,
        notes: dealId ? `由成交记录 #${dealId} 按开关生成前期工作看板。` : '由成交记录按开关生成前期工作看板。',
        created_at: now,
      };
      const createdProgressRes = await client.entities.service_progresses.create({ data: progressPayload });
      progress = createdProgressRes?.data;
    } else {
      await client.entities.service_progresses.update({
        id: String(progress.id),
        data: {
          package_name: packageName || progress.package_name,
          package_platforms: platforms.length > 0 ? platforms.join(',') : progress.package_platforms,
          service_start_date: deal.service_start_date || progress.service_start_date || deal.deal_date || null,
          service_end_date: deal.service_end_date || progress.service_end_date || null,
          last_update_time: now,
          last_update_person: actor,
          last_work_summary: '成交后同步检查前期运营流程',
        },
      });
    }

    if (!progress?.id) {
      return { platforms, createdCount: 0 };
    }

    const existingTasksRes = await client.entities.service_tasks.queryAll({
      query: { service_progress_id: progress.id },
      limit: 500,
      sort: 'created_at',
    });
    const existingTaskKeys = new Set(
      (existingTasksRes?.data?.items || []).map((task: any) =>
        `${normalizeSearchText(task.task_name)}|${task.platform || ''}`
      )
    );
    let createdCount = 0;

    for (const step of steps) {
      const taskKey = `${normalizeSearchText(step.task_name)}|${step.platform || ''}`;
      if (existingTaskKeys.has(taskKey)) continue;
      await client.entities.service_tasks.create({
        data: {
          service_progress_id: progress.id,
          customer_id: customerId,
          customer_name: customerName,
          task_name: step.task_name,
          task_type: step.task_type,
          platform: step.platform || null,
          assignee_name: progress.ops_person || null,
          priority: step.priority || 'medium',
          status: 'pending',
          due_date: addDaysDateInput(step.dueOffsetDays),
          completed_date: null,
          notes: `${step.notes} 合作平台：${platforms.map(platform => platformLabels[platform] || platform).join('、')}。`,
          created_at: now,
        },
      });
      existingTaskKeys.add(taskKey);
      createdCount += 1;
    }

    return { platforms, createdCount };
  };

  const handleGenerateServiceBoardForDeal = async (deal: any) => {
    const cust = customerMap.get(Number(deal.customer_id)) || customers.find(c => c.id === Number(deal.customer_id));
    if (!cust) {
      toast.error('找不到这个成交记录对应的客户');
      return;
    }
    setGeneratingBoardId(deal.id);
    try {
      const result = await ensureOnboardingBoardForDeal(deal, cust, deal.id);
      if (result.createdCount > 0) {
        toast.success(`已生成 ${result.createdCount} 个前期运营任务`);
      } else if (result.platforms.length > 0) {
        toast.info('服务看板已存在，前期任务无需重复生成');
      } else {
        toast.warning('当前套餐没有配置可生成的平台流程，请先在套餐管理里选择平台');
      }
    } catch (err) {
      console.error('Generate service board error:', err);
      toast.error('生成服务看板失败，请稍后重试');
    } finally {
      setGeneratingBoardId(null);
    }
  };

  const filtered = deals.filter(d => {
    if (showDuplicatesOnly && !duplicateDealIds.has(d.id)) return false;
    // Text search
    if (search) {
      const q = search.toLowerCase();
      const cust = customerMap.get(d.customer_id);
      const packageClassification = getPackageClassification(d.package_name);
      const matchSearch =
        d.customer_name?.toLowerCase().includes(q) ||
        d.package_name?.toLowerCase().includes(q) ||
        packageClassification.currentLabel.toLowerCase().includes(q) ||
        d.sales_name?.toLowerCase().includes(q) ||
        cust?.phone?.toLowerCase().includes(q) ||
        cust?.email?.toLowerCase().includes(q) ||
        cust?.address?.toLowerCase().includes(q) ||
        cust?.city?.toLowerCase().includes(q) ||
        cust?.customer_code?.toLowerCase().includes(q);
      if (!matchSearch) return false;
    }
    // Product type filter
    if (filterProduct !== 'all' && d.product_type !== filterProduct) return false;
    // Payment status filter
    if (filterPaid !== 'all') {
      if (filterPaid === 'paid' && !d.is_paid) return false;
      if (filterPaid === 'unpaid' && d.is_paid) return false;
    }
    // Billing cycle filter
    if (filterCycle !== 'all' && d.billing_cycle !== filterCycle) return false;
    // Date range filter
    const dealDate = d.deal_date?.slice(0, 10) || '';
    if (filterDateFrom && dealDate < filterDateFrom) return false;
    if (filterDateTo && dealDate > filterDateTo) return false;
    return true;
  });
  const paginated = paginateList(filtered, page, pageSize);

  useEffect(() => {
    setPage(1);
  }, [search, filterProduct, filterPaid, filterCycle, filterDateFrom, filterDateTo, filterDatePreset, showDuplicatesOnly, pageSize]);

  const hasActiveFilters = filterProduct !== 'all' || filterPaid !== 'all' || filterCycle !== 'all' || filterDateFrom || filterDateTo || showDuplicatesOnly;

  const formatDateInput = (value: Date) => {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, '0');
    const day = String(value.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const applyDatePreset = (preset: 'all' | 'month' | 'quarter' | 'year') => {
    const now = new Date();
    let from = '';
    let to = '';

    if (preset === 'month') {
      from = formatDateInput(new Date(now.getFullYear(), now.getMonth(), 1));
      to = formatDateInput(new Date(now.getFullYear(), now.getMonth() + 1, 0));
    } else if (preset === 'quarter') {
      const startMonth = Math.floor(now.getMonth() / 3) * 3;
      from = formatDateInput(new Date(now.getFullYear(), startMonth, 1));
      to = formatDateInput(new Date(now.getFullYear(), startMonth + 3, 0));
    } else if (preset === 'year') {
      from = formatDateInput(new Date(now.getFullYear(), 0, 1));
      to = formatDateInput(new Date(now.getFullYear(), 11, 31));
    }

    setFilterDatePreset(preset);
    setFilterDateFrom(from);
    setFilterDateTo(to);
  };

  const clearFilters = () => {
    setFilterProduct('all');
    setFilterPaid('all');
    setFilterCycle('all');
    setFilterDateFrom('');
    setFilterDateTo('');
    setFilterDatePreset('all');
    setShowDuplicatesOnly(false);
    setSearch('');
  };

  const totalAmount = deals.reduce((s, d) => s + (d.deal_amount || 0), 0);
  const paidDealCount = deals.filter(deal => deal.is_paid).length;
  const unpaidDealCount = deals.length - paidDealCount;
  const pendingHandoffCount = deals.filter(deal => !deal.is_handed_over || !deal.is_transferred_ops).length;

  const PaginationFooter = () => {
    if (paginated.total === 0) return null;
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {paginated.start}-{paginated.end} 条 / 共 {paginated.total} 条
          {filtered.length !== deals.length ? `（筛选自 ${deals.length} 条）` : ''}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">每页</span>
          <NativeSelect
            value={String(pageSize)}
            onChange={value => setPageSize(Number(value))}
            options={PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="w-24 text-xs md:h-8"
          />
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(1)} disabled={paginated.page <= 1}>首页</Button>
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(paginated.page - 1)} disabled={paginated.page <= 1}>上一页</Button>
          <span className="min-w-20 text-center text-xs text-slate-500">{paginated.page} / {paginated.totalPages} 页</span>
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(paginated.page + 1)} disabled={paginated.page >= paginated.totalPages}>下一页</Button>
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(paginated.totalPages)} disabled={paginated.page >= paginated.totalPages}>末页</Button>
        </div>
      </div>
    );
  };

  useEffect(() => {
    if (!showForm && !editingId) {
      setPackageOverrideLabels({});
    }
  }, [showForm, editingId]);

  const openPackageManager = () => {
    setPackageDrafts(Object.entries(customerPackageLabels).map(([key, label]) => ({
      key,
      label,
      platforms: customerPackagePlatforms[key] || inferPackagePlatforms(label, customerPackageLabels, customerPackagePlatforms),
    })));
    setNewPackageName('');
    setShowPackageManager(true);
  };

  const savePackageDrafts = async (draftsToSave: PackageDraft[]) => {
    const normalizedEntries = draftsToSave.reduce<Record<string, string>>((acc, item) => {
      const label = normalizePackageLabel(item.label);
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});
    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      throw new Error('请至少保留一个套餐');
    }
    if (new Set(labels.map(label => label.toLowerCase())).size !== labels.length) {
      throw new Error('套餐名称不能重复');
    }
    const platformEntries = draftsToSave.reduce<Record<string, string[]>>((acc, item) => {
      if (!normalizedEntries[item.key]) return acc;
      const selectedPlatforms = Array.from(new Set((item.platforms || []).filter(platform => Boolean(platformLabels[platform]))));
      const fallbackPlatforms = inferPackagePlatforms(normalizedEntries[item.key], normalizedEntries, customerPackagePlatforms);
      const platforms = selectedPlatforms.length > 0 ? selectedPlatforms : fallbackPlatforms;
      if (platforms.length > 0) acc[item.key] = platforms;
      return acc;
    }, {});

    await saveRemoteAppConfig('dict_config', {
      ...dictConfig,
      customerPackages: serializeDictEntries(normalizedEntries),
      customerPackagePlatforms: serializePackagePlatformEntries(platformEntries),
    });
    const availableKeys = new Set(Object.keys(normalizedEntries));
    const savedDrafts = Object.entries(normalizedEntries).map(([key, label]) => ({ key, label, platforms: platformEntries[key] || [] }));
    setPackageDrafts(savedDrafts);
    setForm(prev => ({
      ...prev,
      package_keys: prev.package_keys.filter(key => availableKeys.has(key) || packageOverrideLabels[key]),
    }));
    return savedDrafts;
  };

  const handleAddPackageDraft = async () => {
    if (savingPackages) return;
    const pendingLabel = newPackageName.trim();
    if (!pendingLabel) {
      toast.error('请输入套餐名称');
      return;
    }

    const result = appendPackageDrafts(packageDrafts, pendingLabel);
    if (result.addedCount === 0) {
      toast.error(result.duplicates.length > 0 ? `该套餐已存在：${result.duplicates.join('、')}` : '请输入套餐名称');
      return;
    }

    setSavingPackages(true);
    try {
      await savePackageDrafts(result.drafts);
      setNewPackageName('');
      toast.success(
        result.duplicates.length > 0
          ? `已添加 ${result.addedCount} 个套餐，已跳过重复：${result.duplicates.join('、')}`
          : `已添加 ${result.addedCount} 个套餐`
      );
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '添加套餐配置失败';
      toast.error(detail);
    } finally {
      setSavingPackages(false);
    }
  };

  const handleRemovePackageDraft = (key: string) => {
    if (packageDrafts.length <= 1) {
      toast.error('至少保留一个套餐');
      return;
    }
    const label = packageDrafts.find(item => item.key === key)?.label || customerPackageLabels[key];
    const usedInDeals = !!label && deals.some(item => parseDealPackageLabels(item.package_name).includes(label));
    const usedInCustomers = customers.some(item => parseMultiValue(item.interested_packages).includes(key));
    if (usedInDeals || usedInCustomers) {
      toast.error('该套餐已有客户或成交记录在使用，请先调整历史数据后再删除');
      return;
    }
    const remaining = packageDrafts.filter(item => item.key !== key);
    setPackageDrafts(remaining);
    if (form.package_keys.includes(key)) {
      setForm(prev => ({ ...prev, package_keys: prev.package_keys.filter(item => item !== key) }));
    }
  };

  const togglePackageDraftPlatform = (packageKey: string, platform: string) => {
    setPackageDrafts(prev => prev.map(item => {
      if (item.key !== packageKey) return item;
      const nextPlatforms = item.platforms.includes(platform)
        ? item.platforms.filter(existing => existing !== platform)
        : [...item.platforms, platform];
      return { ...item, platforms: nextPlatforms };
    }));
  };

  const handleSavePackages = async () => {
    if (savingPackages) return;
    const pendingLabel = newPackageName.trim();
    const result = pendingLabel
      ? appendPackageDrafts(packageDrafts, pendingLabel)
      : { drafts: packageDrafts, addedCount: 0, duplicates: [] as string[] };

    if (pendingLabel && result.addedCount === 0) {
      toast.error(result.duplicates.length > 0 ? `该套餐已存在：${result.duplicates.join('、')}` : '请输入套餐名称');
      return;
    }

    setSavingPackages(true);
    try {
      await savePackageDrafts(result.drafts);
      setShowPackageManager(false);
      setNewPackageName('');
      toast.success(
        result.duplicates.length > 0
          ? `套餐配置已更新，已跳过重复：${result.duplicates.join('、')}`
          : '套餐配置已更新'
      );
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存套餐配置失败';
      toast.error(detail);
    } finally {
      setSavingPackages(false);
    }
  };

  const togglePackageKey = (key: string) => {
    setForm(prev => ({
      ...prev,
      package_keys: prev.package_keys.includes(key)
        ? prev.package_keys.filter(item => item !== key)
        : [...prev.package_keys, key],
    }));
  };

  const openEditDeal = (d: any) => {
    const selectedLabels = parseDealPackageLabels(d.package_name);
    const labelToKey = new Map<string, string>();
    Object.entries(customerPackageLabels).forEach(([key, label]) => labelToKey.set(label, key));
    const customLabels: Record<string, string> = {};
    const packageKeys = selectedLabels.map((label, index) => {
      const matchedKey = labelToKey.get(label);
      if (matchedKey) return matchedKey;
      let tempKey = buildOptionKey(label || `package_${index + 1}`);
      while (customerPackageLabels[tempKey] || customLabels[tempKey]) {
        tempKey = `${tempKey}_${index + 1}`;
      }
      customLabels[tempKey] = label;
      return tempKey;
    });
    setPackageOverrideLabels(customLabels);
    setForm({
      customer_id: String(d.customer_id || ''),
      product_type: d.product_type || 'ordering_system',
      package_name: d.package_name || '',
      package_keys: packageKeys,
      billing_cycle: d.billing_cycle || 'monthly',
      deal_amount: String(d.deal_amount || ''),
      deal_date: d.deal_date?.slice(0, 10) || getTodayDateInput(),
      is_paid: d.is_paid || false,
      service_start_date: d.service_start_date?.slice(0, 10) || '',
      service_end_date: d.service_end_date?.slice(0, 10) || '',
      auto_renew: false,
      create_service_board: false,
      needs_group: d.needs_group || false,
      is_handed_over: d.is_handed_over || false,
      is_transferred_ops: d.is_transferred_ops || false,
      notes: d.notes || '',
    });
    setEditingId(d.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.customer_id || form.package_keys.length === 0 || !form.deal_amount) {
      toast.error('请填写必填字段');
      return;
    }
    setSaving(true);
    try {
      const cust = customers.find(c => c.id === Number(form.customer_id));
      const now = new Date().toISOString();
      const packageName = form.package_keys.map(key => dealPackageLabels[key] || key).filter(Boolean).join('、');
      const payload = {
        customer_id: Number(form.customer_id),
        customer_name: cust?.business_name || '',
        sales_name: cust?.sales_person || '',
        product_type: form.product_type,
        package_name: packageName,
        package_platforms: Array.from(new Set(form.package_keys.flatMap(key => (
          customerPackagePlatforms[key] || inferPackagePlatforms(dealPackageLabels[key] || key, dealPackageLabels, customerPackagePlatforms)
        )))).join(','),
        billing_cycle: form.billing_cycle,
        deal_amount: Number(form.deal_amount),
        deal_date: form.deal_date || null,
        is_paid: form.is_paid,
        service_start_date: form.service_start_date || null,
        service_end_date: form.service_end_date || null,
        needs_group: form.needs_group,
        is_handed_over: form.is_handed_over,
        is_transferred_ops: form.is_transferred_ops,
        notes: form.notes,
      };

      delete (payload as any).package_keys;

      const currentDeal = editingId ? deals.find(deal => Number(deal.id) === Number(editingId)) : null;
      const duplicateSignatureChanged = !currentDeal || getDealDuplicateKey(currentDeal) !== getDealDuplicateKey(payload);
      const duplicateDeal = duplicateSignatureChanged ? deals.find(deal => (
        Number(deal.id) !== Number(editingId || 0)
        && getDealDuplicateKey(deal) === getDealDuplicateKey(payload)
      )) : null;
      if (duplicateDeal) {
        toast.error(`检测到相同成交记录（#${duplicateDeal.id}），请编辑已有记录，避免重复统计金额`);
        return;
      }

      if (editingId) {
        const updatedDealRes = await client.entities.deals.update({ id: String(editingId), data: payload });
        const updatedDeal = updatedDealRes?.data || { ...payload, id: editingId, updated_at: now };
        setDeals(prev => prev.map(item => (item.id === editingId ? { ...item, ...updatedDeal } : item)));
        if (form.create_service_board && cust) {
          try {
            const onboardingResult = await ensureOnboardingBoardForDeal({ ...updatedDeal, ...payload, id: editingId }, cust, editingId);
            if (onboardingResult.createdCount > 0) {
              toast.success(`成交记录已更新，已生成 ${onboardingResult.createdCount} 个前期运营任务`);
            } else if (onboardingResult.platforms.length > 0) {
              toast.success('成交记录已更新，服务看板已存在');
            } else {
              toast.success('成交记录已更新，当前套餐暂无可生成的平台流程');
            }
          } catch (onboardingErr) {
            console.error('Create onboarding board error:', onboardingErr);
            toast.warning('成交记录已更新，但服务看板生成失败，请到列表手动生成');
          }
        } else {
          toast.success('成交记录已更新');
        }
      } else {
        const signature = getDealDuplicateKey(payload);
        let matchingBefore: any[];
        try {
          const beforeRes = await client.entities.deals.query({
            query: { customer_id: Number(form.customer_id) },
            limit: 2000,
            sort: '-deal_date',
          });
          matchingBefore = (beforeRes?.data?.items || []).filter((deal: any) => getDealDuplicateKey(deal) === signature);
        } catch (preflightError) {
          console.error('Deal duplicate preflight failed:', preflightError);
          toast.error('暂时无法核对服务器成交记录，请刷新后重试；本次没有提交新成交');
          return;
        }
        if (matchingBefore.length > 0) {
          toast.error(`服务器已有相同成交记录（#${matchingBefore.map(item => item.id).join('、#')}），请核对已有记录`);
          return;
        }

        const idsBefore = new Set(matchingBefore.map(item => Number(item.id)));
        let createdDeal: any = null;
        try {
          const createdDealRes = await client.entities.deals.create({ data: { ...payload, created_at: now } });
          createdDeal = createdDealRes?.data;
        } catch (createError) {
          console.error('Deal create response unavailable, reconciling:', createError);
          try {
            const recoveryRes = await client.entities.deals.query({
              query: { customer_id: Number(form.customer_id) },
              limit: 2000,
              sort: '-deal_date',
            });
            const newMatches = (recoveryRes?.data?.items || []).filter((deal: any) => (
              getDealDuplicateKey(deal) === signature && !idsBefore.has(Number(deal.id))
            ));
            if (newMatches.length === 1) {
              createdDeal = newMatches[0];
              toast.info(`成交 #${createdDeal.id} 已在服务器保存，正在继续完成交接`);
            } else if (newMatches.length === 0) {
              toast.error('服务器未发现本次成交记录，本次未确认保存；请检查网络后明确重试');
              return;
            } else {
              toast.error(`服务器发现 ${newMatches.length} 条新的相同成交，已停止自动处理；请人工核对后再操作`);
              return;
            }
          } catch (recoveryError) {
            console.error('Deal create reconciliation failed:', recoveryError);
            toast.warning('成交提交结果暂时无法确认，请刷新列表核对；为避免重复，本页不会自动再次提交');
            return;
          }
        }
        if (!createdDeal?.id) {
          throw new Error('成交已提交，但服务器未返回成交编号，请刷新后核对');
        }
        setDeals(prev => [createdDeal, ...prev]);
        await runDealFinalize(Number(createdDeal.id), {
          ensure_subscription: Boolean(form.service_start_date && form.service_end_date),
          auto_renew: form.auto_renew,
          create_service_board: form.create_service_board,
        });
      }
      setPackageOverrideLabels({});
      setShowForm(false);
      setEditingId(null);
      setForm(buildEmptyDealForm());
      await loadData();
    } catch (err) { toast.error('保存失败'); console.error(err); }
    finally { setSaving(false); }
  };

  const handleDeleteDeal = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.deals.delete({ id: String(deleteTarget.id) });
      toast.success('成交记录已删除');
      setDeleteTarget(null);
      loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); }
    finally { setDeleting(false); }
  };

  if (loading && deals.length === 0) {
    return <PageLoadState loading message="正在核对成交记录与交付状态…" />;
  }
  if (loadError && deals.length === 0) {
    return <PageLoadState error={loadError} onRetry={() => { setLoading(true); void loadData(); }} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">成交管理</h2>
          <p className="text-sm text-slate-500">共 {deals.length} 笔成交，总金额 ${totalAmount.toLocaleString()}</p>
        </div>
        <div className="hidden gap-2 md:flex">
          <ExportButton
            data={filtered.map(d => ({
              ...d,
              package_classification: getPackageClassification(d.package_name).currentLabel,
              package_historical_name: getPackageClassification(d.package_name).changed ? d.package_name : '',
              product_type_label: productLabels[d.product_type] || d.product_type,
              billing_cycle_label: cycleLabels[d.billing_cycle] || d.billing_cycle,
              is_paid_label: d.is_paid ? '已付' : '未付',
              is_handed_over_label: d.is_handed_over ? '已交接' : '待交接',
              is_transferred_ops_label: d.is_transferred_ops ? '已转运营' : '未转运营',
              deal_date_short: d.deal_date?.slice(0, 10) || '',
              service_start_short: d.service_start_date?.slice(0, 10) || '',
              service_end_short: d.service_end_date?.slice(0, 10) || '',
            }))}
            columns={[
              { key: 'customer_name', label: '客户名称' },
              { key: 'sales_name', label: '销售' },
              { key: 'product_type_label', label: '产品类型' },
              { key: 'package_classification', label: '当前套餐归类' },
              { key: 'package_historical_name', label: '历史成交原名' },
              { key: 'deal_amount', label: '成交金额' },
              { key: 'billing_cycle_label', label: '服务周期' },
              { key: 'deal_date_short', label: '成交日期' },
              { key: 'is_paid_label', label: '付款状态' },
              { key: 'is_handed_over_label', label: '交接状态' },
              { key: 'is_transferred_ops_label', label: '转运营' },
              { key: 'service_start_short', label: '服务开始' },
              { key: 'service_end_short', label: '服务到期' },
              { key: 'notes', label: '备注' },
            ]}
            filename={`成交记录_${businessDateKey()}`}
            sheetName="成交记录"
          />
          <Button onClick={() => { setPackageOverrideLabels({}); setForm(buildEmptyDealForm()); setEditingId(null); setShowForm(true); }} className="bg-blue-600 hover:bg-blue-700">
            <Plus className="w-4 h-4 mr-1" /> 录入成交
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-xs text-slate-500">成交记录</p><p className="mt-1 text-2xl font-semibold text-slate-900">{deals.length}</p><p className="mt-1 text-xs text-slate-400">总额 ${totalAmount.toLocaleString()}</p></CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-xs text-slate-500">已付款</p><p className="mt-1 text-2xl font-semibold text-emerald-600">{paidDealCount}</p><p className="mt-1 text-xs text-slate-400">已确认收款</p></CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-xs text-slate-500">未付款</p><p className="mt-1 text-2xl font-semibold text-red-600">{unpaidDealCount}</p><p className="mt-1 text-xs text-slate-400">需要跟进</p></CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-xs text-slate-500">待完成交接</p><p className="mt-1 text-2xl font-semibold text-amber-600">{pendingHandoffCount}</p><p className="mt-1 text-xs text-slate-400">交接或转运营未完成</p></CardContent></Card>
        <Card className={duplicateGroupCount > 0 ? 'border-orange-200 bg-orange-50/60' : 'border-slate-200'}>
          <CardContent className="p-0">
            <button type="button" className="w-full p-4 text-left" onClick={() => setShowDuplicatesOnly(value => !value)} aria-pressed={showDuplicatesOnly}>
              <p className="text-xs text-slate-500">疑似重复组</p>
              <p className={`mt-1 text-2xl font-semibold ${duplicateGroupCount > 0 ? 'text-orange-600' : 'text-slate-500'}`}>{duplicateGroupCount}</p>
              <p className="mt-1 text-xs text-slate-400">{showDuplicatesOnly ? '正在仅看重复记录' : '点击筛选核对'}</p>
            </button>
          </CardContent>
        </Card>
      </div>

      {duplicateGroupCount > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>发现 {duplicateGroupCount} 组客户、套餐、金额、周期和成交日期完全相同的记录。系统已阻止继续录入相同成交；请筛选后逐条确认，不会自动删除历史数据。</span>
        </div>
      )}

      {/* Search & Filters */}
      <Card className="border-slate-200">
        <CardContent className="p-3 space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <Input placeholder="搜索客户名称、电话、邮箱、地址、套餐、销售..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
          </div>
          <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
            <NativeSelect
              value={filterProduct}
              onChange={setFilterProduct}
              className="w-full sm:w-[150px]"
              options={[{ value: 'all', label: '全部产品' }, ...Object.entries(productLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <NativeSelect
              value={filterPaid}
              onChange={setFilterPaid}
              className="w-full sm:w-[130px]"
              options={[{ value: 'all', label: '全部状态' }, { value: 'paid', label: '已付款' }, { value: 'unpaid', label: '未付款' }]}
            />
            <NativeSelect
              value={filterCycle}
              onChange={setFilterCycle}
              className="w-full sm:w-[130px]"
              options={[{ value: 'all', label: '全部周期' }, ...Object.entries(cycleLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
              {([
                { value: 'all', label: '全部' },
                { value: 'month', label: '本月' },
                { value: 'quarter', label: '本季度' },
                { value: 'year', label: '本年' },
              ] as const).map((preset) => (
                <button
                  type="button"
                  key={preset.value}
                  onClick={() => applyDatePreset(preset.value)}
                  className={`min-h-11 whitespace-nowrap rounded-md px-2.5 text-sm font-medium transition md:min-h-9 ${
                    filterDatePreset === preset.value
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'text-slate-600 hover:bg-white hover:text-blue-700'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Input
                type="date"
                value={filterDateFrom}
                onChange={e => {
                  setFilterDatePreset('custom');
                  setFilterDateFrom(e.target.value);
                }}
                className="w-full text-sm sm:w-[145px]"
                placeholder="开始日期"
              />
              <span className="text-slate-400 text-sm">至</span>
              <Input
                type="date"
                value={filterDateTo}
                onChange={e => {
                  setFilterDatePreset('custom');
                  setFilterDateTo(e.target.value);
                }}
                className="w-full text-sm sm:w-[145px]"
                placeholder="结束日期"
              />
            </div>
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="text-slate-500 hover:text-slate-700 shrink-0">
                清除筛选
              </Button>
            )}
          </div>
          {hasActiveFilters && (
            <p className="text-xs text-slate-500">
              筛选结果：{filtered.length} 条记录，合计 (USD) ${filtered.reduce((s, d) => s + (d.deal_amount || 0), 0).toLocaleString()}
            </p>
          )}
        </CardContent>
      </Card>

      {Object.keys(pendingFinalizations).length > 0 && (
        <Card className="border-amber-300 bg-amber-50" data-testid="deal-finalize-pending-list">
          <CardContent className="space-y-3 p-4">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
              <div>
                <p className="font-semibold text-amber-900">成交已保存，部分交接仍需完成</p>
                <p className="mt-1 text-xs text-amber-800">继续完成只会补齐缺少的记录，不会重复创建成交。</p>
              </div>
            </div>
            {Object.entries(pendingFinalizations).map(([rawDealId, pending]) => {
              const dealId = Number(rawDealId);
              const busy = finalizingDealIds.has(dealId);
              const canRetry = pending.retryable !== false;
              return (
                <div
                  key={dealId}
                  role="alert"
                  data-testid={`deal-finalize-pending-${dealId}`}
                  className="flex flex-col gap-3 rounded-lg border border-amber-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-slate-900">成交 #{dealId} 已保存，交接未完成</p>
                    <ul className="mt-1 space-y-1 text-sm text-amber-800">
                      {pending.steps.map(step => (
                        <li key={`${step.key}-${step.message}`}>{step.label}：{step.message}</li>
                      ))}
                    </ul>
                    {!canRetry && (
                      <p className="mt-2 text-xs font-medium text-red-700">该问题无法靠重复点击解决，请联系老板/管理员在电脑端核对后处理。</p>
                    )}
                  </div>
                  <Button
                    type="button"
                    className="min-h-11 shrink-0 bg-amber-700 text-white hover:bg-amber-800"
                    disabled={busy || !canRetry}
                    aria-label={canRetry ? `继续完成交接 #${dealId}` : `交接需要管理员处理 #${dealId}`}
                    onClick={() => void retryDealFinalize(dealId)}
                  >
                    <ClipboardCheck className="mr-2 h-4 w-4" />
                    {busy ? '正在继续...' : canRetry ? '继续完成交接' : '需要管理员处理'}
                  </Button>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Deals list */}
      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-400 py-12">暂无成交记录</p>
          ) : (
            <>
            <div className="grid gap-3 p-3 md:hidden">
              {paginated.items.map(d => {
                const isDuplicate = duplicateDealIds.has(d.id);
                const packageClassification = getPackageClassification(d.package_name);
                return (
                <div key={d.id} className={`rounded-xl border bg-white p-4 shadow-sm ${isDuplicate ? 'border-orange-200 ring-1 ring-orange-100' : 'border-slate-200'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <button type="button" className="min-w-0 text-left" onClick={() => navigate(`/customers?detail=${d.customer_id}&tab=deals`)}>
                      <p className="truncate font-semibold text-blue-700">{d.customer_name}</p>
                      <p className="mt-1 text-xs text-slate-400">{d.deal_date?.slice(0, 10) || '-'} · {d.sales_name || '未分配销售'}</p>
                    </button>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge className={d.is_paid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>{d.is_paid ? '已付' : '未付'}</Badge>
                      {isDuplicate && <Badge className="bg-orange-100 text-orange-700">疑似重复</Badge>}
                    </div>
                  </div>
                  <div className="mt-3 rounded-lg bg-slate-50 p-3">
                    <div className="flex items-center justify-between gap-3"><p className="font-medium text-slate-800">{packageClassification.currentLabel}</p><p className="font-semibold text-emerald-600">${Number(d.deal_amount || 0).toLocaleString()}</p></div>
                    {packageClassification.changed && <p className="mt-1 text-xs text-slate-400">历史成交原名：{packageClassification.historicalLabel}</p>}
                    <p className="mt-1 text-xs text-slate-500">{productLabels[d.product_type] || d.product_type || '-'} · {cycleLabels[d.billing_cycle] || d.billing_cycle || '-'}</p>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                    <div><p className="text-xs text-slate-400">交接</p><p className="mt-1 text-slate-700">{d.is_handed_over ? '已交接' : '待交接'}</p></div>
                    <div><p className="text-xs text-slate-400">运营</p><p className="mt-1 text-slate-700">{d.is_transferred_ops ? '已转运营' : '待转运营'}</p></div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
                    <Button size="sm" variant="outline" className="flex-1" onClick={() => navigate(`/customers?detail=${d.customer_id}&tab=deals`)}><ExternalLink className="mr-1 h-3.5 w-3.5" />客户详情</Button>
                    {hasPermission('deal_edit') && <Button size="sm" variant="outline" className="h-11 flex-1 border-emerald-200 text-emerald-700" disabled={generatingBoardId === d.id} onClick={() => void handleGenerateServiceBoardForDeal(d)}><ClipboardCheck className="mr-1 h-4 w-4" />{generatingBoardId === d.id ? '生成中' : '生成看板'}</Button>}
                    {hasPermission('deal_edit') && <Button size="sm" variant="outline" className="h-11 flex-1" onClick={() => openEditDeal(d)}><Edit className="mr-1 h-4 w-4" />编辑交接</Button>}
                  </div>
                </div>
                );
              })}
            </div>
            {!isMobile && <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-slate-50 text-left text-slate-500">
                    <th className="px-4 py-3 font-medium">客户</th>
                    <th className="px-4 py-3 font-medium">套餐归类</th>
                    <th className="px-4 py-3 font-medium">业务类型</th>
                    <th className="px-4 py-3 font-medium">金额</th>
                    <th className="px-4 py-3 font-medium">周期</th>
                    <th className="px-4 py-3 font-medium hidden md:table-cell">成交日</th>
                    <th className="px-4 py-3 font-medium hidden md:table-cell">付款</th>
                    <th className="px-4 py-3 font-medium hidden lg:table-cell">交接</th>
                    <th className="px-4 py-3 font-medium w-36">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {paginated.items.map(d => (
                    <tr key={d.id} className={`border-b hover:bg-slate-50 ${duplicateDealIds.has(d.id) ? 'border-orange-100 bg-orange-50/50' : 'border-slate-100'}`}>
                      <td className="px-4 py-3 font-medium">
                        <button type="button" className="text-left text-blue-700 hover:underline" onClick={() => navigate(`/customers?detail=${d.customer_id}&tab=deals`)}>{d.customer_name}</button>
                        {duplicateDealIds.has(d.id) && <div className="mt-1 text-xs font-medium text-orange-600">疑似重复记录</div>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-700">{getPackageClassification(d.package_name).currentLabel}</div>
                        {getPackageClassification(d.package_name).changed && <div className="mt-1 text-xs text-slate-400">历史：{getPackageClassification(d.package_name).historicalLabel}</div>}
                      </td>
                      <td className="px-4 py-3"><Badge variant="secondary" className="text-xs">{productLabels[d.product_type] || d.product_type}</Badge></td>
                      <td className="px-4 py-3 font-bold text-green-600">${d.deal_amount}</td>
                      <td className="px-4 py-3 text-slate-500">{cycleLabels[d.billing_cycle] || d.billing_cycle}</td>
                      <td className="px-4 py-3 text-slate-500 hidden md:table-cell">{d.deal_date?.slice(0, 10)}</td>
                      <td className="px-4 py-3 hidden md:table-cell">{d.is_paid ? <Badge className="bg-green-100 text-green-700 text-xs">已付</Badge> : <Badge className="bg-red-100 text-red-700 text-xs">未付</Badge>}</td>
                      <td className="px-4 py-3 hidden lg:table-cell">{d.is_handed_over ? '✅' : '⏳'} {d.is_transferred_ops ? '→运营' : ''}</td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
                            disabled={generatingBoardId === d.id}
                            onClick={() => void handleGenerateServiceBoardForDeal(d)}
                            title="按这条成交记录生成或补齐服务看板"
                          >
                            <ClipboardCheck className="w-3.5 h-3.5 mr-1" />
                            {generatingBoardId === d.id ? '生成中' : '看板'}
                          </Button>
                          <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-blue-600" title="编辑成交" aria-label={`编辑 ${d.customer_name} 的成交记录`} onClick={() => openEditDeal(d)}><Edit className="w-3.5 h-3.5" /></Button>
                          <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" title="删除成交" aria-label={`删除 ${d.customer_name} 的成交记录`} onClick={() => setDeleteTarget(d)}><Trash2 className="w-3.5 h-3.5" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>}
            </>
          )}
          {filtered.length > 0 && <PaginationFooter />}
        </CardContent>
      </Card>

      {!isMobile && <Dialog open={showPackageManager} onOpenChange={(open) => { setShowPackageManager(open); if (!open) setNewPackageName(''); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>管理套餐</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="flex items-center gap-2">
              <Input
                value={newPackageName}
                onChange={e => setNewPackageName(e.target.value)}
                placeholder="新增套餐，例如：Google商家管理"
                onKeyDown={e => {
                  if (e.key === 'Enter' && !savingPackages) {
                    e.preventDefault();
                    void handleAddPackageDraft();
                  }
                }}
              />
              <Button type="button" onClick={() => void handleAddPackageDraft()} disabled={savingPackages}>
                {savingPackages ? '保存中...' : '添加'}
              </Button>
            </div>
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {packageDrafts.map(item => (
                <div key={item.key} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <Input
                        value={item.label}
                        onChange={e => setPackageDrafts(prev => prev.map(pkg => (pkg.key === item.key ? { ...pkg, label: e.target.value } : pkg)))}
                        className="h-8 text-sm"
                        placeholder="套餐名称，例如：A套餐"
                      />
                      <p className="mt-1 truncate text-xs text-slate-400">{item.key}</p>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-slate-500 hover:text-red-600"
                      onClick={() => handleRemovePackageDraft(item.key)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(platformLabels).map(([platform, label]) => (
                      <label key={platform} className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600">
                        <input
                          type="checkbox"
                          checked={item.platforms.includes(platform)}
                          onChange={() => togglePackageDraftPlatform(item.key, platform)}
                          className="h-3 w-3 rounded"
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowPackageManager(false)}>取消</Button>
              <Button onClick={handleSavePackages} disabled={savingPackages}>
                {savingPackages ? '保存中...' : '保存'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>}

      {!isMobile && <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除成交记录"
        description={`确定要删除「${deleteTarget?.customer_name} - ${deleteTarget?.package_name}」的成交记录吗？`}
        onConfirm={handleDeleteDeal}
        loading={deleting}
      />}

      {/* Add/Edit deal dialog */}
      <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setPackageOverrideLabels({}); setEditingId(null); setForm(buildEmptyDealForm()); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑成交记录' : '录入成交'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>选择客户 *</Label>
              <CustomerCombobox
                customers={dataScope === 'self' && employee
                  ? customers.filter(c => c.sales_person === employee.name || c.sales_employee_id === employee.id)
                  : customers}
                value={form.customer_id}
                onValueChange={v => setForm({ ...form, customer_id: v })}
                placeholder="搜索客户编号、名称、联系人或电话"
              />
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <Label>产品类型</Label>
                <NativeSelect
                  value={form.product_type}
                  onChange={v => setForm({ ...form, product_type: v })}
                  options={Object.entries(productLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              <div>
                <Label>服务周期</Label>
                <NativeSelect
                  value={form.billing_cycle}
                  onChange={v => setForm({ ...form, billing_cycle: v })}
                  options={Object.entries(cycleLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label>套餐名称 *</Label>
                {!isMobile && <Button type="button" variant="outline" size="sm" onClick={openPackageManager}>
                  管理套餐
                </Button>}
              </div>
              <div className="max-h-56 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-3">
                {dealPackageOptions.length === 0 ? (
                  <p className="text-sm text-slate-500">暂无可选套餐，请先添加套餐。</p>
                ) : (
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {dealPackageOptions.map(option => (
                      <label key={option.value} className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.package_keys.includes(option.value)}
                          onChange={() => togglePackageKey(option.value)}
                        />
                        <span>{option.label}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-xs text-slate-500">
                已选套餐：
                {form.package_keys.length > 0
                  ? ` ${form.package_keys.map(key => dealPackageLabels[key] || key).join('、')}`
                  : ' 暂未选择'}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div><Label>成交金额 *</Label><Input type="number" value={form.deal_amount} onChange={e => setForm({ ...form, deal_amount: e.target.value })} placeholder="0.00" /></div>
              <div><Label>成交日期</Label><Input type="date" value={form.deal_date} onChange={e => setForm({ ...form, deal_date: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div><Label>服务开始日期</Label><Input type="date" value={form.service_start_date} onChange={e => setForm({ ...form, service_start_date: e.target.value })} /></div>
              <div><Label>服务到期日期</Label><Input type="date" value={form.service_end_date} onChange={e => setForm({ ...form, service_end_date: e.target.value })} /></div>
            </div>
            <div className={`rounded-lg border p-3 ${form.create_service_board ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <Label className="text-sm font-semibold text-slate-800">生成服务看板</Label>
                  <p className="mt-1 text-xs text-slate-500">
                    默认关闭，适合补录旧系统成交。只有新客户需要正式交付时再打开，系统会按套餐平台生成前期运营流程。
                  </p>
                </div>
                <Switch checked={form.create_service_board} onCheckedChange={v => setForm({ ...form, create_service_board: v })} />
              </div>
            </div>
            <div className="flex flex-wrap gap-6">
              <div className="flex items-center gap-2"><Switch checked={form.is_paid} onCheckedChange={v => setForm({ ...form, is_paid: v })} /><Label>已付款</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.auto_renew} onCheckedChange={v => setForm({ ...form, auto_renew: v })} /><Label>开启续费开关</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.needs_group} onCheckedChange={v => setForm({ ...form, needs_group: v })} /><Label>需要建群</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.is_handed_over} onCheckedChange={v => setForm({ ...form, is_handed_over: v })} /><Label>已交接</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.is_transferred_ops} onCheckedChange={v => setForm({ ...form, is_transferred_ops: v })} /><Label>已转运营</Label></div>
            </div>
            <div><Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} /></div>
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
