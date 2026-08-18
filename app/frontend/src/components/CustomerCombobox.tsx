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

const customerLabel = (customer: CustomerLike) => (
  String(customer.business_name || '').trim() || `客户 #${customer.id}`
);

const customerSearchValue = (customer: CustomerLike) => (
  [customer.customer_code, customer.business_name, customer.contact_name, customer.phone, customer.city, customer.id]
    .map(value => String(value || '').trim())
    .filter(Boolean)
    .join(' · ')
);

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
      searchValue: customerSearchValue(customer),
    }));
    return allowClear ? [{ value: '', label: clearLabel }, ...items] : items;
  }, [allowClear, clearLabel, customers]);

  return (
    <Combobox
      options={options}
      value={value}
      onValueChange={onValueChange}
      placeholder={placeholder}
      searchPlaceholder="搜索商家名称或编号"
      emptyText="没有找到匹配客户"
      disabled={disabled}
      className="h-10 justify-between overflow-hidden text-left font-normal [&>span]:truncate"
    />
  );
}
