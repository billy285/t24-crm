import { invokeWithAuth } from './tokenStore';

export type PublicationImage = {
  id: string; customer_id: number; material_id: number; request_id?: string;
  source_sha256: string; image_sha256: string; width: number; height: number; byte_size: number;
  rights_basis: 'owned' | 'client_provided' | 'licensed'; created_at: string; revoked_at: string | null;
  status: 'ready' | 'revoked' | 'source_changed'; preview_path: string; can_revoke: boolean;
};
export type PublicationImageList = { items: PublicationImage[]; can_prepare: boolean; delivery_available: boolean };
export const publicationRights = [
  { value: 'owned', label: '公司或门店自有图片' },
  { value: 'client_provided', label: '客户提供并允许公开使用' },
  { value: 'licensed', label: '已取得相应商业使用授权' },
];
export const MAX_IMAGE_SOURCE_BYTES = 20 * 1024 * 1024;
export const MAX_IMAGE_SIDE = 2048;
/** A late A response stays stale even if navigation goes A → B → A. */
export function imageRequestScope(initial: string) {
  let key = initial, generation = 0, active = true;
  return {
    update(next: string) { if (next !== key) { key = next; generation++; } },
    activate() { active = true; generation++; },
    invalidate() { active = false; generation++; },
    capture() { const capturedKey = key, capturedGeneration = generation; return () => active && key === capturedKey && generation === capturedGeneration; },
  };
}
export const imageVersionId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
export const imagePreviewPath = (value: unknown, id?: string): value is string => typeof value === 'string'
  && /^\/api\/v1\/media-publication-images\/[a-f0-9]{32}\/preview$/.test(value)
  && (!id || value === `/api/v1/media-publication-images/${id}/preview`);
export function verifiedPublicationImage(value: PublicationImage, customerId?: number, materialId?: number): PublicationImage {
  if (!value || !imageVersionId(value.id) || !Number.isSafeInteger(value.customer_id) || value.customer_id < 1 || !Number.isSafeInteger(value.material_id) || value.material_id < 1
    || (customerId !== undefined && value.customer_id !== customerId) || (materialId !== undefined && value.material_id !== materialId)
    || !/^[a-f0-9]{64}$/.test(value.source_sha256) || !/^[a-f0-9]{64}$/.test(value.image_sha256)
    || !imagePreviewPath(value.preview_path, value.id) || !['ready', 'revoked', 'source_changed'].includes(value.status)
    || !publicationRights.some(row => row.value === value.rights_basis) || typeof value.can_revoke !== 'boolean' || typeof value.created_at !== 'string'
    || ![value.width, value.height].every(side => Number.isSafeInteger(side) && side > 0 && side <= MAX_IMAGE_SIDE)
    || !Number.isSafeInteger(value.byte_size) || value.byte_size < 1 || value.byte_size > 8 * 1024 * 1024) throw new Error('发布图片资料返回不完整，请重新读取。');
  return value;
}
export async function publicationImages(customerId: number, materialId: number): Promise<PublicationImageList> {
  const response = await invokeWithAuth({url: '/api/v1/media-publication-images', method: 'GET', data: { customer_id: customerId, material_id: materialId }});
  const data = response.data as PublicationImageList;
  if (!data || !Array.isArray(data.items) || typeof data.can_prepare !== 'boolean' || typeof data.delivery_available !== 'boolean') throw new Error('发布图片列表返回不完整。');
  data.items.forEach(row => verifiedPublicationImage(row, customerId, materialId));
  return data;
}
export async function sha256Blob(blob: Blob): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, '0')).join('');
}
export async function verifiedPreviewBlob(image: PublicationImage, value: unknown): Promise<Blob> {
  verifiedPublicationImage(image);
  if (!(value instanceof Blob) || value.size !== image.byte_size || value.size > 8 * 1024 * 1024 || await sha256Blob(value) !== image.image_sha256) throw new Error('图片内容与保存版本不一致，请刷新后核对。');
  return new Blob([value], {type: 'image/png'});
}

/** Check dimensions before asking the browser decoder to allocate a bitmap. */
export function sourceImageDimensions(bytes: Uint8Array): { kind: 'png' | 'jpeg'; width: number; height: number } {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let width = 0, height = 0, kind: 'png' | 'jpeg';
  if (bytes.length >= 33 && [137,80,78,71,13,10,26,10].every((value, index) => bytes[index] === value)) {
    if (view.getUint32(8) !== 13 || String.fromCharCode(...bytes.slice(12, 16)) !== 'IHDR') throw new Error('PNG 图片头不完整。');
    width = view.getUint32(16); height = view.getUint32(20); kind = 'png';
    // Multi-frame files are not silently reduced to a single public picture.
    let position = 8;
    while (position + 12 <= bytes.length) {
      const length = view.getUint32(position), end = position + length + 12;
      if (length > bytes.length || end > bytes.length) throw new Error('PNG 图片数据不完整。');
      const chunk = String.fromCharCode(...bytes.slice(position + 4, position + 8));
      if (['acTL', 'fcTL', 'fdAT'].includes(chunk)) throw new Error('暂不支持动态图，请提供单张 JPEG 或 PNG 图片。');
      position = end;
      if (chunk === 'IEND') break;
    }
  } else if (bytes.length > 4 && bytes[0] === 255 && bytes[1] === 216) {
    kind = 'jpeg'; let position = 2;
    while (position + 4 <= bytes.length) {
      if (bytes[position++] !== 255) throw new Error('JPEG 图片数据不完整。');
      while (bytes[position] === 255) position++;
      const marker = bytes[position++];
      if (marker === 0xda || marker === 0xd9) break;
      if (marker === 0x01 || marker >= 0xd0 && marker <= 0xd7) continue;
      if (position + 2 > bytes.length) break;
      const length = view.getUint16(position);
      if (length < 2 || position + length > bytes.length) throw new Error('JPEG 图片数据不完整。');
      if ([0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf].includes(marker)) {
        if (length < 8) throw new Error('JPEG 图片尺寸无效。');
        height = view.getUint16(position + 3); width = view.getUint16(position + 5); break;
      }
      position += length;
    }
  } else throw new Error('仅支持真实的 JPEG 或 PNG 单张图片，请勿选择视频、SVG 或文档。');
  if (!width || !height || width > 12000 || height > 12000 || width * height > 40_000_000) throw new Error('图片尺寸过大或无法核实，请使用不超过 4000 万像素的图片。');
  return { kind, width, height };
}
export function publicationImageSize(width: number, height: number): { width: number; height: number } {
  const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}
export async function prepareBrowserImage(source: Blob): Promise<{ file: Blob; sourceSha256: string; width: number; height: number }> {
  if (!source.size || source.size > MAX_IMAGE_SOURCE_BYTES) throw new Error('发布图片原文件需小于 20MB。');
  const bytes = new Uint8Array(await source.arrayBuffer()), checked = sourceImageDimensions(bytes);
  if (typeof createImageBitmap !== 'function') throw new Error('当前浏览器尚不支持安全处理图片，请使用新版浏览器后重试。');
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(new Blob([bytes], {type: checked.kind === 'png' ? 'image/png' : 'image/jpeg'}), { imageOrientation: 'from-image' }); }
  catch { throw new Error('原图片无法完整解码，请重新上传完整的 JPEG 或 PNG 文件。'); }
  try {
    // EXIF orientation may exchange width/height; guard decoded dimensions too.
    if (!bitmap.width || !bitmap.height || bitmap.width * bitmap.height > 40_000_000) throw new Error('图片解码后的尺寸超出处理范围。');
    const size = publicationImageSize(bitmap.width, bitmap.height), canvas = document.createElement('canvas');
    canvas.width = size.width; canvas.height = size.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('浏览器暂不支持图片处理，请换用新版浏览器。');
    context.drawImage(bitmap, 0, 0, size.width, size.height);
    const file = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('图片处理未完成，请重试。')), 'image/png'));
    if (!file.size || file.size > 8 * 1024 * 1024) throw new Error('图片处理后仍过大，请使用尺寸更小的图片。');
    return { file, sourceSha256: await sha256Blob(source), ...size };
  } finally { bitmap.close(); }
}
