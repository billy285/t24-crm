import { useRef, useState } from 'react';
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts';
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
  type Selection = { id: string; snapshot: string; interaction: 'hover' | 'focus' | 'touch' };
  const [selection, setSelection] = useState<Selection | null>(null);
  const pointerType = useRef('mouse');
  // A changed period/result must not leave the previous slice selected.
  const snapshot = JSON.stringify(data.map(({ id, name, value, count }) => [id, name, value, count]));
  const selected = selection?.snapshot === snapshot ? data.find(item => item.id === selection.id) : undefined;
  const total = data.reduce((sum, item) => sum + item.value, 0);
  const canDraw = Number.isFinite(total) && total > 0;
  const percentage = selected && canDraw ? (selected.value / total * 100).toFixed(1) : '0.0';
  const show = (id: string, interaction: Selection['interaction']) => setSelection({ id, snapshot, interaction });
  const clear = (interaction: Selection['interaction']) => setSelection(current => current?.interaction === interaction ? null : current);
  const toggleTouch = (id: string) => setSelection(current => current?.id === id && current.snapshot === snapshot && current.interaction === 'touch' ? null : { id, snapshot, interaction: 'touch' });

  return (
    <div className="finance-donut" role="group" aria-label={label}
      onPointerOverCapture={event => { pointerType.current = event.pointerType; }}
      onPointerDownCapture={event => { pointerType.current = event.pointerType; }}
      onKeyDown={event => { if (event.key === 'Escape') setSelection(null); }}>
      <div className="finance-donut-visual" aria-hidden="true">
        {canDraw ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%"
                innerRadius="58%" outerRadius="82%" paddingAngle={1}
                label={false} labelLine={false} isAnimationActive={false} rootTabIndex={-1}
                onMouseEnter={(_, index) => { const item = data[index]; if (item && pointerType.current !== 'touch' && pointerType.current !== 'pen') show(item.id, 'hover'); }}
                onMouseLeave={() => clear('hover')}
                onClick={(_, index) => { const item = data[index]; if (item && (pointerType.current === 'touch' || pointerType.current === 'pen')) toggleTouch(item.id); }}>
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
          {selected ? <><strong>{percentage}%</strong><span>分类占比</span></> : canDraw ? <><span className="finance-donut-mouse-hint">移入查看占比</span><span className="finance-donut-touch-hint">点按查看占比</span></> : <span>暂无可展示金额</span>}
        </div>
      </div>

      <div className="finance-donut-legend" role="group" aria-label={`${label}分类`}>
        {data.map(item => <button key={item.id} type="button"
          className={selected?.id === item.id ? 'is-active' : ''}
          aria-label={`查看${item.name}占比`}
          onPointerEnter={event => { if (event.pointerType !== 'touch' && event.pointerType !== 'pen') show(item.id, 'hover'); }}
          onPointerLeave={() => clear('hover')}
          onFocus={event => { if (event.currentTarget.matches(':focus-visible')) show(item.id, 'focus'); }}
          onBlur={() => clear('focus')}
          onClick={event => { if (event.detail === 0) show(item.id, 'focus'); else if (pointerType.current === 'touch' || pointerType.current === 'pen') toggleTouch(item.id); else show(item.id, 'hover'); }}>
          <i style={{ background: item.color }} /><span>{item.name}</span>
        </button>)}
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
