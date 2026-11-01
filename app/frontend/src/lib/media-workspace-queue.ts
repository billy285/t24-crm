import { mediaWorkspaceGet, verifiedWorkspaceMerchants, workspaceRange, type WorkspaceMerchant, type WorkspacePage, type WorkspaceStatusFilter } from './media-workspace-api';

export type MerchantQueueScope = { platform: string; status: WorkspaceStatusFilter; operatorId: number | null; from: string; to: string; search: string };
export type MerchantQueueDestination = { merchant: WorkspaceMerchant; cursor: string | null; history: (string | null)[] };
type MerchantReader = (path: string, signal?: AbortSignal) => Promise<WorkspacePage<WorkspaceMerchant>>;

export function merchantQueueQuery(scope: MerchantQueueScope, cursor: string | null = null, limit = 12) {
  const range = workspaceRange(scope.from, scope.to);
  const query = new URLSearchParams({ start: range.start, end: range.end, limit: String(limit) });
  if (scope.search.trim()) query.set('q', scope.search.trim());
  if (scope.platform !== 'all') query.set('platform', scope.platform);
  if (scope.status !== 'all') query.set('status', scope.status);
  if (scope.operatorId) query.set('operator_id', String(scope.operatorId));
  if (cursor) query.set('cursor', cursor);
  return query;
}

/** Always read the current authorized queue. Cached names/rows never authorize a switch. */
export async function readNextQueueMerchant(scope: MerchantQueueScope, currentId: number, visited: ReadonlySet<number>, signal?: AbortSignal, read: MerchantReader = path => mediaWorkspaceGet(path, signal)): Promise<MerchantQueueDestination | null> {
  let cursor: string | null = null;
  const cursors = new Set<string>(), ids = new Set<number>(), history: (string | null)[] = [];
  let first: MerchantQueueDestination | null = null, foundCurrent = false, expectedTotal: number | null = null;
  do {
    if (signal?.aborted) throw new DOMException('已取消读取', 'AbortError');
    const page = verifiedWorkspaceMerchants(await read(`/merchants?${merchantQueueQuery(scope, cursor)}`, signal));
    if (expectedTotal !== null && page.total !== expectedTotal || !page.items.length && page.next_cursor) throw new Error('读取期间运营清单已变化，请返回清单刷新后继续。');
    expectedTotal = page.total;
    for (const merchant of page.items) {
      if (ids.has(merchant.id)) throw new Error('读取期间运营清单已变化，请返回清单刷新后继续。');
      ids.add(merchant.id);
      if (merchant.id === currentId) { foundCurrent = true; continue; }
      if (visited.has(merchant.id)) continue;
      const candidate = { merchant, cursor, history: [...history] };
      first ??= candidate;
      if (foundCurrent) return candidate;
    }
    if (!page.next_cursor) return first;
    if (ids.size >= expectedTotal) throw new Error('清单分页数量不一致，请返回清单刷新后继续。');
    if (cursors.has(page.next_cursor)) throw new Error('清单分页状态已变化，请返回清单刷新后继续。');
    cursors.add(page.next_cursor); history.push(cursor); cursor = page.next_cursor;
  } while (cursor);
  return first;
}

export function queueMonth(from: string, to: string): string | null {
  try {
    workspaceRange(from, to);
    const [year, month] = from.split('-').map(Number), end = new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
    return from.endsWith('-01') && to === end ? from.slice(0, 7) : null;
  } catch { return null; }
}
