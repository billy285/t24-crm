import { invokeWithAuth } from './tokenStore';
import { imageVersionId, imagePreviewPath, publicationImagePreviewDataUrl, sha256Blob, sourceImageDimensions } from './media-publication-images';

export type AssetKind = 'poster' | 'collage' | 'enhance' | 'video';
export type AssetFormat = 'square' | 'portrait' | 'landscape' | 'original';
export type AssetProfile = { revision: number; preset: 'editorial' | 'clean' | 'warm'; brand_name: string; primary_color: string; accent_color: string; footer: string };
export type AssetSource = { material_id: number; title: string; suggested_title?: string; linked_item_id: number | null; image_id: string; image_sha256: string; width: number; height: number; byte_size: number; preview_path: string; rights_basis: 'owned' | 'client_provided' | 'licensed' };
export type AssetRecipe = { profile_revision: number; kind: AssetKind; image_ids: string[]; title: string; subtitle: string; format: AssetFormat; exposure: number; color: number; sharpness: number; rights_confirmed: true };
export type AssetOutput = { preview_path: string; download_path?: string; mime_type: 'image/png' | 'video/mp4'; sha256: string; byte_size: number; width: number; height: number; duration_seconds: number | null };
export type AssetJob = { id: string; customer_id: number; request_id: string; revision: number; kind: AssetKind; status: 'queued' | 'processing' | 'succeeded' | 'failed' | 'unknown' | 'adopted'; profile_revision: number; recipe: AssetRecipe; sources: AssetSource[]; created_at: string; updated_at: string; error_code: string | null; message: string; source_stale: boolean; output: AssetOutput | null; adoption: { material_id: number; image_id: string | null; preview_path: string | null } | null; can_retry: boolean; can_adopt: boolean };
export type AssetStudio = { customer_id: number; customer_name: string; cooperation_active: boolean; read_only_reason: string | null; capabilities: { can_edit: boolean; can_create: boolean; can_adopt: boolean; poster: boolean; collage: boolean; enhance: boolean; video: boolean; video_reason: string | null }; profile: AssetProfile; sources: AssetSource[]; jobs: AssetJob[]; copy_suggestions?: { title: string; subtitle: string; source_label: string }[] };
export type AssetMutation = { kind: 'profile' | 'create' | 'retry' | 'adopt'; request_id: string; customer_id: number; job: AssetJob | null; profile: AssetProfile | null };
export const assetKindLabels: Record<AssetKind, string> = { poster: '品牌海报', collage: '真实照片拼图', enhance: '基础照片优化', video: '真实素材短视频' };
export const assetStatusLabels: Record<AssetJob['status'], string> = { queued: '等待制作', processing: '正在制作', succeeded: '待核对成品', failed: '制作未完成', unknown: '制作结果待确认', adopted: '已保存新素材' };
export const assetPresets = [{ value: 'editorial', label: '杂志版式 · 清晰有层次' }, { value: 'clean', label: '简洁留白 · 突出照片' }, { value: 'warm', label: '温暖质感 · 亲切自然' }];
export const MAX_ASSET_OUTPUT_BYTES = 24 * 1024 * 1024;
export function assetProfileReadable(profile: Pick<AssetProfile, 'preset' | 'primary_color'>): boolean {
  const background = profile.preset === 'warm' ? '#F6F3EC' : profile.preset === 'clean' ? '#F8FAFC' : '#FFFFFF';
  const luminance = (color: string) => {
    if (!/^#[a-fA-F0-9]{6}$/.test(color)) return NaN;
    const values = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
    return values[0] * .2126 + values[1] * .7152 + values[2] * .0722;
  };
  const a = luminance(profile.primary_color), b = luminance(background);
  return Number.isFinite(a) && (Math.max(a, b) + .05) / (Math.min(a, b) + .05) >= 4.5;
}
const integer = (value: unknown, min = 1, max = Number.MAX_SAFE_INTEGER): value is number => Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max;
const text = (value: unknown, max = 1000): value is string => typeof value === 'string' && value.length <= max;
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
const id = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
const date = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const fail = (): never => { throw new Error('素材制作资料与当前商家范围不一致，请重新读取。'); };
export function verifiedAssetProfile(value: AssetProfile): AssetProfile {
  if (!value || !integer(value.revision, 0) || !assetPresets.some(row => row.value === value.preset) || !text(value.brand_name, 60) || !text(value.footer, 120) || !/^#[a-fA-F0-9]{6}$/.test(value.primary_color) || !/^#[a-fA-F0-9]{6}$/.test(value.accent_color)) fail();
  return value;
}
export function verifiedAssetSource(value: AssetSource): AssetSource {
  if (!value || !integer(value.material_id) || !text(value.title, 200) || value.suggested_title !== undefined && !text(value.suggested_title, 200) || !(value.linked_item_id === null || integer(value.linked_item_id)) || !imageVersionId(value.image_id) || !hash(value.image_sha256) || !integer(value.width, 1, 2048) || !integer(value.height, 1, 2048) || !integer(value.byte_size, 1, 8 * 1024 * 1024) || !imagePreviewPath(value.preview_path, value.image_id) || !['owned', 'client_provided', 'licensed'].includes(value.rights_basis)) fail();
  return value;
}
export function verifiedAssetRecipe(value: AssetRecipe): AssetRecipe {
  if (!value || !integer(value.profile_revision, 0) || !Object.prototype.hasOwnProperty.call(assetKindLabels, value.kind) || !Array.isArray(value.image_ids) || !value.image_ids.length || value.image_ids.length > 6 || value.image_ids.some(image => !imageVersionId(image)) || new Set(value.image_ids).size !== value.image_ids.length || !text(value.title, 80) || !text(value.subtitle, 160) || !['square', 'portrait', 'landscape', 'original'].includes(value.format) || !Number.isFinite(value.exposure) || value.exposure < -.2 || value.exposure > .2 || !Number.isFinite(value.color) || value.color < .8 || value.color > 1.2 || !Number.isFinite(value.sharpness) || value.sharpness < .8 || value.sharpness > 1.2 || value.rights_confirmed !== true) fail();
  if ((value.kind === 'poster' || value.kind === 'enhance') && value.image_ids.length !== 1 || value.kind === 'collage' && (value.image_ids.length < 2 || value.image_ids.length > 4) || value.kind === 'video' && value.image_ids.length < 2) fail();
  if (value.kind === 'enhance' ? value.format !== 'original' : value.format === 'original') fail();
  return value;
}
export function verifiedAssetJob(value: AssetJob, customerId: number, jobId?: string): AssetJob {
  if (!value || !id(value.id) || jobId && value.id !== jobId || value.customer_id !== customerId || !uuid(value.request_id) || !integer(value.revision) || !Object.prototype.hasOwnProperty.call(assetStatusLabels, value.status) || !Object.prototype.hasOwnProperty.call(assetKindLabels, value.kind) || !integer(value.profile_revision, 0) || !date(value.created_at) || !date(value.updated_at) || !(value.error_code === null || text(value.error_code, 200)) || !text(value.message, 1000) || typeof value.source_stale !== 'boolean' || typeof value.can_retry !== 'boolean' || typeof value.can_adopt !== 'boolean') fail();
  verifiedAssetRecipe(value.recipe);
  if (value.recipe.kind !== value.kind || value.recipe.profile_revision !== value.profile_revision || !Array.isArray(value.sources) || value.sources.length !== value.recipe.image_ids.length) fail();
  value.sources.forEach(verifiedAssetSource);
  if (value.sources.some((source, index) => source.image_id !== value.recipe.image_ids[index])) fail();
  if (value.output) {
    const output = value.output;
    if (output.preview_path !== `/api/v1/media-asset-studio/jobs/${value.id}/preview` || output.download_path !== undefined && output.download_path !== `/api/v1/media-asset-studio/jobs/${value.id}/download` || !['image/png', 'video/mp4'].includes(output.mime_type) || !hash(output.sha256) || !integer(output.byte_size, 1, MAX_ASSET_OUTPUT_BYTES) || !integer(output.width, 1, 2048) || !integer(output.height, 1, 2048) || !(output.duration_seconds === null || Number.isFinite(output.duration_seconds) && output.duration_seconds > 0 && output.duration_seconds <= 60) || value.kind !== 'video' && output.mime_type !== 'image/png' || value.kind === 'video' && output.mime_type !== 'video/mp4') fail();
  }
  if (['succeeded', 'adopted'].includes(value.status) && !value.output || value.can_adopt && (value.status !== 'succeeded' || value.source_stale || !value.output) || value.can_retry && (value.source_stale || !['failed', 'unknown'].includes(value.status))) fail();
  if (value.adoption && (!integer(value.adoption.material_id) || !(value.adoption.image_id === null || imageVersionId(value.adoption.image_id)) || !(value.adoption.preview_path === null || imagePreviewPath(value.adoption.preview_path, value.adoption.image_id || undefined)) || value.sources.some(source => source.material_id === value.adoption!.material_id || source.image_id === value.adoption!.image_id))) fail();
  if (value.status === 'adopted' && !value.adoption || value.adoption && value.status !== 'adopted') fail();
  if (value.adoption && (value.kind === 'video' ? value.adoption.image_id !== null || value.adoption.preview_path !== null : !value.adoption.image_id || !value.adoption.preview_path)) fail();
  return value;
}
export function verifiedAssetStudio(value: AssetStudio, customerId: number): AssetStudio {
  if (!value || value.customer_id !== customerId || !integer(customerId) || !text(value.customer_name, 200) || typeof value.cooperation_active !== 'boolean' || !(value.read_only_reason === null || text(value.read_only_reason, 1000)) || !value.capabilities || ['can_edit', 'can_create', 'can_adopt', 'poster', 'collage', 'enhance', 'video'].some(key => typeof value.capabilities[key as keyof AssetStudio['capabilities']] !== 'boolean') || !(value.capabilities.video_reason === null || text(value.capabilities.video_reason, 1000)) || !Array.isArray(value.sources) || value.sources.length > 500 || !Array.isArray(value.jobs) || value.jobs.length > 100) fail();
  verifiedAssetProfile(value.profile); value.sources.forEach(verifiedAssetSource); value.jobs.forEach(job => verifiedAssetJob(job, customerId));
  if (value.copy_suggestions !== undefined && (!Array.isArray(value.copy_suggestions) || value.copy_suggestions.length > 12 || value.copy_suggestions.some(row => !row || !text(row.title, 80) || !row.title.trim() || !text(row.subtitle, 160) || !text(row.source_label, 200)))) fail();
  if (new Set(value.sources.map(source => source.image_id)).size !== value.sources.length || new Set(value.jobs.map(job => job.id)).size !== value.jobs.length || !value.cooperation_active && (value.capabilities.can_create || value.capabilities.can_edit || value.capabilities.can_adopt)) fail();
  return value;
}
export function verifiedAssetMutation(value: AssetMutation, expected: { kind: AssetMutation['kind']; request_id: string; customer_id: number; job_id?: string; recipe?: AssetRecipe; sources?: AssetSource[]; profile?: Omit<AssetProfile, 'revision'>; profile_revision?: number }): AssetMutation {
  if (!value || value.kind !== expected.kind || value.request_id !== expected.request_id || value.customer_id !== expected.customer_id) fail();
  if (value.kind === 'profile') {
    if (!value.profile || value.job !== null) fail(); verifiedAssetProfile(value.profile);
    if (expected.profile_revision !== undefined && value.profile.revision <= expected.profile_revision) fail();
    if (expected.profile && (expected.profile_revision === undefined || value.profile.revision === expected.profile_revision + 1) && Object.entries(expected.profile).some(([key, entry]) => value.profile![key as keyof AssetProfile] !== entry)) fail();
  } else {
    if (!value.job || value.profile !== null) fail(); verifiedAssetJob(value.job, expected.customer_id, expected.job_id);
    if (expected.recipe && JSON.stringify(value.job.recipe) !== JSON.stringify(expected.recipe)) {
      if (Object.entries(expected.recipe).some(([key, entry]) => JSON.stringify(value.job!.recipe[key as keyof AssetRecipe]) !== JSON.stringify(entry))) fail();
    }
    if (expected.sources && (expected.sources.length !== value.job.sources.length || expected.sources.some((source, index) => ['material_id', 'image_id', 'image_sha256', 'width', 'height', 'byte_size', 'rights_basis'].some(key => source[key as keyof AssetSource] !== value.job!.sources[index][key as keyof AssetSource])))) fail();
  }
  return value;
}
export async function assetStudioApi<T>(path: string, method: 'GET' | 'POST' | 'PUT' = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/media-asset-studio${path}`, method, ...(data !== undefined ? { data } : {}), options: { signal, timeout: 30000 } });
  return response.data as T;
}
export async function assetStudioPreview(output: AssetOutput | AssetSource, signal?: AbortSignal): Promise<{ blob: Blob; pngUrl: string | null }> {
  const source = 'image_id' in output, expectedHash = source ? output.image_sha256 : output.sha256;
  const path = output.preview_path;
  if (!integer(output.byte_size, 1, source ? 8 * 1024 * 1024 : MAX_ASSET_OUTPUT_BYTES) || !hash(expectedHash) || !integer(output.width, 1, 2048) || !integer(output.height, 1, 2048)) fail();
  if (source ? !imagePreviewPath(path, output.image_id) : !/^\/api\/v1\/media-asset-studio\/jobs\/[a-f0-9]{32}\/preview$/.test(path)) fail();
  const response = await invokeWithAuth({ url: path, method: 'GET', options: { responseType: 'blob', signal, timeout: 30000 } });
  if (!(response.data instanceof Blob) || response.data.size !== output.byte_size || response.data.size > MAX_ASSET_OUTPUT_BYTES || await sha256Blob(response.data) !== expectedHash) throw new Error('成品内容与固定记录不一致，请重新读取核对。');
  if (source || output.mime_type === 'image/png') {
    const blob = new Blob([response.data], { type: 'image/png' });
    const dimensions = sourceImageDimensions(new Uint8Array(await blob.arrayBuffer()));
    if (dimensions.kind !== 'png' || dimensions.width !== output.width || dimensions.height !== output.height) throw new Error('图片尺寸与固定记录不一致，请重新读取。');
    return { blob, pngUrl: await publicationImagePreviewDataUrl(blob) };
  }
  if (output.mime_type !== 'video/mp4') fail();
  const header = new Uint8Array(await response.data.slice(0, 64).arrayBuffer());
  if (header.length < 12 || String.fromCharCode(...header.slice(4, 8)) !== 'ftyp') throw new Error('视频文件格式无法核对，请重新读取。');
  return { blob: new Blob([response.data], { type: 'video/mp4' }), pngUrl: null };
}
