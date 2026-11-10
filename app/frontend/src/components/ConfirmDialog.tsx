import { useEffect, useRef, useState, type MouseEvent } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  onConfirm: () => void | boolean | Promise<void | boolean>;
  loading?: boolean;
  confirmLabel?: string;
  loadingLabel?: string;
  destructive?: boolean;
}

export default function ConfirmDialog({
  open,
  onOpenChange,
  title = '确认删除',
  description = '此操作不可撤销，确定要删除吗？',
  onConfirm,
  loading = false,
  confirmLabel = '确认删除',
  loadingLabel = '删除中...',
  destructive = true,
}: ConfirmDialogProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const operation = useRef<object | null>(null);
  const isOpen = useRef(open);
  isOpen.current = open;
  useEffect(() => {
    if (!open) {
      operation.current = null;
      setPending(false);
      setError('');
    }
  }, [open]);
  useEffect(() => () => { operation.current = null; }, []);
  const busy = loading || pending;
  const confirm = async (event: MouseEvent<HTMLButtonElement>) => {
    // Radix Action normally closes immediately, before an async operation settles.
    event.preventDefault();
    if (loading || operation.current) return;
    const ticket = {};
    operation.current = ticket;
    setPending(true);
    setError('');
    try {
      const confirmed = await onConfirm();
      // Existing callers close only on success. A resolved callback may have
      // handled a failure itself, so keep its target and show a retry in place.
      if (operation.current === ticket && isOpen.current) {
        if (confirmed === true) onOpenChange(false);
        else setError('操作未完成，请核对提示后重试。');
      }
    } catch (cause) {
      if (operation.current === ticket && isOpen.current) {
        setError(cause instanceof Error && cause.message ? cause.message : '操作未完成，请稍后重试。');
      }
    } finally {
      if (operation.current === ticket) {
        operation.current = null;
        setPending(false);
      }
    }
  };
  return (
    <AlertDialog open={open} onOpenChange={next => {
      if (!next && (loading || operation.current)) return;
      setError('');
      onOpenChange(next);
    }}>
      <AlertDialogContent aria-busy={busy} onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
          <AlertDialogAction
            onClick={confirm}
            disabled={busy}
            aria-busy={busy}
            className={destructive ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}
          >
            {busy ? loadingLabel : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
