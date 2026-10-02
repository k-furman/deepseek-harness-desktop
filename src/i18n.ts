// Named JSON exports let Vite omit native menu/dialog strings from WebView JS.
import { ui as en } from './locales/en.json';
import { ui as ru } from './locales/ru.json';

export type Language = 'en' | 'ru';
export type LanguageSetting = 'system' | Language;
export type NativeError = keyof typeof en.errors;
const catalogs: Record<Language, typeof en> = { en, ru };

export const messages = (language: Language) => catalogs[language];
export const languageName = (language: Language) => language === 'ru' ? 'Русский' : 'English';
export const languageFromLocale = (locale: string): Language => /^ru(?:[-_.@]|$)/i.test(locale.trim()) ? 'ru' : 'en';
export const errorCode = (error: unknown): NativeError =>
  typeof error === 'string' && Object.hasOwn(en.errors, error) ? error as NativeError : 'unknown';

export function errorText(error: unknown, language: Language): string {
  const errors = messages(language).errors;
  return errors[errorCode(error)];
}

export function localizeDocument(language: Language, root: Document = document): void {
  root.documentElement.lang = language;
  const text = messages(language);
  for (const element of root.querySelectorAll<HTMLElement>('[data-i18n]')) {
    const key = element.dataset.i18n as keyof typeof text;
    const value = text[key];
    if (typeof value === 'string') element.textContent = value;
  }
}
