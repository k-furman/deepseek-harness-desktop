import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { closePreferences, getPreferences, onPreferences, setLanguage, type Preferences } from '../src/ipc';

vi.mock('../src/ipc', async () => {
  const actual = await vi.importActual<typeof import('../src/ipc')>('../src/ipc');
  return { ...actual, closePreferences: vi.fn(), getPreferences: vi.fn(), onPreferences: vi.fn(), setLanguage: vi.fn() };
});

const initial: Preferences = { language: 'system', effectiveLanguage: 'en', systemLanguage: 'en' };
let notify: (preferences: Preferences) => void;
const stopPreferences = vi.fn();
const deferred = () => {
  let resolve!: (preferences: Preferences) => void;
  const promise = new Promise<Preferences>((done) => { resolve = done; });
  return { promise, resolve };
};

beforeEach(() => {
  vi.resetModules();
  stopPreferences.mockReset();
  vi.mocked(closePreferences).mockReset().mockResolvedValue(undefined);
  vi.mocked(setLanguage).mockReset();
  vi.mocked(getPreferences).mockReset().mockResolvedValue(initial);
  vi.mocked(onPreferences).mockReset().mockImplementation(async (handler) => {
    notify = handler;
    return stopPreferences;
  });
  document.body.innerHTML = `<h1 data-i18n="settings"></h1>
    <select id="language" disabled><option value="system"></option>
    <option value="en">English</option><option value="ru">Русский</option></select>
    <div id="preference-status"></div><button id="close-preferences"></button>`;
});

afterEach(() => { window.dispatchEvent(new Event('pagehide')); });

it('keeps the native selector usable, saves rapid choices in order and waits before closing', async () => {
  const first = deferred();
  const second = deferred();
  vi.mocked(setLanguage).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  await import('../src/preferences');
  const select = document.querySelector<HTMLSelectElement>('#language')!;
  select.value = 'ru';
  select.dispatchEvent(new Event('change'));
  await vi.waitFor(() => expect(setLanguage).toHaveBeenCalledWith('ru'));
  expect(select.disabled).toBe(false);
  select.value = 'en';
  select.dispatchEvent(new Event('change'));
  notify({ ...initial, language: 'ru', effectiveLanguage: 'ru' });
  expect(select.value).toBe('en');
  document.querySelector<HTMLButtonElement>('#close-preferences')!.click();
  expect(closePreferences).not.toHaveBeenCalled();
  first.resolve({ ...initial, language: 'ru', effectiveLanguage: 'ru' });
  await vi.waitFor(() => expect(setLanguage).toHaveBeenLastCalledWith('en'));
  expect(closePreferences).not.toHaveBeenCalled();
  second.resolve({ ...initial, language: 'en' });
  await vi.waitFor(() => expect(closePreferences).toHaveBeenCalledOnce());
  expect(select.value).toBe('en');
  expect(select.disabled).toBe(false);
  expect(document.documentElement.lang).toBe('en');
  expect(document.querySelector('#preference-status')!.textContent).toBe('Saved');
});

it('restores the saved choice and shows a translated error when saving fails', async () => {
  vi.mocked(setLanguage).mockRejectedValue('saveSettings');
  await import('../src/preferences');
  const select = document.querySelector<HTMLSelectElement>('#language')!;
  select.value = 'ru';
  select.dispatchEvent(new Event('change'));
  await vi.waitFor(() => expect(document.querySelector('#preference-status')!.textContent).toContain('Could not save settings'));
  expect(select.value).toBe('system');
  expect(select.disabled).toBe(false);
});

it('does not reset a newer choice or show an old error after a delayed recovery read', async () => {
  const recovery = deferred();
  const second = deferred();
  vi.mocked(getPreferences).mockResolvedValueOnce(initial).mockReturnValueOnce(recovery.promise);
  vi.mocked(setLanguage).mockRejectedValueOnce('saveSettings').mockReturnValueOnce(second.promise);
  await import('../src/preferences');
  const select = document.querySelector<HTMLSelectElement>('#language')!;
  select.value = 'ru';
  select.dispatchEvent(new Event('change'));
  await vi.waitFor(() => expect(getPreferences).toHaveBeenCalledTimes(2));
  select.value = 'en';
  select.dispatchEvent(new Event('change'));
  recovery.resolve(initial);
  await vi.waitFor(() => expect(setLanguage).toHaveBeenLastCalledWith('en'));
  expect(select.value).toBe('en');
  expect(document.querySelector('#preference-status')!.textContent).toBe('');
  expect(document.querySelector('#preference-status')!.classList.contains('error')).toBe(false);
  second.resolve({ ...initial, language: 'en' });
  await vi.waitFor(() => expect(document.querySelector('#preference-status')!.textContent).toBe('Saved'));
});

it('waits for changes queued after Close and coalesces repeated close requests', async () => {
  const first = deferred();
  const second = deferred();
  vi.mocked(setLanguage).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  await import('../src/preferences');
  const select = document.querySelector<HTMLSelectElement>('#language')!;
  select.value = 'ru';
  select.dispatchEvent(new Event('change'));
  await vi.waitFor(() => expect(setLanguage).toHaveBeenCalledWith('ru'));
  document.querySelector<HTMLButtonElement>('#close-preferences')!.click();
  document.querySelector<HTMLButtonElement>('#close-preferences')!.click();
  select.value = 'en';
  select.dispatchEvent(new Event('change'));
  first.resolve({ ...initial, language: 'ru', effectiveLanguage: 'ru' });
  await vi.waitFor(() => expect(setLanguage).toHaveBeenLastCalledWith('en'));
  expect(closePreferences).not.toHaveBeenCalled();
  second.resolve({ ...initial, language: 'en' });
  await vi.waitFor(() => expect(closePreferences).toHaveBeenCalledOnce());
});

it('uses a newer event instead of a stale startup read and updates idle selections', async () => {
  const snapshot = deferred();
  vi.mocked(getPreferences).mockReturnValue(snapshot.promise);
  const loading = import('../src/preferences');
  await vi.waitFor(() => expect(getPreferences).toHaveBeenCalledOnce());
  notify({ ...initial, language: 'ru', effectiveLanguage: 'ru' });
  snapshot.resolve(initial);
  await loading;
  expect(document.querySelector<HTMLSelectElement>('#language')!.value).toBe('ru');
  expect(document.documentElement.lang).toBe('ru');
  notify(initial);
  expect(document.querySelector<HTMLSelectElement>('#language')!.value).toBe('system');
});

it('removes the native listener after failed startup and on teardown only once', async () => {
  vi.mocked(getPreferences).mockRejectedValue('unavailable');
  await import('../src/preferences');
  expect(stopPreferences).toHaveBeenCalledOnce();
  window.dispatchEvent(new Event('pagehide'));
  expect(stopPreferences).toHaveBeenCalledOnce();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  expect(closePreferences).not.toHaveBeenCalled();
});
