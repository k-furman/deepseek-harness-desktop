import type { Snapshot } from './ipc';
import { errorText, localizeDocument, messages } from './i18n';

export function renderSnapshot(snapshot: Snapshot, root: Document = document, replaceAddress = true): void {
  localizeDocument(snapshot.language, root);
  const text = messages(snapshot.language);
  const input = root.querySelector<HTMLInputElement>('#server-url')!;
  const button = root.querySelector<HTMLButtonElement>('#connect')!;
  const cancel = root.querySelector<HTMLButtonElement>('#cancel')!;
  const status = root.querySelector<HTMLElement>('#status')!;
  const busy = snapshot.phase === 'connecting';
  input.disabled = busy;
  button.disabled = busy;
  cancel.hidden = !busy;
  button.textContent = busy ? text.connecting : text.connect;
  root.querySelector('form')?.setAttribute('aria-busy', String(busy));
  status.classList.toggle('error', snapshot.phase === 'error');
  status.textContent = snapshot.error ? errorText(snapshot.error, snapshot.language) : (busy ? text.opening : '');
  // Clear the pasted launch token after submission and after any native transition.
  if (replaceAddress) input.value = snapshot.lastUrl;
}
