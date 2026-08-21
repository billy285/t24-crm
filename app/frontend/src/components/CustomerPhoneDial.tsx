import type { ComponentProps } from 'react';
import { ChevronDown, Globe2, Phone, PhoneCall } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { getCustomerDialTarget, launchCustomerDial, type CustomerDialMode } from '@/lib/phone-dial';

type CustomerPhoneDialProps = Omit<ComponentProps<typeof Button>, 'asChild' | 'children' | 'onClick'> & {
  phone: string;
  label?: string;
  showAlternatives?: boolean;
  menuLabel?: string;
  buttonClassName?: string;
  menuButtonClassName?: string;
  onLaunched?: (mode: CustomerDialMode) => void;
};

function launch(phone: string, mode: CustomerDialMode, onLaunched?: (mode: CustomerDialMode) => void) {
  const target = getCustomerDialTarget(phone);
  if (!target) {
    toast.error('电话号码不完整，请先补充正确号码');
    return;
  }

  // Prepare the CRM result form before the browser hands control to the
  // external dialer. When the salesperson returns, the form is ready.
  onLaunched?.(mode);
  launchCustomerDial(phone, mode);

  if (mode === 'ringcentral') {
    toast.message('正在打开 RingCentral；返回系统后请如实记录通话结果。');
  } else if (mode === 'ringcentral_web') {
    toast.message('已打开 RingCentral 网页拨号。');
  } else {
    toast.message('已交给手机的系统电话处理。');
  }
}

export default function CustomerPhoneDial({
  phone,
  label = 'RingCentral 拨号',
  showAlternatives = true,
  menuLabel = '选择其他拨号方式',
  className,
  buttonClassName,
  menuButtonClassName,
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
        className={cn('min-h-11 min-w-0 flex-1 rounded-r-none md:min-h-0', !showAlternatives && 'rounded-r-md', buttonClassName)}
        onClick={() => launch(phone, 'ringcentral', onLaunched)}
      >
        <PhoneCall className="mr-1.5 h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </Button>
      {showAlternatives && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size={size}
              variant={variant}
              disabled={unavailable}
              className={cn('min-h-11 min-w-11 rounded-l-none border-l-0 px-2 md:min-h-0 md:min-w-0', menuButtonClassName)}
              aria-label={menuLabel}
            >
              <ChevronDown className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem className="min-h-11" onSelect={() => launch(phone, 'ringcentral', onLaunched)}>
              <PhoneCall className="mr-2 h-4 w-4" />
              RingCentral App
            </DropdownMenuItem>
            <DropdownMenuItem className="min-h-11" onSelect={() => launch(phone, 'ringcentral_web', onLaunched)}>
              <Globe2 className="mr-2 h-4 w-4" />
              RingCentral 网页版
            </DropdownMenuItem>
            <DropdownMenuItem className="min-h-11" onSelect={() => launch(phone, 'system', onLaunched)}>
              <Phone className="mr-2 h-4 w-4" />
              手机系统电话
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}
