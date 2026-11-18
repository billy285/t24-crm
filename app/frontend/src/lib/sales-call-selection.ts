export const callNoteLimit = 4000;

export type QuickNoteSnapshot = { id: string; label: string; text: string };
export type SelectedQuickNote = QuickNoteSnapshot & {
  /** Location of the original, unedited insertion in the current textarea. */
  start?: number;
  insertedNewline?: boolean;
  remindDoNotContact?: boolean;
};

const resultOrder = ['do_not_contact', 'no_answer', 'not_interested', 'appointment', 'interested', 'callback', 'not_now', 'existing_provider'];
const exclusiveResults = new Set(['do_not_contact', 'no_answer', 'not_interested']);

export function primaryCallOutcome(outcomes: string[]) {
  return resultOrder.find(value => outcomes.includes(value)) || '';
}

export function compatibleCallOutcomes(a: string, b: string) {
  if (a === b) return true;
  if (exclusiveResults.has(a) || exclusiveResults.has(b)) return false;
  const other = a === 'not_now' ? b : b === 'not_now' ? a : '';
  return other !== 'appointment' && other !== 'interested';
}

export function toggleCallOutcome(selected: string[], value: string) {
  if (selected.includes(value)) return selected.filter(item => item !== value);
  if (selected.includes('do_not_contact')) return selected;
  return [...selected.filter(item => compatibleCallOutcomes(item, value)), value];
}

// Keep the exact template snapshot even when the salesperson edits its wording.
// Only text that we can still identify as our own insertion may be removed.
export function trackEditedNotes(previous: string, next: string, selected: SelectedQuickNote[]): SelectedQuickNote[] {
  if (previous === next || !selected.length) return selected;
  let start = 0;
  while (start < previous.length && start < next.length && previous[start] === next[start]) start++;
  let end = previous.length;
  let nextEnd = next.length;
  while (end > start && nextEnd > start && previous[end - 1] === next[nextEnd - 1]) { end--; nextEnd--; }
  return selected.map(item => {
    if (item.start === undefined || item.start + item.text.length <= start) return item;
    if (item.start >= end) return { ...item, start: item.start + next.length - previous.length,
      insertedNewline: item.insertedNewline && item.start - 1 >= end };
    return { ...item, start: undefined, insertedNewline: false };
  });
}

export function toggleQuickNote(notes: string, selected: SelectedQuickNote[], template: QuickNoteSnapshot, remind = false) {
  const old = selected.find(item => item.id === template.id);
  if (!old) {
    const separator = notes && !notes.endsWith('\n') ? '\n' : '';
    return { notes: notes + separator + template.text, quickNotes: [...selected, {
      id: template.id, label: template.label, text: template.text, start: notes.length + separator.length,
      insertedNewline: Boolean(separator), remindDoNotContact: remind,
    }] };
  }
  const remaining = selected.filter(item => item.id !== old.id);
  if (old.start === undefined || notes.slice(old.start, old.start + old.text.length) !== old.text)
    return { notes, quickNotes: remaining };
  const from = old.insertedNewline && old.start > 0 && notes[old.start - 1] === '\n' ? old.start - 1 : old.start;
  let end = old.start + old.text.length;
  // If the first generated line is removed, its successor no longer needs
  // the separator we inserted between the two. Never strip a user's newline.
  const successor = from === 0 ? remaining.find(item => item.insertedNewline && item.start === end + 1) : undefined;
  if (successor && notes[end] === '\n') end++;
  const next = notes.slice(0, from) + notes.slice(end);
  return { notes: next, quickNotes: remaining.map(item => item.start !== undefined && item.start >= end
    ? { ...item, start: item.start - (end - from), insertedNewline: item === successor ? false : item.insertedNewline } : item) };
}
