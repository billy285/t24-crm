import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { getCountryLabel, getStateLabel } from '../lib/country-state-data';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Search, ExternalLink } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import { Combobox } from '@/components/ui/combobox';
import ExportButton from '@/components/ExportButton';
import { useBusinessDicts } from '../lib/dict-config';
import {
  computeSubscriptionStatus,
  decorateEffectiveSubscriptions,
  getSubscriptionRemainingDays,
} from '../lib/subscription-utils';

const subStatusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  expiring_soon: 'bg-amber-100 text-amber-700',
  renewal_pending: 'bg-cyan-100 text-cyan-700',
  expired: 'bg-red-100 text-red-700',
  paused: 'bg-slate-100 text-slate-600',
  lost: 'bg-red-100 text-red-700',
  renewed: 'bg-emerald-100 text-emerald-700',
  none: 'bg-slate-100 text-slate-500',
};

const serviceStatusLabels: Record<string, string> = {
  none: '未建服务',
  active: '正常',
  expiring_soon: '即将到期',
  renewal_pending: '待扣款确认',
  expired: '已到期',
  renewed: '已续费',
  paused: '暂停',
  lost: '流失',
};

const fmt = (value: number) => `$${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

const parseMultiValue = (value: any): string[] => {
  if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean);
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean);
};

const parsePackageSnapshot = (value: any): Record<string, string> => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(String(value));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.entries(parsed).reduce<Record<string, string>>((acc, [key, raw]) => {
      if (typeof raw === 'string') acc[key] = raw;
      else if (raw && typeof raw === 'object' && typeof (raw as any).label === 'string') acc[key] = (raw as any).label;
      return acc;
    }, {});
  } catch {
    return {};
  }
};

const getLatestTime = (item: any, dateFields: string[]) => {
  if (!item) return 0;
  return dateFields.reduce((latest, field) => {
    const value = item[field];
    if (!value) return latest;
    const time = new Date(value).getTime();
    return Number.isNaN(time) ? latest : Math.max(latest, time);
  }, 0);
};

const packageSourceLabels: Record<string, string> = {
  deal: '来自成交记录',
  payment: '来自收款记录',
  subscription: '来自续费记录',
  customer: '来自客户资料',
};
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

export default function Sales() {
  const { employee, dataScope, canViewFinance } = useRole();
  const {
    billingCycles: cycleLabels,
    customerPackages: customerPackageLabels,
    subscriptionStatuses: subStatusLabels,
  } = useBusinessDicts();
  const navigate = useNavigate();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterCustomerId, setFilterCustomerId] = useState('all');
  const [filterServiceStatus, setFilterServiceStatus] = useState('all');
  const [filterSalesPerson, setFilterSalesPerson] = useState('all');
  const [filterCountry, setFilterCountry] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [customerRes, dealRes, subRes, paymentRes] = await Promise.all([
        client.entities.customers.query({ limit: 1000, sort: '-updated_at' }),
        client.entities.deals.query({ limit: 1000, sort: '-deal_date' }),
        client.entities.subscriptions.query({ limit: 1000, sort: '-end_date' }),
        canViewFinance
          ? client.entities.payments.queryAll({ limit: 1000, sort: '-payment_date' })
          : Promise.resolve({ data: { items: [] } }),
      ]);

      let customerItems = customerRes?.data?.items || [];
      const dealItems = dealRes?.data?.items || [];
      const subscriptionItems = decorateEffectiveSubscriptions(subRes?.data?.items || []);
      const paymentItems = paymentRes?.data?.items || [];

      if (dataScope === 'self' && employee) {
        customerItems = customerItems.filter(
          (customer: any) => customer.sales_person === employee.name || customer.sales_employee_id === employee.id,
        );
      }

      const latestDealByCustomer: Record<number, any> = {};
      dealItems.forEach((deal: any) => {
        const customerId = Number(deal.customer_id || 0);
        if (!customerId) return;
        if (!latestDealByCustomer[customerId] || getLatestTime(deal, ['deal_date', 'created_at', 'updated_at']) > getLatestTime(latestDealByCustomer[customerId], ['deal_date', 'created_at', 'updated_at'])) {
          latestDealByCustomer[deal.customer_id] = deal;
        }
      });

      const latestSubscriptionByCustomer: Record<number, any> = {};
      subscriptionItems.forEach((subscription: any) => {
        const customerId = Number(subscription.customer_id || 0);
        if (!customerId) return;
        if (!latestSubscriptionByCustomer[customerId] || getLatestTime(subscription, ['end_date', 'updated_at', 'created_at']) > getLatestTime(latestSubscriptionByCustomer[customerId], ['end_date', 'updated_at', 'created_at'])) {
          latestSubscriptionByCustomer[subscription.customer_id] = subscription;
        }
      });

      const latestPaymentByCustomer: Record<number, any> = {};
      const outstandingByCustomer: Record<number, number> = {};
      paymentItems.forEach((payment: any) => {
        const customerId = Number(payment.customer_id || 0);
        if (!customerId) return;
        if (!latestPaymentByCustomer[customerId] || getLatestTime(payment, ['payment_date', 'created_at', 'updated_at']) > getLatestTime(latestPaymentByCustomer[customerId], ['payment_date', 'created_at', 'updated_at'])) {
          latestPaymentByCustomer[customerId] = payment;
        }
        outstandingByCustomer[customerId] = (outstandingByCustomer[customerId] || 0) + Number(payment.outstanding_amount || 0);
      });

      const closedCustomerIds = new Set<number>();
      customerItems.forEach((customer: any) => {
        if (customer.status === 'closed') closedCustomerIds.add(customer.id);
      });
      dealItems.forEach((deal: any) => {
        if (deal.customer_id) closedCustomerIds.add(deal.customer_id);
      });

      const closedRows = customerItems
        .filter((customer: any) => closedCustomerIds.has(customer.id))
        .map((customer: any) => {
          const latestDeal = latestDealByCustomer[customer.id];
          const latestSubscription = latestSubscriptionByCustomer[customer.id];
          const latestPayment = latestPaymentByCustomer[customer.id];
          const serviceStatus = latestSubscription ? computeSubscriptionStatus(latestSubscription) : 'none';
          const packageSnapshot = parsePackageSnapshot(customer.interested_packages_snapshot);
          const customerPackageName = parseMultiValue(customer.interested_packages)
            .map(key => packageSnapshot[key] || customerPackageLabels[key] || key)
            .filter(Boolean)
            .join('、');
          const selectedPackage =
            latestDeal?.package_name
              ? { name: latestDeal.package_name, source: 'deal' }
              : latestPayment?.product_name
                ? { name: latestPayment.product_name, source: 'payment' }
                : latestSubscription?.package_name
                  ? { name: latestSubscription.package_name, source: 'subscription' }
                  : customerPackageName
                    ? { name: customerPackageName, source: 'customer' }
                    : { name: '-', source: '' };
          const currentPackage =
            latestSubscription?.package_name
              ? { name: latestSubscription.package_name, source: 'subscription' }
              : selectedPackage;

          return {
            id: customer.id,
            customer_code: customer.customer_code || '',
            business_name: customer.business_name || '',
            contact_name: customer.contact_name || '',
            phone: customer.phone || '',
            sales_person: customer.sales_person || '',
            country: customer.country || '',
            country_label: customer.country ? getCountryLabel(customer.country) : '-',
            state: customer.state || '',
            state_label: customer.country && customer.state ? getStateLabel(customer.country, customer.state) : (customer.state || '-'),
            selected_package_name: selectedPackage.name,
            selected_package_source: selectedPackage.source ? packageSourceLabels[selectedPackage.source] : '',
            latest_package_name: currentPackage.name,
            latest_package_source: currentPackage.source ? packageSourceLabels[currentPackage.source] : '',
            latest_deal_amount: Number(latestDeal?.deal_amount || latestPayment?.amount_due || 0),
            latest_deal_date: latestDeal?.deal_date || latestPayment?.payment_date || customer.updated_at || customer.created_at,
            latest_payment_date: latestPayment?.payment_date || '',
            latest_payment_amount: Number(latestPayment?.amount_paid || 0),
            service_status: serviceStatus,
            service_end_date: latestSubscription?.end_date || '',
            service_remaining_days: getSubscriptionRemainingDays(latestSubscription),
            next_payment_date: latestSubscription?.next_payment_date || '',
            auto_renew: Boolean(latestSubscription?.auto_renew),
            billing_cycle: latestSubscription?.billing_cycle || latestDeal?.billing_cycle || '',
            outstanding_amount: Number(outstandingByCustomer[customer.id] || 0),
          };
        })
        .sort((a: any, b: any) => {
          const aTime = a.latest_deal_date ? new Date(a.latest_deal_date).getTime() : 0;
          const bTime = b.latest_deal_date ? new Date(b.latest_deal_date).getTime() : 0;
          return bTime - aTime;
        });

      setRows(closedRows);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const salesPersonOptions = Array.from(new Set(rows.map(row => row.sales_person).filter(Boolean)))
    .sort((a, b) => a.localeCompare(b, 'zh-CN'))
    .map(name => ({ value: name, label: name }));

  const countryOptions = Array.from(new Set(rows.map(row => row.country).filter(Boolean)))
    .sort((a, b) => a.localeCompare(b, 'en-US'))
    .map(code => ({ value: code, label: getCountryLabel(code) }));

  const customerOptions = rows
    .map(row => ({
      value: String(row.id),
      label: [
        row.business_name || `客户#${row.id}`,
        row.customer_code,
        row.contact_name,
        row.phone,
      ].filter(Boolean).join(' · '),
    }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));

  const filtered = rows.filter(row => {
    const searchValue = search.trim().toLowerCase();
    const matchesSearch = !searchValue || [
      row.customer_code,
      row.business_name,
      row.contact_name,
      row.phone,
      row.sales_person,
      row.selected_package_name,
      row.latest_package_name,
      row.country_label,
      row.state,
      row.state_label,
    ].some(field => String(field || '').toLowerCase().includes(searchValue));

    const matchesCustomer = filterCustomerId === 'all' || String(row.id) === filterCustomerId;
    const matchesServiceStatus = filterServiceStatus === 'all' || row.service_status === filterServiceStatus;
    const matchesSalesPerson = filterSalesPerson === 'all' || row.sales_person === filterSalesPerson;
    const matchesCountry = filterCountry === 'all' || row.country === filterCountry;

    return matchesCustomer && matchesSearch && matchesServiceStatus && matchesSalesPerson && matchesCountry;
  });
  const paginated = paginateList(filtered, page, pageSize);

  useEffect(() => {
    setPage(1);
  }, [search, filterCustomerId, filterServiceStatus, filterSalesPerson, filterCountry, pageSize]);

  const totalClosedCustomers = rows.length;
  const activeCustomers = rows.filter(row => row.service_status === 'active').length;
  const renewalCustomers = rows.filter(row => ['expiring_soon', 'expired', 'renewal_pending'].includes(row.service_status)).length;
  const outstandingCustomers = rows.filter(row => row.outstanding_amount > 0).length;

  const exportData = filtered.map(row => ({
    customer_code: row.customer_code,
    business_name: row.business_name,
    contact_name: row.contact_name,
    phone: row.phone,
    state: row.state || '',
    country: row.country_label,
    selected_package_name: row.selected_package_name,
    selected_package_source: row.selected_package_source,
    latest_package_name: row.latest_package_name,
    latest_package_source: row.latest_package_source,
    latest_deal_amount: row.latest_deal_amount ? fmt(row.latest_deal_amount) : '-',
    latest_deal_date: row.latest_deal_date?.slice(0, 10) || '',
    latest_payment_date: row.latest_payment_date?.slice(0, 10) || '',
    latest_payment_amount: row.latest_payment_amount ? fmt(row.latest_payment_amount) : '-',
    service_status: subStatusLabels[row.service_status] || serviceStatusLabels[row.service_status] || row.service_status,
    billing_cycle: cycleLabels[row.billing_cycle] || row.billing_cycle || '',
    service_end_date: row.service_end_date?.slice(0, 10) || '',
    service_remaining_text: row.service_remaining_days == null
      ? '-'
      : row.service_remaining_days <= 0
        ? `已超期 ${Math.abs(row.service_remaining_days)} 天`
        : `剩余 ${row.service_remaining_days} 天`,
    next_payment_date: row.next_payment_date?.slice(0, 10) || '',
    outstanding_amount: row.outstanding_amount > 0 ? fmt(row.outstanding_amount) : '-',
    sales_person: row.sales_person || '',
  }));

  const openCustomerDetail = (customerId: number) => {
    navigate(`/customers?detail=${customerId}`);
  };

  const PaginationFooter = () => {
    if (paginated.total === 0) return null;
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {paginated.start}-{paginated.end} 条 / 共 {paginated.total} 条
          {filtered.length !== rows.length ? `（筛选自 ${rows.length} 条）` : ''}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">每页</span>
          <NativeSelect
            value={String(pageSize)}
            onChange={value => setPageSize(Number(value))}
            options={PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="h-8 w-24 text-xs"
          />
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(1)} disabled={paginated.page <= 1}>首页</Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.page - 1)} disabled={paginated.page <= 1}>上一页</Button>
          <span className="min-w-20 text-center text-xs text-slate-500">{paginated.page} / {paginated.totalPages} 页</span>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.page + 1)} disabled={paginated.page >= paginated.totalPages}>下一页</Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.totalPages)} disabled={paginated.page >= paginated.totalPages}>末页</Button>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">成交客户管理</h2>
          <p className="text-sm text-slate-500 mt-1">这里只展示已经成交的客户，用于查看服务状态、到期时间和收款情况。</p>
        </div>
        <ExportButton
          data={exportData}
          columns={[
            { key: 'customer_code', label: '编号' },
            { key: 'business_name', label: '商家名称' },
            { key: 'contact_name', label: '联系人' },
            { key: 'phone', label: '电话' },
            { key: 'state', label: '州/省' },
            { key: 'country', label: '国家' },
            { key: 'selected_package_name', label: '成交套餐' },
            { key: 'selected_package_source', label: '成交套餐来源' },
            { key: 'latest_package_name', label: '当前服务套餐' },
            { key: 'latest_package_source', label: '当前服务套餐来源' },
            { key: 'latest_deal_amount', label: '成交金额' },
            { key: 'latest_deal_date', label: '最近成交时间' },
            { key: 'latest_payment_date', label: '最近收款时间' },
            { key: 'latest_payment_amount', label: '最近收款金额' },
            { key: 'service_status', label: '服务状态' },
            { key: 'billing_cycle', label: '服务周期' },
            { key: 'service_end_date', label: '到期时间' },
            { key: 'service_remaining_text', label: '剩余/超期' },
            { key: 'next_payment_date', label: '下次付款时间' },
            { key: 'outstanding_amount', label: '未收尾款' },
            { key: 'sales_person', label: '负责销售' },
          ]}
          filename={`成交客户_${new Date().toISOString().slice(0, 10)}`}
          sheetName="成交客户"
        />
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">成交客户</p><p className="text-2xl font-semibold text-slate-800 mt-1">{totalClosedCustomers}</p></CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">服务中客户</p><p className="text-2xl font-semibold text-green-600 mt-1">{activeCustomers}</p></CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">续费关注</p><p className="text-2xl font-semibold text-amber-600 mt-1">{renewalCustomers}</p></CardContent></Card>
        <Card className="border-slate-200"><CardContent className="p-4"><p className="text-sm text-slate-500">待收尾款客户</p><p className="text-2xl font-semibold text-red-600 mt-1">{outstandingCustomers}</p></CardContent></Card>
      </div>

      <Card className="border-slate-200">
        <CardContent className="p-3">
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-[300px_minmax(0,1fr)_170px_170px_170px] gap-3">
            <Combobox
              value={filterCustomerId}
              onValueChange={setFilterCustomerId}
              options={[{ value: 'all', label: '全部成交客户' }, ...customerOptions]}
              placeholder="选择成交客户"
              searchPlaceholder="输入商家名、编号、联系人或电话"
              emptyText="没有找到成交客户"
            />
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input
                placeholder="搜索商家、联系人、电话、套餐、负责人..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <NativeSelect
              value={filterServiceStatus}
              onChange={setFilterServiceStatus}
              options={[
                { value: 'all', label: '全部服务状态' },
                { value: 'active', label: subStatusLabels.active || '正常' },
                { value: 'expiring_soon', label: subStatusLabels.expiring_soon || '即将到期' },
                { value: 'renewal_pending', label: subStatusLabels.renewal_pending || serviceStatusLabels.renewal_pending },
                { value: 'expired', label: subStatusLabels.expired || '已到期' },
                { value: 'paused', label: subStatusLabels.paused || '暂停' },
                { value: 'lost', label: subStatusLabels.lost || '流失' },
                { value: 'none', label: '未建服务' },
              ]}
            />
            <NativeSelect
              value={filterSalesPerson}
              onChange={setFilterSalesPerson}
              options={[{ value: 'all', label: '全部负责人' }, ...salesPersonOptions]}
            />
            <NativeSelect
              value={filterCountry}
              onChange={setFilterCountry}
              options={[{ value: 'all', label: '全部国家' }, ...countryOptions]}
            />
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-400 py-12">暂无符合条件的成交客户</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-slate-50 text-left text-slate-500">
                    <th className="px-4 py-3 font-medium">商家名称</th>
                    <th className="px-4 py-3 font-medium">联系人</th>
                    <th className="px-4 py-3 font-medium">州/国家</th>
                    <th className="px-4 py-3 font-medium">成交套餐</th>
                    <th className="px-4 py-3 font-medium">当前服务</th>
                    <th className="px-4 py-3 font-medium">最近成交</th>
                    <th className="px-4 py-3 font-medium">服务状态</th>
                    {canViewFinance && <th className="px-4 py-3 font-medium">最近收款</th>}
                    {canViewFinance && <th className="px-4 py-3 font-medium">尾款</th>}
                    <th className="px-4 py-3 font-medium">负责销售</th>
                    <th className="px-4 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {paginated.items.map(row => (
                    <tr key={row.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <button
                          className="text-left text-blue-600 hover:text-blue-800 hover:underline"
                          onClick={() => openCustomerDetail(row.id)}
                        >
                          <div className="font-medium">{row.business_name}</div>
                          <div className="text-xs text-slate-400 mt-1">{row.customer_code || `客户#${row.id}`}</div>
                        </button>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div>{row.contact_name || '-'}</div>
                        <div className="text-xs text-slate-400 mt-1">{row.phone || '-'}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div>{row.state || '-'}</div>
                        <div className="text-xs text-slate-400 mt-1">{row.country_label}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div className="font-medium text-slate-700">{row.selected_package_name}</div>
                        <div className="text-xs text-slate-400 mt-1">{row.selected_package_source || '-'}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div>{row.latest_package_name}</div>
                        <div className="text-xs text-slate-400 mt-1">
                          {cycleLabels[row.billing_cycle] || row.billing_cycle || '-'}
                          {row.latest_package_source ? ` · ${row.latest_package_source}` : ''}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div className="font-medium text-slate-700">{row.latest_deal_amount ? fmt(row.latest_deal_amount) : '-'}</div>
                        <div className="text-xs text-slate-400 mt-1">{row.latest_deal_date?.slice(0, 10) || '-'}</div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge className={subStatusColors[row.service_status] || subStatusColors.none}>
                          {subStatusLabels[row.service_status] || serviceStatusLabels[row.service_status] || row.service_status}
                        </Badge>
                        {row.auto_renew && (
                          <Badge className="ml-1 bg-cyan-50 text-cyan-700 border border-cyan-100">
                            Stripe订阅
                          </Badge>
                        )}
                        <div className="text-xs text-slate-400 mt-1">
                          到期: {row.service_end_date?.slice(0, 10) || '-'}
                        </div>
                        <div
                          className={`text-xs mt-1 ${
                            row.service_remaining_days == null
                              ? 'text-slate-400'
                              : row.service_remaining_days <= 0
                                ? 'text-red-600 font-medium'
                                : row.service_remaining_days <= 7
                                  ? 'text-amber-600 font-medium'
                                  : 'text-slate-500'
                          }`}
                        >
                          {row.service_remaining_days == null
                            ? '剩余: -'
                            : row.service_remaining_days <= 0
                              ? `已超期 ${Math.abs(row.service_remaining_days)} 天`
                              : `剩余 ${row.service_remaining_days} 天`}
                        </div>
                        <div className="text-xs text-slate-400 mt-1">
                          下次付款: {row.next_payment_date?.slice(0, 10) || '-'}
                        </div>
                      </td>
                      {canViewFinance && (
                        <td className="px-4 py-3 text-slate-600">
                          <div className="font-medium text-slate-700">{row.latest_payment_amount ? fmt(row.latest_payment_amount) : '-'}</div>
                          <div className="text-xs text-slate-400 mt-1">{row.latest_payment_date?.slice(0, 10) || '-'}</div>
                        </td>
                      )}
                      {canViewFinance && (
                        <td className="px-4 py-3">
                          {row.outstanding_amount > 0 ? (
                            <span className="font-medium text-red-600">{fmt(row.outstanding_amount)}</span>
                          ) : (
                            <span className="text-slate-400">-</span>
                          )}
                        </td>
                      )}
                      <td className="px-4 py-3 text-slate-600">{row.sales_person || '-'}</td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="ghost" size="sm" className="text-blue-600 hover:text-blue-700" onClick={() => openCustomerDetail(row.id)}>
                          <ExternalLink className="w-3.5 h-3.5 mr-1" /> 查看详情
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {filtered.length > 0 && <PaginationFooter />}
        </CardContent>
      </Card>
    </div>
  );
}
