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
import ExportButton from '@/components/ExportButton';
import { useBusinessDicts } from '../lib/dict-config';

const subStatusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  expiring_soon: 'bg-amber-100 text-amber-700',
  expired: 'bg-red-100 text-red-700',
  paused: 'bg-slate-100 text-slate-600',
  lost: 'bg-red-100 text-red-700',
  none: 'bg-slate-100 text-slate-500',
};

const serviceStatusLabels: Record<string, string> = {
  none: '未建服务',
};

const fmt = (value: number) => `$${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

function computeSubscriptionStatus(subscription: any): string {
  if (!subscription) return 'none';
  if (!subscription.end_date) return subscription.status || 'active';
  if (subscription.status === 'paused' || subscription.status === 'lost') return subscription.status;

  const endDate = new Date(subscription.end_date);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.ceil((endDate.getTime() - today.getTime()) / 86400000);

  if (diffDays <= 0) return 'expired';
  if (diffDays <= 7) return 'expiring_soon';
  return 'active';
}

export default function Sales() {
  const { employee, dataScope } = useRole();
  const { billingCycles: cycleLabels, subscriptionStatuses: subStatusLabels } = useBusinessDicts();
  const navigate = useNavigate();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterServiceStatus, setFilterServiceStatus] = useState('all');
  const [filterSalesPerson, setFilterSalesPerson] = useState('all');
  const [filterCountry, setFilterCountry] = useState('all');

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [customerRes, dealRes, subRes, paymentRes] = await Promise.all([
        client.entities.customers.query({ limit: 500, sort: '-updated_at' }),
        client.entities.deals.query({ limit: 500, sort: '-deal_date' }),
        client.entities.subscriptions.query({ limit: 500, sort: '-end_date' }),
        client.entities.payments.queryAll({ limit: 500, sort: '-payment_date' }),
      ]);

      let customerItems = customerRes?.data?.items || [];
      const dealItems = dealRes?.data?.items || [];
      const subscriptionItems = subRes?.data?.items || [];
      const paymentItems = paymentRes?.data?.items || [];

      if (dataScope === 'self' && employee) {
        customerItems = customerItems.filter(
          (customer: any) => customer.sales_person === employee.name || customer.sales_employee_id === employee.id,
        );
      }

      const latestDealByCustomer: Record<number, any> = {};
      dealItems.forEach((deal: any) => {
        if (deal.customer_id && !latestDealByCustomer[deal.customer_id]) {
          latestDealByCustomer[deal.customer_id] = deal;
        }
      });

      const latestSubscriptionByCustomer: Record<number, any> = {};
      subscriptionItems.forEach((subscription: any) => {
        if (subscription.customer_id && !latestSubscriptionByCustomer[subscription.customer_id]) {
          latestSubscriptionByCustomer[subscription.customer_id] = subscription;
        }
      });

      const latestPaymentByCustomer: Record<number, any> = {};
      const outstandingByCustomer: Record<number, number> = {};
      paymentItems.forEach((payment: any) => {
        if (!payment.customer_id) return;
        if (!latestPaymentByCustomer[payment.customer_id]) {
          latestPaymentByCustomer[payment.customer_id] = payment;
        }
        outstandingByCustomer[payment.customer_id] = (outstandingByCustomer[payment.customer_id] || 0) + Number(payment.outstanding_amount || 0);
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
          const serviceStatus = computeSubscriptionStatus(latestSubscription);

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
            latest_package_name: latestSubscription?.package_name || latestDeal?.package_name || '-',
            latest_deal_amount: Number(latestDeal?.deal_amount || latestPayment?.amount_due || 0),
            latest_deal_date: latestDeal?.deal_date || latestPayment?.payment_date || customer.updated_at || customer.created_at,
            latest_payment_date: latestPayment?.payment_date || '',
            latest_payment_amount: Number(latestPayment?.amount_paid || 0),
            service_status: serviceStatus,
            service_end_date: latestSubscription?.end_date || '',
            next_payment_date: latestSubscription?.next_payment_date || '',
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

  const filtered = rows.filter(row => {
    const searchValue = search.trim().toLowerCase();
    const matchesSearch = !searchValue || [
      row.customer_code,
      row.business_name,
      row.contact_name,
      row.phone,
      row.sales_person,
      row.latest_package_name,
      row.country_label,
      row.state,
      row.state_label,
    ].some(field => String(field || '').toLowerCase().includes(searchValue));

    const matchesServiceStatus = filterServiceStatus === 'all' || row.service_status === filterServiceStatus;
    const matchesSalesPerson = filterSalesPerson === 'all' || row.sales_person === filterSalesPerson;
    const matchesCountry = filterCountry === 'all' || row.country === filterCountry;

    return matchesSearch && matchesServiceStatus && matchesSalesPerson && matchesCountry;
  });

  const totalClosedCustomers = rows.length;
  const activeCustomers = rows.filter(row => row.service_status === 'active').length;
  const renewalCustomers = rows.filter(row => row.service_status === 'expiring_soon' || row.service_status === 'expired').length;
  const outstandingCustomers = rows.filter(row => row.outstanding_amount > 0).length;

  const exportData = filtered.map(row => ({
    customer_code: row.customer_code,
    business_name: row.business_name,
    contact_name: row.contact_name,
    phone: row.phone,
    state: row.state || '',
    country: row.country_label,
    latest_package_name: row.latest_package_name,
    latest_deal_amount: row.latest_deal_amount ? fmt(row.latest_deal_amount) : '-',
    latest_deal_date: row.latest_deal_date?.slice(0, 10) || '',
    latest_payment_date: row.latest_payment_date?.slice(0, 10) || '',
    latest_payment_amount: row.latest_payment_amount ? fmt(row.latest_payment_amount) : '-',
    service_status: subStatusLabels[row.service_status] || serviceStatusLabels[row.service_status] || row.service_status,
    billing_cycle: cycleLabels[row.billing_cycle] || row.billing_cycle || '',
    service_end_date: row.service_end_date?.slice(0, 10) || '',
    next_payment_date: row.next_payment_date?.slice(0, 10) || '',
    outstanding_amount: row.outstanding_amount > 0 ? fmt(row.outstanding_amount) : '-',
    sales_person: row.sales_person || '',
  }));

  const openCustomerDetail = (customerId: number) => {
    navigate(`/customers?detail=${customerId}`);
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
            { key: 'latest_package_name', label: '当前套餐' },
            { key: 'latest_deal_amount', label: '成交金额' },
            { key: 'latest_deal_date', label: '最近成交时间' },
            { key: 'latest_payment_date', label: '最近收款时间' },
            { key: 'latest_payment_amount', label: '最近收款金额' },
            { key: 'service_status', label: '服务状态' },
            { key: 'billing_cycle', label: '服务周期' },
            { key: 'service_end_date', label: '到期时间' },
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
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_180px_180px_180px] gap-3">
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
                    <th className="px-4 py-3 font-medium">当前套餐</th>
                    <th className="px-4 py-3 font-medium">最近成交</th>
                    <th className="px-4 py-3 font-medium">服务状态</th>
                    <th className="px-4 py-3 font-medium">最近收款</th>
                    <th className="px-4 py-3 font-medium">尾款</th>
                    <th className="px-4 py-3 font-medium">负责销售</th>
                    <th className="px-4 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(row => (
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
                        <div>{row.latest_package_name}</div>
                        <div className="text-xs text-slate-400 mt-1">{cycleLabels[row.billing_cycle] || row.billing_cycle || '-'}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div className="font-medium text-slate-700">{row.latest_deal_amount ? fmt(row.latest_deal_amount) : '-'}</div>
                        <div className="text-xs text-slate-400 mt-1">{row.latest_deal_date?.slice(0, 10) || '-'}</div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge className={subStatusColors[row.service_status] || subStatusColors.none}>
                          {subStatusLabels[row.service_status] || serviceStatusLabels[row.service_status] || row.service_status}
                        </Badge>
                        <div className="text-xs text-slate-400 mt-1">
                          到期: {row.service_end_date?.slice(0, 10) || '-'}
                        </div>
                        <div className="text-xs text-slate-400 mt-1">
                          下次付款: {row.next_payment_date?.slice(0, 10) || '-'}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div className="font-medium text-slate-700">{row.latest_payment_amount ? fmt(row.latest_payment_amount) : '-'}</div>
                        <div className="text-xs text-slate-400 mt-1">{row.latest_payment_date?.slice(0, 10) || '-'}</div>
                      </td>
                      <td className="px-4 py-3">
                        {row.outstanding_amount > 0 ? (
                          <span className="font-medium text-red-600">{fmt(row.outstanding_amount)}</span>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
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
        </CardContent>
      </Card>
    </div>
  );
}
