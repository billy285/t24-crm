import type { ComponentProps } from 'react';
import { PhoneCall } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { getCustomerDialTarget, launchCustomerDial } from '@/lib/phone-dial';

type CustomerPhoneDialProps = Omit<ComponentProps<typeof Button>, 'asChild' | 'children' | 'onClick'> & {
  phone: string;
  label?: string;
  buttonClassName?: string;
  onLaunched?: () => void;
};

function launch(phone: string, onLaunched?: () => void) {
  const target = getCustomerDialTarget(phone);
  if (!target) {
    toast.error('电话号码不完整，请先补充正确号码');
    return;
  }

  // Prepare the CRM result form before the browser hands control to the
  // external dialer. When the salesperson returns, the form is ready.
  onLaunched?.();
  try {
    launchCustomerDial(phone);
  } catch {
    toast.error('未能打开 RingCentral 网页拨号，请稍后重试');
    return;
  }
}

export default function CustomerPhoneDial({
  phone,
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
        onClick={() => launch(phone, onLaunched)}
      >
        <PhoneCall className="mr-1.5 h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </Button>
    </div>
  );
}
