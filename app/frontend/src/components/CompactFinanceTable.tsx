import { Children, Fragment, cloneElement, isValidElement, useEffect, useId, useRef, useState, useSyncExternalStore, type CSSProperties, type MouseEvent, type ReactElement, type ReactNode } from 'react';
import { flushSync } from 'react-dom';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { ChevronRight, X } from 'lucide-react';
import { Sheet, SheetClose, SheetDescription, SheetOverlay, SheetPortal, SheetTitle } from '@/components/ui/sheet';
import './compact-finance-table.css';

export interface CompactFinanceColumn {
  label: string;
  /** Zero-based positions in the original table. Values are never recalculated. */
  indexes: readonly number[];
  /** Relative width, normalized across all summary columns. */
  width?: number;
  align?: 'left' | 'right';
  /** Select one existing text/paragraph/button branch; never format or recalculate its value. */
  summaryMode?: 'first' | 'last';
  /** Lower-priority columns move to the drawer as the desktop ledger narrows. */
  priority?: 1 | 2 | 3;
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
  /** Complete action fields appear once, in the drawer, including mixed status/action cells. */
  actionIndexes?: readonly number[];
}

interface TableElementProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  colSpan?: number;
  rowSpan?: number;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
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

/** Keep the selected original branch, including its props and click handler. */
export function selectCompactFinanceSummary(node: ReactNode, mode?: CompactFinanceColumn['summaryMode']): ReactNode {
  if (!mode) return node;
  const parts = Children.toArray(node).filter(child => typeof child !== 'string' || child.trim());
  // Adjacent strings/numbers belong to the same value (for example, a number and its unit).
  if (!parts.some(child => isValidElement(child))) return node;
  const selected = mode === 'last' ? parts[parts.length - 1] : parts[0];
  if (!isValidElement<TableElementProps>(selected) || selected.props.children === undefined) return selected;
  if (selected.type === 'p' || selected.type === 'button' || selected.type === 'a' || selected.props.onClick) return selected;
  return cloneElement(selected, {}, selectCompactFinanceSummary(selected.props.children, mode));
}

function Value({ cell, children }: { cell?: CompactFinanceCell; children?: ReactNode }) {
  return <div className={`cft-value ${cell?.className || ''}`} style={cell?.style}>{children !== undefined ? children : cell?.node ?? '—'}</div>;
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
  const actionFields = [...actions].filter(index => index >= 0 && index < headers.length);
  if (actionFields.length) sections.push({ label: '操作', indexes: actionFields });
  return sections;
}

/** End the modal before an original handler opens its own dialog or changes the record. */
function withActionHandoff(node: ReactNode, beforeAction: () => void): ReactNode {
  return Children.map(node, child => {
    if (!isValidElement<TableElementProps>(child)) return child;
    const props: Partial<TableElementProps> = {};
    if (child.props.children !== undefined) props.children = withActionHandoff(child.props.children, beforeAction);
    if (child.props.onClick || child.type === 'a') {
      props.onClick = event => {
        beforeAction();
        child.props.onClick?.(event);
      };
    }
    return cloneElement(child, props);
  });
}

/** Follow only the dialog opened by this action, then return to its persistent ledger trigger. */
function startActionFocusHandoff(trigger: HTMLButtonElement | null): () => void {
  const selector = '[role="dialog"], [role="alertdialog"]';
  const existingDialogs = new Set(document.querySelectorAll(selector));
  let actionDialog: HTMLElement | null = null;
  let focusTimer: ReturnType<typeof setTimeout> | undefined;
  let expiryTimer: ReturnType<typeof setTimeout>;
  let stopped = false;
  const restore = () => {
    const active = document.activeElement;
    if (trigger?.isConnected && (!active || active === document.body || !active.isConnected || actionDialog?.contains(active))) trigger.focus({ preventScroll: true });
  };
  const stop = () => {
    stopped = true;
    observer.disconnect();
    clearTimeout(focusTimer);
    clearTimeout(expiryTimer);
  };
  const focusField = () => {
    if (stopped || !actionDialog?.isConnected) return;
    const active = document.activeElement;
    // The original dialog may already have focused a field, or the user may have clicked one.
    if (active && active !== document.body && active !== document.documentElement && active !== trigger && active.isConnected) return;
    const available = (element: HTMLElement) => element.getClientRects().length > 0 && element.getAttribute('aria-disabled') !== 'true' && !element.closest('[inert], [aria-hidden="true"]');
    const fields = Array.from(actionDialog.querySelectorAll<HTMLElement>('input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])'));
    const controls = Array.from(actionDialog.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex="0"]'));
    (fields.find(available) || controls.find(available) || actionDialog).focus({ preventScroll: true });
  };
  const inspect = () => {
    if (stopped) return;
    if (!actionDialog) {
      actionDialog = Array.from(document.querySelectorAll<HTMLElement>(selector)).find(dialog => !existingDialogs.has(dialog) && !dialog.classList.contains('cft-drawer')) || null;
      if (actionDialog) {
        clearTimeout(expiryTimer);
        // A bounded listener is also cleared on a new record, route change or unmount.
        expiryTimer = setTimeout(stop, 5 * 60 * 1000);
        focusTimer = setTimeout(focusField, 0);
      }
    } else if (!actionDialog.isConnected) {
      const nextDialog = Array.from(document.querySelectorAll<HTMLElement>(selector)).find(dialog => !existingDialogs.has(dialog) && !dialog.classList.contains('cft-drawer'));
      if (nextDialog) {
        actionDialog = nextDialog;
        focusTimer = setTimeout(focusField, 0);
      } else {
        restore();
        stop();
      }
    }
  };
  const observer = new MutationObserver(inspect);
  observer.observe(document.body, { childList: true, subtree: true });
  expiryTimer = setTimeout(() => { if (!actionDialog) restore(); stop(); }, 1000);
  focusTimer = setTimeout(inspect, 0);
  return stop;
}

function ExpandedFields({ headers, row, groups, actions, beforeAction }: {
  headers: string[]; row: CompactFinanceRow; groups?: readonly CompactFinanceDetailGroup[];
  actions: Set<number>; beforeAction?: () => void;
}) {
  return <div className="cft-detail-groups">
    {detailSections(headers, groups, actions).map((group, groupIndex) => <section className="cft-detail-group" key={`${group.label}-${groupIndex}`}>
      <h4>{group.label}</h4>
      <dl>{group.indexes.map(index => <div className={`cft-field${actions.has(index) ? ' cft-action-field' : ''}`} key={index}>
        <dt>{headers[index]}</dt><dd><Value cell={row.cells[index]}>{beforeAction ? withActionHandoff(row.cells[index]?.node, beforeAction) : row.cells[index]?.node}</Value></dd>
      </div>)}</dl>
    </section>)}
  </div>;
}

interface LedgerSelection { tableId: string; rowKey: string }
// A page may contain several ledgers. Only one of their records owns the drawer.
let ledgerSelection: LedgerSelection | null = null;
const selectionListeners = new Set<() => void>();
function selectLedgerRecord(selection: LedgerSelection | null) {
  ledgerSelection = selection;
  selectionListeners.forEach(listener => listener());
}
function subscribeSelection(listener: () => void) {
  selectionListeners.add(listener);
  return () => { selectionListeners.delete(listener); };
}
const selectionSnapshot = () => ledgerSelection;
const serverSelectionSnapshot = () => null;
function rowKey(row: CompactFinanceRow) {
  return row.keyed ? row.key : `${row.key}-${row.cells.map(cell => textContent(cell.node)).join('|')}`;
}

function recordTitle(row: CompactFinanceRow, columns: readonly CompactFinanceColumn[]) {
  const identityColumn = columns[0];
  const identityCell = row.cells[identityColumn?.indexes[0] ?? 0];
  return textContent(selectCompactFinanceSummary(identityCell?.node, identityColumn?.summaryMode || 'first')).trim() || '此记录';
}

function CompactRow({ row, columns, open, detailId, onOpen }: {
  row: CompactFinanceRow; columns: readonly CompactFinanceColumn[]; open: boolean;
  detailId: string; onOpen: (row: CompactFinanceRow, button: HTMLButtonElement) => void;
}) {
  const recordLabel = recordTitle(row, columns);
  if (row.fullWidth) return <tr className="cft-message-row"><td colSpan={columns.length + 1}>
    {row.cells.map((cell, index) => <Value cell={cell} key={index} />)}
  </td></tr>;
  return <tr className={`cft-summary-row${open ? ' is-open' : ''}`}>
    {columns.map((column, columnIndex) => <td key={columnIndex} className={column.align === 'right' ? 'cft-number' : 'cft-text'}>
      <div className="cft-summary-values">{column.indexes.map(index => <Value key={index} cell={row.cells[index]}>
        {selectCompactFinanceSummary(row.cells[index]?.node, column.summaryMode)}
      </Value>)}</div>
    </td>)}
    <td className="cft-expand-cell"><button type="button" className="cft-expand" aria-label={`查看${recordLabel}明细`} aria-expanded={open} aria-haspopup="dialog" aria-controls={open ? detailId : undefined} onClick={event => onOpen(row, event.currentTarget)}>
      <ChevronRight aria-hidden="true" />
    </button></td>
  </tr>;
}

/** A presentation adapter over the existing table. No monetary or business logic belongs here. */
export default function CompactFinanceTable({ children, columns, expectedHeaders, className = '', legacyClassName = 'w-full text-sm', label = '财务记录', detailGroups, actionIndexes }: CompactFinanceTableProps) {
  const isDesktop = useSyncExternalStore(subscribeDesktop, desktopSnapshot, serverSnapshot);
  const selection = useSyncExternalStore(subscribeSelection, selectionSnapshot, serverSelectionSnapshot);
  const tableId = useId();
  const detailId = `${tableId}-details`;
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const actionHandoff = useRef(false);
  const stopActionFocusHandoff = useRef<(() => void) | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const table = extractCompactFinanceTable(children);
  const actions = new Set(actionIndexes || table.headers.flatMap((header, index) => header === '操作' ? [index] : []));
  const validColumns = columns.length > 0 && columns.every(column => column.indexes.length && column.indexes.every(index => Number.isInteger(index) && index >= 0 && index < table.headers.length));
  const headersMatch = !expectedHeaders || (expectedHeaders.length === table.headers.length && expectedHeaders.every((header, index) => header === table.headers[index]));
  const compact = isDesktop && table.supported && validColumns && headersMatch;
  const selectedRow = selection?.tableId === tableId ? table.rows.find(row => !row.fullWidth && rowKey(row) === selection.rowKey) : undefined;

  useEffect(() => {
    if (!compact || !containerRef.current) return;
    const observer = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width));
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [compact]);
  useEffect(() => {
    if (!compact || (selection && selection.tableId !== tableId) || (triggerRef.current && !triggerRef.current.isConnected)) stopActionFocusHandoff.current?.();
    if (selection?.tableId === tableId && (!compact || !selectedRow)) selectLedgerRecord(null);
  }, [compact, selectedRow, selection, tableId]);
  useEffect(() => () => {
    stopActionFocusHandoff.current?.();
    if (ledgerSelection?.tableId === tableId) selectLedgerRecord(null);
  }, [tableId]);

  if (!compact) return <table className={legacyClassName}>{children}</table>;
  const priorityLimit = containerWidth > 0 && containerWidth < 660 ? 1 : containerWidth > 0 && containerWidth < 900 ? 2 : 3;
  const summaryColumns = columns.map(column => ({ ...column, indexes: column.indexes.filter(index => !actions.has(index)) })).filter(column => column.indexes.length);
  const visibleColumns = summaryColumns.filter(column => (column.priority || 1) <= priorityLimit);
  const totalWidth = visibleColumns.reduce((total, column) => total + Math.max(column.width || 16, 1), 0);
  const caption = elements(children).find(section => section.type === 'caption');
  const recordLabel = selectedRow ? recordTitle(selectedRow, summaryColumns) : '';
  const closeDrawer = () => {
    if (!actionHandoff.current) stopActionFocusHandoff.current?.();
    if (ledgerSelection?.tableId === tableId) selectLedgerRecord(null);
  };
  const beforeAction = () => {
    actionHandoff.current = true;
    // Unmount the old focus trap and overlay before the original action executes.
    stopActionFocusHandoff.current?.();
    flushSync(closeDrawer);
    stopActionFocusHandoff.current = startActionFocusHandoff(triggerRef.current);
  };
  return <div ref={containerRef} className={`compact-finance-table ${className}`}>
    <div className="cft-scroll">
      <table className="cft-table" aria-label={label}>
        {caption}
        <colgroup>{visibleColumns.map((column, index) => <col key={index} style={{ width: `${Math.max(column.width || 16, 1) / totalWidth * 94}%` }} />)}<col className="cft-detail-column" /></colgroup>
        <thead><tr>{visibleColumns.map((column, index) => <th key={index} scope="col" className={column.align === 'right' ? 'cft-number' : undefined}>{column.label}</th>)}<th scope="col" className="cft-expand-heading">明细</th></tr></thead>
        <tbody>{table.rows.map(row => <CompactRow key={rowKey(row)} row={row} columns={visibleColumns} open={selectedRow === row} detailId={detailId} onOpen={(record, button) => {
          stopActionFocusHandoff.current?.();
          triggerRef.current = button;
          actionHandoff.current = false;
          selectLedgerRecord({ tableId, rowKey: rowKey(record) });
        }} />)}</tbody>
        {table.footerRows.length > 0 && <tfoot>{table.footerRows.map(row => <tr key={row.key} className="cft-footer-row"><td colSpan={visibleColumns.length + 1}>
          {row.fullWidth ? row.cells.map((cell, index) => <Value cell={cell} key={index} />) : <ExpandedFields headers={table.headers} row={row} groups={detailGroups} actions={new Set()} />}
        </td></tr>)}</tfoot>}
      </table>
    </div>
    <Sheet open={Boolean(selectedRow)} onOpenChange={open => { if (!open) closeDrawer(); }}>
      {selectedRow && <SheetPortal>
        <SheetOverlay className="cft-drawer-overlay" />
        <DialogPrimitive.Content id={detailId} className="t24-ui-surface cft-drawer" onCloseAutoFocus={event => {
          event.preventDefault();
          if (!actionHandoff.current && !ledgerSelection) triggerRef.current?.focus();
        }}>
          <header className="cft-drawer-header">
            <div><SheetTitle>{recordLabel}</SheetTitle><SheetDescription>{label} · 完整明细</SheetDescription></div>
            <SheetClose asChild><button type="button" className="cft-drawer-close" aria-label="关闭明细"><X aria-hidden="true" /></button></SheetClose>
          </header>
          <div className="cft-drawer-body"><ExpandedFields headers={table.headers} row={selectedRow} groups={detailGroups} actions={actions} beforeAction={beforeAction} /></div>
        </DialogPrimitive.Content>
      </SheetPortal>}
    </Sheet>
  </div>;
}
