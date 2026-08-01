import { useMemo } from 'react';

import { Combobox } from '@/components/ui/combobox';

type CustomerLike = {
  id: number | string;
  customer_code?: string | null;
  business_name?: string | null;
  contact_name?: string | null;
  phone?: string | null;
  city?: string | null;
};

type CustomerComboboxProps = {
  customers: CustomerLike[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
  clearLabel?: string;
};

const customerLabel = (customer: CustomerLike) => {
  const code = String(customer.customer_code || '').trim() || `#${customer.id}`;
  const business = String(customer.business_name || '').trim() || `客户 #${customer.id}`;
  const details = [customer.contact_name, customer.phone, customer.city]
    .map(value => String(value || '').trim())
    .filter(Boolean)
    .join(' · ');
  return `${code} · ${business}${details ? ` · ${details}` : ''}`;
};

export default function CustomerCombobox({
  customers,
  value,
  onValueChange,
  placeholder = '搜索客户编号、名称、联系人或电话',
  disabled = false,
  allowClear = false,
  clearLabel = '不关联客户',
}: CustomerComboboxProps) {
  const options = useMemo(() => {
    const items = customers.map(customer => ({
      value: String(customer.id),
      label: customerLabel(customer),
    }));
    return allowClear ? [{ value: '', label: clearLabel }, ...items] : items;
  }, [allowClear, clearLabel, customers]);

  return (
    <Combobox
      options={options}
      value={value}
      onValueChange={onValueChange}
      placeholder={placeholder}
      searchPlaceholder="输入客户编号、名称、联系人、电话或城市…"
      emptyText="没有找到匹配客户"
      disabled={disabled}
      className="h-10 justify-between overflow-hidden text-left font-normal [&>span]:truncate"
    />
  );
}
