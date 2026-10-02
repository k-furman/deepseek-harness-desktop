import { describe, expect, it } from 'vitest';
import en from '../src/locales/en.json';
import ru from '../src/locales/ru.json';
import { errorText, languageFromLocale, localizeDocument } from '../src/i18n';

describe('localization', () => {
  it('supports regional Russian locales and defaults unsupported locales to English', () => {
    for (const locale of ['ru-RU', 'ru_RU.UTF-8', 'RU', 'ru']) expect(languageFromLocale(locale)).toBe('ru');
    for (const locale of ['de-DE', 'zh-CN', 'en-GB', 'C', '']) expect(languageFromLocale(locale)).toBe('en');
  });
  it('keeps both catalogs complete and translates static text and safe errors', () => {
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(ru.ui).sort()).toEqual(Object.keys(en.ui).sort());
    expect(Object.keys(ru.ui.errors).sort()).toEqual(Object.keys(en.ui.errors).sort());
    for (const section of ['menu', 'native'] as const) {
      expect(Object.keys(ru[section]).sort()).toEqual(Object.keys(en[section]).sort());
    }
    document.body.innerHTML = '<label data-i18n="serverAddress"></label>';
    localizeDocument('en');
    expect(document.querySelector('label')!.textContent).toBe('Server address');
    localizeDocument('ru');
    expect(document.querySelector('label')!.textContent).toBe('Адрес сервера');
    expect(errorText('unauthorized', 'en')).toContain('Authentication');
    expect(errorText('https://private/?token=secret', 'ru')).not.toContain('secret');
  });
});
