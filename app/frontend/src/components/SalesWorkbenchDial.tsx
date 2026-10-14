import { useEffect, useRef, useState } from 'react';
import { PhoneCall } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { getCustomerDialValidation, launchCustomerDial } from '@/lib/phone-dial';
import { enrichmentError } from '@/lib/use-sales-lead-enrichment';

export default function SalesWorkbenchDial({ phone, country, disabled, onPrepare, onLaunched, onBusyChange }: {
  phone: string; country?: string | null; disabled?: boolean;
  onPrepare: (phone: string) => Promise<void>; onLaunched: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const mounted = useRef(false);
  const generation = useRef(0);
  const target = JSON.stringify([phone, country || '']);
  const currentTarget = useRef(target);
  const pending = useRef<{ generation: number; release?: (busy: boolean) => void } | null>(null);
  const [preparing, setPreparing] = useState(false);
  // Invalidate during render as well as effect cleanup: a reply can arrive
  // after new props render but before that render's passive effects run.
  if (currentTarget.current !== target) {
    currentTarget.current = target;
    generation.current += 1;
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      const cancelled = pending.current;
      pending.current = null;
      // Release the parent's busy hold without setting state on this unmounted button.
      cancelled?.release?.(false);
    };
  }, []);
  useEffect(() => {
    if (pending.current && pending.current.generation !== generation.current) {
      const cancelled = pending.current;
      pending.current = null;
      setPreparing(false);
      cancelled.release?.(false);
    }
  }, [target]);
  const dial = async () => {
    if (!mounted.current || disabled || pending.current) return;
    const parsed = getCustomerDialValidation(phone, country);
    if (!parsed.isValid || !parsed.e164) { toast.error(parsed.reason); return; }
    const request = { generation: generation.current, release: onBusyChange };
    pending.current = request;
    const isCurrent = () => mounted.current && pending.current === request && generation.current === request.generation && currentTarget.current === target;
    onBusyChange?.(true);
    setPreparing(true);
    try {
      await onPrepare(parsed.e164);
      if (!isCurrent()) return;
      onLaunched();
      if (!isCurrent()) return;
      if (parsed.extension) toast.info(`接通后请手动输入分机 ${parsed.extension}`);
      launchCustomerDial(parsed.e164, country);
    } catch (error) { if (isCurrent()) toast.error(enrichmentError(error)); }
    finally {
      if (pending.current === request) {
        pending.current = null;
        if (mounted.current) setPreparing(false);
        request.release?.(false);
      }
    }
  };
  return <Button type="button" variant="outline" className="sw-dial-button" disabled={disabled || preparing || !phone.trim()} onClick={() => void dial()}><PhoneCall size={16} />{preparing ? '准备拨号…' : '拨打电话'}</Button>;
}
