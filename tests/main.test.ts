import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { connect, getSnapshot, onPreferences, onSnapshot, type Preferences, type Snapshot } from '../src/ipc';

vi.mock('../src/ipc', async () => {
  const actual = await vi.importActual<typeof import('../src/ipc')>('../src/ipc');
  return {
    ...actual, connect: vi.fn(), cancelConnect: vi.fn(), getSnapshot: vi.fn(),
    onPreferences: vi.fn(), onSnapshot: vi.fn(), openPreferences: vi.fn(),
  };
});

const initial: Snapshot = { phase: 'idle', lastUrl: '', error: null, language: 'en' };
let notify: (snapshot: Snapshot) => void;
let notifyPreferences: (preferences: Preferences) => void;
const stopSnapshot = vi.fn();
const stopPreferences = vi.fn();
const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};
const submit = () => document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));

beforeEach(() => {
  vi.resetModules();
  stopSnapshot.mockReset();
  stopPreferences.mockReset();
  vi.mocked(connect).mockReset().mockResolvedValue(undefined);
  vi.mocked(getSnapshot).mockReset().mockResolvedValue(initial);
  vi.mocked(onSnapshot).mockReset().mockImplementation(async (handler) => {
    notify = handler;
    return stopSnapshot;
  });
  vi.mocked(onPreferences).mockReset().mockImplementation(async (handler) => {
    notifyPreferences = handler;
    return stopPreferences;
  });
  document.body.innerHTML = `<form id="connect-form"><input id="server-url" disabled>
    <button id="connect" disabled></button><button id="cancel" type="button" hidden></button></form>
    <div id="status"></div><button id="settings"></button>`;
});

afterEach(() => { window.dispatchEvent(new Event('pagehide')); });

it('blocks duplicate submits immediately and clears a pasted token before native events arrive', async () => {
  const command = deferred<void>();
  vi.mocked(connect).mockReturnValue(command.promise);
  await import('../src/main');
  const input = document.querySelector<HTMLInputElement>('#server-url')!;
  input.value = 'localhost:3000/?token=private';
  submit();
  submit();
  expect(connect).toHaveBeenCalledExactlyOnceWith('localhost:3000/?token=private');
  expect(input.disabled).toBe(true);
  expect(input.value).not.toContain('private');
  command.resolve();
  await command.promise;
  submit();
  expect(connect).toHaveBeenCalledOnce();
});

it('does not let a startup read overwrite a newer native connection event', async () => {
  const snapshot = deferred<Snapshot>();
  vi.mocked(getSnapshot).mockReturnValue(snapshot.promise);
  const loading = import('../src/main');
  await vi.waitFor(() => expect(getSnapshot).toHaveBeenCalledOnce());
  notify({ ...initial, phase: 'connecting', lastUrl: 'http://localhost:3000/' });
  snapshot.resolve(initial);
  await loading;
  expect(document.querySelector<HTMLInputElement>('#server-url')!.disabled).toBe(true);
  expect(document.querySelector<HTMLInputElement>('#server-url')!.value).toBe('http://localhost:3000/');
  expect(document.querySelector<HTMLButtonElement>('#cancel')!.hidden).toBe(false);
});

it('keeps a language change received while loading the initial snapshot', async () => {
  const snapshot = deferred<Snapshot>();
  vi.mocked(getSnapshot).mockReturnValue(snapshot.promise);
  const loading = import('../src/main');
  await vi.waitFor(() => expect(getSnapshot).toHaveBeenCalledOnce());
  notifyPreferences({ language: 'ru', effectiveLanguage: 'ru', systemLanguage: 'en' });
  snapshot.resolve(initial);
  await loading;
  expect(document.documentElement.lang).toBe('ru');
});

it('keeps the native outcome when an older connect invocation rejects', async () => {
  const command = deferred<void>();
  vi.mocked(connect).mockReturnValue(command.promise);
  await import('../src/main');
  document.querySelector<HTMLInputElement>('#server-url')!.value = 'localhost:3000';
  submit();
  notify({ ...initial, phase: 'connected', lastUrl: 'http://localhost:3000/' });
  command.reject('openWindow');
  await command.promise.catch(() => {});
  expect(document.querySelector('#status')!.textContent).toBe('');
  expect(document.querySelector<HTMLButtonElement>('#cancel')!.hidden).toBe(true);
});

it('releases earlier subscriptions when later initialization fails', async () => {
  vi.mocked(onPreferences).mockRejectedValue('unavailable');
  await import('../src/main');
  expect(stopSnapshot).toHaveBeenCalledOnce();
  expect(document.querySelector<HTMLInputElement>('#server-url')!.disabled).toBe(true);
  notify({ ...initial, phase: 'connected' });
  expect(document.querySelector<HTMLInputElement>('#server-url')!.disabled).toBe(true);
});

it('unsubscribes immediately if the page disappears during listener registration', async () => {
  const subscription = deferred<() => void>();
  vi.mocked(onSnapshot).mockReturnValue(subscription.promise);
  const loading = import('../src/main');
  await vi.waitFor(() => expect(onSnapshot).toHaveBeenCalledOnce());
  window.dispatchEvent(new Event('pagehide'));
  subscription.resolve(stopSnapshot);
  await loading;
  expect(stopSnapshot).toHaveBeenCalledOnce();
  expect(onPreferences).not.toHaveBeenCalled();
  expect(getSnapshot).not.toHaveBeenCalled();
});
