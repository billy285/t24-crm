import * as React from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

interface ComboboxOption {
  value: string;
  label: string;
  searchValue?: string;
}

interface ComboboxProps {
  options: ComboboxOption[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
}

export function Combobox({
  options,
  value,
  onValueChange,
  placeholder = 'Select option...',
  searchPlaceholder = 'Search...',
  emptyText = 'No options found',
  disabled = false,
  className,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const [portalContainer, setPortalContainer] = React.useState<HTMLElement | null>(null);

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      setPortalContainer(triggerRef.current?.closest<HTMLElement>('[role="dialog"]') ?? null);
    }
    setOpen(nextOpen);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn('w-full justify-between', className)}
          disabled={disabled}
        >
          <span className="truncate">
            {value
              ? options.find(option => option.value === value)?.label
              : placeholder}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        portalContainer={portalContainer ?? undefined}
        data-slot="combobox-content"
        className="w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border-slate-200 bg-white p-0 shadow-[0_18px_50px_-20px_rgba(15,23,42,0.45)]"
      >
        <Command
          className="rounded-xl [&_[cmdk-input-wrapper]]:mx-2 [&_[cmdk-input-wrapper]]:mt-2 [&_[cmdk-input-wrapper]]:rounded-lg [&_[cmdk-input-wrapper]]:border [&_[cmdk-input-wrapper]]:border-slate-200 [&_[cmdk-input-wrapper]]:bg-slate-50"
          filter={(option, search) => (
            option.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) ? 1 : 0
          )}
        >
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList className="max-h-64 touch-pan-y overscroll-contain p-1 [scrollbar-gutter:stable]">
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup className="p-0">
              {options.map(option => (
                <CommandItem
                  key={option.value}
                  value={option.searchValue || option.label}
                  className="min-h-11 rounded-lg px-3 py-2.5 text-[15px] data-[selected=true]:bg-blue-50 data-[selected=true]:text-blue-700"
                  onSelect={() => {
                    onValueChange(option.value);
                    setOpen(false);
                  }}
                >
                  {value === option.value && <Check className="mr-2 h-4 w-4 shrink-0 text-blue-600" />}
                  <span className="truncate">{option.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
