import { useState } from 'react';
import { NativeSelect } from '@/components/ui/native-select';
import { callEvidenceState, reportEvidenceState, type CallEvidence } from '@/lib/sales-call-evidence';

export type SalesIndustryBreakdown = {
  industries: {
    industry: string;
    recorded_merchants: number;
    crm_records: number;
    interested_merchants: number;
    provider_calls: number;
    connected: number;
  }[];
  unmatched_provider_calls: number;
  unmatched_connected: number;
  undated_provider_calls: number;
};

type Employee = CallEvidence & {
  sales_employee_id: number;
  salesperson: string;
  industry_breakdown?: SalesIndustryBreakdown;
};

export type SalesIndustryCallReport = {
  summary: { provider_calls: number };
  employees: Employee[];
  industry_breakdown?: SalesIndustryBreakdown;
};

export default function SalesIndustryReport({ report, scopeLabel }: { report: SalesIndustryCallReport; scopeLabel: string }) {
  const [employeeId, setEmployeeId] = useState('');
  const employee = report.employees.find(item => String(item.sales_employee_id) === employeeId);
  const breakdown = employee ? employee.industry_breakdown : report.industry_breakdown;
  if (!breakdown) return null;
  const evidence = employee ? callEvidenceState(employee) : reportEvidenceState(report);
  return (
    <section aria-label="按商家行业统计" className="rounded-xl border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold">按商家行业统计</h4>
        {report.employees.length > 1 && (
          <NativeSelect aria-label="行业统计销售" className="max-w-48" value={employee ? employeeId : ''}
            onChange={setEmployeeId} options={[
              { value: '', label: scopeLabel },
              ...report.employees.map(item => ({ value: String(item.sales_employee_id), label: item.salesperson })),
            ]} />
        )}
      </div>
      <table className="mt-3 w-full table-fixed text-sm tabular-nums">
        <caption className="sr-only">所选期间各行业的 CRM 记录和已同步官方通话</caption>
        <thead className="text-xs text-muted-foreground"><tr>
          <th scope="col" className="w-[25%] py-2 text-left">行业</th>
          <th scope="col" className="text-right">记录商家</th>
          <th scope="col" className="text-right">意向商家</th>
          <th scope="col" className="text-right">已同步拨出</th>
        </tr></thead>
        <tbody>{breakdown.industries.map(row => <tr key={row.industry} className="border-t align-top">
          <th scope="row" className="break-words py-2 text-left font-medium">{row.industry}</th>
          <td className="py-2 text-right">{row.recorded_merchants}<small className="block text-muted-foreground">{row.crm_records} 条记录</small></td>
          <td className="py-2 text-right">{row.interested_merchants}</td>
          <td className="py-2 text-right">{evidence.available ? row.provider_calls : evidence.label}
            {evidence.available && <small className="block text-muted-foreground">接通 {row.connected}</small>}
          </td>
        </tr>)}</tbody>
      </table>
      <p className="mt-2 text-xs text-muted-foreground">按商家当前行业归类。已记录和有意向（含预约）的商家在所选期间各计一次。</p>
      {breakdown.unmatched_provider_calls > 0 && <p className="mt-1 text-xs text-muted-foreground">另有 {breakdown.unmatched_provider_calls} 次已同步拨出尚未匹配商家，其中 {breakdown.unmatched_connected} 次接通。</p>}
      {breakdown.undated_provider_calls > 0 && <p className="mt-1 text-xs text-muted-foreground">另有 {breakdown.undated_provider_calls} 条官方记录缺少拨出时间，暂无法归入统计期间。</p>}
    </section>
  );
}
