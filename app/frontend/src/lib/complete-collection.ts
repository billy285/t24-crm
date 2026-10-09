type CollectionResponse<T> = { data: { items: T[]; total: number } };

/** Read every authorized page; an incomplete or changing result is never a zero. */
export async function readCompleteCollection<T extends { id?: number | string }>(
  fetchPage: (params: { skip: number; limit: number; sort: string }) => Promise<CollectionResponse<T>>,
  limit = 500,
): Promise<CollectionResponse<T>> {
  const items: T[] = [];
  const ids = new Set<string>();
  let expectedTotal: number | undefined;
  for (let page = 0; page < 200; page++) {
    const response = await fetchPage({ skip: items.length, limit, sort: 'id' });
    const data = response?.data;
    if (!data || !Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0) {
      throw new Error('完整统计读取失败，请重试');
    }
    expectedTotal ??= data.total;
    if (data.total !== expectedTotal || (!data.items.length && items.length < expectedTotal)) {
      throw new Error('资料正在变化，请重新更新完整统计');
    }
    for (const item of data.items) {
      const key = String(item.id ?? '');
      if (!key || ids.has(key)) throw new Error('完整统计包含重复或缺失记录，请重试');
      ids.add(key);
      items.push(item);
    }
    if (items.length === expectedTotal) return { data: { items, total: expectedTotal } };
    if (items.length > expectedTotal) throw new Error('完整统计范围不一致，请重试');
  }
  throw new Error('资料较多，完整统计暂未读取完成，请重试');
}
