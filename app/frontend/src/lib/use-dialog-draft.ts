import { useRef } from 'react';
import { useUnsavedChanges } from './use-unsaved-changes';

/** Compare edits with the values present when the editor opened. */
export function useDialogDraft(open: boolean, values: unknown) {
  const snapshot = JSON.stringify(values);
  const session = useRef({ open: false, initial: snapshot });
  if (!open || !session.current.open) session.current.initial = snapshot;
  session.current.open = open;
  const dirty = open && snapshot !== session.current.initial;
  return { dirty, ...useUnsavedChanges(dirty) };
}
