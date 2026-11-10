import { useCallback, useLayoutEffect, useState } from 'react';
import { applyCrmTheme, crmThemeStorageKey, DEFAULT_CRM_THEME, isCrmThemeId, persistCrmTheme, readCrmTheme, type CrmThemeId } from './crm-theme';
const storage = () => { try { return window.localStorage; } catch { return null; } };
export function useCrmTheme(employeeId: number | string | null | undefined, enabled: boolean) {
  const key=crmThemeStorageKey(employeeId);
  const [selection,setSelection]=useState<{key:string|null;id:CrmThemeId}>({key:null,id:DEFAULT_CRM_THEME});
  const themeId=enabled && selection.key===key ? selection.id : DEFAULT_CRM_THEME;
  useLayoutEffect(()=>{
    if(!enabled || !key) return;
    setSelection(previous=>{
      let id=previous.key===key ? previous.id : DEFAULT_CRM_THEME;
      try { const value=window.localStorage.getItem(key); id=isCrmThemeId(value) ? value : DEFAULT_CRM_THEME; } catch { /* Keep this account's session choice when persistence is unavailable. */ }
      return {key,id};
    });
  },[key,enabled]);
  useLayoutEffect(()=>{
    if(!key || !enabled) return;
    return applyCrmTheme(document.documentElement,themeId);
  },[key,enabled,themeId]);
  useLayoutEffect(()=>{
    if(!key || !enabled) return;
    const sync=(event:StorageEvent)=>{if(event.storageArea===storage() && (event.key===key || event.key===null)) setSelection({key,id:readCrmTheme(storage(),key)});};
    window.addEventListener('storage',sync);return ()=>window.removeEventListener('storage',sync);
  },[key,enabled]);
  const setTheme=useCallback((id:CrmThemeId)=>{
    if(!key || !enabled || !isCrmThemeId(id)) return false;
    setSelection({key,id});return persistCrmTheme(storage(),key,id);
  },[key,enabled]);
  return {themeId,setTheme};
}
