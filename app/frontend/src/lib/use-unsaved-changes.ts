import { useCallback, useLayoutEffect, useRef } from 'react';

const pendingForms = new Set<symbol>();
const DISCARD_MESSAGE = '有尚未保存的修改。确定要放弃修改并离开吗？\n选择“取消”可继续编辑。';
let unloadGuardInstalled = false;

export function hasUnsavedChanges(): boolean {
  return pendingForms.size > 0;
}

function installUnloadGuard() {
  if (unloadGuardInstalled || typeof window === 'undefined') return;
  unloadGuardInstalled = true;
  window.addEventListener('beforeunload', event => {
    if (!hasUnsavedChanges()) return;
    event.preventDefault();
    event.returnValue = '';
  });
}

/** A single prompt protects all mounted drafts when navigating between pages. */
export function confirmDiscardAllChanges(): boolean {
  if (!hasUnsavedChanges()) return true;
  if (!window.confirm(DISCARD_MESSAGE)) return false;
  pendingForms.clear();
  return true;
}

/** Protect a form without storing business or financial data in browser storage. */
export function useUnsavedChanges(dirty: boolean) {
  const identity = useRef(Symbol('draft'));
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useLayoutEffect(() => {
    installUnloadGuard();
    if (dirty) pendingForms.add(identity.current);
    else pendingForms.delete(identity.current);
    const token = identity.current;
    return () => { pendingForms.delete(token); };
  }, [dirty]);

  const markSaved = useCallback(() => {
    pendingForms.delete(identity.current);
    dirtyRef.current = false;
  }, []);

  const confirmDiscard = useCallback(() => {
    if (!dirtyRef.current) return true;
    if (!window.confirm(DISCARD_MESSAGE)) return false;
    markSaved();
    return true;
  }, [markSaved]);

  return { confirmDiscard, markSaved };
}
