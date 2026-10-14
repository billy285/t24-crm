import { useEffect, useRef, useState } from 'react';
import { invokeWithAuth } from './tokenStore';
import { normalizeEnrichmentResponse, type EnrichmentResponse, type EnrichmentUpdate, type EnrichmentProduct, type EnrichmentHistoryEntry } from './sales-lead-enrichment';
import { readEnrichmentDraft, removeEnrichmentDraft, writeEnrichmentDraft, salesEnrichmentDraftKey } from './sales-enrichment-draft';

export function enrichmentError(error: any): string {
  const detail = error?.response?.data?.detail ?? error?.data?.detail ?? error?.message;
  return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg || '资料格式不正确').join('；') : '资料暂时无法保存，请重试';
}
type Scope = { userId?: number; salesId?: number; leadId?: number; taskId?: number; date: string };
type State = { key: string | null; value: EnrichmentResponse | null; draft: EnrichmentUpdate | null; catalog: EnrichmentProduct[]; history: EnrichmentHistoryEntry[]; loading: boolean; saving: boolean; error: string; notice: string };
const empty = (key: string | null): State => ({ key, value: null, draft: null, catalog: [], history: [], loading: Boolean(key), saving: false, error: '', notice: '' });

export function useSalesLeadEnrichment(scope: Scope, onSaved: (value: EnrichmentResponse) => void) {
  const key = salesEnrichmentDraftKey(scope);
  const [state, setState] = useState<State>(() => empty(key));
  const [open, setOpen] = useState(false);
  const generation = useRef(0);
  const currentKey = useRef(key);
  currentKey.current = key;
  const stateRef = useRef(state);
  stateRef.current = state;
  const onSavedRef = useRef(onSaved);
  onSavedRef.current = onSaved;
  const busy = useRef(false);
  const visible = state.key === key ? state : empty(key);

  const load = async (discard = false) => {
    const request = ++generation.current;
    const requestKey = key;
    const leadId = scope.leadId;
    if (!requestKey || !leadId) { setState(empty(null)); return; }
    if (discard) removeEnrichmentDraft(requestKey);
    const restored = discard ? null : readEnrichmentDraft(requestKey);
    setState({ ...empty(requestKey), draft: restored, notice: restored ? '已恢复本商家的资料草稿，保存前请核对' : '' });
    try {
      const [record, catalog] = await Promise.all([
        invokeWithAuth({ url: `/api/v1/sales-leads/${leadId}/enrichment`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/sales-leads/enrichment/catalog', method: 'GET' }),
      ]);
      if (request !== generation.current || currentKey.current !== requestKey) return;
      const value = normalizeEnrichmentResponse(record.data);
      if (value.lead_id !== leadId) throw new Error('资料与当前商家不一致，请重新读取');
      setState(s => ({ ...s, value, catalog: Array.isArray(catalog.data?.items) ? catalog.data.items : [], loading: false }));
    } catch (error) {
      if (request === generation.current && currentKey.current === requestKey) setState(s => ({ ...s, loading: false, error: enrichmentError(error) }));
    }
  };
  useEffect(() => {
    setOpen(false);
    void load();
    return () => { generation.current += 1; };
  }, [key]); // A different employee/lead/task must never inherit the preceding request or draft.

  const changeDraft = (draft: EnrichmentUpdate | null) => {
    if (!key || currentKey.current !== key || busy.current) return;
    const persistence = draft ? writeEnrichmentDraft(key, draft) : (removeEnrichmentDraft(key), 'session');
    setState(s => s.key !== key ? s : ({ ...s, draft, error: '', notice: draft ? persistence === 'session' ? '资料草稿已暂存，将随本次沟通一起保存' : '资料仅保留在当前页面，请先保存再离开' : '' }));
  };
  const acceptSaved = (raw: unknown, expectedKey = key) => {
    if (!expectedKey) return;
    const value = normalizeEnrichmentResponse(raw as EnrichmentResponse);
    const savedLeadId = Number(expectedKey.split(':')[5]);
    if (value.lead_id !== savedLeadId || !Number.isInteger(value.revision) || !value.lead_updated_at) throw new Error('保存结果与当前商家不一致，草稿已保留，请重新核对');
    removeEnrichmentDraft(expectedKey);
    if (currentKey.current !== expectedKey) return;
    setState(s => ({ ...s, value, draft: null, error: '', history: [], notice: '资料已保存' }));
    onSavedRef.current(value);
  };
  const save = async (draft: EnrichmentUpdate) => {
    if (!key || !scope.leadId || busy.current || stateRef.current.key !== key || !stateRef.current.value?.can_edit) return;
    const saveKey = key;
    busy.current = true;
    setState(s => ({ ...s, saving: true, error: '' }));
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${scope.leadId}/enrichment`, method: 'PUT', data: draft });
      acceptSaved(response.data, saveKey);
      if (currentKey.current === saveKey) setOpen(false);
    } catch (error) {
      if (currentKey.current === saveKey) setState(s => ({ ...s, error: enrichmentError(error) }));
    } finally {
      busy.current = false;
      if (currentKey.current === saveKey) setState(s => ({ ...s, saving: false }));
    }
  };
  const loadHistory = async () => {
    const historyKey = key;
    if (!historyKey || !scope.leadId) return;
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${scope.leadId}/enrichment/history?limit=20`, method: 'GET' });
      if (currentKey.current === historyKey) setState(s => ({ ...s, history: response.data?.items || [] }));
    } catch (error) { if (currentKey.current === historyKey) setState(s => ({ ...s, error: enrichmentError(error) })); }
  };
  const reportSaveError = (error: unknown) => setState(s => s.key === key ? { ...s, error: enrichmentError(error) } : s);
  return { ...visible, key, open, setOpen, changeDraft, save, acceptSaved, loadHistory, reload: () => load(true), reportSaveError };
}
