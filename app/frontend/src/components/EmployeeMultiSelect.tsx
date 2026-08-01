import { useMemo, useState } from 'react';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

type EmployeeLike = {
  id?: number | string;
  name?: string | null;
  full_name?: string | null;
  username?: string | null;
  email?: string | null;
  employee_code?: string | null;
  department?: string | null;
  status?: string | null;
};

type EmployeeMultiSelectProps = {
  employees: EmployeeLike[];
  value: string[];
  onValueChange: (value: string[]) => void;
  placeholder?: string;
};

const employeeName = (employee: EmployeeLike) => String(
  employee.name || employee.full_name || employee.username || employee.email || '',
).trim();

export default function EmployeeMultiSelect({
  employees,
  value,
  onValueChange,
  placeholder = '选择协作员工',
}: EmployeeMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const activeEmployees = useMemo(() => employees
    .filter(employee => !employee.status || ['active', 'probation'].includes(employee.status))
    .map(employee => ({ ...employee, displayName: employeeName(employee) }))
    .filter(employee => employee.displayName), [employees]);

  const toggle = (name: string) => {
    onValueChange(value.includes(name) ? value.filter(item => item !== name) : [...value, name]);
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" role="combobox" aria-expanded={open} className="h-10 w-full justify-between font-normal">
            <span className="truncate text-slate-600">{value.length > 0 ? `已选择 ${value.length} 人` : placeholder}</span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[320px] p-0" align="start">
          <Command>
            <CommandInput placeholder="搜索姓名、员工编号或部门…" />
            <CommandList>
              <CommandEmpty>没有找到在职员工</CommandEmpty>
              <CommandGroup>
                {activeEmployees.map(employee => {
                  const label = [employee.displayName, employee.employee_code, employee.department].filter(Boolean).join(' · ');
                  const selected = value.includes(employee.displayName);
                  return (
                    <CommandItem key={String(employee.id || employee.displayName)} value={label} onSelect={() => toggle(employee.displayName)}>
                      <Check className={cn('mr-2 h-4 w-4', selected ? 'opacity-100' : 'opacity-0')} />
                      <span className="truncate">{label}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map(name => (
            <Badge key={name} variant="secondary" className="gap-1 pr-1">
              {name}
              <button type="button" onClick={() => toggle(name)} className="rounded p-0.5 hover:bg-slate-200" aria-label={`移除 ${name}`}>
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
