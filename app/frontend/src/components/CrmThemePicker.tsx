import { useId, type CSSProperties } from 'react';
import { Check } from 'lucide-react';
import { CRM_THEMES, type CrmThemeId } from '@/lib/crm-theme';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogTitle, DialogDescription, CrmFormDialogContent,
  CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter,
} from '@/components/ui/dialog';
import './crm-theme-picker.css';

export type CrmThemePickerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: CrmThemeId;
  onChange: (id: CrmThemeId) => void;
  onReturnFocus?: () => void;
};

export default function CrmThemePicker({ open, onOpenChange, value, onChange, onReturnFocus }: CrmThemePickerProps) {
  const pickerId = useId();
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <CrmFormDialogContent className="crm-theme-picker-dialog max-w-3xl" onCloseAutoFocus={onReturnFocus ? event => {
      event.preventDefault();
      onReturnFocus();
    } : undefined}>
      <CrmFormDialogHeader>
        <DialogTitle>界面主题</DialogTitle>
        <DialogDescription>选择喜欢的配色，切换后立即预览。</DialogDescription>
      </CrmFormDialogHeader>
      <CrmFormDialogBody>
        <fieldset className="crm-theme-picker-grid" role="radiogroup" aria-labelledby={`${pickerId}-legend`}>
          <legend id={`${pickerId}-legend`} className="sr-only">选择界面主题</legend>
          {CRM_THEMES.map(theme => {
            const selected = value === theme.id;
            const descriptionId = `${pickerId}-${theme.id}-description`;
            const previewStyle = {
              '--ctp-accent': theme.swatch.accent,
              '--ctp-canvas': theme.swatch.canvas,
              '--ctp-rail': theme.swatch.rail,
              '--ctp-surface': theme.swatch.surface,
            } as CSSProperties;
            return <label key={theme.id} data-theme-id={theme.id} className={`crm-theme-picker-card${selected ? ' is-selected' : ''}`} style={previewStyle}>
              <span className="crm-theme-picker-card-heading">
                <span className="crm-theme-picker-name"><input type="radio" name={`${pickerId}-theme`} value={theme.id} checked={selected} aria-label={theme.name} aria-describedby={descriptionId} onChange={event => { if (event.currentTarget.checked) onChange(theme.id); }} /><span>{theme.name}</span></span>
                {selected && <span className="crm-theme-picker-current" aria-hidden="true"><Check size={13} />当前</span>}
              </span>
              <span id={descriptionId} className="crm-theme-picker-description">{theme.description}</span>
              <span className="crm-theme-picker-preview" aria-hidden="true">
                <span className="ctp-preview-rail"><span className="ctp-preview-logo" /><span className="ctp-preview-nav is-active" /><span className="ctp-preview-nav" /><span className="ctp-preview-nav" /></span>
                <span className="ctp-preview-main">
                  <span className="ctp-preview-toolbar"><span className="ctp-preview-title" /><span className="ctp-preview-action" /></span>
                  <span className="ctp-preview-table"><span className="ctp-preview-table-head" />{[0, 1, 2].map(row => <span className="ctp-preview-row" key={row}><span /><span /><span className="ctp-preview-status" /></span>)}</span>
                </span>
              </span>
            </label>;
          })}
        </fieldset>
      </CrmFormDialogBody>
      <CrmFormDialogFooter className="crm-theme-picker-footer">
        <p>仅影响当前账号在此浏览器的显示偏好</p>
        <Button type="button" onClick={() => onOpenChange(false)}>完成</Button>
      </CrmFormDialogFooter>
    </CrmFormDialogContent>
  </Dialog>;
}
