export type CrmThemeId = 'blue' | 'obsidian' | 'ocean' | 'forest' | 'amethyst' | 'copper';
type Palette = { accent: string; accentHover: string; accentSoft: string; accentBorder: string; canvas: string; surface: string; surfaceSubtle: string; ink: string; muted: string; border: string; rail: string; railMuted: string; railActive: string; railActiveText: string };
export type CrmTheme = { id: CrmThemeId; name: string; description: string; swatch: Pick<Palette, 'accent' | 'canvas' | 'rail' | 'surface'>; palette: Palette };
const theme = (id: CrmThemeId, name: string, description: string, palette: Palette): CrmTheme => ({ id, name, description, swatch: { accent: palette.accent, canvas: palette.canvas, rail: palette.rail, surface: palette.surface }, palette });
export const CRM_THEMES: readonly CrmTheme[] = [
  theme('blue', '经典蓝', '熟悉明快 · 默认风格', { accent:'#2563EB',accentHover:'#1D4ED8',accentSoft:'#EFF6FF',accentBorder:'#BFDBFE',canvas:'#F3F6FB',surface:'#FFFFFF',surfaceSubtle:'#F8FAFC',ink:'#0F172A',muted:'#64748B',border:'#DFE5EE',rail:'#0B1730',railMuted:'#BAC6D8',railActive:'#2563EB',railActiveText:'#FFFFFF' }),
  theme('obsidian', '墨金', '炭墨与香槟 · 沉静精致', { accent:'#705735',accentHover:'#584329',accentSoft:'#F1EBDD',accentBorder:'#D8CBB3',canvas:'#F3F1EC',surface:'#FFFEFC',surfaceSubtle:'#F7F5F0',ink:'#25231F',muted:'#716B60',border:'#E1DCD2',rail:'#1D1E20',railMuted:'#C8C3B9',railActive:'#D8BE88',railActiveText:'#28231B' }),
  theme('ocean', '深海', '藏蓝与雾青 · 清晰稳重', { accent:'#175B76',accentHover:'#10465C',accentSoft:'#E5F0F3',accentBorder:'#B9D3DD',canvas:'#F0F4F7',surface:'#FFFFFF',surfaceSubtle:'#F5F8FA',ink:'#182C39',muted:'#5D7380',border:'#D8E2E8',rail:'#132834',railMuted:'#B4C9D5',railActive:'#C5E1E8',railActiveText:'#153D4C' }),
  theme('forest', '松绿', '深松与云白 · 自然克制', { accent:'#2E6352',accentHover:'#214C3E',accentSoft:'#E8F0EB',accentBorder:'#BFD4C8',canvas:'#F1F4F0',surface:'#FEFFFC',surfaceSubtle:'#F6F8F3',ink:'#22342B',muted:'#66766A',border:'#DCE3D9',rail:'#1C2D27',railMuted:'#BACCBF',railActive:'#CDDFCD',railActiveText:'#244333' }),
  theme('amethyst', '烟紫', '灰紫与瓷白 · 温润雅致', { accent:'#69527D',accentHover:'#503E61',accentSoft:'#EFEAF3',accentBorder:'#D2C5DE',canvas:'#F4F1F6',surface:'#FFFEFF',surfaceSubtle:'#F8F5FA',ink:'#302637',muted:'#776C80',border:'#E3DCE9',rail:'#2B2333',railMuted:'#CCBFD7',railActive:'#DDD0E7',railActiveText:'#473454' }),
  theme('copper', '暖铜', '烟棕与燕麦 · 简约温暖', { accent:'#865942',accentHover:'#6A4432',accentSoft:'#F3EAE3',accentBorder:'#DEC8B9',canvas:'#F6F2EC',surface:'#FFFEFB',surfaceSubtle:'#FAF6F0',ink:'#372C25',muted:'#7B6E62',border:'#E7DED3',rail:'#302820',railMuted:'#D0C3B2',railActive:'#E7CFB0',railActiveText:'#4A3424' }),
];
export const DEFAULT_CRM_THEME: CrmThemeId = 'blue';
export const isCrmThemeId = (value: unknown): value is CrmThemeId => CRM_THEMES.some(item => item.id === value);
export const getCrmTheme = (id: unknown): CrmTheme => CRM_THEMES.find(item => item.id === id) || CRM_THEMES[0];
export function crmThemeStorageKey(employeeId: number | string | null | undefined): string | null {
  const id = String(employeeId ?? '').trim();
  return /^[1-9]\d*$/.test(id) ? `t24_crm_theme_v1:${id}` : null;
}
type ThemeStorage = Pick<Storage, 'getItem' | 'setItem'>;
export function readCrmTheme(storage: ThemeStorage | null, key: string | null): CrmThemeId {
  if (!key) return DEFAULT_CRM_THEME;
  try { const value = storage?.getItem(key); return isCrmThemeId(value) ? value : DEFAULT_CRM_THEME; } catch { return DEFAULT_CRM_THEME; }
}
export function persistCrmTheme(storage: ThemeStorage | null, key: string | null, id: unknown): boolean {
  if (!key || !storage || !isCrmThemeId(id)) return false;
  try { storage.setItem(key, id); return true; } catch { return false; }
}
function hsl(hex: string): string {
  const [r,g,b] = [1,3,5].map(start => parseInt(hex.slice(start,start+2),16)/255);
  const hi=Math.max(r,g,b),lo=Math.min(r,g,b),d=hi-lo,l=(hi+lo)/2;
  let hue=0;
  if(d) hue=(hi===r?(g-b)/d+(g<b?6:0):hi===g?(b-r)/d+2:(r-g)/d+4)*60;
  return `${hue.toFixed(2)} ${(d ? d/(1-Math.abs(2*l-1))*100 : 0).toFixed(2)}% ${(l*100).toFixed(2)}%`;
}
export function crmThemeVariables(id: CrmThemeId): Record<string,string> {
  const p=getCrmTheme(id).palette;
  const variables=Object.fromEntries(Object.entries(p).map(([key,value])=>[`--crm-${key.replace(/[A-Z]/g,char=>`-${char.toLowerCase()}`)}`,value]));
  const roles={background:p.canvas,foreground:p.ink,card:p.surface,'card-foreground':p.ink,popover:p.surface,'popover-foreground':p.ink,primary:p.accent,'primary-foreground':'#FFFFFF',secondary:p.surfaceSubtle,'secondary-foreground':p.ink,muted:p.surfaceSubtle,'muted-foreground':p.muted,accent:p.accentSoft,'accent-foreground':p.accent,border:p.border,input:p.border,ring:p.accent};
  for(const [key,value] of Object.entries(roles)) variables[`--${key}`]=hsl(value);
  return variables;
}
/** Restore only the properties this application theme owns, including on logout. */
export function applyCrmTheme(root: HTMLElement, id: CrmThemeId): () => void {
  if(id===DEFAULT_CRM_THEME) return () => {};
  const priorAttribute=root.getAttribute('data-crm-theme');
  const variables=crmThemeVariables(id);
  const prior=Object.keys(variables).map(key=>({key,value:root.style.getPropertyValue(key),priority:root.style.getPropertyPriority(key)}));
  root.setAttribute('data-crm-theme',id);
  for(const [key,value] of Object.entries(variables)) root.style.setProperty(key,value);
  return () => {
    if(priorAttribute===null) root.removeAttribute('data-crm-theme'); else root.setAttribute('data-crm-theme',priorAttribute);
    for(const {key,value,priority} of prior) { if(value) root.style.setProperty(key,value,priority); else root.style.removeProperty(key); }
  };
}
