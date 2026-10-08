import type { ComponentProps } from 'react';
import { PhoneCall } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { getCustomerDialValidation, launchCustomerDial } from '@/lib/phone-dial';

type CustomerPhoneDialProps = Omit<ComponentProps<typeof Button>, 'asChild' | 'children' | 'onClick'> & {
  phone: string;
  country?: string | null;
  label?: string;
  buttonClassName?: string;
  onLaunched?: () => void;
};

function launch(phone: string, country?: string | null, onLaunched?: () => void) {
  const parsed = getCustomerDialValidation(phone, country);
  if (!parsed.isValid) {
    toast.error(parsed.reason);
    return;
  }

  // Prepare the CRM result form before the browser hands control to the
  // external dialer. When the salesperson returns, the form is ready.
  onLaunched?.();
  try {
    if (parsed.extension) toast.info(`接通后请手动输入分机 ${parsed.extension}`);
    launchCustomerDial(phone, country);
  } catch {
    toast.error('未能打开 RingCentral 网页拨号，请稍后重试');
    return;
  }
}

export default function CustomerPhoneDial({
  phone,
  country,
  label = 'RingCentral 网页拨号',
  className,
  buttonClassName,
  onLaunched,
  disabled,
  variant = 'outline',
  size = 'sm',
  ...buttonProps
}: CustomerPhoneDialProps) {
  const unavailable = disabled || !phone.trim();

  return (
    <div className={cn('inline-flex min-w-0', className)}>
      <Button
        {...buttonProps}
        type="button"
        size={size}
        variant={variant}
        disabled={unavailable}
        className={cn('min-h-11 min-w-0 flex-1 md:min-h-0', buttonClassName)}
        onClick={() => launch(phone, country, onLaunched)}
      >
        <PhoneCall className="mr-1.5 h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </Button>
    </div>
  );
}
