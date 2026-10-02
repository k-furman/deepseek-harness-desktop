import './style.css';
import { closePreferences, errorMessage, getPreferences, onPreferences, setLanguage, type Preferences } from './ipc';
import { languageFromLocale, languageName, localizeDocument, messages, type LanguageSetting } from './i18n';

const select = document.querySelector<HTMLSelectElement>('#language')!;
const status = document.querySelector<HTMLElement>('#preference-status')!;
let language = languageFromLocale(navigator.language);
let active = true;
let preferenceVersion = 0;
let pendingSaves = 0;
let closing = false;
let unlisten: (() => void) | undefined;
localizeDocument(language);
status.textContent = messages(language).preparing;

const render = (preferences: Preferences, preserveSelection = false) => {
  if (!active) return;
  language = preferences.effectiveLanguage;
  localizeDocument(language);
  if (!preserveSelection) select.value = preferences.language;
  select.querySelector<HTMLOptionElement>('[value="system"]')!.textContent =
    `${messages(language).systemLanguage} (${languageName(preferences.systemLanguage)})`;
};

let changeSequence = 0;
let saves = Promise.resolve();
select.addEventListener('change', () => {
  if (!active || select.disabled) return;
  const requested = select.value as LanguageSetting;
  const sequence = ++changeSequence;
  ++pendingSaves;
  status.textContent = '';
  status.classList.remove('error');
  // WebKitGTK can dispatch change before its native select popup closes.
  // Disabling or resetting it here cancels the highlighted choice. Keep the
  // control usable and save changes in order, including rapid keyboard input.
  saves = saves.then(async () => {
    try {
      if (!active) return;
      const preferences = await setLanguage(requested);
      if (active && sequence === changeSequence) {
        render(preferences, true);
        status.textContent = messages(language).saved;
      }
    } catch (error) {
      if (!active || sequence !== changeSequence) return;
      let preferences: Preferences | undefined;
      try { preferences = await getPreferences(); } catch { /* Keep the last resolved language. */ }
      // A new choice can arrive while the recovery read is in flight.
      if (!active || sequence !== changeSequence) return;
      if (preferences) render(preferences);
      status.textContent = errorMessage(error, language);
      status.classList.add('error');
    } finally {
      --pendingSaves;
    }
  });
});

const close = () => {
  if (!active || closing) return;
  closing = true;
  void (async () => {
    // Include changes made while an earlier save is still finishing.
    let pending: Promise<void>;
    do {
      pending = saves;
      await pending;
    } while (pending !== saves);
    if (active) await closePreferences();
  })().catch((error: unknown) => {
    if (!active) return;
    closing = false;
    status.textContent = errorMessage(error, language);
    status.classList.add('error');
  });
};
const onKeydown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !select.disabled) close(); };
document.querySelector('#close-preferences')!.addEventListener('click', close);
window.addEventListener('keydown', onKeydown);
window.addEventListener('pagehide', () => {
  active = false;
  unlisten?.();
  unlisten = undefined;
  window.removeEventListener('keydown', onKeydown);
}, { once: true });

async function initialize() {
  const stopListening = await onPreferences((preferences) => {
    ++preferenceVersion;
    render(preferences, pendingSaves > 0);
  });
  if (!active) { stopListening(); return; }
  unlisten = stopListening;
  const version = preferenceVersion;
  const preferences = await getPreferences();
  if (!active) return;
  if (version === preferenceVersion) render(preferences);
  select.disabled = false;
  status.textContent = '';
}

try {
  await initialize();
} catch {
  unlisten?.();
  unlisten = undefined;
  if (active) {
    status.textContent = messages(language).settingsUnavailable;
    status.classList.add('error');
  }
}
