import './style.css';
import { cancelConnect, connect, errorMessage, getSnapshot, onSnapshot, onPreferences, openPreferences, type Snapshot } from './ipc';
import { errorCode, languageFromLocale, localizeDocument, messages } from './i18n';
import { renderSnapshot } from './view';

const input = document.querySelector<HTMLInputElement>('#server-url')!;
const status = document.querySelector<HTMLElement>('#status')!;
let last: Snapshot = { phase: 'idle', lastUrl: '', error: null, language: languageFromLocale(navigator.language) };
let active = true;
let ready = false;
let submitting = false;
let request = 0;
let snapshotVersion = 0;
let languageVersion = 0;
const listeners: (() => void)[] = [];
const dispose = () => {
  active = false;
  for (const unlisten of listeners.splice(0)) unlisten();
};
window.addEventListener('pagehide', dispose, { once: true });
localizeDocument(last.language);
status.textContent = messages(last.language).preparing;
const update = (snapshot: Snapshot) => {
  if (!active) return;
  last = snapshot;
  renderSnapshot(snapshot);
  if (snapshot.phase === 'error' || snapshot.phase === 'idle') input.focus();
};

document.querySelector<HTMLFormElement>('#connect-form')!.addEventListener('submit', (event) => {
  event.preventDefault();
  if (!active || !ready || submitting || last.phase === 'connecting') return;
  const address = input.value.trim();
  if (!address) { input.focus(); return; }
  submitting = true;
  const current = ++request;
  const version = snapshotVersion;
  // Lock immediately: native events arrive asynchronously, so a second Enter
  // must not create another remote webview. This also clears the pasted token.
  update({ ...last, phase: 'connecting', error: null });
  void connect(address).catch((error: unknown) => {
    if (current === request && version === snapshotVersion) {
      update({ ...last, phase: 'error', error: errorCode(error) });
    }
  }).finally(() => {
    if (current === request) submitting = false;
  });
});
document.querySelector('#cancel')!.addEventListener('click', () => {
  if (!active || !ready) return;
  const current = ++request;
  submitting = false;
  void cancelConnect().catch((error: unknown) => {
    if (active && current === request) status.textContent = errorMessage(error, last.language);
  });
});
document.querySelector('#settings')!.addEventListener('click', () => {
  void openPreferences().catch((error: unknown) => {
    if (active) status.textContent = errorMessage(error, last.language);
  });
});

async function initialize() {
  const unlisten = await onSnapshot((snapshot) => {
    ++snapshotVersion;
    update(snapshot);
  });
  if (!active) { unlisten(); return; }
  listeners.push(unlisten);
  const unlistenPreferences = await onPreferences((preferences) => {
    if (!active) return;
    ++languageVersion;
    last = { ...last, language: preferences.effectiveLanguage };
    renderSnapshot(last, document, false);
  });
  if (!active) { unlistenPreferences(); return; }
  listeners.push(unlistenPreferences);
  const version = snapshotVersion;
  const localeVersion = languageVersion;
  const snapshot = await getSnapshot();
  if (!active) return;
  if (version === snapshotVersion) {
    update({ ...snapshot, language: localeVersion === languageVersion ? snapshot.language : last.language });
  }
  ready = true;
  if (!input.disabled) input.focus();
}

try {
  await initialize();
} catch {
  if (active) {
    dispose();
    input.disabled = true;
    document.querySelector<HTMLButtonElement>('#connect')!.disabled = true;
    status.textContent = messages(last.language).openApp;
  }
}
