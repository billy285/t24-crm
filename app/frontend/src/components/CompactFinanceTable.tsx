import { Children, Fragment, isValidElement, useId, useState, useSyncExternalStore, type CSSProperties, type ReactElement, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import './compact-finance-table.css';

export interface CompactFinanceColumn {
  label: string;
  /** Zero-based positions in the original table. Values are never recalculated. */
  indexes: readonly number[];
  /** Relative width, normalized across all summary columns. */
  width?: number;
  align?: 'left' | 'right';
}

export interface CompactFinanceDetailGroup {
  label: string;
  indexes: readonly number[];
}

interface CompactFinanceTableProps {
  children: ReactNode;
  columns: readonly CompactFinanceColumn[];
  /** A source-column contract: an inserted, renamed, or reordered field uses the intact legacy table. */
  expectedHeaders?: readonly string[];
  className?: string;
  /** The original table's className, used only below the desktop breakpoint. */
  legacyClassName?: string;
  label?: string;
  detailGroups?: readonly CompactFinanceDetailGroup[];
  /** These complete, untruncated fields stay in the summary; their buttons appear once. */
  actionIndexes?: readonly number[];
}

interface TableElementProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  colSpan?: number;
  rowSpan?: number;
}

export interface CompactFinanceCell {
  node: ReactNode;
  className: string;
  style?: CSSProperties;
  colSpan: number;
}

export interface CompactFinanceRow {
  key: string;
  keyed: boolean;
  cells: CompactFinanceCell[];
  fullWidth: boolean;
}

/** Flatten fragments without evaluating user components or changing their props. */
function elements(children: ReactNode): ReactElement<TableElementProps>[] {
  const result: ReactElement<TableElementProps>[] = [];
  Children.forEach(children, child => {
    if (!isValidElement<TableElementProps>(child)) return;
    if (child.type === Fragment) result.push(...elements(child.props.children));
    else result.push(child);
  });
  return result;
}

function textContent(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  let text = '';
  Children.forEach(node, child => {
    if (typeof child === 'string' || typeof child === 'number') text += String(child);
    else if (isValidElement<TableElementProps>(child)) text += textContent(child.props.children);
  });
  return text;
}

// Preserve datum colours and weights while removing the old table's geometry.
function datumClasses(className = ''): string {
  return className.split(/\s+/).filter(value => (
    /^(?:[a-z]+:)*(?:text-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}|font-(?:normal|medium|semibold|bold)|tabular-nums)$/.test(value)
  )).join(' ');
}

function datumStyle(style?: CSSProperties): CSSProperties | undefined {
  if (!style) return undefined;
  return { color: style.color, fontWeight: style.fontWeight, fontVariantNumeric: style.fontVariantNumeric };
}

export function extractCompactFinanceTable(children: ReactNode) {
  const sections = elements(children);
  const headers: string[] = [];
  const header = sections.find(section => section.type === 'thead');
  const headerRows = header ? elements(header.props.children) : [];
  const headerCells = headerRows.length === 1 ? elements(headerRows[0].props.children) : [];
  let supported = Boolean(headerCells.length);
  for (const cell of headerCells) {
    if ((cell.type !== 'th' && cell.type !== 'td') || Number(cell.props.colSpan || 1) !== 1 || Number(cell.props.rowSpan || 1) !== 1) supported = false;
    headers.push(textContent(cell.props.children).trim() || `字段 ${headers.length + 1}`);
  }
  const collectRows = (sectionType: 'tbody' | 'tfoot'): CompactFinanceRow[] => sections
    .filter(section => section.type === sectionType)
    .flatMap(section => elements(section.props.children))
    .filter(row => {
      if (row.type !== 'tr') supported = false;
      return row.type === 'tr';
    })
    .map((row, index) => {
      const originalCells = elements(row.props.children);
      if (originalCells.some(cell => !['td', 'th'].includes(String(cell.type)) || Number(cell.props.rowSpan || 1) !== 1)) supported = false;
      const cells = originalCells.filter(cell => cell.type === 'td' || cell.type === 'th').map(cell => ({
        node: cell.props.children,
        className: datumClasses(cell.props.className),
        style: datumStyle(cell.props.style),
        colSpan: Number(cell.props.colSpan || 1),
      }));
      const fullWidth = cells.some(cell => cell.colSpan !== 1) || cells.length !== headers.length;
      return { key: row.key === null ? `unkeyed-${sectionType}-${index}` : String(row.key), keyed: row.key !== null, cells, fullWidth };
    });
  const rows = collectRows('tbody');
  const footerRows = collectRows('tfoot');
  if (sections.some(section => !['thead', 'tbody', 'tfoot', 'caption', 'colgroup'].includes(String(section.type)))) supported = false;
  return { headers, rows, footerRows, supported };
}

const desktopQuery = '(min-width: 1024px)';
function subscribeDesktop(onChange: () => void) {
  const query = window.matchMedia(desktopQuery);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}
const desktopSnapshot = () => typeof window !== 'undefined' && window.matchMedia(desktopQuery).matches;
const serverSnapshot = () => false;

function Value({ cell }: { cell?: CompactFinanceCell }) {
  return <div className={`cft-value ${cell?.className || ''}`} style={cell?.style}>{cell?.node ?? '—'}</div>;
}

function detailSections(headers: string[], groups: readonly CompactFinanceDetailGroup[] | undefined, actions: Set<number>) {
  const used = new Set<number>();
  const sections = (groups || []).map(group => ({
    label: group.label,
    indexes: group.indexes.filter(index => {
      if (index < 0 || index >= headers.length || actions.has(index) || used.has(index)) return false;
      used.add(index);
      return true;
    }),
  })).filter(group => group.indexes.length);
  const remaining = headers.map((_, index) => index).filter(index => !used.has(index) && !actions.has(index));
  if (remaining.length) sections.push({ label: sections.length ? '其他明细' : '完整明细', indexes: remaining });
  return sections;
}

function ExpandedFields({ headers, row, groups, actions }: { headers: string[]; row: CompactFinanceRow; groups?: readonly CompactFinanceDetailGroup[]; actions: Set<number> }) {
  return <div className="cft-detail-groups">
    {detailSections(headers, groups, actions).map((group, groupIndex) => <section className="cft-detail-group" key={`${group.label}-${groupIndex}`}>
      <h4>{group.label}</h4>
      <dl>{group.indexes.map(index => <div className="cft-field" key={index}>
        <dt>{headers[index]}</dt><dd><Value cell={row.cells[index]} /></dd>
      </div>)}</dl>
    </section>)}
  </div>;
}

function CompactRow({ row, headers, columns, detailGroups, actions, tableId }: {
  row: CompactFinanceRow; headers: string[]; columns: readonly CompactFinanceColumn[];
  detailGroups?: readonly CompactFinanceDetailGroup[]; actions: Set<number>; tableId: string;
}) {
  const [open, setOpen] = useState(false);
  const localId = useId();
  const detailId = `${tableId}-${localId}-details`;
  const recordLabel = textContent(row.cells[0]?.node).trim() || '此记录';
  if (row.fullWidth) return <tr className="cft-message-row"><td colSpan={columns.length + 1}>
    {row.cells.map((cell, index) => <Value cell={cell} key={index} />)}
  </td></tr>;
  return <>
    <tr className={`cft-summary-row${open ? ' is-open' : ''}`}>
      {columns.map((column, columnIndex) => <td key={columnIndex} data-label={column.label} className={column.align === 'right' ? 'cft-number' : undefined}>
        <div className="cft-summary-values">{column.indexes.map((index, position) => <div key={index} className={position ? 'cft-summary-secondary' : 'cft-summary-primary'}>
          {column.indexes.length > 1 && <span className="cft-inline-label">{headers[index]}</span>}
          <Value cell={row.cells[index]} />
        </div>)}</div>
      </td>)}
      <td className="cft-expand-cell" data-label="明细"><button type="button" className="cft-expand" aria-label={`${open ? '收起' : '展开'}${recordLabel}明细`} aria-expanded={open} aria-controls={detailId} onClick={() => setOpen(value => !value)}>
        {open ? '收起明细' : '展开明细'}<ChevronDown aria-hidden="true" />
      </button></td>
    </tr>
    {open && <tr className="cft-expanded-row"><td colSpan={columns.length + 1}>
      <div id={detailId} className="cft-detail-panel" role="region" aria-label={`${recordLabel}完整财务明细`}>
        <ExpandedFields headers={headers} row={row} groups={detailGroups} actions={actions} />
      </div>
    </td></tr>}
  </>;
}

/** A presentation adapter over the existing table. No monetary or business logic belongs here. */
export default function CompactFinanceTable({ children, columns, expectedHeaders, className = '', legacyClassName = 'w-full text-sm', label = '财务记录', detailGroups, actionIndexes }: CompactFinanceTableProps) {
  const isDesktop = useSyncExternalStore(subscribeDesktop, desktopSnapshot, serverSnapshot);
  const tableId = useId();
  const table = extractCompactFinanceTable(children);
  const actions = new Set(actionIndexes || table.headers.flatMap((header, index) => header === '操作' ? [index] : []));
  const configuredIndexes = new Set(columns.flatMap(column => [...column.indexes]));
  // Every original action remains reachable even if a caller omits its summary column.
  const missingActions = [...actions].filter(index => !configuredIndexes.has(index));
  const visibleColumns = missingActions.length ? [...columns, { label: '操作', indexes: missingActions, width: 14 } as CompactFinanceColumn] : columns;
  const validColumns = visibleColumns.length > 0 && visibleColumns.every(column => column.indexes.length && column.indexes.every(index => Number.isInteger(index) && index >= 0 && index < table.headers.length));
  const headersMatch = !expectedHeaders || (expectedHeaders.length === table.headers.length && expectedHeaders.every((header, index) => header === table.headers[index]));
  const caption = elements(children).find(section => section.type === 'caption');
  if (!isDesktop || !table.supported || !validColumns || !headersMatch) return <table className={legacyClassName}>{children}</table>;
  const totalWidth = visibleColumns.reduce((total, column) => total + Math.max(column.width || 16, 1), 0) + 12;
  return <div className={`compact-finance-table ${className}`}>
    <table className="cft-table" aria-label={label}>
      {caption}
      <colgroup>{visibleColumns.map((column, index) => <col key={index} style={{ width: `${Math.max(column.width || 16, 1) / totalWidth * 100}%` }} />)}
        <col style={{ width: `${12 / totalWidth * 100}%` }} />
      </colgroup>
      <thead><tr>{visibleColumns.map((column, index) => <th key={index} scope="col" className={column.align === 'right' ? 'cft-number' : undefined}>{column.label}</th>)}<th scope="col" className="cft-expand-heading">明细</th></tr></thead>
      <tbody>{table.rows.map(row => <CompactRow key={row.keyed ? row.key : `${row.key}-${row.cells.map(cell => textContent(cell.node)).join('|')}`} row={row} headers={table.headers} columns={visibleColumns} detailGroups={detailGroups} actions={actions} tableId={tableId} />)}</tbody>
      {table.footerRows.length > 0 && <tfoot>{table.footerRows.map(row => <tr key={row.key} className="cft-footer-row"><td colSpan={visibleColumns.length + 1}>
        {row.fullWidth ? row.cells.map((cell, index) => <Value cell={cell} key={index} />) : <ExpandedFields headers={table.headers} row={row} groups={detailGroups} actions={new Set()} />}
      </td></tr>)}</tfoot>}
    </table>
  </div>;
}
