export type SettingsSaveFeedback = { phase: 'saving' | 'success' | 'error'; message: string };

/** A successful notice follows the existing remote-save promise, never a click. */
export async function trackSettingsSave(label: string, save: () => Promise<void>, notify: (feedback: SettingsSaveFeedback) => void) {
  notify({ phase: 'saving', message: `正在保存${label}…` });
  try {
    await save();
    notify({ phase: 'success', message: `${label}已保存` });
    return true;
  } catch (error) {
    notify({ phase: 'error', message: error instanceof Error ? error.message : `${label}保存未完成，请重试` });
    return false;
  }
}
