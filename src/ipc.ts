import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { errorText, type Language, type LanguageSetting, type NativeError } from './i18n';

export interface Snapshot {
  phase: 'idle' | 'connecting' | 'connected' | 'error';
  lastUrl: string;
  error: NativeError | null;
  language: Language;
}

export interface Preferences {
  language: LanguageSetting;
  effectiveLanguage: Language;
  systemLanguage: Language;
}

export const getSnapshot = () => invoke<Snapshot>('get_snapshot');
export const connect = (address: string) => invoke<void>('connect', { address });
export const cancelConnect = () => invoke<void>('cancel_connect');
export const openPreferences = () => invoke<void>('open_preferences');
export const getPreferences = () => invoke<Preferences>('get_preferences');
export const setLanguage = (language: LanguageSetting) => invoke<Preferences>('set_language', { language });
export const closePreferences = () => invoke<void>('close_preferences');
export const onPreferences = (callback: (preferences: Preferences) => void) =>
  listen<Preferences>('preferences-changed', (event) => callback(event.payload));
export const onSnapshot = (callback: (snapshot: Snapshot) => void) =>
  listen<Snapshot>('connection-state', (event) => callback(event.payload));

export const errorMessage = (error: unknown, language: Language = 'en') => errorText(error, language);
