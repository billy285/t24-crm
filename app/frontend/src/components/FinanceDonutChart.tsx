import { useState } from 'react';
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts';
import { X } from 'lucide-react';
import './finance-donut-chart.css';

type DonutItem = {
  id: string;
  name: string;
  value: number;
  color: string;
  count?: number;
};

type Props = {
  label: string;
  data: DonutItem[];
  formatValue: (value: number) => string;
};

/** Presentation only: use the existing report amounts, currencies and filters. */
export default function FinanceDonutChart({ label, data, formatValue }: Props) {
  const [selection, setSelection] = useState<{ id: string; snapshot: string } | null>(null);
  // A changed period/result must not leave the previous slice selected.
  const snapshot = JSON.stringify(data.map(({ id, name, value, count }) => [id, name, value, count]));
  const selected = selection?.snapshot === snapshot ? data.find(item => item.id === selection.id) : undefined;
  const total = data.reduce((sum, item) => sum + item.value, 0);
  const canDraw = Number.isFinite(total) && total > 0;
  const percentage = selected && canDraw ? (selected.value / total * 100).toFixed(1) : '0.0';
  const select = (id: string) => setSelection(id ? { id, snapshot } : null);

  return (
    <div className="finance-donut" role="group" aria-label={label}>
      <div className="finance-donut-visual" aria-hidden="true">
        {canDraw ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%"
                innerRadius="58%" outerRadius="82%" paddingAngle={1}
                label={false} labelLine={false} isAnimationActive={false} rootTabIndex={-1}
                onClick={(_, index) => { const item = data[index]; if (item) select(item.id); }}>
                {data.map(item => (
                  <Cell key={item.id} fill={item.color} stroke="#fff" strokeWidth={2}
                    opacity={!selected || selected.id === item.id ? 1 : 0.3}
                    className="finance-donut-slice" />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        ) : <div className="finance-donut-empty-ring" />}
        <div className="finance-donut-center">
          {selected ? <><strong>{percentage}%</strong><span>所选分类占比</span></> : <span>{canDraw ? '点击查看占比' : '暂无可展示金额'}</span>}
        </div>
      </div>

      <div className="finance-donut-controls">
        <select aria-label={`选择${label}分类`} value={selected?.id || ''}
          onChange={event => select(event.target.value)}>
          <option value="">选择分类 · {data.length} 项</option>
          {data.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        {selected && <button type="button" aria-label={`清除${label}选择`} onClick={() => setSelection(null)}><X size={16} /></button>}
      </div>
      <div className="finance-donut-detail" role="status" aria-live="polite" aria-atomic="true">
        {selected && <>
          <span className="finance-donut-detail-name"><i style={{ background: selected.color }} />{selected.name}</span>
          <span className="finance-donut-detail-value">{formatValue(selected.value)}{selected.count !== undefined && <small>{selected.count} 笔</small>}</span>
          <span className="sr-only">占比 {percentage}%</span>
        </>}
      </div>
    </div>
  );
}
